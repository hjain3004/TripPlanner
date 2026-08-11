from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from gateway.evidence.nodes import (
    Artifact, Claim, Evaluation, Run, Source,
)


class EdgeKind(StrEnum):
    SUPPORTS = "SUPPORTS"           # source -> claim
    CONTRADICTS = "CONTRADICTS"     # claim <-> claim
    SUPERSEDES = "SUPERSEDES"       # claim -> claim
    RESOLVED_TO = "RESOLVED_TO"     # claim -> canonical claim
    DERIVED_FROM = "DERIVED_FROM"   # artifact -> claims consumed
    EVALUATED_BY = "EVALUATED_BY"   # claim|artifact -> evaluation


class Edge(BaseModel):
    kind: EdgeKind
    src: str = Field(min_length=1)
    dst: str = Field(min_length=1)
    created_by_run: str = Field(min_length=1)


class InvalidEdge(ValueError):
    """Raised when an edge's endpoints or direction violate its contract."""


class EvidenceGraph(BaseModel):
    """In-memory graph. Task 8 adds a SQLite-backed equivalent."""
    claims: dict[str, Claim] = Field(default_factory=dict)
    sources: dict[str, Source] = Field(default_factory=dict)
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    runs: dict[str, Run] = Field(default_factory=dict)
    evaluations: dict[str, Evaluation] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)

    def add_claim(self, claim: Claim) -> None:
        self.claims[claim.claim_id] = claim

    def add_source(self, source: Source) -> None:
        self.sources[source.source_id] = source

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts[artifact.artifact_id] = artifact

    def add_run(self, run: Run) -> None:
        self.runs[run.run_id] = run

    def add_evaluation(self, evaluation: Evaluation) -> None:
        self.evaluations[evaluation.evaluation_id] = evaluation

    def add_edge(self, edge: Edge) -> None:
        """Validate endpoints/direction, then add. Exact repeats (and, for
        CONTRADICTS, either orientation of the same pair) are a no-op."""
        violation = validate_edge_endpoints(self, edge)
        if violation is not None:
            raise InvalidEdge(violation)
        key = _edge_key(edge)
        if any(_edge_key(e) == key for e in self.edges):
            return
        self.edges.append(edge)

    def has_node(self, node_id: str) -> bool:
        return (
            node_id in self.claims
            or node_id in self.sources
            or node_id in self.artifacts
            or node_id in self.runs
            or node_id in self.evaluations
        )


def _node_kind(graph: EvidenceGraph, node_id: str) -> str | None:
    if node_id in graph.claims:
        return "claim"
    if node_id in graph.sources:
        return "source"
    if node_id in graph.artifacts:
        return "artifact"
    if node_id in graph.evaluations:
        return "evaluation"
    if node_id in graph.runs:
        return "run"
    return None


def validate_edge_endpoints(graph: EvidenceGraph, edge: Edge) -> str | None:
    """Return a violation message, or None if the edge is well-formed.

    Shared by EvidenceGraph.add_edge() (pre-mutation) and check_invariants()
    (post-hoc audit of graphs that may have bypassed add_edge, e.g. via
    model_copy or direct field assignment) — one classifier, not duplicated
    per caller.
    """
    src_kind = _node_kind(graph, edge.src)
    dst_kind = _node_kind(graph, edge.dst)
    if src_kind is None:
        return f"edge {edge.kind} has missing src {edge.src}"
    if dst_kind is None:
        return f"edge {edge.kind} has missing dst {edge.dst}"

    if edge.kind is EdgeKind.SUPPORTS:
        if src_kind != "source" or dst_kind != "claim":
            return f"SUPPORTS must be source -> claim, got {src_kind} -> {dst_kind}"
        claim = graph.claims[edge.dst]
        if claim.source_id != edge.src:
            return f"SUPPORTS edge {edge.src}->{edge.dst}: claim.source_id does not match"

    elif edge.kind is EdgeKind.CONTRADICTS:
        if src_kind != "claim" or dst_kind != "claim":
            return f"CONTRADICTS must be claim <-> claim, got {src_kind} -> {dst_kind}"
        if edge.src == edge.dst:
            return "CONTRADICTS requires two different claims"

    elif edge.kind is EdgeKind.SUPERSEDES:
        if src_kind != "claim" or dst_kind != "claim":
            return f"SUPERSEDES must be claim -> claim, got {src_kind} -> {dst_kind}"
        if edge.src == edge.dst:
            return "SUPERSEDES requires two different claims"

    elif edge.kind is EdgeKind.RESOLVED_TO:
        if src_kind != "claim" or dst_kind != "claim":
            return f"RESOLVED_TO must be claim -> claim, got {src_kind} -> {dst_kind}"
        if edge.src == edge.dst:
            return "RESOLVED_TO requires two different claims"

    elif edge.kind is EdgeKind.DERIVED_FROM:
        if src_kind != "artifact":
            return f"DERIVED_FROM must originate from an artifact, got {src_kind}"
        if dst_kind not in ("claim", "artifact"):
            return f"DERIVED_FROM must point to a claim or artifact, got {dst_kind}"
        if edge.src == edge.dst:
            return "DERIVED_FROM requires two different nodes"

    elif edge.kind is EdgeKind.EVALUATED_BY:
        if src_kind not in ("claim", "artifact"):
            return f"EVALUATED_BY must originate from a claim or artifact, got {src_kind}"
        if dst_kind != "evaluation":
            return f"EVALUATED_BY must point to an evaluation, got {dst_kind}"
        evaluation = graph.evaluations[edge.dst]
        if evaluation.subject_id != edge.src:
            return f"EVALUATED_BY edge {edge.src}->{edge.dst}: evaluation.subject_id does not match"

    return None


def _edge_key(edge: Edge) -> tuple[str, str, str]:
    """CONTRADICTS is symmetric: either orientation normalizes to the same
    key so reverse insertion is recognized as the same edge."""
    if edge.kind is EdgeKind.CONTRADICTS:
        a, b = sorted((edge.src, edge.dst))
        return (edge.kind.value, a, b)
    return (edge.kind.value, edge.src, edge.dst)
