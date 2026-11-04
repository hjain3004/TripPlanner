"""Regressions for two FI3 operator-CLI defects found while running a real capture.

1. ``main()`` used ``env or {}``, so the real process environment never reached the
   production guard or the ``TRIPWISE_DATA_DIR`` fallback (and ``--data-dir`` was mandatory, so
   the fallback in ``resolve_data_dir`` was unreachable from the CLI).
2. ``add-curator`` stored ``created_at=now()``, so re-running it raised a raw
   ``ConflictingWriteError`` instead of succeeding for the same curator.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ingestion.contracts import CuratorRecord
from ingestion.review_server import LocalOnlyError, main
from ingestion.storage import FinancialIngestionStore

BACKEND = Path(__file__).resolve().parents[1]
ADD = ["add-curator", "--curator-id", "alice", "--display-name", "Alice"]


def _cli(args: list[str], **env: str) -> subprocess.CompletedProcess[str]:
    """Run the real CLI in a child process with the given environment variables set."""
    clean = {k: v for k, v in os.environ.items() if k not in {"TRIPWISE_ENV", "TRIPWISE_DATA_DIR"}}
    return subprocess.run(
        [sys.executable, "-m", "ingestion.review_server", *args],
        cwd=BACKEND,
        env={**clean, **env},
        capture_output=True,
        text=True,
        timeout=120,
    )


def _record(data: Path) -> CuratorRecord | None:
    return FinancialIngestionStore(data / "ingestion.sqlite").get_curator("alice")


def test_the_cli_refuses_to_run_when_the_process_environment_says_production(
    tmp_path: Path,
) -> None:
    data = tmp_path / "data"
    result = _cli([*ADD, "--data-dir", str(data)], TRIPWISE_ENV="production")
    assert result.returncode != 0
    assert "disabled in production" in result.stderr
    assert not data.exists()  # refused before touching anything


def test_the_cli_uses_tripwise_data_dir_when_no_flag_is_given(tmp_path: Path) -> None:
    root = tmp_path / "root"
    result = _cli(ADD, TRIPWISE_DATA_DIR=str(root))
    assert result.returncode == 0, result.stderr
    assert (root / "ingestion" / "ingestion.sqlite").is_file()


def test_a_data_directory_is_still_required_from_somewhere() -> None:
    result = _cli(ADD)
    assert result.returncode != 0
    assert "TRIPWISE_DATA_DIR" in result.stderr


def test_main_reads_the_real_environment_by_default_and_honours_an_injected_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = [*ADD, "--data-dir", str(tmp_path / "data")]
    monkeypatch.setenv("TRIPWISE_ENV", "production")
    with pytest.raises(LocalOnlyError):
        main(argv)  # env=None means os.environ, not an empty mapping
    monkeypatch.delenv("TRIPWISE_ENV")
    assert main(argv, env={}) == 0  # an explicitly injected (even empty) environment still wins


def test_add_curator_is_idempotent_for_the_same_curator_and_name(tmp_path: Path) -> None:
    argv = [*ADD, "--data-dir", str(tmp_path)]
    assert main(argv, env={}) == 0
    first = _record(tmp_path)
    assert first is not None
    assert main(argv, env={}) == 0  # previously: raw ConflictingWriteError
    assert _record(tmp_path) == first  # the original record, created_at included, is kept


def test_add_curator_with_a_different_name_exits_2_without_a_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*ADD, "--data-dir", str(tmp_path)], env={}) == 0
    first = _record(tmp_path)
    capsys.readouterr()
    other = ["add-curator", "--curator-id", "alice", "--display-name", "Mallory"]
    assert main([*other, "--data-dir", str(tmp_path)], env={}) == 2
    err = capsys.readouterr().err
    assert "alice" in err and "Alice" in err and "already registered" in err
    assert "Traceback" not in err
    assert _record(tmp_path) == first


def test_add_curator_survives_a_concurrent_registration_of_the_same_curator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Another process registers the curator between our lookup and our write."""
    assert main([*ADD, "--data-dir", str(tmp_path)], env={}) == 0
    real = FinancialIngestionStore.get_curator
    calls = {"n": 0}

    def first_lookup_misses(self: FinancialIngestionStore, curator_id: str) -> CuratorRecord | None:
        calls["n"] += 1
        return None if calls["n"] == 1 else real(self, curator_id)

    monkeypatch.setattr(FinancialIngestionStore, "get_curator", first_lookup_misses)
    assert main([*ADD, "--data-dir", str(tmp_path)], env={}) == 0
    assert calls["n"] >= 2
