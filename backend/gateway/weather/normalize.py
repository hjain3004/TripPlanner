"""Strict normalization of Open-Meteo MCP tool payloads into typed evidence (G4).

Design rules:

* The payload is *data*. Only whitelisted keys are read; unknown keys, blocks
  that were not requested (e.g. ``hourly``) and unknown row keys are ignored
  and never copied to the output.
* Every number is range-checked and must be finite; strings that must be
  identifiers (timezone) match a strict pattern; the only free text that
  survives (the advisory ``notice``) goes through the sanitizer.
* Rejection messages name the offending *field* only — never provider values.
* Date semantics are enforced twice: ``assert_date_semantics`` on the request
  and structural checks on what the provider returned (a "forecast" dated in
  the past, a "current" observation that is stale or from the future, a
  climate payload carrying a ``current`` block, rows outside the window).
* No weather value is ever converted to, or combined with, a money quantity.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from gateway.weather.contracts import (
    ATTRIBUTION_TEXT,
    ATTRIBUTION_URL,
    EVIDENCE_LABELS,
    FORECAST_LAST_DAY_OFFSET,
    LICENSE_ID,
    MAX_RESPONSE_BYTES,
    PROVIDER_ID,
    SOURCE_URLS,
    TERMS_VERSION,
    UPSTREAM_SERVER_ID,
    ClimateRequest,
    ClimateSummary,
    Confidence,
    CurrentAndForecastRequest,
    CurrentObservation,
    DailyWeather,
    EvidenceKind,
    EvidenceOrigin,
    HistoricalObservation,
    HistoricalRequest,
    NearTermForecast,
    WeatherEvidence,
    WeatherEvidenceMeta,
    WeatherLocation,
    WeatherPlace,
    WeatherRequest,
    assert_date_semantics,
)
from gateway.weather.errors import WeatherGatewayError
from gateway.weather.sanitize import sanitize_provider_text
from gateway.weather.tool_policy import (
    CLIMATE_DAILY_VARIABLES,
    CURRENT_VARIABLES,
    FORECAST_DAILY_VARIABLES,
    HISTORICAL_DAILY_VARIABLES,
    PINNED_ARCHIVE_MODEL,
    PINNED_CLIMATE_MODEL,
)
from gateway.weather.transport import ToolResult

_TZ_RE = re.compile(r"^[A-Za-z0-9_+\-/]{1,64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$")
_FORBIDDEN_KEYS = ("canvas_id", "table_name")
_MAX_COORD_DELTA_DEG = 1.0  # Open-Meteo snaps to a grid point; anything farther is wrong
_CURRENT_MAX_AGE = timedelta(hours=6)
_CURRENT_MAX_FUTURE = timedelta(hours=1)
_MEDIUM_CONFIDENCE_LEAD_DAYS = 7

_UNIT_OK: dict[str, frozenset[str]] = {
    "temperature_2m": frozenset({"°C"}),
    "temperature_2m_max": frozenset({"°C"}),
    "temperature_2m_min": frozenset({"°C"}),
    "relative_humidity_2m": frozenset({"%"}),
    "precipitation": frozenset({"mm"}),
    "precipitation_sum": frozenset({"mm"}),
    "precipitation_probability_max": frozenset({"%"}),
    "weather_code": frozenset({"wmo code"}),
    "wind_speed_10m": frozenset({"km/h"}),
    "wind_speed_10m_max": frozenset({"km/h"}),
}


def _invalid(message: str) -> WeatherGatewayError:
    return WeatherGatewayError("invalid_response", message)


# --- primitive parsers -------------------------------------------------------
def _obj(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _invalid(f"{name} is not an object")
    return value


def _num(
    row: dict[str, Any], key: str, lo: float, hi: float, *, required: bool = False
) -> float | None:
    value = row.get(key)
    if value is None:
        if required:
            raise _invalid(f"{key} is missing")
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _invalid(f"{key} is not a number")
    if not math.isfinite(value) or not lo <= value <= hi:
        raise _invalid(f"{key} is out of range")
    return float(value)


def _int_in(row: dict[str, Any], key: str, lo: int, hi: int) -> int | None:
    value = _num(row, key, lo, hi)
    if value is None:
        return None
    if value != int(value):
        raise _invalid(f"{key} is not an integer")
    return int(value)


def _day(value: Any, name: str) -> date:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        raise _invalid(f"{name} is not an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _invalid(f"{name} is not a real date") from exc


# --- shared payload checks ---------------------------------------------------
def _validated_payload(raw: Any) -> dict[str, Any]:
    payload = _obj(raw, "payload")
    try:
        size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise _invalid("payload is not JSON-serialisable") from exc
    if size > MAX_RESPONSE_BYTES:
        raise _invalid("payload exceeds the response bound")
    for key in _FORBIDDEN_KEYS:
        if key in payload:
            raise _invalid(f"payload carries a storage artifact ({key})")
    if payload.get("truncated") is True:
        raise _invalid("payload is truncated")
    return payload


def _place(
    payload: dict[str, Any], location: WeatherLocation, *, need_offset: bool
) -> WeatherPlace:
    lat = _num(payload, "latitude", -90, 90, required=True)
    lon = _num(payload, "longitude", -180, 180, required=True)
    elevation = _num(payload, "elevation", -500, 9000, required=True)
    assert lat is not None and lon is not None and elevation is not None
    lon_delta = abs(lon - location.longitude)
    if abs(lat - location.latitude) > _MAX_COORD_DELTA_DEG or min(lon_delta, 360 - lon_delta) > (
        _MAX_COORD_DELTA_DEG
    ):
        raise _invalid("the provider answered for a different location")
    tz = payload.get("timezone")
    if not isinstance(tz, str) or not _TZ_RE.fullmatch(tz):
        raise _invalid("timezone is not a plain identifier")
    offset = _int_in(payload, "utc_offset_seconds", -50_400, 50_400)
    if need_offset and offset is None:
        raise _invalid("utc_offset_seconds is missing")
    return WeatherPlace(
        latitude=lat, longitude=lon, elevation_m=elevation, timezone=tz, utc_offset_seconds=offset
    )


def _check_units(payload: dict[str, Any], units_key: str, variables: tuple[str, ...]) -> None:
    units = _obj(payload.get(units_key), units_key)
    for variable in variables:
        if units.get(variable) not in _UNIT_OK[variable]:
            raise _invalid(f"{units_key} has an unexpected unit for {variable}")


def _rows(payload: dict[str, Any], max_rows: int) -> list[dict[str, Any]]:
    rows = payload.get("daily")
    if not isinstance(rows, list) or not 1 <= len(rows) <= max_rows:
        raise _invalid("daily rows are missing or exceed the permitted count")
    return [_obj(row, "daily row") for row in rows]


def _daily(row: dict[str, Any]) -> DailyWeather:
    return DailyWeather(
        day=_day(row.get("time"), "daily time"),
        weather_code=_int_in(row, "weather_code", 0, 99),
        temperature_max_c=_num(row, "temperature_2m_max", -90, 60),
        temperature_min_c=_num(row, "temperature_2m_min", -90, 60),
        precipitation_sum_mm=_num(row, "precipitation_sum", 0, 2000),
        precipitation_probability_max_pct=_num(row, "precipitation_probability_max", 0, 100),
        wind_speed_max_kmh=_num(row, "wind_speed_10m_max", 0, 500),
    )


def _notes(
    payload: dict[str, Any], origin: EvidenceOrigin, *, date_granular: bool
) -> tuple[str, ...]:
    notes: list[str] = []
    if origin == "fixture_synthetic":
        notes.append("Fixture replay (authored synthetic) — not live provider output.")
    elif origin == "fixture_captured":
        notes.append("Fixture replay (sanitized capture) — not live provider output.")
    if date_granular:
        notes.append("Validity bounds are date-granular (UTC day boundaries).")
    notice = payload.get("notice")
    if isinstance(notice, str):
        cleaned = sanitize_provider_text(notice)
        if cleaned:
            notes.append(cleaned)
    return tuple(notes)


def _verified_by(origin: EvidenceOrigin) -> str:
    if origin == "live":
        return f"provider:{UPSTREAM_SERVER_ID} (unreviewed model output)"
    return (
        "fixture:authored_synthetic"
        if origin == "fixture_synthetic"
        else "fixture:sanitized_capture"
    )


def _meta(
    kind: EvidenceKind,
    *,
    origin: EvidenceOrigin,
    now: datetime,
    valid_from: datetime,
    valid_to: datetime,
    confidence: Confidence,
    notes: tuple[str, ...],
) -> WeatherEvidenceMeta:
    return WeatherEvidenceMeta(
        provider_id=PROVIDER_ID,
        kind=kind,
        label=EVIDENCE_LABELS[kind],
        origin=origin,
        source_url=SOURCE_URLS[kind],
        retrieved_at=now,
        last_verified=now,
        valid_from=valid_from,
        valid_to=valid_to,
        attribution=ATTRIBUTION_TEXT,
        attribution_url=ATTRIBUTION_URL,
        license=LICENSE_ID,
        terms_version=TERMS_VERSION,
        confidence=confidence,
        needs_verification=origin != "live" or kind == "climate_summary",
        verified_by=_verified_by(origin),
        upstream_server=UPSTREAM_SERVER_ID,
        notes=notes,
    )


def _end_of_day(day: date, tz: timezone) -> datetime:
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=tz)


# --- per-kind normalizers ----------------------------------------------------
def _forecast(
    request: CurrentAndForecastRequest,
    payload: dict[str, Any],
    origin: EvidenceOrigin,
    now: datetime,
) -> tuple[WeatherEvidence, ...]:
    place = _place(payload, request.location, need_offset=True)
    assert place.utc_offset_seconds is not None
    tz = timezone(timedelta(seconds=place.utc_offset_seconds))
    local_today = now.astimezone(tz).date()

    rows = _rows(payload, request.forecast_days)
    _check_units(payload, "daily_units", FORECAST_DAILY_VARIABLES)
    days = tuple(_daily(row) for row in rows)
    first = days[0].day
    if first != local_today:
        raise _invalid("forecast does not start on the current local date")
    for i, day in enumerate(days):
        if day.day != first + timedelta(days=i):
            raise _invalid("forecast days are not contiguous and ascending")
    last = days[-1].day
    if last > local_today + timedelta(days=FORECAST_LAST_DAY_OFFSET + 1):
        raise _invalid("forecast extends beyond the provider's horizon")

    notes = _notes(payload, origin, date_granular=False)
    lead_days = (last - local_today).days
    forecast_confidence: Confidence = (
        "medium" if lead_days <= _MEDIUM_CONFIDENCE_LEAD_DAYS else "low"
    )
    forecast = NearTermForecast(
        meta=_meta(
            "near_term_forecast",
            origin=origin,
            now=now,
            valid_from=datetime(first.year, first.month, first.day, tzinfo=tz),
            valid_to=_end_of_day(last, tz),
            confidence=forecast_confidence,
            notes=notes,
        ),
        place=place,
        days=days,
    )
    if not request.include_current:
        return (forecast,)

    current = _obj(payload.get("current"), "current")
    _check_units(payload, "current_units", CURRENT_VARIABLES)
    time_text = current.get("time")
    if not isinstance(time_text, str) or not _DATETIME_RE.fullmatch(time_text):
        raise _invalid("current time is not an ISO local datetime")
    try:
        observed_at = datetime.fromisoformat(time_text).replace(tzinfo=tz)
    except ValueError as exc:
        raise _invalid("current time is not a real datetime") from exc
    if not now - _CURRENT_MAX_AGE <= observed_at <= now + _CURRENT_MAX_FUTURE:
        raise _invalid("current observation time is implausible for 'now'")
    interval = _int_in(current, "interval", 0, 3600)
    if interval is None:
        raise _invalid("current interval is missing")
    observation = CurrentObservation(
        meta=_meta(
            "current_observation",
            origin=origin,
            now=now,
            valid_from=observed_at,
            valid_to=observed_at + timedelta(seconds=interval),
            confidence="medium",
            notes=notes,
        ),
        place=place,
        observed_at=observed_at,
        interval_seconds=interval,
        temperature_c=_num(current, "temperature_2m", -90, 60),
        relative_humidity_pct=_num(current, "relative_humidity_2m", 0, 100),
        precipitation_mm=_num(current, "precipitation", 0, 2000),
        weather_code=_int_in(current, "weather_code", 0, 99),
        wind_speed_kmh=_num(current, "wind_speed_10m", 0, 500),
    )
    return (observation, forecast)


def _windowed_days(
    payload: dict[str, Any], start: date, end: date, variables: tuple[str, ...], model: str
) -> tuple[DailyWeather, ...]:
    if "current" in payload or "current_units" in payload:
        raise _invalid("a dated-window payload must not carry a current block")
    if payload.get("models") != [model]:
        raise _invalid("the provider did not confirm the pinned model")
    span = (end - start).days + 1
    rows = _rows(payload, span)
    _check_units(payload, "daily_units", variables)
    days = tuple(_daily(row) for row in rows)
    if len(days) != span:
        raise _invalid("daily rows do not cover the complete requested window")
    for offset, day in enumerate(days):
        if day.day != start + timedelta(days=offset):
            raise _invalid("daily rows do not cover the complete requested window")
    return days


def _historical(
    request: HistoricalRequest, payload: dict[str, Any], origin: EvidenceOrigin, now: datetime
) -> tuple[WeatherEvidence, ...]:
    place = _place(payload, request.location, need_offset=False)
    days = _windowed_days(
        payload,
        request.start_date,
        request.end_date,
        HISTORICAL_DAILY_VARIABLES,
        PINNED_ARCHIVE_MODEL,
    )
    first, last = days[0].day, days[-1].day
    return (
        HistoricalObservation(
            meta=_meta(
                "historical_observation",
                origin=origin,
                now=now,
                valid_from=datetime(first.year, first.month, first.day, tzinfo=UTC),
                valid_to=_end_of_day(last, UTC),
                confidence="medium",
                notes=_notes(payload, origin, date_granular=True),
            ),
            place=place,
            model=PINNED_ARCHIVE_MODEL,
            days=days,
        ),
    )


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def _complete_metric(values: list[float | None]) -> list[float]:
    """Return a metric series only when every requested day supplied it."""
    if any(value is None for value in values):
        return []
    return [value for value in values if value is not None]


def _climate(
    request: ClimateRequest, payload: dict[str, Any], origin: EvidenceOrigin, now: datetime
) -> tuple[WeatherEvidence, ...]:
    place = _place(payload, request.location, need_offset=False)
    days = _windowed_days(
        payload, request.start_date, request.end_date, CLIMATE_DAILY_VARIABLES, PINNED_CLIMATE_MODEL
    )
    first, last = days[0].day, days[-1].day
    highs = _complete_metric([d.temperature_max_c for d in days])
    lows = _complete_metric([d.temperature_min_c for d in days])
    rain = _complete_metric([d.precipitation_sum_mm for d in days])
    return (
        ClimateSummary(
            meta=_meta(
                "climate_summary",
                origin=origin,
                now=now,
                valid_from=datetime(first.year, first.month, first.day, tzinfo=UTC),
                valid_to=_end_of_day(last, UTC),
                confidence="low",
                notes=_notes(payload, origin, date_granular=True),
            ),
            place=place,
            window_start=first,
            window_end=last,
            sample_days=len(days),
            model=PINNED_CLIMATE_MODEL,
            mean_temperature_max_c=_mean(highs),
            mean_temperature_min_c=_mean(lows),
            total_precipitation_mm=round(sum(rain), 1) if rain else None,
        ),
    )


def normalize_tool_result(
    request: WeatherRequest, result: ToolResult, *, now: datetime
) -> tuple[WeatherEvidence, ...]:
    """Turn one tool payload into typed evidence, or raise ``WeatherGatewayError``.

    ``now`` is the injected clock; this function never reads the wall clock.
    """
    if now.tzinfo is None:
        raise WeatherGatewayError("invalid_request", "now must be timezone-aware")
    assert_date_semantics(request, today=now.astimezone(UTC).date())
    payload = _validated_payload(result.payload)
    if isinstance(request, CurrentAndForecastRequest):
        return _forecast(request, payload, result.origin, now)
    if isinstance(request, HistoricalRequest):
        return _historical(request, payload, result.origin, now)
    return _climate(request, payload, result.origin, now)
