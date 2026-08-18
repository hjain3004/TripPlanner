from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from agents.models import RetrievalContext, TripSpec
from core.db import KnowledgeBase
from core.models import POI, Area, Provenance
from core.travel_taxonomy import canonical_overlap
from gateway.catalog.regions import Region
from gateway.places.contracts import PlaceCandidate

CITY_BY_IATA = {"SIN": "Singapore"}


def default_catalog_root() -> Path:
    root = Path("catalogs")
    if root.exists():
        return root
    return Path(__file__).resolve().parent.parent / "catalogs"


def geo_cell_area_id(region: Region, lat: float | None, lon: float | None) -> str:
    if lat is None or lon is None:
        return "Unknown"
    lat_cell = math.floor(lat * 10.0) / 10.0
    lon_cell = math.floor(lon * 10.0) / 10.0
    return f"geo-cell:{region.iata.casefold()}:{lat_cell:.1f}:{lon_cell:.1f}"


def resolve_destination_city(destination_iata: str) -> str:
    from gateway.catalog.regions import get_region

    region = get_region(destination_iata)
    if region:
        return region.city_name
    return CITY_BY_IATA.get(destination_iata, destination_iata)

def _map_candidate_to_poi(
    c: PlaceCandidate, city: str, region: Region | None = None
) -> POI:
    name = next((cl.value for cl in c.claims if cl.field == "name"), "Unknown")
    cat = next((cl.value for cl in c.claims if cl.field == "category"), "other")
    coords = next(
        (cl.value for cl in c.claims if cl.field == "coordinates"), None
    )

    lat = coords["lat"] if isinstance(coords, dict) and "lat" in coords else None
    lon = coords["lon"] if isinstance(coords, dict) and "lon" in coords else None

    desc = next((cl.value for cl in c.claims if cl.field == "description"), "")

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

    from datetime import datetime

    from core.models import Provenance, TimezoneAwareHours

    claim_dt = next((cl.last_verified for cl in c.claims if cl.last_verified), None)
    if isinstance(claim_dt, datetime):
        last_ver_date = claim_dt.date()
    elif isinstance(claim_dt, date):
        last_ver_date = claim_dt
    else:
        last_ver_date = date(2026, 8, 17)

    src_url = next((cl.source_url for cl in c.claims if cl.source_url), "")
    verified_by = next((cl.verified_by for cl in c.claims if cl.verified_by), "UNVERIFIED")
    claim_needs_ver = any(cl.needs_verification for cl in c.claims)
    needs_ver = (
        (c.status in ("verify_required", "cached", "estimated"))
        or needs_verification_override
        or claim_needs_ver
    )

    area = geo_cell_area_id(region, lat, lon) if region else "Unknown"

    poi = POI(
        id=c.place_id,
        city=city,
        name=str(name),
        tags=[str(cat)],
        typical_duration_min=90,
        price_minor=0,
        currency=region.currency if region else "INR",
        lat=lat,
        lon=lon,
        area=area,
        open_hours=TimezoneAwareHours(
            timezone=region.timezone if region else "UTC",
            regular_hours=regular_hours,
            closed_dates=[],
        ),
        booking_channel="pos_abroad",
        description=str(desc),
        provenance=Provenance(
            source_url=src_url,
            source_type="manual_curation" if c.status == "live" else "crawl_draft",
            last_verified=last_ver_date,
            verified_by=verified_by,
            needs_verification=needs_ver,
            confidence=0.85 if c.status == "live" else 0.5,
        ),
    )
    return poi


def _geo_cell_area(area_id: str, city: str, tags: list[str]) -> Area:
    return Area(
        id=area_id,
        city=city,
        name=area_id.replace("geo-cell:", "Geographic cell "),
        good_for_tags=sorted(set(tags)),
        centrality_score=0.5,
        provenance=Provenance(
            source_url=None,
            source_type="crawl_draft",
            last_verified=date(2026, 8, 18),
            verified_by="deterministic_geo_cell",
            needs_verification=True,
            confidence=0.4,
            notes="Deterministic coordinate bucket, not a verified neighborhood name.",
        ),
    )

def get_catalog_poi(poi_id: str, destination_iata: str) -> POI | None:

    from gateway.catalog.activate import active_catalog_path
    from gateway.catalog.regions import get_region

    region = get_region(destination_iata)
    if region is None:
        return None
    try:
        catalog = active_catalog_path(default_catalog_root(), catalog_id=region.catalog_id)
        if catalog and catalog.exists():
            from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
            adapter = SnapshotPlaceAdapter(catalog)
            for c in adapter._load():
                if c.place_id == poi_id:
                    return _map_candidate_to_poi(c, region.city_name, region)
    except FileNotFoundError:
        pass
    return None


def _overlap(poi: POI, interests: list[str]) -> int:
    return canonical_overlap(poi.tags, interests)


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
    from gateway.catalog.regions import get_region
    region = get_region(spec.destination_city)
    
    if catalog is None and region is not None:
        from gateway.catalog.activate import active_catalog_path
        try:
            catalog = active_catalog_path(default_catalog_root(), catalog_id=region.catalog_id)
        except FileNotFoundError:
            catalog = None

    city = resolve_destination_city(spec.destination_city)
    pois = kb.pois(city)
    
    poi_provenance = []

    if catalog and catalog.exists():
        from core.trip_models import POIEvidence
        from gateway.catalog.quality import SUPPORTED_CATEGORIES
        from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
        
        origin_lat = region.centroid_lat if region else 0.0
        origin_lon = region.centroid_lon if region else 0.0

        adapter = SnapshotPlaceAdapter(catalog)
        supported = set(SUPPORTED_CATEGORIES)
        candidates = [
            c
            for c in adapter._load()
            if next(
                (cl.value for cl in c.claims if cl.field == "category"),
                None,
            )
            in supported
        ]

        def distance_sort(c: PlaceCandidate) -> tuple[float, str]:
            coords = next(
                (cl.value for cl in c.claims if cl.field == "coordinates"),
                None,
            )
            if not isinstance(coords, dict):
                return (float("inf"), c.place_id)
            lat = coords.get("lat")
            lon = coords.get("lon")
            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                return (float("inf"), c.place_id)
            return (
                (float(lat) - origin_lat) ** 2 + (float(lon) - origin_lon) ** 2,
                c.place_id,
            )

        candidates = sorted(
            candidates,
            key=lambda c: (
                -canonical_overlap(
                    [
                        str(
                            next(
                                (cl.value for cl in c.claims if cl.field == "category"),
                                "",
                            )
                        )
                    ],
                    spec.interests,
                ),
                distance_sort(c),
            ),
        )
        candidates = candidates[: max(limit * 4, limit)]

        for c in candidates:
            poi = _map_candidate_to_poi(c, city, region)
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
    if not areas and sorted_pois:
        by_area: dict[str, list[str]] = {}
        for poi in sorted_pois:
            if poi.area == "Unknown":
                continue
            by_area.setdefault(poi.area, []).extend(poi.tags)
        areas = [
            _geo_cell_area(area_id, city, tags)
            for area_id, tags in sorted(by_area.items())
        ]
    return RetrievalContext(
        pois=sorted_pois,
        areas=areas,
        poi_rows=[_poi_row(poi) for poi in sorted_pois],
        area_rows=[_area_row(area) for area in areas],
        poi_provenance=poi_provenance,
    )
