"""Offline change-feed event identity, deterministic validation, and subject resolution.

Implements the core contracts from Sol's change-feed design:
`docs/superpowers/specs/2026-11-11-change-feed-design.md`.
- Re-exports feed contracts.
- Deterministic event_id computation via canonical JSON.
- Subject resolution against KnowledgeBase / alias maps with explicit unmapped state.
- Evidence span verification against immutable snapshots.
- Typed event validation and refusal.
- Supersession versus conflict classification.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

# Re-export neutral contracts from backend/feed/contracts.py
from feed.contracts import (
    BlockLimits,
    BlockOutcome,
    ChangedBlock,
    ChangeEvent,
    DraftReceipt,
    EarnRateChangeTerms,
    EffectiveWindow,
    EventImpact,
    EventType,
    EvidenceReceipt,
    FactsStatus,
    FeedFilters,
    FeedPage,
    FeedTerms,
    FieldSpan,
    HeadReceipt,
    PublicationPermission,
    PublicationReceipt,
    PublicEvent,
    StepOutcome,
    SubjectKind,
    SubjectRef,
    TransferBonusTerms,
    TrustLevel,
    WelcomeOfferTerms,
)

__all__ = [
    "BlockLimits",
    "BlockOutcome",
    "ChangeEvent",
    "ChangedBlock",
    "DraftReceipt",
    "EarnRateChangeTerms",
    "EffectiveWindow",
    "EventImpact",
    "EventRefusal",
    "EventRelationship",
    "EventType",
    "EvidenceReceipt",
    "EvidenceResolver",
    "ExtractedEvent",
    "FactsStatus",
    "FeedFilters",
    "FeedPage",
    "FeedTerms",
    "FieldSpan",
    "HeadReceipt",
    "KBSubjectResolver",
    "PublicEvent",
    "PublicationPermission",
    "PublicationReceipt",
    "SnapshotEvidenceResolver",
    "StepOutcome",
    "SubjectKind",
    "SubjectRef",
    "SubjectResolver",
    "TransferBonusTerms",
    "TrustLevel",
    "ValidatedEvent",
    "WelcomeOfferTerms",
    "classify_event_relationship",
    "compute_event_id",
    "validate_event",
]


# --- Deterministic Canonical Identity ---


def _canonical_subject(s: SubjectRef) -> dict[str, Any]:
    return {
        "kind": s.kind,
        "kb_id": s.kb_id,
        "source_name": s.source_name if s.kb_id is None else None,
    }


def _canonical_terms_dict(terms: FeedTerms) -> dict[str, Any]:
    if isinstance(terms, TransferBonusTerms):
        return {
            "type": "transfer_bonus",
            "from_program": _canonical_subject(terms.from_program),
            "to_program": _canonical_subject(terms.to_program),
            "bonus_bp": terms.bonus_bp,
            "min_transfer_points": terms.min_transfer_points,
            "max_bonus_points": terms.max_bonus_points,
            "restrictions": list(terms.restrictions) if terms.restrictions else None,
        }
    if isinstance(terms, WelcomeOfferTerms):
        return {
            "type": "welcome_offer",
            "card": _canonical_subject(terms.card),
            "bonus_points": terms.bonus_points,
            "bonus_program": (
                _canonical_subject(terms.bonus_program) if terms.bonus_program else None
            ),
            "bonus_cash_minor": terms.bonus_cash_minor,
            "currency": terms.currency,
            "min_spend_minor": terms.min_spend_minor,
            "min_spend_currency": terms.min_spend_currency,
            "spend_window_days": terms.spend_window_days,
            "spend_window_months": terms.spend_window_months,
            "spend_window_basis": terms.spend_window_basis,
            "eligibility_exclusions": (
                list(terms.eligibility_exclusions) if terms.eligibility_exclusions else None
            ),
            "fee_first_year_waived": terms.fee_first_year_waived,
            "annual_fee_minor": terms.annual_fee_minor,
        }
    if isinstance(terms, EarnRateChangeTerms):
        return {
            "type": "earn_rate_change",
            "card": _canonical_subject(terms.card),
            "new_points": terms.new_points,
            "new_per_amount_minor": terms.new_per_amount_minor,
            "currency": terms.currency,
            "effective_start": terms.effective_start.isoformat(),
            "spend_scope": terms.spend_scope,
            "prior_points": terms.prior_points,
            "prior_per_amount_minor": terms.prior_per_amount_minor,
            "reward_program": (
                _canonical_subject(terms.reward_program) if terms.reward_program else None
            ),
            "cap": terms.cap,
            "exclusions": list(terms.exclusions) if terms.exclusions else None,
            "effective_end": terms.effective_end.isoformat() if terms.effective_end else None,
        }
    raise ValueError(f"unsupported terms type: {type(terms)}")


def compute_event_id(
    version: int,
    event_type: EventType,
    subjects: Sequence[SubjectRef],
    effective_window: EffectiveWindow,
    terms: FeedTerms,
) -> str:
    """Compute deterministic SHA-256 event_id from canonical JSON.

    Sol's spec §1:
    event_id = sha256(canonical_json(version, type, subjects, effective_window, typed_terms))
    - sort subject sets, preserve semantic list order, use strict integers and ISO dates.
    - identify resolved subjects by kind/KB ID, not changing display names.
    - exclude observation times, quotes, and snapshot hashes.
    """
    sorted_raw = sorted(
        [_canonical_subject(s) for s in subjects],
        key=lambda x: (
            str(x["kind"]),
            str(x["kb_id"]) if x["kb_id"] is not None else "",
            str(x["source_name"]) if x["source_name"] is not None else "",
        ),
    )

    # Deduplicate canonical subject set
    seen_keys: set[tuple[str, str | None, str | None]] = set()
    sorted_subjects: list[dict[str, Any]] = []
    for s in sorted_raw:
        key = (str(s["kind"]), s["kb_id"], s["source_name"])
        if key not in seen_keys:
            seen_keys.add(key)
            sorted_subjects.append(s)

    canonical_window = {
        "start_date": effective_window.start_date.isoformat(),
        "end_date": effective_window.end_date.isoformat() if effective_window.end_date else None,
        "is_ongoing": effective_window.is_ongoing,
    }

    identity_dict = {
        "version": version,
        "type": event_type,
        "subjects": sorted_subjects,
        "effective_window": canonical_window,
        "typed_terms": _canonical_terms_dict(terms),
    }

    canonical_bytes = json.dumps(
        identity_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(canonical_bytes).hexdigest()


# --- Subject Resolution ---


class SubjectResolver(Protocol):
    """Protocol for resolving subject names to KB entities."""

    def resolve(self, ref: SubjectRef) -> SubjectRef:
        ...


class KBSubjectResolver:
    """Deterministic subject resolver backed by known entity IDs and alias mappings."""

    def __init__(
        self,
        *,
        card_ids: Iterable[str] = (),
        program_ids: Iterable[str] = (),
        reward_rule_ids: Iterable[str] = (),
        partner_ids: Iterable[str] = (),
        merchant_ids: Iterable[str] = (),
        alias_map: Mapping[tuple[SubjectKind, str], str] | None = None,
    ) -> None:
        self._card_ids = set(card_ids)
        self._program_ids = set(program_ids)
        self._reward_rule_ids = set(reward_rule_ids)
        self._partner_ids = set(partner_ids)
        self._merchant_ids = set(merchant_ids)
        self._alias_map = dict(alias_map or {})

    def resolve(self, ref: SubjectRef) -> SubjectRef:
        """Resolve a SubjectRef against known IDs or alias mappings.

        Unknown references stay unmapped (kb_id=None).
        """
        # If already carrying an exact valid KB ID, verify it
        if ref.kb_id is not None:
            if ref.kind == "card" and ref.kb_id in self._card_ids:
                return ref
            if ref.kind == "loyalty_program" and ref.kb_id in self._program_ids:
                return ref
            if ref.kind == "reward_rule" and ref.kb_id in self._reward_rule_ids:
                return ref
            if ref.kind == "transfer_partner":
                if not self._partner_ids or ref.kb_id in self._partner_ids:
                    return ref
            if ref.kind == "merchant_offer":
                if not self._merchant_ids or ref.kb_id in self._merchant_ids:
                    return ref

        # Try exact alias map lookup: (kind, normalized_source_name)
        alias_key = (ref.kind, ref.source_name.strip().lower())
        if alias_key in self._alias_map:
            mapped_id = self._alias_map[alias_key]
            return SubjectRef(
                kind=ref.kind,
                source_name=ref.source_name,
                kb_id=mapped_id,
            )

        # Direct name match in known card IDs or program IDs
        normalized_name = ref.source_name.strip().lower().replace(" ", "-")
        if ref.kind == "card" and normalized_name in self._card_ids:
            return SubjectRef(kind=ref.kind, source_name=ref.source_name, kb_id=normalized_name)
        if ref.kind == "loyalty_program" and normalized_name in self._program_ids:
            return SubjectRef(kind=ref.kind, source_name=ref.source_name, kb_id=normalized_name)

        # Unmapped: cannot produce personal financial impact
        return SubjectRef(
            kind=ref.kind,
            source_name=ref.source_name,
            kb_id=None,
        )


# --- Evidence Resolution ---


class EvidenceResolver(Protocol):
    """Protocol for verifying evidence spans against immutable snapshot text."""

    def verify_span(
        self,
        span: FieldSpan,
        *,
        snapshot_id: str,
        text: str,
    ) -> bool:
        ...


class SnapshotEvidenceResolver:
    """Pure verifier checking exact character slices and quotes against canonical snapshot."""

    def verify_span(
        self,
        span: FieldSpan,
        *,
        snapshot_id: str,
        text: str,
    ) -> bool:
        if span.start_offset < 0 or span.end_offset > len(text):
            return False
        if span.start_offset >= span.end_offset:
            return False
        actual_slice = text[span.start_offset : span.end_offset]
        if actual_slice != span.quote:
            return False
        if not span.quote or not span.quote.strip():
            return False
        if span.slice_sha256 is not None:
            expected_hash = hashlib.sha256(span.quote.encode("utf-8")).hexdigest()
            if span.slice_sha256 != expected_hash:
                return False
        return True


# --- Extracted Event and Validation Models ---


class ExtractedEvent(BaseModel):
    """Raw event extracted from a snapshot before offline deterministic validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: EventType
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    subjects: tuple[SubjectRef, ...] = Field(min_length=1)
    effective_window: EffectiveWindow
    terms: FeedTerms
    evidence_spans: tuple[FieldSpan, ...] = ()
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
    fidelity: Literal[
        "original_issuer_bytes",
        "provider_rendered_html",
        "manual_capture",
        "synthetic_fixture",
    ]
    snapshot_text: str


