"""Explicit, fail-closed Gondola adapter construction.

This module is the only bridge from the MCP transport to the normalized
travel gateway.  It is intentionally not imported by the default confirmed
planning factory: live Gondola remains opt-in and sample inventory remains
the product fallback.  The provider's currently observed Markdown response
is discovery evidence, not a quote; only a typed ``results`` list can cross
this boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from pydantic import ValidationError

from gateway.travel.adapters.gondola.adapter import (
    FlightFetcher,
    GondolaAdapter,
    HotelFetcher,
)
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.contracts import (
    GondolaFlightResult,
    GondolaHotelResult,
    parse_flight_results,
    parse_hotel_results,
)
from gateway.travel.adapters.gondola.requests import (
    build_flight_request_arguments,
    build_hotel_request_arguments,
)
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError


class GondolaToolTransport(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


def _typed_results(payload: dict[str, Any], *, kind: str) -> object:
    """Extract only the reviewed native result envelope.

    In particular, a provider ``{"result": "...Markdown..."}`` payload is
    never coerced into inventory.  We also reject alternate guessed keys so a
    future provider response cannot silently change the contract.
    """

    if "result" in payload:
        raise TravelGatewayError(
            "invalid_response",
            f"Gondola returned provider Markdown discovery evidence, not {kind} quotes",
        )
    results = payload.get("results")
    if not isinstance(results, list):
        raise TravelGatewayError(
            "invalid_response", f"Gondola {kind} response has no typed results list"
        )
    return results


def make_live_fetchers(
    transport: GondolaToolTransport,
) -> tuple[HotelFetcher, FlightFetcher]:
    """Create strict request/response fetchers over an injected transport.

    The transport owns authentication, host restrictions, payload bounds and
    the Gondola tool allowlist.  These fetchers own only the application
    request-shape and native-response contracts.
    """

    async def fetch_hotels(request: HotelSearchRequest) -> list[GondolaHotelResult]:
        payload = await transport.call_tool(
            "search_hotels", build_hotel_request_arguments(request)
        )
        raw = _typed_results(payload, kind="hotel")
        try:
            return parse_hotel_results(raw)
        except ValidationError as exc:
            raise TravelGatewayError(
                "invalid_response", "Gondola hotel result failed its native contract"
            ) from exc

    async def fetch_flights(request: FlightSearchRequest) -> list[GondolaFlightResult]:
        payload = await transport.call_tool(
            "search_flights", build_flight_request_arguments(request)
        )
        raw = _typed_results(payload, kind="flight")
        try:
            return parse_flight_results(raw)
        except ValidationError as exc:
            raise TravelGatewayError(
                "invalid_response", "Gondola flight result failed its native contract"
            ) from exc

    return fetch_hotels, fetch_flights


def build_live_gondola_adapter(
    *,
    transport: GondolaToolTransport,
    budget: GondolaCallBudget,
    plan_id: str,
    now: Callable[[], datetime],
    live_enabled: bool,
) -> GondolaAdapter:
    """Build an explicitly enabled adapter; no environment is read here."""

    hotels, flights = make_live_fetchers(transport)
    return GondolaAdapter(
        fetch_hotels=hotels,
        fetch_flights=flights,
        budget=budget,
        plan_id=plan_id,
        now=now,
        live_enabled=live_enabled,
    )
