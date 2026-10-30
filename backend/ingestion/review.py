from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from ingestion.artifacts import ArtifactIntegrityError, ContentAddressedStore
from ingestion.contracts import (
    ChangeProposal,
    EvidenceDigest,
    EvidenceSpan,
    PageKind,
    ProposalStatus,
    ReverifyTask,
    ReviewAttestation,
    ReviewDecision,
    ReviewDecisionStatus,
)
from ingestion.evidence import EvidenceVerificationError, verify_evidence_span
from ingestion.extraction_types import ExtractionResponse
from ingestion.parsing import UnresolvedValueError, parse_field_value
from ingestion.review_rows import SeedRowError, SeedRowSource, flatten_row
from ingestion.review_types import (
    ComputedFinding,
    CuratorFieldEdit,
    DecisionRequest,
    EvidenceContext,
    FieldDiff,
    FindingCode,
    LineageView,
    ReviewContext,
    ReviewRefusedError,
)
from ingestion.storage import FinancialIngestionStore
from ingestion.validation import ProposalValidationError, canonical_row_hash, validate_extraction

CONTEXT_CHARS = 240
SUPERSESSION_LIMIT = 50


def _supported_edit_value(value: Any) -> bool:
    return isinstance(value, (date, int, str)) and not isinstance(value, bool)


