"""OPT-2 transfer pooling, grouped caps, deadline pruning, and determinism tests."""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from typing import Literal

from core.db import KnowledgeBase
from core.models import (
    AwardChartEntry,
    AwardTarget,
    LoyaltyProgram,
    Provenance,
    RecommendationKind,
    TransferBonus,
    TransferEdge,
    UserWallet,
)
from core.transfer.arithmetic import destination_units
from core.transfer.pathfinder import find_transfer_plans
from core.transfer.pooling import (
    ExpiryDiscount,
    PoolingConfig,
    TransferGroupCap,
    discounted_valuation_micro,
    effective_lot_spec,
    prune_edges_by_deadline,
    solve_pooled_transfer,
    sun_zhang_expiry_discount_bp,
)

PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 24),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)

ON_DATE = date(2026, 7, 24)


def _program(
    pid: str,
    name: str | None = None,
    kind: Literal["airline", "hotel", "card_currency"] = "airline",
) -> LoyaltyProgram:
    return LoyaltyProgram(
        id=pid,
        kind=kind,
        name=name or pid,
        booking_url=f"https://example.test/{pid}",
        provenance=PROV,
    )


def _edge(
    eid: str,
    from_id: str,
    to_id: str,
    *,
    ratio_from: int = 1,
    ratio_to: int = 1,
    min_transfer: int = 1000,
    increment: int = 1000,
    typical_h: int = 0,
    max_h: int = 0,
) -> TransferEdge:
    return TransferEdge(
        id=eid,
        from_id=from_id,
        to_id=to_id,
        ratio_from=ratio_from,
        ratio_to=ratio_to,
        min_transfer=min_transfer,
        increment=increment,
        transfer_time_hours_typical=typical_h,
        transfer_time_hours_max=max_h,
        provenance=PROV,
    )


def _award(
    aid: str = "avios-del-sin",
    program_id: str = "avios",
    miles_cost: int = 50_000,
    fees_minor: int = 200_000,
) -> AwardChartEntry:
    return AwardChartEntry(
        id=aid,
        program_id=program_id,
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        miles_cost=miles_cost,
        fees_minor=fees_minor,
        fees_currency="INR",
        provenance=PROV,
    )


def _target(travelers: int = 1) -> AwardTarget:
    return AwardTarget(
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        travelers=travelers,
        home_currency="INR",
    )


def _build_kb(
    *,
    programs: list[LoyaltyProgram],
    edges: list[TransferEdge],
    awards: list[AwardChartEntry],
    bonuses: list[TransferBonus] | None = None,
) -> KnowledgeBase:
    return KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        loyalty_programs=programs,
        transfer_edges=edges,
        transfer_bonuses=bonuses or [],
        award_chart_entries=awards,
    )


def test_effective_lot_spec_fractional_ratio_and_bonus_exact_conservation() -> None:
    # Edge 3:2 with 25% bonus -> effective ratio = 5:6, lcm(500, 6) = 1500
    edge = _edge(
        "e-frac", "bank", "avios", ratio_from=3, ratio_to=2, increment=500, min_transfer=1000
    )
    spec = effective_lot_spec(edge, bonus_bp=2_500)
    assert spec.p_from == 6
    assert spec.q_to == 5
    assert spec.delta_tilde == 1_500
    assert spec.dest_per_lot == 1_250
    assert spec.min_lots_when_active == 1

    for lots in range(1, 20):
        source = lots * spec.delta_tilde
        assert destination_units(source, edge, 2_500) == lots * spec.dest_per_lot


