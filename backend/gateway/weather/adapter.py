"""OpenMeteoWeatherAdapter — fail-soft weather *context* (G4).

Contract: ``get_context`` never raises into planning (except task
cancellation) and never fabricates data. Every failure — disabled provider,
open circuit breaker, exhausted budget, bad request dates, transport error,
timeout, rate limit, malformed or hostile payload — becomes
``status="unavailable"`` with the fixed message "Weather context
unavailable" and a typed code.

Activation is a single injected boolean (``enabled``, default ``False``) that
only the registry decides; this class never reads the environment. Retry
policy follows spec 16 §13: at most one retry, only for transient failures
(``provider_unavailable``/``timeout``); a rate limit is a hard stop. Every
attempt (including the retry) reserves a slot from the per-plan ledger.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from gateway.weather.budget import WeatherBudgetContentionError
from gateway.weather.contracts import (
    WeatherContextOutcome,
    WeatherEvidence,
    WeatherRequest,
    WeatherUnavailable,
    assert_date_semantics,
)
from gateway.weather.errors import ErrorCode, WeatherGatewayError
from gateway.weather.normalize import normalize_tool_result
from gateway.weather.tool_policy import build_tool_call
from gateway.weather.transport import ToolResult, WeatherToolTransport

CIRCUIT_BREAKER_FAILURE_THRESHOLD = 3
DEFAULT_CALL_TIMEOUT_S = 15.0
_RETRYABLE: frozenset[ErrorCode] = frozenset({"provider_unavailable", "timeout"})
# Provider-side failures count toward the breaker; caller/budget problems do not.
_BREAKER_CODES: frozenset[ErrorCode] = frozenset(
    {"provider_unavailable", "timeout", "rate_limited", "invalid_response"}
)


class WeatherCircuitBreaker:
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


class OpenMeteoWeatherAdapter:
    def __init__(
        self,
        *,
        transport: WeatherToolTransport,
        budget: Any,
        plan_id: str,
        now: Callable[[], datetime],
        enabled: bool = False,
        circuit_breaker: WeatherCircuitBreaker | None = None,
        call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
    ) -> None:
        self._transport = transport
        self._budget = budget
        self._plan_id = plan_id
        self._now = now
        self._enabled = enabled
        self._breaker = circuit_breaker or WeatherCircuitBreaker()
        self._call_timeout_s = call_timeout_s

    async def get_context(self, request: WeatherRequest) -> WeatherContextOutcome:
        if not self._enabled:
            return self._unavailable("provider_disabled", request)
        try:
            evidence = await self._fetch(request)
        except WeatherGatewayError as exc:
            return self._unavailable(exc.code, request)
        except Exception:
            # Anything unexpected is still just "unavailable": planning must never
            # break on weather, and no exception text may travel onward.
            return self._unavailable("provider_unavailable", request)
        return WeatherContextOutcome(status="available", evidence=evidence)

    # -- internals ------------------------------------------------------------
    @staticmethod
    def _unavailable(code: ErrorCode, request: WeatherRequest) -> WeatherContextOutcome:
        return WeatherContextOutcome(
            status="unavailable",
            unavailable=WeatherUnavailable(code=code, request_kind=request.kind),
        )

    async def _fetch(self, request: WeatherRequest) -> tuple[WeatherEvidence, ...]:
        now = self._now()
        # Date semantics and tool-call shape are caller concerns: checked before
        # anything is spent, and never counted against the provider.
        assert_date_semantics(request, today=now.astimezone(UTC).date())
        tool_name, arguments = build_tool_call(request)
        if self._breaker.is_open:
            raise WeatherGatewayError("provider_unavailable", "circuit breaker is open")

        try:
            result = await self._call_with_bounded_retry(tool_name, arguments)
            evidence = normalize_tool_result(request, result, now=now)
        except WeatherGatewayError as exc:
            if exc.code in _BREAKER_CODES:
                self._breaker.record_failure()
            raise
        except Exception as exc:
            self._breaker.record_failure()
            raise WeatherGatewayError(
                "provider_unavailable", "the weather transport failed unexpectedly"
            ) from exc
        self._breaker.record_success()
        return evidence

    async def _call_with_bounded_retry(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        try:
            return await self._attempt(tool_name, arguments)
        except WeatherGatewayError as exc:
            if exc.code not in _RETRYABLE:
                raise
        return await self._attempt(tool_name, arguments)  # exactly one retry, then stop

    async def _attempt(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        try:
            reserved = self._budget.reserve_call(self._plan_id)
        except WeatherBudgetContentionError as exc:
            # Fail closed: if the ledger cannot confirm headroom, make no call.
            raise WeatherGatewayError(
                "budget_exhausted", "call budget could not be confirmed"
            ) from exc
        if not reserved:
            raise WeatherGatewayError("budget_exhausted", "per-plan call budget exhausted")
        try:
            async with asyncio.timeout(self._call_timeout_s):
                return await self._transport.call_tool(tool_name, arguments)
        except TimeoutError as exc:
            raise WeatherGatewayError("timeout", "weather call timed out") from exc
