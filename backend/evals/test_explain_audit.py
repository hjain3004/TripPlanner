"""OPT-4 tests: always-on counterfactuals, QUICKXPLAIN cores, and XAIOR audit certificates."""

from __future__ import annotations

import ast
import time
from datetime import date
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from ortools.sat.python import cp_model

from core.db import KnowledgeBase, load_kb
from core.explain.audit import (
    CP_SAT_SAFE_INT64_BOUND,
    AssumedConstraintSpec,
    SpendMilestoneSpec,
    TransferGroupCapSpec,
    build_always_on_explanation,
    build_audit_certificate,
    build_catalog_snapshot_hash,
    build_plan_explain_and_audit,
    explain_milestone_infeasibility,
    explain_transfer_infeasibility,
    quickxplain_cpsat,
)
from core.models import (
    AwardTarget,
    Card,
    Channel,
    CostedTrip,
    EarnRate,
    LoyaltyProgram,
    OptimizationPrefs,
    PointValuation,
    Provenance,
    RedemptionPath,
    RewardCap,
    RewardRule,
    SpendCategory,
    SpendLineItem,
    TransferEdge,
    UserWallet,
)
from core.optimizer import optimize
from core.optimizer.allocate import allocate
from core.optimizer.demo_data import demo_kb, demo_trip, demo_wallet
from core.transfer.pathfinder import find_transfer_plans

TODAY = date(2026, 11, 26)


def _prov(verified_by: str = "CURATOR_TEST", needs_verification: bool = False) -> Provenance:
    return Provenance(
        source_url="https://example.invalid/opt4-test",
        source_type="manual_curation",
        last_verified=TODAY,
        verified_by=verified_by,
        needs_verification=needs_verification,
        confidence=0.95,
    )


def _pooling_kb() -> KnowledgeBase:
    p = _prov()
    return KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        loyalty_programs=[
            LoyaltyProgram(id="chase-ur", kind="card_currency", name="Chase UR", provenance=p),
            LoyaltyProgram(id="amex-mr", kind="card_currency", name="Amex MR", provenance=p),
            LoyaltyProgram(id="axis-edge", kind="card_currency", name="Axis Edge", provenance=p),
            LoyaltyProgram(id="avios", kind="airline", name="Avios", provenance=p),
            LoyaltyProgram(id="hotel-pts", kind="hotel", name="Hotel Pts", provenance=p),
        ],
        transfer_edges=[
            TransferEdge(
                id="E_CHASE_AVIOS",
                from_id="chase-ur",
                to_id="avios",
                ratio_from=1,
                ratio_to=1,
                min_transfer=1000,
                increment=1000,
                transfer_time_hours_typical=1,
                transfer_time_hours_max=4,
                provenance=p,
            ),
            TransferEdge(
                id="E_AMEX_AVIOS",
                from_id="amex-mr",
                to_id="avios",
                ratio_from=1,
                ratio_to=1,
                min_transfer=1000,
                increment=500,
                transfer_time_hours_typical=24,
                transfer_time_hours_max=48,
                provenance=p,
            ),
            TransferEdge(
                id="E_AXIS_AVIOS",
                from_id="axis-edge",
                to_id="avios",
                ratio_from=2,
                ratio_to=1,
                min_transfer=1000,
                increment=1000,
                transfer_time_hours_typical=12,
                transfer_time_hours_max=72,
                provenance=p,
            ),
            TransferEdge(
                id="E_AXIS_HOTEL",
                from_id="axis-edge",
                to_id="hotel-pts",
                ratio_from=1,
                ratio_to=1,
                min_transfer=1000,
                increment=1000,
                transfer_time_hours_typical=2,
                transfer_time_hours_max=12,
                provenance=p,
            ),
        ],
        transfer_bonuses=[],
        award_chart_entries=[],
    )


