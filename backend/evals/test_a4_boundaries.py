"""A4 Task 8 — error mapping and boundary coverage for the saved-trip API.

What these pin: the closed route surface, authentication and CSRF on every route,
the order of the error mapper (typed errors are ``ValueError`` subclasses, so the
broad 422 arm must come last), that no driver or traceback text ever reaches a
client, and that the legacy unauthenticated ``/plan`` is untouched.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

import accounts.store as store_module
from accounts.store import (
    ReportTooLargeError,
    RevisionLimitReachedError,
    TripIdempotencyConflictError,
    TripLimitReachedError,
    TripRevisionConflictError,
    UnknownRevisionError,
    UnknownTripError,
)
from agents.llm import ScriptedLLMClient
from agents.models import (
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    TripSpec,
)
from api import saved_trips
from api.main import app, get_booking_date, get_kb, get_llm, get_trace_dir
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from evals.a4_support import PlanningKit, csrf, finished_plan, signed_in_client

FORBIDDEN_IN_BODIES = ("sqlite", "sqlalchemy", "operationalerror", "traceback")

EXPECTED_ROUTES = {
    ("POST", "/account/trips"),
    ("GET", "/account/trips"),
    ("GET", "/account/trips/{trip_id}"),
    ("DELETE", "/account/trips/{trip_id}"),
    ("POST", "/account/trips/{trip_id}/revisions"),
    ("GET", "/account/trips/{trip_id}/revisions/{revision}"),
    ("POST", "/account/trips/{trip_id}/reruns"),
    ("GET", "/account/trips/{trip_id}/reruns/{job_id}"),
}


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _saved_routes() -> set[tuple[str, str]]:
    """The documented surface, read from OpenAPI (FastAPI nests included routers)."""
    return {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/account/trips")
        for method in operations
    }


VALID_BODIES = {
    "/account/trips": {"session_id": "s", "client_event_id": "e"},
    "/account/trips/{trip_id}/revisions": {"session_id": "s", "client_event_id": "e"},
    "/account/trips/{trip_id}/reruns": {"client_event_id": "e"},
}


def _url(path: str) -> str:
    return path.replace("{trip_id}", "t").replace("{revision}", "1").replace("{job_id}", "j")


def _no_leak(text: str) -> None:
    lowered = text.lower()
    for word in FORBIDDEN_IN_BODIES:
        assert word not in lowered, f"{word!r} leaked into a response body"


def _raiser(exc: BaseException) -> Any:
    def call(*_: Any, **__: Any) -> None:
        raise exc

    return call


def _saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, Any, dict[str, Any], str]:
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


# --- the surface is closed, authenticated, CSRF-protected ---------------------------------- #


def test_the_saved_trip_route_inventory_is_exactly_the_documented_one() -> None:
    assert _saved_routes() == EXPECTED_ROUTES


def test_every_route_requires_authentication() -> None:
    with TestClient(app) as anonymous:
        for method, path in sorted(EXPECTED_ROUTES):
            response = anonymous.request(method, _url(path), json=VALID_BODIES.get(path))
            assert response.status_code == 401, (method, path, response.status_code)


def test_every_mutating_route_requires_csrf(tmp_path: Path) -> None:
    client, _store = signed_in_client(tmp_path)
    mutating = sorted(r for r in EXPECTED_ROUTES if r[0] in {"POST", "DELETE"})
    assert len(mutating) == 4
    for method, path in mutating:
        # A valid body, because CSRF is checked by the handler after validation.
        response = client.request(method, _url(path), json=VALID_BODIES.get(path))
        assert response.status_code == 403, (method, path, response.status_code)


def test_request_models_reject_unknown_and_identity_fields() -> None:
    for model in (saved_trips.SaveTripIn, saved_trips.AppendRevisionIn, saved_trips.RerunIn):
        assert model.model_config.get("extra") == "forbid", model.__name__
        assert "user_id" not in model.model_fields


# --- the mapper: order matters ---------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (UnknownTripError("x"), 404, "TRIP_NOT_FOUND"),
        (UnknownRevisionError("x"), 404, "REVISION_NOT_FOUND"),
        (TripIdempotencyConflictError("x"), 409, "IDEMPOTENCY_KEY_REUSED"),
        (TripLimitReachedError("x"), 409, "TRIP_LIMIT_REACHED"),
        (RevisionLimitReachedError("x"), 409, "REVISION_LIMIT_REACHED"),
        (TripRevisionConflictError("x"), 409, "TRIP_REVISION_CONFLICT"),
        (ReportTooLargeError("x"), 413, "REPORT_TOO_LARGE"),
        (
            OperationalError("SELECT 1", {}, sqlite3.OperationalError("database is locked")),
            503,
            "SAVED_TRIPS_UNAVAILABLE",
        ),
        (ValueError("anything else"), 422, "SAVED_TRIP_INVALID"),
    ],
)
def test_each_typed_failure_maps_to_its_own_status_never_the_catch_all(
    exc: BaseException, status: int, code: str
) -> None:
    with pytest.raises(HTTPException) as caught:
        saved_trips._handle(_raiser(exc))

    assert caught.value.status_code == status
    assert caught.value.detail["code"] == code  # type: ignore[index]
    _no_leak(str(caught.value.detail))


# --- nothing from the driver reaches a client ------------------------------------------------- #


def test_error_bodies_never_carry_driver_or_traceback_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit)
    headers = csrf(client)
    body = {"session_id": session["id"], "client_event_id": "e1"}

    unprocessable = client.post("/account/trips", headers=headers, json={**body, "x": 1})  # 422
    monkeypatch.setattr(store_module, "MAX_REPORT_BYTES", 16)
    too_large = client.post("/account/trips", headers=headers, json=body)  # 413
    monkeypatch.setattr(store_module, "MAX_REPORT_BYTES", 2 * 1024 * 1024)
    assert client.post("/account/trips", headers=headers, json=body).status_code == 201
    second = {**body, "client_event_id": "e2"}
    conflict = client.post("/account/trips", headers=headers, json=second)  # 409
    locked = OperationalError("SELECT 1", {}, sqlite3.OperationalError("database is locked"))
    monkeypatch.setattr(store, "trip_overviews", _raiser(locked))
    unavailable = client.get("/account/trips")  # 503
    monkeypatch.setattr(store, "trip_overviews", _raiser(RuntimeError("sqlite3.OperationalError")))
    with TestClient(app, base_url="https://testserver", raise_server_exceptions=False) as quiet:
        quiet.cookies.update(client.cookies)
        broken = quiet.get("/account/trips")  # 500

    assert unprocessable.status_code == 422
    assert too_large.status_code == 413 and too_large.json()["detail"]["code"] == "REPORT_TOO_LARGE"
    assert conflict.status_code == 409
    assert unavailable.status_code == 503
    assert broken.status_code == 500
    for response in (unprocessable, too_large, conflict, unavailable, broken):
        _no_leak(response.text)


# --- the codes the milestone promises ------------------------------------------------------------


def test_the_trip_limit_is_a_409_and_a_retry_of_the_last_save_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    monkeypatch.setattr(store_module, "MAX_SAVED_TRIPS", 1)
    first, _ = finished_plan(client, kit)
    second, _ = finished_plan(client, kit)
    headers = csrf(client)
    one = {"session_id": first["id"], "client_event_id": "save-1"}
    other = {"session_id": second["id"], "client_event_id": "save-2"}

    assert client.post("/account/trips", headers=headers, json=one).status_code == 201
    full = client.post("/account/trips", headers=headers, json=other)
    retry = client.post("/account/trips", headers=headers, json=one)

    assert full.status_code == 409 and full.json()["detail"]["code"] == "TRIP_LIMIT_REACHED"
    assert retry.status_code == 201  # replay beats the limit it consumed


def test_the_revision_limit_is_a_409_on_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, session, trip_id = _saved(tmp_path, monkeypatch)
    monkeypatch.setattr(store_module, "MAX_REVISIONS_PER_TRIP", 1)

    response = client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVISION_LIMIT_REACHED"


def test_a_revision_number_collision_surfaces_as_a_409(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, session, trip_id = _saved(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "add_revision", _raiser(TripRevisionConflictError("collision")))

    response = client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "a"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRIP_REVISION_CONFLICT"


# --- the legacy /plan is untouched ---------------------------------------------------------------


def test_the_legacy_unauthenticated_plan_has_no_saved_trip_side_effect(tmp_path: Path) -> None:
    owner, store = signed_in_client(tmp_path)  # a signed-in user exists, but /plan ignores them
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    kb = load_kb(db_path)
    spec = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature"],
        wallet=UserWallet(card_ids=["hdfc-infinia"], points_balances={"voyager-prime": 140000}),
    )
    itinerary = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[ItineraryDay(date=date(2026, 8, d), items=[]) for d in (1, 2, 3, 4)],
    )
    llm = ScriptedLLMClient(
        {
            "intake": [spec],
            "planner": [itinerary],
            "critic": [CriticVerdict(passed=True)],
            "explainer": [
                ExplainerOutput(summary="s", itinerary_overview="i", payment_overview="p")
            ],
        }
    )
    app.dependency_overrides[get_kb] = lambda: kb
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_booking_date] = lambda: date(2026, 7, 25)
    app.dependency_overrides[get_trace_dir] = lambda: tmp_path

    with TestClient(app) as anonymous:  # no cookie: /plan stays open
        started = anonymous.post("/plan", json={"raw_request": "Delhi to Singapore Aug 1-5"})
        assert started.status_code == 202
        job: dict[str, Any] = {}
        for _ in range(200):
            job = anonymous.get(f"/plan/{started.json()['job_id']}").json()
            if job["status"] in {"complete", "failed", "needs_clarification"}:
                break

    assert job["status"] == "complete"
    assert job["report"]["trip_spec"]["wallet"]["card_ids"] == ["hdfc-infinia"]  # caller-supplied
    assert owner.get("/account/trips").json() == []
    assert store.trip_mutation_events(owner.get("/auth/me").json()["id"]) == []
