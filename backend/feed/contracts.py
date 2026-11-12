"""Neutral, immutable DTOs and contracts for the travel change feed.

Strict isolation rule: this module must never import from backend/ingestion/,
backend/api/, backend/accounts/, or backend/core/.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

# --- Event Types and Subject References ---

EventType = Literal["transfer_bonus", "welcome_offer", "earn_rate_change"]

SubjectKind = Literal[
    "card",
    "reward_rule",
    "loyalty_program",
    "transfer_partner",
    "merchant_offer",
]


class SubjectRef(BaseModel):
    """Reference to a financial or reward subject.

    Resolves only through exact existing KB IDs or an owner-approved alias map.
    Unknown references stay unmapped (kb_id=None) and cannot produce personal impacts.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: SubjectKind
    source_name: str = Field(min_length=1)
    kb_id: str | None = None


# --- Effective Dates ---


class EffectiveWindow(BaseModel):
    """Effective date window for a change event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start_date: date
    end_date: date | None = None
    is_ongoing: bool = False
    reconfirm_by: date | None = None

    @model_validator(mode="after")
    def _validate_dates(self) -> EffectiveWindow:
        if self.end_date is not None and self.start_date > self.end_date:
            raise ValueError(
                f"start_date ({self.start_date}) cannot be after end_date ({self.end_date})"
            )
        return self


# --- Typed Terms (Discriminated Union) ---


class TransferBonusTerms(BaseModel):
    """Terms for a points transfer bonus between programmes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["transfer_bonus"] = "transfer_bonus"
    from_program: SubjectRef
    to_program: SubjectRef
    bonus_bp: int = Field(ge=0, le=100_000)
    quoted_dates: str = Field(min_length=1)
    min_transfer_points: int | None = Field(default=None, gt=0)
    max_bonus_points: int | None = Field(default=None, gt=0)
    restrictions: tuple[str, ...] | None = None
    raw_bonus_text: str | None = None


class WelcomeOfferTerms(BaseModel):
    """Terms for a new card acquisition welcome offer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["welcome_offer"] = "welcome_offer"
    card: SubjectRef
    bonus_points: int | None = Field(default=None, ge=0)
    bonus_program: SubjectRef | None = None
    bonus_cash_minor: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    min_spend_minor: int = Field(ge=0)
    min_spend_currency: str = Field(min_length=3, max_length=3)
    spend_window_days: int | None = Field(default=None, gt=0)
    spend_window_months: int | None = Field(default=None, gt=0)
    spend_window_basis: Literal[
        "approval",
        "account_open",
        "card_activation",
        "first_spend",
        "calendar_month",
    ] = "approval"
    quoted_spend_window: str = Field(min_length=1)
    eligibility_exclusions: tuple[str, ...] | None = None
    fee_first_year_waived: bool | None = None
    annual_fee_minor: int | None = Field(default=None, ge=0)
    approval_delivery_time: str | None = None

    @model_validator(mode="after")
    def _validate_bonus_and_window(self) -> WelcomeOfferTerms:
        has_points = self.bonus_points is not None and self.bonus_points > 0
        has_cash = self.bonus_cash_minor is not None and self.bonus_cash_minor > 0
        if not has_points and not has_cash:
            raise ValueError(
                "welcome_offer requires either positive bonus_points or positive bonus_cash_minor"
            )
        if has_points and self.bonus_program is None:
            raise ValueError("points bonus requires bonus_program SubjectRef")
        if has_cash and self.currency is None:
            raise ValueError("cash bonus requires currency ISO code")
        if self.spend_window_days is None and self.spend_window_months is None:
            raise ValueError("welcome_offer requires spend_window_days or spend_window_months")
        return self


class EarnRateChangeTerms(BaseModel):
    """Terms for an earn rate change on a card or rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: Literal["earn_rate_change"] = "earn_rate_change"
    card: SubjectRef
    new_points: int = Field(ge=0)
    new_per_amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    effective_start: date
    spend_scope: str = Field(min_length=1)
    prior_points: int | None = Field(default=None, ge=0)
    prior_per_amount_minor: int | None = Field(default=None, gt=0)
    reward_program: SubjectRef | None = None
    cap: int | None = Field(default=None, gt=0)
    exclusions: tuple[str, ...] | None = None
    effective_end: date | None = None

    @model_validator(mode="after")
    def _validate_effective_dates(self) -> EarnRateChangeTerms:
        if self.effective_end is not None and self.effective_start > self.effective_end:
            raise ValueError(
                f"effective_start ({self.effective_start}) cannot exceed "
                f"effective_end ({self.effective_end})"
            )
        return self


FeedTerms = Annotated[
    TransferBonusTerms | WelcomeOfferTerms | EarnRateChangeTerms,
    Field(discriminator="type"),
]


# --- Trust and Status Classifications ---

TrustLevel = Literal["lead_only", "primary_confirmed", "human_approved"]

FactsStatus = Literal[
    "draft_proposal",
    "valid_proposal",
    "unsupported_target",
    "applied",
    "rejected",
    "superseded",
]

PublicationPermission = Literal[
    "approved_for_publication",
    "restricted_internal_only",
    "pending_review",
]


# --- Evidence and Provenance Receipts ---


