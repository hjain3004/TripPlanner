from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from gateway.catalog.activate import CatalogArtifact, PinnedSource, canonical_json
from gateway.catalog.quality import QualityReport
from gateway.places.contracts import (
    CompactClaim,
    PartialPlaceResult,
    Place,
    PlaceCandidate,
    PlaceClaim,
    PlaceSearchRequest,
)


def tile_id_for_point(lat: float, lon: float, step: float = 0.1) -> str:
    """Deterministic, unambiguous mapping from (lat, lon) to tile ID.
    Half-open interval [lat_step, lat_step + step) and [lon_step, lon_step + step).
    Uses integer scaling to avoid IEEE-754 division truncation at boundary points."""
    scale = round(1.0 / step)
    lat_i = math.floor(round(lat * scale, 5))
    lon_i = math.floor(round(lon * scale, 5))
    lat_step = round(lat_i / scale, 4)
    lon_step = round(lon_i / scale, 4)
    return f"tile_{lat_step:.1f}_{lon_step:.1f}"


def tiles_for_bbox(
    min_lat: float, min_lon: float, max_lat: float, max_lon: float, step: float = 0.1
) -> list[str]:
    scale = round(1.0 / step)
    min_lat_i = math.floor(round(min_lat * scale, 5))
    max_lat_i = math.floor(round(max_lat * scale, 5))
    min_lon_i = math.floor(round(min_lon * scale, 5))
    max_lon_i = math.floor(round(max_lon * scale, 5))

    tiles = []
    for lat_i in range(min_lat_i, max_lat_i + 1):
        for lon_i in range(min_lon_i, max_lon_i + 1):
            lat_v = round(lat_i / scale, 4)
            lon_v = round(lon_i / scale, 4)
            tiles.append(f"tile_{lat_v:.1f}_{lon_v:.1f}")
    return sorted(set(tiles))


def tiles_for_radius(
    origin_lat: float, origin_lon: float, radius_km: float = 15.0, step: float = 0.1
) -> list[str]:
    d_lat = radius_km / 111.0
    cos_lat = max(0.01, math.cos(math.radians(origin_lat)))
    d_lon = radius_km / (111.0 * cos_lat)
    return tiles_for_bbox(
        min_lat=origin_lat - d_lat,
        min_lon=origin_lon - d_lon,
        max_lat=origin_lat + d_lat,
        max_lon=origin_lon + d_lon,
        step=step,
    )


def build_tiles_from_claims(
    claims: list[PlaceClaim], out_dir: Path, step: float = 0.1
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)

    places_claims: dict[str, list[PlaceClaim]] = {}
    for c in claims:
        places_claims.setdefault(c.place_id, []).append(c)

    tiles_places: dict[str, list[Place]] = {}
    tiles_claims: dict[str, list[CompactClaim]] = {}
    sources_map: dict[str, PinnedSource] = {}

    for pid, c_list in places_claims.items():
        coords = next((c.value for c in c_list if c.field == "coordinates"), None)
        if not coords or not isinstance(coords, dict):
            continue
        lat = float(coords["lat"])
        lon = float(coords["lon"])
        tid = tile_id_for_point(lat, lon, step=step)

        tiles_places.setdefault(tid, []).append(Place(place_id=pid))
        for c in c_list:
            if c.source_id not in sources_map:
                sources_map[c.source_id] = PinnedSource(
                    id=c.source_id,
                    url=c.source_url or "",
                    release=c.source_release or "1",
                    licence_id=c.licence_id or "",
                    attribution_text=c.attribution_requirements or "",
                    format="overture_json",
                    checksum="0" * 64,
                )
            tiles_claims.setdefault(tid, []).append(
                CompactClaim(
                    place_id=c.place_id,
                    field=c.field,
                    value=c.value,
                    source_id=c.source_id,
                    confidence=c.confidence,
                    needs_verification=c.needs_verification,
                    lifecycle_state=c.lifecycle_state,
                )
            )

    result_paths: dict[str, Path] = {}
    for tid, t_places in sorted(tiles_places.items()):
        t_claims = tiles_claims.get(tid, [])
        art = CatalogArtifact(
            catalog_id=tid,
            catalog_release="2026-08-01",
            sources=list(sources_map.values()),
            places=t_places,
            claims=t_claims,
            contradictions=[],
            quality=QualityReport(
                passed=True,
                failures=[],
                by_category={},
                places_without_coordinates=0,
                places_with_unknown_hours=0,
                dropped_uncategorized=0,
                dropped_out_of_bbox=0,
            ),
        )
        target = out_dir / f"{tid}.json"
        target.write_text(canonical_json(art), encoding="utf-8")
        result_paths[tid] = target

    return result_paths


