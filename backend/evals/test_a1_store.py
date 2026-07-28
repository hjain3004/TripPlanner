from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from accounts.models import UserExport, UserProfile
from accounts.store import (
    AccountStore,
    DuplicateEmailError,
    UnknownTripError,
    UnknownUserError,
)

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


def _saved_trip(store: AccountStore, trip_id: str = "t1") -> str:
    trip = store.save_trip(
        user_id="u1",
        title="Singapore, August",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        raw_request="Delhi to Singapore Aug 1-5",
        trip_spec_json='{"origin_city":"DEL","destination_city":"SIN"}',
        now=NOW,
        trip_id=trip_id,
    )
    return trip.id


def test_save_trip_round_trips(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)

    trips = store.trips("u1")

    assert [t.id for t in trips] == [trip_id]
    assert trips[0].trip_spec_json == '{"origin_city":"DEL","destination_city":"SIN"}'


def test_save_trip_rejects_an_unknown_user(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(UnknownUserError):
        store.save_trip(
            user_id="ghost",
            title="x",
            origin_city="DEL",
            destination_city="SIN",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            raw_request="x",
            trip_spec_json="{}",
            now=NOW,
        )


def test_revisions_are_numbered_from_one_and_append(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)

    first = store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )
    second = store.add_revision(
        trip_id=trip_id, trace_id="trace2", report_json='{"summary":"v2"}', now=NOW
    )

    assert first.revision == 1
    assert second.revision == 2
    assert [r.revision for r in store.revisions(trip_id)] == [1, 2]


def test_a_new_revision_never_mutates_an_earlier_one(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)
    store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )

    store.add_revision(
        trip_id=trip_id, trace_id="trace2", report_json='{"summary":"v2"}', now=NOW
    )

    stored = store.revisions(trip_id)
    assert stored[0].report_json == '{"summary":"v1"}'
    assert stored[0].trace_id == "trace1"


def test_the_store_exposes_no_way_to_edit_a_revision() -> None:
    """Immutability is structural: no update/delete method exists for revisions."""
    forbidden = {
        "update_revision",
        "edit_revision",
        "delete_revision",
        "set_revision",
        "replace_revision",
    }

    assert forbidden.isdisjoint(dir(AccountStore))


def test_latest_revision_returns_the_highest_numbered(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)
    store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )
    store.add_revision(
        trip_id=trip_id, trace_id="trace2", report_json='{"summary":"v2"}', now=NOW
    )

    latest = store.latest_revision(trip_id)

    assert latest is not None
    assert latest.revision == 2
    assert latest.trace_id == "trace2"


def test_latest_revision_is_none_for_a_trip_with_no_runs(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)

    assert store.latest_revision(trip_id) is None


def test_add_revision_rejects_an_unknown_trip(tmp_path: Path) -> None:
    store = _user_store(tmp_path)

    with pytest.raises(UnknownTripError):
        store.add_revision(trip_id="nope", trace_id="t", report_json="{}", now=NOW)


def _populated(tmp_path: Path) -> AccountStore:
    store = _user_store(tmp_path)
    store.put_profile(
        UserProfile(
            user_id="u1",
            display_name="Himanshu",
            home_country="IN",
            home_currency="INR",
            updated_at=NOW,
        )
    )
    store.add_wallet_entry(
        user_id="u1",
        card_id="hdfc-infinia",
        nickname="Main",
        now=NOW,
        points_balances={"hdfc-reward-points": 140000},
        entry_id="w1",
    )
    trip_id = _saved_trip(store)
    store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )
    return store


def test_export_user_returns_everything_held(tmp_path: Path) -> None:
    store = _populated(tmp_path)

    export = store.export_user("u1", now=NOW)

    assert isinstance(export, UserExport)
    assert export.user.id == "u1"
    assert export.profile is not None
    assert [e.id for e in export.wallet_entries] == ["w1"]
    assert [t.id for t in export.trips] == ["t1"]
    assert [r.revision for r in export.revisions] == [1]
    assert export.exported_at == NOW


def test_export_rejects_an_unknown_user(tmp_path: Path) -> None:
    with pytest.raises(UnknownUserError):
        _store(tmp_path).export_user("ghost", now=NOW)


def test_delete_user_removes_every_owned_row(tmp_path: Path) -> None:
    store = _populated(tmp_path)

    store.delete_user("u1")

    assert store.get_user("u1") is None
    assert store.get_profile("u1") is None
    assert store.wallet_entries("u1") == []
    assert store.trips("u1") == []
    assert store.revisions("t1") == []


def test_delete_user_leaves_other_users_intact(tmp_path: Path) -> None:
    store = _populated(tmp_path)
    store.create_user(email="b@example.com", now=NOW, user_id="u2")
    store.add_wallet_entry(
        user_id="u2", card_id="amex-platinum", nickname="B", now=NOW, entry_id="w2"
    )

    store.delete_user("u1")

    assert store.get_user("u2") is not None
    assert [e.id for e in store.wallet_entries("u2")] == ["w2"]


def test_delete_user_is_idempotent(tmp_path: Path) -> None:
    store = _populated(tmp_path)

    store.delete_user("u1")
    store.delete_user("u1")  # must not raise

    assert store.get_user("u1") is None
