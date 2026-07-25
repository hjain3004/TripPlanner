from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from agents.llm import ScriptedLLMClient
from agents.models import CriticVerdict, DraftItinerary, ExplainerOutput, ItineraryDay, PipelineStatus, TripSpec
from api.main import app, get_booking_date, get_kb, get_llm, get_trace_dir
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet


def _spec() -> TripSpec:
    return TripSpec(
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


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(date=date(2026, 8, 1), items=[]),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
            ItineraryDay(date=date(2026, 8, 4), items=[]),
        ],
    )


def _client(tmp_path) -> TestClient:
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    kb = load_kb(db_path)
    llm = ScriptedLLMClient(
        {
            "intake": [_spec()],
            "planner": [_itinerary()],
            "critic": [CriticVerdict(passed=True)],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded summary.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ],
        }
    )
    app.dependency_overrides[get_kb] = lambda: kb
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_booking_date] = lambda: date(2026, 7, 25)
    app.dependency_overrides[get_trace_dir] = lambda: tmp_path
    return TestClient(app)


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_plan_endpoint_returns_report(tmp_path) -> None:
    client = _client(tmp_path)
    response = client.post("/plan", json={"raw_request": "Delhi to Singapore Aug 1-5"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == PipelineStatus.OK
    assert payload["report"]["summary"] == "Grounded summary."
    assert payload["report"]["trace_id"] == payload["trace_id"]

    app.dependency_overrides.clear()
