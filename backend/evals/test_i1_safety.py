"""Tests for T4 (hours feasibility) and T5 (travel-time budget) in the composer.

Uses synthetic fixtures with varied provenance (§4 of the I1 plan).
Does NOT expand the seed set.
"""

from __future__ import annotations

from datetime import date

from agents.models import DraftItinerary, RetrievalContext, TripSpec
from core.models import POI, Area, Channel, Provenance, TimezoneAwareHours, UserWallet
from core.itinerary.compose import (
    ComposerResult,
    compose_itinerary,
    day_travel_minutes,
    estimate_travel_min,
    fallback_itinerary,
    haversine_km,
    check_poi_hours,
    validate_day_travel_budget,
)

PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 25),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=0.5,
)


def _poi(
    id_: str,
    lat: float = 1.2816,
    lon: float = 103.8636,
    regular_hours: dict[int, list[str]] | None = None,
    closed_dates: list[str] | None = None,
    area: str = "marina_bay",
    tags: list[str] | None = None,
) -> POI:
    """Build a synthetic POI for testing."""
    if regular_hours is None:
        regular_hours = {i: ["09:00-21:00"] for i in range(7)}
    return POI(
        id=id_,
        city="Singapore",
        name=id_.replace("-", " ").title(),
        tags=tags or ["nature"],
        typical_duration_min=60,
        price_minor=0,
        currency="SGD",
        lat=lat,
        lon=lon,
        area=area,
        open_hours=TimezoneAwareHours(
            timezone="Asia/Singapore",
            regular_hours=regular_hours,
            closed_dates=closed_dates or [],
        ),
        booking_channel=Channel.OTA_GENERIC,
        description="Synthetic test POI.",
        provenance=PROV,
    )


def _area(id_: str = "marina_bay", tags: list[str] | None = None) -> Area:
    return Area(
        id=id_,
        city="Singapore",
        name=id_.replace("_", " ").title(),
        good_for_tags=tags or ["nature"],
        centrality_score=0.9,
        provenance=PROV,
    )


def _spec(
    start: date = date(2026, 8, 3),
    nights: int = 4,
    pace: str = "moderate",
    interests: list[str] | None = None,
) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=start,
        end_date=date.fromordinal(start.toordinal() + nights),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=interests or ["nature"],
        pace=pace,
        wallet=UserWallet(card_ids=["hdfc-infinia"], points_balances={}),
    )


def _retrieval(pois: list[POI], areas: list[Area] | None = None) -> RetrievalContext:
    return RetrievalContext(
        pois=pois,
        areas=areas or [_area()],
        poi_rows=[f"{p.id} | {p.name}" for p in pois],
        area_rows=["marina_bay | Marina Bay"],
    )


# ------------------------------------------------------------------ #
# T4 — Opening-hours feasibility                                      #
# ------------------------------------------------------------------ #


def test_check_poi_hours_rejects_closed_weekday() -> None:
    """POI with regular_hours[0]=[] is closed on Monday."""
    poi = _poi("closed-mon", regular_hours={0: [], 1: ["09:00-18:00"]})
    monday = date(2026, 8, 3)  # verified Monday
    assert check_poi_hours(poi, monday) == 'closed'


def test_check_poi_hours_allows_open_weekday() -> None:
    """Same POI is open on Tuesday (weekday 1)."""
    poi = _poi("open-tue", regular_hours={0: [], 1: ["09:00-18:00"]})
    tuesday = date(2026, 8, 4)  # verified Tuesday
    assert check_poi_hours(poi, tuesday) == 'open'


def test_check_poi_hours_rejects_closed_date() -> None:
    """POI with a specific date in closed_dates is closed that day."""
    poi = _poi("holiday-closed", closed_dates=["2026-08-05"])
    wednesday = date(2026, 8, 5)
    assert check_poi_hours(poi, wednesday) == 'closed'


