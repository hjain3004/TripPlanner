"""Concurrent read-only fan-out orchestrator across verified keyless MCP travel providers."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from core.runtime_paths import state_path
from gateway.travel.adapters.kiwi.adapter import KiwiAdapter, build_live_kiwi_transport
from gateway.travel.adapters.seats_aero.adapter import (
    ANONYMOUS_MAX_ADVANCE_DAYS,
    SeatsAeroAdapter,
    build_live_seats_aero_transport,
)
from gateway.travel.adapters.trivago.adapter import TrivagoAdapter, build_live_trivago_transport
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.mcp_readonly import McpCallBudget, McpCircuitBreaker
from gateway.travel.product import GatewayDiagnostic
from gateway.travel.protocol import TravelProviderAdapter
from gateway.travel.registry import TravelProviderRegistry, get_default_travel_registry

_T = TypeVar("_T")
DomainKind = Literal["flight", "hotel", "award"]


class ProviderAttemptStatus(BaseModel):
    """Concise per-provider telemetry for diagnostics and estimator assumptions."""

    model_config = ConfigDict(frozen=True)

    domain: DomainKind
    provider_id: str
    status: Literal["ok", "disabled", "empty", "fallback"]
    quote_count: int = 0
    reason: str | None = None

    def as_assumption_string(self) -> str:
        if self.status == "ok":
            return f"gateway:{self.domain}:{self.provider_id}:ok ({self.quote_count} quotes)"
        if self.status == "disabled":
            return f"gateway:{self.domain}:{self.provider_id}:disabled"
        if self.status == "empty":
            return f"gateway:{self.domain}:{self.provider_id}:fallback:no_results"
        return f"gateway:{self.domain}:{self.provider_id}:fallback:{self.reason or 'error'}"


AdapterFactory = Callable[
    [str, Callable[[], datetime], bool, Path | str | None], TravelProviderAdapter
]


@dataclass(frozen=True)
class GatewayProviderFactories:
    """Optional dependency-injection factories for offline fixture replay and tests."""

    kiwi: AdapterFactory | None = None
    trivago: AdapterFactory | None = None
    openbnb: AdapterFactory | None = None
    seats_aero: AdapterFactory | None = None


class GatewayFetchBundle(BaseModel):
    """Combined normalized quotes plus per-provider statuses and diagnostics."""

    flights: list[FlightQuote] = Field(default_factory=list)
    hotels: list[HotelQuote] = Field(default_factory=list)
    awards: list[AwardQuote] = Field(default_factory=list)
    flight_provider: str | None = None
    hotel_provider: str | None = None
    award_provider: str | None = None
    statuses: list[ProviderAttemptStatus] = Field(default_factory=list)
    diagnostics: list[GatewayDiagnostic] = Field(default_factory=list)


def run_coro_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Bridge async gateway calls cleanly inside both sync scripts and active event loops."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="gateway-bridge") as pool:
        return pool.submit(asyncio.run, coro).result()


def _default_budget_db(db_path: Path | str | None) -> Path | str:
    if db_path is not None:
        return db_path
    return state_path("mcp_gateway_budget.sqlite", Path("mcp_gateway_budget.sqlite"))


def _build_default_kiwi(
    plan_id: str,
    now: Callable[[], datetime],
    enabled: bool,
    budget_db_path: Path | str | None,
) -> KiwiAdapter:
    return KiwiAdapter(
        transport=build_live_kiwi_transport(),
        budget=McpCallBudget(_default_budget_db(budget_db_path), provider_id="kiwi"),
        plan_id=plan_id,
        now=now,
        live_enabled=enabled,
        circuit_breaker=McpCircuitBreaker(),
    )


def _build_default_trivago(
    plan_id: str,
    now: Callable[[], datetime],
    enabled: bool,
    budget_db_path: Path | str | None,
    *,
    market_country: str = "IN",
) -> TrivagoAdapter:
    return TrivagoAdapter(
        transport=build_live_trivago_transport(),
        budget=McpCallBudget(_default_budget_db(budget_db_path), provider_id="trivago"),
        plan_id=plan_id,
        now=now,
        live_enabled=enabled,
        circuit_breaker=McpCircuitBreaker(),
        market_country=market_country,
    )


def _openbnb_env_enabled() -> bool:
    """Check OpenBnB opt-in env flag without importing the isolated package."""
    truthy = {"1", "true", "yes", "on"}
    if os.environ.get("TRIPWISE_OPENBNB_KILL_SWITCH", "").strip().lower() in truthy:
        return False
    return os.environ.get("TRIPWISE_OPENBNB_ENABLED", "").strip().lower() in truthy


def _build_default_seats_aero(
    plan_id: str,
    now: Callable[[], datetime],
    enabled: bool,
    budget_db_path: Path | str | None,
) -> SeatsAeroAdapter:
    return SeatsAeroAdapter(
        transport=build_live_seats_aero_transport(),
        budget=McpCallBudget(_default_budget_db(budget_db_path), provider_id="seats_aero"),
        plan_id=plan_id,
        now=now,
        live_enabled=enabled,
        circuit_breaker=McpCircuitBreaker(),
        anonymous_mode=True,
    )


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, TravelGatewayError):
        return exc.code
    return type(exc).__name__


async def fetch_gateway_inventory_async(
    *,
    flight_request: FlightSearchRequest,
    hotel_request: HotelSearchRequest,
    award_request: AwardSearchRequest | None,
    country: str,
    booking_date: date,
    plan_id: str,
    now: Callable[[], datetime],
    registry: TravelProviderRegistry | None = None,
    factories: GatewayProviderFactories | None = None,
    budget_db_path: Path | str | None = None,
) -> GatewayFetchBundle:
    """Query enabled read-only providers concurrently per domain, never raising on fallback."""
    resolved_registry = registry or get_default_travel_registry()
    resolved_factories = factories or GatewayProviderFactories()

    flight_entries = [
        e
        for e in resolved_registry.select_providers(
            active_profile="student_noncommercial", domain="flight", country=country
        )
        if e.provider_id == "kiwi"
    ]
    hotel_entries = [
        e
        for e in resolved_registry.select_providers(
            active_profile="student_noncommercial", domain="hotel", country=country
        )
        if e.provider_id in {"trivago", "openbnb"}
    ]
    openbnb_injected = resolved_factories.openbnb is not None and _openbnb_env_enabled()

    award_entries = [
        e
        for e in resolved_registry.select_providers(
            active_profile="student_noncommercial", domain="award", country=country
        )
        if e.provider_id == "seats_aero"
    ]

    statuses: list[ProviderAttemptStatus] = []
    diagnostics: list[GatewayDiagnostic] = []

    if not flight_entries:
        statuses.append(
            ProviderAttemptStatus(domain="flight", provider_id="kiwi", status="disabled")
        )
    if not any(e.provider_id == "trivago" for e in hotel_entries):
        statuses.append(
            ProviderAttemptStatus(domain="hotel", provider_id="trivago", status="disabled")
        )
    if not openbnb_injected and not any(
        e.provider_id == "openbnb" and resolved_factories.openbnb is not None for e in hotel_entries
    ):
        statuses.append(
            ProviderAttemptStatus(domain="hotel", provider_id="openbnb", status="disabled")
        )
    if not award_entries:
        statuses.append(
            ProviderAttemptStatus(domain="award", provider_id="seats_aero", status="disabled")
        )

    tasks: list[tuple[DomainKind, str, Coroutine[Any, Any, list[Any]]]] = []

    async def _run_flight() -> list[Any]:
        builder = resolved_factories.kiwi or _build_default_kiwi
        adapter = builder(plan_id, now, True, budget_db_path)
        return await adapter.search_flights(flight_request)

    async def _run_hotel(provider_id: str) -> list[Any]:
        if provider_id == "trivago":
            if resolved_factories.trivago is not None:
                h_adapter = resolved_factories.trivago(plan_id, now, True, budget_db_path)
            else:
                h_adapter = _build_default_trivago(
                    plan_id,
                    now,
                    True,
                    budget_db_path,
                    market_country=country if len(country) == 2 else "IN",
                )
            return await h_adapter.search_hotels(hotel_request)
        assert resolved_factories.openbnb is not None
        b_adapter = resolved_factories.openbnb(plan_id, now, True, budget_db_path)
        return await b_adapter.search_hotels(hotel_request)

    async def _run_award() -> list[Any]:
        assert award_request is not None
        s_builder = resolved_factories.seats_aero or _build_default_seats_aero
        s_adapter = s_builder(plan_id, now, True, budget_db_path)
        return await s_adapter.search_awards(award_request)

    for _entry in flight_entries:
        tasks.append(("flight", "kiwi", _run_flight()))

    for entry in hotel_entries:
        if entry.provider_id == "trivago":
            tasks.append(("hotel", "trivago", _run_hotel("trivago")))
        elif entry.provider_id == "openbnb" and resolved_factories.openbnb is not None:
            tasks.append(("hotel", "openbnb", _run_hotel("openbnb")))

    if openbnb_injected and not any(e.provider_id == "openbnb" for e in hotel_entries):
        tasks.append(("hotel", "openbnb", _run_hotel("openbnb")))

    if award_entries and award_request is not None:
        days_ahead = (award_request.depart_date - booking_date).days
        if days_ahead < 0 or days_ahead > ANONYMOUS_MAX_ADVANCE_DAYS:
            statuses.append(
                ProviderAttemptStatus(
                    domain="award",
                    provider_id="seats_aero",
                    status="fallback",
                    reason="outside_60d_anonymous_horizon",
                )
            )
            diagnostics.append(
                GatewayDiagnostic(
                    code="outside_60d_anonymous_horizon",
                    domain="general",
                    provider_id="seats_aero",
                    message=(
                        f"Seats.aero anonymous horizon is 0..{ANONYMOUS_MAX_ADVANCE_DAYS} days; "
                        f"falling back to local award chart ({days_ahead}d ahead)."
                    ),
                )
            )
        else:
            tasks.append(("award", "seats_aero", _run_award()))

    flights: list[FlightQuote] = []
    hotels: list[HotelQuote] = []
    awards: list[AwardQuote] = []
    flight_provider: str | None = None
    hotel_provider: str | None = None
    award_provider: str | None = None

    if tasks:
        results = await asyncio.gather(*(t[2] for t in tasks), return_exceptions=True)
        for (domain, pid, _coro), outcome in zip(tasks, results, strict=True):
            if isinstance(outcome, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise outcome
            if isinstance(outcome, BaseException):
                reason = _failure_reason(outcome)
                statuses.append(
                    ProviderAttemptStatus(
                        domain=domain,
                        provider_id=pid,
                        status="fallback",
                        reason=reason,
                    )
                )
                diag_domain: Literal["flight", "hotel", "general"] = (
                    "general" if domain == "award" else domain
                )
                diagnostics.append(
                    GatewayDiagnostic(
                        code=f"provider_fallback_{reason}",
                        domain=diag_domain,
                        provider_id=pid,
                        message=f"{pid} {domain} fallback ({reason}); using SampleAdapter.",
                    )
                )
                continue

            if not outcome:
                statuses.append(
                    ProviderAttemptStatus(domain=domain, provider_id=pid, status="empty")
                )
                diag_domain = "general" if domain == "award" else domain
                diagnostics.append(
                    GatewayDiagnostic(
                        code="provider_empty_fallback",
                        domain=diag_domain,
                        provider_id=pid,
                        message=f"{pid} returned 0 {domain} quotes; using fallback if needed.",
                    )
                )
                continue

            statuses.append(
                ProviderAttemptStatus(
                    domain=domain,
                    provider_id=pid,
                    status="ok",
                    quote_count=len(outcome),
                )
            )
            if domain == "flight":
                flights.extend(outcome)
                if flight_provider is None:
                    flight_provider = pid
            elif domain == "hotel":
                hotels.extend(outcome)
                if hotel_provider is None:
                    hotel_provider = pid
            else:
                awards.extend(outcome)
                if award_provider is None:
                    award_provider = pid

    return GatewayFetchBundle(
        flights=flights,
        hotels=hotels,
        awards=awards,
        flight_provider=flight_provider,
        hotel_provider=hotel_provider,
        award_provider=award_provider,
        statuses=statuses,
        diagnostics=diagnostics,
    )


def fetch_gateway_inventory_sync(
    *,
    flight_request: FlightSearchRequest,
    hotel_request: HotelSearchRequest,
    award_request: AwardSearchRequest | None,
    country: str,
    booking_date: date,
    plan_id: str,
    now: Callable[[], datetime],
    registry: TravelProviderRegistry | None = None,
    factories: GatewayProviderFactories | None = None,
    budget_db_path: Path | str | None = None,
) -> GatewayFetchBundle:
    """Synchronous entry point bridging cleanly across both sync and running-loop contexts."""
    return run_coro_sync(
        fetch_gateway_inventory_async(
            flight_request=flight_request,
            hotel_request=hotel_request,
            award_request=award_request,
            country=country,
            booking_date=booking_date,
            plan_id=plan_id,
            now=now,
            registry=registry,
            factories=factories,
            budget_db_path=budget_db_path,
        )
    )