def test_always_on_demo_trip_latency_and_cap_ledger() -> None:
    kb = demo_kb()
    trip = demo_trip()
    wallet = demo_wallet()
    alloc = allocate(kb, trip, wallet, OptimizationPrefs())
    result = optimize(trip, wallet, kb)

    milestones = [
        SpendMilestoneSpec(
            id="waiver-4l",
            card_id="voyager-prime",
            description="Annual fee waiver",
            threshold_minor=40_000_000,  # ₹4,00,000
            prior_spend_minor=24_000_000,  # ₹2,40,000
            reward_kind="fee_waiver",
            fee_waiver_minor=1_000_000,
            currency="INR",
            provenance=_prov(),
        )
    ]

    # Warm-up call once, then measure always-on explanation + audit bundle latency (< 15 ms).
    build_plan_explain_and_audit(trip, wallet, kb, result, alloc=alloc, milestones=milestones)
    t0 = time.perf_counter()
    bundle = build_plan_explain_and_audit(
        trip, wallet, kb, result, alloc=alloc, milestones=milestones
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 15.0, f"always-on explain+audit took {elapsed_ms:.2f} ms (>= 15 ms)"

    exp = bundle.explanations
    ledger_by_key = {entry.pool_key: entry for entry in exp.cap_ledger}
    assert ledger_by_key["voyager-prime:portal"].binding is True
    assert ledger_by_key["voyager-prime:portal"].remaining_points == 0
    assert ledger_by_key["globesaver:R2"].binding is False
    assert ledger_by_key["globesaver:R2"].remaining_points == 750
    assert len(exp.valuation_breakevens) >= 1
    assert len(exp.milestone_deltas) == 1


def test_exact_rhs_milestone_deltas_and_excluded_rules_mcc() -> None:
    p = _prov()
    cards = [
        Card(
            id="card-a",
            issuer="BankA",
            network="visa",
            country="IN",
            name="Card A",
            annual_fee_minor=500_000,
            fee_currency="INR",
            forex_markup_bp=200,
            forex_markup_tax_bp=1800,
            base_earn=EarnRate(points=2, per_amount_minor=10_000, currency="INR"),
            provenance=p,
        ),
        Card(
            id="card-b",
            issuer="BankB",
            network="mastercard",
            country="IN",
            name="Card B",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=350,
            forex_markup_tax_bp=1800,
            base_earn=EarnRate(points=1, per_amount_minor=10_000, currency="INR"),
            provenance=p,
        ),
    ]
    rules = [
        RewardRule(
            id="rule-dining-mcc",
            card_id="card-a",
            description="5x dining on restaurant MCCs",
            earn=EarnRate(points=5, per_amount_minor=10_000, currency="INR"),
            categories=[SpendCategory.DINING],
            channels=[Channel.POS_DOMESTIC],
            excluded_categories=[SpendCategory.INSURANCE],
            mcc_codes=[5812, 5814],
            cap=RewardCap(max_points=5_000, period="calendar_month"),
            provenance=p,
        ),
        RewardRule(
            id="rule-expired",
            card_id="card-b",
            description="Expired flights promo",
            earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
            categories=[SpendCategory.FLIGHTS],
            valid_to=date(2026, 10, 1),
            provenance=p,
        ),
    ]
    vals = [
        PointValuation(
            id="v-a",
            card_id="card-a",
            path=RedemptionPath.PORTAL_FLIGHTS,
            value_micro_major_per_point=1_000_000,
            currency="INR",
            provenance=p,
        ),
        PointValuation(
            id="v-b",
            card_id="card-b",
            path=RedemptionPath.CASHBACK,
            value_micro_major_per_point=500_000,
            currency="INR",
            provenance=p,
        ),
    ]
    kb = KnowledgeBase.from_models(
        cards=cards, reward_rules=rules, offers=[], point_valuations=vals
    )
    trip = CostedTrip(
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=TODAY,
        trip_start_date=TODAY,
        lines=[
            SpendLineItem(
                id="flight:1",
                label="Flights",
                category=SpendCategory.FLIGHTS,
                amount_minor=6_200_000,  # ₹62,000
                currency="INR",
                available_channels=[Channel.DIRECT_AIRLINE],
            ),
            SpendLineItem(
                id="dining:1",
                label="Cafe",
                category=SpendCategory.DINING,
                amount_minor=1_000_000,  # ₹10,000
                currency="INR",
                available_channels=[Channel.POS_DOMESTIC],
            ),
            SpendLineItem(
                id="ins:1",
                label="Insurance",
                category=SpendCategory.INSURANCE,
                amount_minor=500_000,  # ₹5,000 (excluded category + excluded from milestone)
                currency="INR",
                available_channels=[Channel.POS_DOMESTIC],
            ),
        ],
    )
    wallet = UserWallet(card_ids=["card-a", "card-b"])
    result = optimize(trip, wallet, kb)

    # Prior ₹2,90,000 + trip eligible ₹72,000 (flight + dining, excluding insurance) = ₹3,62,000
    # Gap to ₹4,00,000 fee waiver = exactly ₹38,000 (3_800_000 minor)
    milestones = [
        SpendMilestoneSpec(
            id="fee-waiver-400k",
            card_id="card-a",
            description="Annual fee waiver",
            threshold_minor=40_000_000,
            prior_spend_minor=29_000_000,
            reward_kind="fee_waiver",
            fee_waiver_minor=500_000,
            excluded_categories=[SpendCategory.INSURANCE],
            provenance=p,
        )
    ]

    exp = build_always_on_explanation(
        trip,
        wallet,
        kb,
        result,
        milestones=milestones,
        line_mccs={"dining:1": 5999},  # excluded MCC
    )

    assert len(exp.milestone_deltas) == 1
    delta = exp.milestone_deltas[0]
    assert delta.trip_eligible_spend_minor == 7_200_000
    assert delta.total_eligible_spend_minor == 36_200_000
    assert delta.spend_delta_minor == 3_800_000
    assert delta.unlocked is False
    assert "₹38,000 more eligible spend" in delta.summary

    reasons = {(e.rule_id, e.line_id): e.reason for e in exp.excluded_rules}
    assert reasons[("rule-dining-mcc", "dining:1")] == "excluded_mcc"
    assert reasons[("rule-dining-mcc", "ins:1")] == "excluded_category"
    assert reasons[("rule-expired", "flight:1")] == "expired"


def test_forel_valuation_breakevens_are_exact_to_one_micro_unit() -> None:
    p = _prov()
    cards = [
        Card(
            id="card-win",
            issuer="WinBank",
            network="visa",
            country="IN",
            name="Winner",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=0,
            forex_markup_tax_bp=0,
            base_earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),  # 10 pts/₹100
            provenance=p,
        ),
        Card(
            id="card-run",
            issuer="RunBank",
            network="mastercard",
            country="IN",
            name="Runner",
            annual_fee_minor=0,
            fee_currency="INR",
            forex_markup_bp=0,
            forex_markup_tax_bp=0,
            base_earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
            provenance=p,
        ),
    ]
    vals = [
        PointValuation(
            id="v-win",
            card_id="card-win",
            path=RedemptionPath.PORTAL_FLIGHTS,
            value_micro_major_per_point=1_420_000,  # ₹1.42/pt
            currency="INR",
            provenance=p,
        ),
        PointValuation(
            id="v-run",
            card_id="card-run",
            path=RedemptionPath.TRANSFER_AIRLINE,
            value_micro_major_per_point=500_000,  # ₹0.50/pt
            currency="INR",
            provenance=p,
        ),
    ]
    kb = KnowledgeBase.from_models(cards=cards, reward_rules=[], offers=[], point_valuations=vals)
    trip = CostedTrip(
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=TODAY,
        trip_start_date=TODAY,
        lines=[
            SpendLineItem(
                id="hotel:1",
                label="Hotel",
                category=SpendCategory.HOTELS,
                amount_minor=1_000_000,  # ₹10,000 -> 1,000 pts on both cards
                currency="INR",
                available_channels=[Channel.DIRECT_HOTEL],
            ),
        ],
    )
    wallet = UserWallet(card_ids=["card-win", "card-run"])
    alloc = allocate(kb, trip, wallet, OptimizationPrefs())
    result = optimize(trip, wallet, kb)

    # Check both with alloc and without alloc (reconstruction path)
    for use_alloc in (alloc, None):
        exp = build_always_on_explanation(trip, wallet, kb, result, alloc=use_alloc)
        assert len(exp.valuation_breakevens) == 1
        bk = exp.valuation_breakevens[0]
        assert bk.reachable is True
        assert bk.direction == "above"
        v_star = bk.breakeven_micro_major_per_point
        assert v_star is not None
        assert bk.runner_points == 1000
        # Chosen earns 1000 * 1_420_000 // 10_000 = 142_000 paise.
        # Strict integer beat requires 1000 * V // 10_000 >= 142_001 -> V = 1_420_010.
        assert (bk.runner_points * v_star) // 10_000 > bk.chosen_benefit_minor
        assert (bk.runner_points * (v_star - 1)) // 10_000 <= bk.chosen_benefit_minor
        assert "transfer_airline" in bk.summary


