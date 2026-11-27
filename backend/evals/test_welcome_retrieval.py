"""OPT-1 tests: zero-bias candidate retrieval, sound integer UBs, and lazy max-heap pruning.

Verifies:
1. 500-card multi-tier catalog brute-force equivalence: lazy max-heap top-m matches
   brute-force evaluation across all 500 cards 100% identically while evaluating <10%.
2. Saturated held-wallet cap pool + mismatched block-size + shared pool soundness:
   ``UB(c | W) >= net_first_year_minor(c | W)`` unconditionally across randomized inputs.
3. Hard eligibility filters (``home_country``, ``open_for_application``, ``currency``,
   ``already_held``, ``valid_to < booking_date``, ``min_spend_minor > total_spend``).
4. Exact tie-breaking at threshold ``T_m`` (zero affiliate bias, order-independent).
5. High-spend ``>= 10^9`` minor integer arithmetic safety + AST zero-float verification.
6. Repeated-run bit-for-bit determinism and backwards-compatible ``acquisition.py`` wiring.
"""

from __future__ import annotations

import ast
import random
from datetime import date
from pathlib import Path
from typing import Literal

from core.db import KnowledgeBase
from core.models import (
    Card,
    Channel,
    CostedTrip,
    EarnRate,
    Offer,
    OfferKind,
    OptimizationPrefs,
    PointValuation,
    Provenance,
    RedemptionPath,
    RewardCap,
    RewardRule,
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
from welcome.retrieval import (
    _max_earn_points_ub,
    build_wallet_baseline,
    compute_card_upper_bound,
    retrieve_top_candidates,
)
from welcome.status import StoredPlan

BOOKING_DATE = date(2026, 11, 1)
TRIP_START = date(2026, 11, 20)
TRIP_END = date(2026, 11, 26)
FIRST_SPEND = date(2026, 11, 18)


def _prov() -> Provenance:
    return Provenance(
        source_url="https://example.invalid/opt1-test",
        source_type="manual_curation",
        last_verified=BOOKING_DATE,
        verified_by="SYNTHETIC_OPT1_TEST",
        needs_verification=False,
        confidence=1.0,
    )


def _build_500_card_catalog(
    *,
    seed: int = 42,
    trip_lines: list[SpendLineItem] | None = None,
    held_cap_max_points: int | None = None,
) -> tuple[KnowledgeBase, OfferCatalog, StoredPlan, set[str], list[SpendLineItem]]:
    """Build a deterministic 500-unheld-card + held-wallet multi-tier benchmark."""
    rng = random.Random(seed)
    prov = _prov()

    # Held card: strong travel card (either uncapped or cap-saturated depending on test)
    held_card = Card(
        id="held-flagship",
        issuer="Flagship Bank",
        network="visa",
        country="IN",
        name="Held Flagship Card",
        annual_fee_minor=1_000_000,
        fee_currency="INR",
        forex_markup_bp=200,
        forex_markup_tax_bp=1800,
        base_earn=EarnRate(points=5, per_amount_minor=15_000, currency="INR"),
        provenance=prov,
    )
    held_val = PointValuation(
        id="val-held-flagship",
        card_id="held-flagship",
        path=RedemptionPath.PORTAL_FLIGHTS,
        value_micro_major_per_point=1_000_000,  # ₹1.00 / pt -> 3.33% base
        currency="INR",
        provenance=prov,
    )
    held_rules: list[RewardRule] = [
        RewardRule(
            id="rule-held-portal",
            card_id="held-flagship",
            description="5x flights/hotels",
            earn=EarnRate(points=25, per_amount_minor=15_000, currency="INR"),
            categories=[SpendCategory.FLIGHTS, SpendCategory.HOTELS],
            channels=[Channel.BANK_PORTAL, Channel.DIRECT_AIRLINE, Channel.DIRECT_HOTEL],
            cap=(
                RewardCap(
                    max_points=held_cap_max_points,
                    period="statement_cycle",
                    shared_cap_group="portal",
                )
                if held_cap_max_points is not None
                else None
            ),
            provenance=prov,
        )
    ]

    cards: list[Card] = [held_card]
    rules: list[RewardRule] = list(held_rules)
    valuations: list[PointValuation] = [held_val]
    acq_offers: list[CardAcquisitionOffer] = []

    issuers = ["Axis", "HDFC", "ICICI", "SBI", "Amex"]
    networks: list[Literal["visa", "mastercard", "amex", "rupay", "diners"]] = [
        "visa",
        "mastercard",
        "amex",
    ]
    categories_pool = [
        SpendCategory.FLIGHTS,
        SpendCategory.HOTELS,
        SpendCategory.DINING,
        SpendCategory.GROCERY,
        SpendCategory.SHOPPING,
    ]

    for idx in range(500):
        card_id = f"cand-{idx:03d}"
        tier = idx % 10
        country: Literal["IN", "AE", "US"] = "IN"
        offer_currency = "INR"
        valid_to = date(2027, 6, 30)
        approval_days = 3
        in_hand_days = 4
        min_spend = 1_500_000

        if idx < 12:
            # Tier 1 (~2.4%): top-value acquisition candidates with high bonus & competitive earn
            bonus_flat = 2_200_000 + (12 - idx) * 100_000  # ₹22k - ₹33k
            annual_fee = 500_000
            base_pts = 5
            accel_pts = 20 + (idx % 4) * 5
            accel_cats = [SpendCategory.FLIGHTS, SpendCategory.HOTELS, SpendCategory.DINING]
            cap_pts: int | None = 15_000
        elif idx < 80:
            # Tier 2: competitive mid-tier candidates (moderate bonus, capped bonus categories)
            bonus_flat = rng.randint(400_000, 1_100_000)
            annual_fee = rng.randint(200_000, 600_000)
            base_pts = rng.randint(1, 3)
            accel_pts = rng.randint(4, 8)
            accel_cats = [rng.choice(categories_pool)]
            cap_pts = 2_500
        elif idx < 350:
            # Tier 3: mass-market / lower-tier cards (net positive small or zero)
            bonus_flat = rng.randint(50_000, 350_000)
            annual_fee = rng.randint(100_000, 400_000)
            base_pts = 1
            accel_pts = rng.randint(1, 3)
            accel_cats = [SpendCategory.GROCERY]  # not dominant on travel trip
            cap_pts = 1_000
        else:
            # Tier 4: ineligible or dominated cards (foreign country/currency, expired, high fee)
            sub_bucket = idx % 4
            if sub_bucket == 0:
                country = "US"
                offer_currency = "USD"
            elif sub_bucket == 1:
                valid_to = date(2026, 10, 1)  # expired before booking_date
            elif sub_bucket == 2:
                min_spend = 25_000_000  # clears total trip spend filter
            else:
                approval_days = 30  # fails lead time gate
            bonus_flat = rng.randint(300_000, 1_800_000)
            annual_fee = rng.randint(500_000, 2_500_000)
            base_pts = 2
            accel_pts = 4
            accel_cats = [SpendCategory.FLIGHTS]
            cap_pts = 2_000

        cards.append(
            Card(
                id=card_id,
                issuer=issuers[idx % len(issuers)],
                network=networks[idx % len(networks)],
                country=country,
                name=f"Candidate Card {idx:03d}",
                annual_fee_minor=annual_fee,
                fee_currency=offer_currency,
                forex_markup_bp=350 if idx >= 12 else 200,
                forex_markup_tax_bp=1800,
                base_earn=EarnRate(
                    points=base_pts, per_amount_minor=15_000, currency=offer_currency
                ),
                provenance=prov,
            )
        )
        valuations.append(
            PointValuation(
                id=f"val-{card_id}",
                card_id=card_id,
                path=RedemptionPath.CASHBACK,
                value_micro_major_per_point=1_000_000 if idx < 12 or tier < 5 else 500_000,
                currency=offer_currency,
                provenance=prov,
            )
        )
        rules.append(
            RewardRule(
                id=f"rule-{card_id}",
                card_id=card_id,
                description=f"Bonus category earn for {card_id}",
                earn=EarnRate(points=accel_pts, per_amount_minor=15_000, currency=offer_currency),
                categories=accel_cats,
                channels=None,
                cap=(
                    RewardCap(max_points=cap_pts, period="statement_cycle")
                    if cap_pts is not None
                    else None
                ),
                provenance=prov,
            )
        )
        acq_offers.append(
            synthetic_offer(
                id=f"acq-{card_id}",
                card_id=card_id,
                bonus_points=None,
                bonus_currency_id=None,
                bonus_flat_minor=bonus_flat,
                min_spend_minor=min_spend,
                spend_window_days=90,
                expected_approval_days=approval_days,
                expected_card_in_hand_days=in_hand_days,
                annual_fee_minor=annual_fee,
                currency=offer_currency,
                valid_to=valid_to,
            )
        )

    lines = trip_lines or [
        SpendLineItem(
            id="flt-1",
            label="Flights DEL-SIN",
            category=SpendCategory.FLIGHTS,
            amount_minor=4_000_000,
            currency="INR",
            available_channels=[Channel.DIRECT_AIRLINE, Channel.BANK_PORTAL, Channel.OTA_GENERIC],
        ),
        SpendLineItem(
            id="htl-1",
            label="Singapore Hotel",
            category=SpendCategory.HOTELS,
            amount_minor=3_000_000,
            currency="INR",
            available_channels=[Channel.DIRECT_HOTEL, Channel.BANK_PORTAL, Channel.OTA_GENERIC],
        ),
        SpendLineItem(
            id="din-1",
            label="Singapore Dining",
            category=SpendCategory.DINING,
            amount_minor=1_500_000,
            currency="INR",
            available_channels=[Channel.POS_ABROAD, Channel.POS_DOMESTIC],
        ),
    ]

    trip = CostedTrip(
        id="trip-500",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=BOOKING_DATE,
        trip_start_date=TRIP_START,
        lines=lines,
    )

    wallet = UserWallet(card_ids=["held-flagship"], points_balances={})
    prefs = OptimizationPrefs(objective="max_savings")
    kb = KnowledgeBase(
        cards=cards,
        reward_rules=rules,
        offers=[],
        point_valuations=valuations,
    )
    held_result = optimize(trip, wallet, kb, prefs)
    plan = StoredPlan(
        trip_id="trip-500",
        revision=1,
        computed_at="2026-11-01T12:00:00+00:00",
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        plan_booking_date=BOOKING_DATE,
        currency="INR",
        assignments=held_result.assignments,
        planned_wallet_card_ids=["held-flagship"],
        costed_trip=trip,
        optimizer_result=held_result,
        planned_wallet=wallet,
        optimization_prefs=prefs,
    )
    catalog = OfferCatalog(acq_offers)
    return kb, catalog, plan, {"held-flagship"}, lines


def _brute_force_top_m(
    *,
    kb: KnowledgeBase,
    catalog: OfferCatalog,
    plan: StoredPlan,
    held_ids: set[str],
    pt: PaymentTimingIn,
    top_m: int,
    home_country: Literal["IN", "AE", "US"] | None = None,
) -> list[tuple[str, int, int]]:
    """Evaluate EVERY unheld card sequentially without UB pruning, returning top-m summary."""
    report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payload=AcquisitionAssessmentIn(candidate_card_id=None, payment_timing=pt),
        top_m=None,
        home_country=home_country,
    )
    return [
        (s.card_id, s.net_first_year_minor, s.trip_earn_delta_minor)
        for s in report.suggestions[:top_m]
    ]


