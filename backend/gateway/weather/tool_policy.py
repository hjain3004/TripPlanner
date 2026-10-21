"""Frozen, code-owned Open-Meteo MCP tool policy (G4).

Two layers, both fail-closed and both applied by *every* transport before any
dispatch:

1. ``assert_tool_allowed`` — only the three read-only weather tools may be
   called. Anything else, including every storage/SQL (``dataframe_*``) tool
   and every tool the upstream server happens to advertise, is refused.
2. ``validate_tool_call`` — the arguments must be exactly the fixed, bounded
   shape produced by ``build_tool_call``: known keys only, numeric
   coordinates in range, variables drawn from a per-tool allowlist, units and
   timezone pinned, a single documented model pinned. Arguments are never
   model-controlled and never contain a URL, SQL, path, or storage token.

Tool availability reported by a server never authorizes a call (spec 06
Tier F-P: no dynamic provider/MCP discovery).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

from gateway.weather.contracts import (
    CLIMATE_EARLIEST,
    CLIMATE_LATEST,
    HISTORICAL_EARLIEST,
    MAX_CLIMATE_SPAN_DAYS,
    MAX_FORECAST_DAYS,
    MAX_HISTORICAL_SPAN_DAYS,
    MAX_VARIABLES_PER_CALL,
    ClimateRequest,
    CurrentAndForecastRequest,
    HistoricalRequest,
    WeatherRequest,
    check_window,
)
from gateway.weather.errors import WeatherGatewayError

FORECAST_TOOL = "openmeteo_get_forecast"
HISTORICAL_TOOL = "openmeteo_get_historical"
CLIMATE_TOOL = "openmeteo_get_climate"

ALLOWED_TOOLS: frozenset[str] = frozenset({FORECAST_TOOL, HISTORICAL_TOOL, CLIMATE_TOOL})

DENIED_TOOLS: frozenset[str] = frozenset(
    {
        # Storage / SQL surface of the upstream server (DataCanvas + DuckDB).
        "openmeteo_dataframe_query",
        "openmeteo_dataframe_describe",
        "openmeteo_dataframe_drop",
        # Real upstream tools that are read-only but outside the reviewed set.
        "openmeteo_search_locations",  # free-text geocoding query; coordinates are bounded inputs
        "openmeteo_get_elevation",
        "openmeteo_get_marine",
        "openmeteo_get_air_quality",
        "openmeteo_get_ensemble",
        "openmeteo_get_flood",
    }
)

# Variable allowlists. The union per call is capped at MAX_VARIABLES_PER_CALL
# (Open-Meteo bills >10 variables as more than one API call).
CURRENT_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "wind_speed_10m",
)
FORECAST_DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
)
HISTORICAL_DAILY_VARIABLES = (
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "wind_speed_10m_max",
)
CLIMATE_DAILY_VARIABLES = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")

# One documented model per dataset, pinned so the response has provenance and
# unsuffixed columns (the upstream catalog's names; ERA5 lags ~5 days).
PINNED_ARCHIVE_MODEL = "era5"
PINNED_CLIMATE_MODEL = "MRI_AGCM3_2_S"

_UNITS = {
    "temperature_unit": "celsius",
    "wind_speed_unit": "kmh",
    "precipitation_unit": "mm",
    "timezone": "auto",
}
_COMMON_KEYS = frozenset({"latitude", "longitude", *_UNITS})


def assert_tool_allowed(tool_name: str) -> None:
    if tool_name in ALLOWED_TOOLS:
        return
    raise WeatherGatewayError(
        "permission_denied", "weather tool is not in the reviewed read-only allowlist"
    )


def build_tool_call(request: WeatherRequest) -> tuple[str, dict[str, Any]]:
    """Map a typed request to the one fixed, bounded MCP argument shape."""
    base: dict[str, Any] = {
        "latitude": request.location.latitude,
        "longitude": request.location.longitude,
        **_UNITS,
    }
    if isinstance(request, CurrentAndForecastRequest):
        args = {
            **base,
            "daily_variables": list(FORECAST_DAILY_VARIABLES),
            "forecast_days": request.forecast_days,
            "past_days": 0,
        }
        if request.include_current:
            args["current_variables"] = list(CURRENT_VARIABLES)
        return FORECAST_TOOL, args
    if isinstance(request, HistoricalRequest):
        return HISTORICAL_TOOL, {
            **base,
            "start_date": request.start_date.isoformat(),
            "end_date": request.end_date.isoformat(),
            "daily_variables": list(HISTORICAL_DAILY_VARIABLES),
            "models": [PINNED_ARCHIVE_MODEL],
        }
    assert isinstance(request, ClimateRequest)
    return CLIMATE_TOOL, {
        **base,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "daily_variables": list(CLIMATE_DAILY_VARIABLES),
        "models": [PINNED_CLIMATE_MODEL],
    }


def _bad(message: str) -> WeatherGatewayError:
    return WeatherGatewayError("invalid_request", message)


def _number(value: Any, name: str, lo: float, hi: float) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _bad(f"{name} must be a number")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise _bad(f"{name} is out of range")


def _variables(args: dict[str, Any], key: str, allowed: tuple[str, ...], *, required: bool) -> int:
    if key not in args:
        if required:
            raise _bad(f"{key} is required")
        return 0
    values = args[key]
    if not isinstance(values, list) or (required and not values):
        raise _bad(f"{key} must be a non-empty list")
    if not all(isinstance(v, str) for v in values) or len(set(values)) != len(values):
        raise _bad(f"{key} must be unique strings")
    if not set(values) <= set(allowed):
        raise WeatherGatewayError("permission_denied", f"{key} contains a non-allowlisted variable")
    return len(values)


def _date(value: Any, name: str) -> date:
    if not isinstance(value, str):
        raise _bad(f"{name} must be an ISO date string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _bad(f"{name} must be an ISO date string") from exc


def validate_tool_call(tool_name: str, arguments: dict[str, Any]) -> None:
    """Validate a tool call against the fixed policy. Raises on any deviation."""
    assert_tool_allowed(tool_name)

    if tool_name == FORECAST_TOOL:
        allowed = _COMMON_KEYS | {
            "current_variables",
            "daily_variables",
            "forecast_days",
            "past_days",
        }
    else:
        allowed = _COMMON_KEYS | {"start_date", "end_date", "daily_variables", "models"}
    extra = set(arguments) - allowed
    if extra:
        raise WeatherGatewayError(
            "permission_denied", f"{len(extra)} unexpected argument(s) are not permitted"
        )

    for key in ("latitude", "longitude"):
        if key not in arguments:
            raise _bad(f"{key} is required")
    _number(arguments["latitude"], "latitude", -90, 90)
    _number(arguments["longitude"], "longitude", -180, 180)
    for key, expected in _UNITS.items():
        if arguments.get(key) != expected:
            raise _bad(f"{key} is pinned")

    if tool_name == FORECAST_TOOL:
        days = arguments.get("forecast_days")
        if (
            isinstance(days, bool)
            or not isinstance(days, int)
            or not 1 <= days <= MAX_FORECAST_DAYS
        ):
            raise _bad("forecast_days is out of range")
        if arguments.get("past_days") != 0:
            raise _bad("past_days is pinned to 0")
        total = _variables(arguments, "current_variables", CURRENT_VARIABLES, required=False)
        total += _variables(arguments, "daily_variables", FORECAST_DAILY_VARIABLES, required=True)
    else:
        is_history = tool_name == HISTORICAL_TOOL
        start = _date(arguments.get("start_date"), "start_date")
        end = _date(arguments.get("end_date"), "end_date")
        try:
            check_window(
                start,
                end,
                earliest=HISTORICAL_EARLIEST if is_history else CLIMATE_EARLIEST,
                latest=None if is_history else CLIMATE_LATEST,
                max_days=MAX_HISTORICAL_SPAN_DAYS if is_history else MAX_CLIMATE_SPAN_DAYS,
            )
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        pinned = PINNED_ARCHIVE_MODEL if is_history else PINNED_CLIMATE_MODEL
        if arguments.get("models") != [pinned]:
            raise _bad("models is pinned")
        total = _variables(
            arguments,
            "daily_variables",
            HISTORICAL_DAILY_VARIABLES if is_history else CLIMATE_DAILY_VARIABLES,
            required=True,
        )

    if total > MAX_VARIABLES_PER_CALL:
        raise _bad("too many variables requested in one call")
