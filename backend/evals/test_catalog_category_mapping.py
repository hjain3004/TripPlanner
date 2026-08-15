"""Category mapping must reflect what the data actually contains.

Measured against the six real Overture extracts before this test existed, the
literal-string allowlist in normalize.py was discarding, across BOM/DXB/LON/
NYC/PAR/SG: ~96,000 restaurants (every cuisine-specific category such as
indian_restaurant), ~21,000 cafes and bakeries, ~17,000 temples, churches and
monuments, and ~8,600 galleries. Singapore kept 3,717 restaurants while
dropping 14,828 of them.

At the same time the `attraction` bucket was ~88% accommodation and real
estate, because Overture's landmark_and_historical_building sweeps in condos,
housing societies and hotels - 4,851 of Mumbai's 6,682 such rows carry an
`accommodation` alternate.

So the planner was being handed apartment blocks while actual restaurants and
temples were thrown away. These tests pin both directions.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gateway.catalog.manifest import PinnedSource, load_manifest
from gateway.catalog.normalize import normalize_overture

FIXTURES = Path(__file__).parent.parent / "gateway" / "catalog" / "fixtures"


def _source() -> PinnedSource:
    manifest = load_manifest(FIXTURES / "manifest_sg.yaml")
    return next(s for s in manifest.sources if s.source_id == "overture_sg")


def _row(rid: str, primary: str, alternate: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": rid,
        "names": {"primary": f"Venue {rid}"},
        "categories": {"primary": primary, "alternate": alternate},
        "geometry": {"lat": 1.30, "lon": 103.80},
    }


def _category_of(row: dict[str, Any]) -> str | None:
    claims = normalize_overture([row], _source())
    return next((c.value for c in claims if c.field == "category"), None)


def test_cuisine_specific_restaurants_are_restaurants() -> None:
    """The single largest loss: ~96k rows across six cities."""
    for primary in (
        "indian_restaurant",
        "italian_restaurant",
        "sushi_restaurant",
        "seafood_restaurant",
        "fast_food_restaurant",
        "restaurant",
    ):
        assert _category_of(_row("r", primary)) == "restaurant", primary


def test_bakeries_and_coffee_shops_are_cafes() -> None:
    for primary in ("bakery", "coffee_shop", "cafe", "tea_house"):
        assert _category_of(_row("c", primary)) == "cafe", primary


def test_places_of_worship_and_monuments_are_attractions() -> None:
    """Mumbai alone drops 2,478 hindu_temple rows - major tourist sites."""
    for primary in (
        "hindu_temple",
        "buddhist_temple",
        "church_cathedral",
        "mosque",
        "monument",
    ):
        assert _category_of(_row("a", primary)) == "attraction", primary


def test_art_galleries_are_museums() -> None:
    """Paris keeps 382 museums while dropping 2,172 galleries/museum variants."""
    for primary in ("art_gallery", "art_museum", "history_museum", "museum"):
        assert _category_of(_row("m", primary)) == "museum", primary


def test_beaches_and_viewpoints_and_gardens_are_kept() -> None:
    assert _category_of(_row("n", "beach")) == "attraction"
    assert _category_of(_row("n", "scenic_lookout")) == "attraction"
    assert _category_of(_row("n", "garden")) == "park"
    assert _category_of(_row("n", "national_park")) == "park"


def test_a_landmark_that_is_really_housing_is_not_an_attraction() -> None:
    """4,851 of Mumbai's 6,682 landmark rows are accommodation. A condo tagged
    as a landmark must not be scheduled as a place to visit."""
    for alt in ("accommodation", "real_estate", "home_developer", "hotel"):
        assert _category_of(_row("x", "landmark_and_historical_building", [alt])) is None, alt


def test_a_genuine_landmark_is_still_an_attraction() -> None:
    """Anti-vacuity for the rule above: the exclusion must not swallow the
    real landmarks it sits next to."""
    assert (
        _category_of(
            _row("y", "landmark_and_historical_building", ["monument", "tourist_attraction"])
        )
        == "attraction"
    )
    assert _category_of(_row("y", "landmark_and_historical_building", None)) == "attraction"


def test_genuinely_irrelevant_categories_are_still_dropped() -> None:
    """The fix must widen the net, not remove it. These are the categories the
    crematorium/logistics-hub problem was about."""
    for primary in (
        "bank_credit_union",
        "real_estate",
        "beauty_salon",
        "school",
        "hospital",
        "shopping",
        "atms",
    ):
        assert _category_of(_row("z", primary)) is None, primary
