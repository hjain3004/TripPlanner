from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from gateway.evidence.nodes import (
    Claim,
    ClaimKind,
    FreshnessState,
    Source,
)
from gateway.places.contracts import Place, PlaceClaim


@pytest.fixture
def source_a() -> Source:
    return Source(
        source_id="s-a",
        run_id="r1",
        provider="adapter-a",
        adapter_id="adapter-a",
        retrieved_at="2026-10-12T10:00:00Z",
        source_url="https://example.test/a",
        terms_ref=None,
    )


@pytest.fixture
def claim_a(source_a: Source) -> Claim:
    return Claim(
        claim_id="c-a",
        run_id="r1",
        adapter_id="adapter-a",
        kind=ClaimKind.CASH_QUOTE,
        identity={
            "kind": "flight_quote",
            "segments": [
                {
                    "origin": "DEL",
                    "destination": "SIN",
                    "departure_at": "2026-10-12T10:00:00Z",
                    "arrival_at": "2026-10-12T16:00:00Z",
                    "operating_carrier": "AI",
                    "flight_number": "AI2384",
                }
            ],
            "cabin": "economy",
            "fare_conditions": "SAVER",
        },
        payload={
            "carrier": "AI",
            "flight_number": "AI2384",
            "depart_date": "2026-10-12",
            "cabin": "economy",
            "fare_conditions": "SAVER",
            "total_minor": 2450000,
            "currency": "INR",
        },
        source_id="s-a",
        is_inference=False,
        status=FreshnessState.LIVE,
        confidence=0.95,
        needs_verification=True,
        expires_at="2026-10-12T10:20:00Z",
    )


def _c(place_id: str, field: str, value: Any, source_id: str = "src") -> PlaceClaim:
    return PlaceClaim(
        place_id=place_id,
        field=field,  # type: ignore
        value=value,
        source_id=source_id,
        source_url="http://x",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_release="1",
        last_verified=datetime(2026, 1, 1, tzinfo=UTC),
        verified_by="test",
        confidence=0.9,
        needs_verification=False,
        licence_id="L",
        attribution_requirements="A",
    )


@pytest.fixture
def claims_sharing_wikidata() -> list[PlaceClaim]:
    return [
        _c("overture:1|wikidata:Q1", "name", "Place 1", "overture"),
        _c("osm:1|wikidata:Q1", "name", "Place 1", "osm"),
        _c("wikidata:Q1", "name", "Place 1", "wikidata"),
    ]


@pytest.fixture
def claims_same_name_far_apart() -> list[PlaceClaim]:
    return [
        _c("overture:a", "name", "Starbucks", "overture"),
        _c("overture:a", "category", "cafe", "overture"),
        _c("overture:a", "coordinates", {"lat": 1.280, "lon": 103.840}, "overture"),
        _c("osm:b", "name", "Starbucks", "osm"),
        _c("osm:b", "category", "cafe", "osm"),
        _c("osm:b", "coordinates", {"lat": 1.320, "lon": 103.840}, "osm"),  # 4km away
    ]


@pytest.fixture
def claims_near_duplicate() -> list[PlaceClaim]:
    return [
        _c("overture:a", "name", "Starbucks", "overture"),
        _c("overture:a", "category", "cafe", "overture"),
        _c("overture:a", "coordinates", {"lat": 1.280, "lon": 103.840}, "overture"),
        _c("osm:b", "name", "Starbucks ", "osm"),
        _c("osm:b", "category", "cafe", "osm"),
        _c("osm:b", "coordinates", {"lat": 1.280, "lon": 103.8401}, "osm"),  # ~11m away
    ]


@pytest.fixture
def claims_ambiguous() -> list[PlaceClaim]:
    return [
        _c("overture:a", "name", "Park", "overture"),
        _c("overture:a", "category", "park", "overture"),
        _c("overture:a", "coordinates", {"lat": 1.280, "lon": 103.840}, "overture"),
        _c("osm:b", "name", "Park", "osm"),
        _c("osm:b", "category", "park", "osm"),
        _c(
            "osm:b", "coordinates", {"lat": 1.285, "lon": 103.840}, "osm"
        ),  # ~550m away (threshold 400, ambiguous < 800)
    ]


def _cq(place_id: str, field: str, value: Any, lic: str = "L") -> PlaceClaim:
    return PlaceClaim(
        place_id=place_id,
        field=field,  # type: ignore
        value=value,
        source_id="src",
        source_url="http://x",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_release="1",
        last_verified=datetime(2026, 1, 1, tzinfo=UTC),
        verified_by="test",
        confidence=0.9,
        needs_verification=False,
        licence_id=lic,
        attribution_requirements="A",
    )


@pytest.fixture
def places() -> list[Place]:
    return [Place(place_id=f"pl_{i}", external_ids=[]) for i in range(1, 11)]


