"""An operator-readable review packet: what each draft says, what it quotes, what is still open.

``inspect`` shows one proposal at a time. A curator preparing to decide wants the whole queue
at once: for every draft, the exact quote and offsets for each field, the current and proposed
values side by side, how old the capture is, what the row's provenance claims today, which
fields of the row the draft says nothing about (and so would leave unverified), and the decisions
that remain open. It reads the ingestion database and writes nothing, and it prepares no
decision: the commands it prints are templates with placeholders for the curator.

The packet contains verbatim quotations from captured documents. It is for the local operator and
must not be committed (the CLI refuses to write it inside a git checkout).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ingestion.contracts import PageKind, ProposalStatus
from ingestion.review import ReviewService
from ingestion.storage import FinancialIngestionStore
from ingestion.verification import required_fact_paths


class QueueField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    current: Any
    proposed: Any
    changed: bool
    quote: str | None = None
    quote_start: int | None = None
    quote_end: int | None = None
    quote_verified: bool | None = None


class QueueItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    target: str
    intent: str
    status: str
    version: int
    extractor_version: str
    snapshot_id: str | None
    captured_at: datetime | None
    capture_age_days: int | None
    source_policy_id: str | None
    page_kind: str | None
    row_provenance: str
    findings: list[str]
    fields: list[QueueField]
    unresolved_fields: list[str] = Field(default_factory=list)
    blocked_by: list[str]
    decisions: list[str]
    owner_actions: list[str]


def build_review_queue(
    *,
    store: FinancialIngestionStore,
    service: ReviewService,
    as_of: datetime,
    statuses: tuple[ProposalStatus, ...] = (ProposalStatus.PENDING,),
    data_dir_hint: str = "<DATA_DIR>",
) -> list[QueueItem]:
    items: list[QueueItem] = []
    for proposal in sorted(store.list_proposals(), key=lambda p: p.proposal_id):
        if proposal.status not in statuses:
            continue
        context = service.context(proposal.proposal_id)
        by_path = {e.span.field_path: e for e in context.evidence}
        diffs = {d.field_path: d for d in context.field_diffs}
        fields: list[QueueField] = []
        for field in proposal.field_proposals:
            diff = diffs.get(field.field_path)
            evidence = by_path.get(field.field_path)
            fields.append(
                QueueField(
                    field_path=field.field_path,
                    current=diff.current if diff else field.old_value,
                    proposed=diff.proposed if diff else field.parsed_value,
                    changed=bool(diff.changed) if diff else field.old_value != field.parsed_value,
                    quote=evidence.span.quote if evidence else None,
                    quote_start=evidence.span.normalized_start if evidence else None,
                    quote_end=evidence.span.normalized_end if evidence else None,
                    quote_verified=evidence.verified if evidence else None,
                )
            )
        row = context.current_row or {}
        covered = {f.field_path for f in proposal.field_proposals}
        unresolved = [p for p in required_fact_paths(row) if p not in covered] if row else []
        lineage = context.lineage
        snapshot = lineage.snapshots[0] if lineage and lineage.snapshots else None
        manual = lineage is not None and lineage.watch_target.page_kind is PageKind.MANUAL_CAPTURE
        blocked = (["D1"] if unresolved else []) + (["D2"] if manual else [])
        prov = row.get("provenance") or {}
        pid = proposal.proposal_id
        items.append(
            QueueItem(
                proposal_id=pid,
                target=f"{proposal.target_table}/{proposal.target_id}",
                intent=proposal.intent,
                status=proposal.status.value,
                version=proposal.version,
                extractor_version=proposal.extractor_version,
                snapshot_id=snapshot.snapshot_id if snapshot else None,
                captured_at=snapshot.captured_at if snapshot else None,
                capture_age_days=(as_of - snapshot.captured_at).days if snapshot else None,
                source_policy_id=lineage.source_policy.policy_id if lineage else None,
                page_kind=lineage.watch_target.page_kind.value if lineage else None,
                row_provenance=(
                    f"{prov.get('source_type')} / verified_by={prov.get('verified_by')} / "
                    f"needs_verification={prov.get('needs_verification')} / "
                    f"last_verified={prov.get('last_verified')}"
                ),
                findings=[
                    f"{f.severity}: {f.code}: {f.message}" for f in context.computed_findings
                ],
                fields=fields,
                unresolved_fields=unresolved,
                blocked_by=blocked,
                decisions=[
                    f"{d.status} by {d.reviewer_id} at {d.decided_at.isoformat()} "
                    f"({d.client_event_id})"
                    for d in context.decisions
                ],
                owner_actions=[
                    f"python -m ingestion.review_server inspect --data-dir {data_dir_hint} "
                    f"--proposal-id '{pid}'",
                    f"python -m ingestion.review_server decision --data-dir {data_dir_hint} "
                    f"--proposal-id '{pid}' --curator-id <YOUR_CURATOR_ID> "
                    f"--action <approve|edit|reject> --reason '<your reason>' "
                    f"--expected-version {proposal.version} --client-event-id <UNIQUE_ID> "
                    "--curator-confidence <0..1>",
                ],
            )
        )
    return items


def render_queue_markdown(items: list[QueueItem], *, as_of: datetime) -> str:
    lines = [
        "# Financial-data review queue",
        "",
        f"As of {as_of.isoformat()}. {len(items)} draft(s). **Nothing here is approved.** "
        "Quotes are verbatim from local captures: keep this file out of Git.",
        "",
    ]
    for item in items:
        taken = item.captured_at.isoformat() if item.captured_at else "unknown"
        lines += [
            f"## {item.target}  ({item.status}, v{item.version})",
            "",
            f"* proposal: `{item.proposal_id}`",
            f"* source: policy `{item.source_policy_id}`, page kind `{item.page_kind}`, "
            f"extractor `{item.extractor_version}`",
            f"* capture: `{item.snapshot_id}` taken {taken} "
            f"({item.capture_age_days} days before this packet)",
            f"* row provenance today: {item.row_provenance}",
            f"* blocked from verification by: {', '.join(item.blocked_by) or 'nothing'}",
        ]
        lines += [f"* finding: {finding}" for finding in item.findings]
        lines += [
            "",
            "| field | current | proposed | changed | quote (offsets) |",
            "|---|---|---|---|---|",
        ]
        for f in item.fields:
            where = f"{f.quote_start}-{f.quote_end}, verified={f.quote_verified}"
            quote = (f.quote or "").replace("|", "\\|").replace("\n", " ").replace("\t", " ")
            lines.append(
                f"| `{f.field_path}` | {f.current} | {f.proposed} | {'yes' if f.changed else 'no'} "
                f"| “{quote}” ({where}) |"
            )
        unresolved = ", ".join(f"`{p}`" for p in item.unresolved_fields) or "none"
        lines += [
            "",
            f"Left unverified by this draft (it quotes nothing for them): {unresolved}",
            "",
        ]
        if item.decisions:
            lines += ["Decisions so far: " + "; ".join(item.decisions), ""]
        lines += ["Owner actions (templates, not run):", ""]
        lines += [f"    {a}" for a in item.owner_actions]
        lines.append("")
    return "\n".join(lines)