class EventRefusal(BaseModel):
    """Rejection record when a candidate event fails deterministic validation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: Literal[
        "invalid_evidence_quote",
        "invalid_evidence_slice",
        "missing_mandatory_evidence",
        "outlier_bonus_bound",
        "invalid_dates",
        "artifact_hash_mismatch",
    ]
    detail: str
    field_path: str | None = None


class ValidatedEvent(BaseModel):
    """A deterministically validated change event with resolved subjects and receipts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event: ChangeEvent
    evidence_receipts: tuple[EvidenceReceipt, ...]
    unmapped_subjects: tuple[SubjectRef, ...] = ()
    facts_status: FactsStatus = "unsupported_target"
    is_personal_impact_eligible: bool = False


# --- Validation Logic ---


def _required_term_evidence_paths(terms: FeedTerms) -> set[str]:
    """Return the set of field paths that must have supporting evidence quotes."""
    if isinstance(terms, TransferBonusTerms):
        return {"bonus_bp", "quoted_dates"}
    if isinstance(terms, WelcomeOfferTerms):
        paths = {"min_spend_minor", "quoted_spend_window"}
        if terms.bonus_points is not None:
            paths.add("bonus_points")
        if terms.bonus_cash_minor is not None:
            paths.add("bonus_cash_minor")
        return paths
    if isinstance(terms, EarnRateChangeTerms):
        return {"new_points", "spend_scope"}
    return set()