@pytest.fixture
def claims() -> list[PlaceClaim]:
    claims = []
    # 2 parks (1, 2)
    claims.extend(
        [
            _cq("pl_1", "category", "park"),
            _cq("pl_1", "coordinates", "1,1"),
            _cq("pl_1", "opening_hours", "x"),
            _cq("pl_2", "category", "park"),
            _cq("pl_2", "coordinates", "1,1"),
            _cq("pl_2", "opening_hours", "x"),
        ]
    )
    # 2 food_court (3, 4)
    claims.extend(
        [
            _cq("pl_3", "category", "food_court"),
            _cq("pl_3", "coordinates", "1,1"),
            _cq("pl_3", "opening_hours", "x"),
            _cq("pl_4", "category", "food_court"),
            _cq("pl_4", "coordinates", "1,1"),
            _cq("pl_4", "opening_hours", "x"),
        ]
    )
    # 2 restaurant (5, 6)
    claims.extend(
        [
            _cq("pl_5", "category", "restaurant"),
            _cq("pl_5", "coordinates", "1,1"),
            _cq("pl_5", "opening_hours", "x"),
            _cq("pl_6", "category", "restaurant"),
            _cq("pl_6", "coordinates", "1,1"),
            _cq("pl_6", "opening_hours", "x"),
        ]
    )
    # 1 cafe (7)
    claims.extend(
        [
            _cq("pl_7", "category", "cafe"),
            _cq("pl_7", "coordinates", "1,1"),
            _cq("pl_7", "opening_hours", "x"),
        ]
    )
    # 2 attraction (8, 9)
    claims.extend(
        [
            _cq("pl_8", "category", "attraction"),
            _cq("pl_8", "coordinates", "1,1"),
            _cq("pl_8", "opening_hours", "x"),
            _cq("pl_9", "category", "attraction"),
            _cq("pl_9", "coordinates", "1,1"),
            _cq("pl_9", "opening_hours", "x"),
        ]
    )
    # 1 museum (10)
    claims.extend(
        [
            _cq("pl_10", "category", "museum"),
            _cq("pl_10", "coordinates", "1,1"),
            _cq("pl_10", "opening_hours", "x"),
        ]
    )
    return claims


@pytest.fixture
def places_missing_food(places: list[Place]) -> list[Place]:
    return [p for p in places if p.place_id not in ("pl_3", "pl_4")]


@pytest.fixture
def claims_without_coords(claims: list[PlaceClaim]) -> list[PlaceClaim]:
    return [c for c in claims if c.field != "coordinates"]


@pytest.fixture
def claims_without_hours(claims: list[PlaceClaim]) -> list[PlaceClaim]:
    return [c for c in claims if c.field != "opening_hours"]


@pytest.fixture
def claims_one_missing_licence(claims: list[PlaceClaim]) -> list[PlaceClaim]:
    c2 = claims.copy()
    c2[0] = _cq("pl_1", "category", "park", lic="")
    return c2


@pytest.fixture
def active_catalog(tmp_path: Path) -> Path:

    from gateway.catalog.activate import activate
    from gateway.catalog.build import build_catalog

    manifest_yaml = """
catalog_id: overture_sg
catalog_release: "2026-08-01"
sources:
  - source_id: overture_sg
    source_url: "http://x"
    licence_id: "L"
    source_release: "1"
    checksum: "3b18c8bfa27eeb355f2f3bf7568833352c719338fa8faa213f1428cfa0fa2975"
    max_bytes: 5000
    geographic_scope: "SG"
    allowed_purpose: "non-commercial"
    attribution_text: "Overture"
"""
    m = tmp_path / "manifest.yaml"
    m.write_text(manifest_yaml)

    import json
    import zipfile
    
    zip_path = tmp_path / "dummy.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        from gateway.catalog.quality import _MIN_PER_CATEGORY
        places = []
        idx = 1
        for cat, min_count in _MIN_PER_CATEGORY.items():
            for _ in range(min_count):
                places.append({
                    "id": f"ext_{idx}",
                    "names": {"primary": f"Place {idx}"},
                    "categories": {"primary": "zoo" if cat == "attraction" else cat},
                    "geometry": {"lat": 1.3, "lon": 103.8}
                })
                idx += 1
        z.writestr("data.json", json.dumps(places))
        
    payload = zip_path.read_bytes()

    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "overture_sg_1.zip").write_bytes(payload)
    
    import hashlib
    true_checksum = hashlib.sha256(payload).hexdigest()
    old_chk = "3b18c8bfa27eeb355f2f3bf7568833352c719338fa8faa213f1428cfa0fa2975"
    m.write_text(manifest_yaml.replace(old_chk, true_checksum))

    artifact = build_catalog(m, raw, tmp_path / "work")
    return activate(artifact, tmp_path / "catalogs")

@pytest.fixture(autouse=True)
def mock_active_catalog_path(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """Prevent tests from loading the real 161MB catalog by default."""
    if "allow_real_catalog" in request.keywords:
        return
    def _mock(*args, **kwargs):
        raise FileNotFoundError("Mocked: catalog not found")
    monkeypatch.setattr("gateway.catalog.activate.active_catalog_path", _mock)