def test_shared_currency_breakeven_when_runner_is_same_card_other_channel() -> None:
    p = _prov()
    card = Card(
        id="card-same",
        issuer="SameBank",
        network="visa",
        country="IN",
        name="Same Card",
        annual_fee_minor=0,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=2, per_amount_minor=10_000, currency="INR"),
        provenance=p,
    )
    rules = [
        RewardRule(
            id="rule-portal",
            card_id="card-same",
            description="Portal 10x",
            earn=EarnRate(points=10, per_amount_minor=10_000, currency="INR"),
            categories=[SpendCategory.FLIGHTS],
            channels=[Channel.BANK_PORTAL],
            provenance=p,
        ),
        RewardRule(
            id="rule-direct",
            card_id="card-same",
            description="Direct 4x",
            earn=EarnRate(points=4, per_amount_minor=10_000, currency="INR"),
            categories=[SpendCategory.FLIGHTS],
            channels=[Channel.DIRECT_AIRLINE],
            provenance=p,
        ),
    ]
    vals = [
        PointValuation(
            id="v-same",
            card_id="card-same",
            path=RedemptionPath.TRANSFER_AIRLINE,
            value_micro_major_per_point=1_000_000,
            currency="INR",
            provenance=p,
        )
    ]
    kb = KnowledgeBase.from_models(
        cards=[card], reward_rules=rules, offers=[], point_valuations=vals
    )
    trip = CostedTrip(
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=TODAY,
        trip_start_date=TODAY,
        lines=[
            SpendLineItem(
                id="f1",
                label="Flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=1_000_000,
                currency="INR",
                available_channels=[Channel.BANK_PORTAL, Channel.DIRECT_AIRLINE],
            )
        ],
    )
    wallet = UserWallet(card_ids=["card-same"])
    result = optimize(trip, wallet, kb)
    exp = build_always_on_explanation(trip, wallet, kb, result)
    assert len(exp.valuation_breakevens) == 1
    bk = exp.valuation_breakevens[0]
    assert bk.shared_currency is True
    assert bk.reachable is False
    assert bk.direction == "unreachable"