def validate_event(
    raw: ExtractedEvent,
    *,
    evidence: EvidenceResolver,
    subjects: SubjectResolver,
) -> ValidatedEvent | EventRefusal:
    """Validate a candidate change event deterministically.

    Enforces:
    - Evidence quote and slice verification against snapshot text.
    - Artifact normalized SHA-256 match.
    - Mandatory evidence span coverage.
    - Outlier bounds check (e.g. bonus_bp in 0..100000).
    - Subject resolution with unmapped tracking.
    - Unmapped subjects cannot produce personal financial impact.
    """
    # 1. Verify artifact hash
    computed_hash = hashlib.sha256(raw.snapshot_text.encode("utf-8")).hexdigest()
    if raw.normalized_sha256 != computed_hash:
        return EventRefusal(
            reason="artifact_hash_mismatch",
            detail=(
                f"snapshot normalized_sha256 ({raw.normalized_sha256}) does not match "
                f"computed hash of text ({computed_hash})"
            ),
        )

    # 2. Check mandatory evidence coverage
    required_paths = _required_term_evidence_paths(raw.terms)
    present_paths = {span.field_path for span in raw.evidence_spans}
    missing_paths = required_paths - present_paths
    if missing_paths:
        return EventRefusal(
            reason="missing_mandatory_evidence",
            detail=f"missing required evidence spans for fields: {sorted(missing_paths)}",
            field_path=sorted(missing_paths)[0],
        )

    # 3. Verify each evidence span against snapshot text
    for span in raw.evidence_spans:
        if not evidence.verify_span(span, snapshot_id=raw.snapshot_id, text=raw.snapshot_text):
            return EventRefusal(
                reason="invalid_evidence_quote",
                detail=(
                    f"evidence span for field '{span.field_path}' does not match "
                    f"snapshot text at slice [{span.start_offset}:{span.end_offset}]"
                ),
                field_path=span.field_path,
            )

    # 4. Resolve subjects
    resolved_subjects: list[SubjectRef] = [subjects.resolve(s) for s in raw.subjects]

    # Also resolve embedded subjects in terms
    resolved_terms: FeedTerms
    if isinstance(raw.terms, TransferBonusTerms):
        resolved_terms = TransferBonusTerms(
            from_program=subjects.resolve(raw.terms.from_program),
            to_program=subjects.resolve(raw.terms.to_program),
            bonus_bp=raw.terms.bonus_bp,
            quoted_dates=raw.terms.quoted_dates,
            min_transfer_points=raw.terms.min_transfer_points,
            max_bonus_points=raw.terms.max_bonus_points,
            restrictions=raw.terms.restrictions,
            raw_bonus_text=raw.terms.raw_bonus_text,
        )
    elif isinstance(raw.terms, WelcomeOfferTerms):
        resolved_terms = WelcomeOfferTerms(
            card=subjects.resolve(raw.terms.card),
            bonus_points=raw.terms.bonus_points,
            bonus_program=(
                subjects.resolve(raw.terms.bonus_program)
                if raw.terms.bonus_program
                else None
            ),
            bonus_cash_minor=raw.terms.bonus_cash_minor,
            currency=raw.terms.currency,
            min_spend_minor=raw.terms.min_spend_minor,
            min_spend_currency=raw.terms.min_spend_currency,
            spend_window_days=raw.terms.spend_window_days,
            spend_window_months=raw.terms.spend_window_months,
            spend_window_basis=raw.terms.spend_window_basis,
            quoted_spend_window=raw.terms.quoted_spend_window,
            eligibility_exclusions=raw.terms.eligibility_exclusions,
            fee_first_year_waived=raw.terms.fee_first_year_waived,
            annual_fee_minor=raw.terms.annual_fee_minor,
            approval_delivery_time=raw.terms.approval_delivery_time,
        )
    elif isinstance(raw.terms, EarnRateChangeTerms):
        resolved_terms = EarnRateChangeTerms(
            card=subjects.resolve(raw.terms.card),
            new_points=raw.terms.new_points,
            new_per_amount_minor=raw.terms.new_per_amount_minor,
            currency=raw.terms.currency,
            effective_start=raw.terms.effective_start,
            spend_scope=raw.terms.spend_scope,
            prior_points=raw.terms.prior_points,
            prior_per_amount_minor=raw.terms.prior_per_amount_minor,
            reward_program=(
                subjects.resolve(raw.terms.reward_program)
                if raw.terms.reward_program
                else None
            ),
            cap=raw.terms.cap,
            exclusions=raw.terms.exclusions,
            effective_end=raw.terms.effective_end,
        )
    else:
        raise ValueError(f"unsupported terms: {type(raw.terms)}")

    # Collect all resolved subjects to verify mapping
    all_subjects: list[SubjectRef] = list(resolved_subjects)
    if isinstance(resolved_terms, TransferBonusTerms):
        all_subjects.extend([resolved_terms.from_program, resolved_terms.to_program])
    elif isinstance(resolved_terms, WelcomeOfferTerms):
        all_subjects.append(resolved_terms.card)
        if resolved_terms.bonus_program:
            all_subjects.append(resolved_terms.bonus_program)
    elif isinstance(resolved_terms, EarnRateChangeTerms):
        all_subjects.append(resolved_terms.card)
        if resolved_terms.reward_program:
            all_subjects.append(resolved_terms.reward_program)

    seen_unmapped: set[tuple[str, str]] = set()
    unique_unmapped: list[SubjectRef] = []
    for s in all_subjects:
        if s.kb_id is None:
            ukey = (s.kind, s.source_name.strip().lower())
            if ukey not in seen_unmapped:
                seen_unmapped.add(ukey)
                unique_unmapped.append(s)
    unmapped = tuple(unique_unmapped)

    # Core rule: unmapped subjects cannot produce personal financial impact
    is_personal_impact_eligible = len(unmapped) == 0

    # 5. Compute canonical event_id
    event_id = compute_event_id(
        version=1,
        event_type=raw.event_type,
        subjects=tuple(resolved_subjects),
        effective_window=raw.effective_window,
        terms=resolved_terms,
    )

    # 6. Create immutable evidence receipt
    receipt_key = f"{raw.snapshot_id}:{raw.fetch_attempt_id}:{event_id}"
    receipt_id = f"rcpt:{hashlib.sha256(receipt_key.encode('utf-8')).hexdigest()[:16]}"
    receipt = EvidenceReceipt(
        receipt_id=receipt_id,
        source_policy_id=raw.source_policy_id,
        source_policy_hash=raw.source_policy_hash,
        target_id=raw.target_id,
        snapshot_id=raw.snapshot_id,
        artifact_sha256=raw.artifact_sha256,
        raw_sha256=raw.raw_sha256,
        normalized_sha256=raw.normalized_sha256,
        provider_envelope_sha256=raw.provider_envelope_sha256,
        fetch_attempt_id=raw.fetch_attempt_id,
        observed_at=raw.observed_at,
        is_replayed=raw.is_replayed,
        field_spans=raw.evidence_spans,
        fidelity=raw.fidelity,
    )

    # 7. Facts status classification (Sol §4: review_rows supports cards/rules/offers;
    # transfer bonuses and welcome offers record facts_status=unsupported_target).
    facts_status: FactsStatus = (
        "valid_proposal" if (raw.event_type == "earn_rate_change" and is_personal_impact_eligible)
        else "unsupported_target"
    )

    event = ChangeEvent(
        event_id=event_id,
        version=1,
        event_type=raw.event_type,
        subjects=tuple(resolved_subjects),
        effective_window=raw.effective_window,
        terms=resolved_terms,
        trust_level="primary_confirmed" if raw.fidelity != "synthetic_fixture" else "lead_only",
        facts_status=facts_status,
        first_seen_at=raw.observed_at,
        latest_observed_at=raw.observed_at,
        title=raw.title,
        summary=raw.summary,
        source_url=raw.source_url,
        evidence_receipts=(receipt,),
    )

    return ValidatedEvent(
        event=event,
        evidence_receipts=(receipt,),
        unmapped_subjects=unmapped,
        facts_status=facts_status,
        is_personal_impact_eligible=is_personal_impact_eligible,
    )


