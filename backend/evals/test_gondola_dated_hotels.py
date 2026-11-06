"""Regressions for the observed hotel format and the real planning boundary.

Identifiers, names and prices below are synthetic; only the wire grammar was
observed live. No network or credential access is used here.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from agents.gateway_estimator import estimate_confirmed_inventory
from api.confirmed_planning import build_travel_service
from evals.test_travel_gateway_parity import _itinerary, _kb, _spec
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.dated_hotel_adapter import GondolaDatedHotelAdapter
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError

NOW = datetime(2026, 11, 5, tzinfo=UTC)
START, END = date(2027, 2, 10), date(2027, 2, 13)
SYNTHETIC_RATES = (
    "## Hotel Rates (ID: 123456)\n"
    "**Stay:** 2027-02-10 to 2027-02-13 | 1 adults\n"
    "### Available Rooms\n#### Synthetic Deluxe room\n"
    "- **Cheapest non-refundable:** `rate_id=SECRET_SYNTHETIC_RATE` "
    "**SGD 90/night** (total: SGD 300.25) Non-refundable | "
    "Offer: Synthetic rate; cancellation fee is estimated.\n"
)


class Transport:
    def __init__(self, rates: str = SYNTHETIC_RATES, search: str | None = None) -> None:
        self.rates = rates
        self.search = search or "### Synthetic hotel (ID: 123456)\n"
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name == "search_hotels":
            return {"result": self.search}
        if name == "get_hotel_rates":
            return {"result": self.rates}
        raise AssertionError("Unexpected tool")


def request() -> HotelSearchRequest:
    return HotelSearchRequest(
        city="Singapore", check_in=START, check_out=END,
        travelers=TravelerMix(adults=1), rooms=1, style="balanced", currency="INR",
    )


def adapter(
    transport: Transport, budget: GondolaCallBudget | None = None
) -> GondolaDatedHotelAdapter:
    return GondolaDatedHotelAdapter(
        transport=transport, budget=budget or GondolaCallBudget(),
        plan_id="synthetic-rate-plan", now=lambda: NOW, live_enabled=True,
    )


def test_real_format_preserves_stay_total_and_never_exports_rate_token() -> None:
    transport = Transport()
    quotes = asyncio.run(adapter(transport).search_hotels(request()))
    assert [name for name, _ in transport.calls] == ["search_hotels", "get_hotel_rates"]
    assert transport.calls[1][1]["hotel_id"] == 123456
    assert isinstance(transport.calls[1][1]["hotel_id"], int)
    quote = quotes[0]
    assert quote.total_minor == 30025  # stated total, not nightly amount * nights
    assert quote.currency == "SGD" and quote.taxes_minor is None and quote.fees_minor is None
    assert quote.refundable is False and quote.evidence.completeness == "taxes_uncertain"
    assert "SECRET_SYNTHETIC_RATE" not in quote.model_dump_json()
    assert "origin=synthetic_fixture" in quote.evidence.notes


@pytest.mark.parametrize("bad", [
    SYNTHETIC_RATES.replace("ID: 123456", "ID: 654321"),
    SYNTHETIC_RATES.replace("| 1 adults", "| 2 adults"),
    SYNTHETIC_RATES.replace("2027-02-13", "2027-02-14"),
    SYNTHETIC_RATES.replace("total: SGD", "total: USD"),
    SYNTHETIC_RATES.replace("300.25", "3,00.25"),
])
def test_wrong_identity_scope_or_ambiguous_amount_is_refused(bad: str) -> None:
    with pytest.raises(TravelGatewayError):
        asyncio.run(adapter(Transport(bad)).search_hotels(request()))


def test_missing_identity_never_dispatches_rates_and_budget_prevents_redispatch() -> None:
    transport = Transport(search="No results. A price of 123456 is not a hotel ID.")
    with pytest.raises(TravelGatewayError):
        asyncio.run(adapter(transport).search_hotels(request()))
    assert [name for name, _ in transport.calls] == ["search_hotels"]
    transport = Transport()
    instance = adapter(transport)
    asyncio.run(instance.search_hotels(request()))
    with pytest.raises(TravelGatewayError):
        asyncio.run(instance.search_hotels(request()))
    assert len(transport.calls) == 2


def test_source_currency_alternative_reaches_plan_without_replacing_budget(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    service = build_travel_service(
        kb, plan_id="synthetic-rate-plan", now=lambda: NOW,
        gondola_hotel_adapter=adapter(Transport()),
    )
    hotel = request()
    flight = FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=START, return_date=END,
        travelers=hotel.travelers, cabin="economy", currency="INR",
    )
    snapshot = asyncio.run(service.search(flight, hotel))
    spec = _spec().model_copy(update={"start_date": START, "end_date": END, "travelers": 1})
    result = estimate_confirmed_inventory(
        spec, _itinerary(), kb, snapshot, booking_date=NOW.date()
    )
    assert result.summary.hotel is not None
    assert result.summary.hotel.provider_id == "sample_travel_adapter"
    alternative = next(q for q in result.summary.alternatives if q.provider_id == "gondola")
    assert alternative.source_currency == "SGD" and alternative.source_amount_minor == 30025
    assert alternative.property_name == "Synthetic hotel"
    assert alternative.room_name == "Synthetic Deluxe room"
    assert not alternative.price_scope.cost_eligible and not alternative.selected
    assert not any("Sample hotel packaging" in text for text in alternative.limitations)
    assert "SECRET_SYNTHETIC_RATE" not in result.summary.model_dump_json()


def test_kill_switch_overrides_even_explicit_replay_injection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TRIPWISE_GONDOLA_KILL_SWITCH", "1")
    kb = _kb(tmp_path)
    transport = Transport()
    service = build_travel_service(
        kb, plan_id="blocked", now=lambda: NOW, gondola_hotel_adapter=adapter(transport)
    )
    assert "gondola" not in service.adapters
    assert not transport.calls
