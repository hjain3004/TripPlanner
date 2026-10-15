"""G4 weather replay transport: deterministic, policy-gated, honestly labelled."""

from __future__ import annotations

import asyncio
import json
import socket
from datetime import date
from pathlib import Path
from typing import Any

import pytest

import gateway.weather as weather_pkg
from gateway.weather.contracts import (
    ClimateRequest,
    CurrentAndForecastRequest,
    HistoricalRequest,
    WeatherLocation,
)
from gateway.weather.errors import WeatherGatewayError
from gateway.weather.tool_policy import (
    CLIMATE_TOOL,
    FORECAST_TOOL,
    build_tool_call,
)
from gateway.weather.transport import FixtureWeatherTransport

FIXTURES = Path(weather_pkg.__file__).parent / "fixtures"
LOC = WeatherLocation(latitude=1.3521, longitude=103.8198)
FORECAST_CALL = build_tool_call(CurrentAndForecastRequest(location=LOC, forecast_days=7))
HISTORICAL_CALL = build_tool_call(
    HistoricalRequest(location=LOC, start_date=date(2026, 9, 1), end_date=date(2026, 9, 7))
)
CLIMATE_CALL = build_tool_call(
    ClimateRequest(location=LOC, start_date=date(2027, 2, 1), end_date=date(2027, 2, 7))
)


def call(transport: FixtureWeatherTransport, tool: str, args: dict[str, Any]) -> Any:
    return asyncio.run(transport.call_tool(tool, args))


def write_fixture(tmp: Path, scenario: str, short: str, envelope: Any) -> None:
    (tmp / f"{scenario}.{short}.json").write_text(json.dumps(envelope))


def base_envelope(tool: str, **meta: Any) -> dict[str, Any]:
    return {
        "_fixture_meta": {"origin": "authored_synthetic", "description": "t", **meta},
        "tool": tool,
        "payload": {"latitude": 1.375},
    }


def test_replays_each_tool_with_synthetic_origin() -> None:
    transport = FixtureWeatherTransport("singapore_ok")
    for tool, args in (FORECAST_CALL, HISTORICAL_CALL, CLIMATE_CALL):
        result = call(transport, tool, args)
        assert result.origin == "fixture_synthetic"
        assert isinstance(result.payload, dict)


def test_replay_is_deterministic() -> None:
    transport = FixtureWeatherTransport("singapore_ok")
    first = call(transport, *FORECAST_CALL).payload
    second = call(transport, *FORECAST_CALL).payload
    assert first == second


def test_forbidden_tool_is_refused_before_any_file_access(tmp_path: Path) -> None:
    transport = FixtureWeatherTransport("singapore_ok", fixture_dir=tmp_path)
    for tool in ("openmeteo_dataframe_query", "openmeteo_get_marine", "anything_else"):
        with pytest.raises(WeatherGatewayError) as exc:
            call(transport, tool, {})
        assert exc.value.code == "permission_denied"


def test_out_of_policy_arguments_are_refused(tmp_path: Path) -> None:
    transport = FixtureWeatherTransport("singapore_ok")
    tool, args = FORECAST_CALL
    with pytest.raises(WeatherGatewayError):
        call(transport, tool, {**args, "canvas_id": "tok"})
    with pytest.raises(WeatherGatewayError):
        call(transport, tool, {**args, "forecast_days": 99})


def test_missing_fixture_is_provider_unavailable(tmp_path: Path) -> None:
    transport = FixtureWeatherTransport("nothing_here", fixture_dir=tmp_path)
    with pytest.raises(WeatherGatewayError) as exc:
        call(transport, *FORECAST_CALL)
    assert exc.value.code == "provider_unavailable"


@pytest.mark.parametrize("scenario", ["../x", "a/b", "A", "", "x" * 65, "a.b"])
def test_scenario_names_cannot_traverse(scenario: str) -> None:
    with pytest.raises(WeatherGatewayError):
        FixtureWeatherTransport(scenario)


def test_fixture_claiming_live_is_rejected(tmp_path: Path) -> None:
    envelope = base_envelope(FORECAST_TOOL, status="live")
    write_fixture(tmp_path, "s", "forecast", envelope)
    with pytest.raises(WeatherGatewayError) as exc:
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    assert exc.value.code == "invalid_response"


def test_unrecognised_or_missing_origin_is_rejected(tmp_path: Path) -> None:
    for origin in ("live", "provider", None):
        envelope = base_envelope(FORECAST_TOOL)
        envelope["_fixture_meta"]["origin"] = origin
        write_fixture(tmp_path, "s", "forecast", envelope)
        with pytest.raises(WeatherGatewayError):
            call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)


def test_captured_fixture_must_record_capture_provenance(tmp_path: Path) -> None:
    envelope = base_envelope(FORECAST_TOOL, origin="sanitized_capture")
    write_fixture(tmp_path, "s", "forecast", envelope)
    with pytest.raises(WeatherGatewayError):
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    envelope["_fixture_meta"].update(
        captured_at="2026-10-14T06:00:00Z",
        upstream_version="0.4.1",
        sanitization="stripped nothing; numeric only",
    )
    write_fixture(tmp_path, "s", "forecast", envelope)
    result = call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    assert result.origin == "fixture_captured"


def test_fixture_recorded_for_another_tool_is_rejected(tmp_path: Path) -> None:
    write_fixture(tmp_path, "s", "forecast", base_envelope(CLIMATE_TOOL))
    with pytest.raises(WeatherGatewayError) as exc:
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    assert exc.value.code == "invalid_response"


def test_oversized_and_malformed_fixtures_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "s.forecast.json").write_text("x" * 250_000)
    with pytest.raises(WeatherGatewayError) as exc:
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    assert exc.value.code == "invalid_response"
    (tmp_path / "s.forecast.json").write_text("{not json")
    with pytest.raises(WeatherGatewayError):
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    (tmp_path / "s.forecast.json").write_text("[1,2]")
    with pytest.raises(WeatherGatewayError):
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("singapore_rate_limited", "rate_limited"),
        ("singapore_timeout", "timeout"),
        ("singapore_unavailable", "provider_unavailable"),
    ],
)
def test_error_scenarios_replay_typed_errors(scenario: str, code: str) -> None:
    with pytest.raises(WeatherGatewayError) as exc:
        call(FixtureWeatherTransport(scenario), *FORECAST_CALL)
    assert exc.value.code == code


def test_unknown_error_codes_are_not_replayed(tmp_path: Path) -> None:
    envelope = base_envelope(FORECAST_TOOL)
    del envelope["payload"]
    envelope["error"] = {"code": "budget_exhausted"}
    write_fixture(tmp_path, "s", "forecast", envelope)
    with pytest.raises(WeatherGatewayError) as exc:
        call(FixtureWeatherTransport("s", fixture_dir=tmp_path), *FORECAST_CALL)
    assert exc.value.code == "invalid_response"


def test_replay_never_opens_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("replay must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    call(FixtureWeatherTransport("singapore_ok"), *FORECAST_CALL)


def test_every_committed_fixture_is_honestly_labelled() -> None:
    files = sorted(FIXTURES.glob("*.json"))
    assert files, "expected committed fixtures"
    for path in files:
        meta = json.loads(path.read_text())["_fixture_meta"]
        assert meta["origin"] == "authored_synthetic", path.name
        assert "NOT provider output" in meta["description"], path.name
        assert meta.get("status") != "live", path.name
