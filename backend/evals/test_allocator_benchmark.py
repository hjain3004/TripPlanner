"""Focused tests for the allocator benchmark oracle and naive baseline (Stream F — F-core)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

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
from evals.allocator_benchmark import (
    BenchmarkCase,
    compare_case,
    exhaustive_oracle,
    generate_benchmark_cases,
    load_golden_benchmark_cases,
    naive_allocate,
    naive_optimize,
    write_benchmark_report,
)

_PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 7),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)

_GOLDEN_CASES = load_golden_benchmark_cases()
_SINGLE_LINE_GOLDENS = [c for c in _GOLDEN_CASES if len(c.trip.lines) == 1]


@pytest.mark.parametrize("case", _SINGLE_LINE_GOLDENS, ids=[c.name for c in _SINGLE_LINE_GOLDENS])
def test_one_line_trips_naive_allocator_and_oracle_all_agree(case: BenchmarkCase) -> None:
    """On any one-line trip, naive baseline, kernel allocator, and exhaustive oracle agree."""
    comp = compare_case(case)
    assert comp.oracle_status == "proven_optimal"
    assert comp.oracle_result is not None
    assert comp.oracle_score is not None

    assert comp.naive_score.sort_key == comp.allocator_score.sort_key
    assert comp.allocator_score.sort_key == comp.oracle_score.sort_key

    assert comp.naive_result.effective_cost_minor == comp.allocator_result.effective_cost_minor
    assert comp.oracle_result.effective_cost_minor == comp.allocator_result.effective_cost_minor
    assert comp.naive_result.assignments[0].card_id == comp.allocator_result.assignments[0].card_id
    assert comp.oracle_result.assignments[0].card_id == comp.allocator_result.assignments[0].card_id
    assert comp.naive_result.assignments[0].channel == comp.allocator_result.assignments[0].channel
    assert comp.oracle_result.assignments[0].channel == comp.allocator_result.assignments[0].channel
    assert (
        comp.naive_result.assignments[0].benefit_minor
        == comp.allocator_result.assignments[0].benefit_minor
        == comp.oracle_result.assignments[0].benefit_minor
    )


@pytest.mark.parametrize("case", _GOLDEN_CASES, ids=[c.name for c in _GOLDEN_CASES])
def test_oracle_is_never_worse_than_allocator_on_goldens(case: BenchmarkCase) -> None:
    """Acceptance test (F-core): on existing golden cases, the oracle is never worse
    than the allocator.
    """
    comp = compare_case(case)
    assert comp.oracle_status == "proven_optimal"
    assert comp.oracle_score is not None
    assert comp.oracle_result is not None
    assert comp.allocator_gap_minor is not None

    # Primary scalar objective: higher is better.
    assert comp.oracle_score.primary_scalar >= comp.allocator_score.primary_scalar
    assert (
        comp.oracle_score.objective_comparison_key
        >= comp.allocator_score.objective_comparison_key
    )
    assert comp.allocator_gap_minor >= 0

    # Effective cost: lower is better (all golden cases use max_savings / simplicity).
    assert comp.oracle_result.effective_cost_minor <= comp.allocator_result.effective_cost_minor


def test_regret_trap_naive_loses_while_allocator_matches_oracle() -> None:
    """Demonstrates the coupled cap-pool trap where naive independent selection loses."""
    regret_case = next(c for c in _GOLDEN_CASES if c.name == "regret_trap")
    comp = compare_case(regret_case)

    assert comp.oracle_status == "proven_optimal"
    assert comp.naive_score.primary_scalar == 500_000
    assert comp.allocator_score.primary_scalar == 723_500
    assert comp.oracle_score is not None
    assert comp.oracle_score.primary_scalar == 723_500
    assert comp.allocator_gain_over_naive_minor == 223_500
    assert comp.allocator_gap_minor == 0


def test_uses_per_card_naive_exhausts_offer_when_small_line_comes_first() -> None:
    """When a smaller line precedes a larger line in trip order, naive wastes a 1-use offer."""
    uses_case = next(c for c in _GOLDEN_CASES if c.name == "uses_per_card")
    reversed_trip = uses_case.trip.model_copy(
        update={"lines": list(reversed(uses_case.trip.lines))}
    )
    reversed_case = BenchmarkCase(
        name="uses_per_card_reversed",
        kb=uses_case.kb,
        trip=reversed_trip,
        wallet=uses_case.wallet,
        prefs=uses_case.prefs,
    )
    comp = compare_case(reversed_case)
    assert comp.oracle_status == "proven_optimal"
    assert comp.oracle_score is not None

    # Small line (Rs 8,000) takes the 10% offer first under naive -> 80,000 discount + 72 pts
    # (7,200) + big line (Rs 10,000) gets no offer -> 100 pts (10,000) => 97,200 total benefit.
    # Allocator and oracle give the 1-use offer to big line -> 109,000 + 8,000 = 117,000.
    assert comp.naive_score.primary_scalar == 97_200
    assert comp.allocator_score.primary_scalar == 117_000
    assert comp.oracle_score.primary_scalar == 117_000
    assert comp.allocator_gain_over_naive_minor == 19_800


def test_oracle_isolated_state_explored_branches_never_contaminate_each_other() -> None:
    """Exploring an early branch that exhausts a cap pool and a 1-use offer never leaks state."""
    card_a = Card(
        id="cardA",
        issuer="Bank A",
        network="visa",
        country="IN",
        name="Card A",
        annual_fee_minor=0,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=1, per_amount_minor=10_000, currency="INR"),
        provenance=_PROV,
    )
    rule_capped = RewardRule(
        id="R_cap",
        card_id="cardA",
        description="10 pts/Rs100 capped at 1000",
        earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.SHOPPING],
        cap=RewardCap(max_points=1000, period="statement_cycle"),
        provenance=_PROV,
    )
    val_a = PointValuation(
        id="valA",
        card_id="cardA",
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=1_000_000,
        currency="INR",
        provenance=_PROV,
    )
    offer_once = Offer(
        id="O_once",
        title="Flat Rs 500 off (1 use)",
        kind=OfferKind.INSTANT_DISCOUNT,
        card_ids=["cardA"],
        merchant="ShopZ",
        channels=[Channel.OTA_GENERIC],
        categories=[SpendCategory.SHOPPING],
        discount_flat_minor=50_000,
        currency="INR",
        valid_to=date(2026, 12, 31),
        stacking_class="coupon",
        uses_per_card=1,
        provenance=_PROV,
    )
    kb = KnowledgeBase.from_models(
        cards=[card_a],
        reward_rules=[rule_capped],
        offers=[offer_once],
        point_valuations=[val_a],
    )
    trip = CostedTrip(
        booking_date=date(2026, 7, 24),
        trip_start_date=date(2026, 7, 24),
        lines=[
            SpendLineItem(
                id="line1",
                label="Line 1",
                category=SpendCategory.SHOPPING,
                amount_minor=1_000_000,
                currency="INR",
                available_channels=[Channel.OTA_GENERIC],
                merchant_hint="ShopZ",
            ),
            SpendLineItem(
                id="line2",
                label="Line 2",
                category=SpendCategory.SHOPPING,
                amount_minor=1_000_000,
                currency="INR",
                available_channels=[Channel.OTA_GENERIC],
                merchant_hint="ShopZ",
            ),
        ],
    )
    wallet = UserWallet(card_ids=["cardA"])
    oracle_run = exhaustive_oracle(kb, trip, wallet, OptimizationPrefs(objective="max_savings"))
    assert oracle_run.status == "proven_optimal"
    assert oracle_run.result is not None
    # Total cap pool is 1,000 pts across both lines, and 1-use offer applies to exactly one line.
    assert oracle_run.result.cap_pools_final == {"cardA:R_cap": 0}
    applied_counts = [len(a.offers_applied) for a in oracle_run.result.assignments]
    assert sorted(applied_counts) == [0, 1]


def test_oracle_finds_order_dependent_shared_cap_pool_optimum() -> None:
    """When two rules share a cap pool and one line has a strong fallback rule on the same card,
    commit order changes total points; the oracle explores cap permutations and finds the optimum.
    """
    card_m = Card(
        id="cardM",
        issuer="Bank M",
        network="visa",
        country="IN",
        name="Card M",
        annual_fee_minor=0,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=1, per_amount_minor=10_000, currency="INR"),
        provenance=_PROV,
    )
    # Shared pool of 1,000 pts at 10 pts/Rs100 across flights and hotels.
    r_shared_flights = RewardRule(
        id="R_sf",
        card_id="cardM",
        description="10 pts/Rs100 flights shared",
        earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.FLIGHTS],
        cap=RewardCap(max_points=1000, period="statement_cycle", shared_cap_group="shared"),
        provenance=_PROV,
    )
    r_shared_hotels = RewardRule(
        id="R_sh",
        card_id="cardM",
        description="10 pts/Rs100 hotels shared",
        earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.HOTELS],
        cap=RewardCap(max_points=1000, period="statement_cycle", shared_cap_group="shared"),
        provenance=_PROV,
    )
    # Flights also has an uncapped secondary rule at 8 pts/Rs100; hotels falls to 1 pt base.
    r_flights_fallback = RewardRule(
        id="R_ff",
        card_id="cardM",
        description="8 pts/Rs100 flights uncapped secondary",
        earn=EarnRate(points=8, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.FLIGHTS],
        provenance=_PROV,
    )
    val_m = PointValuation(
        id="valM",
        card_id="cardM",
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=1_000_000,
        currency="INR",
        provenance=_PROV,
    )
    kb = KnowledgeBase.from_models(
        cards=[card_m],
        reward_rules=[r_shared_flights, r_shared_hotels, r_flights_fallback],
        offers=[],
        point_valuations=[val_m],
    )
    # Flights is listed first in trip.lines. If flights draws the 1,000 shared pool first,
    # flights gets 1,000 pts and hotels falls through to 1 pt/Rs100 = 100 pts (1,100 pts total).
    # If hotels draws the 1,000 shared pool first, hotels gets 1,000 pts and flights falls through
    # to its secondary 8 pts/Rs100 rule = 800 pts (1,800 pts total).
    trip = CostedTrip(
        booking_date=date(2026, 7, 24),
        trip_start_date=date(2026, 7, 24),
        lines=[
            SpendLineItem(
                id="a_flights",
                label="Flights",
                category=SpendCategory.FLIGHTS,
                amount_minor=1_000_000,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
            SpendLineItem(
                id="b_hotel",
                label="Hotel",
                category=SpendCategory.HOTELS,
                amount_minor=1_000_000,
                currency="INR",
                available_channels=[Channel.DIRECT_HOTEL],
            ),
        ],
    )
    wallet = UserWallet(card_ids=["cardM"])
    prefs = OptimizationPrefs(objective="max_savings")

    naive_res = naive_optimize(trip, wallet, kb, prefs)
    alloc_res = optimize(trip, wallet, kb, prefs)
    oracle_run = exhaustive_oracle(kb, trip, wallet, prefs)

    assert oracle_run.status == "proven_optimal"
    assert oracle_run.score is not None
    # Naive commits in line order (a_flights then b_hotel) -> 110,000 minor benefit.
    assert naive_res.rewards_value_minor == 110_000
    # Pairwise improvement sweep in allocate() and cap-permutation in oracle both find 180,000.
    assert alloc_res.rewards_value_minor == 180_000
    assert oracle_run.score.primary_scalar == 180_000


def test_oracle_finds_order_dependent_single_rule_mismatched_base_block_optimum() -> None:
    """When a card has a single capped rule whose block size (per_amount_minor) differs from
    base_earn.per_amount_minor (as on hdfc-infinia), the per-line floor on post-cap remainder
    is order-dependent; the oracle explores cap permutations and matches the sweep optimum.
    """
    card_c = Card(
        id="cardC",
        issuer="Bank C",
        network="visa",
        country="IN",
        name="Card C",
        annual_fee_minor=0,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=5, per_amount_minor=15_000, currency="INR"),
        provenance=_PROV,
    )
    r_single = RewardRule(
        id="R1",
        card_id="cardC",
        description="10 pts/Rs100 capped at 10 pts",
        earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
        categories=[SpendCategory.FLIGHTS],
        cap=RewardCap(max_points=10, period="statement_cycle"),
        provenance=_PROV,
    )
    val_c = PointValuation(
        id="valC",
        card_id="cardC",
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=1_000_000,
        currency="INR",
        provenance=_PROV,
    )
    kb = KnowledgeBase.from_models(
        cards=[card_c],
        reward_rules=[r_single],
        offers=[],
        point_valuations=[val_c],
    )
    # a_small (20,000) before b_big (25,000):
    # If a_small takes the 10,000 cap block first, its 10,000 remainder < 15,000 base block (0 pts),
    # and b_big gets 25,000 // 15,000 = 1 base block (5 pts) -> 15 pts (1,500 minor).
    # If b_big takes the 10,000 cap block first, its 15,000 remainder = 1 base block (5 pts),
    # and a_small gets 20,000 // 15,000 = 1 base block (5 pts) -> 20 pts (2,000 minor).
    trip = CostedTrip(
        booking_date=date(2026, 7, 24),
        trip_start_date=date(2026, 7, 24),
        lines=[
            SpendLineItem(
                id="a_small",
                label="Small flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=20_000,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
            SpendLineItem(
                id="b_big",
                label="Big flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=25_000,
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
        ],
    )
    wallet = UserWallet(card_ids=["cardC"])
    prefs = OptimizationPrefs(objective="max_savings")

    naive_res = naive_optimize(trip, wallet, kb, prefs)
    alloc_res = optimize(trip, wallet, kb, prefs)
    oracle_run = exhaustive_oracle(kb, trip, wallet, prefs)

    assert oracle_run.status == "proven_optimal"
    assert oracle_run.score is not None
    assert naive_res.rewards_value_minor == 1_500
    assert alloc_res.rewards_value_minor == 2_000
    assert oracle_run.score.primary_scalar == 2_000


def test_oracle_stops_and_reports_not_proven_when_line_or_state_limit_exceeded() -> None:
    """An enumeration stopped at its resource limit is 'not_proven', never claimed as optimal."""
    demo_case = next(c for c in _GOLDEN_CASES if c.name == "demo_trip")

    by_line_limit = exhaustive_oracle(
        demo_case.kb,
        demo_case.trip,
        demo_case.wallet,
        demo_case.prefs,
        max_lines=3,
    )
    assert by_line_limit.status == "not_proven"
    assert by_line_limit.allocation is None
    assert by_line_limit.result is None
    assert by_line_limit.score is None
    assert by_line_limit.explored_states == 0
    assert by_line_limit.stop_reason is not None
    assert "max_lines=3" in by_line_limit.stop_reason

    by_state_limit = exhaustive_oracle(
        demo_case.kb,
        demo_case.trip,
        demo_case.wallet,
        demo_case.prefs,
        max_states=10,
    )
    assert by_state_limit.status == "not_proven"
    assert by_state_limit.allocation is None
    assert by_state_limit.result is None
    assert by_state_limit.score is None
    assert by_state_limit.explored_states > 10
    assert by_state_limit.stop_reason is not None
    assert "max_states=10" in by_state_limit.stop_reason


def test_naive_allocate_handles_empty_wallet_cash_only() -> None:
    """Empty wallet uses cash_only fallback across naive, allocator, and oracle."""
    demo_case = next(c for c in _GOLDEN_CASES if c.name == "cap_fallthrough")
    empty_wallet = UserWallet(card_ids=[])
    naive_res = naive_optimize(demo_case.trip, empty_wallet, demo_case.kb, demo_case.prefs)
    alloc_res = optimize(demo_case.trip, empty_wallet, demo_case.kb, demo_case.prefs)
    oracle_run = exhaustive_oracle(demo_case.kb, demo_case.trip, empty_wallet, demo_case.prefs)

    assert oracle_run.status == "proven_optimal"
    assert oracle_run.result is not None
    assert naive_res.effective_cost_minor == alloc_res.effective_cost_minor == 3_000_000
    assert oracle_run.result.effective_cost_minor == 3_000_000
    naive_alloc = naive_allocate(demo_case.kb, demo_case.trip, empty_wallet)
    assert naive_alloc.chosen["flights"].card_id == "cash_only"


def test_f_build_seams_are_marked_for_luna(tmp_path: Path) -> None:
    """The generator and report writer seams raise NotImplementedError for F-build."""
    with pytest.raises(NotImplementedError, match="F-build seam"):
        generate_benchmark_cases(seed=42, count=10)

    with pytest.raises(NotImplementedError, match="F-build seam"):
        write_benchmark_report(
            [], tmp_path / "allocator_benchmark.md", seed=42, elapsed_seconds=0.1
        )
