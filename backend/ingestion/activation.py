from __future__ import annotations

import hashlib
import json
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict

from core.db import KnowledgeBase
from core.models import Card, Offer, PointValuation, RewardRule
from ingestion.artifacts import ArtifactIntegrityError, ContentAddressedStore
from ingestion.contracts import ImmutableArtifactRef, PageKind, ProposalStatus
from ingestion.review import ReviewService
from ingestion.review_rows import (
    SUPPORTED_TABLES,
    SeedRowError,
    SeedRowSource,
    flatten_row,
)
from ingestion.storage import FinancialIngestionStore
from ingestion.validation import canonical_row_hash

BUNDLE_SCHEMA: Final = "tripwise.financial-activation-bundle/v1"


class FieldChange(BaseModel):
    field_path: str
    old: Any = None
    new: Any = None


class ActivationEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    target_table: str
    target_id: str
    base_row_sha256: str
    new_row: dict[str, Any]
    new_row_sha256: str
    field_changes: tuple[FieldChange, ...]
    unevidenced_fields: tuple[str, ...]
    proposal_id: str
    proposal_payload_sha256: str
    decision_id: str
    decision_status: str
    reviewer_id: str
    decided_at: str
    evidence: tuple[dict[str, str], ...]
    source_url: str
    source_type: Literal["official_page", "tnc_pdf", "manual_curation"]
    attribution_required: bool


class RefusedEntry(BaseModel):
    proposal_id: str
    code: str
    message: str


class ActivationBundle(BaseModel):
    schema_version: Literal["tripwise.financial-activation-bundle/v1"] = BUNDLE_SCHEMA
    seed_files: dict[str, str]
    entries: tuple[ActivationEntry, ...]
    refused: tuple[RefusedEntry, ...]
    applicable: bool


class ActivationBundleRecord(BaseModel):
    bundle_sha256: str
    artifact: ImmutableArtifactRef
    proposal_ids: tuple[str, ...]


class DryRunEntry(BaseModel):
    target_table: str
    target_id: str
    status: Literal["would_update", "stale", "row_missing", "invalid_row"]
    field_changes: tuple[FieldChange, ...] = ()


class DryRunReport(BaseModel):
    bundle_sha256: str
    entries: tuple[DryRunEntry, ...]
    kb_constructs: bool
    reference_errors: tuple[str, ...]
    seed_files_unchanged: bool
    applicable: bool


