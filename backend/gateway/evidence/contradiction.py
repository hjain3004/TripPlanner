"""Detect disagreement between claims about the same real-world thing.

Thresholds are named per-kind constants in basis points (design §11.2).
Comparing two prices against a threshold produces no monetary value and stores
none; this is not money math.
"""
from __future__ import annotations

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.nodes import ClaimKind


CONTRADICTION_THRESHOLD_BPS: dict[ClaimKind, int] = {
    ClaimKind.CASH_QUOTE: 200,          # 2.00%
    ClaimKind.PRICE_OBSERVATION: 1000,  # 10.00% — observations are noisier
    ClaimKind.AWARD_AVAILABILITY: 0,    # any mileage difference is material
}


def detect_contradictions(
    graph: EvidenceGraph, claim_ids: list[str], *, created_by_run: str
) -> list[Edge]:
    """Return CONTRADICTS edges for same-identity claims that disagree."""
    edges: list[Edge] = []
    ids = sorted(claim_ids)

    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1:]:
            left, right = graph.claims[left_id], graph.claims[right_id]
            if left.kind is not right.kind:
                continue
            threshold = CONTRADICTION_THRESHOLD_BPS.get(left.kind)
            if threshold is None:
                continue
            left_ident = left.identity.model_dump() if hasattr(left.identity, "model_dump") else left.identity
            right_ident = right.identity.model_dump() if hasattr(right.identity, "model_dump") else right.identity
            if left_ident != right_ident:
                continue

            base = left.payload.get("total_minor")
            other = right.payload.get("total_minor")
            if not isinstance(base, int) or not isinstance(other, int) or base == 0:
                continue

            delta_bps = abs(other - base) * 10_000 // base
            if delta_bps > threshold:
                edges.append(
                    Edge(
                        kind=EdgeKind.CONTRADICTS, src=left_id, dst=right_id,
                        created_by_run=created_by_run,
                    )
                )
    return edges
