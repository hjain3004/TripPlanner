"""Assemble the machine-readable OptimizerResult from an allocation (spec 02 §7).

Every user-facing number must be traceable to a field here; the explainer LLM
(M2) may rephrase these atoms but must never recompute them.
"""

from __future__ import annotations

from core.db import KnowledgeBase
from core.models import (
    CostedTrip,
    LineAssignment,
    OptimizationPrefs,
    OptimizerResult,
    RedemptionPath,
    RunnerUp,
    SpendLineItem,
    UserWallet,
)
from core.optimizer.allocate import AllocationResult, Option
from core.optimizer.money import savings_pct_bp


def _rupees(minor: int) -> str:
    return f"₹{minor // 100:,}"


def _explanation(line: SpendLineItem, opt: Option) -> list[str]:
    atoms: list[str] = []
    for applied in opt.applied:
        atoms.append(
            f"Applied offer {applied.offer_id} ({applied.stacking_class}): "
            f"-{_rupees(applied.discount_minor)} on running amount"
        )
    if opt.discount_minor:
        atoms.append(
            f"Points base reduced to {_rupees(opt.post_amount_minor)} after instant discount"
        )
    for seg in opt.segments:
        atoms.append(f"{seg.description}: +{seg.points} pts on {_rupees(seg.amount_minor)}")
    if opt.points_value_minor:
        atoms.append(
            f"{opt.points} pts valued at {_rupees(opt.points_value_minor)} "
            f"(assumes redemption via {opt.assumed_redemption.value})"
        )
    if opt.forex_fee_minor:
        atoms.append(
            f"Forex fee {_rupees(opt.forex_fee_minor)} on {_rupees(opt.post_amount_minor)} "
            f"(POS abroad)"
        )
    atoms.extend(opt.expired_notes)
    return atoms


def _runner_up(chosen: Option, runner: Option | None) -> RunnerUp | None:
    if runner is None:
        return None
    delta = chosen.benefit_minor - runner.benefit_minor
    return RunnerUp(
        card_id=runner.card_id,
        channel=runner.channel,
        benefit_minor=runner.benefit_minor,
        delta_minor=delta,
        summary=(
            f"{runner.card_id} via {runner.channel.value} "
            f"(benefit {_rupees(runner.benefit_minor)}, -{_rupees(delta)} vs chosen)"
        ),
    )


def _assignment(line: SpendLineItem, opt: Option, runner: Option | None) -> LineAssignment:
    return LineAssignment(
        line=line,
        card_id=opt.card_id,
        channel=opt.channel,
        offers_applied=opt.applied,
        points_earned=opt.points,
        points_value_minor=opt.points_value_minor,
        assumed_redemption=opt.assumed_redemption,
        forex_fee_minor=opt.forex_fee_minor,
        benefit_minor=opt.benefit_minor,
        explanation=_explanation(line, opt),
        provenance_flags=opt.provenance_flags,
        runner_up=_runner_up(opt, runner),
    )


def build_result(
    kb: KnowledgeBase,
    trip: CostedTrip,
    wallet: UserWallet,
    alloc: AllocationResult,
    prefs: OptimizationPrefs,
) -> OptimizerResult:
    assignments: list[LineAssignment] = []
    for line in alloc.lines:
        opt = alloc.chosen[line.id]
        assignments.append(_assignment(line, opt, alloc.runner_ups.get(line.id)))

    gross = sum(line.amount_minor for line in alloc.lines)
    discounts = sum(alloc.chosen[line.id].discount_minor for line in alloc.lines)
    rewards_value = sum(alloc.chosen[line.id].points_value_minor for line in alloc.lines)
    forex_fees = sum(alloc.chosen[line.id].forex_fee_minor for line in alloc.lines)
    effective = gross - discounts - rewards_value + forex_fees
    cash_now = gross - discounts + forex_fees
    deferred = rewards_value
    savings = gross - effective
    pools_final = {key: alloc.pool_balances.get(key, 0) for key in alloc.pool_keys}

    confidences = [alloc.chosen[line.id].min_confidence for line in alloc.lines]
    confidence = min(confidences) if confidences else 1.0

    assumptions = _assumptions(assignments)

    return OptimizerResult(
        assignments=assignments,
        gross_minor=gross,
        discounts_minor=discounts,
        rewards_value_minor=rewards_value,
        forex_fees_minor=forex_fees,
        effective_cost_minor=effective,
        cash_outlay_now_minor=cash_now,
        deferred_value_minor=deferred,
        savings_pct_bp=savings_pct_bp(savings, gross),
        cap_pools_final=pools_final,
        assumptions=assumptions,
        confidence=confidence,
    )


def _assumptions(assignments: list[LineAssignment]) -> list[str]:
    out = [
        "Points valued at each card's best available redemption path (MVP: max valuation).",
        "Cap pools assume one statement cycle covers the booking window.",
        "Forex fee = markup x (1 + GST) applied only to POS-abroad lines; "
        "always choose local currency at POS (DCC out of scope).",
        "Annual fees are treated as sunk for owned cards and excluded from optimization.",
    ]
    paths = sorted({a.assumed_redemption.value for a in assignments})
    if paths:
        out.append("Assumed redemption paths in use: " + ", ".join(paths) + ".")
    return out