def test_multi_currency_pooling_chase_and_amex_into_avios() -> None:
    programs = [
        _program("chase-ur", kind="card_currency"),
        _program("amex-mr", kind="card_currency"),
        _program("avios"),
    ]
    edges = [
        _edge("chase-avios", "chase-ur", "avios", typical_h=0, max_h=2),
        _edge("amex-avios", "amex-mr", "avios", typical_h=12, max_h=24),
    ]
    kb = _build_kb(programs=programs, edges=edges, awards=[_award(miles_cost=50_000)])
    wallet = UserWallet(
        card_ids=["chase-ur", "amex-mr"],
        points_balances={"chase-ur": 30_000, "amex-mr": 30_000},
    )
    valuations = {"chase-ur": 900_000, "amex-mr": 1_100_000}

    # Legacy mode has insufficient balance on either single card.
    legacy = find_transfer_plans(
        _target(), wallet, kb, valuations, cash_price_minor=12_000_000, on_date=ON_DATE
    )
    assert legacy.plans == []
    assert len(legacy.infeasible) == 2

    # Pooling combines both currencies, drains cheaper Chase UR first, clears margin gate.
    pooled = find_transfer_plans(
        _target(),
        wallet,
        kb,
        valuations,
        cash_price_minor=12_000_000,
        on_date=ON_DATE,
        allow_pooling=True,
    )
    assert pooled.recommendation.kind == RecommendationKind.REDEEM
    assert len(pooled.plans) == 1
    plan = pooled.plans[0]
    assert plan.source_currency == "amex-mr+chase-ur"
    assert plan.points_consumed == 50_000
    assert {s.from_id: s.amount_source for s in plan.steps} == {
        "chase-ur": 30_000,
        "amex-mr": 20_000,
    }
    assert plan.checklist_steps[0].startswith("VERIFY (blocking):")


def test_grouped_transfer_cap_enforced_and_reroutes_across_pool() -> None:
    # Axis Atlas Group A capped at 30_000 combined across SQ and AC; HDFCs fills the remainder.
    programs = [
        _program("axis-atlas", kind="card_currency"),
        _program("hdfc-infinia", kind="card_currency"),
        _program("interm", kind="hotel"),
        _program("sq"),
    ]
    edges = [
        _edge("atlas-sq", "axis-atlas", "sq", min_transfer=1000, increment=1000),
        _edge("atlas-interm", "axis-atlas", "interm", min_transfer=1000, increment=1000),
        _edge("interm-sq", "interm", "sq", min_transfer=1000, increment=1000),
        _edge("hdfc-sq", "hdfc-infinia", "sq", min_transfer=1000, increment=1000),
    ]
    kb = _build_kb(
        programs=programs,
        edges=edges,
        awards=[_award(aid="sq-award", program_id="sq", miles_cost=45_000)],
    )
    wallet = UserWallet(
        card_ids=["axis-atlas", "hdfc-infinia"],
        points_balances={"axis-atlas": 100_000, "hdfc-infinia": 25_000},
    )
    valuations = {"axis-atlas": 800_000, "hdfc-infinia": 1_000_000}
    cfg = PoolingConfig(
        grouped_caps=(
            TransferGroupCap(
                group_id="axis-group-a",
                edge_ids=("atlas-sq", "atlas-interm"),
                max_source_points=30_000,
            ),
        ),
        max_transfers=3,
    )

    advice = find_transfer_plans(
        _target(),
        wallet,
        kb,
        valuations,
        cash_price_minor=15_000_000,
        on_date=ON_DATE,
        allow_pooling=True,
        pooling_config=cfg,
    )
    assert advice.recommendation.kind == RecommendationKind.REDEEM
    assert len(advice.plans) == 1
    plan = advice.plans[0]
    atlas_used = sum(s.amount_source for s in plan.steps if s.from_id == "axis-atlas")
    hdfc_used = sum(s.amount_source for s in plan.steps if s.from_id == "hdfc-infinia")
    assert atlas_used == 30_000
    assert hdfc_used == 15_000
    assert any("axis-group-a" in line for line in plan.explanation)


