"""Shared builders for the CP4 post-plan tests (not itself a test module).

A small, fully synthetic confirmed trip — DEL to SIN, 2026-11-01 to 2026-11-05, four
itinerary days — with the routing and impact contexts a workspace would derive from it.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from core.models import UserWallet
from planning.answers import (
    BudgetObjectivePayload,
    DailyRhythmPayload,
    ExperiencesFoodPayload,
    FlightPreferencesPayload,
    HardConstraintsPayload,
    PurposePartyPayload,
    StayPreferencesPayload,
    TripEssentialsPayload,
)
from planning.contracts import TravelerHomeContext, TripBrief
from planning.post_plan import (
    DayOverride,
    ExplainableRef,
    ImpactContext,
    ImpactItem,
    RoutingContext,
    RoutingDay,
    RoutingItem,
    flight_fingerprint,
    hotel_fingerprint,
)

START = date(2026, 11, 1)  # a Sunday
HOTEL_AREA = "marina_bay"

GARDENS = RoutingItem(poi_id="poi:gardens", name="Gardens by the Bay")
MAXWELL = RoutingItem(poi_id="poi:maxwell", name="Maxwell Food Centre")
GALLERY = RoutingItem(poi_id="poi:gallery", name="National Gallery Singapore")
FLYER = RoutingItem(poi_id="poi:flyer", name="Singapore Flyer")
JEWEL = RoutingItem(poi_id="poi:jewel", name="Jewel Changi Airport")
SAFARI = RoutingItem(poi_id="poi:safari", name="Night Safari")

DAY_ITEMS: list[list[RoutingItem]] = [[GARDENS, MAXWELL], [GALLERY], [FLYER], []]


def make_brief(**overrides: Any) -> TripBrief:
    fields: dict[str, Any] = {
        "home": TravelerHomeContext(home_country="IN", home_currency="INR", default_origin="DEL"),
        "trip_essentials": TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=START,
            end_date=START + timedelta(days=4),
            travelers=2,
        ),
        "purpose_and_party": PurposePartyPayload(purpose="leisure", adults=2),
        "budget_and_objective": BudgetObjectivePayload(
            budget_minor=None,
            currency="INR",
            travel_style="balanced",
            objective="balanced",
            points_priority="best_value",
        ),
        "flight_preferences": FlightPreferencesPayload(
            cabin="economy", max_stops=0, schedule="no_preference"
        ),
        "stay_preferences": StayPreferencesPayload(
            room_count=1, location_price_tradeoff="balanced"
        ),
        "daily_rhythm": DailyRhythmPayload(
            pace="moderate",
            day_start="normal",
            evening_style="flexible",
            day_trip_appetite="none",
        ),
        "experiences_and_food": ExperiencesFoodPayload(
            interests=["food"], iconic_local_balance="balanced"
        ),
        "hard_constraints": HardConstraintsPayload(has_constraints=False),
        "wallet": UserWallet(card_ids=["hdfc-infinia"]),
    }
    fields.update(overrides)
    return TripBrief(**fields)


def routing_context(brief: TripBrief | None = None, **overrides: Any) -> RoutingContext:
    fields: dict[str, Any] = {
        "days": [
            RoutingDay(date=START + timedelta(days=index), items=list(items))
            for index, items in enumerate(DAY_ITEMS)
        ],
        "candidates": [JEWEL, SAFARI],
        "explainable": [
            ExplainableRef(
                kind="cost_line", ref_id="flight:SQ", label="Singapore Airlines flight"
            ),
            ExplainableRef(kind="cost_line", ref_id="hotel:MBS", label="Marina Bay hotel"),
            ExplainableRef(
                kind="transfer_recommendation", ref_id="transfer:main", label="transfer plan"
            ),
        ],
        "brief": brief or make_brief(),
    }
    fields.update(overrides)
    return RoutingContext(**fields)


def impact_context(
    brief: TripBrief | None = None,
    *,
    day_overrides: list[DayOverride] | None = None,
    **overrides: Any,
) -> ImpactContext:
    brief = brief or make_brief()
    fields: dict[str, Any] = {
        "itinerary_dates": [START + timedelta(days=i) for i in range(4)],
        "items": [
            ImpactItem(poi_id=item.poi_id, day_index=index)
            for index, items in enumerate(DAY_ITEMS)
            for item in items
        ],
        "day_overrides": day_overrides or [],
        "retained_hotel_area_id": HOTEL_AREA,
        "flight_fingerprint": flight_fingerprint(brief),
        "hotel_fingerprint": hotel_fingerprint(brief, hotel_area_id=HOTEL_AREA),
    }
    fields.update(overrides)
    return ImpactContext(**fields)