def test_check_poi_hours_allows_when_not_in_closed_dates() -> None:
    """Same POI is open on a day not in closed_dates."""
    poi = _poi("holiday-closed", closed_dates=["2026-08-05"])
    thursday = date(2026, 8, 6)
    assert check_poi_hours(poi, thursday) == 'open'


def test_check_poi_hours_missing_weekday_key_returns_unknown() -> None:
    """If a weekday key is absent from regular_hours, treat as open (conservative)."""
    # Only define Monday (0) — all others are absent.
    poi = _poi("partial-hours", regular_hours={0: ["09:00-18:00"]})
    tuesday = date(2026, 8, 4)  # weekday 1 — not in dict
    assert check_poi_hours(poi, tuesday) == 'unknown'


def test_check_poi_hours_all_day_coverage() -> None:
    """POI with all-day coverage is always open."""
    poi = _poi("always-open", regular_hours={i: ["00:00-23:59"] for i in range(7)})
    assert check_poi_hours(poi, date(2026, 8, 3)) == 'open'
    assert check_poi_hours(poi, date(2026, 8, 4)) == 'open'
    assert check_poi_hours(poi, date(2026, 8, 5)) == 'open'


# ------------------------------------------------------------------ #
# T5 — Travel-time budget                                             #
# ------------------------------------------------------------------ #


def test_haversine_known_distance() -> None:
    """Gardens by the Bay to Sentosa is approximately 5 km."""
    dist = haversine_km(1.2816, 103.8636, 1.2540, 103.8238)
    assert 4.0 < dist < 6.0, f"Expected ~5 km, got {dist:.2f} km"


def test_haversine_same_point_is_zero() -> None:
    """Distance from a point to itself is zero."""
    assert haversine_km(1.0, 103.0, 1.0, 103.0) == 0.0


def test_estimate_travel_min_short_hop() -> None:
    """Two nearby points should have travel time dominated by base overhead."""
    minutes = estimate_travel_min(1.2816, 103.8636, 1.2820, 103.8640)
    # Very short distance → should be roughly the base overhead (~15 min)
    assert 15 <= minutes <= 20


def test_estimate_travel_min_cross_city() -> None:
    """~5 km hop should give a meaningful estimate above base overhead."""
    minutes = estimate_travel_min(1.2816, 103.8636, 1.2540, 103.8238)
    # ~5 km × 1.4 stretch / 20 km/h × 60 + 15 ≈ 36 min
    assert 25 <= minutes <= 50


def test_day_travel_minutes_sums_consecutive_hops() -> None:
    """Total travel for 3 stops = hop(1→2) + hop(2→3)."""
    pois = [
        _poi("a", lat=1.28, lon=103.86),
        _poi("b", lat=1.29, lon=103.87),
        _poi("c", lat=1.30, lon=103.88),
    ]
    total = day_travel_minutes(pois)
    hop_ab = estimate_travel_min(1.28, 103.86, 1.29, 103.87)
    hop_bc = estimate_travel_min(1.29, 103.87, 1.30, 103.88)
    assert total == hop_ab + hop_bc


def test_validate_day_travel_budget_exceeded() -> None:
    """4 POIs far apart should exceed a 120-minute budget."""
    pois = [
        _poi("p1", lat=1.28, lon=103.86),
        _poi("p2", lat=1.40, lon=104.00),
        _poi("p3", lat=1.28, lon=103.86),
        _poi("p4", lat=1.40, lon=104.00),
    ]
    warnings = validate_day_travel_budget(pois, max_travel_min=120)
    assert len(warnings) > 0
    assert warnings[0].kind == "travel_budget_exceeded"


def test_validate_day_travel_budget_within() -> None:
    """2 nearby POIs should be well within budget."""
    pois = [
        _poi("p1", lat=1.2816, lon=103.8636),
        _poi("p2", lat=1.2820, lon=103.8640),
    ]
    warnings = validate_day_travel_budget(pois, max_travel_min=120)
    assert len(warnings) == 0