def test_grouped_transfer_caps_ledger_matches_specific_edges() -> None:
    kb = load_kb()
    advice = find_transfer_plans(
        AwardTarget(
            origin="DEL",
            destination="SIN",
            cabin="business",
            trip_type="round_trip",
            travelers=2,
            home_currency="INR",
        ),
        UserWallet(card_ids=[], points_balances={"voyager-prime": 200_000}),
        kb,
        {"voyager-prime": 1_000_000},
        19_000_000,
        date(2026, 7, 24),
    )
    # Recommended plan transfers via E1 (voyager-prime -> lionmiles)
    group_caps = [
        TransferGroupCapSpec(
            group_id="group-a",
            description="Group A airline cap",
            source_currency="voyager-prime",
            edge_ids=["E1"],
            max_source_units=124_000,
            used_source_units_prior=0,
        ),
        TransferGroupCapSpec(
            group_id="group-b",
            description="Group B skyorchid cap",
            source_currency="voyager-prime",
            edge_ids=["E2"],
            max_source_units=50_000,
            used_source_units_prior=0,
        ),
    ]
    trip = demo_trip()
    wallet = demo_wallet()
    d_kb = demo_kb()
    result = optimize(trip, wallet, d_kb)
    exp = build_always_on_explanation(
        trip, wallet, kb, result, transfer_advice=advice, group_caps=group_caps
    )
    by_gid = {g.group_id: g for g in exp.grouped_transfer_caps}
    assert by_gid["group-a"].used_plan_units == 124_000
    assert by_gid["group-a"].binding is True
    assert by_gid["group-b"].used_plan_units == 0
    assert by_gid["group-b"].binding is False


