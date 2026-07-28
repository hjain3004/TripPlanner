"""Freshness transitions and supersession. Implements spec 16 §8.

A superseded claim is never deleted (design §4 invariant 4).
"""
from __future__ import annotations

from datetime import datetime

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim, FreshnessState


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_expired(claim: Claim, now: str) -> bool:
    """True when the claim carries an expiry that has passed."""
    expires_at = claim.payload.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    return _parse(now) > _parse(expires_at)


def mark_stale(graph: EvidenceGraph, claim_id: str, now: str) -> None:
    """Transition an expired live claim to stale. Idempotent; never deletes."""
    claim = graph.claims[claim_id]
    if is_expired(claim, now) and claim.status is FreshnessState.LIVE:
        graph.claims[claim_id] = claim.model_copy(
            update={"status": FreshnessState.STALE}
        )


def supersede(graph: EvidenceGraph, old_id: str, new_claim: Claim) -> None:
    """Replace `old_id` with `new_claim`, keeping the old claim addressable."""
    old = graph.claims[old_id]
    graph.claims[old_id] = old.model_copy(update={
        "status": FreshnessState.SUPERSEDED,
        "superseded_by": new_claim.claim_id,
    })
    graph.add_claim(new_claim)
    graph.add_edge(
        Edge(kind=EdgeKind.SUPERSEDES, src=new_claim.claim_id, dst=old_id)
    )
