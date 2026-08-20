"""Gate I7: every activated region passes the same structural/provenance
invariants, regardless of which city it is. Requires real catalogs built on
disk (backend/catalogs/active_*.json) - skips per-catalog otherwise, since
this is a real-data integration check, not a hermetic unit test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gateway.catalog.manifest import load_manifest
from gateway.catalog.regions import load_regions

BACKEND = Path(__file__).parent.parent
CATALOGS_ROOT = BACKEND / "catalogs"
REGIONS_PATH = BACKEND / "gateway" / "catalog" / "fixtures" / "regions.yaml"
FIXTURES = BACKEND / "gateway" / "catalog" / "fixtures"

_MANIFEST_BY_CATALOG_ID = {
    "sg-core": FIXTURES / "manifest_sg.yaml",
    "bom-core": FIXTURES / "manifest_bom.yaml",
    "dxb-core": FIXTURES / "manifest_dxb.yaml",
    "nyc-core": FIXTURES / "manifest_nyc.yaml",
    "lon-core": FIXTURES / "manifest_lon.yaml",
    "par-core": FIXTURES / "manifest_par.yaml",
}


def _activated_regions() -> list[tuple[str, dict]]:
    regions = load_regions(REGIONS_PATH)
    found = []
    for region in regions.values():
        path = CATALOGS_ROOT / f"active_{region.catalog_id}.json"
        if path.exists():
            found.append((region.catalog_id, json.loads(path.read_text(encoding="utf-8"))))
    return found


_ACTIVATED = _activated_regions()

pytestmark = pytest.mark.allow_real_catalog


@pytest.mark.skipif(not _ACTIVATED, reason="requires at least one real catalog built")
def test_the_gate_actually_found_catalogs() -> None:
    """Anti-vacuity: the gate below must not silently pass because it found
    nothing to check."""
    assert len(_ACTIVATED) >= 1


@pytest.mark.parametrize("catalog_id,data", _ACTIVATED, ids=[c for c, _ in _ACTIVATED])
def test_at_least_95_percent_of_places_are_categorized(catalog_id: str, data: dict) -> None:
    place_count = len(data["places"])
    categorized = sum(data["quality"]["by_category"].values())
    assert place_count > 0
    assert categorized / place_count >= 0.95


@pytest.mark.parametrize("catalog_id,data", _ACTIVATED, ids=[c for c, _ in _ACTIVATED])
def test_zero_places_are_missing_coordinates(catalog_id: str, data: dict) -> None:
    assert data["quality"]["places_without_coordinates"] == 0


@pytest.mark.parametrize("catalog_id,data", _ACTIVATED, ids=[c for c, _ in _ACTIVATED])
def test_every_claim_carries_a_licence(catalog_id: str, data: dict) -> None:
    claims = data["claims"]
    assert claims, "fixture must not be vacuous"
    source_map = {s["id"]: s for s in data.get("sources", [])}
    assert all(
        c.get("licence_id") or source_map.get(c.get("source_id"), {}).get("licence_id")
        for c in claims
    )


@pytest.mark.parametrize("catalog_id,data", _ACTIVATED, ids=[c for c, _ in _ACTIVATED])
def test_every_place_is_inside_the_declared_bbox(catalog_id: str, data: dict) -> None:
    manifest_path = _MANIFEST_BY_CATALOG_ID[catalog_id]
    manifest = load_manifest(manifest_path)
    assert manifest.bbox is not None
    b = manifest.bbox

    coords_by_place: dict[str, dict] = {}
    for c in data["claims"]:
        if c["field"] == "coordinates":
            coords_by_place[c["place_id"]] = c["value"]

    checked = 0
    for place in data["places"]:
        coords = coords_by_place.get(place["place_id"])
        assert coords is not None, f"{place['place_id']} has no coordinate claim"
        assert b.min_lat <= coords["lat"] <= b.max_lat
        assert b.min_lon <= coords["lon"] <= b.max_lon
        checked += 1
    assert checked == len(data["places"])


def test_all_activated_regions_have_disjoint_place_ids() -> None:
    if len(_ACTIVATED) < 2:
        pytest.skip("requires at least two real catalogs built")
    seen: dict[str, str] = {}
    for catalog_id, data in _ACTIVATED:
        for place in data["places"]:
            pid = place["place_id"]
            assert pid not in seen, (
                f"place_id {pid} appears in both {seen.get(pid)} and {catalog_id}"
            )
            seen[pid] = catalog_id
    assert len(seen) == sum(len(data["places"]) for _, data in _ACTIVATED)
