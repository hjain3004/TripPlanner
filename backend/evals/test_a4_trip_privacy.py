"""A4 Task 3 — saved trips in privacy export and erasure (spec 17 §6).

``delete_user`` enumerates tables explicitly, so a table added without being added
there silently survives erasure. The generic sweep below is what makes that
failure loud: it inspects every table in the accounts schema.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accounts.db import AccountsBase
from accounts.models import PlanningSessionSnapshot
from accounts.store import AccountStore
from api.main import app
from evals.a4_support import (
    PlanningKit,
    csrf,
    finished_plan,
    second_client,
    signed_in_client,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
MARKER = "SECRET-MARKER-42"


def _store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="u-bob")
    return store


def _save(store: AccountStore, user_id: str, event: str | None = None, **kw: Any) -> Any:
    return store.save_trip_with_revision(
        user_id=user_id,
        title="DEL to SIN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 6),
        raw_request="Delhi to Singapore",
        trip_spec_json="{}",
        trace_id="trace-1",
        report_json=f'{{"summary":"{MARKER}"}}',
        now=NOW,
        client_event_id=event,
        request_fingerprint=f"fp-{event}" if event else None,
        **kw,
    )


def _session(store: AccountStore, user_id: str, session_id: str, trip_id: str | None) -> None:
    store.create_planning_session_snapshot(
        PlanningSessionSnapshot(
            id=session_id,
            user_id=user_id,
            status="complete",
            version=1,
            updated_at=NOW,
            expires_at=datetime(2026, 11, 24, tzinfo=UTC),
            saved_trip_id=trip_id,
            payload_json="{}",
        )
    )


# --------------------------------------------------------------------------- #
# Export                                                                        #
# --------------------------------------------------------------------------- #


def test_export_includes_trips_revisions_and_events_verbatim(tmp_path: Path) -> None:
    store = _store(tmp_path)
    saved = _save(store, "u-alice", "evt-1")
    store.add_revision(
        user_id="u-alice",
        trip_id=saved.trip.id,
        trace_id="trace-2",
        report_json='{"summary":"second"}',
        now=NOW,
        client_event_id="evt-2",
        request_fingerprint="fp-2",
    )

    export = store.export_user("u-alice", now=NOW)

    assert [t.id for t in export.trips] == [saved.trip.id]
    assert [r.revision for r in export.revisions] == [1, 2]
    assert export.revisions[0].report_json == f'{{"summary":"{MARKER}"}}'  # byte for byte
    assert [e.client_event_id for e in export.trip_mutation_events] == ["evt-1", "evt-2"]


def test_export_is_scoped_to_one_user_and_deterministic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save(store, "u-alice", "evt-1")
    _save(store, "u-bob", "evt-b")

    first = store.export_user("u-alice", now=NOW)
    second = store.export_user("u-alice", now=NOW)

    assert first == second
    assert all(t.user_id == "u-alice" for t in first.trips)
    assert [e.client_event_id for e in first.trip_mutation_events] == ["evt-1"]
    assert "evt-b" not in first.model_dump_json()


# --------------------------------------------------------------------------- #
# Account erasure                                                               #
# --------------------------------------------------------------------------- #


def test_delete_user_erases_trip_events_trips_and_revisions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _save(store, "u-alice", "evt-1")
    other = _save(store, "u-bob", "evt-b")

    store.delete_user("u-alice")

    assert store.trips("u-alice") == []
    assert store.trip_mutation_events("u-alice") == []
    assert [t.id for t in store.trips("u-bob")] == [other.trip.id]
    assert len(store.trip_mutation_events("u-bob")) == 1


def test_no_table_in_the_schema_keeps_a_deleted_users_rows(tmp_path: Path) -> None:
    """Enumerates every table: a new one that erasure forgot fails here."""
    path = tmp_path / "accounts.sqlite"
    store = _store(tmp_path)
    saved = _save(store, "u-alice", "evt-1")
    _session(store, "u-alice", "s1", saved.trip.id)
    store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Main",
        now=NOW,
        client_event_id="wal-1",
    )
    trip_id = saved.trip.id

    store.delete_user("u-alice")

    connection = sqlite3.connect(path)
    try:
        for table in AccountsBase.metadata.sorted_tables:
            columns = {c.name for c in table.columns}
            if "user_id" in columns:
                (count,) = connection.execute(
                    f"SELECT COUNT(*) FROM {table.name} WHERE user_id = 'u-alice'"
                ).fetchone()
                assert count == 0, f"{table.name} still holds the deleted user's rows"
            if "trip_id" in columns:
                (count,) = connection.execute(
                    f"SELECT COUNT(*) FROM {table.name} WHERE trip_id = ?", (trip_id,)
                ).fetchone()
                assert count == 0, f"{table.name} still references the deleted trip"
    finally:
        connection.close()


# --------------------------------------------------------------------------- #
# Single-trip deletion (D10)                                                    #
# --------------------------------------------------------------------------- #


def test_delete_trip_removes_revisions_events_and_the_attached_session(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.sqlite"
    store = _store(tmp_path)
    saved = _save(store, "u-alice", "evt-1")
    _session(store, "u-alice", "s-attached", saved.trip.id)
    _session(store, "u-alice", "s-unrelated", None)
    kept = _save(store, "u-alice", "evt-keep")

    assert store.delete_trip("u-alice", saved.trip.id) is True

    reopened = AccountStore.open(path)  # a fresh connection: nothing lingers in memory
    assert [t.id for t in reopened.trips("u-alice")] == [kept.trip.id]
    assert reopened._revisions_of_trip(saved.trip.id) == []
    assert [e.client_event_id for e in reopened.trip_mutation_events("u-alice")] == ["evt-keep"]
    assert (
        reopened.get_planning_session_snapshot(user_id="u-alice", session_id="s-attached")
        is None
    )
    assert (
        reopened.get_planning_session_snapshot(user_id="u-alice", session_id="s-unrelated")
        is not None
    )
    assert len(reopened.revisions("u-alice", kept.trip.id)) == 1


def test_a_delete_event_outlives_its_trip_without_holding_trip_data(tmp_path: Path) -> None:
    store = _store(tmp_path)
    saved = _save(store, "u-alice", "evt-1")

    store.delete_trip(
        "u-alice", saved.trip.id, client_event_id="evt-del", request_fingerprint="fp-del"
    )

    (event,) = store.trip_mutation_events("u-alice")
    assert event.operation == "delete" and event.trip_id is None
    assert MARKER not in event.model_dump_json()
    # A retried DELETE therefore still answers "removed", not "not found".
    assert (
        store.delete_trip(
            "u-alice", saved.trip.id, client_event_id="evt-del", request_fingerprint="fp-del"
        )
        is True
    )


def test_delete_trip_does_not_touch_another_users_trip_or_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    saved = _save(store, "u-alice", "evt-1")
    _session(store, "u-alice", "s-attached", saved.trip.id)

    assert store.delete_trip("u-bob", saved.trip.id) is False

    assert len(store.trips("u-alice")) == 1
    assert store.get_planning_session_snapshot(user_id="u-alice", session_id="s-attached")


# --------------------------------------------------------------------------- #
# DELETE /account/trips/{id} (Task 7)                                           #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _api_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, AccountStore, dict[str, Any], str]:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit)
    created = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "save-1"},
    )
    assert created.status_code == 201, created.text
    return client, store, session, str(created.json()["trip"]["id"])


def _delete(client: TestClient, trip_id: str, event: str | None = "del-1") -> Any:
    suffix = f"?client_event_id={event}" if event else ""
    return client.delete(f"/account/trips/{trip_id}{suffix}", headers=csrf(client))


def test_deleting_a_trip_removes_it_its_revisions_and_its_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session, trip_id = _api_saved(tmp_path, monkeypatch)

    response = _delete(client, trip_id)

    assert response.status_code == 204 and response.content == b""
    assert client.get(f"/account/trips/{trip_id}").status_code == 404
    assert client.get(f"/account/trips/{trip_id}/revisions/1").status_code == 404
    assert client.get("/account/trips").json() == []
    assert client.get(f"/planning/sessions/{session['id']}").status_code == 404
    assert store._revisions_of_trip(trip_id) == []


def test_a_retried_delete_is_still_204_but_a_fresh_one_is_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _session, trip_id = _api_saved(tmp_path, monkeypatch)

    first = _delete(client, trip_id, "del-1")
    retry = _delete(client, trip_id, "del-1")
    fresh = _delete(client, trip_id, "del-2")
    bare = _delete(client, trip_id, None)

    assert first.status_code == retry.status_code == 204
    assert fresh.status_code == bare.status_code == 404
    assert fresh.json()["detail"]["code"] == "TRIP_NOT_FOUND"


def test_another_users_trip_cannot_be_deleted_and_looks_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _session, trip_id = _api_saved(tmp_path, monkeypatch)
    intruder = second_client("intruder@example.com")

    foreign = _delete(intruder, trip_id)
    missing = _delete(intruder, "no-such-trip", "del-2")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert client.get(f"/account/trips/{trip_id}").status_code == 200


def test_deleting_requires_authentication_and_csrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _session, trip_id = _api_saved(tmp_path, monkeypatch)

    assert client.delete(f"/account/trips/{trip_id}").status_code == 403  # no CSRF header
    with TestClient(app) as anonymous:
        assert anonymous.delete(f"/account/trips/{trip_id}").status_code == 401
    assert client.get(f"/account/trips/{trip_id}").status_code == 200
