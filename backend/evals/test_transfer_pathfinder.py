from datetime import date

import pytest
import yaml
from pydantic import ValidationError

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
from core.db import KnowledgeBase
from core.transfer import find_transfer_plans
from core.transfer.arithmetic import (
    destination_units,
    minimum_source_units,
    redemption_value_micro,
)
from evals.transfer_harness import GOLDEN_DIR, run_transfer_case

PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 24),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)


def test_transfer_edge_rejects_zero_ratio_and_increment() -> None:
    with pytest.raises(ValidationError):
        TransferEdge(
            id="bad",
            from_id="card",
            to_id="program",
            ratio_from=0,
            ratio_to=1,
            min_transfer=0,
            increment=0,
            transfer_time_hours_typical=0,
            transfer_time_hours_max=0,
            provenance=PROV,
        )


def test_award_target_defaults_to_home_currency() -> None:
    target = AwardTarget(
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        travelers=2,
    )
    assert target.home_currency == "INR"
    assert RecommendationKind.NO_DATA.value == "NO_DATA"


def test_transfer_kb_queries_are_filtered_and_sorted() -> None:
    program = LoyaltyProgram(
        id="lionmiles",
        kind="airline",
        name="LionMiles",
        booking_url="https://example.test/lionmiles",
        provenance=PROV,
    )
    edge_b = TransferEdge(
        id="b",
        from_id="voyager",
        to_id="lionmiles",
        ratio_from=1,
        ratio_to=1,
        min_transfer=1000,
        increment=500,
        transfer_time_hours_typical=0,
        transfer_time_hours_max=24,
        provenance=PROV,
    )
    edge_a = edge_b.model_copy(update={"id": "a"})
    bonus = TransferBonus(
        id="bonus",
        edge_id="a",
        bonus_bp=2000,
        valid_from=date(2026, 7, 1),
        valid_to=date(2026, 7, 31),
        provenance=PROV,
    )
    award = AwardChartEntry(
        id="award",
        program_id="lionmiles",
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        miles_cost=62000,
        fees_minor=900000,
        fees_currency="INR",
        provenance=PROV,
    )
    kb = KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        loyalty_programs=[program],
        transfer_edges=[edge_b, edge_a],
        transfer_bonuses=[bonus],
        award_chart_entries=[award],
    )
    assert [edge.id for edge in kb.edges_from(["voyager"])] == ["a", "b"]
    assert [row.id for row in kb.bonuses_active(["a"], date(2026, 7, 24))] == [
        "bonus"
    ]
    assert [
        row.id for row in kb.award_entries("del", "sin", "business", "round_trip")
    ] == ["award"]


def test_transfer_math_floors_forward_and_rounds_source_up() -> None:
    edge = TransferEdge(
        id="e",
        from_id="card",
        to_id="air",
        ratio_from=3,
        ratio_to=1,
        min_transfer=1000,
        increment=500,
        transfer_time_hours_typical=0,
        transfer_time_hours_max=0,
        provenance=PROV,
    )
    assert destination_units(225000, edge, 2000) == 90000
    assert minimum_source_units(90000, edge, 2000) == 225000
    assert minimum_source_units(41234, edge, 0) == 124000


def test_redemption_value_uses_micro_major_units() -> None:
    assert (
        redemption_value_micro(
            cash_price_minor=19000000,
            fees_minor=1800000,
            points=124000,
        )
        == 1387096
    )


def worked_example_kb() -> KnowledgeBase:
    programs = [
        LoyaltyProgram(
            id="lionmiles",
            kind="airline",
            name="LionMiles",
            booking_url="https://example.test/lionmiles",
            provenance=PROV,
        ),
        LoyaltyProgram(
            id="skyorchid",
            kind="airline",
            name="SkyOrchid",
            booking_url="https://example.test/skyorchid",
            provenance=PROV,
        ),
        LoyaltyProgram(
            id="grandstay",
            kind="hotel",
            name="GrandStay",
            booking_url="https://example.test/grandstay",
            provenance=PROV,
        ),
    ]
    edges = [
        TransferEdge(
            id="E1",
            from_id="voyager-prime",
            to_id="lionmiles",
            ratio_from=1,
            ratio_to=1,
            min_transfer=1000,
            increment=500,
            transfer_time_hours_typical=0,
            transfer_time_hours_max=24,
            provenance=PROV,
        ),
        TransferEdge(
            id="E2",
            from_id="voyager-prime",
            to_id="skyorchid",
            ratio_from=3,
            ratio_to=1,
            min_transfer=1000,
            increment=500,
            transfer_time_hours_typical=0,
            transfer_time_hours_max=0,
            provenance=PROV,
        ),
        TransferEdge(
            id="E3",
            from_id="voyager-prime",
            to_id="grandstay",
            ratio_from=1,
            ratio_to=2,
            min_transfer=1000,
            increment=500,
            transfer_time_hours_typical=0,
            transfer_time_hours_max=0,
            provenance=PROV,
        ),
        TransferEdge(
            id="E4",
            from_id="grandstay",
            to_id="lionmiles",
            ratio_from=3,
            ratio_to=1,
            min_transfer=1000,
            increment=500,
            transfer_time_hours_typical=72,
            transfer_time_hours_max=72,
            provenance=PROV,
        ),
    ]
    bonuses = [
        TransferBonus(
            id="B1",
            edge_id="E2",
            bonus_bp=2000,
            valid_from=date(2026, 7, 1),
            valid_to=date(2026, 7, 31),
            provenance=PROV,
        )
    ]
    awards = [
        AwardChartEntry(
            id="lion-award",
            program_id="lionmiles",
            origin="DEL",
            destination="SIN",
            cabin="business",
            trip_type="round_trip",
            miles_cost=62000,
            fees_minor=900000,
            fees_currency="INR",
            operating_airline_hint="own metal",
            availability_note="Verify before transfer.",
            provenance=PROV,
        ),
        AwardChartEntry(
            id="sky-award",
            program_id="skyorchid",
            origin="DEL",
            destination="SIN",
            cabin="business",
            trip_type="round_trip",
            miles_cost=45000,
            fees_minor=1200000,
            fees_currency="INR",
            operating_airline_hint="partner",
            availability_note="Verify before transfer.",
            provenance=PROV,
        ),
    ]
    return KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        loyalty_programs=programs,
        transfer_edges=edges,
        transfer_bonuses=bonuses,
        award_chart_entries=awards,
    )


