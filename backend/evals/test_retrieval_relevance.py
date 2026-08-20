import json
from pathlib import Path

from gateway.catalog.quality import SUPPORTED_CATEGORIES
from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
from gateway.places.contracts import PlaceSearchRequest


def _write_catalog(tmp_path: Path, places: list[dict], claims: list[dict]) -> Path:
    cat_path = tmp_path / "active.json"
    cat_path.write_text(json.dumps({"places": places, "claims": claims}))
    return cat_path


def test_every_candidate_has_a_supported_category(tmp_path: Path) -> None:
    # Build a catalog fixture containing both categorized venues and uncategorized records
    places = [
        {"place_id": "pl_1", "external_ids": []},
        {"place_id": "pl_2", "external_ids": []},
    ]
    claims = [
        {
            "place_id": "pl_1",
            "field": "category",
            "value": "park",
            "source_id": "src",
            "source_url": "http://x",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_release": "1",
            "last_verified": "2026-01-01T00:00:00Z",
            "verified_by": "test",
            "confidence": 0.9,
            "needs_verification": False,
            "licence_id": "L",
            "attribution_requirements": "A",
        },
        # pl_2 is uncategorized
    ]
    cat_path = _write_catalog(tmp_path, places, claims)
    adapter = SnapshotPlaceAdapter(cat_path)

    # Assert retrieval returns only the categorized venue
    req = PlaceSearchRequest(
        origin_lat=1.3,
        origin_lon=103.8,
        category_filters=list(SUPPORTED_CATEGORIES),
        max_results=10,
        destination_area_id="",
        timeout_ms=5000,
    )
    candidates, _ = adapter.search_places(req)

    # Anti-vacuity: assert fixture has both
    assert len(places) == 2

    assert len(candidates) == 1
    assert candidates[0].place_id == "pl_1"


def test_candidates_are_ordered_by_distance_from_origin(tmp_path: Path) -> None:
    # Origin is 1.3, 103.8
    places = [
        {"place_id": "pl_1", "external_ids": []},
        {"place_id": "pl_2", "external_ids": []},
    ]
    # pl_1 is further (lat: 1.4, lon: 103.8) -> ~11km
    # pl_2 is nearer (lat: 1.31, lon: 103.8) -> ~1km
    claims = [
        {
            "place_id": "pl_1",
            "field": "coordinates",
            "value": {"lat": 1.4, "lon": 103.8},
            "source_id": "src",
            "source_url": "http://x",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_release": "1",
            "last_verified": "2026-01-01T00:00:00Z",
            "verified_by": "test",
            "confidence": 0.9,
            "needs_verification": False,
            "licence_id": "L",
            "attribution_requirements": "A",
        },
        {
            "place_id": "pl_1",
            "field": "category",
            "value": "park",
            "source_id": "src",
            "source_url": "http://x",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_release": "1",
            "last_verified": "2026-01-01T00:00:00Z",
            "verified_by": "test",
            "confidence": 0.9,
            "needs_verification": False,
            "licence_id": "L",
            "attribution_requirements": "A",
        },
        {
            "place_id": "pl_2",
            "field": "coordinates",
            "value": {"lat": 1.31, "lon": 103.8},
            "source_id": "src",
            "source_url": "http://x",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_release": "1",
            "last_verified": "2026-01-01T00:00:00Z",
            "verified_by": "test",
            "confidence": 0.9,
            "needs_verification": False,
            "licence_id": "L",
            "attribution_requirements": "A",
        },
        {
            "place_id": "pl_2",
            "field": "category",
            "value": "park",
            "source_id": "src",
            "source_url": "http://x",
            "retrieved_at": "2026-01-01T00:00:00Z",
            "source_release": "1",
            "last_verified": "2026-01-01T00:00:00Z",
            "verified_by": "test",
            "confidence": 0.9,
            "needs_verification": False,
            "licence_id": "L",
            "attribution_requirements": "A",
        },
    ]

    req = PlaceSearchRequest(
        origin_lat=1.3,
        origin_lon=103.8,
        category_filters=list(SUPPORTED_CATEGORIES),
        max_results=10,
        destination_area_id="",
        timeout_ms=5000,
    )

    cat_path = _write_catalog(tmp_path, places, claims)
    candidates, _ = SnapshotPlaceAdapter(cat_path).search_places(req)

    assert [c.place_id for c in candidates] == ["pl_2", "pl_1"]

    # Assert permutation doesn't change output
    places_rev = places[::-1]
    claims_rev = claims[::-1]
    cat_path_rev = _write_catalog(tmp_path, places_rev, claims_rev)
    candidates_rev, _ = SnapshotPlaceAdapter(cat_path_rev).search_places(req)

    assert [c.place_id for c in candidates_rev] == ["pl_2", "pl_1"]
