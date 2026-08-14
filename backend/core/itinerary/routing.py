from typing import Any, Tuple, Iterable, List
from datetime import datetime, UTC
from core.itinerary.contracts import RouteMatrix, RouteCell
from core.itinerary.compose import haversine_km, estimate_travel_min

def build_geodesic_matrix_with_gaps(places: Iterable[Any], mode: str) -> Tuple[RouteMatrix, List[str]]:
    valid_places = []
    unroutable = []
    for p in places:
        if getattr(p, "lat", None) is None or getattr(p, "lon", None) is None:
            unroutable.append(p.id)
        else:
            valid_places.append(p)
            
    valid_places.sort(key=lambda p: p.id)
    cells = []
    
    # Geodesic estimates are deterministic mathematical functions; their "retrieval"
    # is effectively constant. Use a fixed date so they test deterministically.
    now = datetime(2026, 1, 1, tzinfo=UTC)
    
    # Generate all pairs
    for a in valid_places:
        for b in valid_places:
            if a.id == b.id:
                continue
            dist = haversine_km(a.lat, a.lon, b.lat, b.lon)
            dur = estimate_travel_min(a.lat, a.lon, b.lat, b.lon)
            cells.append(
                RouteCell(
                    origin_place_id=a.id,
                    destination_place_id=b.id,
                    mode=mode,
                    duration_min=dur,
                    distance_km=dist,
                    retrieved_at=now,
                    source="geodesic_estimate",
                    status="estimated",
                    confidence=0.8
                )
            )
            
    return RouteMatrix(cells=cells), unroutable

def build_geodesic_matrix(places: Iterable[Any], mode: str) -> RouteMatrix:
    matrix, _ = build_geodesic_matrix_with_gaps(places, mode)
    return matrix
