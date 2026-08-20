from pydantic import BaseModel

from gateway.catalog.manifest import CatalogManifest
from gateway.places.contracts import Place, PlaceClaim

SUPPORTED_CATEGORIES = ("park", "food_court", "restaurant", "cafe", "attraction", "museum")
_MIN_PER_CATEGORY = {
    "park": 2,
    "food_court": 2,
    "restaurant": 2,
    "cafe": 1,
    "attraction": 2,
    "museum": 1,
}


class QualityReport(BaseModel):
    passed: bool
    failures: list[str]
    by_category: dict[str, int]
    places_without_coordinates: int
    places_with_unknown_hours: int
    dropped_uncategorized: int
    dropped_out_of_bbox: int


def evaluate_quality(
    places: list[Place],
    claims: list[PlaceClaim],
    manifest: CatalogManifest,
    dropped_uncategorized: int = 0,
    dropped_out_of_bbox: int = 0,
) -> QualityReport:
    by_category: dict[str, int] = {cat: 0 for cat in SUPPORTED_CATEGORIES}
    places_without_coords = 0
    places_with_unknown_hours = 0
    failures = []

    # Pre-calculate what claims exist for each place
    # Since claims are un-resolved / raw claims or resolved claims?
    # Actually, evaluate_quality takes claims (the resolved winners, or raw claims?).
    # The tests assume claims is a list of all claims for the places.
    # Group claims by place_id
    from collections import defaultdict

    place_claims = defaultdict(list)
    for c in claims:
        place_claims[c.place_id].append(c)

    # Also check licence coverage across all claims
    missing_licence = sum(1 for c in claims if not c.licence_id)
    if missing_licence > 0:
        failures.append(f"{missing_licence} claims missing licence")

    for p in places:
        c_list = place_claims[p.place_id]

        # Determine category (spec 5.4 says warn on stale, but here we just need
        # to count categories)
        cats = [c.value for c in c_list if c.field == "category"]
        for cat in cats:
            if cat in by_category:
                by_category[cat] += 1

        # Check coordinates
        if not any(c.field == "coordinates" for c in c_list):
            places_without_coords += 1

        # Check hours
        if not any(c.field == "opening_hours" for c in c_list):
            places_with_unknown_hours += 1

    if places_without_coords > 0:
        failures.append(f"{places_without_coords} places missing coordinates")

    for cat, minimum in _MIN_PER_CATEGORY.items():
        if by_category[cat] < minimum:
            failures.append(
                f"Category {cat} below minimum (has {by_category[cat]}, needs {minimum})"
            )

    if manifest.max_places and len(places) > manifest.max_places:
        failures.append(f"Catalog size {len(places)} exceeds max_places {manifest.max_places}")

    if places:
        categorized_count = sum(
            1
            for p in places
            if any(
                c.field == "category" and c.value in SUPPORTED_CATEGORIES
                for c in place_claims[p.place_id]
            )
        )
        if categorized_count / len(places) < 0.95:
            failures.append(
                f"Categorized places {categorized_count}/{len(places)} is below 95% threshold"
            )

    passed = len(failures) == 0
    failures.sort()

    return QualityReport(
        passed=passed,
        failures=failures,
        by_category=by_category,
        places_without_coordinates=places_without_coords,
        places_with_unknown_hours=places_with_unknown_hours,
        dropped_uncategorized=dropped_uncategorized,
        dropped_out_of_bbox=dropped_out_of_bbox,
    )
