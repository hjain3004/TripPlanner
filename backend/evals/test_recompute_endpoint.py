from __future__ import annotations

import time
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents.models import (
    FinalReport,
    MoveItem,
    RecomputeRequest,
    RemoveItem,
    SectionFreshness,
    SectionState,
)
from agents.recompute import recompute_itinerary
from api.main import app, get_kb
from core.db import load_kb
from core.models import UserWallet
from core.trip_models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec


class RaisingLLMClient:
    """An LLMClient that strictly raises on any call to prove no LLM is invoked."""

    def complete_json(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("recompute path must NEVER invoke an LLM!")


def _fixture_spec() -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        travelers=2,
        style="balanced",
        interests=["food", "nature"],
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
    )


def _fixture_itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="area:marina-bay",
        days=[
            ItineraryDay(
                date=date(2026, 9, 1),
                items=[
                    ItineraryItem(poi_id="poi:gardens-by-the-bay"),
                    ItineraryItem(poi_id="poi:cloud-forest"),
                ],
            ),
            ItineraryDay(
                date=date(2026, 9, 2),
                items=[
                    ItineraryItem(poi_id="poi:national-gallery"),
                    ItineraryItem(poi_id="poi:lau-pa-sat"),
                ],
            ),
            ItineraryDay(
                date=date(2026, 9, 3),
                items=[
                    ItineraryItem(poi_id="poi:singapore-flyer"),
                ],
            ),
            ItineraryDay(
                date=date(2026, 9, 4),
                items=[
                    ItineraryItem(poi_id="poi:night-safari"),
                ],
            ),
        ],
    )


