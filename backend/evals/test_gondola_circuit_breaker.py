from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from gateway.travel.adapters.gondola.adapter import GondolaAdapter
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.contracts import GondolaHotelResult
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError

SUCCESS_HOTEL = GondolaHotelResult(
    hotel_id="gnd-hotel-0001", name="Test Hotel", cash_rate_minor=10000, cash_currency="SGD"
)


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


def _flight_request() -> FlightSearchRequest:
    return FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 11, 10),
        travelers=TravelerMix(adults=1),
        cabin="economy",
        currency="INR",
    )


def _now() -> datetime:
    return datetime(2026, 8, 21, tzinfo=UTC)


async def _always_succeeds(request: HotelSearchRequest) -> list[GondolaHotelResult]:
    return [SUCCESS_HOTEL]


async def _always_fails(request: HotelSearchRequest) -> list[GondolaHotelResult]:
    raise TravelGatewayError("provider_unavailable", "simulated transport failure")


def _adapter(
    *, fetch_hotels=_always_succeeds, live_enabled: bool = True, plan_id: str = "plan-1"
) -> GondolaAdapter:
    return GondolaAdapter(
        fetch_hotels=fetch_hotels,
        fetch_flights=None,
        budget=GondolaCallBudget(),
        plan_id=plan_id,
        now=_now,
        live_enabled=live_enabled,
    )


def test_search_hotels_returns_normalized_quotes_on_success() -> None:
    adapter = _adapter()
    quotes = asyncio.run(adapter.search_hotels(_hotel_request()))
    assert len(quotes) == 1
    assert quotes[0].evidence.status == "verify_required"


def test_kill_switch_disabled_by_default_raises_provider_unavailable() -> None:
    adapter = _adapter(live_enabled=False)
    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(adapter.search_hotels(_hotel_request()))
    assert exc_info.value.code == "provider_unavailable"


class _UnlimitedBudget:
    """Test-only stand-in that never exhausts, isolating the circuit breaker
    from the (much lower) per-plan call ceiling for this specific test."""

    def reserve_call(self, plan_id: str) -> bool:
        return True


def test_circuit_breaker_opens_after_three_consecutive_failures() -> None:
    adapter = GondolaAdapter(
        fetch_hotels=_always_fails,
        fetch_flights=None,
        budget=_UnlimitedBudget(),
        plan_id="plan-cb",
        now=_now,
        live_enabled=True,
    )
    for _ in range(3):
        with pytest.raises(TravelGatewayError):
            asyncio.run(adapter.search_hotels(_hotel_request()))

    call_count_before = adapter.consecutive_failures
    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(adapter.search_hotels(_hotel_request()))
    assert exc_info.value.code == "provider_unavailable"
    # The breaker fast-fails without incrementing further (no additional attempt made)
    assert adapter.consecutive_failures == call_count_before


def test_budget_exhausted_raises_budget_exhausted_code() -> None:
    budget = GondolaCallBudget()
    adapter = GondolaAdapter(
        fetch_hotels=_always_succeeds,
        fetch_flights=None,
        budget=budget,
        plan_id="plan-budget",
        now=_now,
        live_enabled=True,
    )
    asyncio.run(adapter.search_hotels(_hotel_request()))
    asyncio.run(adapter.search_hotels(_hotel_request()))
    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(adapter.search_hotels(_hotel_request()))
    assert exc_info.value.code == "budget_exhausted"


def test_search_flights_raises_unsupported_domain_when_fetcher_not_provided() -> None:
    adapter = _adapter()
    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(adapter.search_flights(_flight_request()))
    assert exc_info.value.code == "unsupported_domain"
