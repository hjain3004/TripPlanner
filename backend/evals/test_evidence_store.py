from pathlib import Path

from gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from gateway.evidence.invariants import check_invariants
from gateway.evidence.nodes import Claim, LifecycleState, Source
from gateway.evidence.store import SqliteEvidenceStore


def test_round_trip_preserves_claims_and_edges(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a"))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)
    loaded = store.load(run_id="r1")

    assert loaded.claims["c-a"].payload["total_minor"] == 2450000
    assert loaded.sources["s-a"].provider == "adapter-a"
    assert any(e.kind is EdgeKind.SUPPORTS for e in loaded.edges)
    assert check_invariants(loaded) == []


def test_superseded_claims_survive_a_round_trip(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    """Invariant 4 must hold across persistence, not only in memory."""
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a.model_copy(update={
        "lifecycle": LifecycleState.SUPERSEDED, "superseded_by": "c-a2",
    }))
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-a2"}))
    g.add_edge(Edge(kind=EdgeKind.SUPERSEDES, src="c-a2", dst="c-a"))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)
    loaded = store.load(run_id="r1")

    assert loaded.claims["c-a"].lifecycle is LifecycleState.SUPERSEDED
    assert loaded.claims["c-a"].superseded_by == "c-a2"
    assert check_invariants(loaded) == []