# --------------------------------------------------------------------------- #
# 1. Exactness Proof on 500-Card Multi-Tier Catalog (< 10% Evaluations)       #
# --------------------------------------------------------------------------- #


def test_500_card_lazy_retrieval_matches_brute_force_100pct_with_under_10pct_evals() -> None:
    kb, catalog, plan, held_ids, _lines = _build_500_card_catalog(seed=101)
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    for top_m in (1, 3, 5):
        brute_top = _brute_force_top_m(
            kb=kb, catalog=catalog, plan=plan, held_ids=held_ids, pt=pt, top_m=top_m,
            home_country="IN",
        )
        lazy_res = retrieve_top_candidates(
            as_of=BOOKING_DATE,
            kb=kb,
            catalog=catalog,
            plan=plan,
            user_held_card_ids=held_ids,
            payment_timing=pt,
            top_m=top_m,
            home_country="IN",
        )
        lazy_top = [
            (s.card_id, s.net_first_year_minor, s.trip_earn_delta_minor)
            for s in lazy_res.suggestions
        ]

        assert lazy_top == brute_top
        assert len(lazy_top) == top_m
        assert lazy_res.stats.total_catalog_cards == 500
        assert lazy_res.stats.exact_evaluations < 50  # strictly < 10% of 500 cards
        assert lazy_res.stats.ub_pruned_ratio_bp >= 9_000


