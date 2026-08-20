"""Normalized travel inventory contracts — spec 16 §3-§5.

Provider-neutral Pydantic v2 models for flight/hotel/award search requests and
quotes. All money is integer minor units; all timestamps are timezone-aware.
Sample/sandbox evidence (``provider_id`` prefixed ``sample_``) can never claim
``status="live"`` — enforced in ``EvidenceMeta`` below, not left to adapter
discipline.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

Cabin = Literal["economy", "premium", "business", "first"]
Status = Literal["live", "cached", "estimated", "stale", "verify_required"]
Completeness = Literal["complete", "taxes_uncertain", "fees_uncertain", "partial"]
PropertyKind = Literal["hotel", "serviced_apartment", "vacation_rental", "hostel"]
Channel = Literal[
    "direct_airline", "direct_hotel", "ota_generic", "bank_portal", "pos_abroad", "pos_domestic"
]


def _normalize_iata(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be an IATA code")
    return normalized


def _normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be a 3-letter currency code")
    return normalized


# --------------------------------------------------------------------------- #
# Evidence metadata (spec 16 §3)
# --------------------------------------------------------------------------- #


class EvidenceMeta(BaseModel):
    provider_id: str = Field(min_length=1)
    provider_quote_id: str | None = None
    source_url: str | None = None
    deep_link_url: str | None = None
    retrieved_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    status: Status
    cache_age_seconds: int | None = Field(default=None, ge=0)
    terms_version: str = Field(min_length=1)
    attribution: str | None = None
    completeness: Completeness
    needs_verification: bool
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _live_requires_unexpired_and_non_sample(self) -> EvidenceMeta:
        if self.status == "live":
            if self.expires_at is not None and self.retrieved_at >= self.expires_at:
                raise ValueError("live evidence cannot already be past its own expiry")
            if self.provider_id.startswith("sample_"):
                raise ValueError("sample/sandbox evidence can never be status=live")
        return self


# --------------------------------------------------------------------------- #
# Search requests (spec 16 §4)
# --------------------------------------------------------------------------- #


class TravelerMix(BaseModel):
    adults: int = Field(ge=0)
    children: int = Field(default=0, ge=0)
    infants: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _at_least_one_traveler(self) -> TravelerMix:
        if self.adults + self.children + self.infants < 1:
            raise ValueError("at least one traveler is required")
        return self


class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    travelers: TravelerMix
    cabin: Cabin
    nearby_airports: bool = False
    nonstop_only: bool = False
    currency: str

    _norm_origin = field_validator("origin")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_dest = field_validator("destination")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _return_not_before_depart(self) -> FlightSearchRequest:
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError("return_date cannot precede depart_date")
        return self


class FlexibleFlightSearchRequest(BaseModel):
    origin: str
    destination: str
    depart_window_start: date
    depart_window_end: date
    return_window_start: date | None = None
    return_window_end: date | None = None
    trip_length_nights: int | None = Field(default=None, ge=0)
    travelers: TravelerMix
    cabin: Cabin
    nearby_airports: bool = False
    nonstop_only: bool = False
    currency: str
    max_date_pairs: int = Field(gt=0, le=31)

    _norm_origin = field_validator("origin")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_dest = field_validator("destination")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _windows_are_consistent(self) -> FlexibleFlightSearchRequest:
        if self.depart_window_end < self.depart_window_start:
            raise ValueError("depart_window_end cannot precede depart_window_start")
        if self.return_window_start is not None and self.return_window_end is not None:
            if self.return_window_end < self.return_window_start:
                raise ValueError("return_window_end cannot precede return_window_start")
        return self


class HotelSearchRequest(BaseModel):
    city: str
    check_in: date
    check_out: date
    travelers: TravelerMix
    rooms: int = Field(gt=0)
    area_ids: list[str] = Field(default_factory=list)
    style: Literal["budget", "balanced", "luxury"]
    currency: str
    property_kinds: set[PropertyKind] = Field(default_factory=lambda: {"hotel"})  # type: ignore[arg-type]

    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _checkout_after_checkin(self) -> HotelSearchRequest:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self


class FlexibleStaySearchRequest(BaseModel):
    city: str
    window_start: date
    window_end: date
    nights: int = Field(gt=0)
    travelers: TravelerMix
    rooms: int = Field(gt=0)
    area_ids: list[str] = Field(default_factory=list)
    style: Literal["budget", "balanced", "luxury"]
    currency: str
    property_kinds: set[PropertyKind]
    max_start_dates: int = Field(gt=0, le=31)

    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _window_is_consistent(self) -> FlexibleStaySearchRequest:
        if self.window_end < self.window_start:
            raise ValueError("window_end cannot precede window_start")
        return self


class AwardSearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    travelers: TravelerMix
    cabin: Cabin
    program_ids: list[str] = Field(default_factory=list)

    _norm_origin = field_validator("origin")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_dest = field_validator("destination")(classmethod(lambda cls, v: _normalize_iata(v)))

    @model_validator(mode="after")
    def _return_not_before_depart(self) -> AwardSearchRequest:
        if self.return_date is not None and self.return_date < self.depart_date:
            raise ValueError("return_date cannot precede depart_date")
        return self


# --------------------------------------------------------------------------- #
# Flights (spec 16 §5)
# --------------------------------------------------------------------------- #


class FlightSegment(BaseModel):
    origin: str
    destination: str
    departure_at: AwareDatetime
    arrival_at: AwareDatetime
    marketing_airline: str = Field(min_length=1)
    operating_airline: str | None = None
    flight_number: str = Field(min_length=1)
    cabin: str
    duration_min: int = Field(gt=0)

    _norm_origin = field_validator("origin")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_dest = field_validator("destination")(classmethod(lambda cls, v: _normalize_iata(v)))

    @model_validator(mode="after")
    def _arrival_after_departure(self) -> FlightSegment:
        if self.arrival_at <= self.departure_at:
            raise ValueError("arrival_at must be after departure_at")
        return self


class FlightQuote(BaseModel):
    id: str = Field(min_length=1)
    segments: list[FlightSegment] = Field(min_length=1)
    trip_type: Literal["one_way", "round_trip"]
    travelers: TravelerMix
    fare_brand: str | None = None
    baggage_summary: str | None = None
    refundable: bool | None = None
    changeable: bool | None = None
    base_minor: int | None = Field(default=None, ge=0)
    taxes_minor: int | None = Field(default=None, ge=0)
    fees_minor: int | None = Field(default=None, ge=0)
    total_minor: int = Field(ge=0)
    currency: str
    purchasable_channels: list[Channel] = Field(default_factory=list)
    evidence: EvidenceMeta

    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _segments_are_chronological(self) -> FlightQuote:
        for earlier, later in zip(self.segments, self.segments[1:], strict=False):
            if later.departure_at < earlier.arrival_at:
                raise ValueError("segments must be in non-decreasing chronological order")
        return self


class FlightPriceObservation(BaseModel):
    id: str = Field(min_length=1)
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    cabin: Cabin | None = None
    stops: int | None = Field(default=None, ge=0)
    observed_total_minor: int = Field(ge=0)
    currency: str
    observed_at: AwareDatetime
    itinerary_detail: Literal["route_only", "partial"]
    is_bookable: Literal[False] = False
    evidence: EvidenceMeta

    _norm_origin = field_validator("origin")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_dest = field_validator("destination")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _evidence_cannot_be_live(self) -> FlightPriceObservation:
        if self.evidence.status == "live":
            raise ValueError("a cached/observed price trend can never be status=live")
        return self


# --------------------------------------------------------------------------- #
# Hotels (spec 16 §5)
# --------------------------------------------------------------------------- #


class HotelQuote(BaseModel):
    id: str = Field(min_length=1)
    property_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    property_kind: PropertyKind
    city: str
    area_id: str | None = None
    lat: float | None = None
    lon: float | None = None
    check_in: date
    check_out: date
    travelers: TravelerMix
    rooms: int = Field(gt=0)
    room_name: str | None = None
    rate_plan: str | None = None
    cancellation_summary: str | None = None
    refundable: bool | None = None
    review_score_scaled: int | None = Field(default=None, ge=0, le=10_000)
    review_scale_source: str | None = None
    review_count: int | None = Field(default=None, ge=0)
    placement: Literal["organic", "sponsored", "unknown"]
    base_minor: int | None = Field(default=None, ge=0)
    taxes_minor: int | None = Field(default=None, ge=0)
    fees_minor: int | None = Field(default=None, ge=0)
    total_minor: int = Field(ge=0)
    currency: str
    pay_timing: Literal["now", "property", "mixed", "unknown"]
    purchasable_channels: list[Channel] = Field(default_factory=list)
    evidence: EvidenceMeta

    _norm_ccy = field_validator("currency")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _checkout_after_checkin(self) -> HotelQuote:
        if self.check_out <= self.check_in:
            raise ValueError("check_out must be after check_in")
        return self

    @model_validator(mode="after")
    def _review_score_requires_scale_source(self) -> HotelQuote:
        if self.review_score_scaled is not None and self.review_scale_source is None:
            raise ValueError("a review score is admitted only with a documented provider scale")
        return self


# --------------------------------------------------------------------------- #
# Awards (spec 16 §5)
# --------------------------------------------------------------------------- #


class AwardQuote(BaseModel):
    id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    origin: str
    destination: str
    depart_date: date
    return_date: date | None = None
    cabin: Cabin
    travelers: TravelerMix
    seats_available: int | None = Field(default=None, ge=0)
    miles_total: int = Field(ge=0)
    fees_minor: int = Field(ge=0)
    fees_currency: str
    operating_airline: str | None = None
    mixed_cabin: bool | None = None
    evidence: EvidenceMeta

    _norm_origin = field_validator("origin")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_dest = field_validator("destination")(classmethod(lambda cls, v: _normalize_iata(v)))
    _norm_ccy = field_validator("fees_currency")(classmethod(lambda cls, v: _normalize_currency(v)))
