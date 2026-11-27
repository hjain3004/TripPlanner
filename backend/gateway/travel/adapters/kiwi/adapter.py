"""Kiwi.com TravelProviderAdapter implementation (cash flight search only)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from gateway.travel.adapters.kiwi.normalize import PROVIDER_ID, normalize_kiwi_flights
from gateway.travel.adapters.kiwi.tool_policy import ALLOWED_HOSTS, ALLOWED_PATHS, ALLOWED_TOOLS
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    Cabin,
    FlexibleFlightSearchRequest,
    FlightPriceObservation,
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.mcp_readonly import (
    KeylessMcpTransport,
    McpCallBudget,
    McpCircuitBreaker,
    RawMcpToolResponse,
    call_with_guard_and_retry,
)
from gateway.travel.protocol import AdapterCapabilities

_CABIN_TO_KIWI: dict[Cabin, str] = {
    "economy": "M",
    "premium": "W",
    "business": "C",
    "first": "F",
}


class KiwiTransport(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> RawMcpToolResponse: ...


def build_live_kiwi_transport() -> KeylessMcpTransport:
    return KeylessMcpTransport(
        provider_id=PROVIDER_ID,
        base_url="https://mcp.kiwi.com",
        allowed_hosts=ALLOWED_HOSTS,
        allowed_paths=ALLOWED_PATHS,
        allowed_tools=ALLOWED_TOOLS,
    )


class KiwiAdapter:
    """Spec-16 read-only anonymous MCP adapter for Kiwi.com cash flights."""

    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"flight"},
        countries="configured",
        live_data=True,
        supports_cache=False,
        supports_commercial_use=False,
        allowed_profiles={"student_noncommercial"},
        source_method="provider_mcp",
        stability="experimental",
        requires_user_initiated_search=False,
        max_concurrency=1,
    )

    def __init__(
        self,
        *,
        transport: KiwiTransport,
        budget: McpCallBudget,
        plan_id: str,
        now: Callable[[], datetime],
        live_enabled: bool = False,
        circuit_breaker: McpCircuitBreaker | None = None,
    ) -> None:
        self._transport = transport
        self._budget = budget
        self._plan_id = plan_id
        self._now = now
        self._live_enabled = live_enabled
        self._circuit_breaker = circuit_breaker or McpCircuitBreaker()

    def _build_search_args(self, request: FlightSearchRequest) -> dict[str, Any]:
        args: dict[str, Any] = {
            "flyFrom": request.origin,
            "flyTo": request.destination,
            "departureDate": request.depart_date.strftime("%d/%m/%Y"),
            "adults": request.travelers.adults,
            "children": request.travelers.children,
            "infants": request.travelers.infants,
            "cabinClass": _CABIN_TO_KIWI[request.cabin],
            "currency": request.currency,
            "sort": "price",
        }
        if request.return_date is not None:
            args["returnDate"] = request.return_date.strftime("%d/%m/%Y")
        if request.nonstop_only:
            args["max_sector_stopovers"] = 0
        return args

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]:
        now = self._now()
        args = self._build_search_args(request)

        async def _action() -> list[FlightQuote]:
            raw = await self._transport.call_tool("search-flight", args)
            return normalize_kiwi_flights(raw, request, now=now)

        quotes: list[FlightQuote] = await call_with_guard_and_retry(
            provider_id=PROVIDER_ID,
            live_enabled=self._live_enabled,
            circuit_breaker=self._circuit_breaker,
            budget=self._budget,
            plan_id=self._plan_id,
            action=_action,
        )
        return quotes

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        raise TravelGatewayError(
            "unsupported_domain", f"{PROVIDER_ID} does not support flight_trend"
        )

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support hotel")

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support award")