def test_recompute_makes_no_llm_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The headline test: recompute completes without invoking any LLM."""
    # Monkeypatch LLMClient to fail immediately if instantiated or called
    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("recompute path must NEVER invoke an LLM!")

    monkeypatch.setattr("agents.llm.LLMClient.complete_json", _raise, raising=False)

    kb = load_kb()
    spec = _fixture_spec()
    itin = _fixture_itinerary()
    edit = MoveItem(
        poi_id="poi:singapore-flyer",
        from_day_index=2,
        to_day_index=0,
        position=1,
    )

    report = recompute_itinerary(spec, itin, edit, kb, booking_date=date(2026, 8, 1))

    assert isinstance(report, FinalReport)
    # Check that item moved in the resulting report
    day0_ids = [item.poi_id for item in report.itinerary.days[0].items]
    assert "poi:singapore-flyer" in day0_ids
    assert day0_ids[1] == "poi:singapore-flyer"
    # Money numbers are freshly computed
    assert report.budget_totals.gross_minor > 0
    assert report.optimizer_result.gross_minor > 0


def test_recompute_surfaces_warnings_without_dropping_item() -> None:
    """Moving an item to a day where it is closed surfaces a warning instead of dropping it."""
    kb = load_kb()
    spec = _fixture_spec()
    itin = _fixture_itinerary()

    # Move national gallery to day 0 (or similar)
    edit = MoveItem(
        poi_id="poi:national-gallery",
        from_day_index=1,
        to_day_index=0,
        position=0,
    )
    report = recompute_itinerary(spec, itin, edit, kb, booking_date=date(2026, 8, 1))

    day0_ids = [item.poi_id for item in report.itinerary.days[0].items]
    assert "poi:national-gallery" in day0_ids


def test_recompute_latency_under_500ms() -> None:
    """Recompute should execute in sub-second time (target < 500ms)."""
    kb = load_kb()
    spec = _fixture_spec()
    itin = _fixture_itinerary()
    edit = RemoveItem(
        poi_id="poi:cloud-forest",
        day_index=0,
    )

    t0 = time.perf_counter()
    report = recompute_itinerary(spec, itin, edit, kb, booking_date=date(2026, 8, 1))
    duration_ms = (time.perf_counter() - t0) * 1000

    assert isinstance(report, FinalReport)
    assert duration_ms < 500.0, f"Recompute took {duration_ms:.2f}ms (expected < 500ms)"


def test_recompute_fastapi_endpoint() -> None:
    """Fastapi POST /plan/recompute endpoint returns HTTP 200 with FinalReport."""
    kb = load_kb()
    app.dependency_overrides[get_kb] = lambda: kb

    client = TestClient(app)
    spec = _fixture_spec()
    itin = _fixture_itinerary()
    req = RecomputeRequest(
        trip_spec=spec,
        itinerary=itin,
        edit=MoveItem(
            poi_id="poi:singapore-flyer",
            from_day_index=2,
            to_day_index=0,
            position=0,
        ),
    )

    resp = client.post("/plan/recompute", json=req.model_dump(mode="json"))
    assert resp.status_code == 200
    data = resp.json()
    assert "trip_spec" in data
    assert "itinerary" in data
    assert "optimizer_result" in data
    assert data["itinerary"]["days"][0]["items"][0]["poi_id"] == "poi:singapore-flyer"
    assert data["freshness"]["prose"] == "stale"
    assert data["freshness"]["budget"] == "recomputed"
    assert data["freshness"]["edit_count"] == 1


def test_freshness_states_after_recompute() -> None:
    """Initial report has fresh state; recompute marks budget recomputed and prose stale."""
    kb = load_kb()
    spec = _fixture_spec()
    itin = _fixture_itinerary()
    edit1 = RemoveItem(poi_id="poi:cloud-forest", day_index=0)

    # Initial state verification (anti-vacuity)
    fresh_default = SectionFreshness()
    assert fresh_default.prose == SectionState.FRESH
    assert fresh_default.budget == SectionState.FRESH
    assert fresh_default.edit_count == 0

    # 1st Recompute
    rep1 = recompute_itinerary(spec, itin, edit1, kb, booking_date=date(2026, 8, 1))
    assert rep1.freshness.budget == SectionState.RECOMPUTED
    assert rep1.freshness.payment_strategy == SectionState.RECOMPUTED
    assert rep1.freshness.itinerary == SectionState.RECOMPUTED
    assert rep1.freshness.prose == SectionState.STALE
    assert rep1.freshness.critic_verdict == SectionState.STALE
    assert rep1.freshness.edit_count == 1

    # 2nd Recompute with previous_freshness passed
    edit2 = RemoveItem(poi_id="poi:lau-pa-sat", day_index=1)
    rep2 = recompute_itinerary(
        spec,
        rep1.itinerary,
        edit2,
        kb,
        booking_date=date(2026, 8, 1),
        previous_freshness=rep1.freshness,
    )
    assert rep2.freshness.edit_count == 2
    assert rep2.freshness.prose == SectionState.STALE


def test_refresh_prose_endpoint() -> None:
    """POST /plan/refresh-prose refreshes prose while keeping budget state and edit count."""
    kb = load_kb()
    app.dependency_overrides[get_kb] = lambda: kb

    client = TestClient(app)
    spec = _fixture_spec()
    itin = _fixture_itinerary()

    # Recompute first
    req1 = RecomputeRequest(
        trip_spec=spec,
        itinerary=itin,
        edit=RemoveItem(poi_id="poi:cloud-forest", day_index=0),
    )
    res1 = client.post("/plan/recompute", json=req1.model_dump(mode="json")).json()
    assert res1["freshness"]["prose"] == "stale"
    assert res1["freshness"]["edit_count"] == 1

    # Refresh prose
    refresh_req = {
        "trip_spec": res1["trip_spec"],
        "itinerary": res1["itinerary"],
        "kernel_result": {
            "optimizer_result": res1["optimizer_result"],
            "transfer_advice": res1["transfer_advice"],
        },
        "previous_freshness": res1["freshness"],
    }
    res2 = client.post("/plan/refresh-prose", json=refresh_req)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["freshness"]["prose"] == "fresh"
    assert data2["freshness"]["budget"] == "recomputed"
    assert data2["freshness"]["edit_count"] == 1

