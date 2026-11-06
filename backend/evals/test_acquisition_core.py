"""Unit tests for Card Acquisition assessment core (spec 18 §3-5, Case B).

Pure and deterministic tests verifying all 5 gates from spec 18 §4:
1. earliest_usable_date <= first_bookable_spend_date
2. min_spend_minor <= trip_eligible_spend_minor
3. all trip spend counted in (2) falls on or before window_closes_on
4. net_first_year_minor > 0
5. offer.valid_to >= booking_date

Plus:
- unknown payment timing is refused with a typed limitation (never guessed)
- already-held cards are excluded
- unestablished points valuations are withheld
- held-card strategy remains complete, separate, and unchanged
- verbatim framing and exclusions integrity
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from core.db import DB_PATH, KnowledgeBase, load_kb
from core.models import (
    Channel,
    CostedTrip,
    OptimizationPrefs,
    SpendCategory,
    SpendLineItem,
    UserWallet,
)
from core.optimizer import optimize
from evals.welcome_support import synthetic_offer
from welcome.acquisition import compute_acquisition_assessment
from welcome.catalog import OfferCatalog
from welcome.models import (
    AcquisitionAssessmentIn,
    CardAcquisitionOffer,
    PaymentTimingIn,
)
from welcome.status import StoredPlan

BOOKING_DATE = date(2026, 10, 24)
TRIP_START = date(2026, 11, 1)
TRIP_END = date(2026, 11, 5)
HELD_CARD = "hdfc-infinia"
CANDIDATE_CARD = "axis-atlas"


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_kb(DB_PATH)


def _make_stored_plan(
    kb: KnowledgeBase,
    *,
    held_cards: list[str] | None = None,
    flight_amount: int = 4_000_000,
    hotel_amount: int = 3_000_000,
) -> StoredPlan:
    """Create a realistic StoredPlan using the real optimizer for held cards."""
    cards = [HELD_CARD] if held_cards is None else held_cards
    wallet = UserWallet(card_ids=cards, points_balances={})
    lines = [
        SpendLineItem(
            id="flt-1",
            category=SpendCategory.FLIGHTS,
            amount_minor=flight_amount,
            currency="INR",
            available_channels=[Channel.DIRECT_AIRLINE, Channel.OTA_GENERIC],
            label="Flights DEL-SIN",
        ),
        SpendLineItem(
            id="htl-1",
            category=SpendCategory.HOTELS,
            amount_minor=hotel_amount,
            currency="INR",
            available_channels=[Channel.DIRECT_HOTEL, Channel.OTA_GENERIC],
            label="Hotel Singapore",
        ),
    ]
    trip = CostedTrip(
        id="t-1",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=BOOKING_DATE,
        trip_start_date=TRIP_START,
        lines=lines,
    )
    prefs = OptimizationPrefs()
    result = optimize(trip, wallet, kb, prefs)
    return StoredPlan(
        trip_id="trip-001",
        revision=1,
        computed_at="2026-10-24T12:00:00+00:00",
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        plan_booking_date=BOOKING_DATE,
        currency="INR",
        assignments=result.assignments,
        planned_wallet_card_ids=cards,
        costed_trip=trip,
        optimizer_result=result,
        planned_wallet=wallet,
        optimization_prefs=prefs,
    )


def _flat_offer(
    card_id: str = CANDIDATE_CARD,
    *,
    bonus_flat: int = 1_500_000,
    min_spend: int = 2_000_000,
    window_days: int = 90,
    approval_days: int = 7,
    in_hand_days: int = 7,
    annual_fee: int = 500_000,
    **overrides: Any,
) -> CardAcquisitionOffer:
    return synthetic_offer(
        card_id=card_id,
        bonus_points=None,
        bonus_currency_id=None,
        bonus_flat_minor=bonus_flat,
        min_spend_minor=min_spend,
        spend_window_days=window_days,
        expected_approval_days=approval_days,
        expected_card_in_hand_days=in_hand_days,
        annual_fee_minor=annual_fee,
        **overrides,
    )


# --------------------------------------------------------------------------- #
# Gate 1: Timing & Lead Time                                                  #
# --------------------------------------------------------------------------- #


def test_gate1_timing_lead_time_failure_reported_with_narrow_message(
    kb: KnowledgeBase,
) -> None:
    plan = _make_stored_plan(kb)
    # 7 approval + 7 in-hand = 14 days lead time. Earliest usable = 2026-11-07.
    offer = _flat_offer(approval_days=7, in_hand_days=7)
    catalog = OfferCatalog([offer])

    # First bookable spend is on 2026-11-05 (only 12 days lead time) -> fails Gate 1
    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,  # 2026-10-24
        first_bookable_spend_date=date(2026, 11, 5),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    refusal = report.refusals[0]
    assert refusal.reason == "TIMING_GATE_FAILED"
    assert refusal.card_id == CANDIDATE_CARD
    assert "~14 days' lead time you don't have" in refusal.message
    assert "card expected on 2026-11-07" in refusal.message
    assert "after first spend date 2026-11-05" in refusal.message


def test_gate1_timing_lead_time_success(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    # Earliest usable = 2026-11-07
    offer = _flat_offer(approval_days=7, in_hand_days=7)
    catalog = OfferCatalog([offer])

    # First bookable spend is on 2026-11-10 (> 2026-11-07) -> passes Gate 1
    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 1
    assert len(report.refusals) == 0
    sug = report.suggestions[0]
    assert sug.card_id == CANDIDATE_CARD
    assert sug.timing.lead_time_sufficient is True
    assert sug.timing.earliest_usable_date == date(2026, 11, 7)


# --------------------------------------------------------------------------- #
# Unknown Payment Timing                                                      #
# --------------------------------------------------------------------------- #


def test_unknown_payment_timing_refuses_suggestion(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    offer = _flat_offer()
    catalog = OfferCatalog([offer])

    # payment_timing is None
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=None,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "PAYMENT_TIMING_UNKNOWN"
    assert any(lim.code == "PAYMENT_TIMING_UNKNOWN" for lim in report.limitations)


# --------------------------------------------------------------------------- #
# Gate 2: Minimum Spend                                                       #
# --------------------------------------------------------------------------- #


def test_gate2_minimum_spend_not_met_is_refused(kb: KnowledgeBase) -> None:
    # Trip only has 1,000,000 spend total
    plan = _make_stored_plan(kb, flight_amount=500_000, hotel_amount=500_000)
    # Offer requires 5,000,000 min spend
    offer = _flat_offer(min_spend=5_000_000)
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "MINIMUM_SPEND_NOT_MET"
    assert "less than the required minimum spend" in report.refusals[0].message


# --------------------------------------------------------------------------- #
# Gate 3: Spend Window                                                        #
# --------------------------------------------------------------------------- #


def test_gate3_spend_past_window_close_is_refused(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    # 14 days lead time + 10 days spend window = closes on 2026-11-17
    offer = _flat_offer(window_days=10, approval_days=7, in_hand_days=7)
    catalog = OfferCatalog([offer])

    # Latest spend date is 2026-11-20 (past 2026-11-17)
    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
        latest_spend_date=date(2026, 11, 20),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "SPEND_WINDOW_EXCEEDED"
    assert "extends past the offer spend window closing date" in report.refusals[0].message


# --------------------------------------------------------------------------- #
# Gate 4: Positive Net Value                                                  #
# --------------------------------------------------------------------------- #


def test_gate4_nonpositive_net_value_is_refused(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    # Bonus = 100,000 minor, fee = 1,000,000 minor -> net is negative!
    offer = _flat_offer(bonus_flat=100_000, annual_fee=1_000_000)
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "NONPOSITIVE_NET_VALUE"
    assert "is not greater than zero" in report.refusals[0].message


# --------------------------------------------------------------------------- #
# Gate 5: Offer Validity                                                      #
# --------------------------------------------------------------------------- #


def test_gate5_expired_offer_is_refused(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    # Offer valid_to is 2026-10-01 (before booking date 2026-10-24)
    offer = _flat_offer(valid_to=date(2026, 10, 1))
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "OFFER_EXPIRED"


# --------------------------------------------------------------------------- #
# Points Bonus without Verified Program Link                                  #
# --------------------------------------------------------------------------- #


def test_points_bonus_without_mapping_is_withheld(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    # Points bonus offer
    offer = synthetic_offer(
        card_id=CANDIDATE_CARD,
        bonus_points=25_000,
        bonus_currency_id="some-airline-miles",
        annual_fee_minor=500_000,
    )
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "POINTS_PROGRAM_NOT_ESTABLISHED"
    assert any(lim.code == "POINTS_PROGRAM_NOT_ESTABLISHED" for lim in report.limitations)


# --------------------------------------------------------------------------- #
# Already-Held Cards Excluded                                                 #
# --------------------------------------------------------------------------- #


def test_already_held_card_is_refused(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb, held_cards=[HELD_CARD])
    offer = _flat_offer(card_id=HELD_CARD)
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=HELD_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "ALREADY_HELD_CARD"
    assert "already held in your wallet" in report.refusals[0].message


# --------------------------------------------------------------------------- #
# Held-Card Strategy Preserved and Separate                                   #
# --------------------------------------------------------------------------- #


def test_held_card_strategy_remains_unchanged(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    offer = _flat_offer()
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert report.held_cards_strategy.card_ids == [HELD_CARD]
    assert report.held_cards_strategy.gross_minor == plan.optimizer_result.gross_minor  # type: ignore[union-attr]
    assert (
        report.held_cards_strategy.effective_cost_minor
        == plan.optimizer_result.effective_cost_minor  # type: ignore[union-attr]
    )
    assert report.held_cards_strategy.currency == "INR"


# --------------------------------------------------------------------------- #
# Verbatim Phrasing & Exclusions Integrity                                    #
# --------------------------------------------------------------------------- #


def test_qualifying_suggestion_has_verbatim_framing_and_exclusions(
    kb: KnowledgeBase,
) -> None:
    plan = _make_stored_plan(kb)
    exclusions = [
        "Not available to customers who held any Axis Bank credit card in the preceding 12 months.",
        "Primary cardholder must be an Indian resident aged 21 to 65.",
    ]
    offer = _flat_offer(eligibility_exclusions=exclusions)
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 1
    sug = report.suggestions[0]

    # Required phrasing pattern per spec 18 §5:
    # "This card's current welcome bonus would be worth ₹X on this trip if you held it"
    assert sug.verbatim_framing.startswith("This card's current welcome bonus would be worth")
    assert sug.verbatim_framing.endswith("on this trip if you held it")
    assert "you should apply" not in sug.verbatim_framing.lower()
    assert "you should get" not in sug.verbatim_framing.lower()

    # Exclusions are rendered verbatim
    assert sug.eligibility_exclusions == exclusions


# --------------------------------------------------------------------------- #
# Currency Mismatch Refusal                                                   #
# --------------------------------------------------------------------------- #


def test_currency_mismatch_is_refused(kb: KnowledgeBase) -> None:
    plan = _make_stored_plan(kb)
    offer = _flat_offer(currency="USD")
    catalog = OfferCatalog([offer])

    pt = PaymentTimingIn(
        booking_date=BOOKING_DATE,
        first_bookable_spend_date=date(2026, 11, 10),
    )
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids={HELD_CARD},
        payload=AcquisitionAssessmentIn(
            candidate_card_id=CANDIDATE_CARD,
            payment_timing=pt,
        ),
    )
    assert len(report.suggestions) == 0
    assert len(report.refusals) == 1
    assert report.refusals[0].reason == "CURRENCY_MISMATCH"
