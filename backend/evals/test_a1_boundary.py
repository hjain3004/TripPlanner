from __future__ import annotations

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
