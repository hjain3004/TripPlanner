from __future__ import annotations

from datetime import date
from pathlib import Path

from agents.models import RetrievalContext, TripSpec
from core.db import KnowledgeBase
from core.models import POI, Area
from gateway.places.contracts import PlaceCandidate

CITY_BY_IATA = {"SIN": "Singapore"}

def _map_candidate_to_poi(c: PlaceCandidate, city: str) -> POI:
    name = next((cl.value for cl in c.claims if cl.field == "name"), "Unknown")
    cat = next((cl.value for cl in c.claims if cl.field == "category"), "other")
    coords = next(
        (cl.value for cl in c.claims if cl.field == "coordinates"), {"lat": 0.0, "lon": 0.0}
    )

    lat = coords["lat"] if isinstance(coords, dict) and "lat" in coords else 0.0
    lon = coords["lon"] if isinstance(coords, dict) and "lon" in coords else 0.0

    hours_str = next((cl.value for cl in c.claims if cl.field == "opening_hours"), None)
    # Unknown hours never become open. A venue whose hours cannot be parsed is verify_required
    needs_verification_override = False
    regular_hours = {}
    if hours_str == "24/7":
        regular_hours = {i: ["00:00-23:59"] for i in range(7)}
    elif hours_str:
        needs_verification_override = True
    else:
        needs_verification_override = True

    from core.models import Provenance, TimezoneAwareHours
    
    poi = POI(
        id=c.place_id,
        city=city,
        name=str(name),
        tags=[str(cat)],
        typical_duration_min=90,
        price_minor=0,
        currency="INR",
        lat=lat,
        lon=lon,
        area="Unknown",
        open_hours=TimezoneAwareHours(
            timezone="Asia/Singapore", regular_hours=regular_hours, closed_dates=[]
        ),
        booking_channel="pos_abroad",
        description="",
        provenance=Provenance(
            source_type="crawl_draft",
            last_verified=date(2026, 1, 1),
            verified_by="UNVERIFIED",
            needs_verification=(
                True if needs_verification_override else c.status == "verify_required"
            ),
            confidence=0.5,
        ),
    )
    if c.status == "verify_required" or needs_verification_override:
        poi.provenance.needs_verification = True
    return poi

def get_catalog_poi(poi_id: str, city: str) -> POI | None:
    from pathlib import Path

    from gateway.catalog.activate import active_catalog_path
    try:
        catalog = active_catalog_path(Path("catalogs"))
        if catalog and catalog.exists():
            from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
            adapter = SnapshotPlaceAdapter(catalog)
            for c in adapter._load():
                if c.place_id == poi_id:
                    return _map_candidate_to_poi(c, city)
    except FileNotFoundError:
        pass
    return None


def _overlap(poi: POI, interests: list[str]) -> int:
    wanted = {tag.casefold() for tag in interests}
    return len(wanted.intersection({tag.casefold() for tag in poi.tags}))


def _poi_row(poi: POI) -> str:
    tags = ",".join(sorted(poi.tags))
    status = "verify_required" if poi.provenance.needs_verification else "live"
    trust_status = (
        f"status:{status}|"
        f"verified:{poi.provenance.verified_by}|"
        f"needs_verification:{poi.provenance.needs_verification}|"
        f"last_verified:{poi.provenance.last_verified.isoformat()}|"
        f"confidence:{poi.provenance.confidence}"
    )
    return (
        f"{poi.id} | {poi.name} | {poi.area} | {tags} | "
        f"{poi.price_minor} {poi.currency} minor | {poi.typical_duration_min} min | "
        f"{poi.open_hours} | {trust_status}"
    )


def _area_row(area: Area) -> str:
    tags = ",".join(sorted(area.good_for_tags))
    return f"{area.id} | {area.name} | {tags} | centrality {area.centrality_score}"


def retrieve_candidates(
    spec: TripSpec, kb: KnowledgeBase, limit: int = 40, catalog: Path | None = None
) -> RetrievalContext:
    if catalog is None:
        from gateway.catalog.activate import active_catalog_path
        try:
            catalog = active_catalog_path(Path("catalogs"))
        except FileNotFoundError:
            catalog = None

    city = CITY_BY_IATA.get(spec.destination_city, spec.destination_city)
    pois = kb.pois(city)
    
    poi_provenance = []

    if catalog and catalog.exists():
        from core.trip_models import POIEvidence
        from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
        from gateway.places.contracts import PlaceSearchRequest

        adapter = SnapshotPlaceAdapter(catalog)
        req = PlaceSearchRequest(
            origin_lat=0, origin_lon=0, max_results=limit, timeout_ms=5000, destination_area_id=""
        )
        candidates, _ = adapter.search_places(req)

        for c in candidates:
            poi = _map_candidate_to_poi(c, city)
            pois.append(poi)

            status = c.status
            if status == "verify_required":
                poi.provenance.needs_verification = True

            lic = next((cl.licence_id for cl in c.claims if cl.licence_id), None)
            attr = next(
                (cl.attribution_requirements for cl in c.claims if cl.attribution_requirements),
                None,
            )

            ev = POIEvidence(
                poi_id=c.place_id,
                status=status,
                last_verified=date(2026, 1, 1),
                licence_id=lic,
                attribution=attr,
                needs_verification=(status == "verify_required"),
            )
            poi_provenance.append(ev)

    # Also create provenance for seeded POIs
    from core.trip_models import POIEvidence

    for p in kb.pois(city):
        poi_provenance.append(
            POIEvidence(
                poi_id=p.id,
                status="live",
                last_verified=p.provenance.last_verified,
                needs_verification=p.provenance.needs_verification,
                licence_id="proprietary",
                attribution="TripPlanner Curated",
            )
        )

    sorted_pois = sorted(
        pois,
        key=lambda poi: (
            -_overlap(poi, spec.interests),
            int(poi.provenance.needs_verification),
            int(poi.provenance.verified_by == "UNVERIFIED"),
            -poi.provenance.confidence,
            -poi.provenance.last_verified.toordinal(),
            poi.area,
            poi.id,
        ),
    )[:limit]

    areas = sorted(kb.areas(city), key=lambda area: area.id)
    return RetrievalContext(
        pois=sorted_pois,
        areas=areas,
        poi_rows=[_poi_row(poi) for poi in sorted_pois],
        area_rows=[_area_row(area) for area in areas],
        poi_provenance=poi_provenance,
    )
