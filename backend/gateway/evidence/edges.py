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
        self.edges.append(edge)

    def has_node(self, node_id: str) -> bool:
        return (
            node_id in self.claims
            or node_id in self.sources
            or node_id in self.artifacts
            or node_id in self.runs
            or node_id in self.evaluations
        )
