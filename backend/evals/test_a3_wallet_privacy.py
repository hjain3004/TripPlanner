"""A3 Task 10 — wallet state and mutation history under privacy export/delete.

The idempotency ledger added in Task 3 stores a full ``WalletEntry`` snapshot in
``result_payload``. That is personal data held about the user, so a
subject-access export has to include it and account deletion has to remove it.
Deletion was wired in Task 3 (``delete_user`` enumerates tables explicitly, so a
new table silently survives erasure unless it is added); these tests pin both
halves.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from accounts.store import AccountStore

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _store_with_history(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="u-bob")
    entry = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        points_balances={"hdfc-reward-points": 100},
        client_event_id="evt-create",
    )
    store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Renamed",
        client_event_id="evt-update",
        now=NOW,
    )
    # Bob has his own history, which must never appear in Alice's export.
    store.add_wallet_entry(
        user_id="u-bob",
        card_id="axis-atlas",
        nickname="Bob card",
        now=NOW,
        client_event_id="evt-create",
    )
    return store


# --- export ---------------------------------------------------------------- #


def test_export_includes_wallet_entries_and_mutation_history(tmp_path: Path) -> None:
    store = _store_with_history(tmp_path)
    export = store.export_user("u-alice", now=NOW)

    assert [e.nickname for e in export.wallet_entries] == ["Renamed"]
    event_ids = [e.client_event_id for e in export.wallet_mutation_events]
    assert sorted(event_ids) == ["evt-create", "evt-update"]
    assert {e.operation for e in export.wallet_mutation_events} == {"create", "update"}


def test_export_is_scoped_to_one_user(tmp_path: Path) -> None:
    """Bob reused the same textual event id; Alice's export must not show it."""
    store = _store_with_history(tmp_path)
    alice = store.export_user("u-alice", now=NOW)
    bob = store.export_user("u-bob", now=NOW)

    assert {e.user_id for e in alice.wallet_mutation_events} == {"u-alice"}
    assert {e.user_id for e in bob.wallet_mutation_events} == {"u-bob"}
    assert len(bob.wallet_mutation_events) == 1
    assert [e.nickname for e in bob.wallet_entries] == ["Bob card"]


def test_export_history_is_deterministically_ordered(tmp_path: Path) -> None:
    store = _store_with_history(tmp_path)
    first = store.export_user("u-alice", now=NOW)
    second = store.export_user("u-alice", now=NOW)
    assert [e.client_event_id for e in first.wallet_mutation_events] == [
        e.client_event_id for e in second.wallet_mutation_events
    ]


# --- deletion -------------------------------------------------------------- #


def test_delete_user_removes_wallet_state_and_history(tmp_path: Path) -> None:
    store = _store_with_history(tmp_path)
    store.delete_user("u-alice")

    assert store.wallet_entries("u-alice") == []
    assert store.wallet_mutation_events("u-alice") == []
    # Bob is untouched.
    assert len(store.wallet_entries("u-bob")) == 1
    assert len(store.wallet_mutation_events("u-bob")) == 1


def test_deleted_history_does_not_survive_a_sqlite_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-create",
    )
    store.delete_user("u-alice")

    reopened = AccountStore.open(db_path)
    assert reopened.wallet_mutation_events("u-alice") == []


def test_a_deleted_event_id_is_reusable_after_erasure(tmp_path: Path) -> None:
    """Erasure is real: the ledger no longer remembers the old event."""
    store = _store_with_history(tmp_path)
    store.delete_user("u-alice")
    store.create_user(email="alice2@example.com", now=NOW, user_id="u-alice")

    revived = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Fresh",
        now=NOW,
        client_event_id="evt-create",
    )
    assert revived.nickname == "Fresh"
    assert revived.version == 1
