"""Seats.aero TravelProviderAdapter implementation (cached award availability only)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

from gateway.travel.adapters.seats_aero.normalize import PROVIDER_ID, normalize_seats_aero_awards
from gateway.travel.adapters.seats_aero.tool_policy import (
    ALLOWED_HOSTS,
    ALLOWED_PATHS,
    ALLOWED_TOOLS,
)
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

ANONYMOUS_MAX_ADVANCE_DAYS = 60


class SeatsAeroTransport(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> RawMcpToolResponse: ...


def build_live_seats_aero_transport() -> KeylessMcpTransport:
    return KeylessMcpTransport(
        provider_id=PROVIDER_ID,
        base_url="https://seats.aero/mcp",
        allowed_hosts=ALLOWED_HOSTS,
        allowed_paths=ALLOWED_PATHS,
        allowed_tools=ALLOWED_TOOLS,
    )


class SeatsAeroAdapter:
    """Spec-16 read-only anonymous MCP adapter for Seats.aero cached awards."""

    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"award"},
        countries="configured",
        live_data=False,
        supports_cache=True,
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
        transport: SeatsAeroTransport,
        budget: McpCallBudget,
        plan_id: str,
        now: Callable[[], datetime],
        live_enabled: bool = False,
        circuit_breaker: McpCircuitBreaker | None = None,
        anonymous_mode: bool = True,
    ) -> None:
        self._transport = transport
        self._budget = budget
        self._plan_id = plan_id
        self._now = now
        self._live_enabled = live_enabled
        self._circuit_breaker = circuit_breaker or McpCircuitBreaker()
        self._anonymous_mode = anonymous_mode
        self.last_diagnostic: str | None = None

    def _build_get_flights_args(self, request: AwardSearchRequest) -> dict[str, Any]:
        args: dict[str, Any] = {
            "origins": [request.origin],
            "destinations": [request.destination],
            "start_date": request.depart_date.isoformat(),
            "end_date": request.depart_date.isoformat(),
            "cabin": request.cabin,
            "min_seats": max(1, request.travelers.adults + request.travelers.children),
            # Explicit max_stops prevents Seats.aero's 0 (direct-only) default from
            # dropping valid 1-stop or 2-stop DEL->SIN connecting awards.
            "max_stops": 2,
            "max_results": 25,
        }
        if request.program_ids:
            args["programs"] = list(request.program_ids)
        return args

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]:
        if request.return_date is not None:
            raise TravelGatewayError(
                "unsupported_domain",
                "seats_aero searches one-way awards only; compose return leg separately",
            )
        now = self._now()
        days_ahead = (request.depart_date - now.date()).days
        if self._anonymous_mode and (days_ahead < 0 or days_ahead > ANONYMOUS_MAX_ADVANCE_DAYS):
            if not self._live_enabled:
                raise TravelGatewayError(
                    "provider_unavailable", f"{PROVIDER_ID} adapter is disabled (kill switch off)"
                )
            self.last_diagnostic = (
                f"anonymous_horizon_exceeded: depart_date {request.depart_date.isoformat()} "
                f"({days_ahead}d ahead of {now.date().isoformat()}, "
                f"limit 0..{ANONYMOUS_MAX_ADVANCE_DAYS}d)"
            )
            return []

        args = self._build_get_flights_args(request)

        async def _action() -> list[AwardQuote]:
            raw = await self._transport.call_tool("get_flights", args)
            return normalize_seats_aero_awards(raw, request, now=now)

        quotes: list[AwardQuote] = await call_with_guard_and_retry(
            provider_id=PROVIDER_ID,
            live_enabled=self._live_enabled,
            circuit_breaker=self._circuit_breaker,
            budget=self._budget,
            plan_id=self._plan_id,
            action=_action,
        )
        self.last_diagnostic = "ok" if quotes else "no_matching_awards"
        return quotes

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support flight")

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        raise TravelGatewayError(
            "unsupported_domain", f"{PROVIDER_ID} does not support flight_trend"
        )

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support hotel")
