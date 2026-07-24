"""Pydantic v2 interface models — spec 01 (data model) + spec 02 (optimizer I/O).

Money is **never** a float here: minor units (paise/cents) as ``int``, percentages
as basis points (``int``), per-point values as micro-major units (``int``). The only
floats are non-money curator/geo fields (``confidence``, ``lat``, ``lon``,
``centrality_score``) — see the Gate M1 float audit in ``reports/milestone_1.md``.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

# --------------------------------------------------------------------------- #
# 1. Provenance (spec 01 §1)                                                    #
# --------------------------------------------------------------------------- #


class Provenance(BaseModel):
    """Trust metadata embedded on every fact row that can influence a recommendation."""

    source_url: str | None = None
    source_type: Literal["official_page", "tnc_pdf", "manual_curation", "crawl_draft"]
    last_verified: date
    verified_by: str  # curator id, or "UNVERIFIED"
    needs_verification: bool  # True on all shipped seed data
    confidence: float  # 0.0–1.0 curator-assigned (NOT money)
    notes: str | None = None


# --------------------------------------------------------------------------- #
# 2. Enumerations (spec 01 §2)                                                  #
# --------------------------------------------------------------------------- #


class SpendCategory(str, Enum):
    FLIGHTS = "flights"
    HOTELS = "hotels"
    DINING = "dining"
    GROCERY = "grocery"
    TRANSIT = "transit"
    ATTRACTIONS = "attractions"
    SHOPPING = "shopping"
    FOREX_GENERAL = "forex_general"  # generic intl POS spend
    OTA = "ota"
    INSURANCE = "insurance"
    OTHER = "other"


class Channel(str, Enum):
    DIRECT_AIRLINE = "direct_airline"
    DIRECT_HOTEL = "direct_hotel"
    OTA_GENERIC = "ota_generic"  # MMT, Cleartrip, Agoda
    BANK_PORTAL = "bank_portal"  # issuer travel portal (SmartBuy-class)
    POS_ABROAD = "pos_abroad"  # physical/online spend in destination currency
    POS_DOMESTIC = "pos_domestic"


class RedemptionPath(str, Enum):
    CASHBACK = "cashback"
    PORTAL_FLIGHTS = "portal_flights"
    PORTAL_HOTELS = "portal_hotels"
    TRANSFER_AIRLINE = "transfer_airline"
    TRANSFER_HOTEL = "transfer_hotel"
    VOUCHER = "voucher"


class OfferKind(str, Enum):
    INSTANT_DISCOUNT = "instant_discount"  # reduces amount paid now
    CASHBACK_LATER = "cashback_later"  # statement credit after N days
    BONUS_POINTS = "bonus_points"
    NO_COST_EMI = "no_cost_emi"  # stored only; never selected by the optimizer


# --------------------------------------------------------------------------- #
# 3. Cards & earn (spec 01 §3)                                                  #
# --------------------------------------------------------------------------- #


class EarnRate(BaseModel):
    """``points`` earned per ``per_amount_minor`` of spend, floored per transaction."""

    points: int
    per_amount_minor: int  # e.g. 5 pts per ₹150 → points=5, per_amount_minor=15000
    currency: str


class Card(BaseModel):
    id: str  # slug, e.g. "hdfc-infinia"
    issuer: str
    network: Literal["visa", "mastercard", "amex", "rupay", "diners"]
    country: Literal["IN", "AE", "US"]
    name: str
    annual_fee_minor: int
    fee_currency: str
    forex_markup_bp: int  # 200 = 2.00%
    forex_markup_tax_bp: int  # tax ON the markup; IN GST 1800 = 18%
    base_earn: EarnRate
    lounge_intl_visits_per_year: int | None = None  # report color; not optimized
    provenance: Provenance


# --------------------------------------------------------------------------- #
# 4. Reward rules (spec 01 §4)                                                  #
# --------------------------------------------------------------------------- #


class RewardCap(BaseModel):
    max_points: int
    period: Literal["statement_cycle", "calendar_month", "day", "offer_period"]
    shared_cap_group: str | None = None  # rules sharing a pool


class RewardRule(BaseModel):
    id: str
    card_id: str
    description: str  # human-readable, used verbatim in explanations
    earn: EarnRate  # accelerated rate when matched
    categories: list[SpendCategory]
    channels: list[Channel] | None = None  # None = any channel
    currencies: list[str] | None = None  # None = any currency
    excluded_categories: list[SpendCategory] = Field(default_factory=list)
    mcc_codes: list[int] | None = None
    cap: RewardCap | None = None
    valid_from: date | None = None
    valid_to: date | None = None  # rule expiry (promos)
    provenance: Provenance


# --------------------------------------------------------------------------- #
# 5. Point valuations (spec 01 §5)                                              #
# --------------------------------------------------------------------------- #


class PointValuation(BaseModel):
    id: str
    card_id: str
    path: RedemptionPath
    value_micro_major_per_point: int  # millionths of a major unit; ₹0.50 → 500_000
    currency: str
    min_points: int | None = None
    conditions: str | None = None
    provenance: Provenance


# --------------------------------------------------------------------------- #
# 6. Offers (spec 01 §6)                                                        #
# --------------------------------------------------------------------------- #


class Offer(BaseModel):
    id: str
    title: str
    kind: OfferKind
    issuer: str | None = None
    card_ids: list[str] | None = None
    networks: list[str] | None = None
    merchant: str
    channels: list[Channel]
    categories: list[SpendCategory]
    discount_bp: int | None = None  # 1000 = 10%
    discount_flat_minor: int | None = None  # exactly one of bp/flat set
    max_discount_minor: int | None = None
    min_txn_minor: int | None = None
    currency: str
    valid_to: date
    promo_code: str | None = None
    stacking_class: Literal["bank_offer", "coupon", "card_linked"]
    uses_per_card: int | None = None
    provenance: Provenance


# --------------------------------------------------------------------------- #
# 7. Destination & pricing data (spec 01 §7)                                    #
# --------------------------------------------------------------------------- #


class POI(BaseModel):
    id: str
    city: str
    name: str
    tags: list[str]
    typical_duration_min: int
    price_minor: int
    currency: str
    lat: float  # geo (NOT money)
    lon: float  # geo (NOT money)
    area: str
    open_hours: str
    booking_channel: Channel
    merchant_hint: str | None = None
    description: str
    provenance: Provenance


class SampleFlight(BaseModel):
    id: str
    origin: str
    destination: str  # IATA
    airline: str
    stops: int
    price_minor: int
    currency: str  # per person, round trip
    cabin: Literal["economy", "premium", "business"]
    purchasable_channels: list[Channel]
    notes: str | None = None
    provenance: Provenance


class SampleHotel(BaseModel):
    id: str
    city: str
    name: str
    area: str
    stars: int
    price_per_night_minor: int
    currency: str
    style: Literal["budget", "balanced", "luxury"]
    purchasable_channels: list[Channel]
    provenance: Provenance


class FxRate(BaseModel):
    base: str
    quote: str
    rate_micro: int  # SGD→INR 63.20 → 63_200_000
    as_of: date
    provenance: Provenance


class Area(BaseModel):
    """Per-city neighbourhood (spec 01 §7 'areas' table)."""

    id: str
    city: str
    name: str
    good_for_tags: list[str]
    centrality_score: float  # 0–1 (NOT money)
    provenance: Provenance


# --------------------------------------------------------------------------- #
# 8. Optimizer I/O (spec 02)                                                    #
# --------------------------------------------------------------------------- #


class SpendLineItem(BaseModel):
    """A normalized unit of spend (spec 02 §3)."""

    id: str
    label: str
    category: SpendCategory
    amount_minor: int  # sticker price in billing (home-currency) terms
    currency: str
    available_channels: list[Channel]
    merchant_hint: str | None = None
    splittable: bool = False  # MVP: False (one card per line)


class CostedTrip(BaseModel):
    """Estimator output consumed by the optimizer (spec 02 §3, minimal for M1).

    In M1 the golden harness supplies ``lines`` directly (bypassing the estimator).
    """

    id: str = "trip"
    origin: str = ""
    destination: str = ""
    home_currency: str = "INR"
    booking_date: date  # "today"; rule validity for prepaid lines
    trip_start_date: date  # rule validity for POS lines
    lines: list[SpendLineItem]


class UserWallet(BaseModel):
    """The user's owned cards + optional points balances (from TripSpec, spec 01 §8)."""

    card_ids: list[str]
    points_balances: dict[str, int] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 8b. Transfer pathfinder facts and output (spec 07)                           #