# ------------------------------------------------------------------ #
# Integration: compose_itinerary                                       #
# ------------------------------------------------------------------ #


def test_compose_excludes_closed_day_poi() -> None:
    """compose_itinerary skips a POI that is closed on the scheduled day."""
    # Maxwell-like POI: closed Monday (weekday 0)
    closed_mon = _poi(
        "sg-closed-monday",
        regular_hours={0: [], **{i: ["08:00-20:00"] for i in range(1, 7)}},
        area="chinatown",
    )
    always_open = _poi("sg-always-open", area="marina_bay")
    spec = _spec(start=date(2026, 8, 3), pace="moderate")  # starts Monday
    ctx = _retrieval([closed_mon, always_open])
    result = compose_itinerary(spec, ctx)

    # The closed POI should be in excluded and warnings
    assert "sg-closed-monday" in result.excluded_items
    assert any(w.kind == "closed_day" and w.poi_id == "sg-closed-monday" for w in result.warnings)

    # The open POI should be scheduled on day 1
    day1_ids = [item.poi_id for item in result.itinerary.days[0].items]
    assert "sg-closed-monday" not in day1_ids
    assert "sg-always-open" in day1_ids


def test_compose_allows_poi_on_open_day() -> None:
    """A POI closed on Monday is allowed on Tuesday."""
    closed_mon = _poi(
        "sg-closed-monday",
        regular_hours={0: [], **{i: ["08:00-20:00"] for i in range(1, 7)}},
        area="marina_bay",
    )
    # Start on Tuesday so the POI is open
    spec = _spec(start=date(2026, 8, 4), pace="moderate")  # Tuesday
    ctx = _retrieval([closed_mon])
    result = compose_itinerary(spec, ctx)

    assert "sg-closed-monday" not in result.excluded_items
    day1_ids = [item.poi_id for item in result.itinerary.days[0].items]
    assert "sg-closed-monday" in day1_ids


def test_compose_returns_composer_result() -> None:
    """compose_itinerary returns a ComposerResult with itinerary + metadata."""
    poi = _poi("sg-test")
    spec = _spec()
    ctx = _retrieval([poi])
    result = compose_itinerary(spec, ctx)

    assert isinstance(result, ComposerResult)
    assert isinstance(result.itinerary, DraftItinerary)
    assert isinstance(result.warnings, list)
    assert isinstance(result.excluded_items, list)


def test_fallback_itinerary_returns_draft_itinerary() -> None:
    """fallback_itinerary still returns a plain DraftItinerary (backward compat)."""
    poi = _poi("sg-test")
    spec = _spec()
    ctx = _retrieval([poi])
    result = fallback_itinerary(spec, ctx)

    assert isinstance(result, DraftItinerary)


def test_compose_determinism() -> None:
    """Two identical calls produce byte-identical JSON."""
    pois = [
        _poi("a", lat=1.28, lon=103.86),
        _poi("b", lat=1.29, lon=103.87),
    ]
    spec = _spec()
    ctx = _retrieval(pois)

    r1 = compose_itinerary(spec, ctx)
    r2 = compose_itinerary(spec, ctx)

    assert r1.itinerary.model_dump_json() == r2.itinerary.model_dump_json()
    assert len(r1.warnings) == len(r2.warnings)

# N1/N3/N4 Tests
from agents.models import ItineraryDay, ItineraryItem, DraftItinerary
from core.itinerary.compose import build_final_schedule

def test_build_final_schedule_overlap_rejection():
    """A schedule with two overlapping items emits a warning."""
    poi1 = _poi("poi1")
    poi1.typical_duration_min = 120
    poi2 = _poi("poi2")
    spec = _spec()
    ctx = _retrieval([poi1, poi2])
    
    # LLM proposes an overlapping schedule
    draft = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=spec.start_date,
                items=[
                    ItineraryItem(poi_id="poi1", start_hint="09:00"),
                    ItineraryItem(poi_id="poi2", start_hint="09:30") # Overlaps since poi1 is 2 hours!
                ]
            )
        ]
    )
    result = build_final_schedule(draft, spec, ctx)
    assert any(w.kind == "overlap" for w in result.warnings)

