from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from accounts.models import UserProfile
from accounts.store import AccountStore, DuplicateEmailError, UnknownUserError

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore.open(tmp_path / "accounts.sqlite")


def test_create_user_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)

    created = store.create_user(email="Himanshu@Example.com", now=NOW, user_id="u1")
    fetched = store.get_user("u1")

    assert created.id == "u1"
    assert created.email == "himanshu@example.com"
    assert fetched == created


def test_create_user_mints_an_id_when_none_is_given(tmp_path: Path) -> None:
    store = _store(tmp_path)

    created = store.create_user(email="a@example.com", now=NOW)

    assert len(created.id) > 0
    assert store.get_user(created.id) == created


def test_get_user_by_email_is_case_insensitive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")

    found = store.get_user_by_email("  A@EXAMPLE.COM ")

    assert found is not None
    assert found.id == "u1"


def test_create_user_rejects_a_duplicate_email(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")

    with pytest.raises(DuplicateEmailError):
        store.create_user(email="A@example.com", now=NOW, user_id="u2")


def test_get_user_returns_none_when_absent(tmp_path: Path) -> None:
    assert _store(tmp_path).get_user("nobody") is None


def test_put_profile_upserts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")

    store.put_profile(
        UserProfile(
            user_id="u1",
            display_name="Himanshu",
            home_country="IN",
            home_currency="INR",
            updated_at=NOW,
        )
    )
    store.put_profile(
        UserProfile(
            user_id="u1",
            display_name="H. Jain",
            home_country="IN",
            home_currency="INR",
            origin_city="DEL",
            updated_at=NOW,
        )
    )

    profile = store.get_profile("u1")
    assert profile is not None
    assert profile.display_name == "H. Jain"
    assert profile.origin_city == "DEL"


def test_store_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "accounts.sqlite"
    AccountStore.open(db_path).create_user(email="a@example.com", now=NOW, user_id="u1")

    reopened = AccountStore.open(db_path)

    assert reopened.get_user("u1") is not None


def _user_store(tmp_path: Path) -> AccountStore:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")
    return store


def test_add_wallet_entry_round_trips(tmp_path: Path) -> None:
    store = _user_store(tmp_path)

    entry = store.add_wallet_entry(
        user_id="u1",
        card_id="hdfc-infinia",
        nickname="Main Infinia",
        now=NOW,
        last4="4321",
        statement_day=18,
        opened_on=date(2026, 5, 2),
        points_balances={"hdfc-reward-points": 140000},
        entry_id="w1",
    )

    assert store.wallet_entries("u1") == [entry]


def test_wallet_entries_are_ordered_by_card_id_then_id(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    for entry_id, card_id in [
        ("w3", "hdfc-infinia"),
        ("w1", "amex-platinum"),
        ("w2", "hdfc-infinia"),
    ]:
        store.add_wallet_entry(
            user_id="u1",
            card_id=card_id,
            nickname=entry_id,
            now=NOW,
            entry_id=entry_id,
        )

    assert [e.id for e in store.wallet_entries("u1")] == ["w1", "w2", "w3"]


def test_wallet_entries_are_scoped_to_one_user(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.create_user(email="b@example.com", now=NOW, user_id="u2")
    store.add_wallet_entry(
        user_id="u1", card_id="hdfc-infinia", nickname="A", now=NOW, entry_id="w1"
    )
    store.add_wallet_entry(
        user_id="u2", card_id="amex-platinum", nickname="B", now=NOW, entry_id="w2"
    )

    assert [e.id for e in store.wallet_entries("u1")] == ["w1"]
    assert [e.id for e in store.wallet_entries("u2")] == ["w2"]


def test_add_wallet_entry_rejects_an_unknown_user(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(UnknownUserError):
        store.add_wallet_entry(
            user_id="ghost", card_id="hdfc-infinia", nickname="A", now=NOW
        )


def test_set_points_balances_replaces_the_stored_map(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.add_wallet_entry(
        user_id="u1",
        card_id="hdfc-infinia",
        nickname="A",
        now=NOW,
        points_balances={"hdfc-reward-points": 100},
        entry_id="w1",
    )

    updated = store.set_points_balances("w1", {"hdfc-reward-points": 250})

    assert updated.points_balances == {"hdfc-reward-points": 250}
    assert store.wallet_entries("u1")[0].points_balances == {"hdfc-reward-points": 250}


def test_set_points_balances_rejects_a_negative_balance(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.add_wallet_entry(
        user_id="u1", card_id="hdfc-infinia", nickname="A", now=NOW, entry_id="w1"
    )

    with pytest.raises(ValueError):
        store.set_points_balances("w1", {"hdfc-reward-points": -5})


def test_remove_wallet_entry(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.add_wallet_entry(
        user_id="u1", card_id="hdfc-infinia", nickname="A", now=NOW, entry_id="w1"
    )

    store.remove_wallet_entry("w1")

    assert store.wallet_entries("u1") == []


def test_add_wallet_entry_rejects_a_full_card_number(tmp_path: Path) -> None:
    store = _user_store(tmp_path)

    with pytest.raises(ValueError):
        store.add_wallet_entry(
            user_id="u1",
            card_id="hdfc-infinia",
            nickname="A",
            now=NOW,
            last4="4111111111111111",
        )