# --------------------------------------------------------------------------- #


class LoyaltyProgram(BaseModel):
    id: str
    kind: Literal["airline", "hotel", "card_currency"]
    name: str
    alliance: str | None = None
    booking_url: str | None = None
    provenance: Provenance


class TransferEdge(BaseModel):
    id: str
    from_id: str
    to_id: str
    ratio_from: int = Field(gt=0)
    ratio_to: int = Field(gt=0)
    min_transfer: int = Field(ge=0)
    increment: int = Field(gt=0)
    transfer_time_hours_typical: int = Field(ge=0)
    transfer_time_hours_max: int = Field(ge=0)
    provenance: Provenance


class TransferBonus(BaseModel):
    id: str
    edge_id: str
    bonus_bp: int = Field(ge=0)
    valid_from: date
    valid_to: date
    provenance: Provenance


class AwardChartEntry(BaseModel):
    id: str
    program_id: str
    origin: str
    destination: str
    cabin: Literal["economy", "premium", "business", "first"]
    trip_type: Literal["one_way", "round_trip"]
    miles_cost: int = Field(gt=0)
    fees_minor: int = Field(ge=0)
    fees_currency: str
    operating_airline_hint: str | None = None
    availability_note: str | None = None
    provenance: Provenance


class AwardTarget(BaseModel):
    origin: str
    destination: str
    cabin: Literal["economy", "premium", "business", "first"]
    trip_type: Literal["one_way", "round_trip"]
    travelers: int = Field(gt=0)
    home_currency: str = "INR"


