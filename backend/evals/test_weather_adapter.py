"""G4 weather adapter: fail-soft contract, bounded retries, breaker, budget, kill switch.

Every failure mode must end in ``status="unavailable"`` with the fixed
"Weather context unavailable" message — never an exception into planning and
never a fabricated forecast.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import gateway.weather as weather_pkg
from gateway.weather.adapter import (
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    OpenMeteoWeatherAdapter,
    WeatherCircuitBreaker,
)
from gateway.weather.budget import MAX_CALLS_PER_PLAN, WeatherCallBudget
from gateway.weather.contracts import (
    ClimateRequest,
    CurrentAndForecastRequest,
    HistoricalRequest,
    WeatherLocation,
    WeatherRequest,
)
from gateway.weather.errors import ErrorCode, WeatherGatewayError
from gateway.weather.tool_policy import build_tool_call
from gateway.weather.transport import FixtureWeatherTransport, ToolResult

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
LOC = WeatherLocation(latitude=1.3521, longitude=103.8198, label="Singapore")
FORECAST = CurrentAndForecastRequest(location=LOC, forecast_days=7, include_current=True)
HISTORICAL = HistoricalRequest(location=LOC, start_date=date(2026, 9, 1), end_date=date(2026, 9, 7))
CLIMATE = ClimateRequest(location=LOC, start_date=date(2027, 2, 1), end_date=date(2027, 2, 7))
FIXTURES = Path(weather_pkg.__file__).parent / "fixtures"


def good_forecast() -> ToolResult:
    envelope = json.loads((FIXTURES / "singapore_ok.forecast.json").read_text())
    return ToolResult(payload=envelope["payload"], origin="fixture_synthetic")


class ScriptedTransport:
    """Plays back a script of results/exceptions and records every call."""

    def __init__(self, *script: ToolResult | BaseException | Callable[[], Any]) -> None:
        self.script = list(script)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((tool_name, arguments))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return await step()  # type: ignore[no-any-return]
        return step


def make(
    transport: Any,
    *,
    enabled: bool = True,
    plan_id: str = "plan-1",
    breaker: WeatherCircuitBreaker | None = None,
    budget: WeatherCallBudget | None = None,
    call_timeout_s: float = 5.0,
) -> OpenMeteoWeatherAdapter:
    return OpenMeteoWeatherAdapter(
        transport=transport,
        budget=budget or WeatherCallBudget(),
        plan_id=plan_id,
        now=lambda: NOW,
        enabled=enabled,
        circuit_breaker=breaker,
        call_timeout_s=call_timeout_s,
    )


def run(adapter: OpenMeteoWeatherAdapter, request: WeatherRequest = FORECAST) -> Any:
    return asyncio.run(adapter.get_context(request))


def err(code: ErrorCode) -> WeatherGatewayError:
    return WeatherGatewayError(code, f"scripted {code}")


def assert_unavailable(outcome: Any, code: ErrorCode, kind: str = "current_and_forecast") -> None:
    assert outcome.status == "unavailable"
    assert outcome.evidence == ()
    assert outcome.unavailable.code == code
    assert outcome.unavailable.request_kind == kind
    assert outcome.unavailable.message == "Weather context unavailable"


class TestSuccess:
    def test_available_outcome_has_evidence_and_attribution(self) -> None:
        transport = ScriptedTransport(good_forecast())
        outcome = run(make(transport))
        assert outcome.status == "available"
        assert [e.kind for e in outcome.evidence] == ["current_observation", "near_term_forecast"]
        assert outcome.attribution == "Weather data by Open-Meteo.com (CC BY 4.0)"
        assert outcome.attribution_url == "https://open-meteo.com/"

    def test_transport_receives_exactly_the_policy_shaped_call(self) -> None:
        transport = ScriptedTransport(good_forecast())
        run(make(transport))
        assert transport.calls == [build_tool_call(FORECAST)]

    def test_replay_transport_end_to_end_for_all_three_dataset_kinds(self) -> None:
        for request, expected in [
            (FORECAST, ["current_observation", "near_term_forecast"]),
            (HISTORICAL, ["historical_observation"]),
            (CLIMATE, ["climate_summary"]),
        ]:
            adapter = make(FixtureWeatherTransport("singapore_ok"))
            outcome = run(adapter, request)
            assert [e.kind for e in outcome.evidence] == expected


class TestDisabledAndKillSwitch:
    def test_disabled_by_default_never_touches_transport_or_budget(self) -> None:
        transport = ScriptedTransport(good_forecast())
        budget = WeatherCallBudget()
        adapter = OpenMeteoWeatherAdapter(
            transport=transport, budget=budget, plan_id="p", now=lambda: NOW
        )
        assert_unavailable(run(adapter), "provider_disabled")
        assert transport.calls == []
        assert budget.calls_used("p") == 0

    def test_explicitly_disabled_adapter_is_unavailable(self) -> None:
        transport = ScriptedTransport(good_forecast())
        assert_unavailable(run(make(transport, enabled=False)), "provider_disabled")
        assert transport.calls == []


class TestFailSoft:
    @pytest.mark.parametrize(
        "code", ["rate_limited", "timeout", "provider_unavailable", "invalid_response"]
    )
    def test_provider_errors_become_unavailable(self, code: ErrorCode) -> None:
        outcome = run(make(ScriptedTransport(err(code))))
        assert_unavailable(outcome, code)

    def test_unexpected_exception_becomes_unavailable_not_a_crash(self) -> None:
        outcome = run(make(ScriptedTransport(RuntimeError("boom with secret sk-123456789"))))
        assert_unavailable(outcome, "provider_unavailable")
        assert "boom" not in outcome.model_dump_json()

    def test_malformed_payload_becomes_unavailable(self) -> None:
        bad = ToolResult(payload={"latitude": "x"}, origin="fixture_synthetic")
        assert_unavailable(run(make(ScriptedTransport(bad))), "invalid_response")

    def test_unsafe_text_payload_cannot_block_planning(self) -> None:
        outcome = run(make(FixtureWeatherTransport("singapore_unsafe_notice")))
        assert outcome.status == "available"  # notice is redacted, not fatal
        assert "ignore previous" not in outcome.model_dump_json().lower()

    def test_timeout_via_slow_transport(self) -> None:
        async def slow() -> ToolResult:
            await asyncio.sleep(2)
            return good_forecast()

        transport = ScriptedTransport(slow)
        outcome = run(make(transport, call_timeout_s=0.05))
        assert_unavailable(outcome, "timeout")
        assert len(transport.calls) == 2  # timeout is retryable exactly once

    def test_cancellation_is_not_swallowed(self) -> None:
        transport = ScriptedTransport(asyncio.CancelledError())
        with pytest.raises(asyncio.CancelledError):
            run(make(transport))

    def test_invalid_request_dates_fail_soft_without_spending_budget(self) -> None:
        budget = WeatherCallBudget()
        transport = ScriptedTransport(good_forecast())
        recent = HistoricalRequest(
            location=LOC, start_date=date(2026, 10, 1), end_date=date(2026, 10, 12)
        )
        outcome = run(make(transport, budget=budget), recent)
        assert_unavailable(outcome, "invalid_request", "historical")
        assert transport.calls == [] and budget.calls_used("plan-1") == 0

    def test_climate_inside_forecast_horizon_is_refused_not_relabelled(self) -> None:
        transport = ScriptedTransport(good_forecast())
        inside = ClimateRequest(
            location=LOC, start_date=date(2026, 10, 20), end_date=date(2026, 10, 26)
        )
        assert_unavailable(run(make(transport), inside), "invalid_request", "climate")
        assert transport.calls == []


class TestForbiddenAndWrongEndpoint:
    def test_forbidden_tool_in_transport_response_path_is_blocked_by_policy(self) -> None:
        # The replay transport enforces the same policy: a forbidden tool never loads a fixture.
        transport = FixtureWeatherTransport("singapore_ok")
        with pytest.raises(WeatherGatewayError) as exc:
            asyncio.run(transport.call_tool("openmeteo_dataframe_query", {"sql": "select 1"}))
        assert exc.value.code == "permission_denied"

    def test_permission_denied_from_transport_is_unavailable(self) -> None:
        outcome = run(make(ScriptedTransport(err("permission_denied"))))
        assert_unavailable(outcome, "permission_denied")


class TestRetries:
    def test_one_bounded_retry_on_transient_failure_then_success(self) -> None:
        transport = ScriptedTransport(err("provider_unavailable"), good_forecast())
        outcome = run(make(transport))
        assert outcome.status == "available"
        assert len(transport.calls) == 2

    @pytest.mark.parametrize("code", ["provider_unavailable", "timeout"])
    def test_never_more_than_one_retry(self, code: ErrorCode) -> None:
        transport = ScriptedTransport(err(code))
        assert_unavailable(run(make(transport)), code)
        assert len(transport.calls) == 2

    @pytest.mark.parametrize("code", ["rate_limited", "invalid_response", "permission_denied"])
    def test_no_retry_for_non_transient_failures(self, code: ErrorCode) -> None:
        transport = ScriptedTransport(err(code))
        run(make(transport))
        assert len(transport.calls) == 1


class TestBudget:
    def test_per_plan_call_ceiling_is_enforced_across_requests(self) -> None:
        budget = WeatherCallBudget()
        transport = ScriptedTransport(good_forecast())
        adapter = make(transport, budget=budget)
        outcomes = [run(adapter) for _ in range(MAX_CALLS_PER_PLAN + 1)]
        assert [o.status for o in outcomes[:MAX_CALLS_PER_PLAN]] == [
            "available"
        ] * MAX_CALLS_PER_PLAN
        assert_unavailable(outcomes[-1], "budget_exhausted")
        assert len(transport.calls) == MAX_CALLS_PER_PLAN

    def test_retry_attempts_consume_budget(self) -> None:
        budget = WeatherCallBudget()
        run(make(ScriptedTransport(err("timeout")), budget=budget))
        assert budget.calls_used("plan-1") == 2

    def test_ledger_contention_fails_soft(self, tmp_path: Path) -> None:
        import sqlite3

        db = tmp_path / "b.sqlite"
        budget = WeatherCallBudget(db, busy_timeout_s=0.05)
        blocker = sqlite3.connect(db, timeout=0.05)
        blocker.execute("BEGIN IMMEDIATE")
        try:
            outcome = run(make(ScriptedTransport(good_forecast()), budget=budget))
        finally:
            blocker.rollback()
            blocker.close()
        assert_unavailable(outcome, "budget_exhausted")  # fail closed: no confirmed headroom


class TestCircuitBreaker:
    def test_breaker_opens_after_consecutive_failures_and_stops_calling(self) -> None:
        breaker = WeatherCircuitBreaker()
        transport = ScriptedTransport(err("rate_limited"))
        adapter = make(transport, breaker=breaker, budget=WeatherCallBudget())
        for _ in range(CIRCUIT_BREAKER_FAILURE_THRESHOLD):
            assert_unavailable(run(adapter), "rate_limited")
        assert breaker.is_open
        calls_before = len(transport.calls)
        outcome = run(adapter)
        assert_unavailable(outcome, "provider_unavailable")
        assert len(transport.calls) == calls_before

    def test_success_resets_the_failure_count(self) -> None:
        breaker = WeatherCircuitBreaker()
        transport = ScriptedTransport(err("rate_limited"), err("rate_limited"), good_forecast())
        adapter = make(transport, breaker=breaker)
        run(adapter)
        run(adapter)
        assert breaker.consecutive_failures == 2
        assert run(adapter).status == "available"
        assert breaker.consecutive_failures == 0
        assert not breaker.is_open

    def test_caller_errors_do_not_trip_the_breaker(self) -> None:
        breaker = WeatherCircuitBreaker()
        adapter = make(ScriptedTransport(good_forecast()), breaker=breaker)
        recent = HistoricalRequest(
            location=LOC, start_date=date(2026, 10, 1), end_date=date(2026, 10, 12)
        )
        for _ in range(CIRCUIT_BREAKER_FAILURE_THRESHOLD + 2):
            run(adapter, recent)
        assert breaker.consecutive_failures == 0 and not breaker.is_open

    def test_shared_breaker_protects_the_next_plan(self) -> None:
        breaker = WeatherCircuitBreaker()
        for plan in ("a", "b", "c"):
            run(make(ScriptedTransport(err("provider_unavailable")), breaker=breaker, plan_id=plan))
        assert breaker.is_open
        transport = ScriptedTransport(good_forecast())
        assert_unavailable(
            run(make(transport, breaker=breaker, plan_id="d")), "provider_unavailable"
        )
        assert transport.calls == []
