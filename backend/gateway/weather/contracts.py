"""Weather-context contracts (G4).

Weather is *contextual evidence* — it is not travel inventory (no price, no
availability) and never financial evidence. Nothing here imports ``core`` or
any money type, and nothing defined here may enter reward/fee/points
arithmetic; a structural test (``test_weather_boundary``) enforces that.

Four evidence kinds are kept deliberately distinct and are never promoted
into one another:

* ``current_observation``   — model-derived conditions "right now" (15-minute
  current block). Not a station measurement.
* ``near_term_forecast``    — daily forecast within the provider's genuine
  horizon (today .. today + 15 days). The only kind with ``is_forecast``.
* ``historical_observation``— reanalysis (archive) for past dates, beyond the
  archive's ~5-day lag.
* ``climate_summary``       — CMIP6 climate *projection* aggregated over a
  window. Never a forecast: it is only requestable for dates strictly beyond
  the forecast horizon, is reduced to window statistics (no per-day series
  that could pass for a forecast), is always ``confidence="low"`` and
  ``needs_verification=True``, and carries a fixed "not a forecast" caveat.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from typing import Annotated, Final, Literal, Self
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from gateway.weather.errors import ErrorCode, WeatherGatewayError

PROVIDER_ID = "open_meteo"
UPSTREAM_SERVER_NAME = "open-meteo-mcp-server"
UPSTREAM_SERVER_VERSION = "0.4.1"
UPSTREAM_SERVER_ID = f"{UPSTREAM_SERVER_NAME}@{UPSTREAM_SERVER_VERSION}"

ATTRIBUTION_TEXT = "Weather data by Open-Meteo.com (CC BY 4.0)"
ATTRIBUTION_URL = "https://open-meteo.com/"
LICENSE_ID: Final = "CC-BY-4.0"
TERMS_VERSION = "open-meteo-terms@2026-10-14"
UNAVAILABLE_MESSAGE = "Weather context unavailable"

# --- Bounds -----------------------------------------------------------------
MAX_FORECAST_DAYS = 16
FORECAST_LAST_DAY_OFFSET = MAX_FORECAST_DAYS - 1  # forecast covers today .. today + 15
MAX_HISTORICAL_SPAN_DAYS = 31
MAX_CLIMATE_SPAN_DAYS = 31
HISTORICAL_LAG_DAYS = 7  # archive (ERA5) lags ~5 days; 2 days of margin
HISTORICAL_EARLIEST = date(1940, 1, 1)
CLIMATE_EARLIEST = date(1950, 1, 1)
CLIMATE_LATEST = date(2050, 12, 31)
COORD_DECIMALS = 2
MAX_VARIABLES_PER_CALL = 10  # Open-Meteo counts >10 variables as >1 API call
MAX_RESPONSE_BYTES = 200_000
MAX_NOTES = 4

EvidenceKind = Literal[
    "current_observation", "near_term_forecast", "historical_observation", "climate_summary"
]
RequestKind = Literal["current_and_forecast", "historical", "climate"]
EvidenceOrigin = Literal["live", "fixture_synthetic", "fixture_captured"]
Confidence = Literal["high", "medium", "low"]

EVIDENCE_LABELS: dict[str, str] = {
    "current_observation": "Current conditions (model-derived)",
    "near_term_forecast": "Forecast",
    "historical_observation": "Past conditions (reanalysis)",
    "climate_summary": "Climate summary — not a forecast",
}
SOURCE_URLS: dict[str, str] = {
    "current_observation": "https://open-meteo.com/en/docs",
    "near_term_forecast": "https://open-meteo.com/en/docs",
    "historical_observation": "https://open-meteo.com/en/docs/historical-weather-api",
    "climate_summary": "https://open-meteo.com/en/docs/climate-api",
}
CLIMATE_CAVEAT = (
    "Climate summary — not a forecast. Window statistics from a climate-model projection; "
    "it says nothing reliable about the weather on any specific day."
)
_ALLOWED_SOURCE_HOSTS = frozenset(
    {
        "open-meteo.com",
        "api.open-meteo.com",
        "archive-api.open-meteo.com",
        "climate-api.open-meteo.com",
    }
)
_LABEL_RE = re.compile(r"^[A-Za-z0-9 ,.'\-]{1,80}$")


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def check_window(
    start: date, end: date, *, earliest: date, latest: date | None, max_days: int
) -> None:
    """Shared window rule for request models and the tool-call validator."""
    if end < start:
        raise ValueError("end_date is before start_date")
    if start < earliest:
        raise ValueError("start_date is before the dataset's coverage")
    if latest is not None and end > latest:
        raise ValueError("end_date is after the dataset's coverage")
    if (end - start).days + 1 > max_days:
        raise ValueError(f"window exceeds {max_days} days")


# --- Requests ---------------------------------------------------------------
class WeatherLocation(_Model):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    label: str | None = None

    @field_validator("latitude", "longitude")
    @classmethod
    def _finite_and_rounded(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("coordinate must be finite")
        return round(value, COORD_DECIMALS)

    @field_validator("label")
    @classmethod
    def _plain_label(cls, value: str | None) -> str | None:
        if value is not None and not _LABEL_RE.fullmatch(value):
            raise ValueError("label must be short plain text")
        return value


class CurrentAndForecastRequest(_Model):
    kind: Literal["current_and_forecast"] = "current_and_forecast"
    location: WeatherLocation
    forecast_days: int = Field(ge=1, le=MAX_FORECAST_DAYS)
    include_current: bool = True


class HistoricalRequest(_Model):
    kind: Literal["historical"] = "historical"
    location: WeatherLocation
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _window(self) -> Self:
        check_window(
            self.start_date,
            self.end_date,
            earliest=HISTORICAL_EARLIEST,
            latest=None,
            max_days=MAX_HISTORICAL_SPAN_DAYS,
        )
        return self


class ClimateRequest(_Model):
    kind: Literal["climate"] = "climate"
    location: WeatherLocation
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _window(self) -> Self:
        check_window(
            self.start_date,
            self.end_date,
            earliest=CLIMATE_EARLIEST,
            latest=CLIMATE_LATEST,
            max_days=MAX_CLIMATE_SPAN_DAYS,
        )
        return self


WeatherRequest = Annotated[
    CurrentAndForecastRequest | HistoricalRequest | ClimateRequest, Field(discriminator="kind")
]


def assert_date_semantics(request: WeatherRequest, *, today: date) -> None:
    """Reject requests whose dates do not match the evidence kind they ask for.

    ``today`` is injected (the adapter passes its injected clock's date); this
    function never reads the wall clock.
    """
    if isinstance(request, HistoricalRequest):
        if request.end_date > today - timedelta(days=HISTORICAL_LAG_DAYS):
            raise WeatherGatewayError(
                "invalid_request",
                "historical observations are only available for dates older than the "
                "archive lag; recent or future dates are not historical",
            )
    elif isinstance(request, ClimateRequest) and request.start_date <= today + timedelta(
        days=FORECAST_LAST_DAY_OFFSET
    ):
        raise WeatherGatewayError(
            "invalid_request",
            "a climate summary may only describe dates beyond the forecast horizon; "
            "it must never stand in for a forecast or an observation",
        )


class WeatherRequestPlan(_Model):
    requests: tuple[WeatherRequest, ...]
    notes: tuple[str, ...] = ()


def plan_weather_requests(
    location: WeatherLocation, trip_start: date, trip_end: date, *, today: date
) -> WeatherRequestPlan:
    """Deterministically choose which evidence kinds may describe a trip window.

    Dates inside the forecast horizon get a forecast; dates beyond it get a
    (clearly labelled, window-aggregated) climate summary — never a forecast;
    past dates get a historical observation only once the archive has caught up.
    """
    if trip_end < trip_start:
        raise WeatherGatewayError("invalid_request", "trip_end is before trip_start")
    horizon_last = today + timedelta(days=FORECAST_LAST_DAY_OFFSET)
    requests: list[WeatherRequest] = []
    notes: list[str] = []

    if trip_end >= today and trip_start <= horizon_last:
        last = min(trip_end, horizon_last)
        requests.append(
            CurrentAndForecastRequest(
                location=location,
                forecast_days=(last - today).days + 1,
                include_current=trip_start <= today + timedelta(days=1),
            )
        )

    if trip_end > horizon_last:
        start = max(trip_start, horizon_last + timedelta(days=1))
        end = min(trip_end, start + timedelta(days=MAX_CLIMATE_SPAN_DAYS - 1), CLIMATE_LATEST)
        if end < trip_end:
            notes.append("climate_summary_truncated_to_31_days")
        if start <= CLIMATE_LATEST:
            requests.append(ClimateRequest(location=location, start_date=start, end_date=end))
            notes.append("beyond_forecast_horizon_climate_summary_only")

    if trip_end < today:
        if trip_end <= today - timedelta(days=HISTORICAL_LAG_DAYS):
            start = max(trip_start, trip_end - timedelta(days=MAX_HISTORICAL_SPAN_DAYS - 1))
            requests.append(
                HistoricalRequest(location=location, start_date=start, end_date=trip_end)
            )
        else:
            notes.append("recent_past_unavailable")

    return WeatherRequestPlan(requests=tuple(requests), notes=tuple(notes))


# --- Evidence ---------------------------------------------------------------
class WeatherEvidenceMeta(_Model):
    """Provenance for every weather fact (CLAUDE.md non-negotiable 3)."""

    provider_id: Literal["open_meteo"]
    kind: EvidenceKind
    label: str
    origin: EvidenceOrigin
    source_url: str
    retrieved_at: datetime
    last_verified: datetime
    valid_from: datetime
    valid_to: datetime
    attribution: str
    attribution_url: str
    license: Literal["CC-BY-4.0"]
    terms_version: str
    confidence: Confidence
    needs_verification: bool
    verified_by: str
    upstream_server: str
    notes: tuple[str, ...] = Field(default=(), max_length=MAX_NOTES)

    @property
    def is_forecast(self) -> bool:
        return self.kind == "near_term_forecast"

    @field_validator("source_url")
    @classmethod
    def _open_meteo_https(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_SOURCE_HOSTS:
            raise ValueError("source_url must be an https Open-Meteo URL")
        return value

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        for name in ("retrieved_at", "last_verified", "valid_from", "valid_to"):
            if getattr(self, name).tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.valid_to < self.valid_from:
            raise ValueError("valid_to is before valid_from")
        if self.label != EVIDENCE_LABELS[self.kind]:
            raise ValueError("label does not match evidence kind")
        if self.attribution != ATTRIBUTION_TEXT or self.attribution_url != ATTRIBUTION_URL:
            raise ValueError("attribution is fixed by the provider's licence")
        if self.kind == "climate_summary" and (
            not self.needs_verification or self.confidence != "low"
        ):
            raise ValueError("a climate summary is always low-confidence and needs verification")
        if self.origin != "live" and not self.needs_verification:
            raise ValueError("fixture evidence always needs verification")
        return self


class WeatherPlace(_Model):
    """Grid point the provider actually answered for (it snaps coordinates)."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    elevation_m: float = Field(ge=-500, le=9000)
    timezone: str
    utc_offset_seconds: int | None = Field(default=None, ge=-50_400, le=50_400)


class DailyWeather(_Model):
    day: date
    weather_code: int | None = Field(default=None, ge=0, le=99)
    temperature_max_c: float | None = Field(default=None, ge=-90, le=60)
    temperature_min_c: float | None = Field(default=None, ge=-90, le=60)
    precipitation_sum_mm: float | None = Field(default=None, ge=0, le=2000)
    precipitation_probability_max_pct: float | None = Field(default=None, ge=0, le=100)
    wind_speed_max_kmh: float | None = Field(default=None, ge=0, le=500)


def _kind_matches(kind: str, meta: WeatherEvidenceMeta) -> None:
    if meta.kind != kind:
        raise ValueError("evidence kind does not match its provenance kind")


class CurrentObservation(_Model):
    kind: Literal["current_observation"] = "current_observation"
    meta: WeatherEvidenceMeta
    place: WeatherPlace
    observed_at: datetime
    interval_seconds: int = Field(ge=0, le=3600)
    temperature_c: float | None = Field(default=None, ge=-90, le=60)
    relative_humidity_pct: float | None = Field(default=None, ge=0, le=100)
    precipitation_mm: float | None = Field(default=None, ge=0, le=2000)
    weather_code: int | None = Field(default=None, ge=0, le=99)
    wind_speed_kmh: float | None = Field(default=None, ge=0, le=500)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _kind_matches(self.kind, self.meta)
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class NearTermForecast(_Model):
    kind: Literal["near_term_forecast"] = "near_term_forecast"
    meta: WeatherEvidenceMeta
    place: WeatherPlace
    days: tuple[DailyWeather, ...] = Field(min_length=1, max_length=MAX_FORECAST_DAYS)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _kind_matches(self.kind, self.meta)
        return self


class HistoricalObservation(_Model):
    kind: Literal["historical_observation"] = "historical_observation"
    meta: WeatherEvidenceMeta
    place: WeatherPlace
    model: str
    days: tuple[DailyWeather, ...] = Field(min_length=1, max_length=MAX_HISTORICAL_SPAN_DAYS)

    @model_validator(mode="after")
    def _check(self) -> Self:
        _kind_matches(self.kind, self.meta)
        return self


class ClimateSummary(_Model):
    kind: Literal["climate_summary"] = "climate_summary"
    meta: WeatherEvidenceMeta
    place: WeatherPlace
    window_start: date
    window_end: date
    sample_days: int = Field(ge=1, le=MAX_CLIMATE_SPAN_DAYS)
    model: str
    mean_temperature_max_c: float | None = Field(default=None, ge=-90, le=60)
    mean_temperature_min_c: float | None = Field(default=None, ge=-90, le=60)
    total_precipitation_mm: float | None = Field(default=None, ge=0, le=62_000)
    caveat: str = CLIMATE_CAVEAT

    @model_validator(mode="after")
    def _check(self) -> Self:
        _kind_matches(self.kind, self.meta)
        if self.caveat != CLIMATE_CAVEAT:
            raise ValueError("the climate caveat is fixed")
        if self.window_end < self.window_start:
            raise ValueError("window_end is before window_start")
        return self


WeatherEvidence = Annotated[
    CurrentObservation | NearTermForecast | HistoricalObservation | ClimateSummary,
    Field(discriminator="kind"),
]


class WeatherUnavailable(_Model):
    code: ErrorCode
    request_kind: RequestKind
    message: str = UNAVAILABLE_MESSAGE

    @field_validator("message")
    @classmethod
    def _fixed(cls, value: str) -> str:
        if value != UNAVAILABLE_MESSAGE:
            raise ValueError("the unavailable message is fixed")
        return value


class WeatherContextOutcome(_Model):
    """What planning receives: either evidence, or "weather context unavailable".

    Never raises into the caller and never carries a fabricated forecast.
    """

    status: Literal["available", "unavailable"]
    evidence: tuple[WeatherEvidence, ...] = ()
    unavailable: WeatherUnavailable | None = None
    attribution: str = ATTRIBUTION_TEXT
    attribution_url: str = ATTRIBUTION_URL

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.status == "available":
            if not self.evidence or self.unavailable is not None:
                raise ValueError("available outcomes carry evidence and no unavailable marker")
        elif self.evidence or self.unavailable is None:
            raise ValueError("unavailable outcomes carry no evidence and an unavailable marker")
        if self.attribution != ATTRIBUTION_TEXT or self.attribution_url != ATTRIBUTION_URL:
            raise ValueError("attribution is fixed by the provider's licence")
        return self
