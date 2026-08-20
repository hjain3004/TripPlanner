from pathlib import Path

from gateway.catalog.tiles import (
    TiledPlaceAdapter,
    build_tiles_from_claims,
    tile_id_for_point,
    tiles_for_bbox,
)
from gateway.places.contracts import PlaceSearchRequest


def test_tile_id_is_pure_function_and_boundary_unambiguous() -> None:
    # Stable mapping
    assert tile_id_for_point(1.35, 103.82) == "tile_1.3_103.8"
    assert tile_id_for_point(25.033, 121.565) == "tile_25.0_121.5"
    assert tile_id_for_point(-33.868, 151.209) == "tile_-33.9_151.2"

    # Exact boundary coordinates land in exactly one tile: [lat_step, lat_step + step)
    assert tile_id_for_point(1.4, 103.8) == "tile_1.4_103.8"
    assert tile_id_for_point(1.399999, 103.8) == "tile_1.3_103.8"
    assert tile_id_for_point(1.3, 103.9) == "tile_1.3_103.9"
    assert tile_id_for_point(1.3, 103.899999) == "tile_1.3_103.8"


def test_tiles_for_bbox_covers_grid() -> None:
    tiles = tiles_for_bbox(min_lat=1.31, min_lon=103.81, max_lat=1.45, max_lon=103.95)
    # Lat: 1.3, 1.4. Lon: 103.8, 103.9 -> 2x2 = 4 tiles
    assert sorted(tiles) == [
        "tile_1.3_103.8",
        "tile_1.3_103.9",
        "tile_1.4_103.8",
        "tile_1.4_103.9",
    ]


def test_tiled_adapter_loads_fewer_bytes_than_whole_catalog(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from gateway.places.contracts import PlaceClaim

    now = datetime(2026, 1, 1, tzinfo=UTC)
    claims: list[PlaceClaim] = []

    def _make(pid: str, lat: float, lon: float, name: str) -> list[PlaceClaim]:
        return [
            PlaceClaim(
                place_id=pid,
                field="coordinates",
                value={"lat": lat, "lon": lon},
                source_id="src",
                source_url="http://x",
                retrieved_at=now,
                last_verified=now,
                verified_by="cat",
                confidence=0.9,
                needs_verification=False,
                licence_id="L",
            ),
            PlaceClaim(
                place_id=pid,
                field="category",
                value="attraction",
                source_id="src",
                source_url="http://x",
                retrieved_at=now,
                last_verified=now,
                verified_by="cat",
                confidence=0.9,
                needs_verification=False,
                licence_id="L",
            ),
            PlaceClaim(
                place_id=pid,
                field="name",
                value=name,
                source_id="src",
                source_url="http://x",
                retrieved_at=now,
                last_verified=now,
                verified_by="cat",
                confidence=0.9,
                needs_verification=False,
                licence_id="L",
            ),
        ]

    # Tile 1 (1.3, 103.8) - 10 places
    for i in range(10):
        claims.extend(_make(f"p_t1_{i}", 1.32, 103.82, f"Place T1 {i}"))

    # Tile 2 (1.8, 103.8) - 10 places (far away north)
    for i in range(10):
        claims.extend(_make(f"p_t2_{i}", 1.82, 103.82, f"Place T2 {i}"))

    # Tile 3 (1.3, 104.5) - 10 places (far away east)
    for i in range(10):
        claims.extend(_make(f"p_t3_{i}", 1.32, 104.52, f"Place T3 {i}"))

    tiles_dir = tmp_path / "tiles"
    tile_paths = build_tiles_from_claims(claims, tiles_dir)
    assert len(tile_paths) == 3

    total_tile_bytes = sum(p.stat().st_size for p in tile_paths.values())

    adapter = TiledPlaceAdapter(tiles_dir, radius_km=5.0)
    req = PlaceSearchRequest(
        destination_area_id="",
        origin_lat=1.32,
        origin_lon=103.82,
        max_results=5,
        category_filters=["attraction"],
    )
    candidates, partial = adapter.search_places(req)

    assert len(candidates) == 5
    # Must only load tile_1.3_103.8
    assert adapter.last_loaded_tiles == ["tile_1.3_103.8"]
    assert adapter.last_bytes_loaded < total_tile_bytes
    assert adapter.last_bytes_loaded == tile_paths["tile_1.3_103.8"].stat().st_size


def test_build_catalog_tiles_from_manifest(tmp_path: Path) -> None:
    import hashlib
    import json
    import zipfile

    from gateway.catalog.build import build_catalog_tiles
    from gateway.catalog.quality import _MIN_PER_CATEGORY

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    places = []
    idx = 1
    for cat, min_count in _MIN_PER_CATEGORY.items():
        for _ in range(min_count):
            places.append(
                {
                    "id": f"ext_{idx}",
                    "names": {"primary": f"Place {idx}"},
                    "categories": {"primary": "zoo" if cat == "attraction" else cat},
                    "geometry": {"lat": 1.35, "lon": 103.82},
                }
            )
            idx += 1

    zip_path = tmp_path / "dummy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("data.json", json.dumps(places))

    payload = zip_path.read_bytes()
    chk = hashlib.sha256(payload).hexdigest()
    raw_file = raw_dir / "overture_sg_2026-07-22.0.zip"
    raw_file.write_bytes(payload)

    manifest_yaml = f"""
catalog_id: sg-test
catalog_release: "2026-08-01"
centroid_lat: 1.3521
centroid_lon: 103.8198
bbox:
  min_lat: 1.20
  max_lat: 1.48
  min_lon: 103.60
  max_lon: 104.09
sources:
  - source_id: overture_sg
    source_url: "https://example.com/overture-sg"
    licence_id: "CDLA-Permissive-2.0"
    source_release: "2026-07-22.0"
    checksum: "{chk}"
    max_bytes: 50000
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture Maps Foundation"
"""
    m_path = tmp_path / "manifest.yaml"
    m_path.write_text(manifest_yaml, encoding="utf-8")

    tiles_dir = tmp_path / "tiles"
    tile_paths = build_catalog_tiles(m_path, raw_dir, tmp_path / "work", tiles_dir)
    assert len(tile_paths) == 1
    assert "tile_1.3_103.8" in tile_paths
    assert tile_paths["tile_1.3_103.8"].exists()

