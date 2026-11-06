"""Application-owned weather context orchestration.

This module adapts an admitted destination/date window to the already reviewed
Open-Meteo gateway. It owns no network client and never changes an itinerary.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime

from gateway.weather.adapter import OpenMeteoWeatherAdapter
from gateway.weather.contracts import (
    UNAVAILABLE_MESSAGE,
    RequestKind,
    WeatherContextOutcome,
    WeatherEvidence,
    WeatherLocation,
    WeatherUnavailable,
    plan_weather_requests,
)
from gateway.weather.errors import ErrorCode, WeatherGatewayError


class WeatherContextService:
    """Fetch optional weather evidence for one admitted trip window."""

    def __init__(
        self,
        adapter: OpenMeteoWeatherAdapter | None = None,
        *,
        adapter_factory: Callable[[str], OpenMeteoWeatherAdapter] | None = None,
        location_provider: Callable[[str], WeatherLocation | None],
        now: Callable[[], datetime],
    ) -> None:
        if (adapter is None) == (adapter_factory is None):
            raise ValueError("provide exactly one weather adapter construction path")
        self._adapter = adapter
        self._adapter_factory = adapter_factory
        self._location_provider = location_provider
        self._now = now

    async def get_context(
        self, *, destination_iata: str, trip_start: date, trip_end: date, plan_id: str = "default"
    ) -> WeatherContextOutcome:
        location = self._location_provider(destination_iata)
        if location is None:
            return self._unavailable(
                "invalid_request",
                "destination_coordinates_unavailable",
                requested_start=trip_start,
                requested_end=trip_end,
            )

        today = self._now().astimezone(UTC).date()
        try:
            plan = plan_weather_requests(
                WeatherLocation(
                    latitude=location.latitude,
                    longitude=location.longitude,
                    label=location.label,
                ),
                trip_start,
                trip_end,
                today=today,
            )
        except (WeatherGatewayError, ValueError) as error:
            code: ErrorCode = (
                error.code if isinstance(error, WeatherGatewayError) else "invalid_request"
            )
            return self._unavailable(
                code,
                "unsupported_date_window",
                requested_start=trip_start,
                requested_end=trip_end,
            )

        if "climate_summary_truncated_to_31_days" in plan.notes:
            return self._unavailable(
                "invalid_request",
                "unsupported_date_window",
                limitations=plan.notes,
                requested_start=trip_start,
                requested_end=trip_end,
            )
        if not plan.requests:
            return self._unavailable(
                "invalid_request",
                "unsupported_date_window",
                limitations=plan.notes,
                requested_start=trip_start,
                requested_end=trip_end,
            )

        adapter = self._adapter_factory(plan_id) if self._adapter_factory else self._adapter
        assert adapter is not None
        evidence: list[WeatherEvidence] = []
        for request in plan.requests:
            outcome = await adapter.get_context(request)
            if outcome.status == "unavailable":
                unavailable = outcome.unavailable
                assert unavailable is not None
                return self._unavailable(
                    unavailable.code,
                    "provider_unavailable",
                    request_kind=request.kind,
                    limitations=(*plan.notes, "weather_context_not_available"),
                    requested_start=trip_start,
                    requested_end=trip_end,
                )
            evidence.extend(outcome.evidence)
        return WeatherContextOutcome(
            status="available",
            evidence=tuple(evidence),
            requested_start=trip_start,
            requested_end=trip_end,
            limitations=plan.notes,
        )

    def get_context_sync(
        self, *, destination_iata: str, trip_start: date, trip_end: date, plan_id: str = "default"
    ) -> WeatherContextOutcome:
        return asyncio.run(
            self.get_context(
                destination_iata=destination_iata,
                trip_start=trip_start,
                trip_end=trip_end,
                plan_id=plan_id,
            )
        )

    @staticmethod
    def _unavailable(
        code: ErrorCode,
        limitation: str,
        *,
        requested_start: date,
        requested_end: date,
        request_kind: RequestKind = "current_and_forecast",
        limitations: tuple[str, ...] = (),
    ) -> WeatherContextOutcome:
        return WeatherContextOutcome(
            status="unavailable",
            unavailable=WeatherUnavailable(
                code=code, request_kind=request_kind, message=UNAVAILABLE_MESSAGE
            ),
            requested_start=requested_start,
            requested_end=requested_end,
            limitations=(*limitations, limitation),
        )
