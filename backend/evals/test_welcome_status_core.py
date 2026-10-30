"""Welcome-window arithmetic and honesty rules (spec 18 §2-3), pure computation.

These pin the risks that matter for a feature that tells someone where their welcome
bonus stands: a points bonus never valued by guesswork, unknown inputs staying
unknown, travel dates never standing in for payment dates, and the report never touching
the optimizer's assignments.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest

from core.db import DB_PATH, KnowledgeBase, load_kb
from core.models import (
    AppliedOffer,
    Channel,
    LineAssignment,
    RedemptionPath,
    SpendCategory,
    SpendLineItem,
)
from evals.welcome_support import synthetic_offer
from welcome.catalog import OfferCatalog, OfferSelection
from welcome.models import CLOSING_SOON_DAYS, CardAcquisitionOffer, WelcomeWindowReport
from welcome.status import StoredPlan, compute_welcome_status

CARD = "hdfc-infinia"
OPENED = date(2026, 10, 1)
AS_OF = date(2026, 10, 24)
TRIP_START = date(2026, 11, 1)
TRIP_END = date(2026, 11, 5)


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return load_kb(DB_PATH)


def _assignment(
    line_id: str,
    amount: int,
    channel: Channel,
    *,
    card_id: str = CARD,
    discount: int = 0,
    currency: str = "INR",
) -> LineAssignment:
    return LineAssignment(
        line=SpendLineItem(
            id=line_id,
            label=line_id,
            category=SpendCategory.FLIGHTS,
            amount_minor=amount,
            currency=currency,
            available_channels=[channel],
        ),
        card_id=card_id,
        channel=channel,
        offers_applied=(
            [AppliedOffer(offer_id="o1", discount_minor=discount, stacking_class="bank_offer")]
            if discount
            else []
        ),
        points_earned=0,
        points_value_minor=0,
        assumed_redemption=RedemptionPath.CASHBACK,
        forex_fee_minor=0,
        benefit_minor=0,
    )


def _plan(
    assignments: list[LineAssignment],
    *,
    start: date = TRIP_START,
    end: date = TRIP_END,
    wallet: list[str] | None = None,
) -> StoredPlan:
    return StoredPlan(
        trip_id="t1",
        revision=1,
        computed_at="2026-10-24T00:00:00+00:00",
        trip_start_date=start,
        trip_end_date=end,
        plan_booking_date=AS_OF,
        currency="INR",
        assignments=assignments,
        planned_wallet_card_ids=[CARD] if wallet is None else wallet,
    )


def _run(
    kb: KnowledgeBase,
    *,
    plan: StoredPlan | None = None,
    offer: CardAcquisitionOffer | None = None,
    opened_on: date | None = OPENED,
    as_of: date = AS_OF,
    prior: int | None = None,
    duplicate: bool = False,
    card_id: str = CARD,
) -> WelcomeWindowReport:
    offer = offer or synthetic_offer(card_id)
    selection = OfferCatalog([offer]).select_offer(card_id, opened_on)
    return compute_welcome_status(
        wallet_entry_id="w1",
        card_id=card_id,
        opened_on=opened_on,
        kb=kb,
        selection=selection,
        plan=plan or _plan([_assignment("flight", 100, Channel.BANK_PORTAL)]),
        as_of=as_of,
        prior_spend_minor=prior,
        duplicate_card_entries=duplicate,
    )


def _codes(report: WelcomeWindowReport) -> set[str]:
    return {item.code for item in report.limitations}


# --- bonus: stated as the offer states it; never valued by guesswork ---------- #
#
# The data model keys point valuations by CARD and has no verified link from a card to a
# points program, so a points bonus cannot be turned into money by matching
# ``bonus_currency_id`` to a valuation row. It must stay ``None`` (never 0) with a typed
# limitation while the stated points and the offer's provenance are preserved.


def test_a_points_bonus_is_not_valued_by_borrowing_the_cards_valuation(
    kb: KnowledgeBase,
) -> None:
    # The demonstrated defect: an offer naming an unrelated program ("some-airline-miles")
    # was valued at the card's INR 1.00/pt portal valuation (10_000 pts -> 1_000_000).
    for currency_id in ("some-airline-miles", "synthetic-card-points"):
        offer = synthetic_offer(bonus_currency_id=currency_id, bonus_points=10_000)
        report = _run(kb, offer=offer)
        assert report.bonus is not None
        assert report.bonus.bonus_value_minor is None, currency_id
        assert "POINTS_PROGRAM_NOT_ESTABLISHED" in _codes(report)


def test_an_offer_naming_the_cards_own_program_id_is_still_unvalued_without_a_mapping(
    kb: KnowledgeBase,
) -> None:
    # "hdfc-reward-points" is the id wallet entries use for this card's points. Nothing in
    # the data model verifies that link, so even this looks-right id must not be trusted.
    offer = synthetic_offer("hdfc-infinia", bonus_currency_id="hdfc-reward-points")
    report = _run(kb, offer=offer)
    assert report.bonus is not None
    assert report.bonus.bonus_value_minor is None
    assert "POINTS_PROGRAM_NOT_ESTABLISHED" in _codes(report)
    # axis-atlas has a valuation too (INR 0.80/pt); it is equally unused.
    atlas_offer = synthetic_offer("axis-atlas", bonus_points=12_345)
    atlas = _run(kb, offer=atlas_offer, card_id="axis-atlas")
    assert atlas.bonus is not None and atlas.bonus.bonus_value_minor is None


def test_an_unvalued_points_bonus_keeps_the_stated_points_program_and_provenance(
    kb: KnowledgeBase,
) -> None:
    offer = synthetic_offer(bonus_points=25_000, bonus_currency_id="some-airline-miles")
    report = _run(kb, offer=offer)
    assert report.bonus is not None
    assert report.bonus.bonus_points == 25_000
    assert report.bonus.bonus_currency_id == "some-airline-miles"
    assert report.bonus.bonus_flat_minor is None
    assert report.offer is not None
    assert report.offer.provenance.verification_status == "synthetic_fixture"
    assert report.offer.provenance.source_url == offer.provenance.source_url
    assert report.offer.bonus_points == 25_000
    # The status itself is unaffected by the bonus being unvalued.
    assert report.status == "active" and report.window_closes_on is not None


def test_a_card_with_no_valuation_at_all_is_equally_unvalued(kb: KnowledgeBase) -> None:
    offer = synthetic_offer("no-such-card")
    report = _run(kb, offer=offer, card_id="no-such-card")
    assert report.bonus is not None
    assert report.bonus.bonus_value_minor is None
    assert "POINTS_PROGRAM_NOT_ESTABLISHED" in _codes(report)


def test_flat_bonus_is_carried_unvalued_and_unchanged(kb: KnowledgeBase) -> None:
    offer = synthetic_offer(
        bonus_points=None, bonus_currency_id=None, bonus_flat_minor=250_000
    )
    report = _run(kb, offer=offer)
    assert report.bonus is not None
    assert report.bonus.bonus_value_minor == 250_000
    assert report.bonus.bonus_flat_minor == 250_000
    assert report.bonus.bonus_points is None and report.bonus.bonus_currency_id is None
    assert "POINTS_PROGRAM_NOT_ESTABLISHED" not in _codes(report)


# --- unknown stays unknown ------------------------------------------------- #


def test_missing_open_date_is_unknown_and_never_guessed(kb: KnowledgeBase) -> None:
    report = _run(kb, opened_on=None, prior=0)
    assert report.status == "unknown"
    assert report.opened_on is None
    assert report.window_closes_on is None
    assert report.days_remaining is None
    assert "OPENED_ON_UNKNOWN" in _codes(report)
    # The offer's minimum is still stated, but nothing is counted against a window.
    assert report.min_spend_minor == 5_000_000
    assert report.conditional_trip_spend_minor == 0
    assert report.trip_alone_clears_minimum_if_conditions_hold is None
    assert {line.assessment for line in report.lines} == {"window_unknown"}


def test_missing_prior_spend_is_not_zero(kb: KnowledgeBase) -> None:
    unknown = _run(kb, prior=None)
    zero = _run(kb, prior=0)
    assert unknown.qualifying_spend_to_date_minor is None
    assert unknown.shortfall_minor is None
    assert unknown.shortfall_after_conditional_trip_minor is None
    assert "PRIOR_SPEND_UNKNOWN" in _codes(unknown)
    # An explicit zero is a statement; an omitted figure is not.
    assert zero.shortfall_minor == 5_000_000
    assert "PRIOR_SPEND_UNKNOWN" not in _codes(zero)


def test_a_future_open_date_is_unknown_not_a_window(kb: KnowledgeBase) -> None:
    report = _run(kb, opened_on=AS_OF + timedelta(days=3))
    assert report.status == "unknown"
    assert report.window_closes_on is None
    assert "OPENED_ON_IN_FUTURE" in _codes(report)


# --- window dates and status ------------------------------------------------ #


def test_window_closes_on_open_date_plus_the_offers_days(kb: KnowledgeBase) -> None:
    report = _run(kb)
    assert report.window_closes_on == OPENED + timedelta(days=90)
    assert report.days_remaining == (OPENED + timedelta(days=90) - AS_OF).days


def test_status_boundaries(kb: KnowledgeBase) -> None:
    closes = OPENED + timedelta(days=90)
    cases = {
        closes - timedelta(days=CLOSING_SOON_DAYS + 1): "active",
        closes - timedelta(days=CLOSING_SOON_DAYS): "closing_soon",
        closes: "closing_soon",  # the closing day is still inside the window
        closes + timedelta(days=1): "expired",
    }
    for as_of, expected in cases.items():
        assert _run(kb, as_of=as_of).status == expected, as_of


def test_met_needs_the_users_own_figure_and_trip_spend_never_sets_it(kb: KnowledgeBase) -> None:
    # The plan alone could clear the minimum, but the status never claims "met" from it.
    big = _plan([_assignment("flight", 9_000_000, Channel.BANK_PORTAL)])
    assert _run(kb, plan=big, prior=None).status == "active"
    assert _run(kb, plan=big, prior=4_999_999).status == "active"
    assert _run(kb, plan=big, prior=5_000_000).status == "met"
    # Entered spend that meets the minimum is "met" even after the window closed.
    late = OPENED + timedelta(days=200)
    assert _run(kb, as_of=late, prior=5_000_000).status == "met"
    assert _run(kb, as_of=late, prior=1).status == "expired"


# --- travel dates are not payment dates ------------------------------------- #


def test_trip_inside_the_window_could_count_but_is_never_called_confirmed(
    kb: KnowledgeBase,
) -> None:
    plan = _plan(
        [
            _assignment("flight", 4_000_000, Channel.BANK_PORTAL),
            _assignment("dining", 1_500_000, Channel.POS_ABROAD),
        ]
    )
    report = _run(kb, plan=plan, prior=0)
    assert report.conditional_trip_spend_minor == 5_500_000
    assert report.shortfall_after_conditional_trip_minor == 0
    assert report.trip_alone_clears_minimum_if_conditions_hold is True
    # There is no field or assessment that asserts confirmed qualifying spend.
    assert {line.assessment for line in report.lines} == {"could_count_if_paid_by_close"}
    assert any("never as confirmed" in note for note in report.assumptions)
    # The user's prior figure must not already include this plan's bookings.
    assert any("count that spend twice" in note for note in report.assumptions)


def test_on_trip_spend_after_the_window_does_not_count(kb: KnowledgeBase) -> None:
    # Window closes 2026-12-30; this trip is in 2027.
    plan = _plan(
        [_assignment("dining", 9_000_000, Channel.POS_ABROAD)],
        start=date(2027, 1, 10),
        end=date(2027, 1, 15),
    )
    report = _run(kb, plan=plan, prior=0)
    assert report.conditional_trip_spend_minor == 0
    assert report.lines[0].assessment == "outside_window"
    assert report.trip_alone_clears_minimum_if_conditions_hold is False


def test_trip_straddling_the_close_is_unknown_not_counted(kb: KnowledgeBase) -> None:
    plan = _plan(
        [_assignment("dining", 9_000_000, Channel.POS_ABROAD)],
        start=date(2026, 12, 28),
        end=date(2027, 1, 3),
    )
    report = _run(kb, plan=plan, prior=0)
    assert report.lines[0].assessment == "straddles_window_unknown"
    assert report.conditional_trip_spend_minor == 0


def test_a_trip_before_the_card_was_opened_does_not_count(kb: KnowledgeBase) -> None:
    plan = _plan(
        [_assignment("dining", 9_000_000, Channel.POS_ABROAD)],
        start=date(2026, 9, 10),
        end=date(2026, 9, 15),
    )
    assert _run(kb, plan=plan).lines[0].assessment == "outside_window"


def test_advance_booking_after_the_close_does_not_count_even_if_travel_is_in_window(
    kb: KnowledgeBase,
) -> None:
    # Travel dates sit inside the window, but "today" is past the close: the flight cannot
    # be paid inside the window any more, while on-trip spend still falls within it only
    # by travel dates. The two are judged on different dates.
    after_close = OPENED + timedelta(days=91)
    plan = _plan(
        [
            _assignment("flight", 4_000_000, Channel.BANK_PORTAL),
            _assignment("dining", 1_000_000, Channel.POS_ABROAD),
        ],
        start=OPENED + timedelta(days=20),
        end=OPENED + timedelta(days=25),
    )
    report = _run(kb, plan=plan, as_of=after_close, prior=0)
    by_id = {line.line_id: line for line in report.lines}
    assert by_id["flight"].assessment == "outside_window"
    assert by_id["flight"].timing_basis == "advance_booking"
    assert by_id["dining"].timing_basis == "on_trip"


# --- what is counted --------------------------------------------------------- #


def test_only_this_cards_assignments_are_counted(kb: KnowledgeBase) -> None:
    plan = _plan(
        [
            _assignment("mine", 3_000_000, Channel.BANK_PORTAL),
            _assignment("theirs", 8_000_000, Channel.BANK_PORTAL, card_id="sbi-cashback"),
        ],
        wallet=[CARD, "sbi-cashback"],
    )
    report = _run(kb, plan=plan, prior=0)
    assert report.trip_assigned_spend_minor == 3_000_000
    assert [line.line_id for line in report.lines] == ["mine"]


def test_instant_discounts_reduce_the_counted_amount_and_never_below_zero(
    kb: KnowledgeBase,
) -> None:
    plan = _plan(
        [
            _assignment("a", 1_000_000, Channel.OTA_GENERIC, discount=250_000),
            _assignment("b", 100, Channel.OTA_GENERIC, discount=900),
        ]
    )
    report = _run(kb, plan=plan, prior=0)
    by_id = {line.line_id: line for line in report.lines}
    assert by_id["a"].amount_minor == 1_000_000
    assert by_id["a"].counted_minor == 750_000
    assert by_id["b"].counted_minor == 0
    assert report.trip_assigned_spend_minor == 1_000_100
    assert report.trip_counted_spend_minor == 750_000


def test_a_currency_mismatch_counts_nothing_instead_of_converting(kb: KnowledgeBase) -> None:
    plan = _plan([_assignment("flight", 9_000_000, Channel.BANK_PORTAL, currency="USD")])
    report = _run(kb, plan=plan, prior=0)
    assert report.conditional_trip_spend_minor == 0
    assert report.lines[0].assessment == "currency_mismatch"
    assert "CURRENCY_MISMATCH" in _codes(report)
    # Unattributable spend leaves the trip-dependent conclusions unknown, not False / full.
    assert report.trip_alone_clears_minimum_if_conditions_hold is None
    assert report.shortfall_after_conditional_trip_minor is None
    assert report.shortfall_minor == 5_000_000


def test_two_entries_for_one_product_attribute_no_spend_to_either(kb: KnowledgeBase) -> None:
    report = _run(kb, prior=0, duplicate=True)
    assert report.conditional_trip_spend_minor == 0
    assert {line.assessment for line in report.lines} == {"ambiguous_card_entry"}
    assert "DUPLICATE_CARD_ENTRIES" in _codes(report)
    assert report.trip_alone_clears_minimum_if_conditions_hold is None
    assert report.shortfall_after_conditional_trip_minor is None


def test_a_card_the_plan_never_used_reports_zero_and_says_why(kb: KnowledgeBase) -> None:
    plan = _plan([_assignment("x", 1, Channel.BANK_PORTAL, card_id="sbi-cashback")], wallet=[])
    report = _run(kb, plan=plan, prior=0)
    assert report.trip_assigned_spend_minor == 0
    assert report.lines == []
    assert "CARD_NOT_IN_PLANNED_WALLET" in _codes(report)


def test_zero_amount_lines_are_counted_as_omitted_not_dropped_silently(
    kb: KnowledgeBase,
) -> None:
    plan = _plan(
        [
            _assignment("real", 500, Channel.BANK_PORTAL),
            _assignment("empty1", 0, Channel.POS_ABROAD),
            _assignment("empty2", 0, Channel.POS_ABROAD),
        ]
    )
    report = _run(kb, plan=plan, prior=0)
    assert [line.line_id for line in report.lines] == ["real"]
    assert report.omitted_zero_amount_lines == 2


# --- the optimizer is untouched ---------------------------------------------- #


def test_the_report_does_not_mutate_or_add_to_the_assignments(kb: KnowledgeBase) -> None:
    assignments = [
        _assignment("flight", 4_000_000, Channel.BANK_PORTAL),
        _assignment("dining", 1_000_000, Channel.POS_ABROAD),
    ]
    before: list[Any] = [a.model_dump() for a in assignments]
    report = _run(kb, plan=_plan(assignments), prior=0)
    assert [a.model_dump() for a in assignments] == before
    # The bonus is reported beside the spend, never folded into it.
    assert report.trip_assigned_spend_minor == 5_000_000
    # A flat bonus is reported beside the spend, never folded into it.
    flat_offer = synthetic_offer(
        bonus_points=None, bonus_currency_id=None, bonus_flat_minor=1_000_000
    )
    flat = _run(kb, offer=flat_offer, plan=_plan(assignments), prior=0)
    assert flat.bonus is not None and flat.bonus.bonus_value_minor == 1_000_000
    assert flat.trip_assigned_spend_minor == 5_000_000
    assert any("does not change them" in note for note in report.assumptions)


def test_no_selection_still_reports_the_trip_side(kb: KnowledgeBase) -> None:
    plan = _plan([_assignment("flight", 100, Channel.BANK_PORTAL)])
    report = compute_welcome_status(
        wallet_entry_id="w1",
        card_id=CARD,
        opened_on=OPENED,
        kb=kb,
        selection=OfferSelection(None, "NO_APPROVED_OFFER", 0),
        plan=plan,
        as_of=AS_OF,
        prior_spend_minor=None,
        duplicate_card_entries=False,
    )
    assert report.status == "unknown"
    assert report.offer is None and report.bonus is None
    assert report.trip_assigned_spend_minor == 100
    assert "NO_APPROVED_OFFER" in _codes(report)
