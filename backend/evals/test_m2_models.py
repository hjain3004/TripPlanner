from datetime import date

import pytest
from pydantic import ValidationError

from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec
from core.models import OptimizationPrefs, UserWallet


def _trip(**updates: object) -> TripSpec:
    data: dict[str, object] = {
        "home_country": "IN",
        "origin_city": "DEL",
        "destination_city": "SIN",
        "start_date": date(2026, 8, 1),
        "end_date": date(2026, 8, 5),
        "travelers": 2,
        "budget_minor": 25000000,
        "budget_currency": "INR",
        "style": "balanced",
        "interests": ["nature", "food"],
        "pace": "moderate",
        "dietary": [],
        "wallet": UserWallet(card_ids=["voyager-prime"], points_balances={}),
        "optimization": OptimizationPrefs(objective="max_savings"),
        "unresolved": [],
    }
    data.update(updates)
    return TripSpec.model_validate(data)


def test_trip_spec_accepts_valid_kernel_trip() -> None:
    spec = _trip()
    assert spec.home_country == "IN"
    assert spec.travelers == 2
    assert spec.nights == 4


def test_trip_spec_rejects_invalid_traveler_count() -> None:
    with pytest.raises(ValidationError):
        _trip(travelers=0)


def test_trip_spec_rejects_two_night_range() -> None:
    with pytest.raises(ValidationError):
        _trip(start_date=date(2026, 8, 1), end_date=date(2026, 8, 3))


def test_trip_spec_rejects_eight_night_range() -> None:
    with pytest.raises(ValidationError):
        _trip(start_date=date(2026, 8, 1), end_date=date(2026, 8, 9))


def test_list_defaults_are_isolated() -> None:
    first = _trip(interests=[])
    second = _trip(interests=[])
    first.unresolved.append("missing dates")
    assert second.unresolved == []


def test_draft_itinerary_requires_days() -> None:
    itinerary = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1),
                items=[ItineraryItem(poi_id="sg-gardens-by-the-bay")],
            )
        ],
    )
    assert itinerary.itinerary_quality == "llm"
