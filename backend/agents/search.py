from __future__ import annotations

from pathlib import Path

from agents.models import (
    PlaceProviderDiagnostic,
    PlaceSearchRequest,
    PlaceSearchResponse,
    PlaceSearchResult,
)
from core.db import KnowledgeBase
from core.models import POI
from core.trip_models import POIEvidence
from gateway.catalog.activate import active_catalog_path
from gateway.catalog.regions import Region, get_region
from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
from gateway.places.contracts import (
    PlaceCandidate,
)
from gateway.places.contracts import (
    PlaceSearchRequest as GatewayPlaceSearchRequest,
)
from gateway.places.protocol import PlaceProviderAdapter
from gateway.places.registry import PlaceGatewayError


def _adapter_provider_id(provider_adapter: PlaceProviderAdapter) -> str:
    raw_provider_id = getattr(provider_adapter, "provider_id", None)
    if isinstance(raw_provider_id, str) and raw_provider_id:
        return raw_provider_id
    return provider_adapter.__class__.__name__


def _map_candidate_to_poi_and_evidence(
    c: PlaceCandidate, city: str, region: Region | None = None
) -> tuple[POI, POIEvidence]:
    from agents.retrieval import _map_candidate_to_poi

    poi = _map_candidate_to_poi(c, city, region)
    status = c.status

    claim_needs_ver = any(cl.needs_verification for cl in c.claims)
    needs_ver = (
        (status in ("verify_required", "cached", "estimated"))
        or claim_needs_ver
        or poi.provenance.needs_verification
    )
    poi.provenance.needs_verification = needs_ver

    lic = next((cl.licence_id for cl in c.claims if cl.licence_id), None)
    attr = next(
        (cl.attribution_requirements for cl in c.claims if cl.attribution_requirements),
        None,
    )

    ev = POIEvidence(
        poi_id=c.place_id,
        status=status,
        last_verified=poi.provenance.last_verified,
        licence_id=lic,
        attribution=attr,
        needs_verification=needs_ver,
    )
    return poi, ev


def search_catalog_places(
    request: PlaceSearchRequest,
    kb: KnowledgeBase,
    catalogs_root: Path = Path("catalogs"),
    provider_adapter: PlaceProviderAdapter | None = None,
) -> PlaceSearchResponse:
    """Deterministically searches local active place catalogs and seeded knowledge base."""
    dest_iata = request.destination.strip().upper()
    region = get_region(dest_iata)
    city_name = region.city_name if region else dest_iata

    items: list[tuple[POI, POIEvidence]] = []
    seen_ids: set[str] = set()

    # 1. Load active snapshot catalog if present
    if region is not None:
        try:
            catalog_path = active_catalog_path(catalogs_root, catalog_id=region.catalog_id)
            if catalog_path and catalog_path.exists():
                adapter = SnapshotPlaceAdapter(catalog_path)
                candidates = adapter._load()
                for c in candidates:
                    if c.place_id not in seen_ids:
                        poi, ev = _map_candidate_to_poi_and_evidence(c, city_name, region)
                        items.append((poi, ev))
                        seen_ids.add(c.place_id)
        except (FileNotFoundError, Exception):
            pass

    diagnostics: list[PlaceProviderDiagnostic] = []

    # 2. Optionally supplement with extra provider adapter if supplied (e.g. Tripadvisor)
    if provider_adapter is not None:
        provider_id = _adapter_provider_id(provider_adapter)
        try:
            gw_req = GatewayPlaceSearchRequest(
                query=request.query,
                destination_area_id=city_name,
                max_results=request.limit,
                category_filters=[request.category] if request.category else [],
            )
            extra_candidates, partial = provider_adapter.search_places(gw_req)
            if partial is not None:
                diagnostics.append(
                    PlaceProviderDiagnostic(
                        provider_id=provider_id,
                        code=partial.stop_reason,
                        message=f"Provider returned partial results: {partial.stop_reason}",
                        fallback_used=True,
                        stop_reason=partial.stop_reason,
                    )
                )
            for c in extra_candidates:
                if c.place_id not in seen_ids:
                    poi, ev = _map_candidate_to_poi_and_evidence(c, city_name, region)
                    items.append((poi, ev))
                    seen_ids.add(c.place_id)
        except PlaceGatewayError as e:
            # Typed gateway failure: record safe diagnostic and fall back cleanly
            diagnostics.append(
                PlaceProviderDiagnostic(
                    provider_id=provider_id,
                    code=e.code,
                    message=e.message,
                    fallback_used=True,
                    stop_reason=e.code,
                )
            )
        except Exception:
            # Unexpected error: record safe diagnostic without leaking stack traces or secrets
            diagnostics.append(
                PlaceProviderDiagnostic(
                    provider_id=provider_id,
                    code="internal_error",
                    message="Provider search encountered an unexpected internal error",
                    fallback_used=True,
                    stop_reason="internal_error",
                )
            )

    # 3. Load seeded KB POIs
    for p in kb.pois(city_name):
        if p.id not in seen_ids:
            ev = POIEvidence(
                poi_id=p.id,
                status="live",
                last_verified=p.provenance.last_verified,
                needs_verification=p.provenance.needs_verification,
                licence_id="proprietary",
                attribution="TripPlanner Curated",
            )
            items.append((p, ev))
            seen_ids.add(p.id)

    # 3. Filter by category
    if request.category:
        cat_lower = request.category.strip().casefold()
        items = [
            (poi, ev)
            for poi, ev in items
            if any(t.casefold() == cat_lower for t in poi.tags)
        ]

    # 4. Filter by query
    q = request.query.strip().casefold()
    if q:
        items = [
            (poi, ev)
            for poi, ev in items
            if q in poi.name.casefold()
            or any(q in t.casefold() for t in poi.tags)
            or q in poi.description.casefold()
        ]

    # 5. Deterministic sorting
    def _sort_key(entry: tuple[POI, POIEvidence]) -> tuple[int, int, str, str]:
        poi, _ = entry
        name_lower = poi.name.casefold()
        starts = -1 if q and name_lower.startswith(q) else 0
        contains = -1 if q and q in name_lower else 0
        return (starts, contains, name_lower, poi.id)

    items.sort(key=_sort_key)
    sliced = items[: request.limit]

    results = [
        PlaceSearchResult(
            poi_id=poi.id,
            name=poi.name,
            category=poi.tags[0] if poi.tags else "other",
            area=poi.area,
            lat=poi.lat,
            lon=poi.lon,
            price_minor=poi.price_minor,
            currency=poi.currency,
            evidence=ev,
        )
        for poi, ev in sliced
    ]

    return PlaceSearchResponse(results=results, diagnostics=diagnostics)
