from datetime import date

import pytest

from core.models import Channel, Provenance, SpendCategory
from core.optimizer.milestones import Bundle, SpendMilestone, prune_dominated_bundles
from evals._harness import golden_files

PROVENANCE = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 1, 1),
    verified_by="test-curator",
    needs_verification=True,
    confidence=0.8,
)


def bundle(name: str, nominal: int, floor: int, **changes: object) -> Bundle:
    fields = dict(
        id=name,
        line_id="one",
        card_id="card",
        channel=Channel.POS_DOMESTIC,
        category=SpendCategory.DINING,
        spend_minor=100,
        currency_id="points",
        nominal_minor=nominal,
        floor_minor=floor,
        resource_signature=(),
    )
    fields.update(changes)
    return Bundle(**fields)  # type: ignore[arg-type]


def test_milestone_requires_one_bonus_and_preserves_provenance() -> None:
    milestone = SpendMilestone(
        card_id="card",
        threshold_minor=100,
        bonus_points=50,
        eligible_categories=(SpendCategory.DINING,),
        period_type="annual",
        prior_spend_minor=10,
        provenance=PROVENANCE,
    )
    assert milestone.provenance.needs_verification
    with pytest.raises(ValueError):
        milestone.model_copy(update={"fee_waiver_minor": 20}).__class__.model_validate(
            {**milestone.model_dump(), "fee_waiver_minor": 20}
        )


def test_dominance_keeps_distinct_resources_and_robust_tradeoffs() -> None:
    options = [
        bundle("dominated", 5, 3),
        bundle("best", 8, 4),
        bundle("floor", 7, 6),
        bundle("different-card", 4, 2, card_id="other"),
        bundle("different-resources", 4, 2, resource_signature=(("promo", 1),)),
    ]
    result = prune_dominated_bundles(options)
    assert {b.id for b in result} == {"best", "floor", "different-card", "different-resources"}


def test_solver_crosses_cliffs_and_excludes_categories() -> None:
    from core.optimizer.milp_solver import solve_milestones

    choices = [
        bundle("a1", 4, 4, line_id="l1", card_id="A", spend_minor=100),
        bundle("b1", 6, 6, line_id="l1", card_id="B", spend_minor=100),
        bundle("a2", 4, 4, line_id="l2", card_id="A", spend_minor=100),
        bundle("b2", 6, 6, line_id="l2", card_id="B", spend_minor=100),
        bundle(
            "a3", 0, 0, line_id="l3", card_id="A", spend_minor=100, category=SpendCategory.TRANSIT
        ),
    ]
    milestones = [
        SpendMilestone(
            card_id="A",
            threshold_minor=t,
            fee_waiver_minor=v,
            eligible_categories=(SpendCategory.DINING,),
            period_type="annual",
            provenance=PROVENANCE,
        )
        for t, v in [(100, 3), (200, 4), (300, 100)]
    ]
    result = solve_milestones(choices, milestones)
    assert {choice.id for choice in result.chosen} == {"a1", "a2", "a3"}
    assert result.achieved_milestones == (0, 1)
    assert result.objective_scaled == 15 * 100_000


def test_robustness_counts_currency_exposure_once() -> None:
    from core.optimizer.milp_solver import solve_milestones

    choices = [
        bundle("a", 100, 0, currency_id="a"),
        bundle("b", 80, 75, currency_id="b", card_id="b"),
    ]
    assert solve_milestones(choices, [], gamma=0).chosen[0].id == "a"
    assert solve_milestones(choices, [], gamma=1).chosen[0].id == "b"
    assert solve_milestones(choices, [], gamma=2).chosen[0].id == "b"


def test_high_spend_and_solver_determinism() -> None:
    from core.optimizer.milp_solver import solve_milestones

    choices = [bundle("a", 100_000_000, 80_000_000, spend_minor=1_000_000_000)]
    first = solve_milestones(choices, [], gamma=1)
    assert first.objective_scaled == 80_000_000 * 100_000
    assert all(solve_milestones(choices, [], gamma=1) == first for _ in range(4))


