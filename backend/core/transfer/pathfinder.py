from __future__ import annotations

from datetime import date

from core.db import KnowledgeBase
from core.models import (
    AwardTarget,
    InfeasiblePlan,
    Recommendation,
    RecommendationKind,
    TransferAdvice,
    TransferBonus,
    TransferEdge,
    TransferPlan,
    TransferStep,
    UserWallet,
)
from core.transfer.arithmetic import (
    convert_minor,
    destination_units,
    minimum_source_units,
    opportunity_cost_minor,
    redemption_value_micro,
)
from core.transfer.checklist import build_checklist
from core.transfer.pooling import (
    PoolingConfig,
    effective_valuation_map,
    solve_pooled_transfer,
)

REDEEM_MARGIN_BP = 11_500
BASIS_POINTS = 10_000


def _paths(
    source_ids: list[str], target_id: str, edges: list[TransferEdge]
) -> list[list[TransferEdge]]:
    by_from: dict[str, list[TransferEdge]] = {}
    for edge in sorted(edges, key=lambda row: row.id):
        by_from.setdefault(edge.from_id, []).append(edge)

    out: list[list[TransferEdge]] = []
    for source_id in sorted(source_ids):
        for first in by_from.get(source_id, []):
            if first.to_id == target_id:
                out.append([first])
            for second in by_from.get(first.to_id, []):
                nodes = [first.from_id, first.to_id, second.to_id]
                if second.to_id == target_id and len(nodes) == len(set(nodes)):
                    out.append([first, second])
    return sorted(out, key=lambda path: "+".join(edge.id for edge in path))


def _active_bonus_by_edge(
    path: list[TransferEdge], bonuses: list[TransferBonus]
) -> dict[str, TransferBonus]:
    edge_ids = {edge.id for edge in path}
    candidates = [bonus for bonus in bonuses if bonus.edge_id in edge_ids]
    best: dict[str, TransferBonus] = {}
    for bonus in sorted(candidates, key=lambda row: (-row.bonus_bp, row.id)):
        best.setdefault(bonus.edge_id, bonus)
    return best


def _bonus_bp(edge: TransferEdge, bonuses: dict[str, TransferBonus]) -> int:
    bonus = bonuses.get(edge.id)
    return bonus.bonus_bp if bonus is not None else 0


def _required_source(
    need_dest: int, path: list[TransferEdge], bonuses: dict[str, TransferBonus]
) -> int:
    required = need_dest
    for edge in reversed(path):
        required = minimum_source_units(required, edge, _bonus_bp(edge, bonuses))
    return required


def _forward_steps(
    source: int, path: list[TransferEdge], bonuses: dict[str, TransferBonus]
) -> list[TransferStep]:
    amount = source
    steps: list[TransferStep] = []
    for edge in path:
        bonus = bonuses.get(edge.id)
        dest = destination_units(amount, edge, bonus.bonus_bp if bonus is not None else 0)
        steps.append(
            TransferStep(
                from_id=edge.from_id,
                to_id=edge.to_id,
                amount_source=amount,
                amount_dest=dest,
                bonus_applied=bonus.id if bonus is not None else None,
                transfer_time_hours_typical=edge.transfer_time_hours_typical,
                transfer_time_hours_max=edge.transfer_time_hours_max,
            )
        )
        amount = dest
    return steps


def _typical_hours(plan: TransferPlan) -> int:
    return sum(step.transfer_time_hours_typical for step in plan.steps)


def _max_hours(plan: TransferPlan) -> int:
    return sum(step.transfer_time_hours_max for step in plan.steps)


def _sort_key(plan: TransferPlan) -> tuple[int, int, int, str]:
    return (-plan.savings_vs_cash_minor, len(plan.steps), _typical_hours(plan), plan.id)


def _dominates(left: TransferPlan, right: TransferPlan) -> bool:
    metrics_left = (
        left.savings_vs_cash_minor,
        -len(left.steps),
        -_max_hours(left),
    )
    metrics_right = (
        right.savings_vs_cash_minor,
        -len(right.steps),
        -_max_hours(right),
    )
    return all(a >= b for a, b in zip(metrics_left, metrics_right, strict=False)) and any(
        a > b for a, b in zip(metrics_left, metrics_right, strict=False)
    )


def _mark_dominated(plans: list[TransferPlan]) -> list[TransferPlan]:
    dominated_ids = {
        plan.id
        for plan in plans
        if any(other.id != plan.id and _dominates(other, plan) for other in plans)
    }
    kept = [plan for plan in plans if plan.id not in dominated_ids]
    dominated_two_hops = sorted(
        [plan for plan in plans if plan.id in dominated_ids and len(plan.steps) == 2],
        key=_sort_key,
    )
    if dominated_two_hops:
        kept.append(dominated_two_hops[0].model_copy(update={"dominated": True}))
    return sorted(kept, key=_sort_key)


