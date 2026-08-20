import json
from collections import OrderedDict
from pathlib import Path

from gateway.places.contracts import (
    PartialPlaceResult,
    PlaceCandidate,
    PlaceClaim,
    PlaceSearchRequest,
)
from gateway.places.registry import PlaceGatewayError

_CACHE_MAX_ENTRIES = 8
_SnapshotCacheKey = tuple[str, int, int]
_SNAPSHOT_CACHE: OrderedDict[_SnapshotCacheKey, list[PlaceCandidate]] = OrderedDict()


def clear_snapshot_catalog_cache() -> None:
    _SNAPSHOT_CACHE.clear()


def _cache_key(catalog_path: Path) -> _SnapshotCacheKey:
    stat = catalog_path.stat()
    return (str(catalog_path.resolve()), stat.st_mtime_ns, stat.st_size)


class SnapshotPlaceAdapter:
    def __init__(self, catalog_path: Path) -> None:
        self.catalog_path = catalog_path
        self._cache: list[PlaceCandidate] | None = None

    def _load(self) -> list[PlaceCandidate]:
        if self._cache is not None:
            return self._cache

        if not self.catalog_path.exists():
            raise PlaceGatewayError(code="provider_unavailable", message="Catalog snapshot missing")

        try:
            key = _cache_key(self.catalog_path)
            if key in _SNAPSHOT_CACHE:
                _SNAPSHOT_CACHE.move_to_end(key)
                self._cache = _SNAPSHOT_CACHE[key]
                return self._cache

            content = self.catalog_path.read_text(encoding="utf-8")
            data = json.loads(content)

            # create lookup for claims
            # we need to map source to licence and attribution
            source_map = {}
            for s in data.get("sources", []):
                source_map[s["id"]] = s

            # claims have licence_id but lack attribution text?
            # Wait, in conftest I set attribution_requirements.
            # wait, the spec says "map claims into PlaceCandidate"
            places_claims: dict[str, list[PlaceClaim]] = {}
            for c in data.get("claims", []):
                pid = c["place_id"]
                if pid not in places_claims:
                    places_claims[pid] = []

                c_dict = dict(c)
                src = source_map.get(c_dict.get("source_id"))
                if src:
                    if not c_dict.get("source_url"):
                        c_dict["source_url"] = src.get("url") or src.get("source_url") or ""
                    if not c_dict.get("licence_id"):
                        c_dict["licence_id"] = src.get("licence_id") or ""
                    if not c_dict.get("source_release"):
                        c_dict["source_release"] = src.get("release") or src.get("source_release")
                    if not c_dict.get("attribution_requirements"):
                        c_dict["attribution_requirements"] = (
                            src.get("attribution_text") or src.get("attribution_requirements")
                        )
                    if not c_dict.get("verified_by"):
                        c_dict["verified_by"] = (
                            src.get("verified_by") or f"catalog:{c_dict.get('source_id')}"
                        )
                    if not c_dict.get("retrieved_at"):
                        c_dict["retrieved_at"] = src.get("retrieved_at") or "2026-01-01T00:00:00Z"
                    if not c_dict.get("last_verified"):
                        c_dict["last_verified"] = src.get("last_verified") or "2026-01-01T00:00:00Z"
                places_claims[pid].append(PlaceClaim.model_validate(c_dict))

            candidates: list[PlaceCandidate] = []
            for p in data.get("places", []):
                pid = p["place_id"]
                claims = places_claims.get(pid, [])

                # Check status
                has_hours = any(c.field == "opening_hours" for c in claims)
                needs_verify = any(getattr(c, "needs_verification", False) for c in claims)

                if not has_hours or needs_verify:
                    status = "verify_required"
                else:
                    status = "cached"

                candidates.append(PlaceCandidate(place_id=pid, status=status, claims=claims))

            candidates.sort(key=lambda c: c.place_id)
            self._cache = candidates
            _SNAPSHOT_CACHE[key] = candidates
            _SNAPSHOT_CACHE.move_to_end(key)
            while len(_SNAPSHOT_CACHE) > _CACHE_MAX_ENTRIES:
                _SNAPSHOT_CACHE.popitem(last=False)
            return self._cache

        except PlaceGatewayError:
            raise
        except Exception as e:
            raise PlaceGatewayError(code="provider_unavailable", message=str(e)) from e

    def search_places(
        self, request: PlaceSearchRequest
    ) -> tuple[list[PlaceCandidate], PartialPlaceResult | None]:
        candidates = self._load()
        import math

        def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            R = 6371.0
            lat1_rad = math.radians(lat1)
            lon1_rad = math.radians(lon1)
            lat2_rad = math.radians(lat2)
            lon2_rad = math.radians(lon2)
            dlat = lat2_rad - lat1_rad
            dlon = lon2_rad - lon1_rad
            a = (
                math.sin(dlat / 2) ** 2
                + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
            )
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c

        filtered = []
        for c in candidates:
            # check category
            if request.category_filters:
                cat = next((claim.value for claim in c.claims if claim.field == "category"), None)
                if cat not in request.category_filters:
                    continue
            filtered.append(c)

        if request.origin_lat is not None and request.origin_lon is not None:
            # Capture for mypy
            o_lat = request.origin_lat
            o_lon = request.origin_lon

            def get_distance(c: PlaceCandidate) -> float:
                coords = next(
                    (claim.value for claim in c.claims if claim.field == "coordinates"), None
                )
                if not coords or not isinstance(coords, dict):
                    return float("inf")
                lat = coords.get("lat")
                lon = coords.get("lon")
                if lat is None or lon is None:
                    return float("inf")
                return haversine(o_lat, o_lon, lat, lon)

            filtered.sort(key=lambda c: (get_distance(c), c.place_id))

        if len(filtered) > request.max_results:
            return (
                filtered[: request.max_results],
                PartialPlaceResult(
                    stop_reason="budget_exhausted", unresolved_needs=["budget_exhausted"]
                ),
            )

        return filtered, None
