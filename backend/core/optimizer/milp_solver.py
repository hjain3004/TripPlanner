"""Opt-in deterministic CP-SAT solver over independently evaluated spend bundles.

This module does not replace the frozen allocator. Inputs are already evaluated
minor-unit benefits; callers must not treat a scaled-rate approximation as an exact
per-transaction points calculation. Unsupported inputs fail closed.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import gcd
from typing import Literal

from ortools.sat.python import cp_model

from core.db import KnowledgeBase
from core.models import (
    CostedTrip,
    OptimizationPrefs,
    OptimizerResult,
    Provenance,
    SpendCategory,
    UserWallet,
)
from core.optimizer.milestones import Bundle, SpendMilestone, prune_dominated_bundles

SCALE = 100_000
_SAFE_MAX = (1 << 61) - 1


@dataclass(frozen=True)
class PointFloor:
    currency_id: str
    nominal_micro_major: int
    floor_micro_major: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.currency_id or not 0 <= self.floor_micro_major <= self.nominal_micro_major:
            raise ValueError("a named currency and nonnegative guaranteed floor are required")


@dataclass(frozen=True)
class ConcaveCap:
    """A verified two-tier marginal yield, expressed in 1/100000 minor units per minor spent."""

    card_id: str
    category: SpendCategory
    currency_id: str
    cap_minor: int
    first_scaled: int
    remainder_scaled: int
    first_floor_scaled: int
    remainder_floor_scaled: int
    provenance: Provenance

    def __post_init__(self) -> None:
        if (
            not self.card_id
            or not self.currency_id
            or self.cap_minor < 0
            or not 0 <= self.first_floor_scaled <= self.first_scaled
            or not 0 <= self.remainder_floor_scaled <= self.remainder_scaled
            or self.first_scaled < self.remainder_scaled
            or self.first_floor_scaled < self.remainder_floor_scaled
        ):
            raise ValueError("cap tiers must be nonnegative and concave at nominal and floor")


@dataclass(frozen=True)
class MilestoneSolution:
    chosen: tuple[Bundle, ...]
    achieved_milestones: tuple[int, ...]
    objective_scaled: int
    status: Literal["optimal"] = "optimal"


def solve_milestones(
    bundles: list[Bundle],
    milestones: list[SpendMilestone],
    *,
    gamma: int = 0,
    point_values: dict[str, PointFloor] | None = None,
    resources: dict[str, int] | None = None,
    caps: tuple[ConcaveCap, ...] = (),
    timeout_seconds: int = 10,
) -> MilestoneSolution:
    """Solve an exact integer model for the supplied evaluated bundles.

    ``gamma`` applies to aggregate downside per points currency, not per line.
    Fail rather than return an unproven optimum or fabricate a points floor.
    """
    if gamma not in (0, 1, 2) or not 1 <= timeout_seconds <= 60:
        raise ValueError("gamma must be 0..2 and timeout must be 1..60 seconds")
    if not bundles or len({b.id for b in bundles}) != len(bundles):
        raise ValueError("bundles must be nonempty and have unique ids")
    point_values = point_values or {}
    resources = resources or {}
    if any(not k or v < 0 for k, v in resources.items()):
        raise ValueError("resource capacities must be named and nonnegative")
    for bundle in bundles:
        if any(key not in resources for key, _ in bundle.resource_signature):
            raise ValueError("every scarce resource requires an explicit capacity")
    if len({(c.card_id, c.category) for c in caps}) != len(caps):
        raise ValueError("overlapping cap definitions are ambiguous")

    # CP-SAT requires int64-safe expression domains, not just a safe optimal value.
    envelope = sum(
        (abs(b.nominal_minor) + abs(b.floor_minor) + b.spend_minor) * SCALE for b in bundles
    )
    for m in milestones:
        if m.bonus_points is not None:
            value = point_values.get(m.card_id)
            if value is None:
                raise ValueError("points milestone requires an explicit valuation and floor")
            envelope += m.bonus_points * value.nominal_micro_major // 10_000 * SCALE
        else:
            envelope += (m.fee_waiver_minor or 0) * SCALE
        envelope += m.threshold_minor + m.prior_spend_minor
    for cap in caps:
        envelope += sum(
            b.spend_minor
            for b in bundles
            if b.card_id == cap.card_id and b.category == cap.category
        ) * (cap.first_scaled + cap.remainder_scaled)
    if envelope > _SAFE_MAX or any(v > _SAFE_MAX for v in resources.values()):
        raise OverflowError("model may exceed the safe int64 expression envelope")

    quantum = SCALE
    for cap in caps:
        quantum = gcd(quantum, cap.first_scaled - cap.first_floor_scaled)
        quantum = gcd(quantum, cap.remainder_scaled - cap.remainder_floor_scaled)
    choices = prune_dominated_bundles(bundles)
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"choice_{i}") for i in range(len(choices))]
    by_line: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    by_resource: dict[str, list[cp_model.LinearExpr]] = defaultdict(list)
    nominal: list[cp_model.LinearExpr] = []
    downside: dict[str, list[cp_model.LinearExpr]] = defaultdict(list)
    for b, var in zip(choices, variables, strict=True):
        by_line[b.line_id].append(var)
        nominal.append(b.nominal_minor * SCALE * var)
        downside[b.currency_id].append(((b.nominal_minor - b.floor_minor) * SCALE // quantum) * var)
        for key, amount in b.resource_signature:
            by_resource[key].append(amount * var)
    for vars_for_line in by_line.values():
        model.add_exactly_one(vars_for_line)
    for key, terms in by_resource.items():
        model.add(sum(terms) <= resources[key])

    milestone_vars: list[cp_model.IntVar] = []
    groups: dict[tuple[object, ...], list[tuple[int, cp_model.IntVar]]] = defaultdict(list)
    for i, m in enumerate(milestones):
        var = model.new_bool_var(f"milestone_{i}")
        milestone_vars.append(var)
        eligible = sum(
            b.spend_minor * v
            for b, v in zip(choices, variables, strict=True)
            if b.card_id == m.card_id and b.category in m.eligible_categories
        )
        required = m.threshold_minor - m.prior_spend_minor
        model.add(eligible >= required).only_enforce_if(var)
        model.add(eligible <= required - 1).only_enforce_if(var.Not())
        milestone_key = (
            m.card_id,
            m.period_type,
            tuple(sorted(m.eligible_categories)),
            m.prior_spend_minor,
        )
        groups[milestone_key].append((m.threshold_minor, var))
        if m.bonus_points is None:
            nominal.append((m.fee_waiver_minor or 0) * SCALE * var)
        else:
            value = point_values[m.card_id]
            upper = m.bonus_points * value.nominal_micro_major // 10_000
            floor = m.bonus_points * value.floor_micro_major // 10_000
            nominal.append(upper * SCALE * var)
            downside[value.currency_id].append(((upper - floor) * SCALE // quantum) * var)
    for milestone_group in groups.values():
        ordered = sorted(milestone_group, key=lambda p: p[0])
        for (_, first), (_, second) in zip(ordered, ordered[1:], strict=False):
            model.add(second <= first)

    for i, cap in enumerate(caps):
        terms = [
            b.spend_minor * v
            for b, v in zip(choices, variables, strict=True)
            if b.card_id == cap.card_id and b.category == cap.category
        ]
        maximum = sum(
            b.spend_minor
            for b in choices
            if b.card_id == cap.card_id and b.category == cap.category
        )
        first = model.new_int_var(0, min(cap.cap_minor, maximum), f"tier1_{i}")
        rest = model.new_int_var(0, maximum, f"tier2_{i}")
        model.add(first + rest == sum(terms))
        nominal.extend((cap.first_scaled * first, cap.remainder_scaled * rest))
        downside[cap.currency_id].extend(
            (
                ((cap.first_scaled - cap.first_floor_scaled) // quantum) * first,
                ((cap.remainder_scaled - cap.remainder_floor_scaled) // quantum) * rest,
            )
        )

    penalty: list[cp_model.LinearExpr] = []
    if gamma:
        threshold = model.new_int_var(0, envelope // quantum, "risk_threshold")
        penalty.append(gamma * quantum * threshold)
        for i, terms in enumerate(downside.values()):
            excess = model.new_int_var(0, envelope // quantum, f"risk_excess_{i}")
            model.add(excess >= sum(terms) - threshold)
            penalty.append(quantum * excess)
    model.maximize(sum(nominal) - sum(penalty))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    solver.parameters.max_time_in_seconds = timeout_seconds
    status = solver.solve(model)
    if status != cp_model.OPTIMAL:
        raise RuntimeError(f"solver did not prove an optimum: {solver.status_name(status)}")
    picked = tuple(b for b, var in zip(choices, variables, strict=True) if solver.value(var))
    achieved = tuple(i for i, var in enumerate(milestone_vars) if solver.value(var))
    # OR-Tools' objective accessor is floating point; evaluate the linear expression
    # through integer variable values rather than converting a floating result.
    objective = sum(solver.value(term) for term in nominal) - sum(
        solver.value(term) for term in penalty
    )
    return MilestoneSolution(picked, achieved, objective)


def optimize_trip(
    trip: CostedTrip,
    wallet: UserWallet,
    kb: KnowledgeBase,
    milestones: tuple[SpendMilestone, ...] = (),
    *,
    gamma: int = 0,
    point_values: dict[str, PointFloor] | None = None,
    prefs: OptimizationPrefs | None = None,
    timeout_seconds: int = 10,
) -> OptimizerResult | MilestoneSolution:
    """Use the frozen optimizer unless the caller explicitly enables OPT-3.

    The active adapter accepts uncapped rules only: a generic affine cap cannot
    reproduce the kernel's per-transaction floors and cap fall-through. Such
    inputs fail closed until represented exactly rather than changing money math.
    """
    from core.optimizer import optimize
    from core.optimizer.allocate import _line_options, _on_date_fn, _pool_sizes

    if not milestones and gamma == 0:
        return optimize(trip, wallet, kb, prefs)
    if prefs is not None and prefs.objective != "max_savings":
        raise ValueError("OPT-3 currently supports only max_savings")
    if any(m.card_id not in wallet.card_ids or not kb.has_card(m.card_id) for m in milestones):
        raise ValueError("milestones must refer to a card in the wallet")
    if _pool_sizes(kb, wallet):
        raise ValueError("capped kernel reward rules require exact block-aware modeling")
    if len({line.id for line in trip.lines}) != len(trip.lines) or not trip.lines:
        raise ValueError("OPT-3 requires nonempty lines with unique ids")
    values = dict(point_values or {})
    choices: list[Bundle] = []
    capacities: dict[str, int] = {}
    on_date = _on_date_fn(trip)
    for line in sorted(trip.lines, key=lambda item: item.id):
        options = _line_options(kb, line, wallet, {}, {}, on_date)
        seen: set[tuple[object, ...]] = set()
        for option in options:
            key = (option.card_id, option.channel, tuple(x.offer_id for x in option.applied))
            if key in seen:
                continue
            seen.add(key)
            point_value = values.get(option.card_id)
            if option.points and gamma and point_value is None:
                raise ValueError("robust mode requires an explicit floor for earned points")
            best_value = kb.best_valuation(option.card_id) if kb.has_card(option.card_id) else None
            if point_value is not None and best_value is not None:
                if point_value.nominal_micro_major != best_value[0]:
                    raise ValueError("nominal valuation must match the kernel's selected valuation")
            if point_value is None:
                currency = option.card_id
                floor_benefit = option.benefit_minor
            else:
                currency = point_value.currency_id
                floor_benefit = (
                    option.discount_minor
                    - option.forex_fee_minor
                    + option.points * point_value.floor_micro_major // 10_000
                )
            signatures = []
            for offer_id, limit in option.uses_offers:
                resource = f"{option.card_id}:{offer_id}"
                capacities[resource] = min(capacities.get(resource, limit), limit)
                signatures.append((resource, 1))
            choices.append(
                Bundle(
                    id=f"{line.id}:{len(choices)}",
                    line_id=line.id,
                    card_id=option.card_id,
                    channel=option.channel,
                    category=line.category,
                    spend_minor=option.post_amount_minor,
                    currency_id=currency,
                    nominal_minor=option.benefit_minor,
                    floor_minor=floor_benefit,
                    resource_signature=tuple(sorted(signatures)),
                )
            )
    return solve_milestones(
        choices,
        list(milestones),
        gamma=gamma,
        point_values=values,
        resources=capacities,
        timeout_seconds=timeout_seconds,
    )
