"""Freshness transitions and supersession. Implements spec 16 §8.

A superseded claim is never deleted (design §4 invariant 4).
"""
from __future__ import annotations

from datetime import datetime

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim, FreshnessState, LifecycleState


def is_expired(claim: Claim, now: datetime) -> bool:
    """True when the claim carries an expiry that now has reached or passed.

    Exact-instant equality counts as expired: evidence is live only while
    now < expires_at (spec 16 §8).
    """
    if claim.expires_at is None:
        return False
    return now >= claim.expires_at


def mark_stale(graph: EvidenceGraph, claim_id: str, now: datetime) -> None:
    """Transition an expired live claim to stale. Idempotent; never deletes."""
    claim = graph.claims[claim_id]
    if claim.lifecycle == LifecycleState.ACTIVE and is_expired(claim, now) and claim.status is FreshnessState.LIVE:
        graph.claims[claim_id] = claim.model_copy(
            update={"status": FreshnessState.STALE}
        )


def supersede(graph: EvidenceGraph, old_id: str, new_claim: Claim) -> None:
    """Replace `old_id` with `new_claim`, keeping the old claim addressable."""
    old = graph.claims[old_id]
    graph.claims[old_id] = old.model_copy(update={
        "lifecycle": LifecycleState.SUPERSEDED,
        "superseded_by": new_claim.claim_id,
    })
    graph.add_claim(new_claim)
    graph.add_edge(
        Edge(kind=EdgeKind.SUPERSEDES, src=new_claim.claim_id, dst=old_id)
    )