def test_backward_latency_pruning_and_parallel_vs_sequential_deadline() -> None:
    edges = [
        _edge("fast-a", "bank-a", "avios", max_h=24),
        _edge("fast-b", "bank-b", "avios", max_h=36),
        _edge("slow-c", "bank-c", "avios", max_h=72),
        _edge("hop-1", "bank-a", "hotel", max_h=24),
        _edge("hop-2", "hotel", "avios", max_h=36),  # sequential 24+36 = 60 > 48
    ]
    prune = prune_edges_by_deadline(
        target_id="avios",
        edges=edges,
        source_ids=["bank-a", "bank-b", "bank-c"],
        deadline_hours=48,
        max_hops=3,
    )
    kept_ids = {edge.id for edge in prune.kept_edges}
    assert kept_ids == {"fast-a", "fast-b"}
    assert "slow-c" in prune.pruned_edge_reasons
    assert "hop-1" in prune.pruned_edge_reasons

    # Parallel edges (24h and 36h) both satisfy 48h critical-path deadline.
    wallet = UserWallet(
        card_ids=["bank-a", "bank-b", "bank-c"],
        points_balances={"bank-a": 30_000, "bank-b": 30_000, "bank-c": 60_000},
    )
    valuations = {"bank-a": 1_000_000, "bank-b": 1_000_000, "bank-c": 500_000}
    sol = solve_pooled_transfer(
        award=_award(miles_cost=50_000),
        target=_target(),
        program=_program("avios"),
        wallet=wallet,
        edges=edges,
        bonuses=[],
        baseline_valuations=valuations,
        award_total_fees_minor=200_000,
        cash_price_minor=12_000_000,
        config=PoolingConfig(deadline_hours=48),
    )
    assert sol is not None
    assert sol.critical_path_hours_max == 36
    assert "slow-c" not in [s.from_id for s in sol.plan.steps]
    assert set(sol.consumed_by_currency) == {"bank-a", "bank-b"}

    # With deadline_hours=120, cheaper slow-c (72h) unlocks and reports exact 72h, not 120h.
    generous = solve_pooled_transfer(
        award=_award(miles_cost=50_000),
        target=_target(),
        program=_program("avios"),
        wallet=wallet,
        edges=edges,
        bonuses=[],
        baseline_valuations=valuations,
        award_total_fees_minor=200_000,
        cash_price_minor=12_000_000,
        config=PoolingConfig(deadline_hours=120),
    )
    assert generous is not None
    assert generous.critical_path_hours_max == 72
    assert set(generous.consumed_by_currency) == {"bank-c"}

    # Without slow-c and with generous deadline_hours=120, parallel fast paths report exact 36h.
    fast_only = solve_pooled_transfer(
        award=_award(miles_cost=50_000),
        target=_target(),
        program=_program("avios"),
        wallet=wallet,
        edges=edges[:2],
        bonuses=[],
        baseline_valuations=valuations,
        award_total_fees_minor=200_000,
        cash_price_minor=12_000_000,
        config=PoolingConfig(deadline_hours=120),
    )
    assert fast_only is not None
    assert fast_only.critical_path_hours_max == 36

    # Deadline too tight for everyone -> None.
    assert (
        solve_pooled_transfer(
            award=_award(miles_cost=50_000),
            target=_target(),
            program=_program("avios"),
            wallet=wallet,
            edges=edges,
            bonuses=[],
            baseline_valuations=valuations,
            award_total_fees_minor=200_000,
            cash_price_minor=12_000_000,
            config=PoolingConfig(deadline_hours=12),
        )
        is None
    )


