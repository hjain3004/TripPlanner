"""Evidence graph node types.

Names follow spec 16 where spec 16 already defines them. Money is integer minor
units. Nothing in this module performs arithmetic on money.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


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
    provider: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)   # ISO-8601
    source_url: str = Field(min_length=1)
    terms_ref: str | None = None


class Claim(BaseModel):
    claim_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    kind: ClaimKind
    payload: dict[str, Any]
    source_id: str | None
    is_inference: bool
    status: FreshnessState
    lifecycle: LifecycleState = LifecycleState.ACTIVE
    superseded_by: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    needs_verification: bool

    @model_validator(mode="after")
    def _source_or_inference(self) -> Claim:
        """Invariant 1: every claim has a source or is marked inference."""
        if self.source_id is None and not self.is_inference:
            raise ValueError("claim must have a source_id or is_inference=True")
        return self


class Artifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    run_id: str = Field(min_length=1)          # invariant 2
    version: int = Field(ge=1)                 # invariant 2
    derived_from: list[str] = Field(default_factory=list)
    # ^ claim ids OR artifact ids; both must resolve in the graph
    derived_from_kb_facts: list[str] = Field(default_factory=list)
    # ^ opaque approved-KB row ids. NOT graph nodes. KB rows keep their own
    #   Tier-F Provenance columns and are never copied into the graph.


class Run(BaseModel):
    run_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    ended_at: str | None = None


class Evaluation(BaseModel):
    evaluation_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    rubric_id: str = Field(min_length=1)       # invariant 3
    verdict: str = Field(min_length=1)
    reasons: list[str] = Field(default_factory=list)
