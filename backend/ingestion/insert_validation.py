"""Deterministic validation for *insert* proposals: a row that does not exist yet.

An update changes values on a row the seed already holds. An insert proposes a whole new row,
so the same questions get different answers:

* There is no base row to bind to. The proposal records ``intent="insert"``, carries no base
  hash, and a decision binds to the *absence* of the id instead (``absent_row_hash``). If the id
  appears later (another approval, a seed edit) the insert is refused, never merged.
* Every value is either **evidenced** (a quote from the stored snapshot, verified and parsed by
  the same deterministic code as updates) or **unevidenced** (a value the curator typed into
  the extraction file). Nothing here invents a value. Unevidenced values are recorded as
  warning findings so they stay visible in review, in the bundle and, later, to D1.
* The row's provenance is built by code as an unverified ``crawl_draft``. The curator cannot
  supply it and no insert can arrive already verified.
* A row that cannot be made schema-valid from the supplied template plus the quoted evidence is
  refused with the list of required fields it lacks (``needs more evidence``), never padded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from datetime import date, datetime
from types import UnionType
from typing import Any, Union, get_args, get_origin

from pydantic import BaseModel, ValidationError

from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import (
    ChangeProposal,
    EvidenceSpan,
    FieldProposal,
    SnapshotBundle,
    ValidationFinding,
)
from ingestion.evidence import EvidenceVerificationError, verify_evidence_span
from ingestion.extraction_types import ExtractionResponse
from ingestion.parsing import UnresolvedValueError, parse_field_value
from ingestion.review_rows import SUPPORTED_TABLES
from ingestion.validation import (
    TARGET_MODELS,
    ProposalValidationError,
    _flatten,
    _quote_supports_value,
    _same_value,
    _sanity_findings,
)

INSERT_EXTRACTOR_PREFIX = "insert:"


def absent_row_hash(table: str, row_id: str) -> str:
    """The hash an insert decision attests in place of a base-row hash: "this id is absent"."""
    payload = json.dumps(
        {"absent_row": {"table": table, "id": row_id}}, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def draft_provenance(*, source_url: str, today: date, curator_id: str) -> dict[str, Any]:
    """The only provenance an inserted row can start with: an unverified, unconfident draft."""
    return {
        "source_url": source_url,
        "source_type": "crawl_draft",
        "last_verified": today.isoformat(),
        "verified_by": "UNVERIFIED",
        "needs_verification": True,
        "confidence": 0.0,
        "notes": f"draft insert from a curator-authored extraction by {curator_id}; unverified",
    }


def type_guide(model: type[BaseModel], path: str) -> Any:
    """A value of the right Python type for ``path`` so the shared parser can interpret raw text.

    ``parse_field_value`` decides how to read a raw value partly from the type of the value it
    replaces. An inserted row has no previous value, so the model's own annotation stands in.
    Raises ``ProposalValidationError`` for a path that is not a field of the model.
    """
    current: Any = model
    for part in path.split("."):
        if not (isinstance(current, type) and issubclass(current, BaseModel)):
            raise ProposalValidationError(f"unknown field path: {path}")
        field = current.model_fields.get(part)
        if field is None:
            raise ProposalValidationError(f"unknown field path: {path}")
        current = _unwrap_optional(field.annotation)
    return _sample(current, path)


def _unwrap_optional(annotation: Any) -> Any:
    if get_origin(annotation) in (Union, UnionType):
        options = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(options) == 1:
            return options[0]
    return annotation


def _sample(annotation: Any, path: str) -> Any:
    if annotation is bool:
        return False
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is str:
        return ""
    if annotation is date:
        return date.min
    if get_origin(annotation) is list:
        return []
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        raise ProposalValidationError(f"{path} is a group of fields; quote one of its fields")
    return None


def check_field_evidence(
    *,
    path: str,
    raw_value: Any,
    spans: tuple[EvidenceSpan, ...],
    expected: Any,
    proposed_value: Any,
    snapshot: SnapshotBundle,
    artifacts: ContentAddressedStore,
) -> Any:
    """Verify one field's evidence and return its deterministic parse.

    The same three checks, with the same messages, that ``validate_extraction`` applies to an
    update: every span is an exact, hash-bound slice of the snapshot; the raw value parses; the
    quote supports the value as a whole token; and the row carries exactly that parse.
    """
    for span in spans:
        if span.field_path != path:
            raise ProposalValidationError(f"evidence field path does not match {path}")
        try:
            verify_evidence_span(span, snapshot=snapshot, artifacts=artifacts)
        except EvidenceVerificationError as error:
            raise ProposalValidationError(f"invalid evidence for {path}: {error}") from error
    try:
        parsed = parse_field_value(path, raw_value, expected=expected)
    except UnresolvedValueError as error:
        raise ProposalValidationError(f"unresolved value for {path}: {error}") from error
    if not any(
        _quote_supports_value(
            field_path=path,
            raw_value=raw_value,
            parsed_value=parsed,
            expected=expected,
            quote=span.quote,
        )
        for span in spans
    ):
        raise ProposalValidationError(
            f"evidence quote does not support the proposed value for {path}"
        )
    if not _same_value(proposed_value, parsed):
        raise ProposalValidationError(
            f"proposed row value for {path} is not the deterministic parse"
        )
    return parsed


def missing_required_fields(error: ValidationError) -> list[str]:
    return sorted(
        ".".join(str(part) for part in item["loc"])
        for item in error.errors()
        if item["type"] == "missing"
    )


def validate_insert(
    *,
    response: Any,
    target_table: str,
    target_id: str,
    existing_ids: Collection[str],
    snapshot: SnapshotBundle,
    artifacts: ContentAddressedStore,
    now: datetime,
    extractor_version: str,
) -> ChangeProposal:
    """Validate an untrusted insert response into a pending, unverified draft proposal."""
    try:
        parsed = (
            response
            if isinstance(response, ExtractionResponse)
            else ExtractionResponse.model_validate(response)
        )
    except ValidationError as error:
        raise ProposalValidationError(
            f"extractor response failed its typed contract: {error}"
        ) from error
    if parsed.target_table != target_table or parsed.target_id != target_id:
        raise ProposalValidationError("extractor target does not match the requested row")
    if target_table not in SUPPORTED_TABLES:
        raise ProposalValidationError(f"unsupported financial target table: {target_table}")
    model = TARGET_MODELS[target_table]
    if target_id in existing_ids:
        raise ProposalValidationError(f"insert id already exists: {target_id}")
    row = parsed.proposed_row
    if row.get("id") != target_id:
        raise ProposalValidationError("proposed row identity does not match the requested target")
    provenance = row.get("provenance")
    if not (
        isinstance(provenance, dict)
        and provenance.get("source_type") == "crawl_draft"
        and provenance.get("needs_verification") is True
        and provenance.get("verified_by") == "UNVERIFIED"
        and provenance.get("confidence") == 0.0
    ):
        raise ProposalValidationError(
            "an inserted row must carry unverified crawl_draft provenance"
        )
    flat = _flatten(row)
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for extracted in parsed.fields:
        path = extracted.field_path
        if path in seen:
            raise ProposalValidationError(f"duplicate field proposal: {path}")
        seen.add(path)
        if path == "id" or path.startswith("provenance"):
            raise ProposalValidationError(
                "identity and provenance are not extractable: a human decision sets them"
            )
        if path not in flat:
            raise ProposalValidationError(f"field path missing from proposed row: {path}")
        parsed_value = check_field_evidence(
            path=path,
            raw_value=extracted.proposed_raw_value,
            spans=extracted.evidence_spans,
            expected=type_guide(model, path),
            proposed_value=flat[path],
            snapshot=snapshot,
            artifacts=artifacts,
        )
        fields.append(
            {
                "field_path": path,
                "old_value": None,
                "proposed_raw_value": extracted.proposed_raw_value,
                "parsed_value": parsed_value,
                "evidence_spans": extracted.evidence_spans,
            }
        )
    if not fields:
        raise ProposalValidationError("an insert needs quoted evidence for at least one field")
    try:
        typed_row = model.model_validate(row)
    except ValidationError as error:
        missing = missing_required_fields(error)
        if missing:
            raise ProposalValidationError(
                f"needs more evidence: required fields are missing: {', '.join(missing)}"
            ) from error
        raise ProposalValidationError(f"proposed row failed the target schema: {error}") from error
    findings: list[ValidationFinding] = _sanity_findings(
        target_table, typed_row.model_dump(), today=now
    )
    findings.extend(
        ValidationFinding(
            code="unevidenced_field",
            severity="warning",
            message="value supplied by the curator without quoted evidence",
            field_path=path,
        )
        for path, value in sorted(_flatten(typed_row.model_dump(mode="json")).items())
        if path != "id"
        and not path.startswith("provenance.")
        and path not in seen
        and value is not None  # an unknown optional value asserts nothing
    )
    return ChangeProposal(
        proposal_id=f"proposal:{target_id}:{snapshot.snapshot_id}",
        target_table=target_table,
        target_id=target_id,
        current_row_hash=None,
        proposed_row=typed_row.model_dump(mode="json"),
        field_proposals=tuple(FieldProposal.model_validate(field) for field in fields),
        change_summary=parsed.change_summary,
        extractor_version=extractor_version,
        validation_findings=tuple(findings),
        lineage_ids=(snapshot.snapshot_id,),
        version=1,
        created_at=now,
        updated_at=now,
        intent="insert",
    )
