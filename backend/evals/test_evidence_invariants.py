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

def test_superseded_by_missing_edge_is_a_violation(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    claim_a2 = claim_a.model_copy(update={"claim_id": "c-a2"})
    g.add_claim(claim_a.model_copy(update={
        "lifecycle": LifecycleState.SUPERSEDED, "superseded_by": "c-a2"
    }))
    g.add_claim(claim_a2)
    # Edge is missing intentionally
    violations = check_invariants(g)
    assert any("SUPERSEDES edge missing" in v for v in violations)

def test_supersedes_edge_missing_field_is_a_violation(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    claim_a2 = claim_a.model_copy(update={"claim_id": "c-a2"})
    g.add_claim(claim_a) # Field is intentionally missing
    g.add_claim(claim_a2)
    g.add_edge(Edge(kind=EdgeKind.SUPERSEDES, src="c-a2", dst="c-a"))
    violations = check_invariants(g)
    assert any("superseded_by field missing" in v for v in violations)

def test_artifact_can_derive_from_another_artifact(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    a1 = Artifact(artifact_id="a1", kind="OptimizerResult", run_id="r1",
                  version=1, derived_from=["c-a"])
    a2 = Artifact(artifact_id="a2", kind="CostedTrip", run_id="r1",
                  version=1, derived_from=["a1"])
    g.add_artifact(a1)
    g.add_artifact(a2)
    violations = check_invariants(g)
    assert violations == []

def test_artifact_can_derive_from_kb_facts(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    a1 = Artifact(artifact_id="a1", kind="OptimizerResult", run_id="r1",
                  version=1, derived_from=["c-a"],
                  derived_from_kb_facts=["card_rule_42"])
    g.add_artifact(a1)
    violations = check_invariants(g)
    assert violations == []
