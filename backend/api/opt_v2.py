"""Optimization Engine v2 (OPT-2, OPT-3, OPT-4) deterministic FastAPI routes.

Exposes multi-currency pooled transfer planning, spend milestones + Bertsimas-Sim
Gamma-robustness optimization, always-on counterfactuals + XAIOR audit certificates,
and CP-SAT QUICKXPLAIN infeasibility diagnosis without altering frozen ``/plan``
or golden behavior. Zero LLM calls; zero float money math.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.db import DB_PATH, KnowledgeBase, load_kb, seed_database
from core.explain.audit import (
    AlwaysOnExplanation,
    DecisionAuditCertificate,
    InfeasibilityCoreResult,
    SpendMilestoneSpec,
    TransferGroupCapSpec,
    build_plan_explain_and_audit,
    explain_milestone_infeasibility,
    explain_transfer_infeasibility,
)
from core.models import (
    AwardTarget,
    Channel,
    CostedTrip,
    OptimizationPrefs,
    OptimizerResult,
    Provenance,
    TransferAdvice,
    UserWallet,
)
from core.optimizer.allocate import allocate
from core.optimizer.milestones import SpendMilestone
from core.optimizer.milp_solver import SCALE, PointFloor, optimize_trip
from core.optimizer.report import build_result
from core.transfer.pathfinder import find_transfer_plans
from core.transfer.pooling import PoolingConfig

router = APIRouter(prefix="/opt", tags=["optimization-v2"])


def get_kb() -> KnowledgeBase:
    """Load seeded KnowledgeBase, seeding locally from YAML if SQLite is absent."""
    if not DB_PATH.exists():
        seed_database()
    return load_kb(DB_PATH)


def get_opt_date() -> date:
    """Current evaluation date (overridable in tests for deterministic runs)."""
    return date.today()


# --------------------------------------------------------------------------- #
# OPT-2: Multi-Currency Pooled Transfer Planning                              #
# --------------------------------------------------------------------------- #


class PooledTransferRequest(BaseModel):
    """Request payload for OPT-2 pooled multi-currency transfer optimization."""

    model_config = ConfigDict(extra="forbid")

    target: AwardTarget
    wallet: UserWallet | None = None
    points_balances: dict[str, int] | None = None
    baseline_valuations: dict[str, int] = Field(default_factory=dict)
    cash_price_minor: int = Field(ge=0)
    on_date: date | None = None
    pooling_config: PoolingConfig | None = None

    @model_validator(mode="after")
    def _validate_wallet_or_balances(self) -> PooledTransferRequest:
        if self.wallet is None and self.points_balances is None:
            raise ValueError("either wallet or points_balances must be provided")
        if self.wallet is not None and self.points_balances is not None:
            if self.wallet.points_balances != self.points_balances:
                raise ValueError(
                    "supply either wallet or points_balances, not differing balances"
                )
        if any(v < 0 for v in self.baseline_valuations.values()):
            raise ValueError("baseline_valuations must be nonnegative")
        if self.points_balances is not None and any(v < 0 for v in self.points_balances.values()):
            raise ValueError("points_balances must be nonnegative")
        return self

    def resolved_wallet(self) -> UserWallet:
        if self.wallet is not None:
            return self.wallet
        return UserWallet(card_ids=[], points_balances=dict(self.points_balances or {}))


@router.post("/transfers/pooled", response_model=TransferAdvice)
def post_pooled_transfers(
    payload: PooledTransferRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    default_date: Annotated[date, Depends(get_opt_date)],
) -> TransferAdvice:
    """Plan single-source and pooled multi-currency award transfers (OPT-2)."""
    on_date = payload.on_date or default_date
    try:
        return find_transfer_plans(
            payload.target,
            payload.resolved_wallet(),
            kb,
            payload.baseline_valuations,
            payload.cash_price_minor,
            on_date,
            allow_pooling=True,
            pooling_config=payload.pooling_config,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


# --------------------------------------------------------------------------- #
# OPT-3: Spend Milestones, Gamma-Robustness & Shared-Cap Execution Order      #
# --------------------------------------------------------------------------- #


class OptimizeV2Request(BaseModel):
    """Request payload for OPT-3 milestones and Bertsimas-Sim Gamma-robust optimization."""

    model_config = ConfigDict(extra="forbid")

    trip: CostedTrip
    wallet: UserWallet
    prefs: OptimizationPrefs | None = None
    milestones: list[SpendMilestone] = Field(default_factory=list)
    gamma: int = Field(default=0, ge=0, le=2)
    valuation_floors_micro: dict[str, int] | None = None
    floor_provenance: dict[str, Provenance] | None = None

    @model_validator(mode="after")
    def _validate_robust_floors(self) -> OptimizeV2Request:
        if self.gamma > 0 and not self.valuation_floors_micro:
            raise ValueError(
                "gamma > 0 requires explicit valuation_floors_micro; "
                "downside floors are never invented"
            )
        if self.valuation_floors_micro is not None:
            for card_id, floor_val in self.valuation_floors_micro.items():
                if floor_val < 0:
                    raise ValueError(f"valuation floor for {card_id} must be nonnegative")
        return self


class OptimizeV2Assignment(BaseModel):
    """Per-line selected card/channel and benefit breakdown from OPT-3/frozen optimization."""

    model_config = ConfigDict(extra="forbid")

    line_id: str
    card_id: str
    channel: Channel
    spend_minor: int
    nominal_benefit_minor: int
    floor_benefit_minor: int
    bundle_id: str | None = None


class OptimizeV2Response(BaseModel):
    """Normalized response for OPT-3 milestones/robustness and frozen fallback."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["kernel_frozen", "opt3_milp"]
    status: Literal["optimal", "frozen_deterministic"]
    objective_scaled: int
    gamma: int
    execution_order: list[str]
    assignments: list[OptimizeV2Assignment]
    achieved_milestone_indices: list[int]
    achieved_milestones: list[SpendMilestone]
    optimizer_result: OptimizerResult | None = None


