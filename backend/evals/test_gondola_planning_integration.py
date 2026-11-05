"""Offline acceptance for the explicit Gondola planning adapter seam."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import pytest

from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.fixture_transport import FixtureGondolaTransport
from gateway.travel.adapters.gondola.live_adapter import build_live_gondola_adapter
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


def _requests() -> tuple[FlightSearchRequest, HotelSearchRequest]:
    travelers = TravelerMix(adults=1)
    return (
        FlightSearchRequest.model_construct(
            origin="DEL",
            destination="SIN",
            depart_date=date(2026, 11, 10),
            travelers=travelers,
            cabin="economy",
            currency="",
        ),
        HotelSearchRequest.model_construct(
            city="Singapore",
            check_in=date(2026, 11, 10),
            check_out=date(2026, 11, 13),
            travelers=travelers,
            rooms=1,
            # The provider-compatible seam is exercised separately from the
            # product request, whose style/currency dimensions are rejected
            # rather than silently dropped by the request builders.
            style=None,
            currency="",
        ),
    )


class _FixtureAsyncTransport:
    def __init__(self) -> None:
        self.inner = FixtureGondolaTransport(now=lambda: NOW)

    async def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        del arguments
        fixture = (
            "search_hotels_success" if tool_name == "search_hotels" else "search_flights_success"
        )
        return self.inner.call_tool(tool_name, fixture)


def _adapter(*, enabled: bool = True) -> object:
    return build_live_gondola_adapter(
        transport=_FixtureAsyncTransport(),
        budget=GondolaCallBudget(),
        plan_id="offline-gondola-planning",
        now=lambda: NOW,
        live_enabled=enabled,
    )


def test_explicit_fixture_adapter_produces_normalized_quotes_without_network() -> None:
    flight, hotel = _requests()
    adapter = _adapter()
    flights = asyncio.run(adapter.search_flights(flight))  # type: ignore[attr-defined]
    hotels = asyncio.run(adapter.search_hotels(hotel))  # type: ignore[attr-defined]
    assert flights[0].evidence.provider_id == "gondola"
    assert flights[0].evidence.needs_verification is True
    assert hotels[0].total_minor == 18500
    assert hotels[0].evidence.status == "verify_required"


def test_live_adapter_rejects_observed_markdown_before_quote_normalization() -> None:
    class MarkdownTransport:
        async def call_tool(
            self, tool_name: str, arguments: dict[str, object]
        ) -> dict[str, object]:
            del tool_name, arguments
            return {"result": "## Hotel Search Results"}

    _, hotel = _requests()
    adapter = build_live_gondola_adapter(
        transport=MarkdownTransport(),
        budget=GondolaCallBudget(),
        plan_id="markdown-rejection",
        now=lambda: NOW,
        live_enabled=True,
    )
    with pytest.raises(TravelGatewayError, match="Markdown discovery evidence"):
        asyncio.run(adapter.search_hotels(hotel))

# End of offline acceptance coverage.
#
__all__: tuple[str, ...] = ()
def test_live_adapter_turns_malformed_native_rows_into_typed_failure() -> None:
    class MalformedTransport:
        async def call_tool(
            self, tool_name: str, arguments: dict[str, object]
        ) -> dict[str, object]:
            del tool_name, arguments
            return {"results": [{"hotel_id": "missing-required-fields"}]}

    _, hotel = _requests()
    adapter = build_live_gondola_adapter(
        transport=MalformedTransport(),
        budget=GondolaCallBudget(),
        plan_id="malformed-gondola",
        now=lambda: NOW,
        live_enabled=True,
    )
    with pytest.raises(TravelGatewayError, match="native contract"):
        asyncio.run(adapter.search_hotels(hotel))


def test_default_disabled_boundary_does_not_dispatch_transport() -> None:
    class NeverCalledTransport(_FixtureAsyncTransport):
        async def call_tool(
            self, tool_name: str, arguments: dict[str, object]
        ) -> dict[str, object]:
            raise AssertionError("disabled Gondola must not dispatch")

    _, hotel = _requests()
    adapter = build_live_gondola_adapter(
        transport=NeverCalledTransport(),
        budget=GondolaCallBudget(),
        plan_id="disabled-gondola",
        now=lambda: NOW,
        live_enabled=False,
    )
    with pytest.raises(TravelGatewayError, match="disabled"):
        asyncio.run(adapter.search_hotels(hotel))

# End of offline acceptance coverage.
