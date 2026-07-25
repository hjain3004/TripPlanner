from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec
from core.models import UserWallet


class AnchorItinerary(BaseModel):
    case_id: str
    expected_rank: int
    trip_spec: TripSpec
    itinerary: DraftItinerary


class GoldenItineraryCase(BaseModel):
    case_id: str
    trip_spec: TripSpec
    itinerary: DraftItinerary


def _spec(
    *,
    case_id: str,
    origin: str = "DEL",
    style: str = "balanced",
    pace: str = "moderate",
    interests: list[str] | None = None,
) -> TripSpec:
    offset = int(case_id.rsplit("_", 1)[-1]) if "_" in case_id and case_id.rsplit("_", 1)[-1].isdigit() else 1
    start = date(2026, 8, min(offset, 20))
    return TripSpec(
        home_country="IN",
        origin_city=origin,
        destination_city="SIN",
        start_date=start,
        end_date=date.fromordinal(start.toordinal() + 4),
        travelers=2,
        budget_minor=18000000 if style == "budget" else 25000000 if style == "balanced" else 45000000,
        budget_currency="INR",
        style=style,
        interests=interests or ["nature", "food"],
        pace=pace,
        wallet=UserWallet(card_ids=["hdfc-infinia", "axis-atlas"], points_balances={}),
    )


def _days(spec: TripSpec, poi_days: list[list[str]]) -> list[ItineraryDay]:
    return [
        ItineraryDay(
            date=date.fromordinal(spec.start_date.toordinal() + index),
            items=[ItineraryItem(poi_id=poi_id) for poi_id in poi_ids],
        )
        for index, poi_ids in enumerate(poi_days)
    ]


def _itinerary(spec: TripSpec, area_id: str, poi_days: list[list[str]]) -> DraftItinerary:
    return DraftItinerary(hotel_area_id=area_id, days=_days(spec, poi_days))


def load_anchor_itineraries() -> list[AnchorItinerary]:
    spec_good = _spec(case_id="anchor_1", interests=["nature", "food"], pace="moderate")
    spec_scattered = _spec(case_id="anchor_2", interests=["nature", "food"], pace="moderate")
    spec_overpacked = _spec(case_id="anchor_3", interests=["nature"], pace="relaxed")
    return [
        AnchorItinerary(
            case_id="anchor_good",
            expected_rank=1,
            trip_spec=spec_good,
            itinerary=_itinerary(
                spec_good,
                "marina_bay",
                [
                    ["sg-gardens-by-the-bay", "sg-marina-bay-sands-skypark"],
                    ["sg-hawker-maxwell"],
                    ["sg-sentosa-skyline-luge"],
                    [],
                ],
            ),
        ),
        AnchorItinerary(
            case_id="anchor_scattered",
            expected_rank=2,
            trip_spec=spec_scattered,
            itinerary=_itinerary(
                spec_scattered,
                "marina_bay",
                [
                    ["sg-gardens-by-the-bay", "sg-hawker-maxwell", "sg-sentosa-skyline-luge"],
                    ["sg-marina-bay-sands-skypark"],
                    [],
                    [],
                ],
            ),
        ),
        AnchorItinerary(
            case_id="anchor_overpacked",
            expected_rank=3,
            trip_spec=spec_overpacked,
            itinerary=_itinerary(
                spec_overpacked,
                "marina_bay",
                [
                    [
                        "sg-gardens-by-the-bay",
                        "sg-marina-bay-sands-skypark",
                        "sg-hawker-maxwell",
                        "sg-sentosa-skyline-luge",
                    ],
                    [],
                    [],
                    [],
                ],
            ),
        ),
    ]


def load_golden_itineraries() -> list[GoldenItineraryCase]:
    configs = [
        ("golden_1", "DEL", "budget", "relaxed", ["food", "culture"], "chinatown", [["sg-hawker-maxwell"], [], [], []]),
        ("golden_2", "DEL", "balanced", "moderate", ["nature"], "marina_bay", [["sg-gardens-by-the-bay"], ["sg-marina-bay-sands-skypark"], [], []]),
        ("golden_3", "DEL", "luxury", "moderate", ["landmark", "nightlife"], "orchard", [["sg-marina-bay-sands-skypark"], ["sg-gardens-by-the-bay"], [], []]),
        ("golden_4", "BOM", "balanced", "packed", ["kids", "nature"], "sentosa", [["sg-sentosa-skyline-luge", "sg-gardens-by-the-bay"], ["sg-marina-bay-sands-skypark"], [], []]),
        ("golden_5", "BOM", "budget", "moderate", ["food"], "chinatown", [["sg-hawker-maxwell"], ["sg-gardens-by-the-bay"], [], []]),
        ("golden_6", "DEL", "luxury", "packed", ["shopping", "nightlife"], "orchard", [["sg-marina-bay-sands-skypark"], ["sg-hawker-maxwell", "sg-gardens-by-the-bay"], [], []]),
        ("golden_7", "BOM", "balanced", "relaxed", ["landmark"], "marina_bay", [["sg-marina-bay-sands-skypark"], [], ["sg-gardens-by-the-bay"], []]),
        ("golden_8", "DEL", "budget", "packed", ["nature", "food"], "chinatown", [["sg-hawker-maxwell", "sg-gardens-by-the-bay"], ["sg-sentosa-skyline-luge"], [], []]),
    ]
    out: list[GoldenItineraryCase] = []
    for case_id, origin, style, pace, interests, area_id, poi_days in configs:
        spec = _spec(
            case_id=case_id,
            origin=origin,
            style=style,
            pace=pace,
            interests=interests,
        )
        out.append(
            GoldenItineraryCase(
                case_id=case_id,
                trip_spec=spec,
                itinerary=_itinerary(spec, area_id, poi_days),
            )
        )
    return out
