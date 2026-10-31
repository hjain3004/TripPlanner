from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ingestion.contracts import (
    ChangeProposal,
    EvidenceSpan,
    ReviewDecision,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)


class FindingCode(StrEnum):
    STORED_BLOCKING_FINDING = "stored_blocking_finding"
    UNSUPPORTED_TARGET_TABLE = "unsupported_target_table"
    CURRENT_ROW_MISSING = "current_row_missing"
    UNBOUND_BASE_ROW = "unbound_base_row"
    CURRENT_ROW_CHANGED = "current_row_changed"
    EVIDENCE_INTEGRITY_FAILED = "evidence_integrity_failed"
    EVIDENCE_SUPERSEDED = "evidence_superseded"
    MULTI_SNAPSHOT_LINEAGE = "multi_snapshot_lineage"
    MANUAL_CAPTURE = "manual_capture"
    ATTRIBUTION_REQUIRED = "attribution_required"
    UNKNOWN_CURATOR = "unknown_curator"
    UNSUPPORTED_EDIT_TYPE = "unsupported_edit_type"
    INVALID_EDIT = "invalid_edit"
    NO_EFFECTIVE_EDIT = "no_effective_edit"


class ComputedFinding(BaseModel):
    code: FindingCode
    severity: Literal["warning", "blocking"]
    message: str
    field_path: str | None = None


class FieldDiff(BaseModel):
    field_path: str
    current: Any = None
    proposed: Any = None
    edited: Any = None
    changed: bool
    evidence: tuple[EvidenceSpan, ...] = ()


class EvidenceContext(BaseModel):
    span: EvidenceSpan
    before: str
    after: str
    verified: bool
    failure: str | None = None


class LineageView(BaseModel):
    source_policy: SourcePolicyRecord
    watch_target: WatchTarget
    snapshots: tuple[SnapshotBundle, ...]
    supersession_chain: tuple[str, ...]
    latest_snapshot_id: str | None


class ReviewContext(BaseModel):
    proposal: ChangeProposal
    current_row: dict[str, Any] | None
    current_row_sha256: str | None
    field_diffs: tuple[FieldDiff, ...]
    evidence: tuple[EvidenceContext, ...]
    lineage: LineageView | None
    computed_findings: tuple[ComputedFinding, ...]
    decisions: tuple[ReviewDecision, ...]
    audit_events: tuple[dict[str, str], ...]

    @property
    def blocking_for_approval(self) -> bool:
        return any(f.severity == "blocking" for f in self.computed_findings)

    @property
    def blocking_for_edit(self) -> bool:
        return self.blocking_for_approval


class CuratorFieldEdit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_path: str = Field(min_length=1, max_length=200)
    action: Literal["set", "revert"]
    proposed_raw_value: str | None = Field(default=None, max_length=200)
    quote: str | None = Field(default=None, max_length=2000)
    occurrence: int | None = Field(default=None, ge=1)
    snapshot_id: str | None = None
    page_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_shape(self) -> CuratorFieldEdit:
        values = (
            self.proposed_raw_value,
            self.quote,
            self.occurrence,
            self.snapshot_id,
            self.page_number,
        )
        if self.action == "set" and any(value is None for value in values[:2] + values[3:4]):
            raise ValueError("set edits require raw value, quote, and snapshot_id")
        if self.action == "revert" and any(value is not None for value in values):
            raise ValueError("revert edits cannot carry evidence or a value")
        return self


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=1)
    action: Literal["approve", "edit", "reject", "reverify"]
    reason: str = Field(min_length=1, max_length=1000)
    expected_version: int = Field(ge=1)
    client_event_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    curator_confidence: float | None = None
    edits: tuple[CuratorFieldEdit, ...] = ()

    @model_validator(mode="after")
    def validate_request(self) -> DecisionRequest:
        needs_confidence = self.action in {"approve", "edit"}
        if needs_confidence != (self.curator_confidence is not None):
            raise ValueError("curator confidence is required only for approve/edit")
        if self.curator_confidence is not None and (
            not 0 <= self.curator_confidence <= 1
            or round(self.curator_confidence, 2) != self.curator_confidence
        ):
            raise ValueError("curator confidence must be between 0 and 1 with two decimals")
        if (self.action == "edit") != bool(self.edits):
            raise ValueError("edit action requires at least one edit")
        paths = [edit.field_path for edit in self.edits]
        if len(paths) != len(set(paths)):
            raise ValueError("edit field paths must be unique")
        return self


class ReviewRefusedError(ValueError):
    def __init__(self, message: str, findings: tuple[ComputedFinding, ...] = ()) -> None:
        super().__init__(message)
        self.findings = findings
