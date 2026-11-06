"""Observed wire grammar with invented public values; no live service or credentials."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from agents.gateway_estimator import estimate_confirmed_inventory
from api.confirmed_planning import build_travel_service
from evals.test_travel_gateway_parity import _itinerary, _kb, _spec
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.flight_discovery import (
    GondolaFlightDiscoveryAdapter,
    parse_flight_discovery,
)
from gateway.travel.contracts import (
    FlexibleFlightSearchRequest,
    FlightSearchRequest,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.registry import gondola_search_mode

NOW = datetime(2026, 11, 6, tzinfo=UTC)
START, END = date(2027, 2, 10), date(2027, 2, 13)
SYNTHETIC = (
    "## Round-trip options — cash prices (1 found)\n"
    "_Source: Google Flights. These results cannot be booked through Gondola._\n"
    "_Each price is the total for both directions, shown against its outbound itinerary. "
    "Google pairs the return leg after an outbound is chosen._\n\n"
    "### 1. Synthetic Airlines — USD 420.25 round trip\n"
    "**Outbound** **DEL -> SIN** (5h 45m) Nonstop · Economy\n"
    "Wed Feb 10 09:45 -> Wed Feb 10 18:00\n"
    "_Returns Sat Feb 13 — price covers both directions. "
    "Pick the return flight on Google Flights._\n"
)


def request() -> FlexibleFlightSearchRequest:
    return FlexibleFlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_window_start=START,
        depart_window_end=START,
        return_window_start=END,
        return_window_end=END,
        travelers=TravelerMix(adults=1),
        cabin="economy",
        currency="INR",
        max_date_pairs=1,
    )


def parse(text: str = SYNTHETIC) -> list:
    return parse_flight_discovery(
        {"result": text}, request(), retrieved_at=NOW, origin="synthetic_fixture"
    )


class Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def call_tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, arguments))
        return {"result": SYNTHETIC}


def adapter(transport: Transport, *, enabled: bool = True) -> GondolaFlightDiscoveryAdapter:
    return GondolaFlightDiscoveryAdapter(
        transport=transport,
        budget=GondolaCallBudget(),
        plan_id="synthetic-flight",
        now=lambda: NOW,
        live_enabled=enabled,
    )


def test_round_trip_fare_is_observation_not_invented_flight_quote() -> None:
    row = parse()[0]
    assert row.observed_total_minor == 42025 and row.currency == "USD"
    assert row.price_scope == "round_trip_total" and not row.return_itinerary_confirmed
    assert row.carrier_name == "Synthetic Airlines" and row.stops == 0
    assert row.outbound_departure_local == "Wed Feb 10 09:45"
    assert not row.is_bookable and row.itinerary_detail == "partial"
    assert row.evidence.status == "verify_required" and row.evidence.needs_verification
    assert "origin=synthetic_fixture" in row.evidence.notes
    assert "segments" not in row.model_dump()


@pytest.mark.parametrize(
    "old,new",
    [
        ("both directions, shown", "one direction, shown"),
        ("DEL -> SIN", "BOM -> SIN"),
        ("Wed Feb 10 09:45", "Thu Feb 11 09:45"),
        ("Sat Feb 13", "Sun Feb 14"),
        ("Economy", "Business"),
        ("420.25", "4,20.25"),
        ("USD", "JPY"),
        ("09:45", "99:45"),
    ],
)
def test_mismatched_or_ambiguous_provider_fields_are_refused(old: str, new: str) -> None:
    with pytest.raises(TravelGatewayError):
        parse(SYNTHETIC.replace(old, new))


def test_equal_fares_with_different_outbound_times_have_distinct_ids() -> None:
    second = SYNTHETIC[SYNTHETIC.index("### 1.") :].replace("### 1.", "### 2.")
    second = second.replace("09:45", "10:45").replace("18:00", "19:00")
    rows = parse(SYNTHETIC + "\n" + second)
    assert len(rows) == 2 and rows[0].id != rows[1].id


def test_nonstop_constraint_is_applied_to_explicit_stop_count() -> None:
    text = SYNTHETIC.replace("Nonstop", "1 stop")
    rows = parse(text)
    assert rows[0].stops == 1
    with pytest.raises(TravelGatewayError):
        parse_flight_discovery(
            {"result": text},
            request().model_copy(update={"nonstop_only": True}),
            retrieved_at=NOW,
            origin="synthetic_fixture",
        )


def test_dispatch_is_bounded_and_disabled_never_calls_transport() -> None:
    transport = Transport()
    active = adapter(transport)
    asyncio.run(active.search_flight_price_trends(request()))
    asyncio.run(active.search_flight_price_trends(request()))
    with pytest.raises(TravelGatewayError):
        asyncio.run(active.search_flight_price_trends(request()))
    assert len(transport.calls) == 2
    assert transport.calls[0][0] == "search_flights"
    assert "currency" not in transport.calls[0][1]
    business = request().model_copy(update={"cabin": "business"})
    fresh_transport = Transport()
    with pytest.raises(TravelGatewayError):
        asyncio.run(adapter(fresh_transport).search_flight_price_trends(business))
    assert not fresh_transport.calls
    with pytest.raises(TravelGatewayError):
        parse_flight_discovery(
            {"result": SYNTHETIC.replace("Economy", "Business")},
            business,
            retrieved_at=NOW,
            origin="synthetic_fixture",
        )
    with pytest.raises(TravelGatewayError):
        asyncio.run(adapter(transport, enabled=False).search_flight_price_trends(request()))
    unsupported = request().model_copy(update={"travelers": TravelerMix(adults=2)})
    with pytest.raises(TravelGatewayError):
        asyncio.run(active.search_flight_price_trends(unsupported))
    assert len(transport.calls) == 2


def test_observation_reaches_planning_without_replacing_payable_budget(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    transport = Transport()
    service = build_travel_service(
        kb, plan_id="synthetic-flight", now=lambda: NOW, gondola_adapter=adapter(transport)
    )
    flight = FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=START,
        return_date=END,
        travelers=TravelerMix(adults=1),
        cabin="economy",
        currency="INR",
    )
    hotel = HotelSearchRequest(
        city="Singapore",
        check_in=START,
        check_out=END,
        travelers=flight.travelers,
        rooms=1,
        style="balanced",
        currency="INR",
    )
    snapshot = asyncio.run(service.search(flight, hotel))
    spec = _spec().model_copy(update={"start_date": START, "end_date": END, "travelers": 1})
    result = estimate_confirmed_inventory(spec, _itinerary(), kb, snapshot, booking_date=NOW.date())
    baseline = estimate_confirmed_inventory(
        spec,
        _itinerary(),
        kb,
        snapshot.model_copy(update={"flight_observations": []}),
        booking_date=NOW.date(),
    )
    assert result.summary.flight_observations[0].observed_total_minor == 42025
    assert result.summary.flight is not None
    assert result.summary.flight.provider_id == "sample_travel_adapter"
    assert result.estimate == baseline.estimate
    assert len(transport.calls) == 1
    service.now = lambda: NOW + timedelta(hours=1)
    assert service.revalidate(snapshot).flight_observations[0].evidence.status == "stale"


def test_operator_mode_default_and_kill_switch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRIPWISE_GONDOLA_SEARCH_MODE", raising=False)
    assert gondola_search_mode() == "hotels"
    monkeypatch.setenv("TRIPWISE_GONDOLA_SEARCH_MODE", "flights")
    assert gondola_search_mode() == "flights"
    monkeypatch.setenv("TRIPWISE_GONDOLA_KILL_SWITCH", "1")
    transport = Transport()
    service = build_travel_service(
        _kb(tmp_path), plan_id="blocked", now=lambda: NOW, gondola_adapter=adapter(transport)
    )
    assert "gondola" not in service.adapters and not transport.calls
