"""GondolaAdapter — assembles the transport-agnostic fetch callables,
budget ledger, and circuit breaker into a ``TravelProviderAdapter``.

The kill switch is a single injected boolean (``live_enabled``, defaulting
to ``False``) — never an environment variable read inside this class. Only
the registry (Phase 7) decides activation, keeping this class dumb and
fully testable with injected fetch callables (fixture-backed in tests,
live-transport-backed only when the registry explicitly enables it).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

from gateway.travel.adapters.gondola.contracts import GondolaFlightResult, GondolaHotelResult
from gateway.travel.adapters.gondola.normalize_flight import normalize_gondola_flight
from gateway.travel.adapters.gondola.normalize_hotel import normalize_gondola_hotel
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
from gateway.travel.protocol import AdapterCapabilities

PROVIDER_ID = "gondola"
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
# Zero retries on 4xx-shaped failures (auth/validation/rate-limit/permission);
# at most one bounded retry on a transient failure. rate_limited is treated
# as a hard stop, not a retry target -- an unpublished rate limit is a
# reliability concern to defend against, never permission to hammer the API.
_RETRYABLE_CODES = frozenset({"provider_unavailable", "timeout"})

HotelFetcher = Callable[[HotelSearchRequest], Awaitable[list[GondolaHotelResult]]]
FlightFetcher = Callable[[FlightSearchRequest], Awaitable[list[GondolaFlightResult]]]


class GondolaCircuitBreaker:
    def __init__(self, *, failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD) -> None:
        self._failure_threshold = failure_threshold
        self.consecutive_failures = 0
        self.is_open = False

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self._failure_threshold:
            self.is_open = True


class GondolaAdapter:
    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"flight", "hotel"},
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
        fetch_hotels: HotelFetcher | None,
        fetch_flights: FlightFetcher | None,
        budget: object,
        plan_id: str,
        now: Callable[[], datetime],
        live_enabled: bool = False,
        circuit_breaker: GondolaCircuitBreaker | None = None,
    ) -> None:
        self._fetch_hotels = fetch_hotels
        self._fetch_flights = fetch_flights
        self._budget = budget
        self._plan_id = plan_id
        self._now = now
        self._live_enabled = live_enabled
        self._circuit_breaker = circuit_breaker or GondolaCircuitBreaker()

    @property
    def consecutive_failures(self) -> int:
        return self._circuit_breaker.consecutive_failures

    async def _call_with_bounded_retry(self, fetch: Callable[[], Awaitable[list]]) -> list:  # type: ignore[type-arg]
        try:
            return await fetch()
        except TravelGatewayError as exc:
            if exc.code not in _RETRYABLE_CODES:
                raise
            return await fetch()  # exactly one bounded retry, no further attempts

    def _guard(self) -> None:
        if not self._live_enabled:
            raise TravelGatewayError(
                "provider_unavailable", "Gondola live mode is disabled (kill switch off)"
            )
        if self._circuit_breaker.is_open:
            raise TravelGatewayError(
                "provider_unavailable", "Gondola circuit breaker is open; falling back"
            )
        if not self._budget.reserve_call(self._plan_id):  # type: ignore[attr-defined]
            raise TravelGatewayError(
                "budget_exhausted", "Gondola per-plan call budget exhausted"
            )

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        self._guard()
        fetch_hotels = self._fetch_hotels
        if fetch_hotels is None:
            raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not fetch hotels")
        try:
            raw_results = await self._call_with_bounded_retry(lambda: fetch_hotels(request))
        except Exception:
            self._circuit_breaker.record_failure()
            raise
        self._circuit_breaker.record_success()
        now = self._now()
        return [normalize_gondola_hotel(raw, request, now=now) for raw in raw_results]

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]:
        self._guard()
        fetch_flights = self._fetch_flights
        if fetch_flights is None:
            raise TravelGatewayError(
                "unsupported_domain", f"{PROVIDER_ID} does not fetch flights"
            )
        try:
            raw_results = await self._call_with_bounded_retry(lambda: fetch_flights(request))
        except Exception:
            self._circuit_breaker.record_failure()
            raise
        self._circuit_breaker.record_success()
        now = self._now()
        return [normalize_gondola_flight(raw, request, now=now) for raw in raw_results]

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        raise TravelGatewayError(
            "unsupported_domain", f"{PROVIDER_ID} does not support flight_trend"
        )

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support award")