def test_quickxplain_transfer_infeasibility_minimal_core_and_relaxation() -> None:
    kb = _pooling_kb()
    # Wallet has 20k Chase UR + 15k Amex MR + 50k Axis Edge (2:1 to Avios).
    # Axis Group A cap restricts E_AXIS_AVIOS to 20k source (=10k Avios).
    # Max reachable Avios = 20k + 15k + 10k = 45k < 50k target.
    wallet = UserWallet(
        card_ids=[],
        points_balances={
            "chase-ur": 20_000,
            "amex-mr": 15_000,
            "axis-edge": 50_000,
        },
    )
    group_caps = [
        TransferGroupCapSpec(
            group_id="axis_group_a",
            description="Axis Group A Avios cap",
            source_currency="axis-edge",
            edge_ids=["E_AXIS_AVIOS"],
            max_source_units=20_000,
        ),
        TransferGroupCapSpec(
            group_id="axis_group_hotel_irrelevant",
            description="Irrelevant hotel cap",
            source_currency="axis-edge",
            edge_ids=["E_AXIS_HOTEL"],
            max_source_units=100_000,
        ),
    ]

    res = explain_transfer_infeasibility(
        target_program_id="avios",
        required_miles=50_000,
        wallet=wallet,
        kb=kb,
        on_date=TODAY,
        group_caps=group_caps,
        max_transfer_hours=100,
        max_transfers=3,
    )
    assert res.is_feasible is False
    core_ids = {c.constraint_id for c in res.conflict_core}
    assert "goal:avios" in core_ids
    assert "balance:chase-ur" in core_ids
    assert "balance:amex-mr" in core_ids
    assert "group_cap:axis_group_a" in core_ids
    # Redundant / non-binding constraints MUST NOT be in minimal core
    assert "group_cap:axis_group_hotel_irrelevant" not in core_ids
    assert "balance:axis-edge" not in core_ids
    assert "deadline:100" not in core_ids

    rel_by_id = {r.constraint_id: r for r in res.relaxations}
    # Need 5,000 more Avios -> Chase UR +5,000, Amex MR +5,000, or Axis Group A +10,000 (2:1 ratio!)
    assert rel_by_id["balance:chase-ur"].delta == 5_000
    assert rel_by_id["balance:amex-mr"].delta == 5_000
    assert rel_by_id["group_cap:axis_group_a"].delta == 10_000
    assert rel_by_id["goal:avios"].delta == 5_000


def test_quickxplain_deadline_infeasibility_and_feasible_case() -> None:
    kb = _pooling_kb()
    wallet = UserWallet(card_ids=[], points_balances={"chase-ur": 10_000, "amex-mr": 20_000})

    # Feasible with 48h deadline
    ok = explain_transfer_infeasibility(
        target_program_id="avios",
        required_miles=30_000,
        wallet=wallet,
        kb=kb,
        on_date=TODAY,
        max_transfer_hours=48,
    )
    assert ok.is_feasible is True
    assert ok.conflict_core == []

    # Infeasible with 12h deadline because Amex takes 48h max
    bad = explain_transfer_infeasibility(
        target_program_id="avios",
        required_miles=30_000,
        wallet=wallet,
        kb=kb,
        on_date=TODAY,
        max_transfer_hours=12,
    )
    assert bad.is_feasible is False
    core_ids = {c.constraint_id for c in bad.conflict_core}
    assert core_ids == {"goal:avios", "balance:chase-ur", "deadline:12"}
    rel_by_id = {r.constraint_id: r for r in bad.relaxations}
    assert rel_by_id["deadline:12"].delta == 36  # 12 + 36 = 48 hours


def test_quickxplain_milestone_infeasibility_and_mus_property() -> None:
    kb = demo_kb()
    wallet = demo_wallet()
    trip = CostedTrip(
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=TODAY,
        trip_start_date=TODAY,
        lines=[
            SpendLineItem(
                id="l1",
                label="Flights",
                category=SpendCategory.FLIGHTS,
                amount_minor=10_000_000,  # ₹1,00,000, splittable=False
                currency="INR",
                available_channels=[Channel.BANK_PORTAL],
                splittable=False,
            )
        ],
    )
    # Single unsplit ₹1L flight cannot trigger both cards' milestones simultaneously.
    milestones = [
        SpendMilestoneSpec(
            id="m-vp",
            card_id="voyager-prime",
            description="Voyager ₹80k milestone",
            threshold_minor=8_000_000,
            provenance=_prov(),
        ),
        SpendMilestoneSpec(
            id="m-gs",
            card_id="globesaver",
            description="Globesaver ₹80k milestone",
            threshold_minor=8_000_000,
            provenance=_prov(),
        ),
    ]
    res = explain_milestone_infeasibility(trip, wallet, kb, milestones)
    assert res.is_feasible is False
    core_ids = {c.constraint_id for c in res.conflict_core}
    assert core_ids == {"milestone:voyager-prime:m-vp", "milestone:globesaver:m-gs"}
    rel_by_id = {r.constraint_id: r for r in res.relaxations}
    assert rel_by_id["milestone:voyager-prime:m-vp"].delta == 8_000_000


