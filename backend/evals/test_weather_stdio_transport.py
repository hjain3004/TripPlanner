"""G4 weather: the real MCP stdio boundary, against an offline test double.

These tests start an actual subprocess MCP server (``weather_fake_mcp_server``,
built on the official ``mcp`` SDK) and talk to it through
``StdioWeatherTransport`` over genuine JSON-RPC/stdio. The double serves the
committed authored-synthetic fixtures; nothing here touches Node, npm or the
network, and nothing here is live acceptance of the upstream server.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

import gateway.weather as weather_pkg
from gateway.weather.adapter import OpenMeteoWeatherAdapter
from gateway.weather.budget import WeatherCallBudget
from gateway.weather.contracts import CurrentAndForecastRequest, WeatherLocation
from gateway.weather.errors import WeatherGatewayError
from gateway.weather.stdio_transport import ServerLaunch, StdioWeatherTransport
from gateway.weather.tool_policy import build_tool_call

FAKE_SERVER = Path(__file__).parent / "weather_fake_mcp_server.py"
FIXTURES = Path(weather_pkg.__file__).parent / "fixtures"
NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
LOC = WeatherLocation(latitude=1.3521, longitude=103.8198, label="Singapore")
FORECAST = CurrentAndForecastRequest(location=LOC, forecast_days=7, include_current=True)
FORECAST_CALL = build_tool_call(FORECAST)


def launch(mode: str = "ok", **kwargs: Any) -> ServerLaunch:
    return ServerLaunch(
        command=sys.executable,
        args=(str(FAKE_SERVER),),
        env=(("FAKE_MCP_MODE", mode), ("FAKE_MCP_FIXTURES", str(FIXTURES))),
        **kwargs,
    )


def call(transport: StdioWeatherTransport, tool: str, args: dict[str, Any]) -> Any:
    return asyncio.run(transport.call_tool(tool, args))


def expect(transport: StdioWeatherTransport, code: str, call_spec: Any = FORECAST_CALL) -> None:
    with pytest.raises(WeatherGatewayError) as exc:
        call(transport, *call_spec)
    assert exc.value.code == code


class TestRealProtocolRoundTrip:
    def test_structured_result_round_trips_over_stdio(self) -> None:
        result = call(StdioWeatherTransport(launch(), total_timeout_s=30), *FORECAST_CALL)
        assert result.payload["timezone"] == "Asia/Singapore"
        assert len(result.payload["daily"]) == 7

    def test_text_content_fallback_is_accepted(self) -> None:
        result = call(
            StdioWeatherTransport(launch("unstructured_json"), total_timeout_s=30), *FORECAST_CALL
        )
        assert result.payload["timezone"] == "Asia/Singapore"

    def test_non_pinned_launch_can_only_produce_synthetic_evidence(self) -> None:
        transport = StdioWeatherTransport(launch(), total_timeout_s=30)
        assert transport.origin == "fixture_synthetic"
        assert call(transport, *FORECAST_CALL).origin == "fixture_synthetic"

    def test_full_adapter_path_through_the_mcp_boundary(self) -> None:
        adapter = OpenMeteoWeatherAdapter(
            transport=StdioWeatherTransport(launch(), total_timeout_s=30),
            budget=WeatherCallBudget(),
            plan_id="p",
            now=lambda: NOW,
            enabled=True,
            call_timeout_s=40,
        )
        outcome = asyncio.run(adapter.get_context(FORECAST))
        assert [e.kind for e in outcome.evidence] == ["current_observation", "near_term_forecast"]
        assert all(e.meta.origin == "fixture_synthetic" for e in outcome.evidence)
        assert all(e.meta.needs_verification for e in outcome.evidence)


class TestPolicyIsEnforcedBeforeAnyProcessStarts:
    def test_forbidden_storage_tool_never_spawns_a_process(self) -> None:
        # The command does not exist: a spawn attempt would be provider_unavailable.
        transport = StdioWeatherTransport(
            ServerLaunch(command="/nonexistent/node", args=("x.js",)), total_timeout_s=5
        )
        for tool in ("openmeteo_dataframe_query", "openmeteo_get_marine", "tools/list"):
            expect(transport, "permission_denied", (tool, {"sql": "select 1"}))

    def test_out_of_policy_arguments_never_spawn_a_process(self) -> None:
        transport = StdioWeatherTransport(
            ServerLaunch(command="/nonexistent/node", args=("x.js",)), total_timeout_s=5
        )
        tool, args = FORECAST_CALL
        expect(transport, "permission_denied", (tool, {**args, "canvas_id": "tok"}))
        expect(transport, "invalid_request", (tool, {**args, "forecast_days": 40}))

    def test_server_side_storage_tool_exists_but_is_unreachable(self) -> None:
        # The double registers openmeteo_dataframe_query; our policy still refuses it.
        transport = StdioWeatherTransport(launch(), total_timeout_s=30)
        expect(transport, "permission_denied", ("openmeteo_dataframe_query", {"sql": "select 1"}))


class TestWrongEndpoint:
    def test_wrong_server_identity_is_refused_before_any_tool_call(self) -> None:
        expect(StdioWeatherTransport(launch("wrong_name"), total_timeout_s=30), "permission_denied")

    def test_wrong_server_version_is_refused(self) -> None:
        bad = launch(expected_server_version="9.9.9")
        expect(StdioWeatherTransport(bad, total_timeout_s=30), "permission_denied")

    @pytest.mark.parametrize(
        "env",
        [
            (("OPEN_METEO_API_BASE_URL", "https://evil.example"),),
            (("OPEN_METEO_CLIMATE_BASE_URL", "http://api.open-meteo.com"),),
            (("OPEN_METEO_TELEMETRY_URL", "https://api.open-meteo.com"),),
            (("CANVAS_PROVIDER_TYPE", "duckdb"),),
            (("OPENMETEO_DATAFRAME_DROP_ENABLED", "true"),),
            (("OPEN_METEO_API_KEY", "abcdef123456"),),
            (("SOME_SECRET_TOKEN", "x"),),
        ],
    )
    def test_launch_with_redirected_endpoint_storage_or_credentials_is_refused(
        self, env: tuple[tuple[str, str], ...]
    ) -> None:
        with pytest.raises(WeatherGatewayError) as exc:
            StdioWeatherTransport(ServerLaunch(command=sys.executable, args=(), env=env))
        assert exc.value.code == "permission_denied"

    def test_relative_command_is_refused(self) -> None:
        with pytest.raises(WeatherGatewayError):
            StdioWeatherTransport(ServerLaunch(command="node", args=("index.js",)))

    def test_server_command_that_cannot_start_is_provider_unavailable(self) -> None:
        transport = StdioWeatherTransport(
            ServerLaunch(command="/nonexistent/node", args=("x.js",)), total_timeout_s=5
        )
        expect(transport, "provider_unavailable")


class TestEnvironmentIsolation:
    def test_parent_secrets_and_endpoint_overrides_are_not_inherited(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SOME_SECRET_TOKEN", "super-secret")
        monkeypatch.setenv("OPEN_METEO_API_BASE_URL", "https://evil.example")
        monkeypatch.setenv("HOME", "/sensitive-home")
        monkeypatch.setenv("LOGNAME", "sensitive-logname")
        monkeypatch.setenv("PATH", "/sensitive-path")
        monkeypatch.setenv("SHELL", "/sensitive-shell")
        monkeypatch.setenv("TERM", "sensitive-term")
        monkeypatch.setenv("USER", "sensitive-user")
        transport = StdioWeatherTransport(launch("env_dump"), total_timeout_s=30)
        payload = call(transport, *FORECAST_CALL).payload
        assert payload["leaked_secret"] is False
        assert payload["api_base"] != "https://evil.example"
        assert payload["home"] != "/sensitive-home"
        assert payload["logname"] == "tripwise-weather"
        assert payload["path"] == str(Path(sys.executable).parent)
        assert payload["shell"] == "/bin/false"
        assert payload["term"] == "dumb"
        assert payload["user"] == "tripwise-weather"


class TestFailureModes:
    def test_timeout_is_typed_and_prompt(self) -> None:
        transport = StdioWeatherTransport(launch("sleep"), total_timeout_s=3)
        started = time.monotonic()
        expect(transport, "timeout")
        assert time.monotonic() - started < 20  # the sleeping server is torn down, not awaited

    def test_tool_error_is_invalid_response_and_never_echoes_provider_text(self) -> None:
        with pytest.raises(WeatherGatewayError) as exc:
            call(StdioWeatherTransport(launch("error"), total_timeout_s=30), *FORECAST_CALL)
        assert exc.value.code == "invalid_response"
        assert "ignore previous" not in str(exc.value).lower()
        assert "exploded" not in str(exc.value).lower()

    def test_rate_limit_error_is_classified(self) -> None:
        expect(StdioWeatherTransport(launch("rate_limit"), total_timeout_s=30), "rate_limited")

    def test_oversized_result_is_rejected(self) -> None:
        expect(StdioWeatherTransport(launch("oversize"), total_timeout_s=30), "invalid_response")

    def test_non_json_text_result_is_rejected(self) -> None:
        expect(
            StdioWeatherTransport(launch("unstructured_junk"), total_timeout_s=30),
            "invalid_response",
        )

    def test_adapter_turns_every_transport_failure_into_unavailable(self) -> None:
        for mode in ("error", "rate_limit", "oversize", "wrong_name"):
            adapter = OpenMeteoWeatherAdapter(
                transport=StdioWeatherTransport(launch(mode), total_timeout_s=30),
                budget=WeatherCallBudget(),
                plan_id=f"p-{mode}",
                now=lambda: NOW,
                enabled=True,
                call_timeout_s=40,
            )
            outcome = asyncio.run(adapter.get_context(FORECAST))
            assert outcome.status == "unavailable", mode
            assert outcome.unavailable is not None
            assert outcome.unavailable.message == "Weather context unavailable"


def test_historical_request_shape_is_accepted_by_the_protocol_double() -> None:
    from gateway.weather.contracts import HistoricalRequest

    tool, args = build_tool_call(
        HistoricalRequest(location=LOC, start_date=date(2026, 9, 1), end_date=date(2026, 9, 7))
    )
    result = call(StdioWeatherTransport(launch(), total_timeout_s=30), tool, args)
    assert result.payload["models"] == ["era5"]
