import pytest

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