def test_cap_tiers_and_shared_promo_limits_are_enforced() -> None:
    from core.optimizer.milp_solver import ConcaveCap, solve_milestones

    choices = [
        bundle(
            "a1",
            0,
            0,
            line_id="l1",
            card_id="A",
            spend_minor=100,
            resource_signature=(("promo", 1),),
        ),
        bundle("b1", 0, 0, line_id="l1", card_id="B", spend_minor=100),
        bundle(
            "a2",
            0,
            0,
            line_id="l2",
            card_id="A",
            spend_minor=100,
            resource_signature=(("promo", 1),),
        ),
        bundle("b2", 0, 0, line_id="l2", card_id="B", spend_minor=100),
    ]
    tier = ConcaveCap(
        card_id="A",
        category=SpendCategory.DINING,
        currency_id="points",
        cap_minor=50,
        first_scaled=10_000,
        remainder_scaled=1_000,
        first_floor_scaled=10_000,
        remainder_floor_scaled=1_000,
        provenance=PROVENANCE,
    )
    solution = solve_milestones(choices, [], resources={"promo": 1}, caps=(tier,))
    assert sum(b.card_id == "A" for b in solution.chosen) == 1
    assert solution.objective_scaled == 50 * 10_000 + 50 * 1_000
    with pytest.raises(ValueError, match="resource"):
        solve_milestones(choices, [], caps=(tier,))


def test_points_bonus_requires_explicit_floor_and_preserves_integer_rounding() -> None:
    from core.optimizer.milp_solver import PointFloor, solve_milestones

    choice = bundle("a", 0, 0, card_id="A")
    milestone = SpendMilestone(
        card_id="A",
        threshold_minor=100,
        bonus_points=3,
        eligible_categories=(SpendCategory.DINING,),
        period_type="annual",
        provenance=PROVENANCE,
    )
    with pytest.raises(ValueError, match="valuation"):
        solve_milestones([choice], [milestone])
    value = PointFloor(
        "miles", nominal_micro_major=1_500_000, floor_micro_major=500_000, provenance=PROVENANCE
    )
    solution = solve_milestones([choice], [milestone], point_values={"A": value}, gamma=1)
    assert solution.objective_scaled == 150 * 100_000


def test_gamma_two_limits_two_distinct_currency_losses() -> None:
    from core.optimizer.milp_solver import solve_milestones

    choices = [
        bundle("a", 100, 0, line_id="l1", currency_id="a"),
        bundle("b", 80, 70, line_id="l1", currency_id="b", card_id="B"),
        bundle("c", 100, 0, line_id="l2", currency_id="c"),
        bundle("d", 80, 70, line_id="l2", currency_id="d", card_id="D"),
    ]
    assert {b.id for b in solve_milestones(choices, [], gamma=0).chosen} == {"a", "c"}
    assert {b.id for b in solve_milestones(choices, [], gamma=1).chosen} == {"b", "d"}
    assert {b.id for b in solve_milestones(choices, [], gamma=2).chosen} == {"b", "d"}


def test_solver_matches_exhaustive_integer_oracle() -> None:
    from itertools import product
    from random import Random

    from core.optimizer.milp_solver import solve_milestones

    random = Random(9)
    for case in range(20):
        choices = []
        for line in range(3):
            for card in range(2):
                nominal = random.randrange(1, 50)
                floor = random.randrange(nominal + 1)
                choices.append(
                    bundle(
                        f"{case}-{line}-{card}",
                        nominal,
                        floor,
                        line_id=str(line),
                        card_id=str(card),
                        currency_id=str(card),
                    )
                )
        grouped = [[b for b in choices if b.line_id == str(i)] for i in range(3)]
        for gamma in (0, 1, 2):
            expected = max(
                sum(b.nominal_minor for b in selected)
                - sum(
                    sorted(
                        (
                            sum(
                                b.nominal_minor - b.floor_minor
                                for b in selected
                                if b.currency_id == currency
                            )
                            for currency in ("0", "1")
                        ),
                        reverse=True,
                    )[:gamma]
                )
                for selected in product(*grouped)
            )
            actual = solve_milestones(choices, [], gamma=gamma)
            assert actual.objective_scaled == expected * 100_000


