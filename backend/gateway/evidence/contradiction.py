"""Detect disagreement between claims about the same real-world thing.

Thresholds are named per-kind constants in basis points (design §11.2).
Comparing two prices against a threshold produces no monetary value and stores
none; this is not money math.
"""

from __future__ import annotations

import itertools
from typing import Any

from pydantic import BaseModel

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.nodes import ClaimKind

CONTRADICTION_THRESHOLD_BPS: dict[ClaimKind, int] = {
    ClaimKind.CASH_QUOTE: 200,  # 2.00%
    ClaimKind.PRICE_OBSERVATION: 1000,  # 10.00% — observations are noisier
    ClaimKind.AWARD_AVAILABILITY: 0,  # any mileage difference is material
}


class ContradictionResult(BaseModel):
    edges: list[Edge]
    skipped: list[str]


def detect_contradictions(
    graph: EvidenceGraph, claim_ids: list[str], *, created_by_run: str
) -> ContradictionResult:
    """Return CONTRADICTS edges for same-identity claims that disagree."""
    edges: list[Edge] = []
    skipped: list[str] = []
    ids = sorted(claim_ids)

    for left_id, right_id in itertools.combinations(ids, 2):
        left, right = graph.claims[left_id], graph.claims[right_id]

        if left.kind is not right.kind:
            skipped.append(f"{left_id} and {right_id}: different kinds")
            continue

        threshold = CONTRADICTION_THRESHOLD_BPS.get(left.kind)
        if threshold is None:
            skipped.append(f"{left_id} and {right_id}: unsupported kind {left.kind}")
            continue

        left_ident = (
            left.identity.model_dump() if hasattr(left.identity, "model_dump") else left.identity
        )
        right_ident = (
            right.identity.model_dump() if hasattr(right.identity, "model_dump") else right.identity
        )
        if left_ident != right_ident:
            skipped.append(f"{left_id} and {right_id}: different identities")
            continue

        field = "points_required" if left.kind == ClaimKind.AWARD_AVAILABILITY else "total_minor"

        base: Any = left.payload.get(field)
        other: Any = right.payload.get(field)

        if not isinstance(base, int) or isinstance(base, bool) or base <= 0:
            skipped.append(f"{left_id}: invalid comparison value")
            continue
        if not isinstance(other, int) or isinstance(other, bool) or other <= 0:
            skipped.append(f"{right_id}: invalid comparison value")
            continue

        delta_bps = abs(base - other) * 10_000 // min(base, other)
        if delta_bps > threshold:
            edges.append(
                Edge(
                    kind=EdgeKind.CONTRADICTS,
                    src=left_id,
                    dst=right_id,
                    created_by_run=created_by_run,
                )
            )

    return ContradictionResult(edges=edges, skipped=skipped)
