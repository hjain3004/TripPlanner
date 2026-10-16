from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from agents.gateway_estimator import estimate_confirmed_inventory
from core.models import UserWallet
from core.trip_models import TripSpec
from evals.test_travel_gateway_parity import _itinerary, _kb
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from gateway.travel.product import QuotePriceScope
from gateway.travel.registry import get_default_travel_registry
from gateway.travel.service import TravelInventoryService

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def _service(tmp_path):  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    return kb, TravelInventoryService(
        registry=get_default_travel_registry(),
        adapters={"sample_travel_adapter": SampleAdapter(kb, now=lambda: NOW)},
        plan_id="confirmed:1",
        country="IN",
        now=lambda: NOW,
    )


def _requests(*, rooms: int = 1, nonstop: bool = False):  # type: ignore[no-untyped-def]
    travelers = TravelerMix(adults=2)
    return (
        FlightSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_date=date(2026, 8, 1),
            return_date=date(2026, 8, 5),
            travelers=travelers,
            cabin="economy",
            nonstop_only=nonstop,
            currency="INR",
        ),
        HotelSearchRequest(
            city="Singapore",
            check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5),
            travelers=travelers,
            rooms=rooms,
            area_ids=["marina_bay"],
            style="balanced",
            currency="INR",
        ),
    )


def test_unknown_price_scope_is_not_cost_eligible() -> None:
    assert not QuotePriceScope(basis="unknown", scope_verified=False).cost_eligible


def test_nonstop_filter_inspects_seed_stops(tmp_path) -> None:  # type: ignore[no-untyped-def]
    _, service = _service(tmp_path)
    flight, hotel = _requests(nonstop=True)
    snapshot = asyncio.run(service.search(flight, hotel))
    assert [quote.evidence.provider_quote_id for quote in snapshot.flights] == ["del-sin-si-eco"]


def test_multi_room_sample_is_alternative_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb, service = _service(tmp_path)
    flight, hotel = _requests(rooms=2)
    snapshot = asyncio.run(service.search(flight, hotel))
    result = estimate_confirmed_inventory(
        TripSpec(
            home_country="IN",
            origin_city="DEL",
            destination_city="SIN",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            travelers=2,
            style="balanced",
            wallet=UserWallet(card_ids=[]),
        ),
        _itinerary(),
        kb,
        snapshot,
        booking_date=date(2026, 7, 1),
    )
    assert not any(line.category.value == "hotels" for line in result.estimate.costed_trip.lines)
    assert any(d.code == "missing_price_scope" for d in result.summary.diagnostics)
