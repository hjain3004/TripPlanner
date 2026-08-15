from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from gateway.catalog.manifest import PinnedSource
from gateway.catalog.sanitize import sanitize_text
from gateway.places.contracts import PlaceClaim

# Pinned inputs carry a release, not a wall clock. A build must not embed "now".
_PINNED_RETRIEVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


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

        category = None
        if raw_category:
            raw_category = str(raw_category)
            if raw_category in ("park", "food_court", "restaurant", "cafe", "museum"):
                category = raw_category
            elif raw_category in (
                "landmark_and_historical_building",
                "amusement_park",
                "zoo",
                "aquarium",
                "botanical_garden",
            ):
                category = "attraction"

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