class TiledPlaceAdapter:
    """Place provider adapter that loads only the spatial tiles intersecting the search radius."""

    def __init__(
        self,
        tile_root: Path,
        radius_km: float = 15.0,
        cache_manager: Any = None,
    ) -> None:
        self.tile_root = tile_root
        self.radius_km = radius_km
        self.cache_manager = cache_manager
        self._tile_cache: dict[str, list[PlaceCandidate]] = {}
        self.last_loaded_tiles: list[str] = []
        self.last_bytes_loaded: int = 0

    def _load_tile(self, tile_id: str) -> list[PlaceCandidate]:
        if tile_id in self._tile_cache:
            return self._tile_cache[tile_id]

        p = self.tile_root / f"{tile_id}.json"
        if not p.exists():
            p = self.tile_root / f"active_{tile_id}.json"
        if not p.exists():
            return []

        if self.cache_manager:
            self.cache_manager.touch_tile(tile_id)

        self.last_bytes_loaded += p.stat().st_size
        self.last_loaded_tiles.append(tile_id)

        content = p.read_text(encoding="utf-8")
        data = json.loads(content)

        source_map = {s["id"]: s for s in data.get("sources", [])}
        places_claims: dict[str, list[PlaceClaim]] = {}

        for c in data.get("claims", []):
            pid = c["place_id"]
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
            places_claims.setdefault(pid, []).append(PlaceClaim.model_validate(c_dict))

        candidates: list[PlaceCandidate] = []
        for pl in data.get("places", []):
            pid = pl["place_id"]
            claims = places_claims.get(pid, [])
            has_hours = any(c.field == "opening_hours" for c in claims)
            needs_verify = any(getattr(c, "needs_verification", False) for c in claims)
            status = "verify_required" if (not has_hours or needs_verify) else "cached"
            candidates.append(PlaceCandidate(place_id=pid, status=status, claims=claims))

        candidates.sort(key=lambda c: c.place_id)
        self._tile_cache[tile_id] = candidates
        return candidates

    def search_places(
        self, request: PlaceSearchRequest
    ) -> tuple[list[PlaceCandidate], PartialPlaceResult | None]:
        self.last_loaded_tiles = []
        self.last_bytes_loaded = 0

        if request.origin_lat is not None and request.origin_lon is not None:
            tile_ids = tiles_for_radius(
                request.origin_lat, request.origin_lon, radius_km=self.radius_km
            )
        else:
            tile_files = list(self.tile_root.glob("tile_*.json")) + list(
                self.tile_root.glob("active_tile_*.json")
            )
            tile_ids = [
                p.stem.replace("active_", "")
                for p in tile_files
                if not p.name.endswith(".summary.json")
            ]

        candidates: list[PlaceCandidate] = []
        for tid in tile_ids:
            candidates.extend(self._load_tile(tid))

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

        filtered: list[PlaceCandidate] = []
        for c in candidates:
            if request.category_filters:
                cat = next(
                    (claim.value for claim in c.claims if claim.field == "category"), None
                )
                if cat not in request.category_filters:
                    continue
            filtered.append(c)

        if request.origin_lat is not None and request.origin_lon is not None:
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
                return haversine(o_lat, o_lon, float(lat), float(lon))

            filtered.sort(key=lambda c: (get_distance(c), c.place_id))

        if len(filtered) > request.max_results:
            return (
                filtered[: request.max_results],
                PartialPlaceResult(
                    stop_reason="budget_exhausted", unresolved_needs=["budget_exhausted"]
                ),
            )

        return filtered, None
