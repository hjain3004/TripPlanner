"""Evidence graph node types.

Names follow spec 16 where spec 16 already defines them. Money is integer minor
units. Nothing in this module performs arithmetic on money.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .identity import EvidenceIdentity


class ResolutionState(StrEnum):
    ACTIVE = "active"
    REVERSED = "reversed"


class ResolutionRecord(BaseModel):
    resolution_id: str
    members: list[str]
    canonical_id: str
    rule: str
    confidence: float
    created_by_run: str
    state: ResolutionState = ResolutionState.ACTIVE
    reversed_by_run: str | None = None


class ClaimKind(StrEnum):
    CASH_QUOTE = "cash_quote"
    PRICE_OBSERVATION = "price_observation"
    SANDBOX_FIXTURE = "sandbox_fixture"
    AWARD_AVAILABILITY = "award_availability"
    REFERENCE_FACT = "reference_fact"


class FreshnessState(StrEnum):
    """Spec 16 §3. Evidence provenance only — never graph lifecycle."""

    LIVE = "live"
    CACHED = "cached"
    ESTIMATED = "estimated"
    STALE = "stale"
    VERIFY_REQUIRED = "verify_required"


class LifecycleState(StrEnum):
    """Graph lifecycle. Orthogonal to evidence provenance."""

    ACTIVE = "active"
    SUPERSEDED = "superseded"


class Source(BaseModel):
    source_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    retrieved_at: AwareDatetime
    source_url: str = Field(min_length=1)
    terms_ref: str | None = None


class Claim(BaseModel):
    claim_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    kind: ClaimKind
    identity: EvidenceIdentity
    payload: dict[str, Any]
    source_id: str | None
    is_inference: bool
    status: FreshnessState
    lifecycle: LifecycleState = LifecycleState.ACTIVE
    superseded_by: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_verification: bool
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _source_or_inference(self) -> Claim:
        """Invariant 1: every claim has a source or is marked inference."""
        if self.source_id is None and not self.is_inference:
            raise ValueError("claim must have a source_id or is_inference=True")
        return self

    @model_validator(mode="after")
    def _cross_validate_kind(self) -> Claim:
        if self.kind == ClaimKind.CASH_QUOTE:
            if self.identity.kind not in ("flight_quote", "hotel_quote"):
                raise ValueError("CASH_QUOTE must carry a quote identity")
        elif self.kind == ClaimKind.PRICE_OBSERVATION:
            if self.identity.kind != "flight_price_observation":
                raise ValueError("PRICE_OBSERVATION must carry an observation identity")
        elif self.kind == ClaimKind.AWARD_AVAILABILITY:
            if self.identity.kind != "award_quote":
                raise ValueError("AWARD_AVAILABILITY must carry an award identity")
        elif self.kind == ClaimKind.REFERENCE_FACT:
            if self.identity.kind != "reference_fact":
                raise ValueError("REFERENCE_FACT must carry a reference identity")
        return self


class Artifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    run_id: str = Field(min_length=1)  # invariant 2
    version: int = Field(ge=1)  # invariant 2
    derived_from: list[str] = Field(default_factory=list)
    # ^ claim ids OR artifact ids; both must resolve in the graph
    derived_from_kb_facts: list[str] = Field(default_factory=list)
    # ^ opaque approved-KB row ids. NOT graph nodes. KB rows keep their own
    #   Tier-F Provenance columns and are never copied into the graph.


class Run(BaseModel):
    run_id: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def _ended_not_before_started(self) -> Run:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("ended_at must not be before started_at")
        return self


class Evaluation(BaseModel):
    evaluation_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    rubric_id: str = Field(min_length=1)  # invariant 3
    verdict: str = Field(min_length=1)
    reasons: list[str] = Field(default_factory=list)
    run_id: str = Field(min_length=1)
