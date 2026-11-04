"""Curator-authored capture staging: a local capture becomes validated, reviewable proposals.

This is the operator path that replaces a one-off staging script. An operator supplies a local
capture (HTML, text or PDF they saved themselves), the source policy and watch target that
describe where it came from, and an extraction file in which *they* quote the evidence for each
value. The existing pipeline does the rest:

    ManualUploadBackend -> SnapshotService -> FinancialExtractor -> proposal storage

The extraction is labelled ``curator-authored``. It reaches ``FinancialExtractor`` through the
scripted-client seam, so the extractor's own validation (typed contract, quote verification,
deterministic parsing, schema check) is exactly what runs for a model-authored extraction. There
is no model call, no network access and no new financial parsing here: values are parsed by
``ingestion.parsing`` and quotes are verified by ``ingestion.evidence``.

Batch semantics (also reported in every outcome):

* **Validation is all-or-nothing.** Every record is validated on its own and then every row as
  a whole before any proposal is written. A refusal on any record stores no proposal.
* **Writes are per-record and idempotent**: source policy, watch target, snapshot, then one
  proposal per row. This is *not* one database transaction. A run that is interrupted after
  some writes is completed by running the same command again; nothing is duplicated.
* A refused run still keeps the capture evidence (policy, target, snapshot) it had already
  stored: those are immutable records of what the curator supplied, and reusing them lets a
  corrected extraction file be staged against the same snapshot.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agents.llm import ScriptedLLMClient
from ingestion.artifacts import ContentAddressedStore
from ingestion.canonical import _normalize_lines, is_pdf_media_type
from ingestion.config_loaders import (
    ConfigValidationError,
    _validation_issues,
    host_of,
    is_aggregator_host,
    normalize_host,
    read_structured,
)
from ingestion.contracts import (
    EvidenceSpan,
    FetchAttempt,
    FetchRequest,
    PageKind,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.diff import diff_text
from ingestion.extraction import FinancialExtractor
from ingestion.extraction_types import ExtractionResponse
from ingestion.fetch import ManualUploadBackend
from ingestion.insert_validation import (
    check_field_evidence,
    draft_provenance,
    type_guide,
    validate_insert,
)
from ingestion.parsing import UnresolvedValueError, parse_field_value
from ingestion.pdf_isolation import PdfPageOutOfRange, get_default_runner
from ingestion.preflight import SourcePreflight
from ingestion.review_rows import SUPPORTED_TABLES, SeedRowError, SeedRowSource
from ingestion.snapshots import SnapshotService
from ingestion.storage import (
    ConflictingWriteError,
    FinancialIngestionStore,
    IdempotencyConflictError,
)
from ingestion.validation import (
    TARGET_MODELS,
    ProposalValidationError,
    _get,
    _same_value,
    _set,
    canonical_row_hash,
    validate_extraction,
)

EXTRACTION_SCHEMA = "tripwise.curator-extraction/v1"
EXTRACTOR_VERSION = "curator-authored-v1"
MAX_QUOTE_LOCATIONS = 5
ATOMICITY = (
    "Validation is all-or-nothing: every record and row is checked before any proposal is "
    "written, and a refusal stores no proposal. Writes are per-record and idempotent (source "
    "policy, watch target, snapshot, then one proposal per row), not one database transaction; "
    "re-running the same command completes an interrupted run without duplicating anything."
)
_DOCUMENT_CLASSES = {PageKind.CARD_PAGE, PageKind.OFFER_PAGE, PageKind.TNC_PDF}


class StageRefusalCode(StrEnum):
    UNKNOWN_CURATOR = "unknown_curator"
    SOURCE_NOT_ALLOWED = "source_not_allowed"
    TARGET_INVALID = "target_invalid"
    DOCUMENT_CLASS_NOT_ALLOWED = "document_class_not_allowed"
    DOCUMENT_CLASS_MISMATCH = "document_class_mismatch"
    POLICY_CONFLICT = "policy_conflict"
    TARGET_CONFLICT = "target_conflict"
    CAPTURE_REJECTED = "capture_rejected"
    UNSUPPORTED_TABLE = "unsupported_table"
    ROW_NOT_FOUND = "row_not_found"
    ROW_NOT_BOUND = "row_not_bound"
    DUPLICATE_FIELD_CONFLICT = "duplicate_field_conflict"
    LOCATOR_CONFLICT = "locator_conflict"
    QUOTE_NOT_FOUND = "quote_not_found"
    QUOTE_AMBIGUOUS = "quote_ambiguous"
    OFFSET_MISMATCH = "offset_mismatch"
    OCCURRENCE_OUT_OF_RANGE = "occurrence_out_of_range"
    PAGE_REQUIRED = "page_required"
    PAGE_NOT_APPLICABLE = "page_not_applicable"
    PAGE_OFFSET_MISMATCH = "page_offset_mismatch"
    PAGE_MAP_UNAVAILABLE = "page_map_unavailable"
    FIELD_PATH_INVALID = "field_path_invalid"
    PROVENANCE_FIELD_FORBIDDEN = "provenance_field_forbidden"
    VALUE_UNRESOLVED = "value_unresolved"
    VALUE_NOT_SUPPORTED_BY_QUOTE = "value_not_supported_by_quote"
    EVIDENCE_REJECTED = "evidence_rejected"
    ROW_SCHEMA_INVALID = "row_schema_invalid"
    VALIDATION_REFUSED = "validation_refused"
    PROPOSAL_CONFLICT = "proposal_conflict"
    INSERT_ID_EXISTS = "insert_id_exists"
    INSERT_INVALID = "insert_invalid"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    TEMPLATE_CONFLICTS_WITH_EVIDENCE = "template_conflicts_with_evidence"


class StageRefusal(BaseModel):
    """One reason a record, row or the whole run was refused."""

    code: StageRefusalCode
    message: str
    record_index: int | None = None
    table: str | None = None
    row_id: str | None = None
    field_path: str | None = None


class ExtractionRecord(BaseModel):
    """One curator-authored evidence record: a value and the exact quote that supports it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    table: str = Field(min_length=1)
    id: str = Field(min_length=1)
    field_path: str = Field(min_length=1)
    raw_value: str | int | float
    quote: str = Field(min_length=1)
    occurrence: int | None = Field(default=None, ge=1)
    offset: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)

    @field_validator("raw_value", mode="before")
    @classmethod
    def _not_boolean(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("raw_value must be the source notation, not a boolean")
        return value


class InsertRow(BaseModel):
    """A row the curator proposes to add: values they supply, to be overlaid by quoted evidence.

    ``row`` holds the values the curator types in. Every value in it is **unevidenced** unless a
    record quotes it. ``id`` and ``provenance`` are never supplied here: the id is the key and
    the provenance is built by code as an unverified draft.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    table: str = Field(min_length=1)
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    row: dict[str, Any]

    @field_validator("row")
    @classmethod
    def _no_identity_or_provenance(cls, value: dict[str, Any]) -> dict[str, Any]:
        if {"id", "provenance"} & set(value):
            raise ValueError(
                "row must not contain id or provenance: the key is `id`, and a draft's "
                "provenance is set by code"
            )
        return value


class CuratorExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal["tripwise.curator-extraction/v1"] = Field(alias="schema")
    curator_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")
    change_summary: str | None = Field(default=None, min_length=1, max_length=1500)
    records: tuple[ExtractionRecord, ...] = Field(min_length=1, max_length=500)
    inserts: tuple[InsertRow, ...] = Field(default=(), max_length=50)


def load_curator_extraction(path: Path) -> CuratorExtraction:
    """Read and validate the curator's extraction file (JSON or YAML)."""
    raw = read_structured(path)
    try:
        return CuratorExtraction.model_validate(raw)
    except ValidationError as error:
        raise ConfigValidationError(path, _validation_issues(error, "extraction")) from error


@dataclass(frozen=True)
class StageLimits:
    max_bytes: int = 10_000_000
    max_pages: int = 100
    timeout_seconds: int = 60


class StagedProposal(BaseModel):
    intent: Literal["update", "insert"] = "update"
    proposal_id: str
    target_table: str
    target_id: str
    state: Literal["stored", "already_stored"]
    review_status: str
    version: int
    field_paths: tuple[str, ...]
    finding_codes: tuple[str, ...]


class StageOutcome(BaseModel):
    status: Literal["staged", "refused"]
    extraction: Literal["curator-authored"] = "curator-authored"
    llm_calls: int = 0
    network_calls: int = 0
    curator_id: str | None = None
    policy_id: str | None = None
    policy_state: Literal["stored", "already_stored"] | None = None
    target_id: str | None = None
    target_state: Literal["stored", "already_stored"] | None = None
    snapshot_id: str | None = None
    snapshot_state: Literal["stored", "already_stored"] | None = None
    artifact_kind: Literal["html", "pdf", "text"] | None = None
    raw_sha256: str | None = None
    normalized_sha256: str | None = None
    proposals: tuple[StagedProposal, ...] = ()
    refusals: tuple[StageRefusal, ...] = ()
    atomicity: str = ATOMICITY


@dataclass(frozen=True)
class _Located:
    start: int
    end: int


def _refusal(
    code: StageRefusalCode,
    message: str,
    *,
    index: int | None = None,
    record: ExtractionRecord | None = None,
    table: str | None = None,
    row_id: str | None = None,
    field_path: str | None = None,
) -> StageRefusal:
    return StageRefusal(
        code=code,
        message=message,
        record_index=index,
        table=record.table if record is not None else table,
        row_id=record.id if record is not None else row_id,
        field_path=record.field_path if record is not None else field_path,
    )


def _occurrences(text: str, quote: str) -> list[int]:
    found: list[int] = []
    position = text.find(quote)
    while position != -1 and len(found) < 1000:
        found.append(position)
        position = text.find(quote, position + 1)
    return found


def _near_match(text: str, quote: str) -> str | None:
    """The exact canonical text a whitespace- or NFKC-different quote was probably aiming at."""
    wanted = " ".join(unicodedata.normalize("NFKC", quote).split())
    if not wanted:
        return None
    chars: list[str] = []
    origin: list[int] = []
    previous_space = False
    for index, char in enumerate(text):
        if char.isspace():
            if previous_space:
                continue
            chars.append(" ")
            previous_space = True
        else:
            chars.append(char)
            previous_space = False
        origin.append(index)
    position = "".join(chars).find(wanted)
    if position < 0:
        return None
    start, end = origin[position], origin[position + len(wanted) - 1] + 1
    return text[start:end][:240]


def _context(text: str, start: int, length: int) -> str:
    lo, hi = max(0, start - 25), min(len(text), start + length + 25)
    return " ".join(text[lo:hi].split())


PageSegments = dict[int, tuple[int, int]]


def _pdf_page_segments(
    data: bytes, canonical: str, *, up_to: int, max_chars: int
) -> PageSegments | None:
    """Where each PDF page's text sits inside the stored canonical text (1-based pages).

    The canonical text is the pages' text joined by newlines and normalized line by line, so
    normalizing each page the same way and walking forward reproduces it exactly. If that ever
    fails to hold, return ``None`` instead of guessing a page.
    """
    runner = get_default_runner()
    segments: PageSegments = {}
    cursor = 0
    for number in range(1, up_to + 1):
        try:
            normalized = _normalize_lines(
                runner.page_text(data, page_number=number), max_chars=max_chars
            )
        except PdfPageOutOfRange:
            break
        except Exception:  # a page that cannot be read or normalized cannot be mapped
            return None
        if not normalized:
            continue  # a blank page adds no text
        if canonical[cursor : cursor + len(normalized)] != normalized:
            return None
        segments[number] = (cursor, cursor + len(normalized))
        cursor += len(normalized) + 1
    return segments


def _page_of(segments: PageSegments | None, offset: int) -> int | None:
    if segments is None:
        return None
    for number, (start, end) in segments.items():
        if start <= offset < end:
            return number
    return None


def _locate(
    text: str,
    record: ExtractionRecord,
    index: int,
    segments: PageSegments | None = None,
) -> _Located | StageRefusal:
    """Find the quote in the stored canonical text; ambiguity is refused, never guessed."""
    quote = record.quote
    if record.occurrence is not None and record.offset is not None:
        return _refusal(
            StageRefusalCode.LOCATOR_CONFLICT,
            "give either occurrence or offset, not both",
            index=index,
            record=record,
        )
    if record.offset is not None:
        if text[record.offset : record.offset + len(quote)] != quote:
            return _refusal(
                StageRefusalCode.OFFSET_MISMATCH,
                f"the stored text at offset {record.offset} is not the quote",
                index=index,
                record=record,
            )
        return _Located(record.offset, record.offset + len(quote))
    positions = _occurrences(text, quote)
    if not positions:
        hint = _near_match(text, quote)
        suffix = f" Did you mean the exact stored text {hint!r}?" if hint else ""
        return _refusal(
            StageRefusalCode.QUOTE_NOT_FOUND,
            "the quote is not an exact substring of the stored canonical text." + suffix,
            index=index,
            record=record,
        )
    if record.occurrence is not None:
        if record.occurrence > len(positions):
            return _refusal(
                StageRefusalCode.OCCURRENCE_OUT_OF_RANGE,
                f"occurrence {record.occurrence} requested but the quote appears "
                f"{len(positions)} time(s)",
                index=index,
                record=record,
            )
        start = positions[record.occurrence - 1]
        return _Located(start, start + len(quote))
    if len(positions) > 1:

        def where(start: int) -> str:
            page = _page_of(segments, start)
            return f" (page {page})" if page is not None else ""

        shown = "; ".join(
            f"#{number} @{start}{where(start)}: …{_context(text, start, len(quote))}…"
            for number, start in enumerate(positions[:MAX_QUOTE_LOCATIONS], start=1)
        )
        return _refusal(
            StageRefusalCode.QUOTE_AMBIGUOUS,
            f"the quote appears {len(positions)} times; set occurrence (1-based) or offset. "
            + shown,
            index=index,
            record=record,
        )
    return _Located(positions[0], positions[0] + len(quote))


def _classify(message: str) -> StageRefusalCode:
    if "unresolved value" in message:
        return StageRefusalCode.VALUE_UNRESOLVED
    if "does not support the proposed value" in message:
        return StageRefusalCode.VALUE_NOT_SUPPORTED_BY_QUOTE
    if message.startswith("invalid evidence"):
        return StageRefusalCode.EVIDENCE_REJECTED
    if "field path" in message or "target identity is not an extractable" in message:
        return StageRefusalCode.FIELD_PATH_INVALID
    if "cannot change provenance" in message:
        return StageRefusalCode.PROVENANCE_FIELD_FORBIDDEN
    if "failed the target schema" in message:
        return StageRefusalCode.ROW_SCHEMA_INVALID
    return StageRefusalCode.VALIDATION_REFUSED


def _artifact_kind(snapshot: SnapshotBundle) -> Literal["html", "pdf", "text"]:
    media = snapshot.raw_artifact.media_type
    if is_pdf_media_type(media):
        return "pdf"
    return "html" if media.split(";", 1)[0].strip().lower().startswith("text/html") else "text"


def _event_id(
    *,
    snapshot: SnapshotBundle,
    table: str,
    row_id: str,
    current_row_hash: str,
    curator_id: str,
    summary: str,
    fields: dict[str, tuple[str, list[tuple[int, int, int | None]]]],
) -> str:
    """The idempotency key covers the extraction itself, which FI2's request fingerprint omits.

    Without this, re-staging a *different* extraction under the same event id would silently
    return the first proposal. With it, identical input replays and different input is a
    distinct request that collides on the proposal id and is refused as a conflict.
    """
    payload = json.dumps(
        {
            "snapshot": snapshot.snapshot_id,
            "table": table,
            "row": row_id,
            "row_hash": current_row_hash,
            "curator": curator_id,
            "summary": summary,
            "fields": {path: [value, spans] for path, (value, spans) in sorted(fields.items())},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "stage-" + hashlib.sha256(payload.encode()).hexdigest()[:32]


def _response(
    *,
    table: str,
    row_id: str,
    proposed_row: dict[str, Any],
    fields: list[dict[str, Any]],
    summary: str,
) -> ExtractionResponse:
    return ExtractionResponse.model_validate(
        {
            "target_table": table,
            "target_id": row_id,
            "proposed_row": proposed_row,
            "fields": fields,
            "change_summary": summary[:2000],
            "extractor_confidence": 0.0,
        }
    )


def _present(row: dict[str, Any], path: str) -> Any:
    """The value at a dotted path, or None when any part of it is absent."""
    current: Any = row
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_creating(row: dict[str, Any], path: str, value: Any) -> None:
    """Set a dotted path, creating intermediate groups: an inserted row starts incomplete."""
    parts = path.split(".")
    current = row
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _bound(table: str, row_id: str, target: WatchTarget) -> bool:
    return row_id in target.target_fact_ids or f"{table}:{row_id}" in target.target_fact_ids


def _precheck(
    *,
    store: FinancialIngestionStore,
    policy: SourcePolicyRecord,
    target: WatchTarget,
    extraction: CuratorExtraction,
    document_class: PageKind,
    aggregator_domains: Iterable[str],
) -> list[StageRefusal]:
    """Everything that can be refused before any file is read or any record is written."""
    refusals: list[StageRefusal] = []
    if store.get_curator(extraction.curator_id) is None:
        refusals.append(
            _refusal(
                StageRefusalCode.UNKNOWN_CURATOR,
                f"curator {extraction.curator_id!r} is not registered; run add-curator first",
            )
        )
    extra = tuple(aggregator_domains)
    for host in (normalize_host(policy.domain), host_of(target.canonical_url)):
        if is_aggregator_host(host, extra_domains=extra):
            refusals.append(
                _refusal(
                    StageRefusalCode.SOURCE_NOT_ALLOWED,
                    f"{host} is an aggregator; financial facts come only from issuer evidence",
                )
            )
            break
    if target.source_policy_id != policy.policy_id:
        refusals.append(
            _refusal(
                StageRefusalCode.TARGET_INVALID,
                f"the watch target names policy {target.source_policy_id!r} but the supplied "
                f"policy is {policy.policy_id!r}",
            )
        )
    if (
        target.page_kind is not PageKind.MANUAL_CAPTURE
        or target.preferred_backend != "manual"
        or not target.manual_only
    ):
        refusals.append(
            _refusal(
                StageRefusalCode.TARGET_INVALID,
                "stage-capture needs a manual target: page_kind manual_capture, backend "
                "'manual' and manual_only true, so review keeps the capture marked as manual",
            )
        )
    if target.promoted_from_candidate_id is not None:
        lead = store.get_discovery_candidate(target.promoted_from_candidate_id)
        if lead is None:
            refusals.append(
                _refusal(
                    StageRefusalCode.TARGET_INVALID,
                    f"the target was promoted from lead {target.promoted_from_candidate_id!r}, "
                    "which is not in this data directory; file it with add-lead first",
                )
            )
        elif lead.issuer_url_to_verify != target.canonical_url:
            refusals.append(
                _refusal(
                    StageRefusalCode.TARGET_INVALID,
                    "a promoted target must point at exactly the issuer URL its lead named",
                )
            )
    if target.status != "active":
        refusals.append(
            _refusal(StageRefusalCode.TARGET_INVALID, f"watch target is {target.status}")
        )
    if document_class not in _DOCUMENT_CLASSES:
        refusals.append(
            _refusal(
                StageRefusalCode.DOCUMENT_CLASS_NOT_ALLOWED,
                "document class must be card_page, offer_page or tnc_pdf",
            )
        )
    elif document_class.value not in policy.allowed_page_classes:
        refusals.append(
            _refusal(
                StageRefusalCode.DOCUMENT_CLASS_NOT_ALLOWED,
                f"policy {policy.policy_id!r} does not allow page class "
                f"{document_class.value!r} (allowed: {list(policy.allowed_page_classes)})",
            )
        )
    try:
        SourcePreflight().check_redirect(target.canonical_url, target.canonical_url, policy)
    except (ValueError, UnicodeError) as error:
        refusals.append(
            _refusal(
                StageRefusalCode.SOURCE_NOT_ALLOWED,
                f"the target URL is outside the approved source domain: {error}",
            )
        )
    stored_policy = store.get_source_policy(policy.policy_id)
    if stored_policy is not None and stored_policy != policy:
        refusals.append(
            _refusal(
                StageRefusalCode.POLICY_CONFLICT,
                f"a different policy is already stored as {policy.policy_id!r}; stored "
                "records are immutable, so use a new policy_id",
            )
        )
    stored_target = store.get_watch_target(target.target_id)
    if stored_target is not None and stored_target != target:
        refusals.append(
            _refusal(
                StageRefusalCode.TARGET_CONFLICT,
                f"a different watch target is already stored as {target.target_id!r}; use a "
                "new target_id",
            )
        )
    return refusals


def stage_capture(
    *,
    store: FinancialIngestionStore,
    artifacts: ContentAddressedStore,
    seeds_dir: Path,
    capture_path: Path,
    policy: SourcePolicyRecord,
    target: WatchTarget,
    extraction: CuratorExtraction,
    document_class: PageKind,
    now: Callable[[], datetime],
    limits: StageLimits | None = None,
    aggregator_domains: Iterable[str] = (),
) -> StageOutcome:
    """Stage one local capture and its curator-authored extraction. See the module docstring."""
    limits = limits or StageLimits()
    base = StageOutcome(
        status="refused",
        curator_id=extraction.curator_id,
        policy_id=policy.policy_id,
        target_id=target.target_id,
    )

    def refused(items: Iterable[StageRefusal], **known: Any) -> StageOutcome:
        return base.model_copy(update={"refusals": tuple(items), **known})

    # --- 1. Pure checks of the supplied files, the rows they name, and the stored state. -----
    refusals = _precheck(
        store=store,
        policy=policy,
        target=target,
        extraction=extraction,
        document_class=document_class,
        aggregator_domains=aggregator_domains,
    )
    rows = SeedRowSource(seeds_dir)
    current: dict[tuple[str, str], dict[str, Any]] = {}
    insert_specs: dict[tuple[str, str], InsertRow] = {}
    existing_ids: dict[str, set[str]] = {}
    for spec in extraction.inserts:
        key = (spec.table, spec.id)
        if key in insert_specs:
            refusals.append(
                _refusal(
                    StageRefusalCode.INSERT_INVALID,
                    "the same row is declared twice in inserts",
                    table=spec.table,
                    row_id=spec.id,
                )
            )
            continue
        if spec.table not in SUPPORTED_TABLES:
            refusals.append(
                _refusal(
                    StageRefusalCode.UNSUPPORTED_TABLE,
                    f"unsupported table {spec.table!r}; supported: {sorted(SUPPORTED_TABLES)}",
                    table=spec.table,
                    row_id=spec.id,
                )
            )
            continue
        if spec.table not in existing_ids:
            try:
                existing_ids[spec.table] = {str(r["id"]) for r in rows.table_rows(spec.table)}
            except SeedRowError as error:
                refusals.append(
                    _refusal(
                        StageRefusalCode.VALIDATION_REFUSED,
                        str(error),
                        table=spec.table,
                        row_id=spec.id,
                    )
                )
                continue
        if spec.id in existing_ids[spec.table]:
            refusals.append(
                _refusal(
                    StageRefusalCode.INSERT_ID_EXISTS,
                    f"a {spec.table} row with id {spec.id!r} already exists; an insert never "
                    "merges into or replaces an existing row (use an update for that)",
                    table=spec.table,
                    row_id=spec.id,
                )
            )
            continue
        if not _bound(spec.table, spec.id, target):
            refusals.append(
                _refusal(
                    StageRefusalCode.ROW_NOT_BOUND,
                    f"the watch target {target.target_id!r} does not list {spec.id!r} in "
                    "target_fact_ids (use the id or '<table>:<id>')",
                    table=spec.table,
                    row_id=spec.id,
                )
            )
            continue
        insert_specs[key] = spec
    for position, record in enumerate(extraction.records):
        key = (record.table, record.id)
        if key in current or key in insert_specs:
            continue
        if record.table not in SUPPORTED_TABLES:
            refusals.append(
                _refusal(
                    StageRefusalCode.UNSUPPORTED_TABLE,
                    f"unsupported table {record.table!r}; supported: {sorted(SUPPORTED_TABLES)}",
                    index=position,
                    record=record,
                )
            )
            continue
        try:
            current[key] = rows.current_row(record.table, record.id)
        except SeedRowError as error:
            refusals.append(
                _refusal(StageRefusalCode.ROW_NOT_FOUND, str(error), index=position, record=record)
            )
            continue
        if not _bound(record.table, record.id, target):
            refusals.append(
                _refusal(
                    StageRefusalCode.ROW_NOT_BOUND,
                    f"the watch target {target.target_id!r} does not list {record.id!r} in "
                    "target_fact_ids (use the id or '<table>:<id>')",
                    index=position,
                    record=record,
                )
            )
    if refusals:
        return refused(refusals)

    # --- 2. Read the capture, then record the supplied source description and snapshot. ------
    request = FetchRequest(
        request_id=f"stage:{target.target_id}",
        canonical_url=target.canonical_url,
        source_policy_id=policy.policy_id,
        evidence_kind="tnc_pdf" if document_class is PageKind.TNC_PDF else "official_page",
        page_class=document_class,
        max_bytes=limits.max_bytes,
        max_pages=limits.max_pages,
        timeout_seconds=limits.timeout_seconds,
        run_id=f"stage-run:{target.target_id}",
    )
    result = asyncio.run(
        ManualUploadBackend(capture_path, artifacts=artifacts, policy=policy).fetch(request)
    )
    if result.failure is not None:
        return refused(
            [
                _refusal(
                    StageRefusalCode.CAPTURE_REJECTED,
                    f"{result.failure.kind.value}: {result.failure.diagnostic}",
                )
            ]
        )
    if result.raw_artifact is None or result.normalized_artifact is None:
        return refused(
            [_refusal(StageRefusalCode.CAPTURE_REJECTED, "the capture produced no content")]
        )
    is_pdf = is_pdf_media_type(result.raw_artifact.media_type)
    if is_pdf != (document_class is PageKind.TNC_PDF):
        return refused(
            [
                _refusal(
                    StageRefusalCode.DOCUMENT_CLASS_MISMATCH,
                    f"a {document_class.value} must "
                    + ("be a PDF" if document_class is PageKind.TNC_PDF else "not be a PDF")
                    + f" but the capture is {result.raw_artifact.media_type}",
                )
            ]
        )

    # Everything above depends only on the capture itself and wrote no database row, so a
    # refusal there cannot leave a policy or target behind that the operator then cannot correct.
    policy_state: Literal["stored", "already_stored"] = (
        "already_stored" if store.get_source_policy(policy.policy_id) else "stored"
    )
    target_state: Literal["stored", "already_stored"] = (
        "already_stored" if store.get_watch_target(target.target_id) else "stored"
    )
    try:
        store.put_source_policy(policy)
        store.put_watch_target(target)
    except ConflictingWriteError as error:
        return refused([_refusal(StageRefusalCode.POLICY_CONFLICT, str(error))])
    base = base.model_copy(update={"policy_state": policy_state, "target_state": target_state})

    normalized_hash = hashlib.sha256(result.normalized_text.encode("utf-8")).hexdigest()
    snapshot_id = f"snapshot:{target.target_id}:{normalized_hash}:{result.raw_artifact.sha256}"
    snapshot = store.get_snapshot(snapshot_id)
    snapshot_state: Literal["stored", "already_stored"] = "already_stored"
    if snapshot is None:
        stamp = now()
        attempt = FetchAttempt(
            attempt_id=f"stage-attempt:{target.target_id}:{stamp.strftime('%Y%m%dT%H%M%S%f')}",
            request_id=request.request_id,
            backend="manual",
            backend_version=ManualUploadBackend.backend_version,
            started_at=stamp,
            ended_at=stamp,
            final_url=result.final_url,
            response_class="success",
            retry_index=0,
        )
        snapshot = SnapshotService(store=store, artifacts=artifacts, now=now).capture(
            target_id=target.target_id, result=result, attempt=attempt
        )
        snapshot_state = "stored"
    if snapshot is None:
        return refused([_refusal(StageRefusalCode.CAPTURE_REJECTED, "snapshot was not created")])
    kind = _artifact_kind(snapshot)
    base = base.model_copy(
        update={
            "snapshot_id": snapshot.snapshot_id,
            "snapshot_state": snapshot_state,
            "artifact_kind": kind,
            "raw_sha256": snapshot.raw_sha256,
            "normalized_sha256": snapshot.normalized_sha256,
        }
    )

    # --- 3. Validate every record alone, then every row, before writing any proposal. -------
    text = snapshot.canonical_markdown
    for key, spec in insert_specs.items():
        template = copy.deepcopy(spec.row)
        template["id"] = spec.id
        # The draft's date is the snapshot's capture date, not today's, so staging the same
        # input on another day is the same request rather than a conflicting one.
        template["provenance"] = draft_provenance(
            source_url=target.canonical_url,
            today=snapshot.captured_at.date(),
            curator_id=extraction.curator_id,
        )
        current[key] = template
    summary_suffix = extraction.change_summary or "fields quoted from a manual capture"
    summary = f"Curator-authored by {extraction.curator_id}: {summary_suffix}"
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    problems: list[StageRefusal] = []
    segments: PageSegments | None = None
    if kind == "pdf" and any(r.page is not None for r in extraction.records):
        # Whole document, not just the cited pages: a quote that actually sits on a later page
        # must be attributable to that page to be refused (or its page listed) correctly.
        segments = _pdf_page_segments(
            artifacts.read(snapshot.raw_artifact),
            text,
            up_to=limits.max_pages,
            max_chars=limits.max_bytes,
        )
    for position, record in enumerate(extraction.records):
        row = current[(record.table, record.id)]
        if record.field_path == "id" or record.field_path.startswith("provenance"):
            code = (
                StageRefusalCode.FIELD_PATH_INVALID
                if record.field_path == "id"
                else StageRefusalCode.PROVENANCE_FIELD_FORBIDDEN
            )
            problems.append(
                _refusal(
                    code,
                    "identity and provenance are not extractable: a human decision sets them",
                    index=position,
                    record=record,
                )
            )
            continue
        if kind == "pdf" and record.page is None:
            problems.append(
                _refusal(
                    StageRefusalCode.PAGE_REQUIRED,
                    "PDF evidence must cite the page the quote is on",
                    index=position,
                    record=record,
                )
            )
            continue
        if kind != "pdf" and record.page is not None:
            problems.append(
                _refusal(
                    StageRefusalCode.PAGE_NOT_APPLICABLE,
                    "page applies only to PDF captures",
                    index=position,
                    record=record,
                )
            )
            continue
        located = _locate(text, record, position, segments)
        if isinstance(located, StageRefusal):
            problems.append(located)
            continue
        if kind == "pdf" and record.page is not None:
            if segments is None:
                problems.append(
                    _refusal(
                        StageRefusalCode.PAGE_MAP_UNAVAILABLE,
                        "the PDF's pages could not be mapped onto the stored text, so a page "
                        "citation cannot be confirmed against the offset",
                        index=position,
                        record=record,
                    )
                )
                continue
            actual = _page_of(segments, located.start)
            if actual != record.page or _page_of(segments, located.end - 1) != record.page:
                where = f"page {actual}" if actual is not None else "no page"
                problems.append(
                    _refusal(
                        StageRefusalCode.PAGE_OFFSET_MISMATCH,
                        f"the selected text is on {where}, not page {record.page}: choose the "
                        "occurrence (or offset) that lies on the cited page",
                        index=position,
                        record=record,
                    )
                )
                continue
        is_insert = (record.table, record.id) in insert_specs
        try:
            if is_insert:
                supplied = _present(row, record.field_path)
                expected = (
                    supplied
                    if supplied is not None
                    else type_guide(TARGET_MODELS[record.table], record.field_path)
                )
            else:
                supplied = None
                expected = _get(row, record.field_path)
            parsed = parse_field_value(record.field_path, record.raw_value, expected=expected)
        except ProposalValidationError as error:
            problems.append(
                _refusal(
                    StageRefusalCode.FIELD_PATH_INVALID, str(error), index=position, record=record
                )
            )
            continue
        except UnresolvedValueError as error:
            problems.append(
                _refusal(
                    StageRefusalCode.VALUE_UNRESOLVED,
                    f"unresolved value for {record.field_path}: {error}",
                    index=position,
                    record=record,
                )
            )
            continue
        span = EvidenceSpan(
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.normalized_sha256,
            quote=record.quote,
            normalized_start=located.start,
            normalized_end=located.end,
            field_path=record.field_path,
            verification="exact",
            artifact_kind=kind,
            page_number=record.page,
        )
        if is_insert and supplied is not None and not _same_value(supplied, parsed):
            problems.append(
                _refusal(
                    StageRefusalCode.TEMPLATE_CONFLICTS_WITH_EVIDENCE,
                    f"inserts[].row gives {supplied!r} for {record.field_path} but the quoted "
                    f"evidence says {parsed!r}: drop the value from row or fix the quote",
                    index=position,
                    record=record,
                )
            )
            continue
        if is_insert:
            try:
                check_field_evidence(
                    path=record.field_path,
                    raw_value=record.raw_value,
                    spans=(span,),
                    expected=expected,
                    proposed_value=parsed,
                    snapshot=snapshot,
                    artifacts=artifacts,
                )
            except ProposalValidationError as error:
                problems.append(
                    _refusal(_classify(str(error)), str(error), index=position, record=record)
                )
                continue
            slot = grouped.setdefault((record.table, record.id), {})
            known = slot.get(record.field_path)
            if known is not None and str(known["raw"]) != str(record.raw_value):
                problems.append(
                    _refusal(
                        StageRefusalCode.DUPLICATE_FIELD_CONFLICT,
                        f"{record.field_path} is given two different values "
                        f"({known['raw']!r} and {record.raw_value!r})",
                        index=position,
                        record=record,
                    )
                )
                continue
            if known is None:
                slot[record.field_path] = {"raw": record.raw_value, "parsed": parsed, "spans": []}
            slot[record.field_path]["spans"].append(span)
            continue
        proposed_alone = copy.deepcopy(row)
        _set(proposed_alone, record.field_path, parsed)
        alone = _response(
            table=record.table,
            row_id=record.id,
            proposed_row=proposed_alone,
            fields=[
                {
                    "field_path": record.field_path,
                    "proposed_raw_value": record.raw_value,
                    "evidence_spans": [span.model_dump()],
                }
            ],
            summary=summary,
        )
        try:
            validate_extraction(
                response=alone,
                target_table=record.table,
                target_id=record.id,
                current_row=row,
                current_row_hash=canonical_row_hash(row),
                snapshot=snapshot,
                artifacts=artifacts,
                now=now(),
                extractor_version=EXTRACTOR_VERSION,
                manual_capture=True,
            )
        except ProposalValidationError as error:
            problems.append(
                _refusal(_classify(str(error)), str(error), index=position, record=record)
            )
            continue
        slot = grouped.setdefault((record.table, record.id), {})
        known = slot.get(record.field_path)
        if known is not None and str(known["raw"]) != str(record.raw_value):
            problems.append(
                _refusal(
                    StageRefusalCode.DUPLICATE_FIELD_CONFLICT,
                    f"{record.field_path} is given two different values "
                    f"({known['raw']!r} and {record.raw_value!r})",
                    index=position,
                    record=record,
                )
            )
            continue
        if known is None:
            slot[record.field_path] = {"raw": record.raw_value, "parsed": parsed, "spans": []}
        slot[record.field_path]["spans"].append(span)
    if problems:
        return refused(problems)

    staged: list[tuple[str, str, str, ExtractionResponse, dict[str, Any], bool]] = []
    for missing_key in insert_specs.keys() - grouped.keys():
        problems.append(
            _refusal(
                StageRefusalCode.NEEDS_MORE_EVIDENCE,
                "an insert needs quoted evidence for at least one of its fields: add records "
                "for it",
                table=missing_key[0],
                row_id=missing_key[1],
            )
        )
    for (table, row_id), by_path in grouped.items():
        row = current[(table, row_id)]
        inserting = (table, row_id) in insert_specs
        proposed = copy.deepcopy(row)
        fields: list[dict[str, Any]] = []
        keyed: dict[str, tuple[str, list[tuple[int, int, int | None]]]] = {}
        for path in sorted(by_path):
            if inserting:
                _set_creating(proposed, path, by_path[path]["parsed"])
            else:
                _set(proposed, path, by_path[path]["parsed"])
            # Canonical order: the same evidence given in a different order is the same request.
            spans: list[EvidenceSpan] = sorted(
                by_path[path]["spans"],
                key=lambda span: (
                    span.normalized_start,
                    span.normalized_end,
                    span.page_number or 0,
                ),
            )
            fields.append(
                {
                    "field_path": path,
                    "proposed_raw_value": by_path[path]["raw"],
                    "evidence_spans": [span.model_dump() for span in spans],
                }
            )
            keyed[path] = (
                str(by_path[path]["raw"]),
                [(s.normalized_start, s.normalized_end, s.page_number) for s in spans],
            )
        response = _response(
            table=table, row_id=row_id, proposed_row=proposed, fields=fields, summary=summary
        )
        row_hash = canonical_row_hash(row)
        try:
            if inserting:
                validate_insert(
                    response=response,
                    target_table=table,
                    target_id=row_id,
                    existing_ids=existing_ids[table],
                    snapshot=snapshot,
                    artifacts=artifacts,
                    now=now(),
                    extractor_version=EXTRACTOR_VERSION,
                )
            else:
                validate_extraction(
                    response=response,
                    target_table=table,
                    target_id=row_id,
                    current_row=row,
                    current_row_hash=row_hash,
                    snapshot=snapshot,
                    artifacts=artifacts,
                    now=now(),
                    extractor_version=EXTRACTOR_VERSION,
                    manual_capture=True,
                )
        except ProposalValidationError as error:
            message = str(error)
            code = (
                StageRefusalCode.NEEDS_MORE_EVIDENCE
                if message.startswith("needs more evidence")
                else StageRefusalCode.INSERT_ID_EXISTS
                if message.startswith("insert id already exists")
                else _classify(message)
            )
            problems.append(_refusal(code, message, table=table, row_id=row_id))
            continue
        event = _event_id(
            snapshot=snapshot,
            table=table,
            row_id=row_id,
            current_row_hash=f"insert:{row_hash}" if inserting else row_hash,
            curator_id=extraction.curator_id,
            summary=summary,
            fields=keyed,
        )
        existing = store.get_proposal(f"proposal:{row_id}:{snapshot.snapshot_id}")
        if existing is not None and store.get_proposal_by_client_event(event) is None:
            problems.append(
                _refusal(
                    StageRefusalCode.PROPOSAL_CONFLICT,
                    f"{existing.proposal_id} already exists for this snapshot with different "
                    "content (the extraction, curator or base row changed). Reject it in "
                    "review, or capture a changed document, instead of overwriting history.",
                    table=table,
                    row_id=row_id,
                )
            )
            continue
        staged.append((table, row_id, event, response, row, inserting))
    if problems:
        return refused(problems)

    # --- 4. Write: one proposal per row through the real extractor. -------------------------
    stored: list[StagedProposal] = []
    for table, row_id, event, response, row, inserting in staged:
        client = ScriptedLLMClient({"financial_extractor": [response]})
        extractor = FinancialExtractor(
            client=client,
            store=store,
            artifacts=artifacts,
            now=now,
            extractor_version=EXTRACTOR_VERSION,
        )
        try:
            if inserting:
                outcome = extractor.extract_insert(
                    target_table=table,
                    target_id=row_id,
                    existing_ids=existing_ids[table],
                    snapshot=snapshot,
                    diff=diff_text(None, text),
                    client_event_id=event,
                )
            else:
                outcome = extractor.extract(
                    target_table=table,
                    target_id=row_id,
                    current_row=row,
                    current_row_hash=canonical_row_hash(row),
                    snapshot=snapshot,
                    diff=diff_text(None, text),
                    client_event_id=event,
                    manual_capture=True,
                )
        except (ConflictingWriteError, IdempotencyConflictError) as error:
            return refused(
                [
                    _refusal(
                        StageRefusalCode.PROPOSAL_CONFLICT, str(error), table=table, row_id=row_id
                    )
                ],
                proposals=tuple(stored),
            )
        if outcome.proposal is None:
            return refused(
                [
                    _refusal(
                        StageRefusalCode.VALIDATION_REFUSED,
                        outcome.diagnostic or outcome.status,
                        table=table,
                        row_id=row_id,
                    )
                ],
                proposals=tuple(stored),
            )
        proposal = outcome.proposal
        stored.append(
            StagedProposal(
                intent=proposal.intent,
                proposal_id=proposal.proposal_id,
                target_table=proposal.target_table,
                target_id=proposal.target_id,
                state="stored" if outcome.calls else "already_stored",
                review_status=proposal.status.value,
                version=proposal.version,
                field_paths=tuple(item.field_path for item in proposal.field_proposals),
                finding_codes=tuple(item.code for item in proposal.validation_findings),
            )
        )
    return base.model_copy(update={"status": "staged", "proposals": tuple(stored)})
