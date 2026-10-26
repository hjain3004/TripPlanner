"""OpenBnBAdapter: experimental, disabled-by-default rental-stay evidence.

Assembles an injected transport, call budget and circuit breaker into a
``TravelProviderAdapter`` for the ``hotel`` domain. It is never constructed enabled by any
factory in this repository, and it holds no environment variable: only ``registry.py``
decides ``enabled`` (the kill switch wins there), so this class stays dumb and testable.

Failure policy (spec 16 §13, conservative where the source is a scraper):

* disabled / open breaker / unsupported request: no budget spent, no dispatch;
* one call reserved *before* dispatch; a timeout or crash never refunds it;
* **zero retries.** The matrix permits one bounded retry on a transient failure, but this
  source forbids automated access, so a second hit is never worth taking;
* any failure after reservation counts toward the circuit breaker.

``search_hotels`` returns only priced, verify-required ``HotelQuote`` rows. Discovery-only
listings (nightly rate, unverifiable price) are available from ``search_rental_stays`` as
``IncompleteListing`` rows -- the shared quote contract has no honest place for them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from gateway.travel.adapters.openbnb.budget import (
    OpenBnBBudgetUnavailableError,
    OpenBnBCallBudget,
)
from gateway.travel.adapters.openbnb.contracts import OpenBnBListingDetail, RentalSearchOutcome
from gateway.travel.adapters.openbnb.detail import enrich_quote_with_detail, parse_detail_payload
from gateway.travel.adapters.openbnb.fixture_transport import OpenBnBToolResult, OpenBnBTransport
from gateway.travel.adapters.openbnb.normalize import parse_search_payload
from gateway.travel.adapters.openbnb.requests import build_detail_arguments, build_search_arguments
from gateway.travel.adapters.openbnb.tool_policy import DETAIL_TOOL, SEARCH_TOOL
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

PROVIDER_ID = "openbnb"
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 2
DEFAULT_CALL_TIMEOUT_S = 30.0


class OpenBnBCircuitBreaker:
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


class OpenBnBAdapter:
    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"hotel"},
        countries="configured",
        live_data=False,
        supports_cache=False,
        supports_commercial_use=False,
        allowed_profiles={"student_noncommercial"},
        source_method="scraper_wrapper",
        stability="experimental",
        requires_user_initiated_search=True,
        max_concurrency=1,
    )

    def __init__(
        self,
        *,
        transport: OpenBnBTransport | None,
        budget: OpenBnBCallBudget,
        plan_id: str,
        now: Callable[[], datetime],
        enabled: bool = False,
        circuit_breaker: OpenBnBCircuitBreaker | None = None,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
        bare_dollar_currency: str | None = None,
    ) -> None:
        self._transport = transport
        self._budget = budget
        self._plan_id = plan_id
        self._now = now
        self._enabled = enabled
        self._breaker = circuit_breaker or OpenBnBCircuitBreaker()
        self._timeout = call_timeout_s
        self._bare_dollar_currency = bare_dollar_currency
        self._slot = asyncio.Lock()  # max_concurrency == 1

    @property
    def consecutive_failures(self) -> int:
        return self._breaker.consecutive_failures

    def _guard(self) -> OpenBnBTransport:
        if not self._enabled:
            raise TravelGatewayError(
                "provider_unavailable", "OpenBnB is disabled (default off / kill switch)"
            )
        if self._transport is None:
            raise TravelGatewayError("provider_unavailable", "OpenBnB has no transport configured")
        if self._breaker.is_open:
            raise TravelGatewayError(
                "provider_unavailable", "OpenBnB circuit breaker is open; falling back"
            )
        return self._transport

    def _reserve(self) -> None:
        try:
            reserved = self._budget.reserve_call(self._plan_id)
        except OpenBnBBudgetUnavailableError as exc:
            raise TravelGatewayError("provider_unavailable", str(exc)) from exc
        if not reserved:
            raise TravelGatewayError("budget_exhausted", "OpenBnB call budget exhausted")

    async def _dispatch(
        self, transport: OpenBnBTransport, tool: str, arguments: dict[str, object]
    ) -> OpenBnBToolResult:
        async with self._slot:
            self._reserve()
            try:
                async with asyncio.timeout(self._timeout):
                    return await transport.call_tool(tool, arguments)
            except TimeoutError:
                self._breaker.record_failure()
                raise TravelGatewayError("timeout", "OpenBnB call timed out") from None
            except TravelGatewayError:
                self._breaker.record_failure()
                raise
            except Exception:
                self._breaker.record_failure()
                raise TravelGatewayError(
                    "provider_unavailable", "OpenBnB transport failed"
                ) from None

    async def search_rental_stays(self, request: HotelSearchRequest) -> RentalSearchOutcome:
        transport = self._guard()
        arguments = build_search_arguments(request)  # unsupported => no budget spent
        result = await self._dispatch(transport, SEARCH_TOOL, arguments)
        try:
            outcome = parse_search_payload(
                result.payload,
                request,
                now=self._now(),
                origin=result.origin,
                bare_dollar_currency=self._bare_dollar_currency,
            )
        except TravelGatewayError:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return outcome

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        return (await self.search_rental_stays(request)).quotes

    async def get_listing_detail(
        self, listing_id: str, request: HotelSearchRequest
    ) -> OpenBnBListingDetail:
        transport = self._guard()
        arguments = build_detail_arguments(listing_id, request)
        result = await self._dispatch(transport, DETAIL_TOOL, arguments)
        try:
            detail = parse_detail_payload(result.payload, listing_id, request)
        except TravelGatewayError:
            self._breaker.record_failure()
            raise
        self._breaker.record_success()
        return detail

    async def enrich_with_coordinates(
        self, quote: HotelQuote, request: HotelSearchRequest
    ) -> HotelQuote:
        listing_id = quote.evidence.provider_quote_id
        if listing_id is None or quote.property_id != f"openbnb:{listing_id}":
            raise TravelGatewayError("invalid_response", "quote is not an OpenBnB listing")
        detail = await self.get_listing_detail(listing_id, request)
        return enrich_quote_with_detail(quote, detail)

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
