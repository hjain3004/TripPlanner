"""D1: all mutable runtime state can be relocated into one explicit data directory.

Paths are resolved at import time (they are module constants other code imports by
name), so each case runs in a fresh interpreter.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent

_CODE = (
    "import accounts.db as a, api.main as m, core.db as c; "
    "print(c.DB_PATH); print(a.ACCOUNTS_DB_PATH); print(m.TRACE_DIR)"
)


def _resolve(**env_overrides: str) -> list[Path]:
    env = {k: v for k, v in os.environ.items() if k != "TRIPWISE_DATA_DIR"}
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", _CODE],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return [Path(line) for line in out[:3]]


def test_default_locations_are_unchanged_for_development_and_tests() -> None:
    kb, accounts, traces = _resolve()
    assert kb == BACKEND / "core" / "tripwise.sqlite"
    assert accounts == BACKEND / "accounts" / "accounts.sqlite"
    assert traces == BACKEND / ".traces"


def test_data_dir_relocates_every_mutable_store(tmp_path: Path) -> None:
    kb, accounts, traces = _resolve(TRIPWISE_DATA_DIR=str(tmp_path))
    assert kb == tmp_path / "tripwise.sqlite"
    assert accounts == tmp_path / "accounts.sqlite"
    assert traces == tmp_path / "traces"


def test_blank_data_dir_is_treated_as_unset() -> None:
    kb, accounts, traces = _resolve(TRIPWISE_DATA_DIR="   ")
    assert kb.parent == BACKEND / "core"
    assert accounts.parent == BACKEND / "accounts"
    assert traces == BACKEND / ".traces"


def test_core_runtime_paths_imports_nothing_but_the_standard_library() -> None:
    import ast

    tree = ast.parse((BACKEND / "core" / "runtime_paths.py").read_text())
    roots = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in ast.walk(tree)
        if isinstance(n, ast.Import | ast.ImportFrom)
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert roots <= {"os", "pathlib", "__future__"}
