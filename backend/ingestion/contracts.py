from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256 = r"^[0-9a-f]{64}$"


def _https_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("URL must use http or https and include a host")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("URL cannot contain credentials or a fragment")
    return value


class SourcePolicyRecord(BaseModel):
    policy_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    source_url: str
    terms_url: str
    terms_read_on: date
    automated_access_permitted: bool
    manual_only: bool
    allowed_page_classes: tuple[str, ...] = Field(min_length=1)
    minimum_delay_seconds: int = Field(default=10, ge=10)
    stated_rate_limit: str | None = None
    retention_policy: str | None = None
    attribution_required: bool = False
    reviewed_on: date
    reviewed_by: str = Field(min_length=1)
    terms_version: str = Field(default="unversioned", min_length=1)

    _source_url = field_validator("source_url", "terms_url")(_https_url)

    @model_validator(mode="after")
    def _manual_policy_is_consistent(self) -> SourcePolicyRecord:
        if not self.automated_access_permitted and not self.manual_only:
            raise ValueError("a policy that forbids automation must be manual_only")
        return self


class DiscoveryCandidate(BaseModel):
    """A financial lead; deliberately not a fact and deliberately no provenance."""

    id: str = Field(min_length=1)
    found_at: date
    hint_url: str
    hint_source: str = Field(min_length=1)
    corridor: Literal["IN", "AE", "US"]
    kind: Literal["card", "offer", "welcome_bonus"]
    issuer_guess: str = Field(min_length=1)
    product_guess: str = Field(min_length=1)
    claim_summary: str = Field(min_length=1)
    issuer_url_to_verify: str | None = None
    status: Literal["pending", "promoted", "rejected", "duplicate"]
    decided_by: str | None = None
    decided_at: date | None = None

    _hint_url = field_validator("hint_url")(_https_url)
    _issuer_url = field_validator("issuer_url_to_verify")(_https_url)

    @model_validator(mode="after")
    def _decision_fields(self) -> DiscoveryCandidate:
        if self.status == "pending" and (
            self.decided_by is not None or self.decided_at is not None
        ):
            raise ValueError("pending candidates cannot have a curator decision")
        if self.status != "pending" and (self.decided_by is None or self.decided_at is None):
            raise ValueError("decided candidates require curator metadata")
        return self


class PageKind(StrEnum):
    CARD_PAGE = "card_page"
    OFFER_PAGE = "offer_page"
    TNC_PDF = "tnc_pdf"
    MANUAL_CAPTURE = "manual_capture"


class WatchTarget(BaseModel):
    target_id: str = Field(min_length=1)
    canonical_url: str
    source_policy_id: str = Field(min_length=1)
    target_fact_ids: tuple[str, ...] = Field(min_length=1)
    page_kind: PageKind
    check_frequency_days: int = Field(ge=1)
    css_hint: str | None = None
    preferred_backend: Literal["local", "firecrawl", "manual"] = "local"
    manual_only: bool = False
    status: Literal["active", "paused", "policy_blocked"] = "active"
    promoted_from_candidate_id: str | None = None
    promoted_by: str | None = None
    promoted_at: AwareDatetime | None = None

    _url = field_validator("canonical_url")(_https_url)


class FetchFailureKind(StrEnum):
    ROBOTS_BLOCKED = "robots_blocked"
    POLICY_BLOCKED = "policy_blocked"
    AUTHENTICATION_REQUIRED = "authentication_required"
    CAPTCHA_DETECTED = "captcha_detected"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNEXPECTED_FAILURE = "unexpected_failure"


class FetchRequest(BaseModel):
    request_id: str = Field(min_length=1)
    canonical_url: str
    source_policy_id: str = Field(min_length=1)
    evidence_kind: Literal["official_page", "tnc_pdf", "manual_capture"]
    max_bytes: int = Field(gt=0)
    max_pages: int = Field(gt=0)
    timeout_seconds: int = Field(gt=0)
    expected_selectors: tuple[str, ...] = ()
    locale: str | None = None
    forced_freshness: bool = False
    run_id: str = Field(min_length=1)

    _url = field_validator("canonical_url")(_https_url)


class ImmutableArtifactRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    sha256: str = Field(pattern=SHA256)
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    relative_path: str | None = None


class FetchFailure(BaseModel):
    kind: FetchFailureKind
    diagnostic: str = Field(min_length=1, max_length=1000)
    retryable: bool = False


class FetchResult(BaseModel):
    request_id: str = Field(min_length=1)
    final_url: str | None = None
    content_type: str | None = None
    raw_artifact: ImmutableArtifactRef | None = None
    rendered_html_artifact: ImmutableArtifactRef | None = None
    normalized_text: str = ""
    outbound_links: tuple[str, ...] = ()
    engine: str | None = None
    engine_version: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    failure: FetchFailure | None = None

    _final_url = field_validator("final_url")(_https_url)