def test_compute_acquisition_assessment_top_m_wiring_matches_brute_force() -> None:
    kb, catalog, plan, held_ids, _lines = _build_500_card_catalog(seed=2026)
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    full_report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payload=AcquisitionAssessmentIn(candidate_card_id=None, payment_timing=pt),
        top_m=None,
    )
    pruned_report = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payload=AcquisitionAssessmentIn(candidate_card_id=None, payment_timing=pt),
        top_m=5,
    )

    assert len(pruned_report.suggestions) == 5
    assert pruned_report.suggestions == full_report.suggestions[:5]
    assert pruned_report.held_cards_strategy == full_report.held_cards_strategy


# --------------------------------------------------------------------------- #
# 2. Soundness Proofs: Saturated Held Caps, Mismatched Blocks & Shared Pools  #
# --------------------------------------------------------------------------- #


def test_saturated_held_wallet_cap_pool_soundness_matches_brute_force() -> None:
    """When held wallet saturates a cap pool, liberating capacity helps another line.

    Verifies that ``TotalHeldSlack(W)`` keeps UB >= exact delta unconditionally so
    the lazy heap matches brute force 100% identically even under held pool saturation.
    """
    kb, catalog, plan, held_ids, _lines = _build_500_card_catalog(
        seed=77,
        held_cap_max_points=5_000,  # Held flagship hits cap between flights & hotels!
    )
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    brute_top = _brute_force_top_m(
        kb=kb, catalog=catalog, plan=plan, held_ids=held_ids, pt=pt, top_m=5
    )
    lazy_res = retrieve_top_candidates(
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payment_timing=pt,
        top_m=5,
    )
    lazy_top = [
        (s.card_id, s.net_first_year_minor, s.trip_earn_delta_minor)
        for s in lazy_res.suggestions
    ]
    assert lazy_top == brute_top
    assert lazy_res.stats.exact_evaluations < 50