def canonical_bundle_bytes(bundle: ActivationBundle) -> bytes:
    return json.dumps(
        bundle.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


class ActivationPlanner:
    def __init__(
        self,
        *,
        store: FinancialIngestionStore,
        artifacts: ContentAddressedStore,
        rows: SeedRowSource,
        service: ReviewService,
    ) -> None:
        self.store, self.artifacts, self.rows, self.service = store, artifacts, rows, service

    def build(
        self, *, proposal_ids: tuple[str, ...] | None, curator_id: str, client_event_id: str
    ) -> tuple[ActivationBundleRecord, ActivationBundle]:
        selected = proposal_ids or tuple(
            p.proposal_id
            for p in self.service.list_queue(None)
            if p.status in {ProposalStatus.APPROVED, ProposalStatus.EDITED}
        )
        entries: list[ActivationEntry] = []
        refused: list[RefusedEntry] = []
        targets: dict[tuple[str, str], list[str]] = {}
        for proposal_id in sorted(selected):
            try:
                ctx = self.service.context(proposal_id)
                decision = ctx.decisions[-1]
                if decision.status not in {"approved", "edited"} or decision.attestation is None:
                    raise ValueError("decision is not an attested approval")
                if (
                    ctx.current_row is None
                    or ctx.current_row_sha256 != ctx.proposal.current_row_hash
                ):
                    raise ValueError("current row is stale or missing")
                if decision.status == "edited":
                    # Reconstruct from the stored typed edit payload; never trust stored row data.
                    fields = tuple(
                        __import__(
                            "ingestion.review_types", fromlist=["CuratorFieldEdit"]
                        ).CuratorFieldEdit.model_validate(value)
                        for value in decision.edits.get("fields", [])
                    )
                    new_row, _ = self.service.apply_edits(ctx, fields)
                else:
                    new_row = ctx.proposal.proposed_row
                if canonical_row_hash(new_row) != decision.attestation.resulting_row_sha256:
                    raise ValueError("resulting row attestation does not match")
                targets.setdefault((ctx.proposal.target_table, ctx.proposal.target_id), []).append(
                    proposal_id
                )
                snapshot = ctx.lineage.snapshots[0] if ctx.lineage else None
                if snapshot is None or ctx.lineage is None:
                    raise ValueError("missing evidence lineage")
                changes = tuple(
                    FieldChange(field_path=path, old=flatten_row(ctx.current_row)[path], new=value)
                    for path, value in sorted(flatten_row(new_row).items())
                    if flatten_row(ctx.current_row).get(path) != value
                )
                covered = {field.field_path for field in ctx.proposal.field_proposals} | {
                    change.field_path for change in changes
                }
                unevidenced = tuple(
                    path
                    for path in flatten_row(new_row)
                    if path != "id" and not path.startswith("provenance.") and path not in covered
                )
                page_kind = ctx.lineage.watch_target.page_kind
                source_type = (
                    "manual_curation"
                    if page_kind is PageKind.MANUAL_CAPTURE
                    else "tnc_pdf"
                    if page_kind is PageKind.TNC_PDF
                    else "official_page"
                )
                entries.append(
                    ActivationEntry(
                        target_table=ctx.proposal.target_table,
                        target_id=ctx.proposal.target_id,
                        base_row_sha256=ctx.proposal.current_row_hash or "",
                        new_row=new_row,
                        new_row_sha256=canonical_row_hash(new_row),
                        field_changes=changes,
                        unevidenced_fields=unevidenced,
                        proposal_id=proposal_id,
                        proposal_payload_sha256=decision.attestation.proposal_payload_sha256,
                        decision_id=decision.decision_id,
                        decision_status=decision.status.value,
                        reviewer_id=decision.reviewer_id,
                        decided_at=decision.decided_at.isoformat(),
                        evidence=tuple(
                            d.model_dump(mode="json") for d in decision.attestation.evidence
                        ),
                        source_url=ctx.lineage.watch_target.canonical_url,
                        source_type=source_type,
                        attribution_required=ctx.lineage.source_policy.attribution_required,
                    )
                )
            except Exception as error:
                refused.append(
                    RefusedEntry(proposal_id=proposal_id, code="refused", message=str(error))
                )
        conflicts = {key for key, ids in targets.items() if len(ids) > 1}
        if conflicts:
            entries = [
                entry for entry in entries if (entry.target_table, entry.target_id) not in conflicts
            ]
            refused.extend(
                RefusedEntry(
                    proposal_id=pid,
                    code="conflicting_entries",
                    message="multiple approvals target the same row",
                )
                for key in conflicts
                for pid in targets[key]
            )
        seed_files = {
            filename: self.rows.seed_file_sha256(table)
            for table, (filename, _model) in SUPPORTED_TABLES.items()
        }
        bundle = ActivationBundle(
            seed_files=seed_files,
            entries=tuple(sorted(entries, key=lambda e: (e.target_table, e.target_id))),
            refused=tuple(sorted(refused, key=lambda e: e.proposal_id)),
            applicable=not refused,
        )
        body = canonical_bundle_bytes(bundle)
        digest = hashlib.sha256(body).hexdigest()
        artifact = self.artifacts.put(body, media_type="application/json")
        record_json = ActivationBundleRecord(
            bundle_sha256=digest, artifact=artifact, proposal_ids=tuple(sorted(selected))
        ).model_dump_json()
        fingerprint = hashlib.sha256(
            json.dumps(
                {"proposal_ids": sorted(selected), "curator_id": curator_id},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        self.store.put_activation_bundle(
            record_json,
            bundle_sha256=digest,
            client_event_id=client_event_id,
            request_fingerprint=fingerprint,
            created_by=curator_id,
        )
        return ActivationBundleRecord.model_validate_json(record_json), bundle

    def dry_run(self, bundle_sha256: str) -> DryRunReport:
        record_json = self.store.get_activation_bundle(bundle_sha256)
        if record_json is None:
            raise KeyError(bundle_sha256)
        record = ActivationBundleRecord.model_validate_json(record_json)
        body = self.artifacts.read(record.artifact)
        if hashlib.sha256(body).hexdigest() != bundle_sha256:
            raise ArtifactIntegrityError("activation bundle hash mismatch")
        bundle = ActivationBundle.model_validate_json(body)
        entries: list[DryRunEntry] = []
        models: dict[str, list[dict[str, Any]]] = {table: [] for table in SUPPORTED_TABLES}
        refs: list[str] = []
        for table in SUPPORTED_TABLES:
            models[table] = self.rows.table_rows(table)
        for entry in bundle.entries:
            try:
                current = self.rows.current_row(entry.target_table, entry.target_id)
                status = (
                    "would_update"
                    if canonical_row_hash(current) == entry.base_row_sha256
                    else "stale"
                )
                entries.append(
                    DryRunEntry(
                        target_table=entry.target_table,
                        target_id=entry.target_id,
                        status=status,
                        field_changes=entry.field_changes,
                    )
                )
                if status == "would_update":
                    models[entry.target_table] = [
                        entry.new_row if row.get("id") == entry.target_id else row
                        for row in models[entry.target_table]
                    ]
            except SeedRowError:
                entries.append(
                    DryRunEntry(
                        target_table=entry.target_table,
                        target_id=entry.target_id,
                        status="row_missing",
                    )
                )
            except Exception:
                entries.append(
                    DryRunEntry(
                        target_table=entry.target_table,
                        target_id=entry.target_id,
                        status="invalid_row",
                    )
                )
        kb_constructs = False
        try:
            cards = [Card.model_validate(row) for row in models["cards"]]
            rules = [RewardRule.model_validate(row) for row in models["reward_rules"]]
            offers = [Offer.model_validate(row) for row in models["offers"]]
            vals = [PointValuation.model_validate(row) for row in models["point_valuations"]]
            card_ids = {card.id for card in cards}
            refs.extend(
                f"unknown card reference: {rule.card_id}"
                for rule in rules
                if rule.card_id not in card_ids
            )
            refs.extend(
                f"unknown card reference: {value.card_id}"
                for value in vals
                if value.card_id not in card_ids
            )
            kb_constructs = not refs and not any(
                entry.status != "would_update" for entry in entries
            )
            if kb_constructs:
                KnowledgeBase.from_models(
                    cards=cards, reward_rules=rules, offers=offers, point_valuations=vals
                )
        except Exception as error:
            refs.append(str(error))
        unchanged = all(
            self.rows.seed_file_sha256(table) == digest
            for table, (filename, _model) in SUPPORTED_TABLES.items()
            for digest in (bundle.seed_files[filename],)
        )
        applicable = (
            bundle.applicable
            and unchanged
            and not refs
            and all(entry.status == "would_update" for entry in entries)
        )
        return DryRunReport(
            bundle_sha256=bundle_sha256,
            entries=tuple(entries),
            kb_constructs=kb_constructs,
            reference_errors=tuple(refs),
            seed_files_unchanged=unchanged,
            applicable=applicable,
        )
