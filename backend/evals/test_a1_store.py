from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from accounts.models import UserProfile
from accounts.store import AccountStore, DuplicateEmailError

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
