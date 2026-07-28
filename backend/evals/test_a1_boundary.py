from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import inspect

from accounts.db import AccountsBase, create_accounts_engine
from core.db import Base as CoreBase
from core.db import SEEDS_DIR, seed_database

ACCOUNTS_TABLES = {
    "users",
    "user_profiles",
    "wallet_entries",
    "saved_trips",
    "trip_revisions",
    "user_credentials",
    "sessions",
}


def test_accounts_tables_are_not_registered_on_the_core_metadata() -> None:
    assert set(AccountsBase.metadata.tables) == ACCOUNTS_TABLES
    assert set(CoreBase.metadata.tables).isdisjoint(ACCOUNTS_TABLES)


def test_create_accounts_engine_creates_every_table(tmp_path: Path) -> None:
    engine = create_accounts_engine(tmp_path / "accounts.sqlite")

    assert set(inspect(engine).get_table_names()) == ACCOUNTS_TABLES


def test_reseeding_the_knowledge_base_does_not_touch_accounts_tables(
    tmp_path: Path,
) -> None:
    engine = create_accounts_engine(tmp_path / "accounts.sqlite")
    kb_db = tmp_path / "tripwise.sqlite"

    seed_database(SEEDS_DIR, kb_db)
    seed_database(SEEDS_DIR, kb_db)  # drop_all + create_all, twice

    names = set(inspect(engine).get_table_names())
    assert "users" in names
    assert "cards" not in names


def _first_party_imports(path: Path) -> set[str]:
    """Top-level package names this module imports."""
    names: set[str] = set()
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_core_never_imports_accounts() -> None:
    """The dependency runs one way: accounts may read core, never the reverse."""
    backend_dir = Path(__file__).resolve().parents[1]
    core_dir = backend_dir / "core"
    offenders = [
        str(path.relative_to(backend_dir))
        for path in sorted(core_dir.rglob("*.py"))
        if "accounts" in _first_party_imports(path)
    ]

    assert offenders == [], f"core/ must not import accounts/: {offenders}"


def test_accounts_never_imports_agents_or_api() -> None:
    """Accounts stores JSON snapshots, so it needs no pipeline types."""
    backend_dir = Path(__file__).resolve().parents[1]
    accounts_dir = backend_dir / "accounts"
    offenders = [
        str(path.relative_to(backend_dir))
        for path in sorted(accounts_dir.rglob("*.py"))
        if {"agents", "api"} & _first_party_imports(path)
    ]

    assert offenders == [], f"accounts/ must not import agents/ or api/: {offenders}"
