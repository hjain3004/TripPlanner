from datetime import date

import pytest
from pydantic import ValidationError

from core.models import (
    AwardChartEntry,
    AwardTarget,
    LoyaltyProgram,
    Provenance,
    RecommendationKind,
    TransferBonus,
    TransferEdge,
)
from core.db import KnowledgeBase

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
