"""OPT-4: Always-on counterfactuals, QUICKXPLAIN infeasibility cores, and XAIOR audit certificate.

Design & arithmetic invariants:
- Zero float arithmetic on money, points, rates, breakevens, deltas, or relaxations.
  All monetary amounts remain integer minor units; per-point valuations remain integer
  ``micro_major_per_point`` (``1 minor = 10_000 micro_major``).
- Bit-for-bit deterministic across repeated runs: stable sorted iterations, canonical
  JSON SHA-256 snapshot hashes, and CP-SAT pinned to ``num_search_workers=1`` and
  ``random_seed=1`` with an explicit ``max_time_in_seconds`` ceiling.
- ``int64`` overflow safety in CP-SAT: domain bounds are kept tightly bounded and validated
  below signed 64-bit limits without cross-multiplying ``minor * bp * micro_major``.
- ``core/`` isolation: imports only stdlib, ``pydantic``, ``ortools``, and ``core.*``.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction
from typing import Any, Literal

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field

from core.db import KnowledgeBase
from core.models import (
    Channel,
    CostedTrip,
    LineAssignment,
    OptimizationPrefs,
    OptimizerResult,
    Provenance,
    RedemptionPath,
    RewardRule,
    SpendCategory,
    SpendLineItem,
    TransferAdvice,
    UserWallet,
)
from core.optimizer.allocate import AllocationResult, Option, compute_option
from core.optimizer.offers import eligible_offers, offer_subsets
from core.optimizer.rules import POS_CHANNELS, pool_key
from core.transfer.arithmetic import BASIS_POINTS

MICRO_MAJOR_PER_MINOR = 10_000
MICRO_MAJOR_PER_MAJOR = 1_000_000
# Conservative int64 safe ceiling for individual CP-SAT variable/RHS bounds so
# multi-term sums stay well under 2^63 - 1 (~9.22e18).
CP_SAT_SAFE_INT64_BOUND = 1_000_000_000_000_000  # 10^15

DEFAULT_TRANSACTOR_APR_WARNING = (
    "Assumes full statement balance payoff by the due date (0% revolving APR). "
    "Carrying a revolving balance or paying interest charges typically exceeds card "
    "reward yields and invalidates net benefit calculations."
)

DEFAULT_ZERO_AFFILIATE_ATTESTATION = (
    "All card, channel, and transfer rankings are computed exclusively from deterministic "
    "card earn rules, verified offer terms, and the user's explicit optimization objective, "
    "with zero affiliate, commission, or popularity weights."
)


# --------------------------------------------------------------------------- #
# Formatting & Hashing Helpers (integer-only for money/rates)                 #
# --------------------------------------------------------------------------- #


def _format_minor(minor: int, currency: str) -> str:
    """Format minor units deterministically without floats."""
    sign = "-" if minor < 0 else ""
    abs_minor = abs(minor)
    major = abs_minor // 100
    frac = abs_minor % 100
    prefix = "₹" if currency == "INR" else f"{currency} "
    if frac == 0:
        return f"{sign}{prefix}{major:,}"
    return f"{sign}{prefix}{major:,}.{frac:02d}"


def _format_micro_rate(micro_major_per_pt: int, currency: str) -> str:
    """Format micro-major per-point valuation (10^6 = 1.00 major unit) without floats."""
    sign = "-" if micro_major_per_pt < 0 else ""
    abs_micro = abs(micro_major_per_pt)
    major = abs_micro // MICRO_MAJOR_PER_MAJOR
    rem = abs_micro % MICRO_MAJOR_PER_MAJOR
    frac_str = f"{rem:06d}".rstrip("0")
    if len(frac_str) < 2:
        frac_str = frac_str.ljust(2, "0")
    prefix = "₹" if currency == "INR" else f"{currency} "
    return f"{sign}{prefix}{major:,}.{frac_str}/pt"


def _sha256_canonical(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


# --------------------------------------------------------------------------- #
# Input Specifications (Milestones & Grouped Transfer Caps)                   #
# --------------------------------------------------------------------------- #


class SpendMilestoneSpec(BaseModel):
    """Spend milestone or annual fee waiver specification for counterfactual deltas."""

    id: str
    card_id: str
    description: str
    threshold_minor: int = Field(gt=0)
    prior_spend_minor: int = Field(default=0, ge=0)
    reward_kind: Literal["bonus_points", "fee_waiver"] = "fee_waiver"
    bonus_points: int = Field(default=0, ge=0)
    fee_waiver_minor: int = Field(default=0, ge=0)
    currency: str = "INR"
    eligible_categories: list[SpendCategory] | None = None
    excluded_categories: list[SpendCategory] = Field(default_factory=list)
    eligible_channels: list[Channel] | None = None
    period_type: Literal["annual", "quarterly", "monthly", "trip_window"] = "annual"
    provenance: Provenance | None = None


class TransferGroupCapSpec(BaseModel):
    """Grouped transfer cap across one or more partner transfer edges."""

    group_id: str
    description: str = ""
    source_currency: str
    edge_ids: list[str]
    max_source_units: int = Field(ge=0)
    used_source_units_prior: int = Field(default=0, ge=0)
    period: Literal["annual", "monthly", "cycle"] = "annual"


# --------------------------------------------------------------------------- #
# Always-On Explanation Models                                                #
# --------------------------------------------------------------------------- #


class CapPoolLedgerEntry(BaseModel):
    """Cap pool consumption and binding status for held-card earn rules."""

    pool_key: str
    card_id: str
    initial_points: int
    consumed_points: int
    remaining_points: int
    binding: bool
    affected_line_ids: list[str] = Field(default_factory=list)
    summary: str


class ExcludedRuleEntry(BaseModel):
    """Explains why an accelerated rule on a held card was excluded for a spend line."""

    rule_id: str
    card_id: str
    line_id: str
    reason: Literal[
        "excluded_category",
        "excluded_mcc",
        "mcc_unverified",
        "currency_mismatch",
        "channel_mismatch",
        "expired",
    ]
    detail: str
    summary: str


class GroupedTransferCapEntry(BaseModel):
    """Grouped transfer-cap usage and remaining headroom."""

    group_id: str
    source_currency: str
    max_source_units: int
    used_prior_units: int
    used_plan_units: int
    remaining_units: int
    over_limit_units: int
    binding: bool
    summary: str


class MilestoneSpendDelta(BaseModel):
    """Exact RHS spend delta required to unlock a milestone or fee waiver."""

    milestone_id: str
    card_id: str
    reward_kind: Literal["bonus_points", "fee_waiver"]
    threshold_minor: int
    prior_spend_minor: int
    trip_eligible_spend_minor: int
    total_eligible_spend_minor: int
    spend_delta_minor: int
    unlocked: bool
    currency: str
    summary: str


class ValuationBreakeven(BaseModel):
    """Forel-style single-shot relative valuation breakeven (chosen vs runner-up)."""

    line_id: str
    chosen_card_id: str
    chosen_channel: Channel
    chosen_points: int
    chosen_valuation_micro: int
    chosen_benefit_minor: int
    runner_card_id: str
    runner_channel: Channel
    runner_points: int
    runner_valuation_micro: int
    runner_benefit_minor: int
    runner_partner_label: str
    shared_currency: bool
    reachable: bool
    direction: Literal["above", "below", "unreachable"]
    breakeven_micro_major_per_point: int | None
    delta_vs_current_micro: int | None
    currency: str
    summary: str


class AlwaysOnExplanation(BaseModel):
    """Deterministic counterfactual & constraint ledger emitted with every plan."""

    cap_ledger: list[CapPoolLedgerEntry] = Field(default_factory=list)
    excluded_rules: list[ExcludedRuleEntry] = Field(default_factory=list)
    grouped_transfer_caps: list[GroupedTransferCapEntry] = Field(default_factory=list)
    milestone_deltas: list[MilestoneSpendDelta] = Field(default_factory=list)
    valuation_breakevens: list[ValuationBreakeven] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Infeasibility Core & QUICKXPLAIN Models                                     #
# --------------------------------------------------------------------------- #


ConstraintKind = Literal[
    "award_goal",
    "source_balance",
    "group_cap",
    "deadline",
    "max_transfers",
    "edge_min",
    "milestone_threshold",
    "card_cap",
    "budget_cap",
    "custom",
]


@dataclass(frozen=True)
class AssumedConstraintSpec:
    """Constraint attached to a CP-SAT assumption literal for QUICKXPLAIN refinement."""

    constraint_id: str
    kind: ConstraintKind
    description: str
    literal: Any  # cp_model.IntVar (bool)
    lhs_label: str = ""
    rhs_value: int | None = None
    unit: str = ""


class InfeasibleConstraint(BaseModel):
    """One member of a subset-minimal unsatisfiable core."""

    constraint_id: str
    kind: ConstraintKind
    description: str
    lhs_label: str = ""
    rhs_value: int | None = None
    unit: str = ""


class MinimalRelaxation(BaseModel):
    """Minimal RHS relaxation for a core constraint that restores feasibility."""

    constraint_id: str
    current_rhs: int
    relaxed_rhs: int
    delta: int
    direction: Literal["increase", "decrease"]
    unit: str
    summary: str


class InfeasibilityCoreResult(BaseModel):
    """Subset-minimal infeasibility explanation (QUICKXPLAIN) + minimal relaxations."""

    is_feasible: bool
    solver_backend: str
    solver_seed: int = 1
    num_workers: int = 1
    conflict_core: list[InfeasibleConstraint] = Field(default_factory=list)
    relaxations: list[MinimalRelaxation] = Field(default_factory=list)
    quickxplain_probes: int = 0
    summary: str


# --------------------------------------------------------------------------- #
# XAIOR Decision Audit Certificate Models                                     #
# --------------------------------------------------------------------------- #


class RuleProvenanceEntry(BaseModel):
    """Provenance record for a financial fact used or evaluated during planning."""

    kind: Literal[
        "card",
        "reward_rule",
        "offer",
        "point_valuation",
        "transfer_edge",
        "transfer_bonus",
        "award_chart",
        "spend_milestone",
        "fx_rate",
    ]
    entity_id: str
    source_url: str | None = None
    source_type: str
    last_verified: date
    verified_by: str
    needs_verification: bool
    confidence: float
    version_fingerprint: str


class SolverMetadata(BaseModel):
    """Deterministic solver configuration and optimality status."""

    backend: str
    seed: int
    num_workers: int
    optimality_status: Literal[
        "optimal",
        "feasible",
        "heuristic_bounded",
        "infeasible",
        "unknown",
    ]
    max_time_in_seconds: float | None = None


class RobustnessDisclosure(BaseModel):
    """Active uncertainty budget Gamma and guaranteed cash/portal recourse floors."""

    gamma: int = Field(default=0, ge=0)
    recourse_floors: dict[str, int] = Field(default_factory=dict)
    nominal_assumed_paths: dict[str, str] = Field(default_factory=dict)


class DecisionAuditCertificate(BaseModel):
    """Deterministic XAIOR Decision Audit Certificate (De Bock et al., EJOR 2024)."""

    certificate_version: Literal["xaior-v1"] = "xaior-v1"
    catalog_snapshot_hash: str
    trip_snapshot_hash: str
    result_hash: str
    rule_provenance: list[RuleProvenanceEntry] = Field(default_factory=list)
    any_needs_verification: bool
    min_confidence: float
    earliest_last_verified: date | None = None
    solver: SolverMetadata
    robustness: RobustnessDisclosure
    transactor_apr_warning: str = DEFAULT_TRANSACTOR_APR_WARNING
    revolver_apr_excluded: Literal[True] = True
    zero_affiliate_weight: Literal[True] = True
    zero_paid_promotion: Literal[True] = True
    zero_affiliate_attestation: str = DEFAULT_ZERO_AFFILIATE_ATTESTATION


class ExplainAndAuditBundle(BaseModel):
    """Combined always-on counterfactuals and XAIOR audit certificate."""

    explanations: AlwaysOnExplanation
    audit_certificate: DecisionAuditCertificate


# --------------------------------------------------------------------------- #
# Always-On Explanations: Ledger, Deltas & Forel Valuation Breakevens         #
# --------------------------------------------------------------------------- #


def _build_cap_ledger(
    wallet: UserWallet, kb: KnowledgeBase, result: OptimizerResult
) -> list[CapPoolLedgerEntry]:
    pool_meta: dict[str, tuple[str, int]] = {}
    for card_id in sorted(set(wallet.card_ids)):
        if not kb.has_card(card_id):
            continue
        for rule in kb.rules_for_card(card_id):
            if rule.cap is None:
                continue
            key = pool_key(rule)
            assert key is not None
            prev = pool_meta.get(key)
            max_pts = rule.cap.max_points if prev is None else min(prev[1], rule.cap.max_points)
            pool_meta[key] = (card_id, max_pts)

    entries: list[CapPoolLedgerEntry] = []
    for key in sorted(pool_meta):
        card_id, initial_pts = pool_meta[key]
        remaining = result.cap_pools_final.get(key, initial_pts)
        consumed = max(0, initial_pts - remaining)
        affected_lines = sorted(
            {
                a.line.id
                for a in result.assignments
                if a.card_id == card_id
                and (
                    any(key in atom for atom in a.explanation)
                    or any(
                        pool_key(r) == key and a.line.category in r.categories
                        for r in kb.rules_for_card(card_id)
                    )
                )
            }
        )
        fallthrough = any(
            f"cap pool '{key}' exhausted" in atom
            for a in result.assignments
            for atom in a.explanation
        )
        binding = remaining == 0 or fallthrough
        status = "BINDING" if binding else "unconstrained"
        summary = (
            f"Cap pool {key}: {consumed:,}/{initial_pts:,} pts used, "
            f"{remaining:,} remaining ({status})"
        )
        entries.append(
            CapPoolLedgerEntry(
                pool_key=key,
                card_id=card_id,
                initial_points=initial_pts,
                consumed_points=consumed,
                remaining_points=remaining,
                binding=binding,
                affected_line_ids=affected_lines,
                summary=summary,
            )
        )
    return entries


def _rule_date_valid(rule: RewardRule, on_date: date) -> bool:
    if rule.valid_from is not None and on_date < rule.valid_from:
        return False
    if rule.valid_to is not None and on_date > rule.valid_to:
        return False
    return True


def _effective_line_date(trip: CostedTrip, line: SpendLineItem, chosen_channel: Channel) -> date:
    if chosen_channel in POS_CHANNELS:
        return trip.trip_start_date
    if line.available_channels and all(ch in POS_CHANNELS for ch in line.available_channels):
        return trip.trip_start_date
    return trip.booking_date


def _build_excluded_rules(
    trip: CostedTrip,
    wallet: UserWallet,
    kb: KnowledgeBase,
    result: OptimizerResult,
    line_mccs: dict[str, int] | None,
) -> list[ExcludedRuleEntry]:
    chosen_channel_by_line = {a.line.id: a.channel for a in result.assignments}
    entries: list[ExcludedRuleEntry] = []

    for line in sorted(trip.lines, key=lambda ln: ln.id):
        chosen_ch = chosen_channel_by_line.get(
            line.id,
            line.available_channels[0] if line.available_channels else Channel.POS_DOMESTIC,
        )
        on_date = _effective_line_date(trip, line, chosen_ch)
        line_mcc = line_mccs.get(line.id) if line_mccs is not None else None

        for card_id in sorted(set(wallet.card_ids)):
            if not kb.has_card(card_id):
                continue
            for rule in kb.rules_for_card(card_id):
                entry: ExcludedRuleEntry | None = None
                if line.category in rule.excluded_categories:
                    detail = f"category {line.category.value!r} in rule excluded_categories"
                    entry = ExcludedRuleEntry(
                        rule_id=rule.id,
                        card_id=card_id,
                        line_id=line.id,
                        reason="excluded_category",
                        detail=detail,
                        summary=f"Rule {rule.id} ({card_id}) excluded on {line.id}: {detail}.",
                    )
                elif (
                    rule.mcc_codes is not None
                    and line_mcc is not None
                    and line_mcc not in rule.mcc_codes
                ):
                    allowed = ", ".join(str(m) for m in sorted(rule.mcc_codes))
                    detail = f"MCC {line_mcc} not in allowed [{allowed}]"
                    entry = ExcludedRuleEntry(
                        rule_id=rule.id,
                        card_id=card_id,
                        line_id=line.id,
                        reason="excluded_mcc",
                        detail=detail,
                        summary=f"Rule {rule.id} ({card_id}) excluded on {line.id}: {detail}.",
                    )
                elif line.category in rule.categories:
                    if rule.mcc_codes is not None and line_mcc is None:
                        allowed = ", ".join(str(m) for m in sorted(rule.mcc_codes))
                        detail = f"requires MCC in [{allowed}] (line MCC not provided)"
                        entry = ExcludedRuleEntry(
                            rule_id=rule.id,
                            card_id=card_id,
                            line_id=line.id,
                            reason="mcc_unverified",
                            detail=detail,
                            summary=f"Rule {rule.id} ({card_id}) on {line.id}: {detail}.",
                        )
                    elif rule.currencies is not None and line.currency not in rule.currencies:
                        detail = f"currency {line.currency} not in {rule.currencies}"
                        entry = ExcludedRuleEntry(
                            rule_id=rule.id,
                            card_id=card_id,
                            line_id=line.id,
                            reason="currency_mismatch",
                            detail=detail,
                            summary=f"Rule {rule.id} ({card_id}) skipped on {line.id}: {detail}.",
                        )
                    elif rule.channels is not None and not any(
                        ch in rule.channels for ch in line.available_channels
                    ):
                        req = ", ".join(ch.value for ch in rule.channels)
                        detail = f"requires channel in [{req}]"
                        entry = ExcludedRuleEntry(
                            rule_id=rule.id,
                            card_id=card_id,
                            line_id=line.id,
                            reason="channel_mismatch",
                            detail=detail,
                            summary=f"Rule {rule.id} ({card_id}) skipped on {line.id}: {detail}.",
                        )
                    elif not _rule_date_valid(rule, on_date):
                        detail = f"outside rule validity window on {on_date.isoformat()}"
                        entry = ExcludedRuleEntry(
                            rule_id=rule.id,
                            card_id=card_id,
                            line_id=line.id,
                            reason="expired",
                            detail=detail,
                            summary=f"Rule {rule.id} ({card_id}) skipped on {line.id}: {detail}.",
                        )
                if entry is not None:
                    entries.append(entry)

    return entries


def _build_grouped_transfer_cap_ledger(
    kb: KnowledgeBase,
    transfer_advice: TransferAdvice | None,
    group_caps: Sequence[TransferGroupCapSpec],
) -> list[GroupedTransferCapEntry]:
    if not group_caps:
        return []

    source_ids = sorted({cap.source_currency for cap in group_caps})
    edges_by_pair: dict[tuple[str, str], set[str]] = {}
    for edge in kb.edges_from(source_ids):
        edges_by_pair.setdefault((edge.from_id, edge.to_id), set()).add(edge.id)

    target_plan = None
    if transfer_advice is not None and transfer_advice.plans:
        target_plan = next(
            (p for p in transfer_advice.plans if p.id == transfer_advice.recommendation.plan_id),
            transfer_advice.plans[0],
        )

    entries: list[GroupedTransferCapEntry] = []
    for cap in sorted(group_caps, key=lambda g: g.group_id):
        edge_set = set(cap.edge_ids)
        used_plan = 0
        if target_plan is not None:
            for step in target_plan.steps:
                if step.from_id != cap.source_currency:
                    continue
                if not edge_set:
                    used_plan += step.amount_source
                else:
                    pair_edges = edges_by_pair.get((step.from_id, step.to_id), set())
                    if pair_edges & edge_set:
                        used_plan += step.amount_source
        total_used = cap.used_source_units_prior + used_plan
        remaining = max(0, cap.max_source_units - total_used)
        over = max(0, total_used - cap.max_source_units)
        binding = remaining == 0 or over > 0
        status = "OVER_LIMIT" if over > 0 else ("BINDING" if binding else "available")
        summary = (
            f"Transfer group {cap.group_id} ({cap.source_currency}): "
            f"{total_used:,}/{cap.max_source_units:,} units used, "
            f"{remaining:,} remaining ({status})"
        )
        entries.append(
            GroupedTransferCapEntry(
                group_id=cap.group_id,
                source_currency=cap.source_currency,
                max_source_units=cap.max_source_units,
                used_prior_units=cap.used_source_units_prior,
                used_plan_units=used_plan,
                remaining_units=remaining,
                over_limit_units=over,
                binding=binding,
                summary=summary,
            )
        )
    return entries


def _assignment_net_spend_minor(assignment: LineAssignment) -> int:
    discount = sum(offer.discount_minor for offer in assignment.offers_applied)
    return max(0, assignment.line.amount_minor - discount)


def _line_matches_milestone(assignment: LineAssignment, m: SpendMilestoneSpec) -> bool:
    if assignment.card_id != m.card_id:
        return False
    cat = assignment.line.category
    if cat in m.excluded_categories:
        return False
    if m.eligible_categories is not None and cat not in m.eligible_categories:
        return False
    if m.eligible_channels is not None and assignment.channel not in m.eligible_channels:
        return False
    return True


def _build_milestone_deltas(
    result: OptimizerResult,
    milestones: Sequence[SpendMilestoneSpec],
) -> list[MilestoneSpendDelta]:
    deltas: list[MilestoneSpendDelta] = []
    for m in sorted(milestones, key=lambda item: (item.card_id, item.threshold_minor, item.id)):
        trip_spend = sum(
            _assignment_net_spend_minor(a)
            for a in result.assignments
            if _line_matches_milestone(a, m)
        )
        total_spend = m.prior_spend_minor + trip_spend
        gap = max(0, m.threshold_minor - total_spend)
        unlocked = gap == 0
        thresh_txt = _format_minor(m.threshold_minor, m.currency)
        if unlocked:
            summary = (
                f"{m.card_id}: {m.description} unlocked "
                f"({_format_minor(total_spend, m.currency)} >= {thresh_txt})."
            )
        elif m.reward_kind == "fee_waiver":
            summary = (
                f"{_format_minor(gap, m.currency)} more eligible spend on {m.card_id} "
                f"unlocks the {thresh_txt} fee waiver."
            )
        else:
            summary = (
                f"{_format_minor(gap, m.currency)} more eligible spend on {m.card_id} "
                f"unlocks +{m.bonus_points:,} bonus pts ({m.description})."
            )
        deltas.append(
            MilestoneSpendDelta(
                milestone_id=m.id,
                card_id=m.card_id,
                reward_kind=m.reward_kind,
                threshold_minor=m.threshold_minor,
                prior_spend_minor=m.prior_spend_minor,
                trip_eligible_spend_minor=trip_spend,
                total_eligible_spend_minor=total_spend,
                spend_delta_minor=gap,
                unlocked=unlocked,
                currency=m.currency,
                summary=summary,
            )
        )
    return deltas


def _reconstruct_runner_option(
    kb: KnowledgeBase,
    trip: CostedTrip,
    line: SpendLineItem,
    runner_card_id: str,
    runner_channel: Channel,
    runner_benefit_minor: int,
    cap_pools_final: dict[str, int],
) -> Option | None:
    if runner_card_id == "cash_only" or not kb.has_card(runner_card_id):
        return None
    card = kb.card(runner_card_id)
    on_date = trip.trip_start_date if runner_channel in POS_CHANNELS else trip.booking_date
    eligible = eligible_offers(kb, line, card, runner_channel, on_date)
    subsets = offer_subsets(eligible)
    for pools in ({}, cap_pools_final):
        for subset in subsets:
            opt = compute_option(kb, line, runner_card_id, runner_channel, subset, pools, on_date)
            if opt.benefit_minor == runner_benefit_minor:
                return opt
    if subsets:
        candidates = [
            compute_option(kb, line, runner_card_id, runner_channel, subset, {}, on_date)
            for subset in subsets
        ]
        return min(candidates, key=lambda o: abs(o.benefit_minor - runner_benefit_minor))
    return None


def _partner_label(kb: KnowledgeBase, card_id: str) -> str:
    val_obj = kb.best_valuation_obj(card_id)
    if val_obj is None:
        return "cashback"
    return val_obj.path.value


def _shared_currency_breakeven(
    pts_chosen: int,
    cash_net_chosen: int,
    pts_runner: int,
    cash_net_runner: int,
) -> tuple[bool, Literal["above", "below", "unreachable"], int | None]:
    """Find threshold V for shared valuation where runner strictly beats chosen."""
    if pts_runner > pts_chosen:
        cash_gap = cash_net_chosen - cash_net_runner
        if cash_gap < 0:
            return True, "above", 0
        diff_pts = pts_runner - pts_chosen
        # Proof: floor(pts_runner * V / D) - floor(pts_chosen * V / D) >= cash_gap + 1
        # holds whenever (pts_runner - pts_chosen) * V >= (cash_gap + 1) * D.
        v_bound = ((cash_gap + 1) * MICRO_MAJOR_PER_MINOR + diff_pts - 1) // diff_pts
        return True, "above", v_bound
    if pts_runner < pts_chosen and cash_net_runner > cash_net_chosen:
        # Runner has higher non-point cash gain; beats chosen only below valuation ceiling.
        cash_adv = cash_net_runner - cash_net_chosen
        diff_pts = pts_chosen - pts_runner
        # Need floor(pts_chosen * V / D) - floor(pts_runner * V / D) < cash_adv
        v_ceil = max(0, (cash_adv * MICRO_MAJOR_PER_MINOR - 1) // diff_pts)
        return True, "below", v_ceil
    return False, "unreachable", None


def _independent_breakeven(
    chosen_benefit_minor: int,
    runner_points: int,
    runner_cash_net_minor: int,
) -> tuple[bool, Literal["above", "below", "unreachable"], int | None]:
    """Exact Forel single-shot valuation breakeven holding chosen valuation fixed.

    Finds the smallest integer ``V >= 0`` (in micro-major per point) such that:
    ``runner_cash_net_minor + (runner_points * V) // 10_000 > chosen_benefit_minor``.
    """
    if runner_points <= 0:
        if runner_cash_net_minor > chosen_benefit_minor:
            return True, "above", 0
        return False, "unreachable", None
    required_pv = chosen_benefit_minor - runner_cash_net_minor
    if required_pv < 0:
        return True, "above", 0
    v_star = ((required_pv + 1) * MICRO_MAJOR_PER_MINOR + runner_points - 1) // runner_points
    return True, "above", v_star


def _build_valuation_breakevens(
    trip: CostedTrip,
    kb: KnowledgeBase,
    result: OptimizerResult,
    alloc: AllocationResult | None,
) -> list[ValuationBreakeven]:
    out: list[ValuationBreakeven] = []
    for a in sorted(result.assignments, key=lambda row: row.line.id):
        if a.runner_up is None:
            continue
        chosen_val = kb.best_valuation_obj(a.card_id) if kb.has_card(a.card_id) else None
        chosen_val_micro = chosen_val.value_micro_major_per_point if chosen_val is not None else 0
        chosen_discount = sum(o.discount_minor for o in a.offers_applied)
        chosen_cash_net = chosen_discount - a.forex_fee_minor

        runner_opt: Option | None = (
            alloc.runner_ups.get(a.line.id) if alloc is not None else None
        )
        if runner_opt is None:
            runner_opt = _reconstruct_runner_option(
                kb,
                trip,
                a.line,
                a.runner_up.card_id,
                a.runner_up.channel,
                a.runner_up.benefit_minor,
                result.cap_pools_final,
            )

        runner_val_obj = (
            kb.best_valuation_obj(a.runner_up.card_id)
            if kb.has_card(a.runner_up.card_id)
            else None
        )
        runner_val_micro = (
            runner_val_obj.value_micro_major_per_point if runner_val_obj is not None else 0
        )
        partner = _partner_label(kb, a.runner_up.card_id)

        if runner_opt is not None:
            runner_points = runner_opt.points
            runner_cash_net = runner_opt.discount_minor - runner_opt.forex_fee_minor
            runner_benefit = runner_opt.benefit_minor
        else:
            runner_points = 0
            runner_cash_net = a.runner_up.benefit_minor
            runner_benefit = a.runner_up.benefit_minor

        shared_currency = a.card_id == a.runner_up.card_id
        if shared_currency:
            reachable, direction, breakeven = _shared_currency_breakeven(
                a.points_earned, chosen_cash_net, runner_points, runner_cash_net
            )
        else:
            reachable, direction, breakeven = _independent_breakeven(
                a.benefit_minor, runner_points, runner_cash_net
            )

        delta_vs_current = (
            breakeven - runner_val_micro
            if breakeven is not None and direction == "above"
            else None
        )
        cur = trip.home_currency
        if not reachable or breakeven is None:
            summary = (
                f"{a.runner_up.card_id} ({a.runner_up.channel.value}) earns {runner_points} pts "
                f"and cannot overtake {a.card_id} on {a.line.id} via point valuation alone."
            )
        elif direction == "above":
            summary = (
                f"{a.runner_up.card_id} ({partner}) beats {a.card_id} on {a.line.id} only if "
                f"{a.runner_up.card_id} point value >= "
                f"{_format_micro_rate(breakeven, cur)} "
                f"(currently {_format_micro_rate(runner_val_micro, cur)})."
            )
        else:
            summary = (
                f"{a.runner_up.card_id} ({partner}) beats {a.card_id} on {a.line.id} only if "
                f"shared point value <= {_format_micro_rate(breakeven, cur)} "
                f"(currently {_format_micro_rate(runner_val_micro, cur)})."
            )

        out.append(
            ValuationBreakeven(
                line_id=a.line.id,
                chosen_card_id=a.card_id,
                chosen_channel=a.channel,
                chosen_points=a.points_earned,
                chosen_valuation_micro=chosen_val_micro,
                chosen_benefit_minor=a.benefit_minor,
                runner_card_id=a.runner_up.card_id,
                runner_channel=a.runner_up.channel,
                runner_points=runner_points,
                runner_valuation_micro=runner_val_micro,
                runner_benefit_minor=runner_benefit,
                runner_partner_label=partner,
                shared_currency=shared_currency,
                reachable=reachable,
                direction=direction,
                breakeven_micro_major_per_point=breakeven,
                delta_vs_current_micro=delta_vs_current,
                currency=cur,
                summary=summary,
            )
        )
    return out


def build_always_on_explanation(
    trip: CostedTrip,
    wallet: UserWallet,
    kb: KnowledgeBase,
    result: OptimizerResult,
    *,
    alloc: AllocationResult | None = None,
    transfer_advice: TransferAdvice | None = None,
    milestones: Sequence[SpendMilestoneSpec] = (),
    group_caps: Sequence[TransferGroupCapSpec] = (),
    line_mccs: dict[str, int] | None = None,
) -> AlwaysOnExplanation:
    """Build deterministic always-on counterfactuals and constraint ledgers (<15 ms)."""
    return AlwaysOnExplanation(
        cap_ledger=_build_cap_ledger(wallet, kb, result),
        excluded_rules=_build_excluded_rules(trip, wallet, kb, result, line_mccs),
        grouped_transfer_caps=_build_grouped_transfer_cap_ledger(kb, transfer_advice, group_caps),
        milestone_deltas=_build_milestone_deltas(result, milestones),
        valuation_breakevens=_build_valuation_breakevens(trip, kb, result, alloc),
    )


# --------------------------------------------------------------------------- #
# QUICKXPLAIN Minimal Infeasibility Cores (OR-Tools CP-SAT + Assumptions)     #
# --------------------------------------------------------------------------- #


def _new_deterministic_solver(max_time_in_seconds: float) -> Any:
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 1
    if max_time_in_seconds > 0:
        solver.parameters.max_time_in_seconds = max_time_in_seconds
    return solver


def quickxplain_cpsat(
    model: Any,
    constraints: Sequence[AssumedConstraintSpec],
    *,
    max_time_in_seconds: float = 5.0,
) -> tuple[bool, list[int], int]:
    """Junker (AAAI 2004) QUICKXPLAIN over a CP-SAT model with assumption literals.

    Returns ``(is_feasible, minimal_core_indices, probe_count)``.
    When the full constraint set is infeasible and background constraints alone are
    feasible, ``minimal_core_indices`` is a subset-minimal unsatisfiable set (MUS).
    """
    solver = _new_deterministic_solver(max_time_in_seconds)
    probes = 0

    def is_consistent(indices: Sequence[int]) -> bool:
        nonlocal probes
        probes += 1
        model.clear_assumptions()
        if indices:
            model.add_assumptions([constraints[i].literal for i in indices])
        status = solver.solve(model)
        return bool(status in (cp_model.OPTIMAL, cp_model.FEASIBLE))

    all_indices = list(range(len(constraints)))
    if is_consistent(all_indices):
        return True, [], probes

    if not is_consistent([]):
        # Background constraints themselves are unsatisfiable.
        return False, [], probes

    # If the candidate set is large, pre-filter using CP-SAT's deterministic
    # sufficient core before running exact QUICKXPLAIN minimization.
    candidates = all_indices
    if len(all_indices) > 24:
        is_consistent(all_indices)
        suff_idx_set = set(solver.sufficient_assumptions_for_infeasibility())
        filtered = [i for i in all_indices if constraints[i].literal.index in suff_idx_set]
        if filtered and not is_consistent(filtered):
            candidates = filtered

    def _qx(bg: list[int], cand: list[int], bg_expanded: bool) -> list[int]:
        if bg_expanded and not is_consistent(bg):
            return []
        if len(cand) == 1:
            return list(cand)
        mid = len(cand) // 2
        c1, c2 = cand[:mid], cand[mid:]
        delta2 = _qx(bg + c1, c2, len(c1) > 0)
        delta1 = _qx(bg + delta2, c1, len(delta2) > 0)
        return delta1 + delta2

    core = _qx([], candidates, False)
    return False, sorted(core), probes


def _validate_int64_bound(value: int, label: str) -> int:
    if value < 0 or value > CP_SAT_SAFE_INT64_BOUND:
        raise ValueError(
            f"{label}={value} exceeds int64-safe CP-SAT range [0, {CP_SAT_SAFE_INT64_BOUND}]"
        )
    return value


@dataclass(frozen=True)
class _PreparedEdge:
    edge_id: str
    from_id: str
    to_id: str
    eff_source_lot: int
    eff_dest_lot: int
    min_transfer: int
    max_hours: int


def _effective_edge_lots(
    edge_id: str,
    from_id: str,
    to_id: str,
    ratio_from: int,
    ratio_to: int,
    increment: int,
    min_transfer: int,
    max_hours: int,
    bonus_bp: int,
) -> _PreparedEdge:
    # Exact rational conversion p/q with bonus:
    # dest = src * ratio_to * (10000 + bonus) / (ratio_from * 10000).
    ratio = Fraction(ratio_from * BASIS_POINTS, ratio_to * (BASIS_POINTS + bonus_bp))
    p_e = ratio.numerator
    q_e = ratio.denominator
    eff_src = math.lcm(increment, p_e)
    eff_dst = (eff_src * q_e) // p_e
    return _PreparedEdge(
        edge_id=edge_id,
        from_id=from_id,
        to_id=to_id,
        eff_source_lot=eff_src,
        eff_dest_lot=eff_dst,
        min_transfer=min_transfer,
        max_hours=max_hours,
    )


def _init_transfer_cp_model(
    prepared: Sequence[_PreparedEdge],
    balances: dict[str, int],
    required_miles: int,
) -> tuple[Any, dict[str, Any], dict[str, Any], int]:
    """Initialize CP-SAT transfer flow variables and return ``(model, k_vars, z_vars, ub_flow)``."""
    m = cp_model.CpModel()
    raw_ub = max(required_miles * 20, sum(balances.values()) + required_miles * 10)
    ub_flow = min(CP_SAT_SAFE_INT64_BOUND, max(raw_ub, 10_000_000))
    k_vars: dict[str, Any] = {}
    z_vars: dict[str, Any] = {}
    for idx, pe in enumerate(prepared):
        max_k = max(1, ub_flow // pe.eff_source_lot)
        k = m.new_int_var(0, max_k, f"k_{idx}")
        z = m.new_bool_var(f"z_{idx}")
        m.add(k >= z)
        m.add(k <= max_k * z)
        k_vars[pe.edge_id] = k
        z_vars[pe.edge_id] = z
    return m, k_vars, z_vars, ub_flow


def _node_flow_exprs(
    prepared: Sequence[_PreparedEdge],
    k_vars: dict[str, Any],
    node: str,
) -> tuple[Any, Any]:
    outflow = sum(pe.eff_source_lot * k_vars[pe.edge_id] for pe in prepared if pe.from_id == node)
    inflow = sum(pe.eff_dest_lot * k_vars[pe.edge_id] for pe in prepared if pe.to_id == node)
    return outflow, inflow


def _solve_transfer_relaxation_slack(
    *,
    relax_target_id: str,
    active_ids: set[str],
    nodes: list[str],
    prepared: list[_PreparedEdge],
    balances: dict[str, int],
    target_program_id: str,
    required_miles: int,
    max_transfer_hours: int | None,
    max_transfers: int | None,
    group_caps: Sequence[TransferGroupCapSpec],
    max_time_in_seconds: float,
) -> MinimalRelaxation | None:
    """Solve for minimal discrete integer relaxation of one constraint in the core."""
    m, k_vars, z_vars, ub_flow = _init_transfer_cp_model(prepared, balances, required_miles)
    slack = m.new_int_var(0, ub_flow, "slack")

    # Apply constraints (excluding relax_target_id OR adding slack to relax_target_id)
    for node in nodes:
        cid = f"goal:{node}" if node == target_program_id else f"balance:{node}"
        bal = _validate_int64_bound(balances.get(node, 0), f"balance:{node}")
        outflow, inflow = _node_flow_exprs(prepared, k_vars, node)
        if node == target_program_id:
            if cid == relax_target_id:
                m.add(bal + inflow - outflow + slack >= required_miles)
            elif cid in active_ids:
                m.add(bal + inflow - outflow >= required_miles)
        else:
            if cid == relax_target_id:
                m.add(outflow - inflow <= bal + slack)
            elif cid in active_ids:
                m.add(outflow - inflow <= bal)

    for pe in prepared:
        cid = f"edge_min:{pe.edge_id}"
        if pe.min_transfer <= 0:
            continue
        if cid == relax_target_id:
            m.add(
                pe.eff_source_lot * k_vars[pe.edge_id] + slack
                >= pe.min_transfer * z_vars[pe.edge_id]
            )
        elif cid in active_ids:
            m.add(pe.eff_source_lot * k_vars[pe.edge_id] >= pe.min_transfer * z_vars[pe.edge_id])

    for cap in group_caps:
        cid = f"group_cap:{cap.group_id}"
        allowed = max(0, cap.max_source_units - cap.used_source_units_prior)
        edge_set = set(cap.edge_ids)
        grp_expr = sum(
            pe.eff_source_lot * k_vars[pe.edge_id]
            for pe in prepared
            if (pe.edge_id in edge_set if edge_set else pe.from_id == cap.source_currency)
        )
        if cid == relax_target_id:
            m.add(grp_expr <= allowed + slack)
        elif cid in active_ids:
            m.add(grp_expr <= allowed)

    if max_transfer_hours is not None:
        cid = f"deadline:{max_transfer_hours}"
        if cid == relax_target_id:
            for pe in prepared:
                m.add(pe.max_hours * z_vars[pe.edge_id] <= max_transfer_hours + slack)
        elif cid in active_ids:
            for pe in prepared:
                if pe.max_hours > max_transfer_hours:
                    m.add(z_vars[pe.edge_id] == 0)

    if max_transfers is not None:
        cid = f"max_transfers:{max_transfers}"
        total_z = sum(z_vars[pe.edge_id] for pe in prepared)
        if cid == relax_target_id:
            m.add(total_z <= max_transfers + slack)
        elif cid in active_ids:
            m.add(total_z <= max_transfers)

    m.minimize(slack)
    solver = _new_deterministic_solver(max_time_in_seconds)
    status = solver.solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    delta = int(solver.value(slack))
    if delta <= 0:
        return None

    if relax_target_id.startswith("goal:"):
        cur = required_miles
        new_rhs = max(0, cur - delta)
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="decrease",
            unit="points",
            summary=(
                f"Reduce {target_program_id} award target by {delta:,} miles "
                f"(to {new_rhs:,})."
            ),
        )
    if relax_target_id.startswith("balance:"):
        node = relax_target_id.split(":", 1)[1]
        cur = balances.get(node, 0)
        new_rhs = cur + delta
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="increase",
            unit="points",
            summary=f"Increase {node} balance by {delta:,} points (to {new_rhs:,}).",
        )
    if relax_target_id.startswith("group_cap:"):
        gid = relax_target_id.split(":", 1)[1]
        cap_obj = next(c for c in group_caps if c.group_id == gid)
        cur = cap_obj.max_source_units
        new_rhs = cur + delta
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="increase",
            unit="points",
            summary=f"Increase transfer group cap {gid} by {delta:,} points (to {new_rhs:,}).",
        )
    if relax_target_id.startswith("deadline:") and max_transfer_hours is not None:
        cur = max_transfer_hours
        new_rhs = cur + delta
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="increase",
            unit="hours",
            summary=f"Extend booking deadline by {delta:,} hours (to {new_rhs:,}h).",
        )
    if relax_target_id.startswith("max_transfers:") and max_transfers is not None:
        cur = max_transfers
        new_rhs = cur + delta
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="increase",
            unit="transfers",
            summary=f"Allow {delta} more transfer(s) (max {new_rhs}).",
        )
    return None


def explain_transfer_infeasibility(
    target_program_id: str,
    required_miles: int,
    wallet: UserWallet,
    kb: KnowledgeBase,
    *,
    on_date: date,
    max_transfer_hours: int | None = None,
    max_transfers: int | None = None,
    group_caps: Sequence[TransferGroupCapSpec] = (),
    max_time_in_seconds: float = 5.0,
) -> InfeasibilityCoreResult:
    """Diagnose why a transfer target is infeasible using CP-SAT + QUICKXPLAIN.

    Models exact rational transfer lots, node flow conservation, balances, grouped
    transfer caps, per-edge minimums, booking deadline, and max transfer count.
    """
    _validate_int64_bound(required_miles, "required_miles")
    # Collect all transfer edges from KB programs/balances.
    all_program_ids = [p.id for p in kb.programs()]
    raw_edges = kb.edges_from(all_program_ids)
    edge_ids = [e.id for e in raw_edges]
    active_bonuses = kb.bonuses_active(edge_ids, on_date)
    best_bonus_by_edge: dict[str, int] = {}
    for b in sorted(active_bonuses, key=lambda row: (-row.bonus_bp, row.id)):
        best_bonus_by_edge.setdefault(b.edge_id, b.bonus_bp)

    prepared = [
        _effective_edge_lots(
            edge_id=e.id,
            from_id=e.from_id,
            to_id=e.to_id,
            ratio_from=e.ratio_from,
            ratio_to=e.ratio_to,
            increment=e.increment,
            min_transfer=e.min_transfer,
            max_hours=e.transfer_time_hours_max,
            bonus_bp=best_bonus_by_edge.get(e.id, 0),
        )
        for e in sorted(raw_edges, key=lambda edge: edge.id)
    ]
    nodes = sorted(
        {target_program_id, *wallet.points_balances.keys()}
        | {pe.from_id for pe in prepared}
        | {pe.to_id for pe in prepared}
    )

    m, k_vars, z_vars, _ = _init_transfer_cp_model(
        prepared, wallet.points_balances, required_miles
    )
    specs: list[AssumedConstraintSpec] = []

    # 1. Target award goal constraint
    goal_lit = m.new_bool_var("assume_goal")
    target_bal = _validate_int64_bound(
        wallet.points_balances.get(target_program_id, 0), f"balance:{target_program_id}"
    )
    t_outflow, t_inflow = _node_flow_exprs(prepared, k_vars, target_program_id)
    m.add(target_bal + t_inflow - t_outflow >= required_miles).only_enforce_if(goal_lit)
    specs.append(
        AssumedConstraintSpec(
            constraint_id=f"goal:{target_program_id}",
            kind="award_goal",
            description=f"Reach {required_miles:,} miles in {target_program_id}",
            literal=goal_lit,
            lhs_label=target_program_id,
            rhs_value=required_miles,
            unit="points",
        )
    )

    # 2. Source balance limits
    for node in nodes:
        if node == target_program_id:
            continue
        bal = _validate_int64_bound(wallet.points_balances.get(node, 0), f"balance:{node}")
        lit = m.new_bool_var(f"assume_bal_{node}")
        n_outflow, n_inflow = _node_flow_exprs(prepared, k_vars, node)
        m.add(n_outflow - n_inflow <= bal).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"balance:{node}",
                kind="source_balance",
                description=f"{node} available balance cap ({bal:,} pts)",
                literal=lit,
                lhs_label=node,
                rhs_value=bal,
                unit="points",
            )
        )

    # 3. Grouped transfer caps
    for cap in sorted(group_caps, key=lambda g: g.group_id):
        allowed = _validate_int64_bound(
            max(0, cap.max_source_units - cap.used_source_units_prior),
            f"group_cap:{cap.group_id}",
        )
        lit = m.new_bool_var(f"assume_gcap_{cap.group_id}")
        edge_set = set(cap.edge_ids)
        grp_expr = sum(
            pe.eff_source_lot * k_vars[pe.edge_id]
            for pe in prepared
            if (pe.edge_id in edge_set if edge_set else pe.from_id == cap.source_currency)
        )
        m.add(grp_expr <= allowed).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"group_cap:{cap.group_id}",
                kind="group_cap",
                description=(
                    f"Group cap {cap.group_id} ({cap.source_currency}): "
                    f"max {cap.max_source_units:,} pts "
                    f"({allowed:,} remaining)"
                ),
                literal=lit,
                lhs_label=cap.group_id,
                rhs_value=cap.max_source_units,
                unit="points",
            )
        )

    # 4. Deadline filter
    if max_transfer_hours is not None:
        lit = m.new_bool_var("assume_deadline")
        for pe in prepared:
            if pe.max_hours > max_transfer_hours:
                m.add(z_vars[pe.edge_id] == 0).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"deadline:{max_transfer_hours}",
                kind="deadline",
                description=f"Transfer settlement within {max_transfer_hours}h booking deadline",
                literal=lit,
                lhs_label="transfer_time_hours_max",
                rhs_value=max_transfer_hours,
                unit="hours",
            )
        )

    # 5. Cardinality limit
    if max_transfers is not None:
        lit = m.new_bool_var("assume_max_transfers")
        m.add(sum(z_vars[pe.edge_id] for pe in prepared) <= max_transfers).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"max_transfers:{max_transfers}",
                kind="max_transfers",
                description=f"At most {max_transfers} transfer step(s)",
                literal=lit,
                lhs_label="transfer_count",
                rhs_value=max_transfers,
                unit="transfers",
            )
        )

    # 6. Minimum transfer thresholds per edge
    for pe in prepared:
        if pe.min_transfer <= 0:
            continue
        lit = m.new_bool_var(f"assume_emin_{pe.edge_id}")
        m.add(
            pe.eff_source_lot * k_vars[pe.edge_id] >= pe.min_transfer * z_vars[pe.edge_id]
        ).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"edge_min:{pe.edge_id}",
                kind="edge_min",
                description=(
                    f"Minimum transfer {pe.min_transfer:,} pts on edge {pe.edge_id} "
                    f"({pe.from_id}->{pe.to_id})"
                ),
                literal=lit,
                lhs_label=pe.edge_id,
                rhs_value=pe.min_transfer,
                unit="points",
            )
        )

    is_feasible, core_indices, probes = quickxplain_cpsat(
        m, specs, max_time_in_seconds=max_time_in_seconds
    )
    if is_feasible:
        return InfeasibilityCoreResult(
            is_feasible=True,
            solver_backend="ortools_cp_sat",
            conflict_core=[],
            relaxations=[],
            quickxplain_probes=probes,
            summary=f"Target {required_miles:,} miles in {target_program_id} is feasible.",
        )

    core_specs = [specs[i] for i in core_indices]
    core_models = [
        InfeasibleConstraint(
            constraint_id=s.constraint_id,
            kind=s.kind,
            description=s.description,
            lhs_label=s.lhs_label,
            rhs_value=s.rhs_value,
            unit=s.unit,
        )
        for s in core_specs
    ]

    all_cids = {s.constraint_id for s in specs}
    relaxations: list[MinimalRelaxation] = []
    for s in core_specs:
        rel = _solve_transfer_relaxation_slack(
            relax_target_id=s.constraint_id,
            active_ids=all_cids,
            nodes=nodes,
            prepared=prepared,
            balances=wallet.points_balances,
            target_program_id=target_program_id,
            required_miles=required_miles,
            max_transfer_hours=max_transfer_hours,
            max_transfers=max_transfers,
            group_caps=group_caps,
            max_time_in_seconds=max_time_in_seconds,
        )
        if rel is None:
            # If relaxing over all_cids hits a secondary disjoint conflict, solve relative to core.
            rel = _solve_transfer_relaxation_slack(
                relax_target_id=s.constraint_id,
                active_ids={c.constraint_id for c in core_specs},
                nodes=nodes,
                prepared=prepared,
                balances=wallet.points_balances,
                target_program_id=target_program_id,
                required_miles=required_miles,
                max_transfer_hours=max_transfer_hours,
                max_transfers=max_transfers,
                group_caps=group_caps,
                max_time_in_seconds=max_time_in_seconds,
            )
        if rel is not None:
            relaxations.append(rel)

    core_names = ", ".join(c.constraint_id for c in core_models)
    return InfeasibilityCoreResult(
        is_feasible=False,
        solver_backend="ortools_cp_sat",
        conflict_core=core_models,
        relaxations=relaxations,
        quickxplain_probes=probes,
        summary=f"Infeasible transfer target ({required_miles:,} {target_program_id}); "
        f"minimal core: [{core_names}].",
    )


def _line_eligible_for_milestone(line: SpendLineItem, m: SpendMilestoneSpec) -> bool:
    if line.category in m.excluded_categories:
        return False
    if m.eligible_categories is not None and line.category not in m.eligible_categories:
        return False
    if m.eligible_channels is not None and not any(
        ch in m.eligible_channels for ch in line.available_channels
    ):
        return False
    return True


def _init_milestone_cp_model(
    lines: Sequence[SpendLineItem], card_ids: Sequence[str]
) -> tuple[Any, dict[tuple[str, str], Any]]:
    """Initialize CP-SAT card/line spend assignment variables."""
    m = cp_model.CpModel()
    spend_vars: dict[tuple[str, str], Any] = {}
    for ln in lines:
        _validate_int64_bound(ln.amount_minor, f"line:{ln.id}")
        line_exprs: list[Any] = []
        for cid in card_ids:
            if not ln.splittable:
                x = m.new_bool_var(f"x_{cid}_{ln.id}")
                spend_vars[(cid, ln.id)] = ln.amount_minor * x
                line_exprs.append(x)
            else:
                s = m.new_int_var(0, ln.amount_minor, f"s_{cid}_{ln.id}")
                spend_vars[(cid, ln.id)] = s
                line_exprs.append(s)
        if line_exprs:
            if not ln.splittable:
                m.add(sum(line_exprs) <= 1)
            else:
                m.add(sum(line_exprs) <= ln.amount_minor)
    return m, spend_vars


def _solve_milestone_relaxation_slack(
    *,
    relax_target_id: str,
    active_ids: set[str],
    lines: list[SpendLineItem],
    card_ids: list[str],
    milestones: Sequence[SpendMilestoneSpec],
    total_budget_cap_minor: int | None,
    card_spend_caps_minor: dict[str, int],
    max_time_in_seconds: float,
) -> MinimalRelaxation | None:
    m, spend_vars = _init_milestone_cp_model(lines, card_ids)
    max_amt = sum(ln.amount_minor for ln in lines)
    max_thresh = max((ms.threshold_minor for ms in milestones), default=0)
    ub = min(CP_SAT_SAFE_INT64_BOUND, max(max_amt * 2, max_thresh * 2, 1_000_000))

    slack = m.new_int_var(0, ub, "slack")

    for ms in milestones:
        ms_id = f"milestone:{ms.card_id}:{ms.id}"
        elig_expr = sum(
            spend_vars[(ms.card_id, ln.id)]
            for ln in lines
            if _line_eligible_for_milestone(ln, ms) and (ms.card_id, ln.id) in spend_vars
        )
        if ms_id == relax_target_id:
            m.add(ms.prior_spend_minor + elig_expr + slack >= ms.threshold_minor)
        elif ms_id in active_ids:
            m.add(ms.prior_spend_minor + elig_expr >= ms.threshold_minor)

    for cid, cap_val in sorted(card_spend_caps_minor.items()):
        cap_id = f"card_cap:{cid}"
        c_expr = sum(spend_vars[(cid, ln.id)] for ln in lines if (cid, ln.id) in spend_vars)
        if cap_id == relax_target_id:
            m.add(c_expr <= cap_val + slack)
        elif cap_id in active_ids:
            m.add(c_expr <= cap_val)

    if total_budget_cap_minor is not None:
        b_id = "budget_cap:trip"
        tot_expr = sum(spend_vars.values())
        if b_id == relax_target_id:
            m.add(tot_expr <= total_budget_cap_minor + slack)
        elif b_id in active_ids:
            m.add(tot_expr <= total_budget_cap_minor)

    m.minimize(slack)
    solver = _new_deterministic_solver(max_time_in_seconds)
    status = solver.solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    delta = int(solver.value(slack))
    if delta <= 0:
        return None

    if relax_target_id.startswith("milestone:"):
        ms_obj = next(
            ms for ms in milestones if f"milestone:{ms.card_id}:{ms.id}" == relax_target_id
        )
        cur = ms_obj.threshold_minor
        new_rhs = max(0, cur - delta)
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="decrease",
            unit="minor",
            summary=(
                f"Reduce milestone {ms_obj.id} threshold by "
                f"{_format_minor(delta, ms_obj.currency)} "
                f"(or add {_format_minor(delta, ms_obj.currency)} prior/trip spend)."
            ),
        )
    if relax_target_id.startswith("card_cap:"):
        cid = relax_target_id.split(":", 1)[1]
        cur = card_spend_caps_minor[cid]
        new_rhs = cur + delta
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="increase",
            unit="minor",
            summary=f"Increase {cid} spend cap by {_format_minor(delta, 'INR')}.",
        )
    if relax_target_id == "budget_cap:trip" and total_budget_cap_minor is not None:
        cur = total_budget_cap_minor
        new_rhs = cur + delta
        return MinimalRelaxation(
            constraint_id=relax_target_id,
            current_rhs=cur,
            relaxed_rhs=new_rhs,
            delta=delta,
            direction="increase",
            unit="minor",
            summary=f"Increase total spend budget cap by {_format_minor(delta, 'INR')}.",
        )
    return None


def explain_milestone_infeasibility(
    trip: CostedTrip,
    wallet: UserWallet,
    kb: KnowledgeBase,
    milestones: Sequence[SpendMilestoneSpec],
    *,
    total_budget_cap_minor: int | None = None,
    card_spend_caps_minor: dict[str, int] | None = None,
    max_time_in_seconds: float = 5.0,
) -> InfeasibilityCoreResult:
    """Diagnose conflicting card spend milestones, card caps, and trip budget limits."""
    lines = sorted(trip.lines, key=lambda ln: ln.id)
    card_ids = sorted({cid for cid in wallet.card_ids if kb.has_card(cid)})
    caps = dict(card_spend_caps_minor or {})

    m, spend_vars = _init_milestone_cp_model(lines, card_ids)

    specs: list[AssumedConstraintSpec] = []
    for ms in sorted(milestones, key=lambda item: (item.card_id, item.id)):
        _validate_int64_bound(ms.threshold_minor, f"milestone:{ms.id}")
        _validate_int64_bound(ms.prior_spend_minor, f"milestone_prior:{ms.id}")
        lit = m.new_bool_var(f"assume_ms_{ms.card_id}_{ms.id}")
        elig_expr = sum(
            spend_vars[(ms.card_id, ln.id)]
            for ln in lines
            if _line_eligible_for_milestone(ln, ms) and (ms.card_id, ln.id) in spend_vars
        )
        m.add(ms.prior_spend_minor + elig_expr >= ms.threshold_minor).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"milestone:{ms.card_id}:{ms.id}",
                kind="milestone_threshold",
                description=(
                    f"{ms.card_id} milestone {ms.id}: need "
                    f"{_format_minor(ms.threshold_minor, ms.currency)}"
                ),
                literal=lit,
                lhs_label=ms.card_id,
                rhs_value=ms.threshold_minor,
                unit="minor",
            )
        )

    for cid in sorted(caps):
        cap_val = _validate_int64_bound(caps[cid], f"card_cap:{cid}")
        lit = m.new_bool_var(f"assume_ccap_{cid}")
        c_expr = sum(spend_vars[(cid, ln.id)] for ln in lines if (cid, ln.id) in spend_vars)
        m.add(c_expr <= cap_val).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id=f"card_cap:{cid}",
                kind="card_cap",
                description=f"{cid} max spend limit ({_format_minor(cap_val, trip.home_currency)})",
                literal=lit,
                lhs_label=cid,
                rhs_value=cap_val,
                unit="minor",
            )
        )

    if total_budget_cap_minor is not None:
        _validate_int64_bound(total_budget_cap_minor, "total_budget_cap_minor")
        lit = m.new_bool_var("assume_total_budget")
        m.add(sum(spend_vars.values()) <= total_budget_cap_minor).only_enforce_if(lit)
        specs.append(
            AssumedConstraintSpec(
                constraint_id="budget_cap:trip",
                kind="budget_cap",
                description=(
                    f"Trip spend budget ceiling "
                    f"({_format_minor(total_budget_cap_minor, trip.home_currency)})"
                ),
                literal=lit,
                lhs_label="trip_total",
                rhs_value=total_budget_cap_minor,
                unit="minor",
            )
        )

    is_feasible, core_indices, probes = quickxplain_cpsat(
        m, specs, max_time_in_seconds=max_time_in_seconds
    )
    if is_feasible:
        return InfeasibilityCoreResult(
            is_feasible=True,
            solver_backend="ortools_cp_sat",
            conflict_core=[],
            relaxations=[],
            quickxplain_probes=probes,
            summary="All spend milestones and caps are jointly feasible.",
        )

    core_specs = [specs[i] for i in core_indices]
    core_models = [
        InfeasibleConstraint(
            constraint_id=s.constraint_id,
            kind=s.kind,
            description=s.description,
            lhs_label=s.lhs_label,
            rhs_value=s.rhs_value,
            unit=s.unit,
        )
        for s in core_specs
    ]

    all_cids = {spec.constraint_id for spec in specs}
    relaxations: list[MinimalRelaxation] = []
    for spec in core_specs:
        rel = _solve_milestone_relaxation_slack(
            relax_target_id=spec.constraint_id,
            active_ids=all_cids,
            lines=lines,
            card_ids=card_ids,
            milestones=milestones,
            total_budget_cap_minor=total_budget_cap_minor,
            card_spend_caps_minor=caps,
            max_time_in_seconds=max_time_in_seconds,
        )
        if rel is None:
            rel = _solve_milestone_relaxation_slack(
                relax_target_id=spec.constraint_id,
                active_ids={c.constraint_id for c in core_specs},
                lines=lines,
                card_ids=card_ids,
                milestones=milestones,
                total_budget_cap_minor=total_budget_cap_minor,
                card_spend_caps_minor=caps,
                max_time_in_seconds=max_time_in_seconds,
            )
        if rel is not None:
            relaxations.append(rel)

    core_names = ", ".join(c.constraint_id for c in core_models)
    return InfeasibilityCoreResult(
        is_feasible=False,
        solver_backend="ortools_cp_sat",
        conflict_core=core_models,
        relaxations=relaxations,
        quickxplain_probes=probes,
        summary=f"Infeasible milestone goal; minimal conflict core: [{core_names}].",
    )


# --------------------------------------------------------------------------- #
# XAIOR Decision Audit Certificate                                            #
# --------------------------------------------------------------------------- #


def build_catalog_snapshot_hash(
    kb: KnowledgeBase,
    *,
    milestones: Sequence[SpendMilestoneSpec] = (),
    group_caps: Sequence[TransferGroupCapSpec] = (),
) -> str:
    """Compute canonical SHA-256 hash of all financial KB entities & policies."""
    cards = sorted(kb.cards(), key=lambda c: c.id)
    card_ids = [c.id for c in cards]
    rules = sorted(kb.rules_for_cards(card_ids), key=lambda r: r.id)
    valuations = sorted(
        [v for cid in card_ids for v in kb.valuations_for_card(cid)],
        key=lambda v: v.id,
    )
    programs = kb.programs()
    edges = kb.edges_from([p.id for p in programs])
    snapshot = {
        "cards": [c.model_dump(mode="json") for c in cards],
        "rules": [r.model_dump(mode="json") for r in rules],
        "valuations": [v.model_dump(mode="json") for v in valuations],
        "programs": [p.model_dump(mode="json") for p in programs],
        "edges": [e.model_dump(mode="json") for e in edges],
        "milestones": [
            m.model_dump(mode="json") for m in sorted(milestones, key=lambda x: x.id)
        ],
        "group_caps": [
            g.model_dump(mode="json") for g in sorted(group_caps, key=lambda x: x.group_id)
        ],
    }
    return _sha256_canonical(snapshot)


def _recourse_floor_micro(kb: KnowledgeBase, card_id: str) -> int:
    """Guaranteed floor valuation (prefer cashback, else lowest established valuation)."""
    vals = kb.valuations_for_card(card_id)
    if not vals:
        return 0
    cashback = [v.value_micro_major_per_point for v in vals if v.path == RedemptionPath.CASHBACK]
    if cashback:
        return min(cashback)
    portal = [
        v.value_micro_major_per_point
        for v in vals
        if v.path in (RedemptionPath.PORTAL_FLIGHTS, RedemptionPath.PORTAL_HOTELS)
    ]
    if portal:
        return min(portal)
    return min(v.value_micro_major_per_point for v in vals)


ProvenanceEntityKind = Literal[
    "card",
    "reward_rule",
    "offer",
    "point_valuation",
    "transfer_edge",
    "transfer_bonus",
    "award_chart",
    "spend_milestone",
    "fx_rate",
]


def _collect_rule_provenance(
    wallet: UserWallet,
    kb: KnowledgeBase,
    result: OptimizerResult,
    transfer_advice: TransferAdvice | None,
    milestones: Sequence[SpendMilestoneSpec],
    on_date: date,
) -> list[RuleProvenanceEntry]:
    seen: dict[tuple[ProvenanceEntityKind, str], tuple[Provenance, Any]] = {}

    for a in result.assignments:
        if a.card_id != "cash_only" and kb.has_card(a.card_id):
            card = kb.card(a.card_id)
            seen.setdefault(("card", card.id), (card.provenance, card))
            val_obj = kb.best_valuation_obj(a.card_id)
            if val_obj is not None:
                seen.setdefault(("point_valuation", val_obj.id), (val_obj.provenance, val_obj))
            for r in kb.rules_for_card(a.card_id):
                if a.line.category in r.categories or any(r.id in atom for atom in a.explanation):
                    seen.setdefault(("reward_rule", r.id), (r.provenance, r))
            for app in a.offers_applied:
                matched = kb.offers_matching(
                    a.line.merchant_hint, a.channel, a.line.category, on_date
                )
                for off in matched:
                    if off.id == app.offer_id:
                        seen.setdefault(("offer", off.id), (off.provenance, off))

    if transfer_advice is not None:
        all_edges = {e.id: e for e in kb.edges_from([p.id for p in kb.programs()])}
        for plan in transfer_advice.plans:
            seen.setdefault(("award_chart", plan.award.id), (plan.award.provenance, plan.award))
            for step in plan.steps:
                for eid, e in all_edges.items():
                    if e.from_id == step.from_id and e.to_id == step.to_id:
                        seen.setdefault(("transfer_edge", eid), (e.provenance, e))
                if step.bonus_applied is not None:
                    for b in kb.bonuses_active(list(all_edges), on_date):
                        if b.id == step.bonus_applied:
                            seen.setdefault(("transfer_bonus", b.id), (b.provenance, b))

    for ms in milestones:
        if ms.provenance is not None and (ms.card_id in wallet.card_ids):
            seen.setdefault(("spend_milestone", ms.id), (ms.provenance, ms))

    entries: list[RuleProvenanceEntry] = []
    for (kind, entity_id), (prov, obj) in sorted(seen.items()):
        entries.append(
            RuleProvenanceEntry(
                kind=kind,
                entity_id=entity_id,
                source_url=prov.source_url,
                source_type=prov.source_type,
                last_verified=prov.last_verified,
                verified_by=prov.verified_by,
                needs_verification=prov.needs_verification,
                confidence=prov.confidence,
                version_fingerprint=_sha256_canonical(obj.model_dump(mode="json"))[:16],
            )
        )
    return entries


def build_audit_certificate(
    trip: CostedTrip,
    wallet: UserWallet,
    kb: KnowledgeBase,
    result: OptimizerResult,
    *,
    prefs: OptimizationPrefs | None = None,
    transfer_advice: TransferAdvice | None = None,
    milestones: Sequence[SpendMilestoneSpec] = (),
    group_caps: Sequence[TransferGroupCapSpec] = (),
    solver_backend: str = "greedy_sweep_v1",
    solver_seed: int = 1,
    num_workers: int = 1,
    optimality_status: Literal[
        "optimal", "feasible", "heuristic_bounded", "infeasible", "unknown"
    ] = "heuristic_bounded",
    gamma: int = 0,
    max_time_in_seconds: float | None = None,
) -> DecisionAuditCertificate:
    """Assemble the deterministic XAIOR Decision Audit Certificate."""
    resolved_prefs = prefs or OptimizationPrefs()
    catalog_hash = build_catalog_snapshot_hash(kb, milestones=milestones, group_caps=group_caps)
    trip_hash = _sha256_canonical(
        {
            "trip": trip.model_dump(mode="json"),
            "wallet": wallet.model_dump(mode="json"),
            "prefs": resolved_prefs.model_dump(mode="json"),
        }
    )
    result_hash = _sha256_canonical(result.model_dump(mode="json"))

    prov_entries = _collect_rule_provenance(
        wallet, kb, result, transfer_advice, milestones, trip.booking_date
    )
    any_needs_verif = any(e.needs_verification for e in prov_entries)
    min_conf = min((e.confidence for e in prov_entries), default=result.confidence)
    earliest_verif = min((e.last_verified for e in prov_entries), default=None)

    recourse_floors: dict[str, int] = {}
    nominal_paths: dict[str, str] = {}
    for cid in sorted(set(wallet.card_ids)):
        if not kb.has_card(cid):
            continue
        recourse_floors[cid] = _recourse_floor_micro(kb, cid)
        best_val = kb.best_valuation_obj(cid)
        if best_val is not None:
            nominal_paths[cid] = best_val.path.value

    return DecisionAuditCertificate(
        catalog_snapshot_hash=catalog_hash,
        trip_snapshot_hash=trip_hash,
        result_hash=result_hash,
        rule_provenance=prov_entries,
        any_needs_verification=any_needs_verif,
        min_confidence=min_conf,
        earliest_last_verified=earliest_verif,
        solver=SolverMetadata(
            backend=solver_backend,
            seed=solver_seed,
            num_workers=num_workers,
            optimality_status=optimality_status,
            max_time_in_seconds=max_time_in_seconds,
        ),
        robustness=RobustnessDisclosure(
            gamma=gamma,
            recourse_floors=recourse_floors,
            nominal_assumed_paths=nominal_paths,
        ),
        zero_affiliate_attestation=(
            f"{DEFAULT_ZERO_AFFILIATE_ATTESTATION} Active objective: {resolved_prefs.objective}."
        ),
    )


def build_plan_explain_and_audit(
    trip: CostedTrip,
    wallet: UserWallet,
    kb: KnowledgeBase,
    result: OptimizerResult,
    *,
    alloc: AllocationResult | None = None,
    prefs: OptimizationPrefs | None = None,
    transfer_advice: TransferAdvice | None = None,
    milestones: Sequence[SpendMilestoneSpec] = (),
    group_caps: Sequence[TransferGroupCapSpec] = (),
    line_mccs: dict[str, int] | None = None,
    solver_backend: str = "greedy_sweep_v1",
    solver_seed: int = 1,
    num_workers: int = 1,
    optimality_status: Literal[
        "optimal", "feasible", "heuristic_bounded", "infeasible", "unknown"
    ] = "heuristic_bounded",
    gamma: int = 0,
    max_time_in_seconds: float | None = None,
) -> ExplainAndAuditBundle:
    """Convenience entrypoint emitting both always-on explanations and the XAIOR certificate."""
    explanations = build_always_on_explanation(
        trip,
        wallet,
        kb,
        result,
        alloc=alloc,
        transfer_advice=transfer_advice,
        milestones=milestones,
        group_caps=group_caps,
        line_mccs=line_mccs,
    )
    audit = build_audit_certificate(
        trip,
        wallet,
        kb,
        result,
        prefs=prefs,
        transfer_advice=transfer_advice,
        milestones=milestones,
        group_caps=group_caps,
        solver_backend=solver_backend,
        solver_seed=solver_seed,
        num_workers=num_workers,
        optimality_status=optimality_status,
        gamma=gamma,
        max_time_in_seconds=max_time_in_seconds,
    )
    return ExplainAndAuditBundle(explanations=explanations, audit_certificate=audit)
