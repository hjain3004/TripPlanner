"""Trivago TravelProviderAdapter implementation (accommodation metasearch only)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from gateway.travel.adapters.trivago.normalize import PROVIDER_ID, normalize_trivago_hotels
from gateway.travel.adapters.trivago.tool_policy import ALLOWED_HOSTS, ALLOWED_PATHS, ALLOWED_TOOLS
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
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


class TrivagoTransport(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> RawMcpToolResponse: ...


def build_live_trivago_transport() -> KeylessMcpTransport:
    return KeylessMcpTransport(
        provider_id=PROVIDER_ID,
        base_url="https://mcp.trivago.com/mcp",
        allowed_hosts=ALLOWED_HOSTS,
        allowed_paths=ALLOWED_PATHS,
        allowed_tools=ALLOWED_TOOLS,
    )


class TrivagoAdapter:
    """Spec-16 read-only anonymous MCP adapter for Trivago hotels."""

    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"hotel"},
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
        transport: TrivagoTransport,
        budget: McpCallBudget,
        plan_id: str,
        now: Callable[[], datetime],
        live_enabled: bool = False,
        circuit_breaker: McpCircuitBreaker | None = None,
        market_country: str = "IN",
        language: str = "EN_IN",
    ) -> None:
        self._transport = transport
        self._budget = budget
        self._plan_id = plan_id
        self._now = now
        self._live_enabled = live_enabled
        self._circuit_breaker = circuit_breaker or McpCircuitBreaker()
        self._market_country = market_country
        self._language = language

    def _build_search_args(self, request: HotelSearchRequest) -> dict[str, Any]:
        args: dict[str, Any] = {
            "query": request.city,
            "arrival": request.check_in.isoformat(),
            "departure": request.check_out.isoformat(),
            "adults": request.travelers.adults,
            "rooms": request.rooms,
            "country": self._market_country,
            "currency": request.currency,
            "language": self._language,
        }
        if request.travelers.children > 0:
            args["children"] = request.travelers.children
        return args

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        now = self._now()
        args = self._build_search_args(request)

        async def _action() -> list[HotelQuote]:
            raw = await self._transport.call_tool("trivago-accommodation-search", args)
            return normalize_trivago_hotels(raw, request, now=now)

        quotes: list[HotelQuote] = await call_with_guard_and_retry(
            provider_id=PROVIDER_ID,
            live_enabled=self._live_enabled,
            circuit_breaker=self._circuit_breaker,
            budget=self._budget,
            plan_id=self._plan_id,
            action=_action,
        )
        return quotes

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support flight")

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        raise TravelGatewayError(
            "unsupported_domain", f"{PROVIDER_ID} does not support flight_trend"
        )

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support award")
