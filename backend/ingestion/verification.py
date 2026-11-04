"""D1 (field-level verification) and D2 (manual-origin confirmation), as pure functions.

**D1.** A row may clear ``needs_verification`` only when *every non-identity fact field* has
valid quoted evidence from an approved decision: the decision being applied now, or an earlier
applied decision whose evidence is still applicable. This module only decides; it never writes.

* Identity is ``id`` alone. Provenance is bookkeeping about the row, and neither counts as
  factual evidence or as a field that needs it. Nothing else is exempt: ``issuer``, ``network``,
  ``country`` and ``name`` are facts too (the owner's decision is that fields that are hard to
  evidence do not weaken D1).
* A field whose value is ``None`` asserts nothing, so it needs no evidence (an unknown optional
  value is not a claim). Every field holding a value does.
* Earlier evidence is applicable only while the field *still holds the value it supported*.
  When the value changes and nothing new supports it, the earlier evidence is **invalidated**
  and the field is reported as stale. The decision is never "mostly evidenced".

**D2.** A manual capture can count as ``official_page``/``tnc_pdf`` only when a named curator
explicitly confirmed its origin for *that capture* (bound to the snapshot and its hashes), the
capture's URL is on the issuer domain of the source policy, and the policy is not an aggregator.
A URL appearing in the captured text, or in a target, confirms nothing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

from ingestion.canonical import is_pdf_media_type
from ingestion.config_loaders import host_of, is_aggregator_host
from ingestion.contracts import PageKind, SnapshotBundle, SourcePolicyRecord, WatchTarget
from ingestion.preflight import SourcePreflight
from ingestion.review_rows import flatten_row


def canonical_value(value: Any) -> str:
    """One stable text form of a field value, so evidence can be matched to what it supported."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def required_fact_paths(row: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        path
        for path, value in sorted(flatten_row(dict(row)).items())
        if path != "id" and not path.startswith("provenance.") and value is not None
    )


class LedgerEvidence(BaseModel):
    """A durable record that an applied, approved decision quoted evidence for one field value."""

    apply_id: str
    table_name: str
    row_id: str
    field_path: str
    value_json: str
    proposal_id: str
    decision_id: str
    reviewer_id: str
    snapshot_id: str
    quote: str


class RowVerification(BaseModel):
    satisfied: bool
    required: tuple[str, ...]
    evidenced_now: tuple[str, ...]
    evidenced_earlier: tuple[str, ...]
    missing: tuple[str, ...]
    stale: tuple[str, ...]


def evaluate_row(
    row: Mapping[str, Any],
    *,
    now_evidence: Mapping[str, str],
    earlier: Sequence[LedgerEvidence],
) -> RowVerification:
    """D1 for one row. ``now_evidence`` maps path -> canonical value the current decision quoted."""
    flat = flatten_row(dict(row))
    by_path: dict[str, list[LedgerEvidence]] = {}
    for item in earlier:
        by_path.setdefault(item.field_path, []).append(item)
    required = required_fact_paths(row)
    now: list[str] = []
    before: list[str] = []
    missing: list[str] = []
    stale: list[str] = []
    for path in required:
        value = canonical_value(flat[path])
        if now_evidence.get(path) == value:
            now.append(path)
        elif any(item.value_json == value for item in by_path.get(path, ())):
            before.append(path)
        elif path in by_path:
            stale.append(path)  # earlier evidence exists but no longer supports this value
        else:
            missing.append(path)
    return RowVerification(
        satisfied=not missing and not stale,
        required=required,
        evidenced_now=tuple(now),
        evidenced_earlier=tuple(before),
        missing=tuple(missing),
        stale=tuple(stale),
    )


class OriginConfirmation(BaseModel):
    """A named curator's statement that a manual capture really is the issuer's document."""

    confirmation_id: str
    snapshot_id: str
    raw_sha256: str
    normalized_sha256: str
    target_id: str
    policy_id: str
    canonical_url: str
    document_class: Literal["card_page", "offer_page", "tnc_pdf"]
    curator_id: str
    confirmed_at: AwareDatetime
    statement: str = Field(min_length=10, max_length=1000)


def confirmation_id(snapshot_id: str, document_class: str) -> str:
    return f"origin:{snapshot_id}:{document_class}"


def confirmation_problems(
    confirmation: OriginConfirmation,
    *,
    snapshot: SnapshotBundle,
    target: WatchTarget,
    policy: SourcePolicyRecord,
    extra_aggregators: Sequence[str] = (),
) -> list[str]:
    """Why a confirmation does not (or no longer does) establish an official origin."""
    problems: list[str] = []
    if (
        confirmation.snapshot_id != snapshot.snapshot_id
        or confirmation.raw_sha256 != snapshot.raw_sha256
        or confirmation.normalized_sha256 != snapshot.normalized_sha256
    ):
        problems.append("the confirmation is for a different capture")
    if target.target_id != snapshot.target_id or confirmation.target_id != target.target_id:
        problems.append("the capture does not belong to the confirmed target")
    if target.page_kind is not PageKind.MANUAL_CAPTURE:
        problems.append("only a manual capture needs (or can have) an origin confirmation")
    if confirmation.policy_id != policy.policy_id or target.source_policy_id != policy.policy_id:
        problems.append("the confirmation names a different source policy")
    if confirmation.canonical_url != target.canonical_url:
        problems.append("the confirmed URL is not the target's URL")
    host = host_of(target.canonical_url)
    if is_aggregator_host(host, extra_domains=extra_aggregators) or is_aggregator_host(
        policy.domain, extra_domains=extra_aggregators
    ):
        problems.append("an aggregator is never an issuer origin")
    try:
        SourcePreflight().check_redirect(target.canonical_url, target.canonical_url, policy)
    except (ValueError, UnicodeError):
        problems.append(f"the URL is not on the issuer domain {policy.domain} of its source policy")
    if confirmation.document_class not in policy.allowed_page_classes:
        problems.append(
            f"the source policy does not allow page class {confirmation.document_class!r}"
        )
    is_pdf = is_pdf_media_type(snapshot.raw_artifact.media_type)
    if is_pdf != (confirmation.document_class == "tnc_pdf"):
        problems.append("the confirmed document class does not match the capture's format")
    return problems


def new_confirmation(
    *,
    snapshot: SnapshotBundle,
    target: WatchTarget,
    policy: SourcePolicyRecord,
    document_class: Literal["card_page", "offer_page", "tnc_pdf"],
    curator_id: str,
    statement: str,
    now: datetime,
) -> OriginConfirmation:
    return OriginConfirmation(
        confirmation_id=confirmation_id(snapshot.snapshot_id, document_class),
        snapshot_id=snapshot.snapshot_id,
        raw_sha256=snapshot.raw_sha256,
        normalized_sha256=snapshot.normalized_sha256,
        target_id=target.target_id,
        policy_id=policy.policy_id,
        canonical_url=target.canonical_url,
        document_class=document_class,
        curator_id=curator_id,
        confirmed_at=now,
        statement=statement,
    )