class RecommendationKind(str, Enum):
    REDEEM = "REDEEM"
    PAY_CASH = "PAY_CASH"
    NO_DATA = "NO_DATA"


class TransferStep(BaseModel):
    from_id: str
    to_id: str
    amount_source: int = Field(ge=0)
    amount_dest: int = Field(ge=0)
    bonus_applied: str | None = None
    transfer_time_hours_typical: int = Field(ge=0)
    transfer_time_hours_max: int = Field(ge=0)


class TransferPlan(BaseModel):
    id: str
    award: AwardChartEntry
    travelers: int = Field(gt=0)
    steps: list[TransferStep]
    points_consumed: int = Field(ge=0)
    source_currency: str
    existing_miles_used: int = Field(ge=0)
    leftover_miles: int = Field(ge=0)
    total_fees_minor: int = Field(ge=0)
    value_per_point_micro: int = Field(ge=0)
    effective_redemption_cost_minor: int = Field(ge=0)
    savings_vs_cash_minor: int
    dominated: bool = False
    checklist_steps: list[str] = Field(default_factory=list)
    provenance_flags: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)


class InfeasiblePlan(BaseModel):
    award_id: str
    best_path: list[str]
    shortfall_points: int = Field(gt=0)
    shortfall_currency: str
    note: str


class Recommendation(BaseModel):
    kind: RecommendationKind
    plan_id: str | None = None
    reason: str


class TransferAdvice(BaseModel):
    plans: list[TransferPlan]
    infeasible: list[InfeasiblePlan]
    recommendation: Recommendation


class OptimizationPrefs(BaseModel):
    objective: Literal["max_savings", "min_cash_outlay", "min_forex", "simplicity"] = "max_savings"


class AppliedOffer(BaseModel):
    offer_id: str
    discount_minor: int
    stacking_class: Literal["bank_offer", "coupon", "card_linked"]


class RunnerUp(BaseModel):
    """Second-best option for a line, for the report's 'why not X?' section."""

    card_id: str
    channel: Channel
    benefit_minor: int
    delta_minor: int  # winner.benefit − runner_up.benefit (>= 0)
    summary: str


class LineAssignment(BaseModel):
    line: SpendLineItem
    card_id: str
    channel: Channel
    offers_applied: list[AppliedOffer] = Field(default_factory=list)
    points_earned: int
    points_value_minor: int
    assumed_redemption: RedemptionPath
    forex_fee_minor: int
    benefit_minor: int
    explanation: list[str] = Field(default_factory=list)
    provenance_flags: list[str] = Field(default_factory=list)
    runner_up: RunnerUp | None = None


class OptimizerResult(BaseModel):
    assignments: list[LineAssignment]
    gross_minor: int
    discounts_minor: int
    rewards_value_minor: int
    forex_fees_minor: int
    effective_cost_minor: int
    cash_outlay_now_minor: int
    deferred_value_minor: int
    savings_pct_bp: int
    cap_pools_final: dict[str, int]
    assumptions: list[str] = Field(default_factory=list)
    confidence: float  # min over used facts' confidences (NOT money)