class FieldSpan(BaseModel):
    """Quoted evidence span in an immutable snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_path: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    slice_sha256: str | None = None

    @model_validator(mode="after")
    def _validate_offsets(self) -> FieldSpan:
        if self.start_offset >= self.end_offset:
            raise ValueError(
                f"start_offset ({self.start_offset}) must be strictly less than "
                f"end_offset ({self.end_offset})"
            )
        return self


class EvidenceReceipt(BaseModel):
    """Immutable evidence receipt binding source policy, snapshot, and fetch lineage."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str = Field(min_length=1)
    source_policy_id: str = Field(min_length=1)
    source_policy_hash: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    artifact_sha256: str = Field(min_length=1)
    raw_sha256: str = Field(min_length=1)
    normalized_sha256: str = Field(min_length=1)
    provider_envelope_sha256: str | None = None
    fetch_attempt_id: str = Field(min_length=1)
    observed_at: AwareDatetime
    is_replayed: bool = False
    field_spans: tuple[FieldSpan, ...] = ()
    fidelity: Literal[
        "original_issuer_bytes",
        "provider_rendered_html",
        "manual_capture",
        "synthetic_fixture",
    ]


# --- Core Change Event ---


class ChangeEvent(BaseModel):
    """An immutable change feed item."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    event_type: EventType
    subjects: tuple[SubjectRef, ...] = Field(min_length=1)
    effective_window: EffectiveWindow
    terms: FeedTerms
    trust_level: TrustLevel = "lead_only"
    facts_status: FactsStatus = "unsupported_target"
    first_seen_at: AwareDatetime
    latest_observed_at: AwareDatetime
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    evidence_receipts: tuple[EvidenceReceipt, ...] = ()
    superseded_by: str | None = None
    conflict_event_ids: tuple[str, ...] = ()
    curator_notes: str | None = None


# --- Changed Block Contracts ---


class BlockLimits(BaseModel):
    """Configurable boundaries for diff block generation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_text_chars: int = 200_000
    max_lines: int = 4_000
    max_block_chars_per_side: int = 8_000
    max_blocks: int = 32
    context_lines: int = 2


class ChangedBlock(BaseModel):
    """Contextual changed block between two canonical snapshots."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    block_id: str = Field(min_length=1)
    change_kind: Literal["addition", "deletion", "modification"]
    before_line_range: tuple[int, int] | None = None  # (start, end) 1-based inclusive
    after_line_range: tuple[int, int] | None = None
    before_char_range: tuple[int, int] | None = None  # (start, end) 0-based slice in before
    after_char_range: tuple[int, int] | None = None   # (start, end) 0-based slice in after
    before_context: tuple[str, ...] = ()
    after_context: tuple[str, ...] = ()
    before_content: str = ""
    after_content: str = ""


class BlockOutcome(BaseModel):
    """Outcome of computing contextual changed blocks."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "unchanged", "oversize", "needs_review", "baseline"]
    blocks: tuple[ChangedBlock, ...] = ()
    total_blocks: int = 0
    truncated: bool = False
    diagnostic: str | None = None


# --- Public Read DTOs ---


class PublicEvent(BaseModel):
    """Sanitized public-facing representation of a published change event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    event_type: EventType
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    trust_level: TrustLevel
    effective_window: EffectiveWindow
    subjects: tuple[SubjectRef, ...]
    first_seen_at: AwareDatetime
    latest_observed_at: AwareDatetime
    is_verified: bool
    terms_summary: dict[str, Any]


class FeedFilters(BaseModel):
    """Query filters for listing published change feed items."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_types: tuple[EventType, ...] | None = None
    program_ids: tuple[str, ...] | None = None
    card_ids: tuple[str, ...] | None = None
    from_date: date | None = None
    to_date: date | None = None


class FeedPage(BaseModel):
    """Paginated collection of public feed events."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    items: tuple[PublicEvent, ...] = ()
    cursor: str | None = None
    has_more: bool = False
    total_approx: int | None = None


# --- Receipts and Operation DTOs ---


class DraftReceipt(BaseModel):
    """Receipt for persisting a draft change event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    status: Literal["draft_saved", "replayed"]
    client_event_id: str = Field(min_length=1)
    saved_at: AwareDatetime


class PublicationReceipt(BaseModel):
    """Receipt for publishing a validated change event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    publication_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    status: Literal["published", "replayed"]
    sequence_num: int = Field(ge=1)
    client_event_id: str = Field(min_length=1)
    published_at: AwareDatetime


class HeadReceipt(BaseModel):
    """Receipt for CAS head updates (retractions or supersessions)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    status: Literal["retracted", "superseded"]
    version: int = Field(ge=1)
    client_event_id: str = Field(min_length=1)
    retracted_at: AwareDatetime
    reason: str = Field(min_length=1)


class StepOutcome(BaseModel):
    """Outcome of a single step in the feed processing pipeline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_name: str = Field(min_length=1)
    fingerprint: str = Field(min_length=1)
    status: Literal["completed", "replayed", "needs_reconciliation", "failed"]
    model_calls_reserved: int = 0
    model_calls_settled: int = 0
    error: str | None = None


class EventImpact(BaseModel):
    """Impact of a change event on an authenticated saved trip or user wallet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    trip_id: str | None = None
    revision_id: str | None = None
    result_hash: str = Field(min_length=1)
    overlay_hash: str = Field(min_length=1)
    input_hash: str = Field(min_length=1)
    delta_minor: int
    basis: str = Field(min_length=1)
    computed_at: AwareDatetime


# --- Protocols for Feed Operations (Handoff Seams) ---


class EventWriterProtocol(Protocol):
    """Writer interface for change-feed lifecycle operations."""

    def put_draft(self, event: ChangeEvent, *, client_event_id: str) -> DraftReceipt:
        ...

    def retract(
        self,
        event_id: str,
        *,
        expected_version: int,
        curator_id: str,
        reason: str,
        client_event_id: str,
    ) -> HeadReceipt:
        ...


class FeedReaderProtocol(Protocol):
    """Reader interface for public feed queries."""

    def list(
        self, filters: FeedFilters, *, cursor: str | None, limit: int, now: AwareDatetime
    ) -> FeedPage:
        ...

    def get(self, event_id: str, *, now: AwareDatetime) -> PublicEvent | None:
        ...
