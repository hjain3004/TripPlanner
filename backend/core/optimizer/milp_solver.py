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
    Card,
    CostedTrip,
    OptimizationPrefs,
    OptimizerResult,
    Provenance,
    RewardRule,
    SpendCategory,
    UserWallet,
)
from core.optimizer.allocate import Option
from core.optimizer.milestones import Bundle, SpendMilestone, prune_dominated_bundles
from core.optimizer.rules import pool_key

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
    execution_order: tuple[str, ...] = ()


@dataclass(frozen=True)
class _KernelProgram:
    option: Option
    card: Card | None
    rules: tuple[RewardRule, ...]
    nominal_micro: int
    floor_micro: int

    def max_points(self) -> int:
        amount = self.option.post_amount_minor
        if self.card is None:
            return 0
        rates = [rule.earn for rule in self.rules] + [self.card.base_earn]
        if any(rate.per_amount_minor <= 0 or rate.points < 0 for rate in rates):
            raise ValueError("reward rates must have positive blocks and nonnegative points")
        return sum((amount // rate.per_amount_minor) * rate.points for rate in rates)


def _eval_choice_program(
    model: cp_model.CpModel,
    tag: str,
    program: _KernelProgram,
    selected: cp_model.IntVar,
    prior: dict[str, cp_model.IntVar],
    pool_sizes: dict[str, int],
    draws: dict[str, list[cp_model.IntVar]],
) -> tuple[cp_model.IntVar, cp_model.IntVar]:
    maximum = program.option.post_amount_minor
    remaining = model.new_int_var(0, maximum, f"remaining_{tag}_start")
    model.add(remaining == maximum * selected)
    available = dict(prior)
    point_terms: list[cp_model.LinearExpr] = []
    for rule_index, rule in enumerate(program.rules):
        amount = rule.earn.per_amount_minor
        points = rule.earn.points
        blocks = model.new_int_var(0, maximum // amount, f"blocks_{tag}_{rule_index}")
        model.add_division_equality(blocks, remaining, amount)
        has_blocks = model.new_bool_var(f"has_blocks_{tag}_{rule_index}")
        model.add(blocks >= 1).only_enforce_if(has_blocks)
        model.add(blocks == 0).only_enforce_if(has_blocks.Not())
        next_remaining = model.new_int_var(0, maximum, f"remaining_{tag}_{rule_index}")
        rule_pool_key = pool_key(rule)
        if rule_pool_key is None:
            point_terms.append(blocks * points)
            model.add(next_remaining == 0).only_enforce_if(has_blocks)
            model.add(next_remaining == remaining).only_enforce_if(has_blocks.Not())
        else:
            pool_before = available[rule_pool_key]
            size = pool_sizes[rule_pool_key]
            drawn = model.new_int_var(0, size, f"draw_{tag}_{rule_index}")
            if points == 0:
                model.add(drawn == 0)
                model.add(next_remaining == 0).only_enforce_if(has_blocks)
                model.add(next_remaining == remaining).only_enforce_if(has_blocks.Not())
            else:
                binds = model.new_bool_var(f"binds_{tag}_{rule_index}")
                model.add(blocks * points > pool_before).only_enforce_if(binds)
                model.add(blocks * points <= pool_before).only_enforce_if(binds.Not())
                affordable = model.new_int_var(0, size // points, f"afford_{tag}_{rule_index}")
                model.add_division_equality(affordable, pool_before, points)
                model.add(drawn == affordable * points).only_enforce_if(binds)
                model.add(drawn == blocks * points).only_enforce_if(binds.Not())
                model.add(next_remaining == remaining - affordable * amount).only_enforce_if(binds)
                model.add(next_remaining == 0).only_enforce_if([has_blocks, binds.Not()])
                model.add(next_remaining == remaining).only_enforce_if(has_blocks.Not())
            after = model.new_int_var(0, size, f"local_pool_{tag}_{rule_index}")
            model.add(after == pool_before - drawn)
            available[rule_pool_key] = after
            draws[rule_pool_key].append(drawn)
            point_terms.append(drawn)
        remaining = next_remaining
    if program.card is not None:
        base = program.card.base_earn
        blocks = model.new_int_var(0, maximum // base.per_amount_minor, f"base_{tag}")
        model.add_division_equality(blocks, remaining, base.per_amount_minor)
        point_terms.append(blocks * base.points)
    max_points = program.max_points()
    total = model.new_int_var(0, max_points, f"points_{tag}")
    model.add(total == sum(point_terms))
    nominal_bound = max_points * program.nominal_micro // 10_000
    floor_bound = max_points * program.floor_micro // 10_000
    nominal = model.new_int_var(0, nominal_bound, f"nominal_points_{tag}")
    floor = model.new_int_var(0, floor_bound, f"floor_points_{tag}")
    model.add_division_equality(nominal, total * program.nominal_micro, 10_000)
    model.add_division_equality(floor, total * program.floor_micro, 10_000)
    return nominal, floor


def _kernel_terms(
    model: cp_model.CpModel,
    choices: list[Bundle],
    variables: list[cp_model.IntVar],
    programs: dict[str, _KernelProgram],
    pool_sizes: dict[str, int],
) -> tuple[
    dict[str, tuple[cp_model.LinearExpr, cp_model.LinearExpr]],
    list[list[tuple[str, cp_model.IntVar]]],
    list[str],
]:
    """Reproduce the kernel's ordered block floors and shared-cap fall-through.

    Lines that share a cap pool with another line optimize their execution order
    across discrete slots so scarce pools go to the highest-value transactions.
    """
    prior: dict[str, cp_model.IntVar] = {}
    for index, (key, size) in enumerate(sorted(pool_sizes.items())):
        if size < 0 or size > _SAFE_MAX:
            raise ValueError("cap pools must be nonnegative and int64-safe")
        prior[key] = model.new_int_var(size, size, f"pool_start_{index}")
    output: dict[str, tuple[cp_model.LinearExpr, cp_model.LinearExpr]] = {}
    by_line: dict[str, list[tuple[int, Bundle, cp_model.IntVar]]] = defaultdict(list)
    pool_lines: dict[str, set[str]] = defaultdict(set)
    for index, (choice, variable) in enumerate(zip(choices, variables, strict=True)):
        by_line[choice.line_id].append((index, choice, variable))
        for rule in programs[choice.id].rules:
            rpk = pool_key(rule)
            if rpk is not None:
                pool_lines[rpk].add(choice.line_id)

    shared_line_ids = sorted(
        {lid for lids in pool_lines.values() if len(lids) >= 2 for lid in lids}
    )
    use_slots = 2 <= len(shared_line_ids) <= 8
    slot_order_vars: list[list[tuple[str, cp_model.IntVar]]] = []

    if use_slots:
        num_slots = len(shared_line_ids)
        slot_choice_vars: dict[tuple[int, int], cp_model.IntVar] = {}
        line_slot_vars: dict[tuple[str, int], cp_model.IntVar] = {}
        for slot_idx in range(num_slots):
            slot_line_entries: list[tuple[str, cp_model.IntVar]] = []
            for lid in shared_line_ids:
                lvar = model.new_bool_var(f"order_{lid}_slot_{slot_idx}")
                line_slot_vars[(lid, slot_idx)] = lvar
                slot_line_entries.append((lid, lvar))
                c_vars: list[cp_model.IntVar] = []
                for idx, _choice, _var in by_line[lid]:
                    svar = model.new_bool_var(f"slot_{slot_idx}_choice_{idx}")
                    slot_choice_vars[(slot_idx, idx)] = svar
                    c_vars.append(svar)
                model.add(sum(c_vars) == lvar)
            model.add_exactly_one(v for _, v in slot_line_entries)
            slot_order_vars.append(slot_line_entries)
        for lid in shared_line_ids:
            model.add_exactly_one(line_slot_vars[(lid, s)] for s in range(num_slots))
            for idx, _choice, var in by_line[lid]:
                model.add(sum(slot_choice_vars[(s, idx)] for s in range(num_slots)) == var)

        nom_by_choice: dict[str, list[cp_model.IntVar]] = defaultdict(list)
        flr_by_choice: dict[str, list[cp_model.IntVar]] = defaultdict(list)
        for slot_idx in range(num_slots):
            draws: dict[str, list[cp_model.IntVar]] = defaultdict(list)
            for lid in shared_line_ids:
                for idx, choice, _var in by_line[lid]:
                    nom, flr = _eval_choice_program(
                        model,
                        f"s{slot_idx}_{idx}",
                        programs[choice.id],
                        slot_choice_vars[(slot_idx, idx)],
                        prior,
                        pool_sizes,
                        draws,
                    )
                    nom_by_choice[choice.id].append(nom)
                    flr_by_choice[choice.id].append(flr)
            for key, items in draws.items():
                after_slot = model.new_int_var(0, pool_sizes[key], f"pool_s{slot_idx}_{key}")
                model.add(after_slot == prior[key] - sum(items))
                prior[key] = after_slot
        for lid in shared_line_ids:
            for _idx, choice, _var in by_line[lid]:
                output[choice.id] = (
                    cp_model.LinearExpr.sum(nom_by_choice[choice.id]),
                    cp_model.LinearExpr.sum(flr_by_choice[choice.id]),
                )

    remaining_line_ids = [
        lid for lid in by_line if not (use_slots and lid in shared_line_ids)
    ]
    for line_index, lid in enumerate(remaining_line_ids):
        draws = defaultdict(list)
        for index, choice, selected in by_line[lid]:
            nom, flr = _eval_choice_program(
                model,
                str(index),
                programs[choice.id],
                selected,
                prior,
                pool_sizes,
                draws,
            )
            output[choice.id] = (nom, flr)
        for key, items in draws.items():
            after_line = model.new_int_var(0, pool_sizes[key], f"pool_{line_index}_{key}")
            model.add(after_line == prior[key] - sum(items))
            prior[key] = after_line
    return output, slot_order_vars, remaining_line_ids


def solve_milestones(
    bundles: list[Bundle],
    milestones: list[SpendMilestone],
    *,
    gamma: int = 0,
    point_values: dict[str, PointFloor] | None = None,
    resources: dict[str, int] | None = None,
    caps: tuple[ConcaveCap, ...] = (),
    timeout_seconds: int = 10,
    _programs: dict[str, _KernelProgram] | None = None,
    _pool_sizes: dict[str, int] | None = None,
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
    if _programs is not None:
        for program in _programs.values():
            max_points = program.max_points()
            if max_points * program.nominal_micro > _SAFE_MAX:
                raise OverflowError("points valuation exceeds the int64 envelope")
            envelope += max_points * program.nominal_micro // 10_000 * SCALE
    if envelope > _SAFE_MAX or any(v > _SAFE_MAX for v in resources.values()):
        raise OverflowError("model may exceed the safe int64 expression envelope")

    quantum = SCALE
    for cap in caps:
        quantum = gcd(quantum, cap.first_scaled - cap.first_floor_scaled)
        quantum = gcd(quantum, cap.remainder_scaled - cap.remainder_floor_scaled)
    choices = bundles if _programs is not None else prune_dominated_bundles(bundles)
    model = cp_model.CpModel()
    variables = [model.new_bool_var(f"choice_{i}") for i in range(len(choices))]
    by_line: dict[str, list[cp_model.IntVar]] = defaultdict(list)
    by_resource: dict[str, list[cp_model.LinearExpr]] = defaultdict(list)
    nominal: list[cp_model.LinearExpr] = []
    downside: dict[str, list[cp_model.LinearExpr]] = defaultdict(list)
    if _programs is not None:
        kernel, slot_order_vars, remaining_line_ids = _kernel_terms(
            model, choices, variables, _programs, _pool_sizes or {}
        )
    else:
        kernel, slot_order_vars, remaining_line_ids = {}, [], []
    for b, var in zip(choices, variables, strict=True):
        by_line[b.line_id].append(var)
        if b.id in kernel:
            nominal_points, floor_points = kernel[b.id]
            option = _programs[b.id].option if _programs is not None else None
            assert option is not None
            nominal.append((option.discount_minor - option.forex_fee_minor) * SCALE * var)
            nominal.append(SCALE * nominal_points)
            downside[b.currency_id].append((SCALE // quantum) * (nominal_points - floor_points))
        else:
            nominal.append(b.nominal_minor * SCALE * var)
            downside[b.currency_id].append(
                ((b.nominal_minor - b.floor_minor) * SCALE // quantum) * var
            )
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
    # OR-Tools' objective accessor is floating point; evaluate the linear expression
    # through integer variable values rather than converting a floating result.
    objective = sum(solver.value(term) for term in nominal) - sum(
        solver.value(term) for term in penalty
    )
    if slot_order_vars:
        # Canonical tie-break among equal-objective execution orders: prefer
        # lexicographically earlier line_ids in earlier slots without altering objective.
        model.add(sum(nominal) - sum(penalty) == objective)
        num_slots = len(slot_order_vars)
        tie_terms = [
            (num_slots - slot_idx) * (num_slots - rank) * lvar
            for slot_idx, entries in enumerate(slot_order_vars)
            for rank, (_lid, lvar) in enumerate(entries)
        ]
        model.maximize(sum(tie_terms))
        tie_status = solver.solve(model)
        if tie_status != cp_model.OPTIMAL:
            raise RuntimeError(
                f"tie-break solver did not prove an optimum: {solver.status_name(tie_status)}"
            )
    picked_list: list[Bundle] = []
    for b, var in zip(choices, variables, strict=True):
        if not solver.value(var):
            continue
        if b.id in kernel and _programs is not None:
            nominal_points, floor_points = kernel[b.id]
            option = _programs[b.id].option
            cash = option.discount_minor - option.forex_fee_minor
            b = b.model_copy(
                update={
                    "nominal_minor": cash + solver.value(nominal_points),
                    "floor_minor": cash + solver.value(floor_points),
                }
            )
        picked_list.append(b)
    picked = tuple(picked_list)
    achieved = tuple(i for i, var in enumerate(milestone_vars) if solver.value(var))
    if slot_order_vars:
        ordered_shared = [
            lid
            for slot_entries in slot_order_vars
            for lid, lvar in slot_entries
            if solver.value(lvar)
        ]
        execution_order = tuple(ordered_shared + remaining_line_ids)
    else:
        execution_order = tuple(b.line_id for b in picked)
    return MilestoneSolution(picked, achieved, objective, execution_order=execution_order)


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

    Active trips model per-transaction earn blocks and cap fall-through exactly.
    The generic affine-tier API remains separate from the kernel adapter.
    """
    from core.optimizer import optimize
    from core.optimizer.allocate import _line_options, _on_date_fn, _pool_sizes
    from core.optimizer.rules import matching_rules

    if not milestones and gamma == 0:
        return optimize(trip, wallet, kb, prefs)
    if prefs is not None and prefs.objective != "max_savings":
        raise ValueError("OPT-3 currently supports only max_savings")
    if any(m.card_id not in wallet.card_ids or not kb.has_card(m.card_id) for m in milestones):
        raise ValueError("milestones must refer to a card in the wallet")
    pools = _pool_sizes(kb, wallet)
    if len({line.id for line in trip.lines}) != len(trip.lines) or not trip.lines:
        raise ValueError("OPT-3 requires nonempty lines with unique ids")
    values = dict(point_values or {})
    choices: list[Bundle] = []
    programs: dict[str, _KernelProgram] = {}
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
            best_value = kb.best_valuation(option.card_id) if kb.has_card(option.card_id) else None
            if gamma and best_value is not None and best_value[0] > 0 and point_value is None:
                raise ValueError("robust mode requires an explicit floor for earned points")
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
            choice_id = f"{line.id}:{len(choices)}"
            card = kb.card(option.card_id) if kb.has_card(option.card_id) else None
            rules = (
                tuple(matching_rules(kb, line, card, option.channel, on_date(option.channel)))
                if card
                else ()
            )
            nominal_micro = best_value[0] if best_value else 0
            if nominal_micro < 0:
                raise ValueError("negative point valuations are unsupported")
            floor_micro = point_value.floor_micro_major if point_value else nominal_micro
            programs[choice_id] = _KernelProgram(option, card, rules, nominal_micro, floor_micro)
            choices.append(
                Bundle(
                    id=choice_id,
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
        _programs=programs,
        _pool_sizes=pools,
    )
