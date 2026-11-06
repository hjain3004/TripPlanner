"""Bounded search -> dated rates using the real, observed Gondola contract."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from gateway.travel.adapters.gondola.adapter import GondolaAdapter
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.hotel_discovery import (
    HotelToolTransport,
    fetch_first_hotel_rates,
)
from gateway.travel.adapters.gondola.hotel_rates import parse_dated_hotel_rates
from gateway.travel.contracts import HotelQuote, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError


class GondolaDatedHotelAdapter(GondolaAdapter):
    capabilities = GondolaAdapter.capabilities.model_copy(
        update={"domains": {"hotel"}, "source_currency_alternatives": True}
    )

    def __init__(
        self,
        *,
        transport: HotelToolTransport,
        budget: GondolaCallBudget,
        plan_id: str,
        now: Callable[[], datetime],
        live_enabled: bool = False,
        origin: Literal["synthetic_fixture", "live_capture_replay"] | None = None,
    ) -> None:
        super().__init__(
            fetch_hotels=None,
            fetch_flights=None,
            budget=budget,
            plan_id=plan_id,
            now=now,
            live_enabled=live_enabled,
        )
        self._transport = transport
        from gateway.travel.adapters.gondola.mcp_client import LiveGondolaTransport

        self._origin = origin or (
            "live_observation"
            if isinstance(transport, LiveGondolaTransport)
            else "synthetic_fixture"
        )

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        if (
            request.rooms != 1
            or request.travelers.children
            or request.travelers.infants
            or request.property_kinds != {"hotel"}
        ):
            raise TravelGatewayError("unsupported_domain", "Unsupported Gondola stay dimensions")
        parent = self

        class ReservedTransport:
            async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
                parent._guard()
                return await parent._transport.call_tool(tool_name, arguments)

        try:
            observation = await fetch_first_hotel_rates(
                ReservedTransport(),
                location=request.city,
                check_in=request.check_in,
                check_out=request.check_out,
                adults=request.travelers.adults,
            )
            result = parse_dated_hotel_rates(
                observation, request, retrieved_at=self._now(), origin=self._origin
            )
        except Exception:
            self._circuit_breaker.record_failure()
            raise
        self._circuit_breaker.record_success()
        return result


def build_keychain_hotel_adapter(
    *, plan_id: str, now: Callable[[], datetime]
) -> GondolaDatedHotelAdapter:
    """Construct only after the runtime registry explicitly enables Gondola."""
    transport, budget = _keychain_resources(plan_id=plan_id, now=now)
    return GondolaDatedHotelAdapter(
        transport=transport, budget=budget, plan_id=plan_id, now=now, live_enabled=True
    )


def _keychain_resources(
    *, plan_id: str, now: Callable[[], datetime]
) -> tuple[HotelToolTransport, GondolaCallBudget]:
    from core.runtime_paths import state_path
    from gateway.travel.adapters.gondola.mcp_client import LiveGondolaTransport
    from gateway.travel.adapters.gondola.oauth import KeychainTokenStore

    def access_token() -> str:
        try:
            stored = KeychainTokenStore().load()
        except Exception:
            raise TravelGatewayError(
                "authentication_failed", "Gondola secure credentials unavailable"
            ) from None
        if stored is None or stored.scope != "mcp:read" or stored.expires_at <= now():
            raise TravelGatewayError(
                "authentication_failed", "Reconnect Gondola with read-only access"
            )
        return stored.access_token

    ledger = state_path(
        "gondola-budget.sqlite", Path(__file__).resolve().parents[4] / "gondola-budget.sqlite"
    )
    ledger.parent.mkdir(parents=True, exist_ok=True)
    return (
        LiveGondolaTransport(
            base_url="https://mcp.gondola.ai/mcp/auth", get_access_token=access_token
        ),
        GondolaCallBudget(ledger),
    )


def build_keychain_gondola_adapter(
    *, plan_id: str, now: Callable[[], datetime], mode: Literal["hotels", "flights"]
) -> GondolaAdapter:
    if mode == "hotels":
        return build_keychain_hotel_adapter(plan_id=plan_id, now=now)
    from gateway.travel.adapters.gondola.flight_discovery import GondolaFlightDiscoveryAdapter

    transport, budget = _keychain_resources(plan_id=plan_id, now=now)
    return GondolaFlightDiscoveryAdapter(
        transport=transport, budget=budget, plan_id=plan_id, now=now, live_enabled=True
    )
