from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agents.llm import ScriptedLLMClient
from agents.models import (
    PIPELINE_STAGES,
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    TripSpec,
)
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


def _client(tmp_path: Path) -> TestClient:
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


def _poll_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = client.get(f"/plan/{job_id}")
        assert resp.status_code == 200
        job: dict[str, Any] = resp.json()
        if job["status"] in ("complete", "needs_clarification", "failed"):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not reach terminal status within {timeout}s")


def test_health_endpoint() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_plan_endpoint_returns_job_id_then_completes(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/plan", json={"raw_request": "Delhi to Singapore Aug 1-5"})

    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert isinstance(job_id, str) and len(job_id) > 0

    job = _poll_job(client, job_id)
    assert job["status"] == "complete", f"Expected complete, got {job}"
    assert job["stage"] == "explaining"
    assert job["stage_index"] == 6
    assert job["stages_total"] == len(PIPELINE_STAGES)
    assert job["report"]["summary"] == "Grounded summary."
    assert job["report"]["trace_id"] is not None

    app.dependency_overrides.clear()


def test_plan_endpoint_rejects_missing_raw_request(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/plan", json={})
    assert response.status_code == 422

    app.dependency_overrides.clear()


def test_get_unknown_job_returns_404() -> None:
    with TestClient(app) as client:
        response = client.get("/plan/unknownjobid123")
    assert response.status_code == 404


def test_plan_accepts_wallet_in_request(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/plan",
        json={
            "raw_request": "Delhi to Singapore Aug 1-5",
            "wallet": {
                "card_ids": ["amex-platinum"],
                "points_balances": {"star-alliance": 50000},
            },
        },
    )

    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = _poll_job(client, job_id)
    assert job["status"] == "complete"

    app.dependency_overrides.clear()