def test_default_entrypoint_returns_actual_existing_optimizer_result() -> None:
    from core.db import load_kb
    from core.models import CostedTrip, UserWallet
    from core.optimizer import optimize
    from core.optimizer.milp_solver import optimize_trip

    trip = CostedTrip(booking_date=date(2026, 1, 1), trip_start_date=date(2026, 1, 2), lines=[])
    wallet = UserWallet(card_ids=[])
    kb = load_kb()
    assert optimize_trip(trip, wallet, kb).model_dump() == optimize(trip, wallet, kb).model_dump()


def test_active_trip_adapter_uses_kernel_values_and_refuses_capped_rules() -> None:
    from core.db import KnowledgeBase, load_kb
    from core.models import CostedTrip, SpendLineItem, UserWallet
    from core.optimizer.milp_solver import MilestoneSolution, optimize_trip

    source = load_kb()
    cards = source.cards()[:2]
    values = [v for card in cards if (v := source.best_valuation_obj(card.id)) is not None]
    kb = KnowledgeBase.from_models(cards=cards, reward_rules=[], offers=[], point_valuations=values)
    line = SpendLineItem(
        id="test-line",
        label="Synthetic dining",
        category=SpendCategory.DINING,
        amount_minor=100_000,
        currency="INR",
        available_channels=[Channel.POS_DOMESTIC],
    )
    trip = CostedTrip(booking_date=date(2026, 1, 1), trip_start_date=date(2026, 1, 2), lines=[line])
    wallet = UserWallet(card_ids=[card.id for card in cards])
    milestone = SpendMilestone(
        card_id=cards[0].id,
        threshold_minor=100_000,
        fee_waiver_minor=1_000_000,
        eligible_categories=(SpendCategory.DINING,),
        period_type="annual",
        provenance=PROVENANCE,
    )
    result = optimize_trip(trip, wallet, kb, (milestone,))
    assert isinstance(result, MilestoneSolution)
    assert result.chosen[0].card_id == cards[0].id
    assert result.achieved_milestones == (0,)
    with pytest.raises(ValueError, match="block-aware"):
        optimize_trip(trip, wallet, source, (milestone,))


def test_frozen_per_transaction_floor_is_not_concave() -> None:
    from core.models import EarnRate
    from core.optimizer.rules import earn_schedule

    rate = EarnRate(points=1, per_amount_minor=15_000, currency="INR")
    earned = [earn_schedule(spend, [], rate, {}).total_points for spend in (0, 7_500, 15_000)]
    assert earned == [0, 0, 1]
    # An exact concave linear tier would require 2*f(7500) >= f(0)+f(15000).
    assert 2 * earned[1] < earned[0] + earned[2]


@pytest.mark.parametrize("case_path", golden_files())
def test_zero_mode_is_identical_for_each_kernel_golden(case_path) -> None:
    import yaml

    from core.models import CostedTrip, OptimizationPrefs, SpendLineItem, UserWallet
    from core.optimizer import optimize
    from core.optimizer.milp_solver import optimize_trip
    from evals._harness import build_kb

    spec = yaml.safe_load(case_path.read_text())
    booking = date.fromisoformat(str(spec.get("booking_date", "2026-07-24")))
    trip = CostedTrip(
        booking_date=booking,
        trip_start_date=date.fromisoformat(str(spec.get("trip_start_date", booking))),
        lines=[SpendLineItem.model_validate(line) for line in spec["lines"]],
    )
    wallet = UserWallet(**spec["wallet"])
    kb = build_kb(spec["kb"])
    prefs = OptimizationPrefs(**spec.get("prefs", {}))
    assert optimize_trip(trip, wallet, kb, prefs=prefs).model_dump() == (
        optimize(trip, wallet, kb, prefs).model_dump()
    )
