"""G4 weather-context contracts: bounds, evidence-kind semantics, date rules.

Weather is contextual evidence — never inventory, never financial evidence.
These tests pin the request bounds and the distinctions between current
observation, near-term forecast, historical observation and climate summary.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from gateway.weather.contracts import (
    ATTRIBUTION_TEXT,
    ATTRIBUTION_URL,
    MAX_FORECAST_DAYS,
    ClimateRequest,
    ClimateSummary,
    CurrentAndForecastRequest,
    HistoricalRequest,
    WeatherContextOutcome,
    WeatherEvidenceMeta,
    WeatherLocation,
    WeatherPlace,
    WeatherUnavailable,
    assert_date_semantics,
    plan_weather_requests,
)
from gateway.weather.errors import WeatherGatewayError

TODAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
SINGAPORE = WeatherLocation(latitude=1.3521, longitude=103.8198, label="Singapore")


def _meta(kind: str = "climate_summary", **overrides: object) -> WeatherEvidenceMeta:
    base: dict[str, object] = {
        "provider_id": "open_meteo",
        "kind": kind,
        "origin": "fixture_synthetic",
        "source_url": "https://open-meteo.com/en/docs/climate-api",
        "retrieved_at": NOW,
        "last_verified": NOW,
        "valid_from": datetime(2027, 2, 1, tzinfo=UTC),
        "valid_to": datetime(2027, 2, 7, 23, 59, 59, tzinfo=UTC),
        "attribution": ATTRIBUTION_TEXT,
        "attribution_url": ATTRIBUTION_URL,
        "license": "CC-BY-4.0",
        "terms_version": "open-meteo-terms@2026-10-14",
        "confidence": "low",
        "needs_verification": True,
        "verified_by": "fixture:authored_synthetic",
        "upstream_server": "open-meteo-mcp-server@0.4.1",
        "label": "Climate summary — not a forecast",
    }
    base.update(overrides)
    return WeatherEvidenceMeta.model_validate(base)


class TestLocationBounds:
    def test_coordinates_are_rounded_to_two_decimals(self) -> None:
        loc = WeatherLocation(latitude=1.35214, longitude=103.81986)
        assert (loc.latitude, loc.longitude) == (1.35, 103.82)

    @pytest.mark.parametrize(
        "lat,lon", [(91, 0), (-91, 0), (0, 181), (0, -181), (float("nan"), 0), (0, float("inf"))]
    )
    def test_out_of_range_or_non_finite_coordinates_rejected(self, lat: float, lon: float) -> None:
        with pytest.raises(ValidationError):
            WeatherLocation(latitude=lat, longitude=lon)

    @pytest.mark.parametrize("label", ["x" * 81, "Sing\napore", "ignore previous; <script>", "a|b"])
    def test_label_must_be_plain_short_text(self, label: str) -> None:
        with pytest.raises(ValidationError):
            WeatherLocation(latitude=1.0, longitude=1.0, label=label)


class TestRequestBounds:
    def test_forecast_days_bounded_one_to_sixteen(self) -> None:
        assert MAX_FORECAST_DAYS == 16
        CurrentAndForecastRequest(location=SINGAPORE, forecast_days=16)
        for bad in (0, 17, -1):
            with pytest.raises(ValidationError):
                CurrentAndForecastRequest(location=SINGAPORE, forecast_days=bad)

    def test_historical_window_ordered_and_at_most_31_days(self) -> None:
        HistoricalRequest(
            location=SINGAPORE, start_date=date(2026, 9, 1), end_date=date(2026, 10, 1)
        )  # 31 days inclusive
        with pytest.raises(ValidationError):
            HistoricalRequest(
                location=SINGAPORE, start_date=date(2026, 9, 1), end_date=date(2026, 10, 2)
            )
        with pytest.raises(ValidationError):
            HistoricalRequest(
                location=SINGAPORE, start_date=date(2026, 9, 5), end_date=date(2026, 9, 1)
            )

    def test_historical_cannot_predate_archive(self) -> None:
        with pytest.raises(ValidationError):
            HistoricalRequest(
                location=SINGAPORE, start_date=date(1939, 12, 31), end_date=date(1940, 1, 2)
            )

    def test_climate_window_inside_cmip6_coverage_and_31_days(self) -> None:
        ClimateRequest(location=SINGAPORE, start_date=date(2027, 2, 1), end_date=date(2027, 2, 7))
        with pytest.raises(ValidationError):
            ClimateRequest(
                location=SINGAPORE, start_date=date(2049, 12, 25), end_date=date(2051, 1, 2)
            )
        with pytest.raises(ValidationError):
            ClimateRequest(
                location=SINGAPORE, start_date=date(1949, 12, 31), end_date=date(1950, 1, 2)
            )
        with pytest.raises(ValidationError):
            ClimateRequest(
                location=SINGAPORE, start_date=date(2027, 2, 1), end_date=date(2027, 3, 5)
            )

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentAndForecastRequest.model_validate(
                {"location": SINGAPORE.model_dump(), "forecast_days": 3, "canvas_id": "x"}
            )


class TestDateSemantics:
    def test_historical_requires_end_date_beyond_archive_lag(self) -> None:
        ok = HistoricalRequest(
            location=SINGAPORE,
            start_date=TODAY - timedelta(days=20),
            end_date=TODAY - timedelta(days=7),
        )
        assert_date_semantics(ok, today=TODAY)
        recent = HistoricalRequest(
            location=SINGAPORE,
            start_date=TODAY - timedelta(days=20),
            end_date=TODAY - timedelta(days=6),
        )
        with pytest.raises(WeatherGatewayError) as exc:
            assert_date_semantics(recent, today=TODAY)
        assert exc.value.code == "invalid_request"

    def test_historical_future_dates_rejected(self) -> None:
        future = HistoricalRequest(
            location=SINGAPORE, start_date=date(2026, 12, 1), end_date=date(2026, 12, 3)
        )
        with pytest.raises(WeatherGatewayError):
            assert_date_semantics(future, today=TODAY)

    def test_climate_inside_forecast_horizon_is_rejected(self) -> None:
        # Forecast covers today..today+15; a climate summary must never stand in for it.
        inside = ClimateRequest(
            location=SINGAPORE,
            start_date=TODAY + timedelta(days=15),
            end_date=TODAY + timedelta(days=20),
        )
        with pytest.raises(WeatherGatewayError) as exc:
            assert_date_semantics(inside, today=TODAY)
        assert exc.value.code == "invalid_request"

    def test_climate_in_the_past_is_rejected(self) -> None:
        past = ClimateRequest(
            location=SINGAPORE, start_date=date(2026, 1, 1), end_date=date(2026, 1, 7)
        )
        with pytest.raises(WeatherGatewayError):
            assert_date_semantics(past, today=TODAY)

    def test_climate_beyond_horizon_is_accepted(self) -> None:
        beyond = ClimateRequest(
            location=SINGAPORE,
            start_date=TODAY + timedelta(days=16),
            end_date=TODAY + timedelta(days=22),
        )
        assert_date_semantics(beyond, today=TODAY)


class TestPlanWeatherRequests:
    def test_trip_inside_horizon_gets_forecast_only(self) -> None:
        plan = plan_weather_requests(
            SINGAPORE, TODAY + timedelta(days=2), TODAY + timedelta(days=5), today=TODAY
        )
        assert [r.kind for r in plan.requests] == ["current_and_forecast"]
        forecast = plan.requests[0]
        assert isinstance(forecast, CurrentAndForecastRequest)
        assert forecast.forecast_days == 6  # today..today+5

    def test_distant_trip_gets_climate_summary_never_a_forecast(self) -> None:
        plan = plan_weather_requests(SINGAPORE, date(2027, 2, 1), date(2027, 2, 7), today=TODAY)
        assert [r.kind for r in plan.requests] == ["climate"]
        assert "beyond_forecast_horizon_climate_summary_only" in plan.notes

    def test_trip_straddling_horizon_gets_both_without_overlap(self) -> None:
        start = TODAY + timedelta(days=10)
        end = TODAY + timedelta(days=24)
        plan = plan_weather_requests(SINGAPORE, start, end, today=TODAY)
        kinds = [r.kind for r in plan.requests]
        assert kinds == ["current_and_forecast", "climate"]
        forecast, climate = plan.requests
        assert isinstance(forecast, CurrentAndForecastRequest)
        assert isinstance(climate, ClimateRequest)
        assert forecast.forecast_days == 16
        assert climate.start_date == TODAY + timedelta(days=16)
        assert climate.end_date == end

    def test_long_distant_trip_climate_window_truncated_with_note(self) -> None:
        plan = plan_weather_requests(SINGAPORE, date(2027, 3, 1), date(2027, 4, 30), today=TODAY)
        climate = plan.requests[0]
        assert isinstance(climate, ClimateRequest)
        assert (climate.end_date - climate.start_date).days + 1 == 31
        assert "climate_summary_truncated_to_31_days" in plan.notes

    def test_past_trip_gets_historical_only_when_beyond_archive_lag(self) -> None:
        old = plan_weather_requests(SINGAPORE, date(2026, 8, 1), date(2026, 8, 7), today=TODAY)
        assert [r.kind for r in old.requests] == ["historical"]
        recent = plan_weather_requests(
            SINGAPORE, TODAY - timedelta(days=5), TODAY - timedelta(days=3), today=TODAY
        )
        assert recent.requests == ()
        assert "recent_past_unavailable" in recent.notes

    def test_reversed_trip_dates_rejected(self) -> None:
        with pytest.raises(WeatherGatewayError):
            plan_weather_requests(SINGAPORE, date(2027, 2, 7), date(2027, 2, 1), today=TODAY)

    def test_every_planned_request_passes_date_semantics(self) -> None:
        for start, end in [
            (TODAY, TODAY + timedelta(days=3)),
            (TODAY + timedelta(days=10), TODAY + timedelta(days=24)),
            (date(2027, 2, 1), date(2027, 2, 7)),
            (date(2026, 8, 1), date(2026, 8, 7)),
        ]:
            for request in plan_weather_requests(SINGAPORE, start, end, today=TODAY).requests:
                assert_date_semantics(request, today=TODAY)


class TestEvidenceMeta:
    def test_climate_is_never_a_forecast_and_always_needs_verification(self) -> None:
        meta = _meta()
        assert meta.is_forecast is False
        with pytest.raises(ValidationError):
            _meta(needs_verification=False)
        with pytest.raises(ValidationError):
            _meta(confidence="medium")

    def test_label_must_match_kind(self) -> None:
        with pytest.raises(ValidationError):
            _meta(label="Forecast")

    def test_only_near_term_forecast_is_a_forecast(self) -> None:
        docs = "https://open-meteo.com/en/docs"
        forecast = _meta(
            kind="near_term_forecast",
            label="Forecast",
            confidence="medium",
            source_url=docs,
        )
        assert forecast.is_forecast is True
        for kind, label in [
            ("current_observation", "Current conditions (model-derived)"),
            ("historical_observation", "Past conditions (reanalysis)"),
        ]:
            meta = _meta(kind=kind, label=label, confidence="medium", source_url=docs)
            assert meta.is_forecast is False

    def test_fixture_origin_always_needs_verification(self) -> None:
        with pytest.raises(ValidationError):
            _meta(
                kind="near_term_forecast",
                label="Forecast",
                confidence="medium",
                needs_verification=False,
            )

    def test_naive_datetimes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _meta(retrieved_at=datetime(2026, 10, 14, 6, 0))

    def test_validity_window_must_be_ordered(self) -> None:
        with pytest.raises(ValidationError):
            _meta(valid_from=datetime(2027, 2, 8, tzinfo=UTC))

    def test_source_url_must_be_an_open_meteo_https_url(self) -> None:
        for bad in [
            "http://open-meteo.com/",
            "https://evil.example/",
            "https://open-meteo.com.evil.example/",
        ]:
            with pytest.raises(ValidationError):
                _meta(source_url=bad)

    def test_attribution_is_fixed(self) -> None:
        with pytest.raises(ValidationError):
            _meta(attribution="Weather by someone else")


class TestOutcome:
    def _climate(self) -> ClimateSummary:
        return ClimateSummary(
            meta=_meta(),
            place=WeatherPlace(
                latitude=1.375, longitude=103.75, elevation_m=18.0, timezone="Asia/Singapore"
            ),
            window_start=date(2027, 2, 1),
            window_end=date(2027, 2, 7),
            sample_days=7,
            model="MRI_AGCM3_2_S",
            mean_temperature_max_c=31.0,
            mean_temperature_min_c=25.0,
            total_precipitation_mm=60.0,
        )

    def test_available_requires_evidence_and_carries_attribution(self) -> None:
        outcome = WeatherContextOutcome(status="available", evidence=(self._climate(),))
        assert outcome.attribution == ATTRIBUTION_TEXT
        assert outcome.attribution_url == ATTRIBUTION_URL
        with pytest.raises(ValidationError):
            WeatherContextOutcome(status="available", evidence=())

    def test_unavailable_has_fixed_message_and_no_evidence(self) -> None:
        outcome = WeatherContextOutcome(
            status="unavailable",
            unavailable=WeatherUnavailable(code="timeout", request_kind="climate"),
        )
        assert outcome.unavailable is not None
        assert outcome.unavailable.message == "Weather context unavailable"
        assert outcome.evidence == ()
        with pytest.raises(ValidationError):
            WeatherContextOutcome(
                status="unavailable",
                evidence=(self._climate(),),
                unavailable=WeatherUnavailable(code="timeout", request_kind="climate"),
            )

    def test_climate_summary_carries_its_non_forecast_caveat(self) -> None:
        assert "not a forecast" in self._climate().caveat.lower()
