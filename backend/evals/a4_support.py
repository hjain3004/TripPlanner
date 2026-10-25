"""Shared fixtures for the A4 saved-trip API tests (not itself a test module).

Drives the *real* authenticated planning path: eight typed interview answers, an
explicit confirmation, and the existing confirmed-planning job running the real
pipeline with a scripted LLM against the seeded sample knowledge base. Nothing here
reaches the network or a paid service.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from accounts.store import AccountStore
from agents.llm import ScriptedLLMClient
from agents.models import (
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    ItineraryItem,
    TripSpec,
)
from api.auth import CSRF_COOKIE, CSRF_HEADER, get_store
from api.main import app
from core.models import UserWallet
from core.trip_models import OptimizationPrefs

PASSWORD = "long-password-123"

INTERVIEW_PAYLOADS: list[dict[str, Any]] = [
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


def signed_in_client(
    tmp_path: Path, email: str = "traveler@example.com"
) -> tuple[TestClient, AccountStore]:
    """A registered, logged-in client whose store lives in ``tmp_path``."""
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app, base_url="https://testserver")
    client.post("/auth/register", json={"email": email, "password": PASSWORD})
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return client, store


def second_client(email: str) -> TestClient:
    """Another signed-in user sharing the same overridden store."""
    client = TestClient(app, base_url="https://testserver")
    client.post("/auth/register", json={"email": email, "password": PASSWORD})
    client.post("/auth/login", json={"email": email, "password": PASSWORD})
    return client


def csrf(client: TestClient) -> dict[str, str]:
    token = client.cookies.get(CSRF_COOKIE)
    assert token is not None
    return {CSRF_HEADER: token}


def _spec(wallet: UserWallet) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 5),
        travelers=2,
        budget_minor=None,
        budget_currency="INR",
        style="balanced",
        interests=["food"],
        wallet=wallet,
        optimization=OptimizationPrefs(objective="max_savings"),
    )


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 11, 1),
                items=[
                    ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                    ItineraryItem(poi_id="sg-hawker-maxwell"),
                ],
            ),
            ItineraryDay(date=date(2026, 11, 2), items=[]),
            ItineraryDay(date=date(2026, 11, 3), items=[]),
            ItineraryDay(date=date(2026, 11, 4), items=[]),
        ],
    )


class PlanningKit:
    """A scripted LLM plus the monkeypatches that point the job at it.

    ``queue_run`` appends one full set of call-site responses; the pipeline's four
    call sites consume one of each per planning run. ``summary`` lets a test tell
    two runs apart.
    """

    def __init__(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        self.llm = ScriptedLLMClient({})
        monkeypatch.setattr(api_main, "get_llm", lambda: self.llm)
        monkeypatch.setattr(api_main, "get_booking_date", lambda: date(2026, 10, 24))
        monkeypatch.setattr(api_main, "get_trace_dir", lambda: tmp_path / "traces")

    def queue_run(self, *, wallet: UserWallet | None = None, summary: str = "Run summary.") -> None:
        scripts = self.llm._scripts
        scripts.setdefault("intake", []).append(_spec(wallet or UserWallet(card_ids=[])))
        scripts.setdefault("planner", []).append(_itinerary())
        scripts.setdefault("critic", []).append(CriticVerdict(passed=True))
        scripts.setdefault("explainer", []).append(
            ExplainerOutput(
                summary=summary,
                itinerary_overview="Grounded itinerary.",
                payment_overview="Grounded payments.",
            )
        )


def run_interview(client: TestClient) -> dict[str, Any]:
    """Create a session and answer all eight core questions; returns the review view."""
    headers = csrf(client)
    session: dict[str, Any] = client.post("/planning/sessions", headers=headers).json()
    for index, payload in enumerate(INTERVIEW_PAYLOADS):
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
        assert response.status_code == 200, response.text
        session = response.json()
    # A richer wallet can add optional adaptive questions (for example the points
    # strategy). They are skippable by design; delegate them until the brief is ready.
    for extra in range(4):
        if session.get("brief") is not None or session.get("current_question") is None:
            break
        response = client.post(
            f"/planning/sessions/{session['id']}/skip",
            headers=headers,
            json={
                "question_id": session["current_question"]["id"],
                "expected_version": session["version"],
                "client_event_id": f"skip-{extra}",
            },
        )
        assert response.status_code == 200, response.text
        session = response.json()
    return session


def confirm(
    client: TestClient, session: dict[str, Any], event: str = "confirm-1"
) -> dict[str, Any]:
    response = client.post(
        f"/planning/sessions/{session['id']}/confirm",
        headers=csrf(client),
        json={
            "expected_version": session["version"],
            "brief": session["brief"],
            "client_event_id": event,
        },
    )
    assert response.status_code == 202, response.text
    return dict(response.json())


def wait_for_job(client: TestClient, session_id: str, *, timeout_s: float = 60.0) -> dict[str, Any]:
    """Poll the session's job until it leaves queued/running."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/planning/sessions/{session_id}/job")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(0.05)
    raise AssertionError("planning job did not finish in time")


def finished_plan(
    client: TestClient, kit: PlanningKit, *, wallet: UserWallet | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Interview -> confirm -> real job. Returns (session, completed job body)."""
    kit.queue_run(wallet=wallet)
    session = confirm(client, run_interview(client))
    job = wait_for_job(client, session["id"])
    assert job["status"] == "complete", job
    return session, job
