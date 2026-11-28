"""Typed Pydantic v2 contracts for non-points card perks and rental-car protection.

All money amounts remain integer minor units, rates in basis points, and per-point
valuations in micro-major units. Zero float money arithmetic.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.models import Channel, EarnRate, Provenance, SpendCategory


def _normalize_iso_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError(f"currency must be a 3-letter ISO 4217 code, got {value!r}")
    return normalized


class RentalCarProtection(BaseModel):
    """Credit card rental-car CDW/LDW benefit terms."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str = Field(min_length=1)
    coverage_type: Literal["primary_cdw", "secondary_cdw", "none"]
    max_coverage_minor: int = Field(ge=0)
    currency: str
    max_rental_days: int = Field(ge=0)
    excluded_countries: list[str] = Field(default_factory=list)
    requires_full_payment_on_card: bool = True
    counter_cdw_avoided_per_day_minor: int = Field(ge=0)
    provenance: Provenance

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _normalize_iso_currency(value)


class CardGrantedStatus(BaseModel):
    """Automatic elite status granted by holding a card (hotel, airline, or car rental)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    program_kind: Literal["hotel", "airline", "car_rental"]
    tier_name: str = Field(min_length=1)
    estimated_value_per_event_minor: int = Field(ge=0)
    currency: str
    requires_enrollment: bool = True
    perks_summary: list[str] = Field(default_factory=list)
    provenance: Provenance

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _normalize_iso_currency(value)


class StatementCreditPerk(BaseModel):
    """Capped statement credit benefit (annual, monthly, semi-annual, or per-stay)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    card_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    categories: list[SpendCategory] = Field(min_length=1)
    channels: list[Channel] | None = None
    max_credit_minor: int = Field(ge=0)
    remaining_credit_minor: int = Field(ge=0)
    currency: str
    period: Literal["annual", "monthly", "semi_annual", "per_stay"]
    provenance: Provenance

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _normalize_iso_currency(value)

    @model_validator(mode="after")
    def _remaining_within_max(self) -> Self:
        if self.remaining_credit_minor > self.max_credit_minor:
            raise ValueError("remaining_credit_minor cannot exceed max_credit_minor")
        return self


class AirlineBagPerk(BaseModel):
    """Card-granted free checked baggage perk for a specific airline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str = Field(min_length=1)
    airline_iata: str = Field(min_length=2, max_length=3)
    free_checked_bags: int = Field(ge=0)
    estimated_value_per_bag_minor: int = Field(ge=0)
    currency: str
    requires_payment_on_card: bool = True
    provenance: Provenance

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _normalize_iso_currency(value)


class ReferenceRentalProgram(BaseModel):
    """Unverified reference metadata for a car-rental loyalty program."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    kind: Literal["car_rental"] = "car_rental"
    name: str = Field(min_length=1)
    booking_url: str | None = None
    provenance: Provenance


class CardPerkProfile(BaseModel):
    """Aggregated non-points perk profile for one card."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str = Field(min_length=1)
    rental_protection: RentalCarProtection | None = None
    granted_statuses: list[CardGrantedStatus] = Field(default_factory=list)
    statement_credits: list[StatementCreditPerk] = Field(default_factory=list)
    bag_perks: list[AirlineBagPerk] = Field(default_factory=list)


class RentalCarCardCandidate(BaseModel):
    """Input candidate card evaluated for a specific car rental transaction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str = Field(min_length=1)
    channel: Channel = Channel.DIRECT_CAR_RENTAL
    paid_in_full_on_card: bool = True
    points_value_minor: int | None = Field(default=None, ge=0)
    earn_rate: EarnRate | None = None
    point_value_micro: int = Field(default=0, ge=0)
    forex_cost_minor: int | None = Field(default=None, ge=0)
    forex_markup_bp: int = Field(default=0, ge=0)
    forex_markup_tax_bp: int = Field(default=0, ge=0)
    perk_profile: CardPerkProfile | None = None
    preferred_rental_program_id: str | None = None


class RentalCarCardBreakdown(BaseModel):
    """Deterministic minor-unit valuation breakdown for one rental-car card candidate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str
    channel: Channel
    rental_cost_home_minor: int
    points_value_minor: int
    primary_cdw_savings_minor: int
    primary_cdw_applied: bool
    applicable_credit_minor: int
    status_perk_value_minor: int
    forex_cost_minor: int
    net_total_value_minor: int
    net_rental_cost_minor: int
    cdw_coverage_type: Literal["primary_cdw", "secondary_cdw", "none"]
    cdw_disqualification_reason: str | None = None
    explanation: list[str] = Field(default_factory=list)
    provenance_warnings: list[str] = Field(default_factory=list)


class RentalCarCardComparison(BaseModel):
    """Ranked rental-car card comparison balancing points, CDW, credits, status, and forex."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    recommended_card_id: str | None
    rental_cost_home_minor: int
    home_currency: str
    candidates: list[RentalCarCardBreakdown] = Field(default_factory=list)
    provenance_warnings: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)


class TripPerkItem(BaseModel):
    """One trip spend line item evaluated for non-points card perks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    label: str = ""
    card_id: str = Field(min_length=1)
    category: SpendCategory
    channel: Channel
    amount_minor: int = Field(ge=0)
    currency: str
    paid_in_full_on_card: bool = True
    rental_days: int = Field(default=0, ge=0)
    pickup_country: str | None = None
    rental_program_id: str | None = None
    hotel_program_id: str | None = None
    airline_iata: str | None = None
    checked_bags_count: int = Field(default=0, ge=0)
    hotel_stays_count: int = Field(default=1, ge=0)

    @field_validator("currency")
    @classmethod
    def _validate_currency(cls, value: str) -> str:
        return _normalize_iso_currency(value)


class TripItemPerkBreakdown(BaseModel):
    """Non-points perk breakdown for a single trip item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    card_id: str
    primary_cdw_savings_minor: int = 0
    status_perk_value_minor: int = 0
    bag_perk_value_minor: int = 0
    statement_credit_minor: int = 0
    total_perk_value_minor: int = 0
    applied_credit_ids: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
    provenance_warnings: list[str] = Field(default_factory=list)


class TripPerksValuation(BaseModel):
    """Aggregated non-points perk valuation across a multi-item trip."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    home_currency: str
    total_primary_cdw_savings_minor: int = 0
    total_status_perk_value_minor: int = 0
    total_bag_perk_value_minor: int = 0
    total_statement_credit_minor: int = 0
    total_perks_value_minor: int = 0
    remaining_credit_balances_minor: dict[str, int] = Field(default_factory=dict)
    item_breakdowns: list[TripItemPerkBreakdown] = Field(default_factory=list)
    provenance_warnings: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)
