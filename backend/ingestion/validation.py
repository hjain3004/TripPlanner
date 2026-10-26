"""Deterministic validation for untrusted financial extraction responses."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ValidationError

from core.models import (
    Card,
    FxRate,
    Offer,
    PointValuation,
    RewardRule,
    TransferBonus,
    TransferEdge,
)
from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import ChangeProposal, SnapshotBundle, ValidationFinding
from ingestion.evidence import EvidenceVerificationError, verify_evidence_span
from ingestion.extraction_types import ExtractionResponse
from ingestion.parsing import UnresolvedValueError, parse_field_value


class ProposalValidationError(ValueError):
    pass


TARGET_MODELS: dict[str, type[BaseModel]] = {
    "cards": Card,
    "reward_rules": RewardRule,
    "offers": Offer,
    "point_valuations": PointValuation,
    "fx_rates": FxRate,
    "transfer_bonuses": TransferBonus,
    "transfer_edges": TransferEdge,
}


def _flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.update(_flatten(child, path))
        return result
    return {prefix: value}


def _get(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ProposalValidationError(f"unknown field path: {path}")
        current = current[part]
    return current


def _set(value: dict[str, Any], path: str, replacement: Any) -> None:
    parts = path.split(".")
    current = value
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise ProposalValidationError(f"field path is not writable: {path}")
        current = child
    current[parts[-1]] = replacement


def _same_value(candidate: Any, parsed: Any) -> bool:
    if isinstance(parsed, date) and isinstance(candidate, str):
        try:
            return date.fromisoformat(candidate) == parsed
        except ValueError:
            return False
    return bool(candidate == parsed)


def _row_hash(row: dict[str, Any]) -> str:
    import json

    payload = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _sanity_findings(
    table: str, row: dict[str, Any], *, today: datetime
) -> list[ValidationFinding]:
    findings: list[ValidationFinding] = []
    if table in {"reward_rules", "offers"}:
        valid_to = row.get("valid_to")
        if valid_to is not None and valid_to < today.date():
            findings.append(
                ValidationFinding(
                    code="expired_value",
                    severity="warning",
                    message="proposed value is already expired",
                    field_path="valid_to",
                )
            )
    if table == "reward_rules":
        earn = row.get("earn", {})
        points = earn.get("points", 0) if isinstance(earn, dict) else 0
        per_amount = earn.get("per_amount_minor", 0) if isinstance(earn, dict) else 0
        if points <= 0 or per_amount <= 0:
            findings.append(
                ValidationFinding(
                    code="non_positive_rate",
                    severity="blocking",
                    message="earn rate must be positive",
                    field_path="earn",
                )
            )
        cap = row.get("cap")
        if isinstance(cap, dict) and cap.get("max_points", 1) <= 0:
            findings.append(
                ValidationFinding(
                    code="non_positive_cap",
                    severity="blocking",
                    message="cap must be positive",
                    field_path="cap.max_points",
                )
            )
    if table == "offers":
        discount = row.get("discount_bp")
        if discount is not None and discount > 5000:
            findings.append(
                ValidationFinding(
                    code="large_discount",
                    severity="warning",
                    message="discount exceeds the normal 50% policy threshold",
                    field_path="discount_bp",
                )
            )
        if row.get("discount_bp") is not None and row.get("discount_flat_minor") is not None:
            findings.append(
                ValidationFinding(
                    code="ambiguous_discount",
                    severity="blocking",
                    message="offer cannot contain both percentage and flat discount",
                    field_path="discount_bp",
                )
            )
    return findings


def validate_extraction(
    *,
    response: Any,
    target_table: str,
    target_id: str,
    current_row: dict[str, Any],
    current_row_hash: str | None,
    snapshot: SnapshotBundle,
    artifacts: ContentAddressedStore,
    now: datetime,
    extractor_version: str,
    manual_capture: bool = False,
) -> ChangeProposal:
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
    if "id" in current_row and current_row.get("id") != target_id:
        raise ProposalValidationError("current row identity does not match the requested target")
    if "id" in parsed.proposed_row and parsed.proposed_row.get("id") != target_id:
        raise ProposalValidationError("proposed row identity does not match the requested target")
    model = TARGET_MODELS.get(target_table)
    if model is None:
        raise ProposalValidationError(f"unsupported financial target table: {target_table}")
    current_flat = _flatten(current_row)
    proposed_flat = _flatten(parsed.proposed_row)
    if set(proposed_flat) != set(current_flat):
        raise ProposalValidationError("proposed_row must contain the complete existing row shape")
    proposed = dict(current_row)
    fields: list[Any] = []
    findings: list[ValidationFinding] = []
    seen: set[str] = set()
    for extracted in parsed.fields:
        path = extracted.field_path
        if path in seen:
            raise ProposalValidationError(f"duplicate field proposal: {path}")
        seen.add(path)
        expected = _get(current_row, path)
        if path not in current_flat:
            raise ProposalValidationError(f"field path is not permitted: {path}")
        if path == "id":
            raise ProposalValidationError("target identity is not an extractable field")
        if path not in proposed_flat:
            raise ProposalValidationError(f"field path missing from proposed row: {path}")
        for span in extracted.evidence_spans:
            if span.field_path != path:
                raise ProposalValidationError(f"evidence field path does not match {path}")
            try:
                verify_evidence_span(span, snapshot=snapshot, artifacts=artifacts)
            except EvidenceVerificationError as error:
                raise ProposalValidationError(f"invalid evidence for {path}: {error}") from error
        try:
            parsed_value = parse_field_value(path, extracted.proposed_raw_value, expected=expected)
        except UnresolvedValueError as error:
            raise ProposalValidationError(f"unresolved value for {path}: {error}") from error
        if not _same_value(proposed_flat[path], parsed_value):
            raise ProposalValidationError(
                f"proposed row value for {path} is not the deterministic parse"
            )
        _set(proposed, path, parsed_value)
        fields.append(
            {
                "field_path": path,
                "old_value": expected,
                "proposed_raw_value": extracted.proposed_raw_value,
                "parsed_value": parsed_value,
                "evidence_spans": extracted.evidence_spans,
            }
        )
    if not fields:
        raise ProposalValidationError("changed extraction must contain at least one field")
    reconstructed_flat = _flatten(proposed)
    for path, value in proposed_flat.items():
        if not _same_value(value, reconstructed_flat[path]):
            raise ProposalValidationError(f"proposed row changes {path} without a field proposal")
    if _row_hash(current_row) != current_row_hash and current_row_hash is not None:
        findings.append(
            ValidationFinding(
                code="stale_current_row",
                severity="blocking",
                message="current row hash does not match the supplied row",
            )
        )
    try:
        typed_row = model.model_validate(proposed)
    except ValidationError as error:
        raise ProposalValidationError(f"proposed row failed the target schema: {error}") from error
    # Manual captures never acquire official verification merely because a
    # source URL appears in the uploaded document.
    provenance = getattr(typed_row, "provenance", None)
    if manual_capture:
        if any(field_path.startswith("provenance") for field_path in seen):
            raise ProposalValidationError(
                "manual captures cannot change provenance before human review"
            )
        if provenance is not None and not provenance.needs_verification:
            raise ProposalValidationError("manual capture evidence must remain unverified")
    if (
        provenance is not None
        and provenance.source_type in {"official_page", "tnc_pdf"}
        and provenance.needs_verification is False
    ):
        raise ProposalValidationError(
            "draft evidence cannot self-promote manual content to official verified evidence"
        )
    findings.extend(_sanity_findings(target_table, typed_row.model_dump(), today=now))
    proposal = ChangeProposal(
        proposal_id=f"proposal:{target_id}:{snapshot.snapshot_id}",
        target_table=target_table,
        target_id=target_id,
        current_row_hash=current_row_hash,
        proposed_row=typed_row.model_dump(mode="json"),
        field_proposals=tuple(fields),
        change_summary=parsed.change_summary,
        extractor_version=extractor_version,
        validation_findings=tuple(findings),
        lineage_ids=(snapshot.snapshot_id,),
        version=1,
        created_at=now,
        updated_at=now,
    )
    return proposal
