"""OPT-2 multi-currency point pooling, grouped caps, and deadline pruning."""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence

from ortools.sat.python import cp_model
from pydantic import BaseModel, ConfigDict, Field

from core.models import (
    AwardChartEntry,
    AwardTarget,
    LoyaltyProgram,
    TransferBonus,
    TransferEdge,
    TransferPlan,
    TransferStep,
    UserWallet,
)
from core.transfer.arithmetic import (
    BASIS_POINTS,
    destination_units,
    opportunity_cost_minor,
    redemption_value_micro,
)
from core.transfer.checklist import build_checklist

_SAFE_FLOW_BOUND = 1 << 40


class TransferGroupCap(BaseModel):
    """Aggregate source-point cap spanning one named group of transfer edges."""

    model_config = ConfigDict(frozen=True)

    group_id: str
    edge_ids: tuple[str, ...]
    max_source_points: int = Field(ge=0)


class ExpiryDiscount(BaseModel):
    """Sun-Zhang finite-horizon expiry parameters for one currency."""

    model_config = ConfigDict(frozen=True)

    source_currency: str
    hazard_bp: int = Field(ge=0, le=BASIS_POINTS)
    horizon_steps: int = Field(ge=0, le=100)


class PoolingConfig(BaseModel):
    """Deterministic configuration for multi-currency pooled transfer optimization."""

    model_config = ConfigDict(frozen=True)

    deadline_hours: int | None = Field(default=None, ge=0)
    max_transfers: int = Field(default=3, ge=1, le=20)
    grouped_caps: tuple[TransferGroupCap, ...] = ()
    edge_fixed_fees_minor: dict[str, int] = Field(default_factory=dict)
    edge_max_transfer: dict[str, int] = Field(default_factory=dict)
    expiry_discounts: dict[str, ExpiryDiscount] = Field(default_factory=dict)
    max_time_seconds: int = Field(default=2, ge=1, le=30)


class EdgeLotSpec(BaseModel):
    """Exact reduced rational lot parameters for one transfer edge."""

    model_config = ConfigDict(frozen=True)

    edge_id: str
    p_from: int
    q_to: int
    delta_tilde: int
    dest_per_lot: int
    min_lots_when_active: int


class LatencyPruneResult(BaseModel):
    """Surviving subgraph and diagnostics after Stage-1 backward latency pruning."""

    model_config = ConfigDict(frozen=True)

    kept_edges: tuple[TransferEdge, ...]
    min_hours_to_target: dict[str, int]
    pruned_edge_reasons: dict[str, str]


class GroupedCapUsage(BaseModel):
    """Observed usage against one configured grouped transfer cap."""

    model_config = ConfigDict(frozen=True)

    group_id: str
    used_source_points: int
    max_source_points: int


class PooledTransferSolution(BaseModel):
    """Resolved pooled transfer solution alongside cap, expiry, and pruning audit info."""

    model_config = ConfigDict(frozen=True)

    plan: TransferPlan
    blended_baseline_micro: int
    consumed_by_currency: dict[str, int]
    effective_valuations_micro: dict[str, int]
    grouped_cap_usage: tuple[GroupedCapUsage, ...]
    pruned_edge_reasons: dict[str, str]
    critical_path_hours_max: int
    solver_status: str


