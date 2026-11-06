from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from agents.llm import ScriptedLLMClient
from agents.models import CriticVerdict, DraftItinerary, ExplainerOutput, ItineraryDay, TripSpec
from api.main import (
    app,
    get_booking_date,
    get_kb,
    get_llm,
    get_trace_dir,
    get_weather_context_service,
)
from api.post_plan_service import parse_stored_report
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from gateway.weather.adapter import OpenMeteoWeatherAdapter
from gateway.weather.budget import WeatherCallBudget
from gateway.weather.contracts import WeatherLocation
from gateway.weather.planning import WeatherContextService
from gateway.weather.transport import FixtureWeatherTransport

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)


def _service(
    tmp_path: Path, *, scenario: str = "singapore_ok", enabled: bool = True
) -> WeatherContextService:
    tmp_path.mkdir(parents=True, exist_ok=True)
    adapter = OpenMeteoWeatherAdapter(
        transport=FixtureWeatherTransport(scenario),
        budget=WeatherCallBudget(tmp_path / "weather.sqlite"),
        plan_id="test-plan",
        now=lambda: NOW,
        enabled=enabled,
    )
    return WeatherContextService(
        adapter,
        location_provider=lambda _iata: WeatherLocation(
            latitude=1.29, longitude=103.85, label="Singapore"
        ),
        now=lambda: NOW,
    )


def test_forecast_context_is_typed_attributed_and_replayable(tmp_path: Path) -> None:
    outcome = _service(tmp_path).get_context_sync(
        destination_iata="SIN", trip_start=date(2026, 10, 15), trip_end=date(2026, 10, 20)
    )
    assert outcome.status == "available"
    assert outcome.requested_start == date(2026, 10, 15)
    assert outcome.evidence[0].meta.attribution_url == "https://open-meteo.com/"
    assert {e.meta.origin for e in outcome.evidence} == {"fixture_synthetic"}
    assert all(e.meta.needs_verification for e in outcome.evidence)


def test_historical_and_climate_contexts_keep_distinct_labels(tmp_path: Path) -> None:
    historical = _service(tmp_path / "historical").get_context_sync(
        destination_iata="SIN", trip_start=date(2026, 9, 1), trip_end=date(2026, 9, 7)
    )
    climate = _service(tmp_path / "climate").get_context_sync(
        destination_iata="SIN", trip_start=date(2027, 2, 1), trip_end=date(2027, 2, 7)
    )
    assert historical.status == "available"
    assert historical.evidence[0].kind == "historical_observation"
    assert climate.status == "available"
    assert climate.evidence[0].kind == "climate_summary"
    assert climate.evidence[0].meta.is_forecast is False
    assert "not a forecast" in climate.evidence[0].caveat.lower()


def test_unavailable_and_unsupported_windows_are_explicit(tmp_path: Path) -> None:
    unavailable = _service(tmp_path / "down", scenario="singapore_unavailable").get_context_sync(
        destination_iata="SIN", trip_start=date(2026, 10, 15), trip_end=date(2026, 10, 18)
    )
    too_long = _service(tmp_path / "long").get_context_sync(
        destination_iata="SIN", trip_start=date(2027, 2, 1), trip_end=date(2027, 4, 30)
    )
    assert unavailable.status == "unavailable"
    assert unavailable.unavailable is not None
    assert unavailable.unavailable.message == "Weather context unavailable"
    assert too_long.status == "unavailable"
    assert "unsupported_date_window" in too_long.limitations


def test_old_saved_report_without_weather_context_remains_readable(tmp_path: Path) -> None:
    from agents.pipeline import run_pipeline
    from evals.test_m2_api import _itinerary, _spec

    kb_path = tmp_path / "kb.sqlite"
    seed_database(SEEDS_DIR, kb_path)
    report = run_pipeline(
        "Delhi to Singapore",
        load_kb(kb_path),
        ScriptedLLMClient(
            {
                "intake": [_spec()],
                "planner": [_itinerary()],
                "critic": [CriticVerdict(passed=True)],
                "explainer": [
                    ExplainerOutput(
                        summary="s", itinerary_overview="i", payment_overview="p"
                    )
                ],
            }
        ),
        booking_date=date(2026, 7, 25),
    ).report
    assert report is not None
    stored = report.model_dump(mode="json")
    stored.pop("weather_context")
    reopened = parse_stored_report(json.dumps(stored))
    assert reopened.trip_spec == report.trip_spec
    assert reopened.weather_context.status == "unavailable"