class ReviewService:
    def __init__(
        self,
        *,
        store: FinancialIngestionStore,
        artifacts: ContentAddressedStore,
        rows: SeedRowSource,
        now: Callable[[], datetime],
        evidence_verifier: Callable[..., None] = verify_evidence_span,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.rows = rows
        self.now = now
        self.evidence_verifier = evidence_verifier

    def list_queue(
        self, status: ProposalStatus | None = ProposalStatus.PENDING
    ) -> list[ChangeProposal]:
        return self.store.list_proposals(status)

    def context(self, proposal_id: str) -> ReviewContext:
        proposal = self.store.get_proposal(proposal_id)
        if proposal is None:
            raise KeyError(proposal_id)
        findings: list[ComputedFinding] = []
        try:
            current = self.rows.current_row(proposal.target_table, proposal.target_id)
            current_hash = canonical_row_hash(current)
        except SeedRowError as error:
            current = None
            current_hash = None
            code = (
                FindingCode(error.code)
                if error.code in FindingCode._value2member_map_
                else FindingCode.CURRENT_ROW_MISSING
            )
            findings.append(ComputedFinding(code=code, severity="blocking", message=str(error)))
        if proposal.current_row_hash is None:
            findings.append(
                ComputedFinding(
                    code=FindingCode.UNBOUND_BASE_ROW,
                    severity="blocking",
                    message="proposal has no bound current-row hash",
                )
            )
        elif current_hash is not None and current_hash != proposal.current_row_hash:
            findings.append(
                ComputedFinding(
                    code=FindingCode.CURRENT_ROW_CHANGED,
                    severity="blocking",
                    message="current seed row changed since extraction",
                )
            )
        for stored in proposal.validation_findings:
            if stored.severity == "blocking":
                findings.append(
                    ComputedFinding(
                        code=FindingCode.STORED_BLOCKING_FINDING,
                        severity="blocking",
                        message=stored.message,
                        field_path=stored.field_path,
                    )
                )
        snapshots = []
        evidence_contexts: list[EvidenceContext] = []
        for snapshot_id in proposal.lineage_ids:
            snapshot = self.store.get_snapshot(snapshot_id)
            if snapshot is None:
                findings.append(
                    ComputedFinding(
                        code=FindingCode.EVIDENCE_INTEGRITY_FAILED,
                        severity="blocking",
                        message=f"missing snapshot: {snapshot_id}",
                    )
                )
                continue
            snapshots.append(snapshot)
            for field in proposal.field_proposals:
                for span in field.evidence_spans:
                    try:
                        self.evidence_verifier(span, snapshot=snapshot, artifacts=self.artifacts)
                        verified = True
                        failure = None
                    except (
                        EvidenceVerificationError,
                        ArtifactIntegrityError,
                        FileNotFoundError,
                    ) as error:
                        verified = False
                        failure = str(error)
                        findings.append(
                            ComputedFinding(
                                code=FindingCode.EVIDENCE_INTEGRITY_FAILED,
                                severity="blocking",
                                message=failure,
                                field_path=field.field_path,
                            )
                        )
                    start = max(0, span.normalized_start - CONTEXT_CHARS)
                    end = min(len(snapshot.canonical_markdown), span.normalized_end + CONTEXT_CHARS)
                    evidence_contexts.append(
                        EvidenceContext(
                            span=span,
                            before=snapshot.canonical_markdown[start : span.normalized_start],
                            after=snapshot.canonical_markdown[span.normalized_end : end],
                            verified=verified,
                            failure=failure,
                        )
                    )
            if snapshot.raw_artifact.media_type.split(";", 1)[0].lower() == "application/pdf":
                if any(
                    span.page_number is None
                    for field in proposal.field_proposals
                    for span in field.evidence_spans
                ):
                    findings.append(
                        ComputedFinding(
                            code=FindingCode.EVIDENCE_INTEGRITY_FAILED,
                            severity="blocking",
                            message="PDF evidence requires page numbers",
                        )
                    )
        if len(proposal.lineage_ids) != 1:
            findings.append(
                ComputedFinding(
                    code=FindingCode.MULTI_SNAPSHOT_LINEAGE,
                    severity="blocking",
                    message="review decisions require one snapshot lineage",
                )
            )
        lineage_snapshot = snapshots[0] if snapshots else None
        target = (
            self.store.get_watch_target(lineage_snapshot.target_id) if lineage_snapshot else None
        )
        policy = self.store.get_source_policy(target.source_policy_id) if target else None
        if target and policy:
            if target.page_kind is PageKind.MANUAL_CAPTURE:
                findings.append(
                    ComputedFinding(
                        code=FindingCode.MANUAL_CAPTURE,
                        severity="warning",
                        message="manual capture remains unverified",
                    )
                )
            if policy.attribution_required:
                findings.append(
                    ComputedFinding(
                        code=FindingCode.ATTRIBUTION_REQUIRED,
                        severity="warning",
                        message="source attribution is required",
                    )
                )
            lineage = LineageView(
                source_policy=policy,
                watch_target=target,
                snapshots=tuple(snapshots),
                supersession_chain=tuple(s.snapshot_id for s in snapshots),
                latest_snapshot_id=self.store.latest_snapshot_id(target.target_id),
            )
            if lineage.latest_snapshot_id not in {None, proposal.lineage_ids[-1]}:
                findings.append(
                    ComputedFinding(
                        code=FindingCode.EVIDENCE_SUPERSEDED,
                        severity="blocking",
                        message="a newer snapshot supersedes the proposal evidence",
                    )
                )
        else:
            lineage = None
        current_flat = flatten_row(current or {})
        proposed_flat = flatten_row(proposal.proposed_row)
        diffs = tuple(
            FieldDiff(
                field_path=path,
                current=current_flat.get(path),
                proposed=value,
                edited=None,
                changed=current_flat.get(path) != value,
                evidence=tuple(
                    span
                    for field in proposal.field_proposals
                    if field.field_path == path
                    for span in field.evidence_spans
                ),
            )
            for path, value in sorted(proposed_flat.items())
        )
        return ReviewContext(
            proposal=proposal,
            current_row=current,
            current_row_sha256=current_hash,
            field_diffs=diffs,
            evidence=tuple(evidence_contexts),
            lineage=lineage,
            computed_findings=tuple(findings),
            decisions=tuple(self.store.list_decisions(proposal_id)),
            audit_events=tuple(self.store.list_audit_events(entity_id=proposal_id)),
        )

    @staticmethod
    def edits_payload(edits: tuple[CuratorFieldEdit, ...]) -> dict[str, Any]:
        return {
            "fields": [
                edit.model_dump(mode="json")
                for edit in sorted(edits, key=lambda value: value.field_path)
            ]
        }

    def apply_edits(
        self, ctx: ReviewContext, edits: tuple[CuratorFieldEdit, ...]
    ) -> tuple[dict[str, Any], ChangeProposal]:
        if ctx.lineage is None or len(ctx.lineage.snapshots) != 1:
            raise ReviewRefusedError(
                "edits require one complete snapshot lineage",
                (
                    ComputedFinding(
                        code=FindingCode.MULTI_SNAPSHOT_LINEAGE,
                        severity="blocking",
                        message="edits require one snapshot",
                    ),
                ),
            )
        row = json.loads(json.dumps(ctx.proposal.proposed_row))
        snapshot = ctx.lineage.snapshots[0]
        fields: list[dict[str, Any]] = []
        for edit in edits:
            if edit.field_path == "id" or edit.field_path.startswith("provenance"):
                raise ReviewRefusedError(
                    "identity and provenance cannot be edited",
                    (
                        ComputedFinding(
                            code=FindingCode.INVALID_EDIT,
                            severity="blocking",
                            message="identity/provenance is not editable",
                            field_path=edit.field_path,
                        ),
                    ),
                )
            expected = flatten_row(ctx.current_row or {}).get(edit.field_path)
            if edit.action == "revert":
                replacement = expected
                if edit.field_path not in flatten_row(row):
                    raise ReviewRefusedError("unknown edit path")
            else:
                assert (
                    edit.quote is not None
                    and edit.proposed_raw_value is not None
                    and edit.snapshot_id is not None
                )
                if (
                    edit.snapshot_id != snapshot.snapshot_id
                    or edit.quote not in snapshot.canonical_markdown
                ):
                    raise ReviewRefusedError("edit evidence is not in the proposal snapshot")
                occurrences = [
                    i
                    for i in range(len(snapshot.canonical_markdown))
                    if snapshot.canonical_markdown.startswith(edit.quote, i)
                ]
                if len(occurrences) != 1 and edit.occurrence is None:
                    raise ReviewRefusedError("ambiguous edit quote requires occurrence")
                index = (
                    occurrences[(edit.occurrence or 1) - 1] if edit.occurrence else occurrences[0]
                )
                if edit.occurrence is not None and (
                    edit.occurrence > len(occurrences) or occurrences[edit.occurrence - 1] != index
                ):
                    raise ReviewRefusedError("edit quote occurrence is invalid")
                if edit.proposed_raw_value.casefold() not in edit.quote.casefold():
                    raise ReviewRefusedError("edited raw value is not supported by its quote")
                span = EvidenceSpan(
                    snapshot_id=snapshot.snapshot_id,
                    snapshot_hash=snapshot.normalized_sha256,
                    quote=edit.quote,
                    normalized_start=index,
                    normalized_end=index + len(edit.quote),
                    field_path=edit.field_path,
                    verification="exact",
                    artifact_kind="pdf"
                    if snapshot.raw_artifact.media_type.startswith("application/pdf")
                    else "html",
                    page_number=edit.page_number,
                )
                try:
                    replacement = parse_field_value(
                        edit.field_path, edit.proposed_raw_value, expected=expected
                    )
                except UnresolvedValueError as error:
                    raise ReviewRefusedError(str(error)) from error
                if not _supported_edit_value(replacement):
                    raise ReviewRefusedError("unsupported edit type")
                fields.append(
                    {
                        "field_path": edit.field_path,
                        "proposed_raw_value": edit.proposed_raw_value,
                        "evidence_spans": [span.model_dump(mode="json")],
                    }
                )
            parts = edit.field_path.split(".")
            cursor = row
            for part in parts[:-1]:
                if not isinstance(cursor.get(part), dict):
                    raise ReviewRefusedError("edit path is not writable")
                cursor = cursor[part]
            cursor[parts[-1]] = replacement
        if row == ctx.proposal.proposed_row:
            raise ReviewRefusedError(
                "no effective edit",
                (
                    ComputedFinding(
                        code=FindingCode.NO_EFFECTIVE_EDIT,
                        severity="blocking",
                        message="edits do not change the proposed row",
                    ),
                ),
            )
        response = ExtractionResponse(
            target_table=ctx.proposal.target_table,
            target_id=ctx.proposal.target_id,
            proposed_row=row,
            fields=tuple(fields),
            change_summary=ctx.proposal.change_summary,
            extractor_confidence=0.0,
        )
        try:
            validated = validate_extraction(
                response=response,
                target_table=ctx.proposal.target_table,
                target_id=ctx.proposal.target_id,
                current_row=ctx.current_row or {},
                current_row_hash=ctx.proposal.current_row_hash,
                snapshot=snapshot,
                artifacts=self.artifacts,
                now=self.now(),
                extractor_version="fi3-curator",
                manual_capture=ctx.lineage.watch_target.page_kind is PageKind.MANUAL_CAPTURE,
            )
        except (ProposalValidationError, ValueError) as error:
            raise ReviewRefusedError(
                str(error),
                (
                    ComputedFinding(
                        code=FindingCode.INVALID_EDIT, severity="blocking", message=str(error)
                    ),
                ),
            ) from error
        return row, validated

    def decide(self, request: DecisionRequest, *, curator_id: str) -> ReviewDecision:
        if self.store.get_curator(curator_id) is None:
            raise ReviewRefusedError(
                "unknown curator",
                (
                    ComputedFinding(
                        code=FindingCode.UNKNOWN_CURATOR,
                        severity="blocking",
                        message="curator is not registered",
                    ),
                ),
            )
        ctx = self.context(request.proposal_id)
        if request.action in {"approve", "edit"} and ctx.blocking_for_approval:
            raise ReviewRefusedError("proposal has blocking findings", ctx.computed_findings)
        edits = self.edits_payload(request.edits) if request.action == "edit" else None
        resulting = ctx.proposal.proposed_row
        if request.action == "edit":
            resulting, _ = self.apply_edits(ctx, request.edits)
        status = {
            "approve": ReviewDecisionStatus.APPROVED,
            "edit": ReviewDecisionStatus.EDITED,
            "reject": ReviewDecisionStatus.REJECTED,
            "reverify": ReviewDecisionStatus.REVERIFY,
        }[request.action]
        evidence = tuple(
            EvidenceDigest(
                snapshot_id=s.snapshot_id,
                raw_sha256=s.raw_sha256,
                normalized_sha256=s.normalized_sha256,
            )
            for s in (ctx.lineage.snapshots if ctx.lineage else ())
        )
        attestation = None
        if ctx.current_row_sha256 is not None:
            attestation = ReviewAttestation(
                proposal_payload_sha256=self.store.proposal_payload_sha256(
                    ctx.proposal.model_dump_json()
                ),
                current_row_sha256=ctx.current_row_sha256,
                resulting_row_sha256=canonical_row_hash(resulting)
                if request.action in {"approve", "edit"}
                else None,
                evidence=evidence,
                computed_finding_codes=tuple(f.code.value for f in ctx.computed_findings),
            )
        task = None
        if request.action == "reverify" and ctx.lineage is not None:
            task = ReverifyTask(
                task_id=f"reverify:{ctx.proposal.proposal_id}",
                target_id=ctx.lineage.watch_target.target_id,
                reason=request.reason,
                priority="normal",
                prior_evidence_ids=ctx.proposal.lineage_ids,
                created_at=self.now(),
                due_at=self.now() + timedelta(days=1),
            )
        return self.store.decide_proposal(
            request.proposal_id,
            reviewer_id=curator_id,
            status=status,
            reason=request.reason,
            expected_version=request.expected_version,
            client_event_id=request.client_event_id,
            edits=edits,
            attestation=attestation,
            curator_confidence=request.curator_confidence,
            reverify_task=task,
        )