class FetchAttempt(BaseModel):
    attempt_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    backend: Literal["local", "firecrawl", "manual"]
    backend_version: str = Field(min_length=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime
    final_url: str | None = None
    response_class: Literal["success", "unchanged", "failure", "blocked"]
    failure: FetchFailure | None = None
    retry_index: int = Field(ge=0)
    credits_reserved: int = Field(default=0, ge=0)
    credits_settled: int = Field(default=0, ge=0)

    _final_url = field_validator("final_url")(_https_url)

    @model_validator(mode="after")
    def _time_order(self) -> FetchAttempt:
        if self.ended_at < self.started_at:
            raise ValueError("fetch attempt ended before it started")
        if self.response_class in {"failure", "blocked"} and self.failure is None:
            raise ValueError("failed or blocked attempts require a typed failure")
        return self


class SnapshotBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    captured_at: AwareDatetime
    raw_artifact: ImmutableArtifactRef
    normalized_artifact: ImmutableArtifactRef
    raw_sha256: str = Field(pattern=SHA256)
    normalized_sha256: str = Field(pattern=SHA256)
    canonical_markdown: str
    extraction_engine: str | None = None
    extraction_engine_version: str | None = None
    attempts: tuple[FetchAttempt, ...] = ()
    supersedes_snapshot_id: str | None = None


class EvidenceSpan(BaseModel):
    snapshot_id: str = Field(min_length=1)
    snapshot_hash: str = Field(pattern=SHA256)
    quote: str = Field(min_length=1)
    normalized_start: int = Field(ge=0)
    normalized_end: int = Field(gt=0)
    field_path: str = Field(min_length=1)
    verification: Literal["exact", "unchecked", "rejected"]
    artifact_kind: Literal["html", "pdf", "text"] = "html"
    page_number: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _span_consistency(self) -> EvidenceSpan:
        if self.normalized_end <= self.normalized_start:
            raise ValueError("evidence offsets must be increasing")
        if self.normalized_end - self.normalized_start != len(self.quote):
            raise ValueError("evidence offsets must match quote length")
        if self.artifact_kind == "pdf" and self.page_number is None:
            raise ValueError("PDF evidence requires a page number")
        if self.artifact_kind != "pdf" and self.page_number is not None:
            raise ValueError("page number is only valid for PDF evidence")
        return self


class ValidationFinding(BaseModel):
    code: str = Field(min_length=1)
    severity: Literal["info", "warning", "blocking"]
    message: str = Field(min_length=1)
    field_path: str | None = None


class FieldProposal(BaseModel):
    field_path: str = Field(min_length=1)
    old_value: Any = None
    proposed_raw_value: Any = None
    parsed_value: Any = None
    evidence_spans: tuple[EvidenceSpan, ...] = Field(min_length=1)


class ProposalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    REVERIFY = "reverify"


class ChangeProposal(BaseModel):
    proposal_id: str = Field(min_length=1)
    target_table: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    current_row_hash: str | None = Field(default=None, pattern=SHA256)
    proposed_row: dict[str, Any]
    field_proposals: tuple[FieldProposal, ...] = Field(min_length=1)
    change_summary: str = Field(min_length=1)
    extractor_version: str = Field(min_length=1)
    validation_findings: tuple[ValidationFinding, ...] = ()
    lineage_ids: tuple[str, ...] = Field(min_length=1)
    status: ProposalStatus = ProposalStatus.PENDING
    version: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def _no_aggregator_fields(self) -> ChangeProposal:
        forbidden = {"hint_url", "hint_source", "claim_summary", "issuer_guess", "product_guess"}
        if forbidden.intersection(self.proposed_row):
            raise ValueError("aggregator discovery fields cannot enter a financial proposal")
        if self.updated_at < self.created_at:
            raise ValueError("proposal updated_at cannot precede created_at")
        return self


class ReviewDecisionStatus(StrEnum):
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"
    REVERIFY = "reverify"


class ReviewDecision(BaseModel):
    decision_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_version: int = Field(ge=1)
    reviewer_id: str = Field(min_length=1)
    status: ReviewDecisionStatus
    edits: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1)
    decided_at: AwareDatetime
    client_event_id: str = Field(min_length=1)


class ReverifyTask(BaseModel):
    task_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    priority: Literal["low", "normal", "high"]
    status: Literal["pending", "claimed", "complete", "cancelled"] = "pending"
    prior_evidence_ids: tuple[str, ...] = ()
    created_at: AwareDatetime
    due_at: AwareDatetime

    @model_validator(mode="after")
    def _time_order(self) -> ReverifyTask:
        if self.due_at < self.created_at:
            raise ValueError("reverification due_at cannot precede created_at")
        return self
