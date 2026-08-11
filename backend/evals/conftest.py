import pytest
from typing import Any

from gateway.evidence.nodes import (
    Claim,
    ClaimKind,
    FreshnessState,
    Source,
)


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

from datetime import UTC, datetime
from gateway.places.contracts import PlaceClaim


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
        _c("osm:b", "coordinates", {"lat": 1.285, "lon": 103.840}, "osm"),  # ~550m away (threshold 400, ambiguous < 800)
    ]
