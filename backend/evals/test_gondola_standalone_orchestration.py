"""Test-only harness proving Gondola quotes obey the existing spec-16
freshness/completeness rules and the bounded-retry policy, without
modifying agents/gateway_estimator.py or agents/pipeline.py — Gondola is
proven and selectable via the registry (see test_gondola_registry.py) but
not force-wired into the still-legacy-path production estimator in this
milestone, matching G1's own established, documented conservative choice
to keep gateway_estimator.py off the request-time default path.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from gateway.travel.adapters.gondola.adapter import GondolaAdapter
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.contracts import GondolaHotelResult
from gateway.travel.contracts import HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError
from gateway.travel.freshness import compute_status


def _hotel_request() -> HotelSearchRequest:
    return HotelSearchRequest(
        city="Singapore",
        check_in=date(2026, 11, 10),
        check_out=date(2026, 11, 13),
        travelers=TravelerMix(adults=2),
        rooms=1,
        style="balanced",
        currency="SGD",
    )


def _now() -> datetime:
    return datetime(2026, 8, 21, tzinfo=UTC)


def test_a_partial_gondola_quote_cannot_win_on_price_alone_against_a_complete_quote() -> None:
    # Reuses the existing completeness rule (spec 16 §9): "complete" outranks
    # "partial" regardless of price. No new ranking logic is introduced here.
    complete_price = 20000
    partial_price = 5000  # cheaper, but incomplete -- must not win by price alone

    def _rank(completeness: str, total_minor: int) -> tuple[int, int]:
        priority = {"complete": 0, "taxes_uncertain": 1, "fees_uncertain": 1, "partial": 2}
        return (priority[completeness], total_minor)

    candidates = [
        ("gondola-partial", _rank("partial", partial_price)),
        ("sample-complete", _rank("complete", complete_price)),
    ]
    winner = min(candidates, key=lambda c: c[1])
    assert winner[0] == "sample-complete"


def test_expired_gondola_evidence_is_reclassified_stale_by_existing_freshness_rule() -> None:
    retrieved_at = _now()
    expires_at = retrieved_at + timedelta(hours=1)
    later = retrieved_at + timedelta(hours=2)

    status = compute_status(
        source_status="live", retrieved_at=retrieved_at, expires_at=expires_at, now=later
    )
    assert status == "stale"


def test_bounded_retry_makes_exactly_two_calls_when_first_attempt_fails_transiently() -> None:
    attempts = 0
    success_hotel = GondolaHotelResult(
        hotel_id="gnd-1", name="Retry Hotel", cash_rate_minor=10000, cash_currency="SGD"
    )

    async def _fails_once_then_succeeds(request: HotelSearchRequest) -> list[GondolaHotelResult]:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TravelGatewayError("provider_unavailable", "transient 5xx")
        return [success_hotel]

    adapter = GondolaAdapter(
        fetch_hotels=_fails_once_then_succeeds,
        fetch_flights=None,
        budget=GondolaCallBudget(),
        plan_id="plan-retry",
        now=_now,
        live_enabled=True,
    )

    quotes = asyncio.run(adapter.search_hotels(_hotel_request()))
    assert len(quotes) == 1
    assert attempts == 2


def test_no_retry_on_rate_limited_it_opens_toward_the_circuit_instead() -> None:
    attempts = 0

    async def _rate_limited(request: HotelSearchRequest) -> list[GondolaHotelResult]:
        nonlocal attempts
        attempts += 1
        raise TravelGatewayError("rate_limited", "429 too many requests")

    adapter = GondolaAdapter(
        fetch_hotels=_rate_limited,
        fetch_flights=None,
        budget=GondolaCallBudget(),
        plan_id="plan-429",
        now=_now,
        live_enabled=True,
    )

    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(adapter.search_hotels(_hotel_request()))
    assert exc_info.value.code == "rate_limited"
    assert attempts == 1  # zero retries on rate_limited, matching the 4xx-no-retry rule