def test_actual_plan_endpoint_returns_weather_context(tmp_path: Path) -> None:
    days = [ItineraryDay(date=date(2026, 9, 1) + timedelta(days=i)) for i in range(6)]
    spec = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 7),
        travelers=2,
        budget_minor=25_000_000,
        style="balanced",
        wallet=UserWallet(card_ids=["hdfc-infinia"], points_balances={"voyager-prime": 140_000}),
    )
    seed_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, seed_path)
    kb = load_kb(seed_path)
    app.dependency_overrides.update(
        {
            get_kb: lambda: kb,
            get_llm: lambda: ScriptedLLMClient(
                {
                    "intake": [spec],
                    "planner": [DraftItinerary(hotel_area_id="marina_bay", days=days)],
                    "critic": [CriticVerdict(passed=True)],
                    "explainer": [
                        ExplainerOutput(summary="s", itinerary_overview="i", payment_overview="p")
                    ],
                }
            ),
            get_booking_date: lambda: date(2026, 8, 1),
            get_trace_dir: lambda: tmp_path,
            get_weather_context_service: lambda: _service(
                tmp_path / "api", scenario="singapore_ok"
            ),
        }
    )
    try:
        with TestClient(app) as client:
            response = client.post("/plan", json={"raw_request": "Delhi to Singapore"})
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                job: dict[str, Any] = client.get(f"/plan/{job_id}").json()
                if job["status"] == "complete":
                    break
                time.sleep(0.05)
            assert job["status"] == "complete"
            assert job["report"]["weather_context"]["status"] == "available"
            assert job["report"]["weather_context"]["evidence"][0]["meta"]["origin"] == (
                "fixture_synthetic"
            )
            reopened = parse_stored_report(json.dumps(job["report"]))
            assert reopened.weather_context.status == "available"
            assert reopened.weather_context.evidence[0].meta.retrieved_at == NOW
    finally:
        app.dependency_overrides.clear()


def test_actual_plan_endpoint_completes_when_weather_is_disabled(tmp_path: Path) -> None:
    from evals.test_m2_api import _client, _poll_job

    client = _client(tmp_path)
    try:
        response = client.post("/plan", json={"raw_request": "Delhi to Singapore"})
        assert response.status_code == 202
        job = _poll_job(client, response.json()["job_id"])
        assert job["status"] == "complete"
        assert job["report"]["weather_context"]["status"] == "unavailable"
        assert job["report"]["weather_context"]["unavailable"]["code"] == "provider_disabled"
    finally:
        app.dependency_overrides.clear()


def test_cp4_same_trip_edit_preserves_weather_without_dispatch(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_edit
    from core.trip_models import RemoveItem
    from evals.test_cp4_recompute import _kb, seed_report, with_admitted_prices

    kb = _kb(tmp_path)
    report = with_admitted_prices(seed_report(kb), kb).model_copy(
        update={"weather_context": _service(tmp_path / "weather").get_context_sync(
            destination_iata="SIN", trip_start=date(2026, 9, 1), trip_end=date(2026, 9, 5)
        )}
    )
    result = recompute_confirmed_edit(
        report, RemoveItem(poi_id="sg-hawker-maxwell", day_index=0), kb=kb, now=NOW
    )
    assert result.weather_context == report.weather_context


def test_cp4_trip_change_invalidates_weather_without_dispatch(tmp_path: Path) -> None:
    from agents.post_plan_execution import recompute_confirmed_report
    from evals.test_cp4_recompute import _kb, seed_report, with_admitted_prices

    kb = _kb(tmp_path)
    report = with_admitted_prices(seed_report(kb), kb)
    weather = _service(tmp_path / "weather").get_context_sync(
        destination_iata="SIN",
        trip_start=report.trip_spec.start_date,
        trip_end=report.trip_spec.end_date,
    )
    report = report.model_copy(update={"weather_context": weather})
    changed = report.trip_spec.model_copy(update={"destination_city": "BOM"})
    result = recompute_confirmed_report(
        report, itinerary=report.itinerary, spec=changed, kb=kb, now=NOW
    )
    assert result.weather_context.status == "unavailable"
    assert result.weather_context != report.weather_context
