from __future__ import annotations

from datetime import date

import pytest

from agents.models import PlaceSearchRequest
from agents.retrieval import retrieve_candidates
from agents.search import search_catalog_places
from core.db import load_kb
from core.models import (
    POI,
    Channel,
    OptimizationPrefs,
    Provenance,
    SpendCategory,
    TimezoneAwareHours,
    UserWallet,
)
from core.trip_models import TripSpec

DESTINATIONS = ["SIN", "BOM", "DXB", "NYC", "LON", "PAR"]

pytestmark = pytest.mark.allow_real_catalog


def _spec(destination: str, interests: list[str]) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city=destination,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=interests,
        pace="moderate",
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        optimization=OptimizationPrefs(),
    )


def _ids(ctx) -> list[str]:  # noqa: ANN001
    return [poi.id for poi in ctx.pois[:8]]


def _categories(ctx) -> list[str]:  # noqa: ANN001
    return [tag.casefold() for poi in ctx.pois[:8] for tag in poi.tags]


@pytest.mark.parametrize("destination", DESTINATIONS)
def test_real_catalog_interests_change_top_candidates(destination: str) -> None:
    kb = load_kb()

    food = retrieve_candidates(_spec(destination, ["food"]), kb, limit=12)
    culture = retrieve_candidates(_spec(destination, ["culture"]), kb, limit=12)

    assert len(food.pois) >= 8
    assert len(culture.pois) >= 8
    assert _ids(food) != _ids(culture)
    assert any(cat in {"food", "restaurant", "cafe", "food_court"} for cat in _categories(food))
    assert any(cat in {"museum", "gallery"} for cat in _categories(culture))


@pytest.mark.parametrize(
    ("destination", "category", "expected_raw_categories"),
    [
        ("LON", "food", {"restaurant", "cafe", "food_court"}),
        ("LON", "culture", {"museum", "gallery"}),
        ("LON", "nature", {"park", "garden"}),
        ("LON", "attractions", {"attraction", "landmark"}),
    ],
)
def test_picker_visible_filters_return_real_catalog_matches(
    destination: str, category: str, expected_raw_categories: set[str]
) -> None:
    resp = search_catalog_places(
        PlaceSearchRequest(destination=destination, category=category, limit=10),
        load_kb(),
    )

    assert len(resp.results) >= 3
    assert {item.category.casefold() for item in resp.results}.issubset(
        expected_raw_categories
    )


def test_restaurants_and_cafes_are_dining_spend_categories() -> None:
    from agents.estimator import _poi_category

    def poi_with_tag(tag: str) -> POI:
        return POI(
            id=f"poi:{tag}",
            city="London",
            name=tag,
            tags=[tag],
            typical_duration_min=60,
            price_minor=1000,
            currency="GBP",
            area="test",
            open_hours=TimezoneAwareHours(
                timezone="Europe/London",
                regular_hours={},
                closed_dates=[],
            ),
            booking_channel=Channel.POS_ABROAD,
            description="test",
            provenance=Provenance(
                source_url="https://example.invalid",
                source_type="manual_curation",
                last_verified=date(2026, 8, 18),
                verified_by="test",
                needs_verification=False,
                confidence=1.0,
            ),
        )

    assert _poi_category(poi_with_tag("restaurant")) == SpendCategory.DINING
    assert _poi_category(poi_with_tag("cafe")) == SpendCategory.DINING
    assert _poi_category(poi_with_tag("food_court")) == SpendCategory.DINING
    assert _poi_category(poi_with_tag("museum")) == SpendCategory.ATTRACTIONS
