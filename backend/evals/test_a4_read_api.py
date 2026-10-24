"""A4 Task 5 — listing and reopening saved trips, verbatim.

The point of a saved revision is that it keeps meaning what it meant when it was
computed. So the read path must hand back the stored JSON object untouched — never
re-parsed through today's ``FinalReport``, which would coerce, default or drop
fields of an older snapshot — and must say how old the snapshot's schema is.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from accounts.db import TripRevisionRow
from accounts.models import TripRevision
from accounts.store import AccountStore
from api.main import app
from evals.a4_support import (
    PlanningKit,
    csrf,
    finished_plan,
    second_client,
    signed_in_client,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _user_id(client: TestClient) -> str:
    return str(client.get("/auth/me").json()["id"])


def _save(client: TestClient, session_id: str, event: str, **extra: Any) -> dict[str, Any]:
    response = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session_id, "client_event_id": event, **extra},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, AccountStore, PlanningKit, dict[str, Any], dict[str, Any]]:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit)
    return client, store, kit, session, _save(client, session["id"], "save-1")


# --- authentication and ownership --------------------------------------------------- #


def test_every_read_route_requires_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, _session, created = _saved(tmp_path, monkeypatch)
    trip_id = created["trip"]["id"]

    with TestClient(app) as anonymous:
        assert anonymous.get("/account/trips").status_code == 401
        assert anonymous.get(f"/account/trips/{trip_id}").status_code == 401
        assert anonymous.get(f"/account/trips/{trip_id}/revisions/1").status_code == 401
    assert client.get("/account/trips").status_code == 200


def test_another_users_trip_reads_exactly_like_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, _store, _kit, _session, created = _saved(tmp_path, monkeypatch)
    trip_id = created["trip"]["id"]
    intruder = second_client("intruder@example.com")

    for path in ("", "/revisions/1"):
        foreign = intruder.get(f"/account/trips/{trip_id}{path}")
        missing = intruder.get(f"/account/trips/no-such-trip{path}")
        assert foreign.status_code == missing.status_code == 404
        assert foreign.json() == missing.json()
    assert intruder.get("/account/trips").json() == []


# --- the list ------------------------------------------------------------------------- #


def test_the_list_is_summaries_newest_first_without_report_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, _session, first = _saved(tmp_path, monkeypatch)
    second_session, _ = finished_plan(client, kit)
    second = _save(client, second_session["id"], "save-2", title="Second trip")

    listing = client.get("/account/trips")

    assert listing.status_code == 200
    items = listing.json()
    assert [item["id"] for item in items] == [second["trip"]["id"], first["trip"]["id"]]
    assert set(items[0]) == {
        "id",
        "title",
        "origin_city",
        "destination_city",
        "start_date",
        "end_date",
        "created_at",
        "revision_count",
        "latest_revision",
        "latest_computed_at",
    }
    assert items[0]["title"] == "Second trip"
    assert items[0]["revision_count"] == items[0]["latest_revision"] == 1
    assert "report" not in listing.text


def test_an_empty_account_lists_nothing(tmp_path: Path) -> None:
    client, _store = signed_in_client(tmp_path)

    assert client.get("/account/trips").json() == []


def test_the_list_only_ever_contains_the_callers_trips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, _session, created = _saved(tmp_path, monkeypatch)
    intruder = second_client("intruder@example.com")

    assert [t["id"] for t in client.get("/account/trips").json()] == [created["trip"]["id"]]
    assert intruder.get("/account/trips").json() == []


# --- one trip ------------------------------------------------------------------------- #


def test_trip_detail_lists_revision_summaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, created = _saved(tmp_path, monkeypatch)
    trip_id = created["trip"]["id"]
    appended = client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "app-1"},
    )
    assert appended.status_code == 201

    detail = client.get(f"/account/trips/{trip_id}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == trip_id and body["revision_count"] == 2
    assert [r["revision"] for r in body["revisions"]] == [1, 2]
    assert set(body["revisions"][0]) == {
        "revision",
        "computed_at",
        "trace_id",
        "schema_version",
        "is_current_schema",
    }
    assert body["revisions"][0]["is_current_schema"] is True
    assert "report" not in detail.text


# --- one revision, verbatim ----------------------------------------------------------- #


def test_a_revision_is_the_stored_report_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, _session, created = _saved(tmp_path, monkeypatch)
    trip_id = created["trip"]["id"]

    response = client.get(f"/account/trips/{trip_id}/revisions/1")

    assert response.status_code == 200
    body = response.json()
    (stored,) = store.revisions(_user_id(client), trip_id)
    assert body["report"] == json.loads(stored.report_json)
    assert body["revision"] == 1
    assert body["schema_version"] == "1" and body["is_current_schema"] is True
    assert body["computed_at"] == stored.created_at.isoformat()


def test_an_old_snapshot_is_returned_untouched_and_flagged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report from a schema the current FinalReport cannot parse still reads back."""
    client, store, _kit, _session, created = _saved(tmp_path, monkeypatch)
    trip_id = created["trip"]["id"]
    legacy_report = {
        "legacy_field": [1, 2, 3],
        "trip_spec": "an older shape, not a TripSpec",
        "summary": 'quoted "text" with unicode ₹ and a null',
        "nested": {"n": None},
    }
    legacy = TripRevision(
        id="legacy-rev",
        trip_id=trip_id,
        revision=2,
        trace_id="old-trace",
        report_json=json.dumps(legacy_report),
        schema_version="0",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with Session(store._engine) as db:
        db.add(
            TripRevisionRow(
                id=legacy.id,
                trip_id=trip_id,
                revision=2,
                payload=legacy.model_dump_json(),
            )
        )
        db.commit()

    body = client.get(f"/account/trips/{trip_id}/revisions/2").json()

    assert body["report"] == legacy_report
    assert body["schema_version"] == "0" and body["is_current_schema"] is False
    listed = client.get(f"/account/trips/{trip_id}").json()["revisions"]
    assert [r["is_current_schema"] for r in listed] == [True, False]


def test_a_missing_revision_is_a_typed_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, _session, created = _saved(tmp_path, monkeypatch)
    trip_id = created["trip"]["id"]

    for number in ("2", "0", "-1"):
        response = client.get(f"/account/trips/{trip_id}/revisions/{number}")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "REVISION_NOT_FOUND"
    assert client.get(f"/account/trips/{trip_id}/revisions/abc").status_code == 422


def test_the_openapi_report_type_is_a_free_form_object() -> None:
    schemas = app.openapi()["components"]["schemas"]

    report = schemas["RevisionOut"]["properties"]["report"]
    assert report["type"] == "object"
    assert report.get("additionalProperties") in (True, {})
