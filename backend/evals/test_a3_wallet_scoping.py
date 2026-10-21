"""A3 Task 2 — wallet mutations are owner-scoped and version-checked.

Before A3 both wallet mutators resolved a row by primary key alone
(``session.get(WalletEntryRow, entry_id)``), with no ``user_id`` predicate. Any
caller holding an entry id could mutate or delete another user's card. These
tests pin the fix, and pin that a wrong-owner failure is indistinguishable from
a genuinely-missing entry so the API can never disclose another user's ids.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from accounts.db import WalletEntryRow
from accounts.models import WalletEntry
from accounts.store import (
    AccountStore,
    StaleWalletEntryError,
    WalletEntryNotFoundError,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _two_users(tmp_path: Path) -> tuple[AccountStore, WalletEntry]:
    """Alice owns one wallet entry; Bob owns nothing."""
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="u-bob")
    entry = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Alice card",
        now=NOW,
        entry_id="w-alice",
        points_balances={"hdfc-reward-points": 100},
    )
    return store, entry


# --- cross-user isolation -------------------------------------------------- #


def test_other_user_cannot_update(tmp_path: Path) -> None:
    store, entry = _two_users(tmp_path)
    with pytest.raises(WalletEntryNotFoundError):
        store.update_wallet_entry(
            user_id="u-bob",
            entry_id=entry.id,
            expected_version=1,
            nickname="stolen",
        )
    # Alice's row is untouched, still at version 1.
    (alice_entry,) = store.wallet_entries("u-alice")
    assert alice_entry.nickname == "Alice card"
    assert alice_entry.version == 1


def test_wrong_owner_update_is_indistinguishable_from_missing(tmp_path: Path) -> None:
    """Both raise the same type, so the API cannot leak another user's ids."""
    store, entry = _two_users(tmp_path)
    with pytest.raises(WalletEntryNotFoundError):
        store.update_wallet_entry(
            user_id="u-bob", entry_id=entry.id, expected_version=1
        )
    with pytest.raises(WalletEntryNotFoundError):
        store.update_wallet_entry(
            user_id="u-bob", entry_id="no-such-entry", expected_version=1
        )


def test_other_user_delete_is_a_no_op_and_non_disclosing(tmp_path: Path) -> None:
    store, entry = _two_users(tmp_path)
    assert store.remove_wallet_entry(user_id="u-bob", entry_id=entry.id) is False
    assert store.remove_wallet_entry(user_id="u-bob", entry_id="no-such-entry") is False
    # Alice still has her card.
    assert [e.id for e in store.wallet_entries("u-alice")] == [entry.id]


def test_owner_delete_succeeds_once_then_reports_false(tmp_path: Path) -> None:
    store, entry = _two_users(tmp_path)
    assert store.remove_wallet_entry(user_id="u-alice", entry_id=entry.id) is True
    assert store.wallet_entries("u-alice") == []
    assert store.remove_wallet_entry(user_id="u-alice", entry_id=entry.id) is False


# --- optimistic concurrency ------------------------------------------------- #


def test_successful_update_bumps_version_by_one(tmp_path: Path) -> None:
    store, entry = _two_users(tmp_path)
    updated = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Renamed",
    )
    assert updated.version == 2
    assert updated.nickname == "Renamed"

    with Session(store._engine) as session:  # noqa: SLF001 - asserting storage shape
        row = session.get(WalletEntryRow, entry.id)
        assert row is not None
        assert row.version == 2
        assert WalletEntry.model_validate_json(row.payload).version == 2


def test_stale_expected_version_loses(tmp_path: Path) -> None:
    store, entry = _two_users(tmp_path)
    store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="first writer",
    )
    with pytest.raises(StaleWalletEntryError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=entry.id,
            expected_version=1,
            nickname="second writer",
        )
    # The first writer's value survives — no silent overwrite.
    (current,) = store.wallet_entries("u-alice")
    assert current.nickname == "first writer"
    assert current.version == 2


# --- immutability and validation ------------------------------------------- #


def test_card_id_and_added_at_are_not_writable(tmp_path: Path) -> None:
    """Only the five safe metadata fields may change."""
    store, entry = _two_users(tmp_path)
    updated = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Renamed",
    )
    assert updated.card_id == entry.card_id
    assert updated.user_id == entry.user_id
    assert updated.added_at == entry.added_at


def test_update_still_enforces_model_validators(tmp_path: Path) -> None:
    """``model_copy`` skips validators, so the update must re-validate."""
    store, entry = _two_users(tmp_path)
    with pytest.raises(ValueError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=entry.id,
            expected_version=1,
            points_balances={"hdfc-reward-points": -5},
        )
    with pytest.raises(ValueError):
        store.update_wallet_entry(
            user_id="u-alice",
            entry_id=entry.id,
            expected_version=1,
            last4="4111111111111111",  # a PAN, not a last4
        )
    # A rejected update must not have advanced the version.
    (current,) = store.wallet_entries("u-alice")
    assert current.version == 1


def test_omitted_fields_are_left_alone(tmp_path: Path) -> None:
    """A partial update is a patch, not a destructive replace of the whole row."""
    store, entry = _two_users(tmp_path)
    updated = store.update_wallet_entry(
        user_id="u-alice",
        entry_id=entry.id,
        expected_version=1,
        nickname="Only the nickname",
    )
    assert updated.points_balances == {"hdfc-reward-points": 100}
    assert updated.last4 == entry.last4
    assert updated.statement_day == entry.statement_day