def _provenance_flags(
    plan: TransferPlan, path: list[TransferEdge], bonuses: dict[str, TransferBonus]
) -> list[str]:
    flags: list[str] = []
    if plan.award.provenance.needs_verification:
        flags.append(f"award:{plan.award.id}:needs_verification")
    for edge in path:
        if edge.provenance.needs_verification:
            flags.append(f"edge:{edge.id}:needs_verification")
        bonus = bonuses.get(edge.id)
        if bonus is not None and bonus.provenance.needs_verification:
            flags.append(f"bonus:{bonus.id}:needs_verification")
    return flags


def _fees_for_target(
    award_fees_minor: int,
    award_currency: str,
    target: AwardTarget,
    kb: KnowledgeBase,
) -> int | None:
    if award_currency == target.home_currency:
        return award_fees_minor
    rate = kb.fx_rate(award_currency, target.home_currency)
    if rate is None:
        return None
    return convert_minor(award_fees_minor, rate)


def _all_relevant_edges(kb: KnowledgeBase, source_ids: list[str]) -> list[TransferEdge]:
    first_edges = kb.edges_from(source_ids)
    second_sources = sorted({edge.to_id for edge in first_edges})
    second_edges = kb.edges_from(second_sources)
    by_id = {edge.id: edge for edge in [*first_edges, *second_edges]}
    return [by_id[key] for key in sorted(by_id)]


def _collect_edges_up_to_hops(
    kb: KnowledgeBase, source_ids: list[str], max_hops: int
) -> list[TransferEdge]:
    by_id: dict[str, TransferEdge] = {}
    frontier = sorted(set(source_ids))
    visited = set(frontier)
    for _ in range(max_hops):
        if not frontier:
            break
        batch = kb.edges_from(frontier)
        next_nodes: set[str] = set()
        for edge in batch:
            by_id[edge.id] = edge
            if edge.to_id not in visited:
                visited.add(edge.to_id)
                next_nodes.add(edge.to_id)
        frontier = sorted(next_nodes)
    return [by_id[key] for key in sorted(by_id)]


def _single_path_pooling_violation(
    path: list[TransferEdge],
    steps: list[TransferStep],
    cfg: PoolingConfig,
) -> str | None:
    if len(path) > cfg.max_transfers:
        return f"Path exceeds max_transfers ({len(path)} > {cfg.max_transfers})."
    if cfg.deadline_hours is not None:
        total_hours = sum(edge.transfer_time_hours_max for edge in path)
        if total_hours > cfg.deadline_hours:
            return f"Path worst-case latency {total_hours}h exceeds {cfg.deadline_hours}h deadline."
    edge_sources = {edge.id: step.amount_source for edge, step in zip(path, steps, strict=True)}
    for edge in path:
        cap = cfg.edge_max_transfer.get(edge.id)
        if cap is not None and edge_sources[edge.id] > cap:
            return f"Edge {edge.id} transfer {edge_sources[edge.id]} exceeds cap {cap}."
    for group_cap in cfg.grouped_caps:
        used = sum(edge_sources.get(eid, 0) for eid in dict.fromkeys(group_cap.edge_ids))
        if used > group_cap.max_source_points:
            return (
                f"Grouped cap {group_cap.group_id} exceeded: "
                f"{used} > {group_cap.max_source_points}."
            )
    return None


def _recommend(
    plans: list[TransferPlan],
    baseline_valuations: dict[str, int],
    plan_baselines: dict[str, int] | None = None,
) -> Recommendation:
    for plan in plans:
        if plan.dominated:
            continue
        if plan.savings_vs_cash_minor <= 0:
            break
        if not plan.steps:
            return Recommendation(
                kind=RecommendationKind.REDEEM,
                plan_id=plan.id,
                reason="Existing miles cover the award and savings are positive.",
            )
        baseline = (
            plan_baselines[plan.id]
            if plan_baselines is not None and plan.id in plan_baselines
            else baseline_valuations[plan.source_currency]
        )
        if plan.value_per_point_micro * BASIS_POINTS >= baseline * REDEEM_MARGIN_BP:
            return Recommendation(
                kind=RecommendationKind.REDEEM,
                plan_id=plan.id,
                reason=(
                    f"Value {plan.value_per_point_micro} micro-major/point meets "
                    f"margin {REDEEM_MARGIN_BP} bp over baseline {baseline}."
                ),
            )
        return Recommendation(
            kind=RecommendationKind.PAY_CASH,
            plan_id=None,
            reason=(
                f"Best transfer value {plan.value_per_point_micro} micro-major/point "
                f"does not clear {REDEEM_MARGIN_BP} bp margin over baseline {baseline}."
            ),
        )
    return Recommendation(
        kind=RecommendationKind.PAY_CASH,
        plan_id=None,
        reason="No transfer plan saves money versus cash.",
    )