def _build_point_floors(
    kb: KnowledgeBase,
    valuation_floors_micro: dict[str, int] | None,
    floor_provenance: dict[str, Provenance] | None,
) -> dict[str, PointFloor]:
    if not valuation_floors_micro:
        return {}
    out: dict[str, PointFloor] = {}
    for card_id, floor_micro in sorted(valuation_floors_micro.items()):
        if not kb.has_card(card_id):
            raise ValueError(f"unknown card_id in valuation_floors_micro: {card_id}")
        val_obj = kb.best_valuation_obj(card_id)
        if val_obj is None:
            raise ValueError(f"no nominal valuation established in KB for {card_id}")
        prov = (
            floor_provenance[card_id]
            if floor_provenance is not None and card_id in floor_provenance
            else val_obj.provenance
        )
        out[card_id] = PointFloor(
            currency_id=card_id,
            nominal_micro_major=val_obj.value_micro_major_per_point,
            floor_micro_major=floor_micro,
            provenance=prov,
        )
    return out


@router.post("/optimize-v2", response_model=OptimizeV2Response)
def post_optimize_v2(
    payload: OptimizeV2Request,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
) -> OptimizeV2Response:
    """Run OPT-3 exact milestone + Gamma-robust solver (or frozen allocator when inactive)."""
    try:
        point_values = _build_point_floors(
            kb, payload.valuation_floors_micro, payload.floor_provenance
        )
        raw = optimize_trip(
            payload.trip,
            payload.wallet,
            kb,
            tuple(payload.milestones),
            gamma=payload.gamma,
            point_values=point_values or None,
            prefs=payload.prefs,
        )
    except (ValueError, OverflowError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if isinstance(raw, OptimizerResult):
        total_benefit = (
            raw.discounts_minor + raw.rewards_value_minor - raw.forex_fees_minor
        )
        assignments = [
            OptimizeV2Assignment(
                line_id=a.line.id,
                card_id=a.card_id,
                channel=a.channel,
                spend_minor=max(
                    0, a.line.amount_minor - sum(o.discount_minor for o in a.offers_applied)
                ),
                nominal_benefit_minor=a.benefit_minor,
                floor_benefit_minor=a.benefit_minor,
                bundle_id=None,
            )
            for a in raw.assignments
        ]
        return OptimizeV2Response(
            mode="kernel_frozen",
            status="frozen_deterministic",
            objective_scaled=total_benefit * SCALE,
            gamma=payload.gamma,
            execution_order=[a.line.id for a in raw.assignments],
            assignments=assignments,
            achieved_milestone_indices=[],
            achieved_milestones=[],
            optimizer_result=raw,
        )

    assignments = [
        OptimizeV2Assignment(
            line_id=b.line_id,
            card_id=b.card_id,
            channel=b.channel,
            spend_minor=b.spend_minor,
            nominal_benefit_minor=b.nominal_minor,
            floor_benefit_minor=b.floor_minor,
            bundle_id=b.id,
        )
        for b in raw.chosen
    ]
    achieved = [payload.milestones[idx] for idx in raw.achieved_milestones]
    return OptimizeV2Response(
        mode="opt3_milp",
        status=raw.status,
        objective_scaled=raw.objective_scaled,
        gamma=payload.gamma,
        execution_order=list(raw.execution_order),
        assignments=assignments,
        achieved_milestone_indices=list(raw.achieved_milestones),
        achieved_milestones=achieved,
        optimizer_result=None,
    )


# --------------------------------------------------------------------------- #
# OPT-4: Always-On Explanations, XAIOR Certificate & QUICKXPLAIN Diagnosis    #
# --------------------------------------------------------------------------- #


class ExplainAuditRequest(BaseModel):
    """Request payload for OPT-4 deterministic explanation and XAIOR audit certificate."""

    model_config = ConfigDict(extra="forbid")

    trip: CostedTrip
    wallet: UserWallet
    prefs: OptimizationPrefs | None = None
    transfer_advice: TransferAdvice | None = None
    milestones: list[SpendMilestoneSpec] = Field(default_factory=list)
    group_caps: list[TransferGroupCapSpec] = Field(default_factory=list)
    line_mccs: dict[str, int] | None = None
    gamma: int = Field(default=0, ge=0, le=2)


class ExplainAuditResponse(BaseModel):
    """Optimizer result paired with always-on counterfactuals and XAIOR certificate."""

    model_config = ConfigDict(extra="forbid")

    optimizer_result: OptimizerResult
    explanation: AlwaysOnExplanation
    audit_certificate: DecisionAuditCertificate


@router.post("/explain-audit", response_model=ExplainAuditResponse)
def post_explain_audit(
    payload: ExplainAuditRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
) -> ExplainAuditResponse:
    """Compute plan allocation alongside always-on explanations and XAIOR audit certificate."""
    try:
        resolved_prefs = payload.prefs or OptimizationPrefs()
        alloc = allocate(kb, payload.trip, payload.wallet, resolved_prefs)
        result = build_result(kb, payload.trip, payload.wallet, alloc, resolved_prefs)
        bundle = build_plan_explain_and_audit(
            payload.trip,
            payload.wallet,
            kb,
            result,
            alloc=alloc,
            prefs=resolved_prefs,
            transfer_advice=payload.transfer_advice,
            milestones=payload.milestones,
            group_caps=payload.group_caps,
            line_mccs=payload.line_mccs,
            gamma=payload.gamma,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return ExplainAuditResponse(
        optimizer_result=result,
        explanation=bundle.explanations,
        audit_certificate=bundle.audit_certificate,
    )


class TransferInfeasibilityRequest(BaseModel):
    """QUICKXPLAIN diagnosis request for an unsatisfiable transfer goal."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["transfer"] = "transfer"
    target_program_id: str = Field(min_length=1)
    required_miles: int = Field(ge=0)
    wallet: UserWallet
    on_date: date | None = None
    max_transfer_hours: int | None = Field(default=None, ge=0)
    max_transfers: int | None = Field(default=None, ge=1)
    group_caps: list[TransferGroupCapSpec] = Field(default_factory=list)


class MilestoneInfeasibilityRequest(BaseModel):
    """QUICKXPLAIN diagnosis request for conflicting card spend milestones/caps."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["milestone"] = "milestone"
    trip: CostedTrip
    wallet: UserWallet
    milestones: list[SpendMilestoneSpec]
    total_budget_cap_minor: int | None = Field(default=None, ge=0)
    card_spend_caps_minor: dict[str, int] | None = None


DiagnoseInfeasibilityRequest = Annotated[
    TransferInfeasibilityRequest | MilestoneInfeasibilityRequest,
    Field(discriminator="kind"),
]


@router.post("/diagnose-infeasibility", response_model=InfeasibilityCoreResult)
def post_diagnose_infeasibility(
    payload: DiagnoseInfeasibilityRequest,
    kb: Annotated[KnowledgeBase, Depends(get_kb)],
    default_date: Annotated[date, Depends(get_opt_date)],
) -> InfeasibilityCoreResult:
    """Compute subset-minimal conflict core (QUICKXPLAIN) and minimal discrete relaxations."""
    try:
        if isinstance(payload, TransferInfeasibilityRequest):
            return explain_transfer_infeasibility(
                target_program_id=payload.target_program_id,
                required_miles=payload.required_miles,
                wallet=payload.wallet,
                kb=kb,
                on_date=payload.on_date or default_date,
                max_transfer_hours=payload.max_transfer_hours,
                max_transfers=payload.max_transfers,
                group_caps=payload.group_caps,
            )
        return explain_milestone_infeasibility(
            trip=payload.trip,
            wallet=payload.wallet,
            kb=kb,
            milestones=payload.milestones,
            total_budget_cap_minor=payload.total_budget_cap_minor,
            card_spend_caps_minor=payload.card_spend_caps_minor,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
