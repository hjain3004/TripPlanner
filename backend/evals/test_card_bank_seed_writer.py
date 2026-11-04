"""The journaled multi-file seed writer: interruption, recovery and exact-byte rollback.

Files here are throwaway bytes in a temp directory. The claim under test is deliberately
narrow: several independent renames are NOT one atomic transaction, so every interruption
point must leave a journal that ``recover`` resolves to *all prior* or *all new* bytes, never a
silent mix, and a rollback restores exactly the bytes that were replaced.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ingestion.seed_writer import SeedWriteError, SeedWriter

NOW = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)
PRIOR = {"cards.yaml": b"- id: a\n  fee: 1\n", "reward_rules.yaml": b"- id: r\n"}
NEW = {"cards.yaml": b"- id: a\n  fee: 2\n- id: b\n", "reward_rules.yaml": b"- id: r\n- id: s\n"}


class Interrupted(BaseException):
    """A process killed mid-operation (BaseException so nothing 'handles' it)."""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Workspace:
    def __init__(self, root: Path) -> None:
        self.seeds = root / "seeds"
        self.seeds.mkdir()
        for name, data in PRIOR.items():
            (self.seeds / name).write_bytes(data)
        (self.seeds / "offers.yaml").write_bytes(b"- id: untouched\n")
        self.writer = SeedWriter(state_dir=root / "state", now=lambda: NOW)

    def contents(self) -> dict[str, bytes]:
        return {name: (self.seeds / name).read_bytes() for name in sorted(PRIOR)}

    def apply(self, apply_id: str = "apply-1", *, crash_at: str | None = None) -> None:
        def checkpoint(step: str) -> None:
            if step == crash_at:
                raise Interrupted(step)

        self.writer.apply(
            seeds_dir=self.seeds,
            apply_id=apply_id,
            bundle_sha256="b" * 64,
            contents=NEW,
            checkpoint=checkpoint,
        )


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path)


def test_a_clean_apply_replaces_the_files_and_a_rollback_restores_the_exact_bytes(
    ws: Workspace,
) -> None:
    ws.apply()
    assert ws.contents() == NEW
    summary = ws.writer.summary("apply-1")
    assert summary.state == "committed"
    assert {c.filename: (c.prior_sha256, c.new_sha256) for c in summary.files} == {
        name: (sha(PRIOR[name]), sha(NEW[name])) for name in PRIOR
    }
    assert (ws.seeds / "offers.yaml").read_bytes() == b"- id: untouched\n"
    assert not list(ws.seeds.glob("*.tmp"))
    ws.writer.rollback(apply_id="apply-1")
    assert ws.contents() == PRIOR  # exact bytes, not a re-serialization
    assert ws.writer.summary("apply-1").state == "rolled_back"
    states = [h["state"] for h in ws.writer.load("apply-1")["history"]]
    assert states == [
        "planned",
        "backed_up",
        "staged",
        "committing",
        "committed",
        "rolling_back",
        "rolled_back",
    ]


@pytest.mark.parametrize(
    ("crash_at", "outcome", "files"),
    [
        ("planned", "aborted", PRIOR),
        ("backed_up", "aborted", PRIOR),
        ("staged", "aborted", PRIOR),
        ("committing", "rolled_back_by_recovery", PRIOR),
        ("replaced:1", "rolled_back_by_recovery", PRIOR),  # a mixed pack, resolved to prior
        ("replaced:2", "committed", NEW),  # every file already new: completed, not undone
    ],
)
def test_every_interruption_point_recovers_to_all_prior_or_all_new_never_a_mix(
    ws: Workspace, crash_at: str, outcome: str, files: dict[str, bytes]
) -> None:
    with pytest.raises(Interrupted):
        ws.apply(crash_at=crash_at)
    # the interrupted operation blocks further applies until it is resolved
    with pytest.raises(SeedWriteError) as blocked:
        ws.apply("apply-2")
    assert blocked.value.code == "incomplete_apply"
    assert ws.writer.recover(ws.seeds) == [("apply-1", outcome)]
    assert ws.contents() == files
    assert not list(ws.seeds.glob("*.tmp"))
    assert not ws.writer.open_journals(ws.seeds)
    ws.apply("apply-2")  # the directory is usable again
    assert ws.contents() == NEW


def test_a_mixed_pack_is_visible_before_recovery_and_never_accepted(ws: Workspace) -> None:
    with pytest.raises(Interrupted):
        ws.apply(crash_at="replaced:1")
    on_disk = ws.contents()
    assert on_disk["cards.yaml"] == NEW["cards.yaml"]  # really mixed before recovery
    assert on_disk["reward_rules.yaml"] == PRIOR["reward_rules.yaml"]
    assert ws.writer.open_journals(ws.seeds)  # and the journal says so
    with pytest.raises(SeedWriteError) as refused:
        ws.writer.rollback(apply_id="apply-1")
    assert refused.value.code == "not_committed"


def test_a_rollback_refuses_to_overwrite_a_later_change_and_touches_nothing(ws: Workspace) -> None:
    ws.apply()
    later = b"- id: a\n  fee: 99  # someone else's edit\n"
    (ws.seeds / "cards.yaml").write_bytes(later)
    before = ws.contents()
    with pytest.raises(SeedWriteError) as refused:
        ws.writer.rollback(apply_id="apply-1")
    assert refused.value.code == "changed_since_apply" and "cards.yaml" in str(refused.value)
    assert ws.contents() == before  # not even the unchanged file was rolled back
    assert ws.writer.summary("apply-1").state == "committed"


def test_a_corrupt_backup_stops_a_rollback_before_any_file_is_touched(ws: Workspace) -> None:
    ws.apply()
    (ws.writer.backup_dir / "apply-1" / "reward_rules.yaml").write_bytes(b"tampered")
    with pytest.raises(SeedWriteError) as refused:
        ws.writer.rollback(apply_id="apply-1")
    assert refused.value.code == "backup_corrupt"
    assert ws.contents() == NEW


def test_a_missing_backup_stops_a_rollback(ws: Workspace) -> None:
    ws.apply()
    (ws.writer.backup_dir / "apply-1" / "cards.yaml").unlink()
    with pytest.raises(SeedWriteError) as refused:
        ws.writer.rollback(apply_id="apply-1")
    assert refused.value.code == "backup_missing" and ws.contents() == NEW


@pytest.mark.parametrize("crash_at", ["rolling_back", "restored:1"])
def test_an_interrupted_rollback_is_finished_by_recovery(ws: Workspace, crash_at: str) -> None:
    ws.apply()

    def checkpoint(step: str) -> None:
        if step == crash_at:
            raise Interrupted(step)

    with pytest.raises(Interrupted):
        ws.writer.rollback(apply_id="apply-1", checkpoint=checkpoint)
    assert ws.writer.recover(ws.seeds) == [("apply-1", "rolled_back")]
    assert ws.contents() == PRIOR
    assert not list(ws.seeds.glob("*.tmp"))


def test_recovery_will_not_touch_a_file_that_holds_foreign_bytes(ws: Workspace) -> None:
    with pytest.raises(Interrupted):
        ws.apply(crash_at="replaced:1")
    (ws.seeds / "reward_rules.yaml").write_bytes(b"neither prior nor new\n")
    with pytest.raises(SeedWriteError) as refused:
        ws.writer.recover(ws.seeds)
    assert refused.value.code == "unrecognised_seed_state"
    assert (ws.seeds / "reward_rules.yaml").read_bytes() == b"neither prior nor new\n"


def test_only_existing_seed_files_can_be_written_and_apply_ids_are_single_use(
    ws: Workspace,
) -> None:
    for bad in ("../escape.yaml", "nope.yaml"):
        with pytest.raises(SeedWriteError) as refused:
            ws.writer.apply(
                seeds_dir=ws.seeds, apply_id="x1", bundle_sha256="b" * 64, contents={bad: b"x"}
            )
        assert refused.value.code == "unknown_seed_file"
    ws.apply()
    with pytest.raises(SeedWriteError) as reused:
        ws.apply()
    assert reused.value.code == "apply_exists"
    with pytest.raises(SeedWriteError) as invalid:
        ws.writer.summary("../evil")
    assert invalid.value.code == "invalid_apply_id"


def test_a_second_apply_stacks_and_must_be_rolled_back_first(ws: Workspace) -> None:
    ws.apply("apply-1")
    third = {"cards.yaml": b"- id: a\n  fee: 3\n"}
    ws.writer.apply(seeds_dir=ws.seeds, apply_id="apply-2", bundle_sha256="c" * 64, contents=third)
    with pytest.raises(SeedWriteError) as refused:
        ws.writer.rollback(apply_id="apply-1")  # apply-2 changed cards.yaml since
    assert refused.value.code == "changed_since_apply"
    ws.writer.rollback(apply_id="apply-2")
    ws.writer.rollback(apply_id="apply-1")
    assert ws.contents() == PRIOR