def test_mismatched_block_size_partial_cap_exhaustion_is_strictly_bounded() -> None:
    """Regression against F-core's mismatched block-size edge case.

    Rule earns 3 pts per 10,000 (cap 3), base earns 29 pts per 100,000. On post = 100,000,
    exhausted pool earns 29 pts while partial pool earns 3 pts. Fractional knapsack UB must
    bound ALL possible pool states (>= 29 pts).
    """
    prov = _prov()
    rule = RewardRule(
        id="r-mismatch",
        card_id="c-mismatch",
        description="3 per 10k capped at 3",
        earn=EarnRate(points=3, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.DINING],
        cap=RewardCap(max_points=3, period="statement_cycle"),
        provenance=prov,
    )
    base = EarnRate(points=29, per_amount_minor=100_000, currency="INR")
    assert _max_earn_points_ub(100_000, [rule], base) >= 29


def test_review_regressions_divisible_cap_fallthrough_and_uncapped_slower_than_base() -> None:
    """Regressions for independent review Critical Findings 1 & 2.

    Case A (Finding 1): A capped rule whose block size is divisible by base_earn's block
    size can drop ``remaining % rule.per_amount_minor`` when non-binding, yet fall through
    and earn strictly MORE points on the remainder when the cap binds on line 2.
    Case B (Finding 2): A card with both a capped rule and an uncapped rule slower than
    ``base_earn`` must bound the uncapped fallback via fractional knapsack over
    ``(uncapped_rules + [base_earn])`` so ``trip_pool_bound`` never underestimates.
    """
    prov = _prov()
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    # --- Case A: Finding 1 ---
    card_a = Card(
        id="cand-div-fallthrough",
        issuer="Bank A",
        network="visa",
        country="IN",
        name="Div Fallthrough Card",
        annual_fee_minor=3_600,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=1, per_amount_minor=100, currency="INR"),
        provenance=prov,
    )
    rule_a = RewardRule(
        id="r-div-cap",
        card_id=card_a.id,
        description="11 pts per 1000 capped at 22",
        earn=EarnRate(points=11, per_amount_minor=1_000, currency="INR"),
        categories=[SpendCategory.FLIGHTS],
        cap=RewardCap(max_points=22, period="statement_cycle"),
        provenance=prov,
    )
    val_a = PointValuation(
        id="val-a",
        card_id=card_a.id,
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=1_000_000,
        currency="INR",
        provenance=prov,
    )
    offer_a = synthetic_offer(
        id="off-a",
        card_id=card_a.id,
        bonus_points=None,
        bonus_currency_id=None,
        bonus_flat_minor=100,
        min_spend_minor=100,
        spend_window_days=90,
        expected_approval_days=1,
        expected_card_in_hand_days=1,
        annual_fee_minor=3_600,
    )
    trip_a = CostedTrip(
        id="t-find-1",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=BOOKING_DATE,
        trip_start_date=TRIP_START,
        lines=[
            SpendLineItem(
                id="l1",
                label="Leg 1",
                category=SpendCategory.FLIGHTS,
                amount_minor=1_000,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
            SpendLineItem(
                id="l2",
                label="Leg 2",
                category=SpendCategory.FLIGHTS,
                amount_minor=2_900,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
        ],
    )
    kb_a = KnowledgeBase(
        cards=[card_a], reward_rules=[rule_a], offers=[], point_valuations=[val_a]
    )
    empty_alloc_a = optimize(trip_a, UserWallet(card_ids=[]), kb_a, OptimizationPrefs())
    plan_a = StoredPlan(
        trip_id="t-find-1",
        revision=1,
        computed_at="2026-11-01T12:00:00+00:00",
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        plan_booking_date=BOOKING_DATE,
        currency="INR",
        assignments=empty_alloc_a.assignments,
        planned_wallet_card_ids=[],
        costed_trip=trip_a,
        optimizer_result=empty_alloc_a,
        planned_wallet=UserWallet(card_ids=[]),
        optimization_prefs=OptimizationPrefs(),
    )
    res_a = retrieve_top_candidates(
        as_of=BOOKING_DATE,
        kb=kb_a,
        catalog=OfferCatalog([offer_a]),
        plan=plan_a,
        user_held_card_ids=set(),
        payment_timing=pt,
        top_m=1,
    )
    assert [s.card_id for s in res_a.suggestions] == [card_a.id]
    assert res_a.suggestions[0].net_first_year_minor == 600

    # --- Case B: Finding 2 ---
    card_b = Card(
        id="cand-unc-slower",
        issuer="Bank B",
        network="visa",
        country="IN",
        name="Slow Uncapped Rule Card",
        annual_fee_minor=2_000,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=4, per_amount_minor=100, currency="INR"),
        provenance=prov,
    )
    rule_b_cap = RewardRule(
        id="r-b-cap",
        card_id=card_b.id,
        description="10 pts per 500 capped at 10",
        earn=EarnRate(points=10, per_amount_minor=500, currency="INR"),
        categories=[SpendCategory.FLIGHTS],
        cap=RewardCap(max_points=10, period="statement_cycle"),
        provenance=prov,
    )
    rule_b_unc = RewardRule(
        id="r-b-unc",
        card_id=card_b.id,
        description="5 pts per 1000 uncapped (slower than base)",
        earn=EarnRate(points=5, per_amount_minor=1_000, currency="INR"),
        categories=[SpendCategory.FLIGHTS],
        cap=None,
        provenance=prov,
    )
    val_b = PointValuation(
        id="val-b",
        card_id=card_b.id,
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=1_000_000,
        currency="INR",
        provenance=prov,
    )
    offer_b = synthetic_offer(
        id="off-b",
        card_id=card_b.id,
        bonus_points=None,
        bonus_currency_id=None,
        bonus_flat_minor=100,
        min_spend_minor=100,
        spend_window_days=90,
        expected_approval_days=1,
        expected_card_in_hand_days=1,
        annual_fee_minor=2_000,
    )
    trip_b = CostedTrip(
        id="t-find-2",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=BOOKING_DATE,
        trip_start_date=TRIP_START,
        lines=[
            SpendLineItem(
                id="l1",
                label="Flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=1_400,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
        ],
    )
    kb_b = KnowledgeBase(
        cards=[card_b],
        reward_rules=[rule_b_cap, rule_b_unc],
        offers=[],
        point_valuations=[val_b],
    )
    empty_alloc_b = optimize(trip_b, UserWallet(card_ids=[]), kb_b, OptimizationPrefs())
    plan_b = StoredPlan(
        trip_id="t-find-2",
        revision=1,
        computed_at="2026-11-01T12:00:00+00:00",
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        plan_booking_date=BOOKING_DATE,
        currency="INR",
        assignments=empty_alloc_b.assignments,
        planned_wallet_card_ids=[],
        costed_trip=trip_b,
        optimizer_result=empty_alloc_b,
        planned_wallet=UserWallet(card_ids=[]),
        optimization_prefs=OptimizationPrefs(),
    )
    res_b = retrieve_top_candidates(
        as_of=BOOKING_DATE,
        kb=kb_b,
        catalog=OfferCatalog([offer_b]),
        plan=plan_b,
        user_held_card_ids=set(),
        payment_timing=pt,
        top_m=1,
    )
    assert [s.card_id for s in res_b.suggestions] == [card_b.id]
    assert res_b.suggestions[0].net_first_year_minor == 2_700


def test_every_single_candidate_satisfies_upper_bound_inequality_with_offers_and_caps() -> None:
    """Exhaustively checks UB(c | W) >= actual net_first_year_minor across mixed rules/offers."""
    prov = _prov()
    rng = random.Random(999)

    held_card = Card(
        id="held-a",
        issuer="Bank H",
        network="visa",
        country="IN",
        name="Held A",
        annual_fee_minor=0,
        fee_currency="INR",
        forex_markup_bp=350,
        forex_markup_tax_bp=1800,
        base_earn=EarnRate(points=2, per_amount_minor=10_000, currency="INR"),
        provenance=prov,
    )
    held_val = PointValuation(
        id="vh",
        card_id="held-a",
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=1_000_000,
        currency="INR",
        provenance=prov,
    )
    held_rule = RewardRule(
        id="rh",
        card_id="held-a",
        description="Held dining bonus",
        earn=EarnRate(points=5, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.DINING],
        cap=RewardCap(max_points=300, period="statement_cycle"),
        provenance=prov,
    )
    merchant_offer = Offer(
        id="off-agoda",
        title="10% Agoda",
        kind=OfferKind.INSTANT_DISCOUNT,
        merchant="Agoda",
        channels=[Channel.OTA_GENERIC],
        categories=[SpendCategory.HOTELS],
        discount_bp=1_000,
        max_discount_minor=200_000,
        currency="INR",
        valid_to=date(2027, 1, 1),
        stacking_class="bank_offer",
        uses_per_card=1,
        provenance=prov,
    )

    cards = [held_card]
    rules = [held_rule]
    vals = [held_val]
    acq_offers: list[CardAcquisitionOffer] = []

    for i in range(40):
        cid = f"adv-{i:02d}"
        # Use non-round valuations and mismatched block sizes intentionally
        val_micro = rng.choice([333_333, 500_000, 750_000, 1_250_000])
        base_per = rng.choice([10_000, 15_000, 20_000])
        rule_per = rng.choice([7_500, 10_000, 15_000, 30_000])
        cards.append(
            Card(
                id=cid,
                issuer="Bank C",
                network="mastercard",
                country="IN",
                name=f"Adv {i}",
                annual_fee_minor=rng.randint(0, 500_000),
                fee_currency="INR",
                forex_markup_bp=rng.choice([0, 200, 350]),
                forex_markup_tax_bp=1800,
                base_earn=EarnRate(
                    points=rng.randint(1, 5), per_amount_minor=base_per, currency="INR"
                ),
                provenance=prov,
            )
        )
        vals.append(
            PointValuation(
                id=f"val-{cid}",
                card_id=cid,
                path=RedemptionPath.TRANSFER_AIRLINE,
                value_micro_major_per_point=val_micro,
                currency="INR",
                provenance=prov,
            )
        )
        # Shared cap group across two rules!
        cap_pts = rng.randint(200, 2_000)
        rules.append(
            RewardRule(
                id=f"r1-{cid}",
                card_id=cid,
                description="Flights+Hotels shared cap",
                earn=EarnRate(points=rng.randint(4, 12), per_amount_minor=rule_per, currency="INR"),
                categories=[SpendCategory.FLIGHTS, SpendCategory.HOTELS],
                cap=RewardCap(max_points=cap_pts, period="statement_cycle", shared_cap_group="g1"),
                provenance=prov,
            )
        )
        rules.append(
            RewardRule(
                id=f"r2-{cid}",
                card_id=cid,
                description="Dining shared cap",
                earn=EarnRate(points=rng.randint(3, 10), per_amount_minor=10_000, currency="INR"),
                categories=[SpendCategory.DINING],
                cap=RewardCap(max_points=cap_pts, period="statement_cycle", shared_cap_group="g1"),
                provenance=prov,
            )
        )
        acq_offers.append(
            synthetic_offer(
                id=f"acq-{cid}",
                card_id=cid,
                bonus_points=None,
                bonus_currency_id=None,
                bonus_flat_minor=rng.randint(100_000, 1_000_000),
                min_spend_minor=500_000,
                spend_window_days=90,
                expected_approval_days=5,
                expected_card_in_hand_days=5,
                annual_fee_minor=cards[-1].annual_fee_minor,
            )
        )

    lines = [
        SpendLineItem(
            id="l-flt",
            label="Flight",
            category=SpendCategory.FLIGHTS,
            amount_minor=1_234_567,
            currency="INR",
            available_channels=[Channel.DIRECT_AIRLINE],
        ),
        SpendLineItem(
            id="l-htl-1",
            label="Hotel 1",
            category=SpendCategory.HOTELS,
            amount_minor=1_500_000,
            currency="INR",
            available_channels=[Channel.OTA_GENERIC, Channel.DIRECT_HOTEL],
            merchant_hint="Agoda",
        ),
        SpendLineItem(
            id="l-htl-2",
            label="Hotel 2",
            category=SpendCategory.HOTELS,
            amount_minor=1_200_000,
            currency="INR",
            available_channels=[Channel.OTA_GENERIC, Channel.DIRECT_HOTEL],
            merchant_hint="Agoda",
        ),
        SpendLineItem(
            id="l-din",
            label="Dining",
            category=SpendCategory.DINING,
            amount_minor=876_543,
            currency="INR",
            available_channels=[Channel.POS_ABROAD],
        ),
    ]
    trip = CostedTrip(
        id="trip-adv",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=BOOKING_DATE,
        trip_start_date=TRIP_START,
        lines=lines,
    )
    kb = KnowledgeBase(
        cards=cards, reward_rules=rules, offers=[merchant_offer], point_valuations=vals
    )
    wallet = UserWallet(card_ids=["held-a"], points_balances={})
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    for obj_mode in ("max_savings", "simplicity", "min_cash_outlay", "min_forex"):
        prefs = OptimizationPrefs(objective=obj_mode)
        held_result = optimize(trip, wallet, kb, prefs)
        held_benefit = (
            held_result.discounts_minor
            + held_result.rewards_value_minor
            - held_result.forex_fees_minor
        )
        baseline = build_wallet_baseline(
            kb=kb,
            costed_trip=trip,
            held_benefit_minor=held_benefit,
            stored_line_benefits={a.line.id: a.benefit_minor for a in held_result.assignments},
            held_card_ids=["held-a"],
        )
        plan = StoredPlan(
            trip_id="trip-adv",
            revision=1,
            computed_at="2026-11-01T12:00:00+00:00",
            trip_start_date=TRIP_START,
            trip_end_date=TRIP_END,
            plan_booking_date=BOOKING_DATE,
            currency="INR",
            assignments=held_result.assignments,
            planned_wallet_card_ids=["held-a"],
            costed_trip=trip,
            optimizer_result=held_result,
            planned_wallet=wallet,
            optimization_prefs=prefs,
        )
        catalog = OfferCatalog(acq_offers)

        for i in range(40):
            cid = f"adv-{i:02d}"
            card_obj = kb.card(cid)
            res = compute_acquisition_assessment(
                trip_id=plan.trip_id,
                revision=plan.revision,
                as_of=BOOKING_DATE,
                kb=kb,
                catalog=catalog,
                plan=plan,
                user_held_card_ids={"held-a"},
                payload=AcquisitionAssessmentIn(candidate_card_id=cid, payment_timing=pt),
            )
            # Check UB vs actual net value (from suggestion OR NONPOSITIVE_NET_VALUE refusal)
            actual_net: int | None = None
            if res.suggestions:
                actual_net = res.suggestions[0].net_first_year_minor
            elif res.refusals and res.refusals[0].reason == "NONPOSITIVE_NET_VALUE":
                actual_net = int(res.refusals[0].details["net_first_year_minor"])

            if actual_net is not None:
                from welcome.retrieval import check_pre_optimize_gates

                ctx, _, _ = check_pre_optimize_gates(
                    card_id=cid,
                    card_name=card_obj.name,
                    as_of=BOOKING_DATE,
                    costed_trip=trip,
                    catalog=catalog,
                    pt=pt,
                )
                assert ctx is not None
                ub = compute_card_upper_bound(
                    kb=kb, card=card_obj, ctx=ctx, costed_trip=trip, baseline=baseline
                )
                assert ub.upper_bound_net_minor >= actual_net, (
                    f"UB unsound for {cid} ({obj_mode}): "
                    f"{ub.upper_bound_net_minor} < {actual_net}"
                )

        # Also prove full lazy vs brute-force equality for every OptimizationPrefs objective!
        brute_top = _brute_force_top_m(
            kb=kb, catalog=catalog, plan=plan, held_ids={"held-a"}, pt=pt, top_m=5
        )
        lazy_res = retrieve_top_candidates(
            as_of=BOOKING_DATE,
            kb=kb,
            catalog=catalog,
            plan=plan,
            user_held_card_ids={"held-a"},
            payment_timing=pt,
            top_m=5,
        )
        assert [
            (s.card_id, s.net_first_year_minor, s.trip_earn_delta_minor)
            for s in lazy_res.suggestions
        ] == brute_top


# --------------------------------------------------------------------------- #
# 3. Hard Eligibility Filters, Ties & Zero-Bias Ordering                      #
# --------------------------------------------------------------------------- #


def test_hard_eligibility_filters_prune_without_calling_optimize() -> None:
    kb, catalog, plan, held_ids, _lines = _build_500_card_catalog(seed=11)
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    evaluated_ids: list[str] = []
    # Restrict open_card_ids to only two ineligible Tier-4 cards + 1 good card
    open_ids = {"cand-000", "cand-400", "cand-401", "cand-402", "cand-403"}
    res = retrieve_top_candidates(
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payment_timing=pt,
        top_m=5,
        home_country="IN",
        open_card_ids=open_ids,
        closed_card_ids={"cand-000"},  # cand-000 closed for application!
        on_exact_evaluate=evaluated_ids.append,
    )
    # Every card in open_ids was either closed or failed country/expiry/min_spend/timing!
    assert evaluated_ids == []
    assert res.suggestions == []
    assert res.stats.exact_evaluations == 0


def test_exact_tie_break_at_threshold_m_and_order_independence() -> None:
    """Equal net values tie-break strictly by card_id ascending regardless of catalog order."""
    prov = _prov()
    cards = [
        Card(
            id=cid,
            issuer="Bank",
            network="visa",
            country="IN",
            name=f"Card {cid}",
            annual_fee_minor=100_000,
            fee_currency="INR",
            forex_markup_bp=350,
            forex_markup_tax_bp=1800,
            base_earn=EarnRate(points=1, per_amount_minor=10_000, currency="INR"),
            provenance=prov,
        )
        for cid in ("c-zebra", "c-alpha", "c-middle", "c-beta")
    ]
    vals = [
        PointValuation(
            id=f"v-{c.id}",
            card_id=c.id,
            path=RedemptionPath.CASHBACK,
            value_micro_major_per_point=1_000_000,
            currency="INR",
            provenance=prov,
        )
        for c in cards
    ]
    # Identical bonus, identical fee, identical earn -> identical net_first_year_minor!
    offers = [
        synthetic_offer(
            id=f"o-{c.id}",
            card_id=c.id,
            bonus_points=None,
            bonus_currency_id=None,
            bonus_flat_minor=500_000,
            min_spend_minor=500_000,
            annual_fee_minor=100_000,
            expected_approval_days=3,
            expected_card_in_hand_days=3,
        )
        for c in cards
    ]
    trip = CostedTrip(
        id="t-tie",
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=BOOKING_DATE,
        trip_start_date=TRIP_START,
        lines=[
            SpendLineItem(
                id="l-1",
                label="Flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=1_000_000,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            )
        ],
    )
    kb = KnowledgeBase(cards=cards, reward_rules=[], offers=[], point_valuations=vals)
    plan = StoredPlan(
        trip_id="t-tie",
        revision=1,
        computed_at="2026-11-01T12:00:00+00:00",
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        plan_booking_date=BOOKING_DATE,
        currency="INR",
        assignments=optimize(trip, UserWallet(card_ids=[]), kb, OptimizationPrefs()).assignments,
        planned_wallet_card_ids=[],
        costed_trip=trip,
        optimizer_result=optimize(trip, UserWallet(card_ids=[]), kb, OptimizationPrefs()),
        planned_wallet=UserWallet(card_ids=[]),
        optimization_prefs=OptimizationPrefs(),
    )
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    # Reverse catalog order to prove zero order/affiliate bias
    rev_res = retrieve_top_candidates(
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=OfferCatalog(list(reversed(offers))),
        plan=plan,
        user_held_card_ids=set(),
        payment_timing=pt,
        top_m=2,
    )
    assert [s.card_id for s in rev_res.suggestions] == ["c-alpha", "c-beta"]
    assert rev_res.stats.exact_evaluations == 4  # did NOT falsely prune tied roots!


# --------------------------------------------------------------------------- #
# 4. High-Spend Overflow Safety, AST Float Audit & Determinism                #
# --------------------------------------------------------------------------- #


def test_high_spend_integer_safety_and_bit_identical_determinism() -> None:
    """High-spend (>= 10^9 minor units) executes without overflow or float drift."""
    huge_lines = [
        SpendLineItem(
            id="huge-1",
            label="Private Charter",
            category=SpendCategory.FLIGHTS,
            amount_minor=2_500_000_000,  # >= 10^9 minor units
            currency="INR",
            available_channels=[Channel.DIRECT_AIRLINE],
        ),
        SpendLineItem(
            id="huge-2",
            label="Gala Catering",
            category=SpendCategory.DINING,
            amount_minor=1_500_000_000,  # >= 10^9 minor units; held flagship has base earn here
            currency="INR",
            available_channels=[Channel.POS_DOMESTIC],
        ),
    ]
    kb, catalog, plan, held_ids, _ = _build_500_card_catalog(
        seed=13,
        trip_lines=huge_lines,
        held_cap_max_points=5_000,
    )
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)

    r1 = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payload=AcquisitionAssessmentIn(candidate_card_id=None, payment_timing=pt),
        top_m=5,
    )
    r2 = compute_acquisition_assessment(
        trip_id=plan.trip_id,
        revision=plan.revision,
        as_of=BOOKING_DATE,
        kb=kb,
        catalog=catalog,
        plan=plan,
        user_held_card_ids=held_ids,
        payload=AcquisitionAssessmentIn(candidate_card_id=None, payment_timing=pt),
        top_m=5,
    )
    assert r1.model_dump_json() == r2.model_dump_json()
    assert len(r1.suggestions) == 5
    for s in r1.suggestions:
        assert isinstance(s.net_first_year_minor, int)
        assert isinstance(s.trip_earn_delta_minor, int)
        assert s.net_first_year_minor > 0


def test_randomized_multi_seed_500_card_catalog_exactness() -> None:
    """Prove exact brute-force equivalence and <10% eval rate across multiple random seeds."""
    pt = PaymentTimingIn(booking_date=BOOKING_DATE, first_bookable_spend_date=FIRST_SPEND)
    for seed in (7, 19, 88):
        kb, catalog, plan, held_ids, _ = _build_500_card_catalog(seed=seed)
        brute_top = _brute_force_top_m(
            kb=kb, catalog=catalog, plan=plan, held_ids=held_ids, pt=pt, top_m=5
        )
        lazy_res = retrieve_top_candidates(
            as_of=BOOKING_DATE,
            kb=kb,
            catalog=catalog,
            plan=plan,
            user_held_card_ids=held_ids,
            payment_timing=pt,
            top_m=5,
        )
        assert [
            (s.card_id, s.net_first_year_minor, s.trip_earn_delta_minor)
            for s in lazy_res.suggestions
        ] == brute_top
        assert lazy_res.stats.exact_evaluations < 50


def test_retrieval_module_contains_no_float_or_random_calls() -> None:
    path = Path(__file__).resolve().parent.parent / "welcome" / "retrieval.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "random"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "random"
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            raise AssertionError(f"float constant {node.value!r} forbidden in {path}")
        if isinstance(node, ast.Name) and node.id == "float":
            raise AssertionError(f"float() usage forbidden in {path}")
