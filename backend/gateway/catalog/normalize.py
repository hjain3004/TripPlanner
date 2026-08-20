from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from gateway.catalog.manifest import PinnedSource
from gateway.catalog.sanitize import sanitize_text
from gateway.places.contracts import PlaceClaim

# Pinned inputs carry a release, not a wall clock. A build must not embed "now".
_PINNED_RETRIEVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


# Overture's taxonomy is far finer-grained than our six itinerary categories.
# Matching literal strings discarded ~96k restaurants, ~21k cafes, ~17k places
# of worship and ~8.6k galleries across the six built cities, because the data
# says `indian_restaurant` and `art_gallery`, not `restaurant` and `museum`.
# See evals/test_catalog_category_mapping.py for the measured numbers.
_EXACT_CATEGORY: dict[str, str] = {
    # food
    "restaurant": "restaurant",
    "food_court": "food_court",
    "cafe": "cafe",
    "bakery": "cafe",
    "coffee_shop": "cafe",
    "tea_house": "cafe",
    "cafeteria": "cafe",
    "dessert_shop": "cafe",
    "juice_bar": "cafe",
    # green space
    "park": "park",
    "garden": "park",
    "botanical_garden": "park",
    "national_park": "park",
    "nature_preserve": "park",
    # culture
    "museum": "museum",
    "art_gallery": "museum",
    "art_museum": "museum",
    "history_museum": "museum",
    "science_museum": "museum",
    # sights
    "amusement_park": "attraction",
    "zoo": "attraction",
    "aquarium": "attraction",
    "monument": "attraction",
    "historical_place": "attraction",
    "castle": "attraction",
    "palace": "attraction",
    "beach": "attraction",
    "scenic_lookout": "attraction",
    "hindu_temple": "attraction",
    "buddhist_temple": "attraction",
    "church_cathedral": "attraction",
    "mosque": "attraction",
    "synagogue": "attraction",
    "shrine": "attraction",
}

# Overture's landmark_and_historical_building is the single broadest category
# in the set and is dominated by housing: 4,851 of Mumbai's 6,682 such rows
# carry an `accommodation` alternate, plus real_estate, home_developer and
# hotel. A condo tagged as a landmark must never be scheduled as a sight.
_LANDMARK_CATEGORY = "landmark_and_historical_building"
_NOT_REALLY_A_SIGHT = frozenset(
    {
        "accommodation",
        "real_estate",
        "home_developer",
        "hotel",
        "apartment_building",
        "residential",
    }
)


def map_overture_category(primary: str | None, alternates: list[str] | None) -> str | None:
    """Map an Overture category pair onto one of our six itinerary categories.

    Returns None for anything that is not a place a traveller would visit -
    the net is deliberately still a net, not an open door (see the
    crematorium/logistics-hub findings in the I7 report).
    """
    if not primary:
        return None

    if primary == _LANDMARK_CATEGORY:
        if any(a in _NOT_REALLY_A_SIGHT for a in (alternates or [])):
            return None
        return "attraction"

    if primary in _EXACT_CATEGORY:
        return _EXACT_CATEGORY[primary]

    # Cuisine-specific restaurants: indian_restaurant, sushi_restaurant, ...
    if primary.endswith("_restaurant"):
        return "restaurant"

    return None


def _claim(source: PinnedSource, place_id: str, field: str, value: Any) -> PlaceClaim:
    return PlaceClaim(
        place_id=place_id,
        field=field,
        value=value,
        source_id=source.source_id,
        source_url=source.source_url,
        retrieved_at=_PINNED_RETRIEVED_AT,
        source_release=source.source_release,
        last_verified=_PINNED_RETRIEVED_AT,
        verified_by=f"catalog:{source.source_id}",
        confidence=0.9,
        needs_verification=field in ("opening_hours", "accessibility", "admission"),
        licence_id=source.licence_id,
        attribution_requirements=source.attribution_text,
    )


def normalize_overture(rows: list[dict[str, Any]], source: PinnedSource) -> list[PlaceClaim]:
    claims: list[PlaceClaim] = []
    for row in rows:
        pid = f"overture:{row['id']}"
        names = row.get("names") or {}
        name = sanitize_text(str(names.get("primary", ""))) if isinstance(names, dict) else ""
        if name:
            claims.append(_claim(source, pid, "name", name))
        categories = row.get("categories") or {}
        raw_category = categories.get("primary") if isinstance(categories, dict) else None

        alternates_raw = categories.get("alternate") if isinstance(categories, dict) else None
        category = map_overture_category(
            str(raw_category) if raw_category else None,
            [str(a) for a in alternates_raw] if alternates_raw else None,
        )

        if category:
            claims.append(_claim(source, pid, "category", sanitize_text(str(category))))
        geom = row.get("geometry")
        if isinstance(geom, str) and geom.startswith("POINT"):
            parts = geom.replace("POINT (", "").replace(")", "").split()
            if len(parts) == 2:
                lon, lat = float(parts[0]), float(parts[1])
                claims.append(_claim(source, pid, "coordinates", {"lat": lat, "lon": lon}))
        elif geom and "lat" in geom and "lon" in geom:
            claims.append(
                _claim(source, pid, "coordinates", {"lat": geom["lat"], "lon": geom["lon"]})
            )
    return sorted(claims, key=lambda c: (c.place_id, c.field))


def normalize_osm(rows: list[dict[str, Any]], source: PinnedSource) -> list[PlaceClaim]:
    claims: list[PlaceClaim] = []
    for row in rows:
        tags = row.get("tags", {})
        pid = f"osm:{row['type']}/{row['id']}"

        name = sanitize_text(tags.get("name", ""))
        if name:
            claims.append(_claim(source, pid, "name", name))

        hours = sanitize_text(tags.get("opening_hours", ""))
        if hours:
            claims.append(_claim(source, pid, "opening_hours", hours))

        wheelchair = sanitize_text(tags.get("wheelchair", ""))
        if wheelchair:
            claims.append(_claim(source, pid, "accessibility", {"wheelchair": wheelchair}))

    return sorted(claims, key=lambda c: (c.place_id, c.field))


def normalize_wikivoyage(rows: list[dict[str, Any]], source: PinnedSource) -> list[PlaceClaim]:
    claims: list[PlaceClaim] = []
    for row in rows:
        title = row.get("title", "")
        if "wikidata" in row:
            pid = f"wikidata:{row['wikidata']}"
        else:
            slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
            pid = f"internal:{slug}"

        extract = sanitize_text(row.get("extract", ""))
        if extract:
            claims.append(_claim(source, pid, "description", extract))

    return sorted(claims, key=lambda c: (c.place_id, c.field))