def test_transfer_worked_example_recommends_lionmiles() -> None:
    advice = find_transfer_plans(
        target=AwardTarget(
            origin="DEL",
            destination="SIN",
            cabin="business",
            trip_type="round_trip",
            travelers=2,
        ),
        wallet=UserWallet(
            card_ids=["voyager-prime"],
            points_balances={"voyager-prime": 140000},
        ),
        kb=worked_example_kb(),
        baseline_valuations={"voyager-prime": 1000000},
        cash_price_minor=19000000,
        on_date=date(2026, 7, 24),
    )
    assert advice.recommendation.kind is RecommendationKind.REDEEM
    assert advice.recommendation.plan_id == "lion-award:E1"
    plan = advice.plans[0]
    assert plan.points_consumed == 124000
    assert plan.total_fees_minor == 1800000
    assert plan.value_per_point_micro == 1387096
    assert plan.effective_redemption_cost_minor == 14200000
    assert plan.savings_vs_cash_minor == 4800000
    assert plan.checklist_steps[0].startswith("VERIFY (blocking):")
    assert "Do NOT transfer" in plan.checklist_steps[0]
    sky = next(row for row in advice.infeasible if row.award_id == "sky-award")
    assert sky.shortfall_points == 85000


def test_transfer_demo_fixture_matches_canonical_values() -> None:
    payload = yaml.safe_load((GOLDEN_DIR / "transfer_demo.yaml").read_text())
    advice = run_transfer_case(payload)
    expect = payload["expect"]
    assert advice.recommendation.kind.value == expect["recommendation"]
    assert advice.recommendation.plan_id == expect["plan_id"]
    plan = advice.plans[0]
    assert plan.points_consumed == expect["points_consumed"]
    assert plan.total_fees_minor == expect["total_fees_minor"]
    assert plan.value_per_point_micro == expect["value_per_point_micro"]
    assert (
        plan.effective_redemption_cost_minor
        == expect["effective_redemption_cost_minor"]
    )
    assert plan.savings_vs_cash_minor == expect["savings_vs_cash_minor"]
    sky = next(row for row in advice.infeasible if row.award_id == "sky-award")
    assert sky.shortfall_points == expect["sky_shortfall_points"]


def _assert_expectation(key: str, value: object, case: dict[str, object]) -> None:
    advice = run_transfer_case(case)
    if key == "recommendation":
        assert advice.recommendation.kind.value == value
        return
    if key == "first_checklist_prefix":
        assert advice.plans[0].checklist_steps[0].startswith(str(value))
        return
    if key == "bonus_applied":
        assert advice.plans[0].steps[0].bonus_applied == value
        return
    if key == "dominated_two_hop_count":
        assert sum(1 for plan in advice.plans if plan.dominated and len(plan.steps) == 2) == value
        return

    plan_fields = {
        "points_consumed",
        "leftover_miles",
        "existing_miles_used",
        "total_fees_minor",
    }
    if key in plan_fields:
        assert getattr(advice.plans[0], key) == value
        return
    raise AssertionError(f"unknown expectation key: {key}")


@pytest.mark.parametrize(
    "case",
    yaml.safe_load((GOLDEN_DIR / "transfer_edge_cases.yaml").read_text())["cases"],
    ids=lambda case: case["name"],
)
def test_transfer_edge_case_fixture(case: dict[str, object]) -> None:
    expect = case["expect"]
    assert isinstance(expect, dict)
    for key, value in expect.items():
        _assert_expectation(key, value, case)