def find_transfer_plans(
    target: AwardTarget,
    wallet: UserWallet,
    kb: KnowledgeBase,
    baseline_valuations: dict[str, int],
    cash_price_minor: int,
    on_date: date,
    *,
    allow_pooling: bool = False,
    pooling_config: PoolingConfig | None = None,
) -> TransferAdvice:
    awards = kb.award_entries(target.origin, target.destination, target.cabin, target.trip_type)
    if not awards:
        return TransferAdvice(
            plans=[],
            infeasible=[],
            recommendation=Recommendation(
                kind=RecommendationKind.NO_DATA,
                reason="No transfer advice for this route; no award-chart evidence is available.",
            ),
        )

    pooling_active = allow_pooling or pooling_config is not None
    cfg = pooling_config or PoolingConfig()
    eff_valuations = (
        effective_valuation_map(baseline_valuations, cfg.expiry_discounts)
        if pooling_active
        else baseline_valuations
    )

    source_ids = sorted(wallet.points_balances)
    edges = (
        _collect_edges_up_to_hops(kb, source_ids, cfg.max_transfers)
        if pooling_active
        else _all_relevant_edges(kb, source_ids)
    )
    active_bonuses = kb.bonuses_active([edge.id for edge in edges], on_date)
    plans: list[TransferPlan] = []
    infeasible: list[InfeasiblePlan] = []
    checklist_bonus_rows: dict[str, TransferBonus] = {}
    plan_baselines: dict[str, int] = {}

    for award in sorted(awards, key=lambda row: row.id):
        program = kb.program(award.program_id)
        fee_per_person = _fees_for_target(award.fees_minor, award.fees_currency, target, kb)
        if fee_per_person is None:
            infeasible.append(
                InfeasiblePlan(
                    award_id=award.id,
                    best_path=[],
                    shortfall_points=1,
                    shortfall_currency=f"{award.fees_currency}->{target.home_currency}",
                    note=(
                        f"Missing FX rate for {award.fees_currency}->{target.home_currency}; "
                        "cannot compare award fees."
                    ),
                )
            )
            continue
        total_fees = fee_per_person * target.travelers
        total_miles = award.miles_cost * target.travelers
        program_balance = wallet.points_balances.get(award.program_id, 0)
        existing_used = min(program_balance, total_miles)
        need_net = total_miles - existing_used

        if need_net == 0:
            effective_cost = total_fees
            savings = cash_price_minor - effective_cost
            plan = TransferPlan(
                id=f"{award.id}:existing",
                award=award,
                travelers=target.travelers,
                steps=[],
                points_consumed=0,
                source_currency=award.program_id,
                existing_miles_used=existing_used,
                leftover_miles=program_balance - existing_used,
                total_fees_minor=total_fees,
                value_per_point_micro=0,
                effective_redemption_cost_minor=effective_cost,
                savings_vs_cash_minor=savings,
                provenance_flags=(
                    [f"award:{award.id}:needs_verification"]
                    if award.provenance.needs_verification
                    else []
                ),
                explanation=[f"Existing {award.program_id} balance covers {total_miles} miles."],
            )
            plans.append(
                plan.model_copy(update={"checklist_steps": build_checklist(plan, program, {})})
            )
            continue

        seen_step_signatures: set[tuple[tuple[str, str, int, int], ...]] = set()
        for path in _paths(source_ids, award.program_id, edges):
            bonuses = _active_bonus_by_edge(path, active_bonuses)
            source_required = _required_source(need_net, path, bonuses)
            source_id = path[0].from_id
            balance = wallet.points_balances.get(source_id, 0)
            path_ids = [edge.id for edge in path]
            if source_required > balance:
                infeasible.append(
                    InfeasiblePlan(
                        award_id=award.id,
                        best_path=path_ids,
                        shortfall_points=source_required - balance,
                        shortfall_currency=source_id,
                        note=(
                            f"Need {source_required} {source_id} points via "
                            f"{' -> '.join(edge.to_id for edge in path)}; "
                            f"you have {balance}."
                        ),
                    )
                )
                continue
            if source_id not in baseline_valuations:
                infeasible.append(
                    InfeasiblePlan(
                        award_id=award.id,
                        best_path=path_ids,
                        shortfall_points=1,
                        shortfall_currency=source_id,
                        note=f"Missing baseline valuation for {source_id}.",
                    )
                )
                continue
            steps = _forward_steps(source_required, path, bonuses)
            if pooling_active:
                violation = _single_path_pooling_violation(path, steps, cfg)
                if violation is not None:
                    infeasible.append(
                        InfeasiblePlan(
                            award_id=award.id,
                            best_path=path_ids,
                            shortfall_points=1,
                            shortfall_currency=source_id,
                            note=violation,
                        )
                    )
                    continue
            destination_received = steps[-1].amount_dest
            fixed_fee_minor = (
                sum(cfg.edge_fixed_fees_minor.get(edge.id, 0) for edge in path)
                if pooling_active
                else 0
            )
            effective_total_fees = total_fees + fixed_fee_minor
            value_per_point = redemption_value_micro(
                cash_price_minor, effective_total_fees, source_required
            )
            opp_valuation = (
                eff_valuations[source_id] if pooling_active else baseline_valuations[source_id]
            )
            opportunity_cost = opportunity_cost_minor(source_required, opp_valuation)
            effective_cost = effective_total_fees + opportunity_cost
            savings = cash_price_minor - effective_cost
            plan_id = f"{award.id}:{'+'.join(path_ids)}"
            plan = TransferPlan(
                id=plan_id,
                award=award,
                travelers=target.travelers,
                steps=steps,
                points_consumed=source_required,
                source_currency=source_id,
                existing_miles_used=existing_used,
                leftover_miles=destination_received - need_net,
                total_fees_minor=effective_total_fees,
                value_per_point_micro=value_per_point,
                effective_redemption_cost_minor=effective_cost,
                savings_vs_cash_minor=savings,
                provenance_flags=_provenance_flags(
                    TransferPlan(
                        id=plan_id,
                        award=award,
                        travelers=target.travelers,
                        steps=steps,
                        points_consumed=source_required,
                        source_currency=source_id,
                        existing_miles_used=existing_used,
                        leftover_miles=destination_received - need_net,
                        total_fees_minor=effective_total_fees,
                        value_per_point_micro=value_per_point,
                        effective_redemption_cost_minor=effective_cost,
                        savings_vs_cash_minor=savings,
                    ),
                    path,
                    bonuses,
                ),
                explanation=[
                    f"Transfer path {' -> '.join([source_id, *[edge.to_id for edge in path]])} "
                    f"requires {source_required} {source_id} points."
                ],
            )
            checklist_bonus_rows.update(bonuses)
            if pooling_active:
                plan_baselines[plan_id] = opp_valuation
                seen_step_signatures.add(
                    tuple((s.from_id, s.to_id, s.amount_source, s.amount_dest) for s in steps)
                )
            plans.append(plan)

        if pooling_active:
            pooled = solve_pooled_transfer(
                award=award,
                target=target,
                program=program,
                wallet=wallet,
                edges=edges,
                bonuses=active_bonuses,
                baseline_valuations=baseline_valuations,
                award_total_fees_minor=total_fees,
                cash_price_minor=cash_price_minor,
                config=cfg,
            )
            if pooled is not None:
                sig = tuple(
                    (s.from_id, s.to_id, s.amount_source, s.amount_dest) for s in pooled.plan.steps
                )
                if sig not in seen_step_signatures:
                    plan_baselines[pooled.plan.id] = pooled.blended_baseline_micro
                    plans.append(pooled.plan)

    ranked = _mark_dominated(plans)
    completed: list[TransferPlan] = []
    for plan in ranked:
        if plan.checklist_steps:
            completed.append(plan)
            continue
        program = kb.program(plan.award.program_id)
        plan_bonuses = {
            step.bonus_applied: checklist_bonus_rows[step.bonus_applied]
            for step in plan.steps
            if step.bonus_applied is not None and step.bonus_applied in checklist_bonus_rows
        }
        completed.append(
            plan.model_copy(
                update={"checklist_steps": build_checklist(plan, program, plan_bonuses)}
            )
        )
    return TransferAdvice(
        plans=completed,
        infeasible=sorted(
            infeasible,
            key=lambda row: (row.award_id, "+".join(row.best_path), row.shortfall_currency),
        ),
        recommendation=_recommend(
            completed,
            baseline_valuations,
            plan_baselines if pooling_active else None,
        ),
    )
