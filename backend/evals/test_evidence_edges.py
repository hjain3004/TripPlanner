"""I0 Task 2: invalid and duplicate edges are unrepresentable."""

import pytest

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph, InvalidEdge
from gateway.evidence.nodes import (
    Artifact,
    Claim,
    Evaluation,
    Source,
)


def _artifact_a() -> Artifact:
    return Artifact(artifact_id="a-a", kind="CostedTrip", run_id="r1", version=1)


def _evaluation_a() -> Evaluation:
    return Evaluation(
        evaluation_id="ev-a",
        subject_id="c-a",
        rubric_id="freshness.v1",
        verdict="accept",
        reasons=[],
        run_id="r1",
    )


@pytest.fixture
def graph_a(claim_a: Claim, source_a: Source) -> EvidenceGraph:
    """A graph with one of each node kind, all sharing plausible IDs so every
    edge kind below has a real endpoint pair to exercise."""
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))
    g.add_artifact(_artifact_a())
    g.add_evaluation(_evaluation_a())
    return g


# --- Valid direction for each of the six edge kinds ------------------------ #


def test_supports_valid_direction(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_contradicts_valid_direction(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.CONTRADICTS, src="c-a", dst="c-b", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_supersedes_valid_direction(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.SUPERSEDES, src="c-b", dst="c-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_resolved_to_valid_direction(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.RESOLVED_TO, src="c-b", dst="c-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_derived_from_valid_direction_to_claim(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.DERIVED_FROM, src="a-a", dst="c-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_derived_from_valid_direction_to_artifact(graph_a: EvidenceGraph) -> None:
    a2 = Artifact(artifact_id="a-b", kind="OptimizerResult", run_id="r1", version=1)
    graph_a.add_artifact(a2)
    graph_a.add_edge(Edge(kind=EdgeKind.DERIVED_FROM, src="a-b", dst="a-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_evaluated_by_valid_direction(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.EVALUATED_BY, src="c-a", dst="ev-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


# --- Invalid direction for each of the six edge kinds ----------------------- #


def test_supports_rejects_reversed_direction(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge):
        graph_a.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="c-a", dst="s-a", created_by_run="r1"))


def test_contradicts_rejects_source_endpoint(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge):
        graph_a.add_edge(Edge(kind=EdgeKind.CONTRADICTS, src="s-a", dst="c-a", created_by_run="r1"))


def test_supersedes_rejects_source_endpoint(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge):
        graph_a.add_edge(Edge(kind=EdgeKind.SUPERSEDES, src="s-a", dst="c-a", created_by_run="r1"))


def test_resolved_to_rejects_self_loop(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge):
        graph_a.add_edge(Edge(kind=EdgeKind.RESOLVED_TO, src="c-a", dst="c-a", created_by_run="r1"))


def test_derived_from_rejects_claim_as_source(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge):
        graph_a.add_edge(
            Edge(kind=EdgeKind.DERIVED_FROM, src="c-a", dst="a-a", created_by_run="r1")
        )


def test_evaluated_by_rejects_evaluation_as_source(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge):
        graph_a.add_edge(
            Edge(kind=EdgeKind.EVALUATED_BY, src="ev-a", dst="c-a", created_by_run="r1")
        )


# --- Named required tests --------------------------------------------------- #


def test_add_edge_rejects_missing_endpoint(graph_a: EvidenceGraph) -> None:
    with pytest.raises(InvalidEdge) as exc:
        graph_a.add_edge(
            Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-ghost", created_by_run="r1")
        )
    assert "c-ghost" in str(exc.value)


def test_add_edge_is_idempotent_for_exact_duplicate(graph_a: EvidenceGraph) -> None:
    edge = Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a", created_by_run="r1")
    graph_a.add_edge(edge)
    graph_a.add_edge(edge)
    assert len(graph_a.edges) == 1


def test_contradiction_reverse_orientation_is_duplicate(graph_a: EvidenceGraph) -> None:
    graph_a.add_edge(Edge(kind=EdgeKind.CONTRADICTS, src="c-a", dst="c-b", created_by_run="r1"))
    graph_a.add_edge(Edge(kind=EdgeKind.CONTRADICTS, src="c-b", dst="c-a", created_by_run="r1"))
    assert len(graph_a.edges) == 1


def test_supports_requires_claim_source_pointer(graph_a: EvidenceGraph) -> None:
    """SUPPORTS is structurally source -> claim, but the claim's own
    source_id must also point back at that source."""
    other_source = Source(
        source_id="s-other",
        run_id="r1",
        provider="p",
        adapter_id="p",
        retrieved_at="2026-10-12T10:00:00Z",
        source_url="https://example.test/other",
        terms_ref=None,
    )
    graph_a.add_source(other_source)
    with pytest.raises(InvalidEdge) as exc:
        # claim_a.source_id == "s-a", not "s-other"
        graph_a.add_edge(
            Edge(kind=EdgeKind.SUPPORTS, src="s-other", dst="c-a", created_by_run="r1")
        )
    assert "source_id" in str(exc.value)


def test_evaluated_by_requires_matching_subject(graph_a: EvidenceGraph) -> None:
    """EVALUATED_BY is structurally claim|artifact -> evaluation, but the
    evaluation's own subject_id must match the edge's source."""
    with pytest.raises(InvalidEdge) as exc:
        # ev-a.subject_id == "c-a", not "c-b"
        graph_a.add_edge(
            Edge(kind=EdgeKind.EVALUATED_BY, src="c-b", dst="ev-a", created_by_run="r1")
        )
    assert "subject_id" in str(exc.value)


def test_invariant_audit_finds_edge_inserted_by_model_copy_bypass(
    graph_a: EvidenceGraph,
) -> None:
    """add_edge() validates; a graph rebuilt via model_copy (or direct field
    assignment) can bypass it entirely. check_invariants() must still catch
    a structurally invalid edge that slipped in that way."""
    from gateway.evidence.invariants import check_invariants

    bad_edge = Edge(kind=EdgeKind.SUPPORTS, src="c-a", dst="s-a", created_by_run="r1")
    bypassed = graph_a.model_copy(update={"edges": [bad_edge]})
    violations = check_invariants(bypassed)
    assert any("SUPPORTS" in v for v in violations)
