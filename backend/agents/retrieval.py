from __future__ import annotations

from agents.models import RetrievalContext, TripSpec
from core.db import KnowledgeBase
from core.models import Area, POI

CITY_BY_IATA = {"SIN": "Singapore"}


def _overlap(poi: POI, interests: list[str]) -> int:
    wanted = {tag.casefold() for tag in interests}
    return len(wanted.intersection({tag.casefold() for tag in poi.tags}))


def _poi_row(poi: POI) -> str:
    tags = ",".join(sorted(poi.tags))
    return (
        f"{poi.id} | {poi.name} | {poi.area} | {tags} | "
        f"{poi.price_minor} {poi.currency} minor | {poi.typical_duration_min} min | "
        f"{poi.open_hours}"
    )


def _area_row(area: Area) -> str:
    tags = ",".join(sorted(area.good_for_tags))
    return f"{area.id} | {area.name} | {tags} | centrality {area.centrality_score}"


def retrieve_candidates(
    spec: TripSpec, kb: KnowledgeBase, limit: int = 40
) -> RetrievalContext:
    city = CITY_BY_IATA.get(spec.destination_city, spec.destination_city)
    pois = sorted(
        kb.pois(city),
        key=lambda poi: (-_overlap(poi, spec.interests), poi.area, poi.id),
    )[:limit]
    areas = sorted(kb.areas(city), key=lambda area: area.id)
    return RetrievalContext(
        pois=pois,
        areas=areas,
        poi_rows=[_poi_row(poi) for poi in pois],
        area_rows=[_area_row(area) for area in areas],
    )
