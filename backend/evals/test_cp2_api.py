"""Acceptance tests for the CP2 authenticated planning API boundary."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

import api.conversation as conversation
from accounts.store import AccountStore
from api.auth import CSRF_COOKIE, CSRF_HEADER, get_store
from api.main import app


def _client(tmp_path: Path) -> tuple[TestClient, AccountStore]:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app, base_url="https://testserver")
    client.post(
        "/auth/register",
        json={"email": "traveler@example.com", "password": "long-password-123"},
    )
    client.post(
        "/auth/login",
        json={"email": "traveler@example.com", "password": "long-password-123"},
    )
    return client, store


def _csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    assert token is not None
    return {CSRF_HEADER: token}


def test_session_requires_authentication_and_csrf_for_mutation(tmp_path: Path) -> None:
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        assert client.post("/planning/sessions").status_code == 401

    client, _ = _client(tmp_path)
    assert client.post("/planning/sessions", headers=_csrf(client)).status_code == 201
    session_id = client.post("/planning/sessions", headers=_csrf(client)).json()["id"]
    response = client.post(
        f"/planning/sessions/{session_id}/skip",
        json={
            "question_id": "trip_essentials",
            "expected_version": 0,
            "client_event_id": "skip-1",
        },
    )
    assert response.status_code == 403
    app.dependency_overrides.clear()


def test_answer_is_typed_idempotent_and_stale_safe(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    session = client.post("/planning/sessions", headers=_csrf(client)).json()
    body = {
        "question_id": "trip_essentials",
        "expected_version": 0,
        "client_event_id": "answer-1",
        "payload": {
            "origin": "DEL",
            "destination": "SIN",
            "start_date": date(2026, 11, 1).isoformat(),
            "end_date": date(2026, 11, 5).isoformat(),
            "travelers": 1,
        },
    }
    headers = _csrf(client)
    first = client.post(f"/planning/sessions/{session['id']}/answers", json=body, headers=headers)
    assert first.status_code == 200
    replay = client.post(f"/planning/sessions/{session['id']}/answers", json=body, headers=headers)
    assert replay.status_code == 200
    assert replay.json()["version"] == first.json()["version"]
    stale = {**body, "client_event_id": "answer-2"}
    assert (
        client.post(
            f"/planning/sessions/{session['id']}/answers", json=stale, headers=headers
        ).status_code
        == 409
    )
    app.dependency_overrides.clear()


def test_partial_profile_patch_preserves_other_groups_and_delete_is_explicit(
    tmp_path: Path,
) -> None:
    client, _ = _client(tmp_path)
    headers = _csrf(client)
    response = client.patch(
        "/planning/preferences",
        headers=headers,
        json={
            "flight": {
                "cabin": {
                    "value": "business",
                    "source": "user_profile_edit",
                    "updated_at": "2026-08-28T00:00:00Z",
                }
            }
        },
    )
    assert response.status_code == 200
    assert response.json()["profile"]["flight"]["cabin"]["value"] == "business"
    assert response.json()["profile"]["stay"] == {
        "lodging_styles": None,
        "location_priorities": None,
        "room_needs": None,
        "location_price_tradeoff": None,
        "loyalty_programs": None,
    }
    removed = client.delete("/planning/preferences/flight", headers=headers)
    assert removed.status_code == 200
    assert removed.json()["profile"]["flight"]["cabin"] is None
    app.dependency_overrides.clear()


def test_review_brief_confirms_exactly_once_and_starts_one_job(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path)
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    headers = _csrf(client)
    session = client.post("/planning/sessions", headers=headers).json()
    payloads = [
        {
            "origin": "DEL",
            "destination": "SIN",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
            "travelers": 2,
        },
        {"purpose": "leisure", "adults": 2, "children_ages": []},
        {
            "budget_minor": None,
            "currency": "INR",
            "travel_style": "balanced",
            "objective": "balanced",
            "points_priority": "best_value",
        },
        {
            "cabin": "economy",
            "max_stops": 0,
            "schedule": "no_preference",
            "checked_baggage": None,
            "airport_flexible": None,
            "seat": "no_preference",
        },
        {
            "lodging_styles": [],
            "neighborhood_priorities": [],
            "room_count": 1,
            "room_needs": [],
            "location_price_tradeoff": "no_preference",
        },
        {
            "pace": "moderate",
            "day_start": "normal",
            "evening_style": "flexible",
            "downtime_minutes": None,
            "transit_tolerance_minutes": None,
            "day_trip_appetite": "none",
        },
        {
            "interests": ["food"],
            "food_interests": [],
            "iconic_local_balance": "balanced",
            "nightlife": None,
            "shopping": None,
        },
        {
            "has_constraints": False,
            "dietary": [],
            "accessibility": [],
            "exclusions": [],
            "immovable_events": [],
        },
    ]
    for index, payload in enumerate(payloads):
        response = client.post(
            f"/planning/sessions/{session['id']}/answers",
            headers=headers,
            json={
                "question_id": session["current_question"]["id"],
                "expected_version": session["version"],
                "client_event_id": f"core-{index}",
                "payload": payload,
            },
        )
        assert response.status_code == 200
        session = response.json()
    confirmed = client.post(
        f"/planning/sessions/{session['id']}/confirm",
        headers=headers,
        json={
            "expected_version": session["version"],
            "brief": session["brief"],
            "client_event_id": "confirm-1",
        },
    )
    assert confirmed.status_code == 202
    replay = client.post(
        f"/planning/sessions/{session['id']}/confirm",
        headers=headers,
        json={
            "expected_version": confirmed.json()["version"],
            "brief": confirmed.json()["brief"],
            "client_event_id": "confirm-2",
        },
    )
    assert replay.status_code == 202
    assert replay.json()["job_id"] == confirmed.json()["job_id"]
    app.dependency_overrides.clear()


def test_confirmation_race_returns_one_durable_job_id(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path)
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    headers = _csrf(client)
    session = client.post("/planning/sessions", headers=headers).json()
    payloads = [
        (
            "trip_essentials",
            {
                "origin": "DEL",
                "destination": "SIN",
                "start_date": "2026-11-01",
                "end_date": "2026-11-05",
                "travelers": 1,
            },
        ),
        ("purpose_and_party", {"purpose": "leisure", "adults": 1, "children_ages": []}),
        (
            "budget_and_objective",
            {
                "budget_minor": None,
                "currency": "INR",
                "travel_style": "balanced",
                "objective": "balanced",
                "points_priority": "best_value",
            },
        ),
        (
            "flight_preferences",
            {
                "cabin": "economy",
                "max_stops": 0,
                "schedule": "no_preference",
                "checked_baggage": None,
                "airport_flexible": None,
                "seat": "no_preference",
            },
        ),
        (
            "stay_preferences",
            {
                "lodging_styles": [],
                "neighborhood_priorities": [],
                "room_count": 1,
                "room_needs": [],
                "location_price_tradeoff": "no_preference",
            },
        ),
        (
            "daily_rhythm",
            {
                "pace": "moderate",
                "day_start": "normal",
                "evening_style": "flexible",
                "downtime_minutes": None,
                "transit_tolerance_minutes": None,
                "day_trip_appetite": "none",
            },
        ),
        (
            "experiences_and_food",
            {
                "interests": ["food"],
                "food_interests": [],
                "iconic_local_balance": "balanced",
                "nightlife": None,
                "shopping": None,
            },
        ),
        (
            "hard_constraints",
            {
                "has_constraints": False,
                "dietary": [],
                "accessibility": [],
                "exclusions": [],
                "immovable_events": [],
            },
        ),
    ]
    for index, (question_id, payload) in enumerate(payloads):
        response = client.post(
            f"/planning/sessions/{session['id']}/answers",
            headers=headers,
            json={
                "question_id": question_id,
                "expected_version": session["version"],
                "client_event_id": f"race-core-{index}",
                "payload": payload,
            },
        )
        assert response.status_code == 200
        session = response.json()
    request = {"expected_version": session["version"], "brief": session["brief"]}

    def confirm(event_id: str) -> int | str:
        response = client.post(
            f"/planning/sessions/{session['id']}/confirm",
            headers=headers,
            json={**request, "client_event_id": event_id},
        )
        return response.status_code, response.json().get("job_id")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, ["race-a", "race-b"]))
    assert all(status == 202 for status, _ in results)
    assert len({job_id for _, job_id in results}) == 1
    app.dependency_overrides.clear()


def test_confirmation_start_failure_is_retryable(tmp_path: Path, monkeypatch) -> None:
    client, _ = _client(tmp_path)
    headers = _csrf(client)
    session = client.post("/planning/sessions", headers=headers).json()
    payloads = [
        (
            "trip_essentials",
            {
                "origin": "DEL",
                "destination": "SIN",
                "start_date": "2026-11-01",
                "end_date": "2026-11-05",
                "travelers": 1,
            },
        ),
        ("purpose_and_party", {"purpose": "leisure", "adults": 1, "children_ages": []}),
        (
            "budget_and_objective",
            {
                "budget_minor": None,
                "currency": "INR",
                "travel_style": "balanced",
                "objective": "balanced",
                "points_priority": "best_value",
            },
        ),
        (
            "flight_preferences",
            {
                "cabin": "economy",
                "max_stops": 0,
                "schedule": "no_preference",
                "checked_baggage": None,
                "airport_flexible": None,
                "seat": "no_preference",
            },
        ),
        (
            "stay_preferences",
            {
                "lodging_styles": [],
                "neighborhood_priorities": [],
                "room_count": 1,
                "room_needs": [],
                "location_price_tradeoff": "no_preference",
            },
        ),
        (
            "daily_rhythm",
            {
                "pace": "moderate",
                "day_start": "normal",
                "evening_style": "flexible",
                "downtime_minutes": None,
                "transit_tolerance_minutes": None,
                "day_trip_appetite": "none",
            },
        ),
        (
            "experiences_and_food",
            {
                "interests": ["food"],
                "food_interests": [],
                "iconic_local_balance": "balanced",
                "nightlife": None,
                "shopping": None,
            },
        ),
        (
            "hard_constraints",
            {
                "has_constraints": False,
                "dietary": [],
                "accessibility": [],
                "exclusions": [],
                "immovable_events": [],
            },
        ),
    ]
    for index, (question_id, payload) in enumerate(payloads):
        response = client.post(
            f"/planning/sessions/{session['id']}/answers",
            headers=headers,
            json={
                "question_id": question_id,
                "expected_version": session["version"],
                "client_event_id": f"retry-core-{index}",
                "payload": payload,
            },
        )
        assert response.status_code == 200
        session = response.json()
    monkeypatch.setattr(
        conversation,
        "_start_legacy_job",
        lambda session, job_id: (_ for _ in ()).throw(RuntimeError("start failed")),
    )
    request = {
        "expected_version": session["version"],
        "brief": session["brief"],
        "client_event_id": "retry-1",
    }
    failed = client.post(
        f"/planning/sessions/{session['id']}/confirm", headers=headers, json=request
    )
    assert failed.status_code == 503
    current = client.get(f"/planning/sessions/{session['id']}").json()
    assert current["status"] == "failed"
    assert current["planning_error"]
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    retry = client.post(
        f"/planning/sessions/{session['id']}/confirm",
        headers=headers,
        json={**request, "expected_version": current["version"], "client_event_id": "retry-2"},
    )
    assert retry.status_code == 202
    assert retry.json()["planning_job_id"]
    app.dependency_overrides.clear()


def test_back_persists_after_reload(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    headers = _csrf(client)
    session = client.post("/planning/sessions", headers=headers).json()
    sid = session["id"]
    first = {
        "question_id": "trip_essentials",
        "expected_version": 0,
        "client_event_id": "back-e1",
        "payload": {
            "origin": "DEL",
            "destination": "SIN",
            "start_date": "2026-11-01",
            "end_date": "2026-11-05",
            "travelers": 1,
        },
    }
    assert (
        client.post(f"/planning/sessions/{sid}/answers", json=first, headers=headers).status_code
        == 200
    )
    second = {
        "question_id": "purpose_and_party",
        "expected_version": 1,
        "client_event_id": "back-e2",
        "payload": {"purpose": "leisure", "adults": 1, "children_ages": []},
    }
    assert (
        client.post(f"/planning/sessions/{sid}/answers", json=second, headers=headers).status_code
        == 200
    )
    response = client.post(
        f"/planning/sessions/{sid}/back",
        headers=headers,
        json={"expected_version": 2, "client_event_id": "back-1"},
    )
    assert response.status_code == 200
    assert response.json()["current_question"]["id"] == "purpose_and_party"
    reopened = client.get(f"/planning/sessions/{sid}")
    assert reopened.status_code == 200
    assert "purpose_and_party" not in reopened.json()["answers"]
    app.dependency_overrides.clear()


def test_question_control_openapi_exposes_discriminator(tmp_path: Path) -> None:
    client, _ = _client(tmp_path)
    schema = client.get("/openapi.json").json()
    control = schema["components"]["schemas"]["QuestionOut"]["properties"]["control"]
    assert control["discriminator"]["propertyName"] == "type"
    assert "oneOf" in control
    app.dependency_overrides.clear()