def sun_zhang_expiry_discount_bp(hazard_bp: int, horizon_steps: int) -> int:
    """Compute closed-form Sun-Zhang expiry discount `1 - (1 - lambda)^K` in basis points."""
    if hazard_bp < 0 or hazard_bp > BASIS_POINTS:
        raise ValueError(f"hazard_bp must be in [0, {BASIS_POINTS}], got {hazard_bp}")
    if horizon_steps < 0:
        raise ValueError(f"horizon_steps must be >= 0, got {horizon_steps}")
    if horizon_steps == 0 or hazard_bp == 0:
        return 0
    if hazard_bp == BASIS_POINTS:
        return BASIS_POINTS
    survival_num = (BASIS_POINTS - hazard_bp) ** horizon_steps
    survival_den = BASIS_POINTS**horizon_steps
    survival_bp = int((BASIS_POINTS * survival_num) // survival_den)
    return BASIS_POINTS - survival_bp


def discounted_valuation_micro(
    base_valuation_micro: int,
    hazard_bp: int,
    horizon_steps: int,
) -> int:
    """Discount baseline valuation by `(1 - lambda)^K` using exact integer arithmetic."""
    if base_valuation_micro < 0:
        raise ValueError(f"base_valuation_micro must be >= 0, got {base_valuation_micro}")
    if hazard_bp < 0 or hazard_bp > BASIS_POINTS:
        raise ValueError(f"hazard_bp must be in [0, {BASIS_POINTS}], got {hazard_bp}")
    if horizon_steps < 0:
        raise ValueError(f"horizon_steps must be >= 0, got {horizon_steps}")
    if horizon_steps == 0 or hazard_bp == 0:
        return base_valuation_micro
    if hazard_bp == BASIS_POINTS:
        return 0
    survival_num = (BASIS_POINTS - hazard_bp) ** horizon_steps
    survival_den = BASIS_POINTS**horizon_steps
    return int((base_valuation_micro * survival_num) // survival_den)


def effective_valuation_map(
    baseline_valuations: dict[str, int],
    expiry_discounts: dict[str, ExpiryDiscount],
) -> dict[str, int]:
    """Resolve effective integer valuations per currency after any expiry discounts."""
    out: dict[str, int] = {}
    for currency in sorted(baseline_valuations):
        base_val = baseline_valuations[currency]
        discount = expiry_discounts.get(currency)
        if discount is None:
            out[currency] = base_val
        else:
            out[currency] = discounted_valuation_micro(
                base_val, discount.hazard_bp, discount.horizon_steps
            )
    return out


def effective_lot_spec(edge: TransferEdge, bonus_bp: int = 0) -> EdgeLotSpec:
    """Compute reduced rational ratio and exact effective lot size `lcm(increment, p_e)`."""
    if bonus_bp < -BASIS_POINTS:
        raise ValueError(f"Invalid bonus_bp: {bonus_bp}")
    raw_num = edge.ratio_to * (BASIS_POINTS + bonus_bp)
    raw_den = edge.ratio_from * BASIS_POINTS
    if raw_num <= 0 or raw_den <= 0:
        return EdgeLotSpec(
            edge_id=edge.id,
            p_from=raw_den,
            q_to=0,
            delta_tilde=edge.increment,
            dest_per_lot=0,
            min_lots_when_active=1,
        )
    gcd_val = math.gcd(raw_num, raw_den)
    q_to = raw_num // gcd_val
    p_from = raw_den // gcd_val
    delta_tilde = math.lcm(edge.increment, p_from)
    dest_per_lot = (delta_tilde // p_from) * q_to
    min_active = max(edge.min_transfer, delta_tilde)
    min_lots = (min_active + delta_tilde - 1) // delta_tilde
    return EdgeLotSpec(
        edge_id=edge.id,
        p_from=p_from,
        q_to=q_to,
        delta_tilde=delta_tilde,
        dest_per_lot=dest_per_lot,
        min_lots_when_active=min_lots,
    )


def _backward_min_hours(
    target_id: str,
    edges: Sequence[TransferEdge],
    max_hops: int | None,
) -> dict[str, int]:
    """Compute shortest worst-case hours from every reachable node to `target_id`."""
    rev_adj: dict[str, list[TransferEdge]] = {}
    for edge in edges:
        rev_adj.setdefault(edge.to_id, []).append(edge)

    if max_hops is None:
        dist: dict[str, int] = {target_id: 0}
        heap: list[tuple[int, str]] = [(0, target_id)]
        while heap:
            hours, node = heapq.heappop(heap)
            if hours > dist.get(node, hours + 1):
                continue
            for edge in rev_adj.get(node, []):
                cand = hours + edge.transfer_time_hours_max
                if cand < dist.get(edge.from_id, cand + 1):
                    dist[edge.from_id] = cand
                    heapq.heappush(heap, (cand, edge.from_id))
        return dist

    if max_hops <= 0:
        return {target_id: 0}

    layer: dict[str, int] = {target_id: 0}
    for _ in range(max_hops):
        next_layer = dict(layer)
        for edge in edges:
            v_hours = layer.get(edge.to_id)
            if v_hours is None:
                continue
            cand = v_hours + edge.transfer_time_hours_max
            if cand < next_layer.get(edge.from_id, cand + 1):
                next_layer[edge.from_id] = cand
        layer = next_layer
    return layer


def prune_edges_by_deadline(
    target_id: str,
    edges: Sequence[TransferEdge],
    source_ids: Sequence[str],
    *,
    deadline_hours: int | None = None,
    max_hops: int | None = None,
) -> LatencyPruneResult:
    """Stage-1 backward latency pruning (WC-A*) and forward reachability filtering."""
    ordered = sorted(edges, key=lambda row: row.id)
    pruned_reasons: dict[str, str] = {}
    structural: list[TransferEdge] = []
    for edge in ordered:
        if edge.from_id == edge.to_id:
            pruned_reasons[edge.id] = "self_loop"
        elif edge.from_id == target_id:
            pruned_reasons[edge.id] = "leaves_target"
        elif deadline_hours is not None and edge.transfer_time_hours_max > deadline_hours:
            pruned_reasons[edge.id] = (
                f"edge_latency_exceeds_deadline:{edge.transfer_time_hours_max}>{deadline_hours}"
            )
        else:
            structural.append(edge)

    suffix_hop_limit = None if max_hops is None else max(max_hops - 1, 0)
    suffix_min_hours = _backward_min_hours(target_id, structural, suffix_hop_limit)

    backward_kept: list[TransferEdge] = []
    for edge in structural:
        to_hours = suffix_min_hours.get(edge.to_id)
        if to_hours is None:
            pruned_reasons[edge.id] = "unreachable_to_target"
            continue
        total_min_hours = edge.transfer_time_hours_max + to_hours
        if deadline_hours is not None and total_min_hours > deadline_hours:
            pruned_reasons[edge.id] = (
                f"path_latency_exceeds_deadline:{total_min_hours}>{deadline_hours}"
            )
            continue
        backward_kept.append(edge)

    fwd_adj: dict[str, list[TransferEdge]] = {}
    for edge in backward_kept:
        fwd_adj.setdefault(edge.from_id, []).append(edge)

    reachable_nodes = set(source_ids)
    queue = sorted(reachable_nodes)
    while queue:
        cur = queue.pop(0)
        for edge in fwd_adj.get(cur, []):
            if edge.to_id not in reachable_nodes:
                reachable_nodes.add(edge.to_id)
                queue.append(edge.to_id)

    kept: list[TransferEdge] = []
    for edge in backward_kept:
        if edge.from_id not in reachable_nodes:
            pruned_reasons[edge.id] = "unreachable_from_funded_source"
        else:
            kept.append(edge)

    full_min_hours = _backward_min_hours(target_id, kept, max_hops)
    return LatencyPruneResult(
        kept_edges=tuple(kept),
        min_hours_to_target=full_min_hours,
        pruned_edge_reasons=pruned_reasons,
    )


def _active_bonuses(
    edges: Sequence[TransferEdge],
    bonuses: Sequence[TransferBonus],
) -> dict[str, TransferBonus]:
    edge_ids = {edge.id for edge in edges}
    candidates = [bonus for bonus in bonuses if bonus.edge_id in edge_ids]
    best: dict[str, TransferBonus] = {}
    for bonus in sorted(candidates, key=lambda row: (-row.bonus_bp, row.id)):
        best.setdefault(bonus.edge_id, bonus)
    return best


def _backward_demand_bounds(
    target_id: str,
    need_net: int,
    edges: Sequence[TransferEdge],
    specs: dict[str, EdgeLotSpec],
    max_hops: int,
) -> dict[str, int]:
    """Upper-bound maximum useful points needed at any node along a simple path."""
    demand: dict[str, int] = {target_id: need_net}
    for _ in range(max_hops):
        updated = dict(demand)
        for edge in edges:
            spec = specs[edge.id]
            to_demand = demand.get(edge.to_id)
            if to_demand is None or spec.dest_per_lot <= 0:
                continue
            lots_needed = (to_demand + spec.dest_per_lot - 1) // spec.dest_per_lot
            lots_needed = max(lots_needed, spec.min_lots_when_active)
            src_needed = min(lots_needed * spec.delta_tilde, _SAFE_FLOW_BOUND)
            if src_needed > updated.get(edge.from_id, 0):
                updated[edge.from_id] = src_needed
        demand = updated
    return demand


def _forward_supply_bounds(
    usable_wallet: dict[str, int],
    edges: Sequence[TransferEdge],
    specs: dict[str, EdgeLotSpec],
    max_hops: int,
) -> dict[str, int]:
    """Upper-bound maximum supply reachable at each node from funded wallet balances."""
    supply: dict[str, int] = {
        node: min(amt, _SAFE_FLOW_BOUND) for node, amt in usable_wallet.items()
    }
    for _ in range(max_hops):
        next_supply = dict(supply)
        for edge in edges:
            spec = specs[edge.id]
            avail = supply.get(edge.from_id, 0)
            max_lots = avail // spec.delta_tilde
            inflow = min(max_lots * spec.dest_per_lot, _SAFE_FLOW_BOUND)
            cand = min(supply.get(edge.to_id, 0) + inflow, _SAFE_FLOW_BOUND)
            if cand > next_supply.get(edge.to_id, 0):
                next_supply[edge.to_id] = cand
        supply = next_supply
    return supply


def _build_pooled_explanation(
    consumed: dict[str, int],
    cap_usage: tuple[GroupedCapUsage, ...],
    critical_hours: int,
    deadline_hours: int | None,
) -> list[str]:
    parts = [f"{qty} {cid}" for cid, qty in sorted(consumed.items())]
    summary = [f"Pooled transfer consuming {', '.join(parts)} across currency sources."]
    for cap in cap_usage:
        summary.append(
            f"Group cap {cap.group_id}: "
            f"{cap.used_source_points}/{cap.max_source_points} points used."
        )
    if deadline_hours is not None:
        summary.append(
            f"Worst-case critical-path latency {critical_hours}h within {deadline_hours}h deadline."
        )
    return summary


def solve_pooled_transfer(
    award: AwardChartEntry,
    target: AwardTarget,
    program: LoyaltyProgram,
    wallet: UserWallet,
    edges: Sequence[TransferEdge],
    bonuses: Sequence[TransferBonus],
    baseline_valuations: dict[str, int],
    award_total_fees_minor: int,
    cash_price_minor: int,
    config: PoolingConfig | None = None,
) -> PooledTransferSolution | None:
    """Solve deterministic CP-SAT fixed-charge generalized flow for one award target."""
    cfg = config or PoolingConfig()
    target_id = award.program_id
    total_miles = award.miles_cost * target.travelers
    program_balance = wallet.points_balances.get(target_id, 0)
    existing_used = min(program_balance, total_miles)
    need_net = total_miles - existing_used

    if need_net == 0:
        savings = cash_price_minor - award_total_fees_minor
        base_plan = TransferPlan(
            id=f"{award.id}:existing",
            award=award,
            travelers=target.travelers,
            steps=[],
            points_consumed=0,
            source_currency=target_id,
            existing_miles_used=existing_used,
            leftover_miles=program_balance - existing_used,
            total_fees_minor=award_total_fees_minor,
            value_per_point_micro=0,
            effective_redemption_cost_minor=award_total_fees_minor,
            savings_vs_cash_minor=savings,
            provenance_flags=(
                [f"award:{award.id}:needs_verification"]
                if award.provenance.needs_verification
                else []
            ),
            explanation=[f"Existing {target_id} balance covers {total_miles} miles."],
        )
        completed = base_plan.model_copy(
            update={"checklist_steps": build_checklist(base_plan, program, {})}
        )
        return PooledTransferSolution(
            plan=completed,
            blended_baseline_micro=baseline_valuations.get(target_id, 0),
            consumed_by_currency={},
            effective_valuations_micro={},
            grouped_cap_usage=(),
            pruned_edge_reasons={},
            critical_path_hours_max=0,
            solver_status="NO_TRANSFER_NEEDED",
        )

    eff_valuations = effective_valuation_map(baseline_valuations, cfg.expiry_discounts)
    usable_wallet: dict[str, int] = {
        cid: amt
        for cid, amt in sorted(wallet.points_balances.items())
        if amt > 0 and cid in baseline_valuations and cid != target_id
    }
    if not usable_wallet:
        return None

    prune_result = prune_edges_by_deadline(
        target_id=target_id,
        edges=edges,
        source_ids=sorted(usable_wallet),
        deadline_hours=cfg.deadline_hours,
        max_hops=cfg.max_transfers,
    )
    pruned_reasons = dict(prune_result.pruned_edge_reasons)
    if not prune_result.kept_edges:
        return None

    bonus_by_edge = _active_bonuses(prune_result.kept_edges, bonuses)
    specs: dict[str, EdgeLotSpec] = {}
    active_candidates: list[TransferEdge] = []
    for edge in prune_result.kept_edges:
        bonus = bonus_by_edge.get(edge.id)
        bonus_bp = bonus.bonus_bp if bonus is not None else 0
        spec = effective_lot_spec(edge, bonus_bp=bonus_bp)
        if spec.dest_per_lot <= 0:
            pruned_reasons[edge.id] = "zero_effective_yield"
            continue
        specs[edge.id] = spec
        active_candidates.append(edge)

    if not active_candidates:
        return None

    demand_bounds = _backward_demand_bounds(
        target_id, need_net, active_candidates, specs, cfg.max_transfers
    )
    supply_bounds = _forward_supply_bounds(
        usable_wallet, active_candidates, specs, cfg.max_transfers
    )

    edge_group_caps: dict[str, list[int]] = {}
    for cap in cfg.grouped_caps:
        for edge_id in dict.fromkeys(cap.edge_ids):
            edge_group_caps.setdefault(edge_id, []).append(cap.max_source_points)

    model = cp_model.CpModel()
    nodes = sorted(
        {target_id}
        | set(usable_wallet)
        | {edge.from_id for edge in active_candidates}
        | {edge.to_id for edge in active_candidates}
    )

    z_vars: dict[str, cp_model.IntVar] = {}
    k_vars: dict[str, cp_model.IntVar] = {}
    k_max_by_edge: dict[str, int] = {}
    modeled_edges: list[TransferEdge] = []
    in_edge_terms: dict[str, list[cp_model.LinearExpr]] = {node: [] for node in nodes}
    out_edge_terms: dict[str, list[cp_model.LinearExpr]] = {node: [] for node in nodes}

    for idx, edge in enumerate(active_candidates):
        spec = specs[edge.id]
        src_supply = supply_bounds.get(edge.from_id, 0)
        src_demand = demand_bounds.get(edge.from_id, need_net)
        upper_src = min(src_supply, max(src_demand, edge.min_transfer))
        if edge.id in cfg.edge_max_transfer:
            upper_src = min(upper_src, cfg.edge_max_transfer[edge.id])
        for gcap in edge_group_caps.get(edge.id, []):
            upper_src = min(upper_src, gcap)
        k_max = upper_src // spec.delta_tilde
        if k_max < spec.min_lots_when_active:
            pruned_reasons[edge.id] = "insufficient_supply_or_cap_for_min_transfer"
            continue

        z_var = model.new_bool_var(f"z_{idx}")
        k_var = model.new_int_var(0, k_max, f"k_{idx}")
        model.add(k_var >= spec.min_lots_when_active * z_var)
        model.add(k_var <= k_max * z_var)

        z_vars[edge.id] = z_var
        k_vars[edge.id] = k_var
        k_max_by_edge[edge.id] = k_max
        modeled_edges.append(edge)

        out_edge_terms[edge.from_id].append(k_var * spec.delta_tilde)
        in_edge_terms[edge.to_id].append(k_var * spec.dest_per_lot)

    if not modeled_edges:
        return None

    # Cardinality bound.
    model.add(sum(z_vars[edge.id] for edge in modeled_edges) <= cfg.max_transfers)
    model.add(sum(z_vars[edge.id] for edge in modeled_edges) >= 1)

    # Grouped source caps across edge groups.
    for cap in cfg.grouped_caps:
        unique_ids = [eid for eid in dict.fromkeys(cap.edge_ids) if eid in k_vars]
        if unique_ids:
            model.add(
                sum(k_vars[eid] * specs[eid].delta_tilde for eid in unique_ids)
                <= cap.max_source_points
            )

    # Acyclic topological rank & sequential settlement arrival bounds.
    node_ranks: dict[str, cp_model.IntVar] = {
        node: model.new_int_var(0, cfg.max_transfers, f"rank_{i}") for i, node in enumerate(nodes)
    }
    arr_hours: dict[str, cp_model.IntVar] = {}
    if cfg.deadline_hours is not None:
        arr_hours = {
            node: model.new_int_var(0, cfg.deadline_hours, f"arr_{i}")
            for i, node in enumerate(nodes)
        }

    for edge in modeled_edges:
        z_var = z_vars[edge.id]
        model.add(node_ranks[edge.to_id] >= node_ranks[edge.from_id] + 1).only_enforce_if(z_var)
        if cfg.deadline_hours is not None:
            model.add(
                arr_hours[edge.to_id] >= arr_hours[edge.from_id] + edge.transfer_time_hours_max
            ).only_enforce_if(z_var)

    # Flow conservation & exact opportunity cost per source currency.
    wallet_used_vars: dict[str, cp_model.IntVar] = {}
    node_leftover_vars: dict[str, cp_model.IntVar] = {}
    opp_cost_terms: list[cp_model.LinearExpr] = []

    for i, node in enumerate(nodes):
        if node == target_id:
            continue
        avail = min(usable_wallet.get(node, 0), supply_bounds.get(node, 0))
        inflow_max = min(
            sum(
                k_max_by_edge[e.id] * specs[e.id].dest_per_lot
                for e in modeled_edges
                if e.to_id == node
            ),
            _SAFE_FLOW_BOUND,
        )
        used_var = model.new_int_var(0, avail, f"used_{i}")
        left_var = model.new_int_var(0, inflow_max, f"left_{i}")
        wallet_used_vars[node] = used_var
        node_leftover_vars[node] = left_var
        model.add(used_var + sum(in_edge_terms[node]) == sum(out_edge_terms[node]) + left_var)
        model.add(left_var <= sum(in_edge_terms[node]))

        eff_val = eff_valuations.get(node, 0)
        if avail > 0 and eff_val > 0:
            q_val = eff_val // BASIS_POINTS
            r_val = eff_val % BASIS_POINTS
            if q_val > 0:
                opp_cost_terms.append(used_var * q_val)
            if r_val > 0:
                rem_max = (avail * r_val) // BASIS_POINTS
                rem_var = model.new_int_var(0, rem_max, f"opp_rem_{i}")
                model.add_division_equality(rem_var, used_var * r_val, BASIS_POINTS)
                opp_cost_terms.append(rem_var)

    target_inflow_max = min(
        sum(
            k_max_by_edge[e.id] * specs[e.id].dest_per_lot
            for e in modeled_edges
            if e.to_id == target_id
        ),
        _SAFE_FLOW_BOUND,
    )
    if target_inflow_max < need_net:
        return None

    target_leftover_var = model.new_int_var(0, target_inflow_max - need_net, "target_leftover")
    model.add(sum(in_edge_terms[target_id]) == need_net + target_leftover_var)

    fixed_fee_terms: list[cp_model.LinearExpr] = []
    for edge in modeled_edges:
        fee_e = cfg.edge_fixed_fees_minor.get(edge.id, 0)
        if fee_e < 0:
            raise ValueError(f"Negative fixed transfer fee not allowed for {edge.id}: {fee_e}")
        if fee_e > 0:
            fixed_fee_terms.append(z_vars[edge.id] * fee_e)

    total_cost_expr = sum(opp_cost_terms) + sum(fixed_fee_terms)
    model.minimize(total_cost_expr)

    def _new_solver() -> cp_model.CpSolver:
        s = cp_model.CpSolver()
        s.parameters.num_search_workers = 1
        s.parameters.random_seed = 1
        s.parameters.max_time_in_seconds = cfg.max_time_seconds
        return s

    solver = _new_solver()
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    snap_z = {edge.id: int(solver.value(z_vars[edge.id])) for edge in modeled_edges}
    snap_k = {edge.id: int(solver.value(k_vars[edge.id])) for edge in modeled_edges}
    snap_used = {cid: int(solver.value(var)) for cid, var in wallet_used_vars.items()}
    snap_ranks = {node: int(solver.value(var)) for node, var in node_ranks.items()}
    accepted_status = status

    # Sequential deterministic tie-breaking with safe snapshots on timeout/UNKNOWN.
    if accepted_status == cp_model.OPTIMAL:
        optimal_cost = int(solver.value(total_cost_expr))
        model.add(total_cost_expr <= optimal_cost)
        step_count_expr = sum(z_vars[edge.id] for edge in modeled_edges)
        step_hours_expr = sum(
            min(edge.transfer_time_hours_max, 10_000) * z_vars[edge.id] for edge in modeled_edges
        )
        waste_expr = sum(node_leftover_vars.values()) + target_leftover_var
        order_tie_expr = sum(
            (idx + 1) * z_vars[edge.id] for idx, edge in enumerate(modeled_edges)
        )

        # Phase 2: minimize step count and cumulative max hours without overflow multipliers.
        model.minimize(step_count_expr * 1_000_000 + step_hours_expr)
        s2 = _new_solver()
        st2 = s2.solve(model)
        if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            snap_z = {edge.id: int(s2.value(z_vars[edge.id])) for edge in modeled_edges}
            snap_k = {edge.id: int(s2.value(k_vars[edge.id])) for edge in modeled_edges}
            snap_used = {cid: int(s2.value(var)) for cid, var in wallet_used_vars.items()}
            snap_ranks = {node: int(s2.value(var)) for node, var in node_ranks.items()}
            accepted_status = st2

        # Phase 3: minimize residual wasted points cleanly (unscaled).
        if st2 == cp_model.OPTIMAL:
            model.add(step_count_expr <= int(s2.value(step_count_expr)))
            model.add(step_hours_expr <= int(s2.value(step_hours_expr)))
            model.minimize(waste_expr)
            s3 = _new_solver()
            st3 = s3.solve(model)
            if st3 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                snap_z = {edge.id: int(s3.value(z_vars[edge.id])) for edge in modeled_edges}
                snap_k = {edge.id: int(s3.value(k_vars[edge.id])) for edge in modeled_edges}
                snap_used = {cid: int(s3.value(var)) for cid, var in wallet_used_vars.items()}
                snap_ranks = {node: int(s3.value(var)) for node, var in node_ranks.items()}
                accepted_status = st3

            # Phase 4: canonical lexical tie-break across edge indices.
            if st3 == cp_model.OPTIMAL:
                model.add(waste_expr <= int(s3.value(waste_expr)))
                model.minimize(order_tie_expr)
                s4 = _new_solver()
                st4 = s4.solve(model)
                if st4 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    snap_z = {edge.id: int(s4.value(z_vars[edge.id])) for edge in modeled_edges}
                    snap_k = {edge.id: int(s4.value(k_vars[edge.id])) for edge in modeled_edges}
                    snap_used = {cid: int(s4.value(var)) for cid, var in wallet_used_vars.items()}
                    snap_ranks = {node: int(s4.value(var)) for node, var in node_ranks.items()}
                    accepted_status = st4

    status_label = "OPTIMAL" if accepted_status == cp_model.OPTIMAL else "FEASIBLE"

    chosen_edges = [edge for edge in modeled_edges if snap_z[edge.id] == 1]
    chosen_edges.sort(
        key=lambda e: (
            snap_ranks[e.from_id],
            snap_ranks[e.to_id],
            e.from_id,
            e.to_id,
            e.id,
        )
    )

    steps: list[TransferStep] = []
    used_bonuses: dict[str, TransferBonus] = {}
    fixed_fees_minor = 0
    edge_source_amounts: dict[str, int] = {}

    for edge in chosen_edges:
        k_val = snap_k[edge.id]
        spec = specs[edge.id]
        source_amt = k_val * spec.delta_tilde
        bonus = bonus_by_edge.get(edge.id)
        bonus_bp = bonus.bonus_bp if bonus is not None else 0
        dest_amt = destination_units(source_amt, edge, bonus_bp)
        if dest_amt != k_val * spec.dest_per_lot:
            expected_dest = k_val * spec.dest_per_lot
            raise AssertionError(
                f"Conservation mismatch on edge {edge.id}: {dest_amt} != {expected_dest}"
            )
        steps.append(
            TransferStep(
                from_id=edge.from_id,
                to_id=edge.to_id,
                amount_source=source_amt,
                amount_dest=dest_amt,
                bonus_applied=bonus.id if bonus is not None else None,
                transfer_time_hours_typical=edge.transfer_time_hours_typical,
                transfer_time_hours_max=edge.transfer_time_hours_max,
            )
        )
        edge_source_amounts[edge.id] = source_amt
        fixed_fees_minor += cfg.edge_fixed_fees_minor.get(edge.id, 0)
        if bonus is not None:
            used_bonuses[bonus.id] = bonus

    consumed_by_currency: dict[str, int] = {}
    total_opp_minor = 0
    weighted_base_num = 0
    weighted_eff_num = 0
    for cid in sorted(wallet_used_vars):
        qty = snap_used[cid]
        if qty > 0:
            consumed_by_currency[cid] = qty
            total_opp_minor += opportunity_cost_minor(qty, eff_valuations[cid])
            weighted_base_num += qty * baseline_valuations[cid]
            weighted_eff_num += qty * eff_valuations[cid]

    points_consumed = sum(consumed_by_currency.values())
    if points_consumed <= 0:
        return None

    total_fees_minor = award_total_fees_minor + fixed_fees_minor
    effective_cost_minor = total_fees_minor + total_opp_minor
    savings_minor = cash_price_minor - effective_cost_minor
    value_per_point = redemption_value_micro(cash_price_minor, total_fees_minor, points_consumed)
    blended_baseline = (
        weighted_eff_num // points_consumed
        if cfg.expiry_discounts
        else weighted_base_num // points_consumed
    )

    critical_hours = _critical_path_hours(chosen_edges, target_id)

    delivered_to_target = sum(step.amount_dest for step in steps if step.to_id == target_id)
    leftover_miles = delivered_to_target - need_net

    cap_usage = tuple(
        GroupedCapUsage(
            group_id=cap.group_id,
            used_source_points=sum(
                edge_source_amounts.get(eid, 0) for eid in dict.fromkeys(cap.edge_ids)
            ),
            max_source_points=cap.max_source_points,
        )
        for cap in cfg.grouped_caps
    )

    provenance_flags: list[str] = []
    if award.provenance.needs_verification:
        provenance_flags.append(f"award:{award.id}:needs_verification")
    for edge in chosen_edges:
        if edge.provenance.needs_verification:
            provenance_flags.append(f"edge:{edge.id}:needs_verification")
        bonus = bonus_by_edge.get(edge.id)
        if bonus is not None and bonus.provenance.needs_verification:
            provenance_flags.append(f"bonus:{bonus.id}:needs_verification")

    source_label = (
        next(iter(consumed_by_currency))
        if len(consumed_by_currency) == 1
        else "+".join(sorted(consumed_by_currency))
    )
    active_edge_ids = "+".join(edge.id for edge in chosen_edges)
    plan_id = f"{award.id}:pooled:{active_edge_ids}"

    draft_plan = TransferPlan(
        id=plan_id,
        award=award,
        travelers=target.travelers,
        steps=steps,
        points_consumed=points_consumed,
        source_currency=source_label,
        existing_miles_used=existing_used,
        leftover_miles=leftover_miles,
        total_fees_minor=total_fees_minor,
        value_per_point_micro=value_per_point,
        effective_redemption_cost_minor=effective_cost_minor,
        savings_vs_cash_minor=savings_minor,
        provenance_flags=list(dict.fromkeys(provenance_flags)),
        explanation=_build_pooled_explanation(
            consumed_by_currency,
            cap_usage,
            critical_hours,
            cfg.deadline_hours,
        ),
    )
    completed_plan = draft_plan.model_copy(
        update={"checklist_steps": build_checklist(draft_plan, program, used_bonuses)}
    )
    return PooledTransferSolution(
        plan=completed_plan,
        blended_baseline_micro=blended_baseline,
        consumed_by_currency=consumed_by_currency,
        effective_valuations_micro={
            cid: eff_valuations[cid] for cid in sorted(consumed_by_currency)
        },
        grouped_cap_usage=cap_usage,
        pruned_edge_reasons=pruned_reasons,
        critical_path_hours_max=critical_hours,
        solver_status=status_label,
    )


def _critical_path_hours(
    chosen_edges: Sequence[TransferEdge],
    target_id: str,
) -> int:
    """Compute exact critical-path worst-case settlement hours to `target_id`."""
    arrival: dict[str, int] = {}
    for _ in range(len(chosen_edges) + 1):
        changed = False
        for edge in chosen_edges:
            cand = arrival.get(edge.from_id, 0) + edge.transfer_time_hours_max
            if cand > arrival.get(edge.to_id, 0):
                arrival[edge.to_id] = cand
                changed = True
        if not changed:
            break
    return arrival.get(target_id, 0)
