"""Deterministic, reversible entity resolution.

Identity keys implement spec 16 §10. No LLM participates: a model deciding two
prices are "the same" is money reasoning by the back door (design §2).
A merge is never a delete (design §4 invariant 4).
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim

_RESOLUTION_PREFIX = "res:"
_MEMBER_SEPARATOR = "|"


class ResolutionRecord(BaseModel):
    resolution_id: str = Field(min_length=1)
    members: list[str]
    canonical_id: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    created_by_run: str = Field(min_length=1)

    @field_validator("members")
    @classmethod
    def _at_least_two(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("a resolution needs at least two members")
        return v


def flight_identity(claim: Claim) -> tuple[str, ...]:
    """Spec 16 §10 flight identity. Deliberately excludes price."""
    p = claim.payload
    return (
        str(p.get("carrier", "")),
        str(p.get("flight_number", "")),
        str(p.get("depart_date", "")),
        str(p.get("cabin", "")),
        str(p.get("fare_conditions", "")),
    )


def resolve(
    graph: EvidenceGraph,
    claim_ids: list[str],
    rule: str,
    confidence: float = 1.0,
    run_id: str = "r1",
) -> ResolutionRecord:
    """Merge claims into a canonical one. Members remain addressable."""
    if len(claim_ids) < 2:
        raise ValueError("a resolution needs at least two members")

    members = sorted(claim_ids)
    canonical_id = members[0]                    # deterministic choice
    record = ResolutionRecord(
        resolution_id=_RESOLUTION_PREFIX + _MEMBER_SEPARATOR.join(members),
        members=members,
        canonical_id=canonical_id,
        rule=rule,
        confidence=confidence,
        created_by_run=run_id,
    )
    for member in members:
        if member != canonical_id:
            graph.add_edge(
                Edge(
                    kind=EdgeKind.RESOLVED_TO, src=member, dst=canonical_id,
                    created_by_run=run_id,
                )
            )
    return record


def unresolve(graph: EvidenceGraph, resolution_id: str) -> None:
    """Reverse a merge. Nothing is rebuilt because nothing was destroyed."""
    members = resolution_id.removeprefix(_RESOLUTION_PREFIX).split(_MEMBER_SEPARATOR)
    graph.edges = [
        e for e in graph.edges
        if not (e.kind is EdgeKind.RESOLVED_TO and e.src in members)
    ]
