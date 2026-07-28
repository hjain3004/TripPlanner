"""The four binding invariants (design §4).

1. Every claim has a source or is marked inference.   (field-level in Claim)
2. Every artifact names an authoring run and version. (field-level in Artifact)
3. Every evaluation names a rubric.                   (field-level in Evaluation)
4. Every superseded or resolved-away object remains addressable.

This module checks the graph-level parts. A violation of 1-3 here means a node
was built by a path that bypassed model validation, or a pointer dangles.
"""
from __future__ import annotations

from gateway.evidence.edges import EvidenceGraph


def check_invariants(graph: EvidenceGraph) -> list[str]:
    """Return human-readable violations. Empty list means the graph is sound."""
    violations: list[str] = []

    for claim_id, claim in graph.claims.items():
        if claim.source_id is None and not claim.is_inference:
            violations.append(
                f"invariant 1: claim {claim_id} has no source and is not inference"
            )
        if claim.source_id is not None and claim.source_id not in graph.sources:
            violations.append(
                f"invariant 1: claim {claim_id} cites missing source {claim.source_id}"
            )
        if claim.superseded_by is not None and not graph.has_node(claim.superseded_by):
            violations.append(
                f"invariant 4: claim {claim_id} superseded by missing "
                f"node {claim.superseded_by}"
            )

    for artifact_id, artifact in graph.artifacts.items():
        for claim_id in artifact.derived_from:
            if claim_id not in graph.claims:
                violations.append(
                    f"invariant 4: artifact {artifact_id} derived from missing "
                    f"claim {claim_id}"
                )

    for evaluation_id, evaluation in graph.evaluations.items():
        if not graph.has_node(evaluation.subject_id):
            violations.append(
                f"invariant 4: evaluation {evaluation_id} judges missing "
                f"subject {evaluation.subject_id}"
            )

    for edge in graph.edges:
        if not graph.has_node(edge.src):
            violations.append(f"edge {edge.kind} has missing src {edge.src}")
        if not graph.has_node(edge.dst):
            violations.append(f"edge {edge.kind} has missing dst {edge.dst}")

    return violations
