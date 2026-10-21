"""D1: the untracked regional catalogs are handled explicitly, never silently.

Behaviour is asserted for whichever situation this checkout is in, so the same test
is meaningful on a clean clone (artifacts absent) and on a provisioned developer
machine or the gate (artifacts present).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from evals.catalog_guard import (
    CORRIDORS,
    REQUIRE_ENV,
    catalogs_required,
    missing_catalogs,
    required_catalog_files,
)

BACKEND = Path(__file__).parent.parent
MARKED_TEST = "evals/test_recompute_endpoint.py::test_catalog_poi_lookup_reuses_active_snapshot"


def _pytest(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != REQUIRE_ENV}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", MARKED_TEST, "-rs"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )


def test_all_six_corridors_are_required_and_named_from_the_region_table() -> None:
    names = {p.name for p in required_catalog_files()}
    assert len(CORRIDORS) == len(names) == 6
    assert all(n.startswith("active_") and n.endswith("-core.json") for n in names)


def test_missing_catalogs_reports_every_absent_file(tmp_path: Path) -> None:
    assert len(missing_catalogs(tmp_path)) == 6
    (tmp_path / "catalogs").mkdir()
    for path in required_catalog_files(tmp_path):
        path.write_text("{}")
    assert missing_catalogs(tmp_path) == []


def test_require_flag_is_exactly_one() -> None:
    assert catalogs_required({REQUIRE_ENV: "1"})
    assert not catalogs_required({REQUIRE_ENV: "true"})
    assert not catalogs_required({})


def test_default_run_skips_visibly_when_absent_and_runs_when_present() -> None:
    result = _pytest({})
    if missing_catalogs():
        assert result.returncode == 0
        assert "1 skipped" in result.stdout
        assert "regional catalog artifacts" in result.stdout  # the reason is visible
    else:
        assert result.returncode == 0 and "1 passed" in result.stdout


def test_strict_run_aborts_when_absent_and_passes_when_present() -> None:
    result = _pytest({REQUIRE_ENV: "1"})
    if missing_catalogs():
        assert result.returncode == 2
        assert REQUIRE_ENV in result.stdout + result.stderr
    else:
        assert result.returncode == 0 and "1 passed" in result.stdout


def test_make_gate_runs_pytest_in_strict_catalog_mode() -> None:
    makefile = (BACKEND.parent / "Makefile").read_text()
    gate = makefile.split("gate:", 1)[1].split("\n\n", 1)[0]
    assert f"{REQUIRE_ENV}=1" in gate and "pytest" in gate
