"""Read-only report of every stored proposal and whether its approval can still be used.

An approval is reusable only while the base row it attested still holds. That rule already lives
in ``ActivationPlanner.entry_for`` (latest decision is an attested approval, the current row still
has the hash the proposal was made against, the resulting row matches the attestation); this
report asks it per proposal instead of restating it. It does not re-hash stored snapshots: like
bundling, it trusts the evidence store, whose integrity is checked when a bundle is built.
"""

from __future__ import annotations

from typing import Any

from ingestion.activation import ActivationPlanner
from ingestion.review import ReviewService
from ingestion.storage import FinancialIngestionStore


def build_status(
    *, store: FinancialIngestionStore, service: ReviewService, planner: ActivationPlanner
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for proposal in sorted(store.list_proposals(), key=lambda p: p.proposal_id):
        context = service.context(proposal.proposal_id)
        lineage = context.lineage
        snapshot = lineage.snapshots[0] if lineage and lineage.snapshots else None
        applies = False
        note: str | None
        if not context.decisions:
            note = "no approved decision: it is still awaiting a curator"
        else:
            try:
                planner.entry_for(proposal.proposal_id)
                applies, note = True, None
            except (ValueError, KeyError) as reason:
                note = f"the latest decision cannot be used: {reason}"
        items.append(
            {
                "proposal_id": proposal.proposal_id,
                "target_table": proposal.target_table,
                "target_id": proposal.target_id,
                "intent": proposal.intent,
                "review_status": proposal.status.value,
                "version": proposal.version,
                "extractor_version": proposal.extractor_version,
                "field_paths": [item.field_path for item in proposal.field_proposals],
                "snapshot_id": snapshot.snapshot_id if snapshot else None,
                "snapshot_captured_at": (
                    snapshot.captured_at.isoformat().replace("+00:00", "Z") if snapshot else None
                ),
                "source_policy_id": lineage.source_policy.policy_id if lineage else None,
                "page_kind": lineage.watch_target.page_kind.value if lineage else None,
                "decisions": [
                    {
                        "decision_id": decision.decision_id,
                        "reviewer_id": decision.reviewer_id,
                        "status": decision.status,
                        "decided_at": decision.decided_at.isoformat().replace("+00:00", "Z"),
                        "client_event_id": decision.client_event_id,
                    }
                    for decision in context.decisions
                ],
                "approval_applies": applies,
                "approval_note": note,
            }
        )
    return {"proposal_count": len(items), "proposals": items}
