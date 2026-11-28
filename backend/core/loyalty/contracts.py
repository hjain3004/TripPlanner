"""Pydantic v2 contracts for airline/hotel loyalty ecosystems (integer minor/bp/micro units)."""

from __future__ import annotations

from datetime import date  # noqa: TC003 - needed at runtime by Pydantic
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.models import LoyaltyProgram, Provenance, TransferEdge


class HotelChainBrandRule(BaseModel):
    """Mapping from normalized hotel chain brand aliases to a loyalty program."""

    model_config = ConfigDict(frozen=True)

    chain_id: str = Field(min_length=1)
    chain_name: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    brand_aliases: tuple[str, ...]
    # Integer base loyalty points earned per USD 1.00 (100 USD cents) of eligible spend.
    base_points_per_usd_minor_or_unit: int = Field(ge=0)
    provenance: Provenance


class HotelBrandMatch(BaseModel):
    """Deterministic property-name match against a curated hotel chain rule."""

    model_config = ConfigDict(frozen=True)

    matched_brand: str = Field(min_length=1)
    chain_id: str = Field(min_length=1)
    program_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Provenance


class AlliancePartnerEdge(BaseModel):
    """Partner award ticketing relationship between operating airline and booking program."""

    model_config = ConfigDict(frozen=True)

    operating_carrier_iata: str = Field(min_length=2, max_length=3)
    operating_carrier_name: str = Field(min_length=1)
    booking_program_id: str = Field(min_length=1)
    alliance_or_bilateral: str = Field(min_length=1)
    notes: str | None = None
    provenance: Provenance


class HotelAwardStayRule(BaseModel):
    """Multi-night award stay discount rule (e.g., 5th or 4th night free)."""

    model_config = ConfigDict(frozen=True)

    program_id: str = Field(min_length=1)
    free_night_every_n: int | None = Field(default=None, ge=2)
    requires_status_or_card: str | None = None
    free_night_selection: Literal["lowest_in_block", "fourth_night_exact", "last_in_block"] = (
        "lowest_in_block"
    )
    provenance: Provenance


class HotelAwardStayCalculation(BaseModel):
    """Deterministic integer calculation of multi-night hotel award points cost."""

    model_config = ConfigDict(frozen=True)

    program_id: str = Field(min_length=1)
    nights: int = Field(ge=0)
    gross_points: int = Field(ge=0)
    free_nights_count: int = Field(ge=0)
    points_saved: int = Field(ge=0)
    net_points: int = Field(ge=0)
    free_night_indices: tuple[int, ...] = ()
    eligibility_applied: bool
    explanation: str
    provenance: Provenance


class DirectVsOtaLoyaltyComparison(BaseModel):
    """Deterministic direct-hotel vs OTA/bank-portal loyalty economics comparison."""

    model_config = ConfigDict(frozen=True)

    direct_cash_minor: int = Field(ge=0)
    ota_cash_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    direct_loyalty_points_earned: int = Field(ge=0)
    direct_loyalty_value_minor: int = Field(ge=0)
    status_perks_value_minor: int = Field(ge=0)
    forfeited_loyalty_value_minor: int = Field(ge=0)
    net_direct_advantage_minor: int
    recommendation: Literal["BOOK_DIRECT", "BOOK_OTA", "TIE"]
    explanation_factors: list[str]
    provenance_warnings: list[str]


class LoyaltyReferenceCatalog(BaseModel):
    """Validated unverified reference catalog overlay for real-world loyalty ecosystems."""

    model_config = ConfigDict(frozen=True)

    generated_date: date | None = None
    programs: tuple[LoyaltyProgram, ...]
    transfer_edges: tuple[TransferEdge, ...]
    hotel_brand_rules: tuple[HotelChainBrandRule, ...]
    hotel_award_stay_rules: tuple[HotelAwardStayRule, ...]
    alliance_partner_edges: tuple[AlliancePartnerEdge, ...]