def test_quickxplain_prefilter_large_constraint_set_is_subset_minimal() -> None:
    # Build > 24 constraints (30 constraints) so the sufficient_assumptions pre-filter runs,
    # and assert strict subset-minimality (MUS) of the returned core.
    m = cp_model.CpModel()
    x = m.new_int_var(0, 1000, "x")
    specs: list[AssumedConstraintSpec] = []
    for i in range(28):
        lit = m.new_bool_var(f"upper_{i}")
        m.add(x <= 50 + i).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"upper_{i}",
                kind="custom",
                description=f"x <= {50 + i}",
                literal=lit,
            )
        )
    lit_lb = m.new_bool_var("lower_100")
    m.add(x >= 100).only_enforce_if(lit_lb)
    specs.append(
        AssumedConstraintSpec(
            constraint_id="lower_100",
            kind="custom",
            description="x >= 100",
            literal=lit_lb,
        )
    )
    lit_ok = m.new_bool_var("triv_ok")
    m.add(x <= 900).only_enforce_if(lit_ok)
    specs.append(
        AssumedConstraintSpec(
            constraint_id="triv_ok",
            kind="custom",
            description="x <= 900",
            literal=lit_ok,
        )
    )

    feasible, core_indices, _ = quickxplain_cpsat(m, specs)
    assert feasible is False
    assert len(core_indices) == 2
    assert "lower_100" in {specs[i].constraint_id for i in core_indices}

    # Verify strict subset-minimality: removing either constraint restores feasibility.
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    for drop_idx in core_indices:
        m.clear_assumptions()
        m.add_assumptions([specs[i].literal for i in core_indices if i != drop_idx])
        assert solver.solve(m) in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def test_xaior_audit_certificate_determinism_and_high_spend_int64_safety() -> None:
    kb = demo_kb()
    transfer_kb = load_kb()
    trip = demo_trip()
    wallet = demo_wallet()
    result = optimize(trip, wallet, kb)
    advice = find_transfer_plans(
        target=AwardTarget(
            origin="DEL",
            destination="SIN",
            cabin="business",
            trip_type="round_trip",
            travelers=1,
            home_currency="INR",
        ),
        wallet=UserWallet(card_ids=[], points_balances={"voyager-prime": 200_000}),
        kb=transfer_kb,
        baseline_valuations={"voyager-prime": 1_000_000},
        cash_price_minor=19_000_000,
        on_date=date(2026, 7, 24),
    )
    milestones = [
        SpendMilestoneSpec(
            id="ms-1",
            card_id="voyager-prime",
            description="₹4L waiver",
            threshold_minor=40_000_000,
            provenance=_prov(verified_by="OWNER_VERIFIED", needs_verification=False),
        )
    ]

    cert1 = build_audit_certificate(
        trip,
        wallet,
        kb,
        result,
        transfer_advice=advice,
        milestones=milestones,
        gamma=1,
        max_time_in_seconds=5.0,
    )
    cert2 = build_audit_certificate(
        trip,
        wallet,
        kb,
        result,
        transfer_advice=advice,
        milestones=milestones,
        gamma=1,
        max_time_in_seconds=5.0,
    )
    assert cert1.model_dump_json() == cert2.model_dump_json()
    assert len(cert1.catalog_snapshot_hash) == 64
    assert cert1.solver.seed == 1
    assert cert1.solver.num_workers == 1
    assert cert1.robustness.gamma == 1
    assert cert1.robustness.recourse_floors["voyager-prime"] > 0
    assert cert1.revolver_apr_excluded is True
    assert "0% revolving APR" in cert1.transactor_apr_warning
    assert cert1.zero_affiliate_weight is True
    assert cert1.zero_paid_promotion is True
    assert cert1.any_needs_verification is True
    assert {e.kind for e in cert1.rule_provenance} >= {
        "card",
        "reward_rule",
        "point_valuation",
        "award_chart",
        "spend_milestone",
    }

    # Snapshot hash sensitivity: mutating KB changes catalog_snapshot_hash
    h_orig = build_catalog_snapshot_hash(kb)
    mutated_card = kb.card("voyager-prime").model_copy(update={"annual_fee_minor": 999})
    kb2 = KnowledgeBase.from_models(
        cards=[mutated_card if c.id == "voyager-prime" else c for c in kb.cards()],
        reward_rules=kb.rules_for_cards([c.id for c in kb.cards()]),
        offers=[],
        point_valuations=[v for c in kb.cards() for v in kb.valuations_for_card(c.id)],
        fx_rates=[],
        loyalty_programs=kb.programs(),
        transfer_edges=kb.edges_from([p.id for p in kb.programs()]),
    )
    assert build_catalog_snapshot_hash(kb2) != h_orig

    # High-spend int64 safety (>= 10^9 minor units) in breakevens, milestones, and CP-SAT
    high_trip = CostedTrip(
        origin="DEL",
        destination="SIN",
        home_currency="INR",
        booking_date=TODAY,
        trip_start_date=TODAY,
        lines=[
            SpendLineItem(
                id="charter:1",
                label="Corporate block booking",
                category=SpendCategory.HOTELS,
                amount_minor=5_000_000_000,  # ₹50,000,000 (5 billion minor units >= 10^9)
                currency="INR",
                available_channels=[Channel.BANK_PORTAL],
            )
        ],
    )
    high_res = optimize(high_trip, wallet, kb)
    high_ms = [
        SpendMilestoneSpec(
            id="ms-high",
            card_id="voyager-prime",
            description="High spend milestone",
            threshold_minor=10_000_000_000,
            provenance=_prov(),
        )
    ]
    high_bundle = build_plan_explain_and_audit(high_trip, wallet, kb, high_res, milestones=high_ms)
    assert high_bundle.explanations.milestone_deltas[0].spend_delta_minor == 5_000_000_000

    infeasible_high = explain_milestone_infeasibility(
        high_trip, wallet, kb, high_ms, total_budget_cap_minor=2_000_000_000
    )
    assert infeasible_high.is_feasible is False

    # Bounds past CP_SAT_SAFE_INT64_BOUND fail closed rather than silently overflowing int64
    with pytest.raises(ValueError, match="int64-safe"):
        explain_transfer_infeasibility(
            target_program_id="lionmiles",
            required_miles=CP_SAT_SAFE_INT64_BOUND + 1,
            wallet=wallet,
            kb=kb,
            on_date=TODAY,
        )


