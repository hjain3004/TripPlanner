"""Optimizer property tests (spec 04 §1, recommended set).

Uses hypothesis over a controlled single-card KB (base earn, no offers/forex) plus
invariant checks across every committed golden.
"""

from __future__ import annotations

from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from core.db import KnowledgeBase
from core.models import (
    Card,
    Channel,
    CostedTrip,
    EarnRate,
    OptimizationPrefs,
    PointValuation,
    Provenance,
    RedemptionPath,
    SpendCategory,
    SpendLineItem,
    UserWallet,
)
from core.optimizer import optimize
from evals._harness import golden_files, load_case

_PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 7),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)


def _single_card_kb() -> KnowledgeBase:
    card = Card(
        id="prop-card",
        issuer="Prop",
        network="visa",
        country="IN",
        name="Prop",
        annual_fee_minor=0,
        fee_currency="INR",
        forex_markup_bp=0,
        forex_markup_tax_bp=0,
        base_earn=EarnRate(points=1, per_amount_minor=10000, currency="INR"),
        provenance=_PROV,
    )
    val = PointValuation(
        id="prop-val",
        card_id="prop-card",
        path=RedemptionPath.CASHBACK,
        value_micro_major_per_point=500_000,  # Rs0.50/pt < Rs1/₹100 earn → benefit < amount
        currency="INR",
        provenance=_PROV,
    )
    return KnowledgeBase.from_models(
        cards=[card], reward_rules=[], offers=[], point_valuations=[val]
    )


@settings(max_examples=200, deadline=None)
@given(amount=st.integers(min_value=0, max_value=50_000_000))
def test_property_determinism_and_bounds(amount: int) -> None:
    kb = _single_card_kb()
    trip = CostedTrip(
        booking_date=date(2026, 7, 24),
        trip_start_date=date(2026, 7, 24),
        lines=[
            SpendLineItem(
                id="l",
                label="L",
                category=SpendCategory.SHOPPING,
                amount_minor=amount,
                currency="INR",
                available_channels=[Channel.POS_DOMESTIC],
            )
        ],
    )
    wallet = UserWallet(card_ids=["prop-card"])
    r1 = optimize(trip, wallet, kb, OptimizationPrefs()).model_dump_json()
    r2 = optimize(trip, wallet, kb, OptimizationPrefs()).model_dump_json()
    assert r1 == r2  # determinism
    result = optimize(trip, wallet, kb, OptimizationPrefs())
    a = result.assignments[0]
    assert 0 <= a.benefit_minor <= a.line.amount_minor  # benefit within [0, amount]
    assert result.effective_cost_minor <= result.gross_minor


def test_property_pools_never_negative_over_goldens() -> None:
    for path in golden_files():
        result = load_case(path)["result"]
        for key, val in result.cap_pools_final.items():
            assert val >= 0, f"{path} pool {key} negative"


def test_property_benefit_within_amount_over_goldens() -> None:
    for path in golden_files():
        result = load_case(path)["result"]
        for a in result.assignments:
            assert a.benefit_minor <= a.line.amount_minor, f"{path} {a.line.id}"


def test_property_removing_card_not_better() -> None:
    from core.optimizer.demo_data import demo_kb, demo_trip

    full = optimize(demo_trip(), UserWallet(card_ids=["voyager-prime", "globesaver"]), demo_kb())
    reduced = optimize(demo_trip(), UserWallet(card_ids=["voyager-prime"]), demo_kb())
    full_benefit = sum(a.benefit_minor for a in full.assignments)
    reduced_benefit = sum(a.benefit_minor for a in reduced.assignments)
    assert reduced_benefit <= full_benefit
