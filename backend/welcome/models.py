"""Welcome-window models (spec 18 §1-2, Case A only).

Two groups live here:

* ``CardAcquisitionOffer`` — the reference-data row of spec 18 §1. It is *terms about a
  card*, never user data, and it carries the same ``Provenance`` every other fact does.
* The status report — what ``compute_welcome_status`` returns and the API serializes.
  It extends spec 18 §2's ``WelcomeWindowStatus`` with the assumptions, the per-line
  timing assessment and the offer provenance the spec requires the report to state.

Every amount is an integer in minor units. An
unknown input is ``None`` and stays ``None``: it is never defaulted to a date or to zero.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.models import Provenance

# spec 18 §2: "closing_soon threshold: <= 21 days remaining. Tier C, tune freely."
CLOSING_SOON_DAYS = 21

# ``verified_by`` prefix reserved for authored test/demo offers. A shipped catalog must
# never contain one (enforced by the loader), and the API labels any that reach a
# response as a synthetic fixture so they cannot be mistaken for issuer terms.
SYNTHETIC_VERIFIER_PREFIX = "SYNTHETIC"


class CardAcquisitionOffer(BaseModel):
    """One welcome-bonus offer for a card (spec 18 §1)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    card_id: str
    title: str  # verbatim from the issuer page
    bonus_points: int | None = Field(default=None, ge=1)
    bonus_currency_id: str | None = None  # 07 LoyaltyProgram.id of kind card_currency
    bonus_flat_minor: int | None = Field(default=None, ge=1)
    min_spend_minor: int = Field(ge=1)
    spend_window_days: int = Field(ge=1)  # measured from the card open date, per T&C
    expected_approval_days: int = Field(ge=0)  # Case B only
    expected_card_in_hand_days: int = Field(ge=0)  # Case B only
    annual_fee_minor: int = Field(ge=0)  # Case B only
    fee_waiver_condition: str | None = None
    eligibility_exclusions: list[str] = Field(default_factory=list)  # VERBATIM T&C
    currency: str
    valid_to: date
    provenance: Provenance

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a 3-letter ISO 4217 code")
        return normalized

    @model_validator(mode="after")
    def _exactly_one_bonus(self) -> CardAcquisitionOffer:
        points = self.bonus_points is not None
        flat = self.bonus_flat_minor is not None
        if points == flat:
            raise ValueError("exactly one of bonus_points / bonus_flat_minor must be set")
        if points and not self.bonus_currency_id:
            raise ValueError("a points-denominated bonus needs bonus_currency_id")
        if flat and self.bonus_currency_id is not None:
            raise ValueError("a flat bonus must not name a points currency")
        return self


# --------------------------------------------------------------------------- #
# Status report                                                                 #
# --------------------------------------------------------------------------- #

WelcomeStatus = Literal["active", "closing_soon", "met", "expired", "unknown"]

# Why a status is ``unknown``, or what a reader must keep in mind. A closed set so a
# client can switch on it; ``message`` is a fixed server-authored sentence per code.
LimitationCode = Literal[
    "NO_APPROVED_OFFER",
    "AMBIGUOUS_OFFER",
    "OFFER_NOT_IN_FORCE_AT_OPEN_DATE",
    "OPENED_ON_UNKNOWN",
    "OPENED_ON_IN_FUTURE",
    "PRIOR_SPEND_UNKNOWN",
    "DUPLICATE_CARD_ENTRIES",
    "CARD_NOT_IN_PLANNED_WALLET",
    "CURRENCY_MISMATCH",
    "POINTS_PROGRAM_NOT_ESTABLISHED",
]

# Payment timing, not travel timing. ``advance_booking`` lines are paid when the traveler
# books; ``on_trip`` lines are charged at the destination. Neither date is observed.
TimingBasis = Literal["advance_booking", "on_trip"]

TimingAssessment = Literal[
    "could_count_if_paid_by_close",
    "outside_window",
    "straddles_window_unknown",
    "window_unknown",
    "currency_mismatch",
    "ambiguous_card_entry",
]

VerificationStatus = Literal["verified", "needs_verification", "synthetic_fixture"]


class Limitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: LimitationCode
    message: str


class OfferProvenanceOut(BaseModel):
    """Provenance of the offer terms, with the verification state made explicit."""

    model_config = ConfigDict(extra="forbid")

    source_url: str | None
    source_type: str
    last_verified: date
    verified_by: str
    needs_verification: bool
    confidence: float
    notes: str | None
    verification_status: VerificationStatus


class OfferOut(BaseModel):
    """The offer terms the status was computed from (never paraphrased)."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    bonus_points: int | None
    bonus_currency_id: str | None
    bonus_flat_minor: int | None
    min_spend_minor: int
    spend_window_days: int
    currency: str
    valid_to: date
    eligibility_exclusions: list[str]
    provenance: OfferProvenanceOut


class BonusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bonus_points: int | None
    # The points program the offer names, echoed as stated (never mapped or corrected).
    bonus_currency_id: str | None
    bonus_flat_minor: int | None
    # A flat bonus is its own value. A points bonus is ``None`` — never 0 — because the
    # data model has no verified link from a card's point valuation to the offer's points
    # program (see ``POINTS_PROGRAM_NOT_ESTABLISHED``).
    bonus_value_minor: int | None
    currency: str


class TripLineTiming(BaseModel):
    """One of this card's assigned lines, with how its payment timing was judged."""

    model_config = ConfigDict(extra="forbid")

    line_id: str
    label: str
    category: str
    channel: str
    timing_basis: TimingBasis
    amount_minor: int
    instant_discounts_minor: int
    # amount net of instant discounts (never below 0): the figure that may count.
    counted_minor: int
    currency: str
    assessment: TimingAssessment


class TripWindow(BaseModel):
    """What the stored plan says about *when*. Travel dates, not payment dates."""

    model_config = ConfigDict(extra="forbid")

    trip_id: str
    revision: int
    revision_computed_at: str
    trip_start_date: date
    trip_end_date: date
    plan_booking_date: date
    currency: str


class WelcomeWindowReport(BaseModel):
    """Spec 18 §2's ``WelcomeWindowStatus`` plus the context spec 18 §3 requires."""

    model_config = ConfigDict(extra="forbid")

    card_id: str
    card_name: str | None
    wallet_entry_id: str
    as_of: date
    status: WelcomeStatus
    limitations: list[Limitation]

    opened_on: date | None
    window_closes_on: date | None
    days_remaining: int | None

    offer: OfferOut | None
    ineligible_offer_count: int
    min_spend_minor: int | None
    currency: str | None

    qualifying_spend_to_date_minor: int | None  # user-entered; None if unknown
    shortfall_minor: int | None  # before this trip; None if prior spend unknown

    trip: TripWindow
    trip_assigned_spend_minor: int  # gross, this card only (spec 18 §2)
    trip_counted_spend_minor: int  # net of instant discounts, this card only
    # What could count if the stated timing conditions hold; never "confirmed".
    conditional_trip_spend_minor: int
    shortfall_after_conditional_trip_minor: int | None
    trip_alone_clears_minimum_if_conditions_hold: bool | None
    # Lines this card was assigned that carry no spend (e.g. per-venue placeholders) are
    # left out of ``lines``; their count is stated so nothing is dropped silently.
    omitted_zero_amount_lines: int
    lines: list[TripLineTiming]

    bonus: BonusOut | None
    assumptions: list[str]
