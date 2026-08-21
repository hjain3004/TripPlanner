"""Gondola-native response contracts — kept separate from the project's
normalized ``HotelQuote``/``FlightQuote`` (spec 16 §3-§5) so a future real
schema correction touches only this file and ``normalize_hotel.py`` /
``normalize_flight.py``.

These fixtures/contracts are synthetic or sanitized placeholders pending a
genuine schema capture (see reports/g3_0_gondola_preflight.md §17 item 4,
and Phase 3 of docs/superpowers/plans/2026-08-21-g3-gondola-readonly-mcp.md)
— never treated as verified real Gondola wire format.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field


class GondolaHotelResult(BaseModel):
    hotel_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    cash_rate_minor: int | None = Field(default=None, ge=0)
    cash_currency: str | None = None
    points_rate: int | None = Field(default=None, ge=0)
    points_program: str | None = None
    cancellation_text: str | None = None
    review_score: float | None = None
    review_count: int | None = Field(default=None, ge=0)
    booking_link: str | None = None
    raw_notes: list[str] = Field(default_factory=list)


class GondolaFlightSegment(BaseModel):
    origin: str
    destination: str
    departure_at: AwareDatetime | None = None
    arrival_at: AwareDatetime | None = None
    marketing_airline: str | None = None
    operating_airline: str | None = None
    flight_number: str | None = None
    cabin: str | None = None
    duration_min: int | None = Field(default=None, gt=0)


class GondolaFlightResult(BaseModel):
    quote_id: str = Field(min_length=1)
    segments: list[GondolaFlightSegment] = Field(default_factory=list)
    trip_type: Literal["one_way", "round_trip"] | None = None
    total_price_minor: int | None = Field(default=None, ge=0)
    currency: str | None = None
    booking_link: str | None = None
    raw_notes: list[str] = Field(default_factory=list)


def parse_hotel_results(raw: list[dict[str, object]]) -> list[GondolaHotelResult]:
    return [GondolaHotelResult.model_validate(item) for item in raw]


def parse_flight_results(raw: list[dict[str, object]]) -> list[GondolaFlightResult]:
    return [GondolaFlightResult.model_validate(item) for item in raw]