def test_fixed_transfer_fee_and_cardinality_bound() -> None:
    programs = [
        _program("card-a", kind="card_currency"),
        _program("card-b", kind="card_currency"),
        _program("avios"),
    ]
    edges = [
        _edge("e-a", "card-a", "avios", min_transfer=1000, increment=1000),
        _edge("e-b", "card-b", "avios", min_transfer=1000, increment=1000),
    ]
    kb = _build_kb(programs=programs, edges=edges, awards=[_award(miles_cost=40_000)])
    wallet = UserWallet(
        card_ids=["card-a", "card-b"],
        points_balances={"card-a": 25_000, "card-b": 40_000},
    )
    valuations = {"card-a": 950_000, "card-b": 1_000_000}

    # With a 250_000 fixed fee on e-a, paying everything via zero-fee e-b saves money.
    advice = find_transfer_plans(
        _target(),
        wallet,
        kb,
        valuations,
        cash_price_minor=12_000_000,
        on_date=ON_DATE,
        allow_pooling=True,
        pooling_config=PoolingConfig(edge_fixed_fees_minor={"e-a": 250_000}, max_transfers=2),
    )
    assert len(advice.plans) == 1
    assert advice.plans[0].source_currency == "card-b"
    assert advice.plans[0].total_fees_minor == 200_000

    # With max_transfers=1 when neither single card covers 40_000, pool is blocked cleanly.
    short_wallet = UserWallet(
        card_ids=["card-a", "card-b"],
        points_balances={"card-a": 25_000, "card-b": 25_000},
    )
    blocked = find_transfer_plans(
        _target(),
        short_wallet,
        kb,
        valuations,
        cash_price_minor=12_000_000,
        on_date=ON_DATE,
        allow_pooling=True,
        pooling_config=PoolingConfig(max_transfers=1),
    )
    assert blocked.plans == []


def test_sun_zhang_expiry_discount_burns_expiring_currency_first() -> None:
    assert sun_zhang_expiry_discount_bp(2_000, 2) == 3_600
    assert discounted_valuation_micro(1_000_000, 2_000, 2) == 640_000
    assert sun_zhang_expiry_discount_bp(0, 5) == 0
    assert sun_zhang_expiry_discount_bp(10_000, 1) == 10_000

    programs = [
        _program("expiring-pts", kind="card_currency"),
        _program("evergreen-pts", kind="card_currency"),
        _program("avios"),
    ]
    edges = [
        _edge("e-exp", "expiring-pts", "avios"),
        _edge("e-evg", "evergreen-pts", "avios"),
    ]
    kb = _build_kb(programs=programs, edges=edges, awards=[_award(miles_cost=40_000)])
    wallet = UserWallet(
        card_ids=["expiring-pts", "evergreen-pts"],
        points_balances={"expiring-pts": 25_000, "evergreen-pts": 50_000},
    )
    valuations = {"expiring-pts": 1_000_000, "evergreen-pts": 1_000_000}
    cfg = PoolingConfig(
        expiry_discounts={
            "expiring-pts": ExpiryDiscount(
                source_currency="expiring-pts",
                hazard_bp=2_000,
                horizon_steps=2,
            )
        }
    )

    advice = find_transfer_plans(
        _target(),
        wallet,
        kb,
        valuations,
        cash_price_minor=12_000_000,
        on_date=ON_DATE,
        allow_pooling=True,
        pooling_config=cfg,
    )
    assert advice.recommendation.kind == RecommendationKind.REDEEM
    best = advice.plans[0]
    assert best.source_currency == "evergreen-pts+expiring-pts"
    consumed = {step.from_id: step.amount_source for step in best.steps}
    assert consumed == {"expiring-pts": 25_000, "evergreen-pts": 15_000}


def test_high_point_int64_overflow_safety_and_determinism() -> None:
    edges = [
        _edge("hi-1", "whale-a", "avios", increment=1000, min_transfer=1000, max_h=1),
        _edge("hi-2", "whale-b", "avios", increment=1000, min_transfer=1000, max_h=2),
    ]
    wallet = UserWallet(
        card_ids=["whale-a", "whale-b"],
        points_balances={"whale-a": 600_000_000, "whale-b": 600_000_000},
    )
    # Non-multiple of 10_000 triggers rem_var AddDivisionEquality path alongside large balances.
    valuations = {"whale-a": 1_234_567, "whale-b": 1_345_678}
    award = _award(miles_cost=750_000_000, fees_minor=10_000_000)

    first = solve_pooled_transfer(
        award=award,
        target=_target(),
        program=_program("avios"),
        wallet=wallet,
        edges=edges,
        bonuses=[],
        baseline_valuations=valuations,
        award_total_fees_minor=10_000_000,
        cash_price_minor=150_000_000_000,
        config=PoolingConfig(max_transfers=3),
    )
    second = solve_pooled_transfer(
        award=award,
        target=_target(),
        program=_program("avios"),
        wallet=wallet,
        edges=edges,
        bonuses=[],
        baseline_valuations=valuations,
        award_total_fees_minor=10_000_000,
        cash_price_minor=150_000_000_000,
        config=PoolingConfig(max_transfers=3),
    )
    assert first is not None and second is not None
    assert first.model_dump_json() == second.model_dump_json()
    assert first.consumed_by_currency == {"whale-a": 600_000_000, "whale-b": 150_000_000}