def test_audit_module_has_zero_float_money_math_and_core_isolation() -> None:
    audit_path = Path(__file__).resolve().parent.parent / "core" / "explain" / "audit.py"
    tree = ast.parse(audit_path.read_text(encoding="utf-8"), filename=str(audit_path))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith(("gateway", "agents", "api", "welcome"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(("gateway", "agents", "api", "welcome"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id != "float", "float() conversion forbidden in core/explain/audit.py"
        elif isinstance(node, ast.Constant) and isinstance(node.value, float):
            # Only non-money solver timeout defaults (5.0) allowed; never financial rates/fractions.
            assert node.value == 5.0, f"Unexpected float constant {node.value} in audit.py"


@given(
    chosen_benefit=st.integers(min_value=0, max_value=10_000_000_000),
    runner_points=st.integers(min_value=1, max_value=1_000_000),
    runner_cash_net=st.integers(min_value=-500_000, max_value=500_000),
)
@settings(max_examples=50, deadline=None)
def test_property_independent_breakeven_is_exact(
    chosen_benefit: int, runner_points: int, runner_cash_net: int
) -> None:
    from core.explain.audit import _independent_breakeven

    reachable, direction, v_star = _independent_breakeven(
        chosen_benefit, runner_points, runner_cash_net
    )
    assert reachable is True
    assert direction == "above"
    assert v_star is not None
    assert runner_cash_net + (runner_points * v_star) // 10_000 > chosen_benefit
    if v_star > 0:
        assert runner_cash_net + (runner_points * (v_star - 1)) // 10_000 <= chosen_benefit


def test_transfer_infeasibility_isolated_target_without_incoming_edges() -> None:
    kb = _pooling_kb()
    wallet = UserWallet(card_ids=[], points_balances={"chase-ur": 50_000})
    res = explain_transfer_infeasibility(
        target_program_id="unreachable-airline",
        required_miles=25_000,
        wallet=wallet,
        kb=kb,
        on_date=TODAY,
    )
    assert res.is_feasible is False
    assert [c.constraint_id for c in res.conflict_core] == ["goal:unreachable-airline"]
    assert res.relaxations[0].delta == 25_000
