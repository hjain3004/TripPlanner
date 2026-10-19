"""A3 Task 3 — durable idempotency for wallet mutations.

A retried request (dropped response, double-submit, two tabs) must not create a
second card or advance a version twice. CP1 solved this for planning sessions
with ``PlanningSession.processed_event_ids``, a list inside the session's own
aggregate payload. That shape cannot carry wallet events: a create has no
pre-existing row to hold the list, wallet events target different entries rather
than one aggregate, and a bare id list can store neither the request fingerprint
needed to detect conflicting reuse nor the original outcome a replay must return.
So wallet events get their own accounts-owned table, keyed ``(user_id,
client_event_id)``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from accounts.store import (
    AccountStore,
    StaleWalletEntryError,
    WalletIdempotencyConflictError,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
OTHER_CLOCK = datetime(2026, 10, 19, 18, 30, tzinfo=UTC)


def _store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="u-bob")
    return store


# --- create ---------------------------------------------------------------- #


def test_identical_create_replay_does_not_add_a_second_card(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-create",
    )
    again = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-create",
    )
    assert again.id == first.id
    assert again.version == first.version
    assert len(store.wallet_entries("u-alice")) == 1


def test_replay_tolerates_a_different_clock_and_generated_id(tmp_path: Path) -> None:
    """A retry sends the same intent; its ``now`` and any generated id differ.

    Folding either into the fingerprint would make every genuine retry look
    like a conflict.
    """
    store = _store(tmp_path)
    first = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-clock",
    )
    again = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=OTHER_CLOCK,
        client_event_id="evt-clock",
    )
    assert again.id == first.id
    assert again.added_at == first.added_at
    assert len(store.wallet_entries("u-alice")) == 1


def test_same_event_id_with_a_different_payload_conflicts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-x",
    )
    with pytest.raises(WalletIdempotencyConflictError):
        store.add_wallet_entry(
            user_id="u-alice",
            card_id="axis-magnus",  # different target
            nickname="Primary",
            now=NOW,
            client_event_id="evt-x",
        )
    with pytest.raises(WalletIdempotencyConflictError):
        store.add_wallet_entry(
            user_id="u-alice",
            card_id="hdfc-infinia",
            nickname="Renamed",  # different payload
            now=NOW,
            client_event_id="evt-x",
        )
    assert len(store.wallet_entries("u-alice")) == 1


# --- update ---------------------------------------------------------------- #


def test_identical_update_replay_does_not_bump_the_version_twice(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    entry = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    first = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Renamed",
        client_event_id="evt-update",
    )
    again = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Renamed",
        client_event_id="evt-update",
    )
    assert first.version == 2
    assert again.version == 2
    assert again.nickname == "Renamed"
    (current,) = store.wallet_entries("u-alice")
    assert current.version == 2


def test_same_event_id_with_a_different_expected_version_conflicts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    entry = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Renamed",
        client_event_id="evt-ver",
    )
    with pytest.raises(WalletIdempotencyConflictError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=entry.id,
            expected_version=2,  # same event id, different precondition
            nickname="Renamed",
            client_event_id="evt-ver",
        )


def test_same_event_id_against_a_different_entry_conflicts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    one = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="One", now=NOW
    )
    two = store.add_wallet_entry(
        user_id="u-alice", card_id="axis-magnus", nickname="Two", now=NOW
    )
    store.update_wallet_entry(
        user_id="u-alice",
        entry_id=one.id,
        expected_version=1,
        nickname="Renamed",
        client_event_id="evt-target",
    )
    with pytest.raises(WalletIdempotencyConflictError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=two.id,  # different target
            expected_version=1,
            nickname="Renamed",
            client_event_id="evt-target",
        )


# --- delete ---------------------------------------------------------------- #


def test_identical_delete_replay_returns_the_original_outcome(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entry = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    first = store.remove_wallet_entry(
        user_id="u-alice", entry_id=entry.id, client_event_id="evt-del"
    )
    again = store.remove_wallet_entry(
        user_id="u-alice", entry_id=entry.id, client_event_id="evt-del"
    )
    assert first is True
    # The replay reports the original True, not the False a second real delete
    # would return.
    assert again is True
    assert store.wallet_entries("u-alice") == []


def test_delete_event_id_reused_against_another_entry_conflicts(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    one = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="One", now=NOW
    )
    two = store.add_wallet_entry(
        user_id="u-alice", card_id="axis-magnus", nickname="Two", now=NOW
    )
    store.remove_wallet_entry(
        user_id="u-alice", entry_id=one.id, client_event_id="evt-del2"
    )
    with pytest.raises(WalletIdempotencyConflictError):
        store.remove_wallet_entry(
            user_id="u-alice", entry_id=two.id, client_event_id="evt-del2"
        )
    assert [e.id for e in store.wallet_entries("u-alice")] == [two.id]


# --- cross-user isolation and durability ----------------------------------- #


def test_cross_user_reuse_of_the_same_event_id_does_not_collide(
    tmp_path: Path,
) -> None:
    """Event identity is ``(user_id, client_event_id)``, not the text alone."""
    store = _store(tmp_path)
    alice = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Alice card",
        now=NOW,
        client_event_id="shared-id",
    )
    bob = store.add_wallet_entry(
        user_id="u-bob",
        card_id="hdfc-infinia",
        nickname="Bob card",
        now=NOW,
        client_event_id="shared-id",
    )
    assert alice.id != bob.id
    assert len(store.wallet_entries("u-alice")) == 1
    assert len(store.wallet_entries("u-bob")) == 1


def test_events_survive_a_sqlite_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    first = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-durable",
    )

    reopened = AccountStore.open(db_path)
    again = reopened.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        client_event_id="evt-durable",
    )
    assert again.id == first.id
    assert len(reopened.wallet_entries("u-alice")) == 1


# --- failures are not recorded as successes -------------------------------- #


def test_a_stale_update_does_not_record_its_event(tmp_path: Path) -> None:
    """A rejected mutation must leave the event id free to retry correctly."""
    store = _store(tmp_path)
    entry = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    store.update_wallet_entry(
        user_id="u-alice", entry_id=entry.id, expected_version=1, nickname="v2"
    )
    # Stale precondition: this must fail, and must NOT be remembered.
    with pytest.raises(StaleWalletEntryError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=entry.id,
            expected_version=1,
            nickname="v3",
            client_event_id="evt-stale",
        )
    # The same event id, now with the correct precondition, must succeed.
    recovered = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=2,
        nickname="v3",
        client_event_id="evt-stale",
    )
    assert recovered.nickname == "v3"
    assert recovered.version == 3


def test_a_rejected_validation_does_not_record_its_event(tmp_path: Path) -> None:
    store = _store(tmp_path)
    entry = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    with pytest.raises(ValueError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=entry.id,
            expected_version=1,
            points_balances={"hdfc-reward-points": -1},
            client_event_id="evt-bad",
        )
    recovered = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        points_balances={"hdfc-reward-points": 10},
        client_event_id="evt-bad",
    )
    assert recovered.points_balances == {"hdfc-reward-points": 10}
    assert recovered.version == 2
