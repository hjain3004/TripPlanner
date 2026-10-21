"""Static, typed weather provider registry (G4).

Mirrors the travel registry's discipline without extending it: weather is
contextual evidence, not travel inventory, so it is *not* a spec-16 ``Domain``
and does not live in ``TravelProviderRegistry``. The entry is **disabled by
default**; unknown cost cannot be stated implicitly (``monthly_cost_minor``
has no default); one kill switch always wins; and the environment is read
exactly once, when the registry is constructed — never inside the adapter's
call path.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from gateway.weather.adapter import (
    DEFAULT_CALL_TIMEOUT_S,
    OpenMeteoWeatherAdapter,
    WeatherCircuitBreaker,
)
from gateway.weather.contracts import PROVIDER_ID, EvidenceKind
from gateway.weather.errors import WeatherGatewayError
from gateway.weather.transport import WeatherToolTransport

ENABLE_ENV_VAR = "TRIPWISE_OPEN_METEO_ENABLED"
KILL_SWITCH_ENV_VAR = "TRIPWISE_OPEN_METEO_KILL_SWITCH"
_TRUTHY = {"1", "true", "yes", "on"}


def _truthy(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUTHY


def _enabled_from_env(env: Mapping[str, str]) -> bool:
    """The kill switch overrides the enable flag unconditionally."""
    if _truthy(env, KILL_SWITCH_ENV_VAR):
        return False
    return _truthy(env, ENABLE_ENV_VAR)


class WeatherProviderRegistryEntry(BaseModel):
    provider_id: str = Field(min_length=1)
    enabled: bool = False
    allowed_profiles: set[Literal["student_noncommercial", "commercial_production"]]
    source_method: Literal["community_mcp"]
    live_data: bool = False
    monthly_cost_minor: int = Field(ge=0)
    evidence_kinds: set[EvidenceKind]


class WeatherProviderRegistry(BaseModel):
    entries: list[WeatherProviderRegistryEntry] = Field(default_factory=list)

    def select(self, *, active_profile: str) -> list[WeatherProviderRegistryEntry]:
        return [e for e in self.entries if e.enabled and active_profile in e.allowed_profiles]

    def get_entry(self, provider_id: str) -> WeatherProviderRegistryEntry:
        for entry in self.entries:
            if entry.provider_id == provider_id:
                return entry
        raise WeatherGatewayError("provider_disabled", "unknown weather provider_id")


def get_default_weather_registry(env: Mapping[str, str] | None = None) -> WeatherProviderRegistry:
    """Build the default registry. ``env`` defaults to the process environment,
    snapshotted here and nowhere else."""
    source = os.environ if env is None else env
    return WeatherProviderRegistry(
        entries=[
            WeatherProviderRegistryEntry(
                provider_id=PROVIDER_ID,
                enabled=_enabled_from_env(source),
                # Open-Meteo's free API is non-commercial only: student profile only.
                allowed_profiles={"student_noncommercial"},
                source_method="community_mcp",
                live_data=True,
                monthly_cost_minor=0,
                evidence_kinds={
                    "current_observation",
                    "near_term_forecast",
                    "historical_observation",
                    "climate_summary",
                },
            )
        ]
    )


def build_weather_adapter(
    registry: WeatherProviderRegistry,
    *,
    active_profile: str,
    transport: WeatherToolTransport,
    budget: Any,
    plan_id: str,
    now: Callable[[], datetime],
    circuit_breaker: WeatherCircuitBreaker | None = None,
    call_timeout_s: float = DEFAULT_CALL_TIMEOUT_S,
) -> OpenMeteoWeatherAdapter:
    selected = any(
        e.provider_id == PROVIDER_ID for e in registry.select(active_profile=active_profile)
    )
    return OpenMeteoWeatherAdapter(
        transport=transport,
        budget=budget,
        plan_id=plan_id,
        now=now,
        enabled=selected,
        circuit_breaker=circuit_breaker,
        call_timeout_s=call_timeout_s,
    )