def test_pooling_module_contains_no_float_div_or_random_calls() -> None:
    pooling_path = Path(__file__).resolve().parent.parent / "core" / "transfer" / "pooling.py"
    tree = ast.parse(pooling_path.read_text(encoding="utf-8"), filename=str(pooling_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "random"
        if isinstance(node, ast.ImportFrom):
            assert node.module != "random"
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            raise AssertionError(f"float constant {node.value!r} forbidden in {pooling_path}")
        if isinstance(node, ast.Name) and node.id == "float":
            raise AssertionError(f"float() usage forbidden in {pooling_path}")
        if isinstance(node, ast.Div):
            raise AssertionError(f"True division '/' forbidden in {pooling_path}; use '//'")


def test_pareto_comparison_retains_best_single_source_over_redundant_pool() -> None:
    programs = [
        _program("cheap-a", kind="card_currency"),
        _program("pricey-b", kind="card_currency"),
        _program("avios"),
    ]
    edges = [
        _edge("e-a", "cheap-a", "avios", typical_h=0, max_h=0),
        _edge("e-b", "pricey-b", "avios", typical_h=12, max_h=24),
    ]
    kb = _build_kb(programs=programs, edges=edges, awards=[_award(miles_cost=40_000)])
    wallet = UserWallet(
        card_ids=["cheap-a", "pricey-b"],
        points_balances={"cheap-a": 60_000, "pricey-b": 60_000},
    )
    valuations = {"cheap-a": 800_000, "pricey-b": 1_200_000}

    advice = find_transfer_plans(
        _target(),
        wallet,
        kb,
        valuations,
        cash_price_minor=12_000_000,
        on_date=ON_DATE,
        allow_pooling=True,
    )
    assert advice.recommendation.kind == RecommendationKind.REDEEM
    assert advice.plans[0].id == "avios-del-sin:e-a"
    assert not any(":pooled:" in plan.id for plan in advice.plans)


def test_full_expiry_discount_does_not_leak_unspent_leftover_as_consumed() -> None:
    # With hazard_bp=10_000 (eff_val == 0), unused balance must never count as consumed.
    edges = [
        _edge("e-a", "expiring-empty", "avios"),
        _edge("e-b", "full-b", "avios"),
    ]
    wallet = UserWallet(
        card_ids=["expiring-empty", "full-b"],
        points_balances={"expiring-empty": 50_000, "full-b": 50_000},
    )
    valuations = {"expiring-empty": 1_000_000, "full-b": 1_000_000}
    sol = solve_pooled_transfer(
        award=_award(miles_cost=40_000),
        target=_target(),
        program=_program("avios"),
        wallet=wallet,
        edges=edges,
        bonuses=[],
        baseline_valuations=valuations,
        award_total_fees_minor=200_000,
        cash_price_minor=12_000_000,
        config=PoolingConfig(
            expiry_discounts={
                "expiring-empty": ExpiryDiscount(
                    source_currency="expiring-empty", hazard_bp=10_000, horizon_steps=1
                )
            }
        ),
    )
    assert sol is not None
    assert sol.consumed_by_currency == {"expiring-empty": 40_000}
    assert sol.plan.points_consumed == 40_000
