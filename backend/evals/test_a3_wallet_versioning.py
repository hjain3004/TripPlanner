"""A3 Task 1 — wallet entries carry a version, added migration-safely.

The version is what lets Task 2 do a compare-and-swap update instead of a
last-writer-wins overwrite. Adding the column must not delete or rewrite any
existing account data: a row written before the column existed has to read
back at version 1, not NULL.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from accounts.db import WalletEntryRow
from accounts.models import WalletEntry
from accounts.store import AccountStore

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def test_new_entry_starts_at_version_one(tmp_path: Path) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    user = store.create_user(email="a@example.com", now=NOW, user_id="u1")
    entry = store.add_wallet_entry(
        user_id=user.id, card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    assert entry.version == 1


def test_version_survives_a_sqlite_reopen(tmp_path: Path) -> None:
    """The column must persist on disk, not be re-derived per process."""
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    user = store.create_user(email="a@example.com", now=NOW, user_id="u1")
    entry = store.add_wallet_entry(
        user_id=user.id, card_id="hdfc-infinia", nickname="Primary", now=NOW
    )

    reopened = AccountStore.open(db_path)
    (loaded,) = reopened.wallet_entries(user.id)
    assert loaded.id == entry.id
    assert loaded.version == 1


def test_row_column_and_payload_version_agree(tmp_path: Path) -> None:
    """The indexed column is what CAS filters on; the payload is what callers read.

    If these two drift, a CAS update can match a row whose deserialized entry
    reports a different version — so pin them together at write time.
    """
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    user = store.create_user(email="a@example.com", now=NOW, user_id="u1")
    entry = store.add_wallet_entry(
        user_id=user.id, card_id="hdfc-infinia", nickname="Primary", now=NOW
    )

    with Session(store._engine) as session:  # noqa: SLF001 - asserting storage shape
        row = session.get(WalletEntryRow, entry.id)
        assert row is not None
        payload_version = WalletEntry.model_validate_json(row.payload).version
        assert row.version == payload_version == 1


def test_preexisting_row_without_a_version_reads_back_as_one(tmp_path: Path) -> None:
    """Simulate a pre-A3 row: payload with no ``version`` key, column defaulted.

    This is the migration-safety property. A user who added a card before A3
    must not lose it, and must not read back a NULL version.
    """
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    user = store.create_user(email="a@example.com", now=NOW, user_id="u1")

    legacy_payload = json.dumps(
        {
            "id": "legacy-1",
            "user_id": user.id,
            "card_id": "hdfc-infinia",
            "nickname": "Pre-A3 card",
            "last4": None,
            "statement_day": None,
            "opened_on": None,
            "points_balances": {},
            "added_at": NOW.isoformat(),
        }
    )
    with Session(store._engine) as session:  # noqa: SLF001 - writing a legacy shape
        session.execute(
            text(
                "INSERT INTO wallet_entries (id, user_id, card_id, payload) "
                "VALUES (:id, :user_id, :card_id, :payload)"
            ),
            {
                "id": "legacy-1",
                "user_id": user.id,
                "card_id": "hdfc-infinia",
                "payload": legacy_payload,
            },
        )
        session.commit()

    (loaded,) = AccountStore.open(db_path).wallet_entries(user.id)
    assert loaded.id == "legacy-1"
    assert loaded.nickname == "Pre-A3 card"
    assert loaded.version == 1


def test_pre_a3_database_is_upgraded_without_rewriting_existing_rows(tmp_path: Path) -> None:
    """Opening a real pre-A3 schema adds version/events without losing rows."""
    db_path = tmp_path / "pre-a3.sqlite"
    legacy_payload = json.dumps(
        {
            "id": "legacy-entry",
            "user_id": "legacy-user",
            "card_id": "hdfc-infinia",
            "nickname": "Legacy card",
            "last4": None,
            "statement_day": None,
            "opened_on": None,
            "points_balances": {"legacy-points": 100},
            "added_at": NOW.isoformat(),
        }
    )
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE users (
                id VARCHAR PRIMARY KEY,
                email VARCHAR UNIQUE,
                payload TEXT NOT NULL
            );
            CREATE TABLE wallet_entries (
                id VARCHAR PRIMARY KEY,
                user_id VARCHAR NOT NULL,
                card_id VARCHAR NOT NULL,
                payload TEXT NOT NULL
            );
            INSERT INTO users VALUES ('legacy-user', 'legacy@example.com', '{}');
            """
        )
        connection.execute(
            "INSERT INTO wallet_entries VALUES (?, ?, ?, ?)",
            ("legacy-entry", "legacy-user", "hdfc-infinia", legacy_payload),
        )
        connection.commit()

    store = AccountStore.open(db_path)
    (loaded,) = store.wallet_entries("legacy-user")
    assert loaded.id == "legacy-entry"
    assert loaded.version == 1
    assert loaded.points_balances == {"legacy-points": 100}
    store.add_wallet_entry(
        user_id="legacy-user",
        card_id="hdfc-infinia",
        nickname="New",
        now=NOW,
        client_event_id="legacy-event",
    )
    assert len(store.wallet_mutation_events("legacy-user")) == 1