def test_build_final_schedule_happy_path_retimes():
    """build_final_schedule retimes a successful LLM draft (happy path)."""
    poi1 = _poi("poi1")
    poi1.typical_duration_min = 60
    poi2 = _poi("poi2")
    spec = _spec()
    ctx = _retrieval([poi1, poi2])
    
    draft = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=spec.start_date,
                items=[
                    ItineraryItem(poi_id="poi1"),
                    ItineraryItem(poi_id="poi2")
                ]
            )
        ]
    )
    result = build_final_schedule(draft, spec, ctx)
    items = result.itinerary.days[0].items
    assert items[0].start_time == "09:00"
    assert items[0].end_time == "10:00"
    assert items[1].start_time != None

def test_build_final_schedule_unknown_hours_emits_verification_task():
    """Unknown hours produce a verification task."""
    # missing regular hours
    poi1 = _poi("unknown-hours-poi", regular_hours={})
    spec = _spec()
    ctx = _retrieval([poi1])

    draft = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=spec.start_date,
                items=[ItineraryItem(poi_id="unknown-hours-poi")]
            )
        ]
    )
    result = build_final_schedule(draft, spec, ctx)
    assert any(w.kind == "unknown_hours" for w in result.warnings)


def test_build_final_schedule_closed_day_warning():
    """An LLM-proposed visit to a POI on its closed day emits closed_day,
    on the same happy-path build_final_schedule the planner actually calls
    (not just the deterministic compose_itinerary fallback)."""
    closed_mon = _poi(
        "closed-mon-poi",
        regular_hours={0: [], **{i: ["08:00-20:00"] for i in range(1, 7)}},
    )
    spec = _spec(start=date(2026, 8, 3))  # Monday
    ctx = _retrieval([closed_mon])

    draft = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=spec.start_date,
                items=[ItineraryItem(poi_id="closed-mon-poi")]
            )
        ]
    )
    result = build_final_schedule(draft, spec, ctx)
    assert any(w.kind == "closed_day" and w.poi_id == "closed-mon-poi" for w in result.warnings)


def test_build_final_schedule_overlap_does_not_adopt_bad_hint():
    """Regression: when an item's start_hint overlaps the previous item, the
    cursor must not jump backwards to that hint. The next item's start_time
    should still be computed forward from where the schedule actually is."""
    poi1 = _poi("poi1")
    poi1.typical_duration_min = 120  # runs 09:00-11:00
    poi2 = _poi("poi2")  # overlapping hint: 09:30, inside poi1's window
    poi3 = _poi("poi3")  # no hint — should be timed after poi1, not after 09:30

    spec = _spec()
    ctx = _retrieval([poi1, poi2, poi3])

    draft = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=spec.start_date,
                items=[
                    ItineraryItem(poi_id="poi1", start_hint="09:00"),
                    ItineraryItem(poi_id="poi2", start_hint="09:30"),
                    ItineraryItem(poi_id="poi3"),
                ],
            )
        ],
    )
    result = build_final_schedule(draft, spec, ctx)
    items = result.itinerary.days[0].items
    assert any(w.kind == "overlap" and w.poi_id == "poi2" for w in result.warnings)
    # poi1 runs 09:00-11:00; poi2's start_time must be timed forward from
    # poi1's actual end (plus travel), not dragged back to the bad 09:30 hint.
    assert items[1].start_time is not None
    assert items[1].start_time >= "11:00"
    assert items[1].start_time != "09:30"
    # poi3 must in turn be timed forward from poi2's corrected placement.
    assert items[2].start_time is not None
    assert items[2].start_time > items[1].start_time
