from datetime import date
from core.trip_models import DraftItinerary, ItineraryDay, ItineraryItem
from core.itinerary.contracts import RouteMatrix, RouteCell, ItineraryConstraints
from core.itinerary.validate import validate_draft
from datetime import datetime, UTC
import pytest
from evals.test_i1_safety import _poi, _retrieval

def _matrix() -> RouteMatrix:
    return RouteMatrix(cells=[])

def _constraints() -> ItineraryConstraints:
    return ItineraryConstraints(max_daily_travel_min=120)

def test_a_stop_without_an_evidence_backed_place_id_is_rejected() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[ItineraryItem(poi_id="invented_place", start_time="09:00", end_time="10:00")])]
    )
    result = validate_draft(draft, _matrix(), _constraints(), _retrieval([]))
    assert result.valid is False
    assert any(r.code == "no_evidence_backed_place_id" for r in result.rejections)

def test_travel_time_that_does_not_fit_is_rejected_with_both_place_ids() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="09:00", end_time="10:00"),
            ItineraryItem(poi_id="p2", start_time="10:05", end_time="11:00")
        ])]
    )
    m = RouteMatrix(cells=[RouteCell(origin_place_id="p1", destination_place_id="p2", mode="transit", duration_min=10, distance_km=1, retrieved_at=datetime.now(UTC), source="geodesic_estimate", status="estimated", confidence=0.9)])
    result = validate_draft(draft, m, _constraints(), _retrieval([_poi("p1"), _poi("p2")]))
    bad = next(r for r in result.rejections if r.code == "travel_time_infeasible")
    assert bad.place_id and bad.detail

def test_overlap_is_rejected() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="09:00", end_time="10:00"),
            ItineraryItem(poi_id="p2", start_time="09:30", end_time="11:00")
        ])]
    )
    result = validate_draft(draft, _matrix(), _constraints(), _retrieval([_poi("p1"), _poi("p2")]))
    assert any(r.code == "overlap" for r in result.rejections)

def test_closed_day_is_rejected() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="09:00", end_time="10:00")
        ])]
    )
    poi = _poi("p1", closed_dates=["2026-08-03"])
    result = validate_draft(draft, _matrix(), _constraints(), _retrieval([poi]))
    assert any(r.code == "closed_day" for r in result.rejections)

def test_unknown_hours_timing_critical_is_rejected() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="09:00", end_time="10:00", start_hint="09:00") 
        ])]
    )
    poi = _poi("p1", regular_hours={})
    result = validate_draft(draft, _matrix(), _constraints(), _retrieval([poi]))
    assert any(r.code == "unknown_hours_timing_critical" for r in result.rejections)

def test_travel_budget_exceeded() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="09:00", end_time="10:00"),
            ItineraryItem(poi_id="p2", start_time="12:30", end_time="13:30")
        ])]
    )
    m = RouteMatrix(cells=[RouteCell(origin_place_id="p1", destination_place_id="p2", mode="transit", duration_min=150, distance_km=1, retrieved_at=datetime.now(UTC), source="geodesic_estimate", status="estimated", confidence=0.9)])
    result = validate_draft(draft, m, _constraints(), _retrieval([_poi("p1"), _poi("p2")]))
    assert any(r.code == "travel_budget_exceeded" for r in result.rejections)

def test_accessibility_excluded_is_rejected() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="09:00", end_time="10:00")
        ])]
    )
    poi = _poi("p1", tags=["inaccessible"])
    result = validate_draft(draft, _matrix(), _constraints(), _retrieval([poi]))
    # Assuming accessibility logic checks tags or we pass an accessibility profile. 
    # Let's say validate_draft looks for 'inaccessible' tag.
    assert any(r.code == "accessibility_excluded" for r in result.rejections)

def test_fixed_window_violated() -> None:
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[
            ItineraryItem(poi_id="p1", start_time="11:00", end_time="12:00")
        ])]
    )
    poi = _poi("p1")
    # We need a way to say a POI is a fixed window event, maybe via tags?
    poi.tags = ["fixed_window_0900_1000"]
    result = validate_draft(draft, _matrix(), _constraints(), _retrieval([poi]))
    assert any(r.code == "fixed_window_violated" for r in result.rejections)
