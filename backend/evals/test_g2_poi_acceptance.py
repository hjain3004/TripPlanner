from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

BACKEND = Path(__file__).parent.parent


def test_no_active_catalog_artifact_is_tracked_by_git() -> None:
    result = subprocess.run(
        ["git", "ls-files", "backend/catalogs"],
        cwd=BACKEND.parent,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == ""


def test_catalogs_directory_is_gitignored() -> None:
    gitignore = (BACKEND / ".gitignore").read_text()
    assert "catalogs/" in gitignore
    assert "raw_overture/" in gitignore


def test_all_six_regional_corridors_resolve() -> None:
    from gateway.catalog.regions import get_region

    for iata in ("SIN", "BOM", "DXB", "NYC", "LON", "PAR"):
        region = get_region(iata)
        assert region is not None, f"{iata} not registered in regions.yaml"
        assert region.catalog_id


def test_place_and_claim_identity_model_is_unchanged() -> None:
    from gateway.places.contracts import CompactClaim, Place, PlaceClaim

    assert "external_ids" in Place.model_fields
    assert "place_id" in PlaceClaim.model_fields
    assert "licence_id" not in CompactClaim.model_fields  # compaction optimization intact


def test_tiling_preserves_real_licence_release_and_attribution(tmp_path: Path) -> None:
    from gateway.catalog.build import build_catalog_tiles
    from gateway.catalog.quality import _MIN_PER_CATEGORY
    from gateway.catalog.tiles import TiledPlaceAdapter
    from gateway.places.contracts import PlaceSearchRequest

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
catalog_id: sg-g2-test
catalog_release: "2026-08-20"
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
    build_catalog_tiles(m_path, raw_dir, tmp_path / "work", tiles_dir)

    adapter = TiledPlaceAdapter(tiles_dir, radius_km=5.0)
    req = PlaceSearchRequest(
        destination_area_id="",
        origin_lat=1.35,
        origin_lon=103.82,
        max_results=10,
        category_filters=["attraction"],
    )
    candidates, _partial = adapter.search_places(req)

    assert candidates  # non-vacuous
    all_claims = [c for cand in candidates for c in cand.claims]
    assert all_claims
    assert all(c.licence_id == "CDLA-Permissive-2.0" for c in all_claims)
    assert all(c.source_release == "2026-07-22.0" for c in all_claims)
    assert all(c.attribution_requirements == "Overture Maps Foundation" for c in all_claims)
