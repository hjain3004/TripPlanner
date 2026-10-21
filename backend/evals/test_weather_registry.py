"""G4 weather registry: disabled by default, one kill switch that always wins,
read once at construction (never inside the adapter's call path)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from gateway.weather.budget import WeatherCallBudget
from gateway.weather.contracts import CurrentAndForecastRequest, WeatherLocation
from gateway.weather.registry import (
    ENABLE_ENV_VAR,
    KILL_SWITCH_ENV_VAR,
    WeatherProviderRegistryEntry,
    build_weather_adapter,
    get_default_weather_registry,
)
from gateway.weather.transport import FixtureWeatherTransport

NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
REQUEST = CurrentAndForecastRequest(
    location=WeatherLocation(latitude=1.35, longitude=103.82), forecast_days=7
)


def entry(env: dict[str, str]) -> WeatherProviderRegistryEntry:
    return get_default_weather_registry(env).get_entry("open_meteo")


def test_disabled_by_default() -> None:
    assert entry({}).enabled is False
    assert get_default_weather_registry({}).select(active_profile="student_noncommercial") == []


def test_env_names_are_stable() -> None:
    assert ENABLE_ENV_VAR == "TRIPWISE_OPEN_METEO_ENABLED"
    assert KILL_SWITCH_ENV_VAR == "TRIPWISE_OPEN_METEO_KILL_SWITCH"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_truthy_enable_flag_enables(value: str) -> None:
    assert entry({ENABLE_ENV_VAR: value}).enabled is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe", "enabled"])
def test_non_truthy_values_leave_it_disabled(value: str) -> None:
    assert entry({ENABLE_ENV_VAR: value}).enabled is False


def test_kill_switch_always_wins() -> None:
    assert entry({ENABLE_ENV_VAR: "1", KILL_SWITCH_ENV_VAR: "1"}).enabled is False
    assert entry({ENABLE_ENV_VAR: "1", KILL_SWITCH_ENV_VAR: "yes"}).enabled is False
    assert entry({ENABLE_ENV_VAR: "1", KILL_SWITCH_ENV_VAR: "0"}).enabled is True


def test_student_profile_only_and_zero_cost() -> None:
    e = entry({ENABLE_ENV_VAR: "1"})
    assert e.allowed_profiles == {"student_noncommercial"}
    assert e.monthly_cost_minor == 0
    assert e.source_method == "community_mcp"
    registry = get_default_weather_registry({ENABLE_ENV_VAR: "1"})
    assert registry.select(active_profile="student_noncommercial") == [e]
    assert registry.select(active_profile="commercial_production") == []


def test_unknown_cost_cannot_construct_an_entry() -> None:
    with pytest.raises(ValidationError):
        WeatherProviderRegistryEntry.model_validate(  # type: ignore[call-arg]
            {
                "provider_id": "x",
                "allowed_profiles": {"student_noncommercial"},
                "source_method": "community_mcp",
                "evidence_kinds": {"climate_summary"},
            }
        )


def test_default_registry_reads_the_process_environment_once_at_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENABLE_ENV_VAR, raising=False)
    monkeypatch.delenv(KILL_SWITCH_ENV_VAR, raising=False)
    registry = get_default_weather_registry()
    monkeypatch.setenv(ENABLE_ENV_VAR, "1")
    assert registry.get_entry("open_meteo").enabled is False  # snapshot, not live-read
    assert get_default_weather_registry().get_entry("open_meteo").enabled is True


def test_unknown_provider_id_raises() -> None:
    from gateway.weather.errors import WeatherGatewayError

    with pytest.raises(WeatherGatewayError):
        get_default_weather_registry({}).get_entry("nope")


def test_built_adapter_follows_the_entry_and_the_profile(tmp_path: Path) -> None:
    def build(env: dict[str, str], profile: str) -> object:
        return build_weather_adapter(
            get_default_weather_registry(env),
            active_profile=profile,
            transport=FixtureWeatherTransport("singapore_ok"),
            budget=WeatherCallBudget(),
            plan_id="p",
            now=lambda: NOW,
        )

    off = build({}, "student_noncommercial")
    on = build({ENABLE_ENV_VAR: "1"}, "student_noncommercial")
    commercial = build({ENABLE_ENV_VAR: "1"}, "commercial_production")
    assert asyncio.run(off.get_context(REQUEST)).unavailable.code == "provider_disabled"  # type: ignore[attr-defined]
    assert asyncio.run(on.get_context(REQUEST)).status == "available"  # type: ignore[attr-defined]
    assert (
        asyncio.run(commercial.get_context(REQUEST)).unavailable.code  # type: ignore[attr-defined]
        == "provider_disabled"
    )
