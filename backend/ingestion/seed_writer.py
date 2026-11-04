"""Journaled, recoverable writes of a *set* of seed files, with exact-byte rollback.

Several seed files change together (a card insert and its rules, say), and the operating system
can replace each file atomically but **not all of them as one transaction**. This module makes
that limit safe instead of pretending it away:

1. A journal (outside the seed directory) records every file's prior and intended SHA-256
   *before* anything is touched.
2. The exact prior bytes of every file are copied to a backup and verified.
3. The new bytes are written beside the originals as temp files and verified.
4. The temp files are renamed over the originals one at a time (each rename is atomic).
5. The journal is marked committed.

An interruption at any point leaves a journal in a non-terminal state. While one exists for a
seed directory no further apply is allowed, and ``recover`` resolves it by the rules below, so a
mixed set of files is never accepted silently:

* before the first rename: nothing changed; temp files are removed (``aborted``);
* during the renames: if **every** file already holds its new bytes the apply is completed;
  otherwise every already-replaced file is restored from its verified backup
  (``rolled_back_by_recovery``);
* during a rollback: the restore is finished.

``rollback`` restores the exact prior bytes of a committed apply, but only if every file still
holds exactly what that apply wrote; a later, unrelated change is never overwritten.

The only ``os`` features used are ``replace`` and ``fsync`` (an AST test pins that).
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

TERMINAL_STATES: Final = frozenset(
    {"committed", "rolled_back", "aborted", "rolled_back_by_recovery"}
)
Checkpoint = Callable[[str], None]


class SeedWriteError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_durable(path: Path, data: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_durable(source: Path, target: Path) -> None:
    os.replace(source, target)


@dataclass(frozen=True)
class FileChange:
    filename: str
    prior_sha256: str
    new_sha256: str


@dataclass(frozen=True)
class JournalSummary:
    apply_id: str
    state: str
    seeds_dir: str
    bundle_sha256: str
    files: tuple[FileChange, ...]


class SeedWriter:
    def __init__(self, *, state_dir: Path, now: Callable[[], datetime]) -> None:
        self.state_dir = state_dir
        self.journal_dir = state_dir / "journals"
        self.backup_dir = state_dir / "backups"
        self.lock_dir = state_dir / "locks"
        self.now = now
        self._held: set[str] = set()
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ exclusive access

    @contextmanager
    def locked(self, seeds_dir: Path) -> Iterator[None]:
        """Exclusive use of one seed directory, across processes, for the whole operation.

        The lock is a file created with exclusive-create semantics (atomic on a local file
        system) and removed when the operation ends, however it ends. A process killed outright
        leaves the file behind; that is deliberate (we cannot tell a dead process from a live one
        without more of ``os`` than this module is allowed), and the refusal names the file so an
        operator who has confirmed nothing is running can remove it. Re-entrant within one
        writer instance.
        """
        key = hashlib.sha256(str(seeds_dir.resolve()).encode()).hexdigest()[:24]
        if key in self._held:
            yield
            return
        path = self.lock_dir / f"{key}.lock"
        try:
            with path.open("x", encoding="utf-8") as handle:
                handle.write(
                    json.dumps({"seeds_dir": str(seeds_dir), "at": self.now().isoformat()})
                )
        except FileExistsError as error:
            raise SeedWriteError(
                "locked",
                f"another operation holds this seed directory (lock file {path}); if no other "
                "process is running, a previous one was killed and that file can be removed",
            ) from error
        self._held.add(key)
        try:
            yield
        finally:
            self._held.discard(key)
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------ journal

    def _journal_path(self, apply_id: str) -> Path:
        if not apply_id or any(ch in apply_id for ch in "/\\") or apply_id.startswith("."):
            raise SeedWriteError("invalid_apply_id", f"invalid apply id {apply_id!r}")
        return self.journal_dir / f"{apply_id}.json"

    def _save(self, journal: dict[str, Any], state: str) -> None:
        journal["state"] = state
        journal.setdefault("history", []).append({"state": state, "at": self.now().isoformat()})
        path = self._journal_path(journal["apply_id"])
        temp = path.with_suffix(".json.tmp")
        _write_durable(temp, json.dumps(journal, sort_keys=True, indent=2).encode())
        _replace_durable(temp, path)

    def load(self, apply_id: str) -> dict[str, Any]:
        path = self._journal_path(apply_id)
        if not path.exists():
            raise SeedWriteError("unknown_apply", f"no journal for apply {apply_id!r}")
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    def summary(self, apply_id: str) -> JournalSummary:
        journal = self.load(apply_id)
        return JournalSummary(
            apply_id=apply_id,
            state=str(journal["state"]),
            seeds_dir=str(journal["seeds_dir"]),
            bundle_sha256=str(journal["bundle_sha256"]),
            files=tuple(FileChange(**item) for item in journal["files"]),
        )

    def open_journals(self, seeds_dir: Path) -> list[JournalSummary]:
        """Non-terminal journals for this seed directory: an interrupted operation."""
        found: list[JournalSummary] = []
        for path in sorted(self.journal_dir.glob("*.json")):
            summary = self.summary(path.stem)
            if summary.state not in TERMINAL_STATES and Path(summary.seeds_dir) == seeds_dir:
                found.append(summary)
        return found

    # ------------------------------------------------------------------ apply

    def apply(
        self,
        *,
        seeds_dir: Path,
        apply_id: str,
        bundle_sha256: str,
        contents: dict[str, bytes],
        expected_priors: dict[str, str] | None = None,
        checkpoint: Checkpoint | None = None,
    ) -> JournalSummary:
        """Replace the named seed files with ``contents``; recoverable at every step.

        ``expected_priors`` (file name -> SHA-256 the caller planned against) is checked under
        the lock against what is on disk now, so an edit made after planning is never silently
        overwritten.
        """
        with self.locked(seeds_dir):
            return self._apply_locked(
                seeds_dir, apply_id, bundle_sha256, contents, expected_priors, checkpoint
            )

    def _apply_locked(
        self,
        seeds_dir: Path,
        apply_id: str,
        bundle_sha256: str,
        contents: dict[str, bytes],
        expected_priors: dict[str, str] | None,
        checkpoint: Checkpoint | None,
    ) -> JournalSummary:
        step = checkpoint or (lambda _name: None)
        if self.open_journals(seeds_dir):
            raise SeedWriteError(
                "incomplete_apply",
                "an earlier apply on this seed directory did not finish: run recover first",
            )
        if self._journal_path(apply_id).exists():
            raise SeedWriteError("apply_exists", f"apply id {apply_id!r} was already used")
        priors: dict[str, bytes] = {}
        for name in sorted(contents):
            target = seeds_dir / name
            if "/" in name or not target.is_file():
                raise SeedWriteError("unknown_seed_file", f"{name!r} is not a seed file here")
            priors[name] = target.read_bytes()
        for name, expected in (expected_priors or {}).items():
            if name not in priors or _sha(priors[name]) != expected:
                raise SeedWriteError(
                    "seeds_changed",
                    f"{name} no longer holds the bytes this apply was planned against; "
                    "something changed it since planning, so nothing was written",
                )
        journal: dict[str, Any] = {
            "version": 1,
            "apply_id": apply_id,
            "seeds_dir": str(seeds_dir),
            "bundle_sha256": bundle_sha256,
            "files": [
                {
                    "filename": name,
                    "prior_sha256": _sha(priors[name]),
                    "new_sha256": _sha(contents[name]),
                }
                for name in sorted(contents)
            ],
            "history": [],
        }
        self._save(journal, "planned")
        step("planned")
        backup = self.backup_dir / apply_id
        backup.mkdir(parents=True, exist_ok=True)
        for name, data in priors.items():
            _write_durable(backup / name, data)
            if sha256_file(backup / name) != _sha(data):
                raise SeedWriteError("backup_failed", f"backup of {name} did not verify")
        self._save(journal, "backed_up")
        step("backed_up")
        for name, data in contents.items():
            temp = seeds_dir / f"{name}.apply-{apply_id}.tmp"
            _write_durable(temp, data)
            if sha256_file(temp) != _sha(data):
                raise SeedWriteError("stage_failed", f"staged copy of {name} did not verify")
        self._save(journal, "staged")
        step("staged")
        self._save(journal, "committing")
        step("committing")
        for index, name in enumerate(sorted(contents), start=1):
            _replace_durable(seeds_dir / f"{name}.apply-{apply_id}.tmp", seeds_dir / name)
            step(f"replaced:{index}")
        self._save(journal, "committed")
        step("committed")
        return self.summary(apply_id)

    # ------------------------------------------------------------------ recovery

    def recover(self, seeds_dir: Path) -> list[tuple[str, str]]:
        """Resolve every interrupted operation on ``seeds_dir``; returns (apply_id, outcome)."""
        outcomes: list[tuple[str, str]] = []
        with self.locked(seeds_dir):
            for summary in self.open_journals(seeds_dir):
                outcomes.append((summary.apply_id, self._recover_one(summary)))
        return outcomes

    def _recover_one(self, summary: JournalSummary) -> str:
        journal = self.load(summary.apply_id)
        seeds_dir = Path(summary.seeds_dir)
        by_name = {change.filename: change for change in summary.files}
        current = {name: sha256_file(seeds_dir / name) for name in by_name}
        for name, change in by_name.items():
            if current[name] not in {change.prior_sha256, change.new_sha256}:
                raise SeedWriteError(
                    "unrecognised_seed_state",
                    f"{name} holds neither its prior nor its new bytes; it was changed by "
                    "something else, so recovery will not touch it",
                )
        if summary.state == "rolling_back":
            self._restore(summary, journal)
            self._remove_temps(summary)
            self._save(journal, "rolled_back")
            return "rolled_back"
        replaced = [n for n, c in by_name.items() if current[n] == c.new_sha256]
        if summary.state == "committing" and len(replaced) == len(by_name):
            self._remove_temps(summary)
            self._save(journal, "committed")
            return "committed"
        for name in replaced:
            self._restore_one(summary, by_name[name])
        self._remove_temps(summary)
        if summary.state == "committing":
            self._save(journal, "rolled_back_by_recovery")
            return "rolled_back_by_recovery"
        self._save(journal, "aborted")
        return "aborted"

    def _remove_temps(self, summary: JournalSummary) -> None:
        for change in summary.files:
            seeds = Path(summary.seeds_dir)
            (seeds / f"{change.filename}.apply-{summary.apply_id}.tmp").unlink(missing_ok=True)
            (seeds / f"{change.filename}.rollback-{summary.apply_id}.tmp").unlink(missing_ok=True)

    def _backup_bytes(self, summary: JournalSummary, change: FileChange) -> bytes:
        path = self.backup_dir / summary.apply_id / change.filename
        if not path.is_file():
            raise SeedWriteError("backup_missing", f"backup of {change.filename} is missing")
        data = path.read_bytes()
        if _sha(data) != change.prior_sha256:
            raise SeedWriteError(
                "backup_corrupt", f"backup of {change.filename} does not match its recorded hash"
            )
        return data

    def _restore_one(self, summary: JournalSummary, change: FileChange) -> None:
        data = self._backup_bytes(summary, change)
        target = Path(summary.seeds_dir) / change.filename
        temp = target.with_name(f"{change.filename}.rollback-{summary.apply_id}.tmp")
        _write_durable(temp, data)
        _replace_durable(temp, target)
        if sha256_file(target) != change.prior_sha256:
            raise SeedWriteError("restore_failed", f"{change.filename} did not restore exactly")

    def _restore(self, summary: JournalSummary, journal: dict[str, Any]) -> None:
        del journal
        for change in summary.files:
            if sha256_file(Path(summary.seeds_dir) / change.filename) != change.prior_sha256:
                self._restore_one(summary, change)

    # ------------------------------------------------------------------ rollback

    def rollback(self, *, apply_id: str, checkpoint: Checkpoint | None = None) -> JournalSummary:
        """Restore the exact prior bytes of a committed apply, refusing if anything moved on."""
        summary = self.summary(apply_id)
        with self.locked(Path(summary.seeds_dir)):
            return self._rollback_locked(apply_id, checkpoint)

    def _rollback_locked(self, apply_id: str, checkpoint: Checkpoint | None) -> JournalSummary:
        step = checkpoint or (lambda _name: None)
        summary = self.summary(apply_id)
        if summary.state != "committed":
            raise SeedWriteError(
                "not_committed",
                f"apply {apply_id!r} is {summary.state}; only a committed apply can be rolled back",
            )
        seeds_dir = Path(summary.seeds_dir)
        if self.open_journals(seeds_dir):
            raise SeedWriteError(
                "incomplete_apply", "another operation on this seed directory is unfinished"
            )
        moved = [
            change.filename
            for change in summary.files
            if sha256_file(seeds_dir / change.filename) != change.new_sha256
        ]
        if moved:
            raise SeedWriteError(
                "changed_since_apply",
                f"{', '.join(moved)} no longer hold what this apply wrote (something changed "
                "them since); refusing to overwrite later changes",
            )
        for change in summary.files:
            self._backup_bytes(summary, change)  # verify every backup before touching anything
        journal = self.load(apply_id)
        self._save(journal, "rolling_back")
        step("rolling_back")
        for index, change in enumerate(summary.files, start=1):
            self._restore_one(summary, change)
            step(f"restored:{index}")
        self._save(journal, "rolled_back")
        return self.summary(apply_id)