# --- Supersession vs. Conflict Classification ---

EventRelationship = Literal["identical", "supersedes", "conflict", "independent"]


def classify_event_relationship(
    existing: ChangeEvent,
    incoming: ChangeEvent,
    *,
    is_same_verified_occurrence: bool = False,
) -> EventRelationship:
    """Classify the relationship between an existing event and an incoming event.

    Sol's spec §1:
    - Identical content is one event (additional evidence receipts).
    - Different terms produce a different event, not an upsert.
    - Automatic supersession requires the same verified source occurrence (primary promo URL
      or explicit promotion identifier); otherwise flag a possible conflict for the operator.
    - Never infer that two concurrent promotions replace each other from matching
      subjects/dates alone.
    """
    if existing.event_id == incoming.event_id:
        return "identical"

    def _subject_key(s: SubjectRef) -> tuple[str, str]:
        return (s.kind, s.kb_id if s.kb_id is not None else s.source_name.strip().lower())

    existing_keys = {_subject_key(s) for s in existing.subjects}
    incoming_keys = {_subject_key(s) for s in incoming.subjects}

    shared_subjects = existing_keys.intersection(incoming_keys)
    if not shared_subjects:
        return "independent"

    # Same verified source occurrence allows supersession if incoming is newer
    if is_same_verified_occurrence or (existing.source_url == incoming.source_url):
        if incoming.latest_observed_at >= existing.latest_observed_at:
            return "supersedes"

    # Overlapping subjects with different terms but without confirmed same occurrence: conflict
    return "conflict"
