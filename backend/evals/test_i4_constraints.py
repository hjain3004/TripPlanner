# ruff: noqa: E501, E402
from datetime import UTC, date, datetime

from core.itinerary.contracts import ItineraryConstraints, RouteCell, RouteMatrix
from core.itinerary.validate import validate_draft
from core.trip_models import DraftItinerary, ItineraryDay, ItineraryItem
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

def test_the_objective_contains_no_money_or_points_arithmetic() -> None:
    import ast
    import inspect

    from core.itinerary import greedy
    src = inspect.getsource(greedy.score_draft)
    tree = ast.parse(src)
    banned = {"minor", "cents", "points", "reward", "fee", "cashback", "bps"}
    names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (names & banned), f"money math in the composer objective: {names & banned}"

def test_a_must_do_outranks_an_optional_filler() -> None:
    from core.itinerary.greedy import GreedyComposer
    from core.models import UserWallet
    from core.trip_models import TripSpec
    spec_with_must_do = TripSpec(
        home_country="IN", origin_city="DEL", destination_city="SIN", 
        start_date=date(2026, 8, 3), end_date=date(2026, 8, 7), travelers=2,
        budget_minor=25000000, budget_currency="INR", style="balanced",
        interests=["must_do_tag"], pace="moderate",
        wallet=UserWallet(card_ids=[])
    )
    p_must = _poi("pl_must", tags=["must_do_tag"])
    p_opt = _poi("pl_opt", tags=["other"])
    ctx = _retrieval([p_must, p_opt])
    
    result = GreedyComposer().compose(spec_with_must_do, ctx, _matrix(), _constraints())
    scheduled = [i.poi_id for d in result.itinerary.days for i in d.items]
    assert "pl_must" in scheduled

def test_fresher_evidence_is_preferred_between_equal_candidates() -> None:
    from core.itinerary.greedy import GreedyComposer
    from core.models import UserWallet
    from core.trip_models import TripSpec
    s = TripSpec(
        home_country="IN", origin_city="DEL", destination_city="SIN", 
        start_date=date(2026, 8, 3), end_date=date(2026, 8, 7), travelers=2,
        budget_minor=25000000, budget_currency="INR", style="balanced",
        interests=["nature"], pace="moderate",
        wallet=UserWallet(card_ids=[])
    )
    p_fresh = _poi("pl_fresh", tags=["nature"])
    p_fresh.provenance.last_verified = date(2026, 8, 1)
    p_stale = _poi("pl_stale", tags=["nature"])
    p_stale.provenance.last_verified = date(2026, 1, 1)
    ctx = _retrieval([p_stale, p_fresh])
    
    result = GreedyComposer().compose(s, ctx, _matrix(), _constraints())
    scheduled = [i.poi_id for d in result.itinerary.days for i in d.items]
    
    assert "pl_fresh" in scheduled
    assert scheduled.index("pl_fresh") <= scheduled.index("pl_stale") if "pl_stale" in scheduled else True

def test_scoring_is_deterministic_across_repeated_calls() -> None:
    from core.itinerary.greedy import score_draft
    draft = DraftItinerary(
        hotel_area_id="a",
        days=[ItineraryDay(date=date(2026, 8, 3), items=[ItineraryItem(poi_id="p1")])]
    )
    ctx = _retrieval([_poi("p1")])
    a = score_draft(draft, _matrix(), _constraints(), ctx)
    b = score_draft(draft, _matrix(), _constraints(), ctx)
    assert a == b
