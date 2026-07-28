from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.invariants import check_invariants
from gateway.evidence.nodes import (
    Artifact, Claim, Evaluation, LifecycleState, Source,
)


def test_clean_graph_has_no_violations(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a"))
    assert check_invariants(g) == []


def test_dangling_superseded_pointer_is_a_violation(
    claim_a: Claim, source_a: Source
) -> None:
    """Invariant 4: a superseded object must remain addressable."""
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a.model_copy(update={
        "lifecycle": LifecycleState.SUPERSEDED, "superseded_by": "c-missing",
    }))
    violations = check_invariants(g)
    assert any("c-missing" in v for v in violations)


def test_artifact_with_unknown_derived_from_is_a_violation(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_artifact(Artifact(artifact_id="a1", kind="CostedTrip", run_id="r1",
                            version=1, derived_from=["c-a", "c-nope"]))
    violations = check_invariants(g)
    assert any("c-nope" in v for v in violations)


def test_evaluation_of_unknown_subject_is_a_violation() -> None:
    g = EvidenceGraph()
    g.add_evaluation(Evaluation(evaluation_id="e1", subject_id="c-ghost",
                                rubric_id="freshness.v1", verdict="reject",
                                reasons=["expired"]))
    violations = check_invariants(g)
    assert any("c-ghost" in v for v in violations)
