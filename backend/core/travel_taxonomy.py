from __future__ import annotations

from enum import StrEnum

from core.models import SpendCategory


class TravelCategory(StrEnum):
    DINING = "dining"
    NATURE = "nature"
    CULTURE = "culture"
    LANDMARK = "landmark"
    OTHER = "other"


_DINING = {
    "dining",
    "food",
    "foods",
    "restaurant",
    "restaurants",
    "cafe",
    "cafes",
    "café",
    "cafés",
    "food_court",
    "food court",
    "hawker",
}
_NATURE = {"nature", "park", "parks", "garden", "gardens", "outdoors"}
_CULTURE = {
    "culture",
    "cultural",
    "museum",
    "museums",
    "gallery",
    "galleries",
    "art",
    "arts",
}
_LANDMARK = {
    "landmark",
    "landmarks",
    "attraction",
    "attractions",
    "architecture",
    "architectural",
    "history",
    "historic",
    "palace",
    "tower",
    "temple",
    "monument",
}

_PROVIDER_CATEGORIES: dict[TravelCategory, set[str]] = {
    TravelCategory.DINING: {"restaurant", "cafe", "food_court", "food"},
    TravelCategory.NATURE: {"park", "garden"},
    TravelCategory.CULTURE: {"museum", "gallery"},
    TravelCategory.LANDMARK: {"attraction", "landmark"},
    TravelCategory.OTHER: {"other"},
}


def normalize_taxonomy_token(value: str) -> str:
    return value.strip().casefold().replace("-", "_")


def canonical_travel_category(value: str) -> TravelCategory:
    token = normalize_taxonomy_token(value).replace("_", " ")
    underscore_token = token.replace(" ", "_")
    if token in _DINING or underscore_token in _DINING:
        return TravelCategory.DINING
    if token in _NATURE or underscore_token in _NATURE:
        return TravelCategory.NATURE
    if token in _CULTURE or underscore_token in _CULTURE:
        return TravelCategory.CULTURE
    if token in _LANDMARK or underscore_token in _LANDMARK:
        return TravelCategory.LANDMARK
    return TravelCategory.OTHER


def provider_categories_for_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    category = canonical_travel_category(value)
    return set(_PROVIDER_CATEGORIES[category])


def category_matches_filter(raw_category: str, requested_filter: str | None) -> bool:
    if not requested_filter:
        return True
    wanted = canonical_travel_category(requested_filter)
    raw = normalize_taxonomy_token(raw_category)
    return canonical_travel_category(raw_category) == wanted or raw in _PROVIDER_CATEGORIES[wanted]


def canonical_overlap(tags: list[str], interests: list[str]) -> int:
    wanted = {canonical_travel_category(value) for value in interests}
    if not wanted:
        return 0
    tagged = {canonical_travel_category(value) for value in tags}
    return len(wanted.intersection(tagged))


def spend_category_for_tags(tags: list[str]) -> SpendCategory:
    concepts = {canonical_travel_category(tag) for tag in tags}
    if TravelCategory.DINING in concepts:
        return SpendCategory.DINING
    attraction_categories = {
        TravelCategory.NATURE,
        TravelCategory.CULTURE,
        TravelCategory.LANDMARK,
    }
    if concepts.intersection(attraction_categories):
        return SpendCategory.ATTRACTIONS
    return SpendCategory.OTHER
