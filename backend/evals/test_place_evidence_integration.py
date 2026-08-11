from __future__ import annotations

from pathlib import Path

from gateway.evidence.edges import EvidenceGraph
from gateway.evidence.identity import PlaceClaimIdentity
from gateway.evidence.invariants import check_invariants
from gateway.evidence.nodes import Artifact
from gateway.evidence.store import SqliteEvidenceStore
from gateway.places.adapters.sample import SamplePlaceAdapter
from gateway.places.contracts import PlaceSearchRequest
from gateway.places.evidence import add_place_candidate_to_graph


def test_sample_search_populates_graph_and_passes_invariants() -> None:
    adapter = SamplePlaceAdapter()
    req = PlaceSearchRequest(destination_area_id="sg_marina", max_results=10)
    candidates, _ = adapter.search_places(req)

    graph = EvidenceGraph()
    run_id = "run_1"
    for candidate in candidates:
        add_place_candidate_to_graph(graph, candidate, run_id)

    # Invariants must pass
    check_invariants(graph)
    assert len(graph.claims) > 0


def test_claims_about_different_fields_do_not_resolve_as_duplicates() -> None:
    c1 = PlaceClaimIdentity(kind="place_claim", place_id="p1", field="category")
    c2 = PlaceClaimIdentity(kind="place_claim", place_id="p1", field="coordinates")
    assert c1 != c2


def test_claims_about_same_field_from_different_sources_do_compare() -> None:
    c1 = PlaceClaimIdentity(kind="place_claim", place_id="p1", field="category")
    c2 = PlaceClaimIdentity(kind="place_claim", place_id="p1", field="category")
    assert c1 == c2


def test_graph_round_trips_through_sqlite_evidence_store(tmp_path: Path) -> None:
    adapter = SamplePlaceAdapter()
    req = PlaceSearchRequest(destination_area_id="sg_marina", max_results=2)
    candidates, _ = adapter.search_places(req)

    graph = EvidenceGraph()
    add_place_candidate_to_graph(graph, candidates[0], "run_1")

    db_path = tmp_path / "evidence.sqlite"
    store = SqliteEvidenceStore(db_path)
    store.save(graph)

    loaded = store.load("run_1")
    assert len(loaded.claims) == len(graph.claims)
    assert len(loaded.edges) == len(graph.edges)

    # Check that a PlaceClaimIdentity is loaded correctly
    place_claims = [n for n in loaded.claims.values() if isinstance(n.identity, PlaceClaimIdentity)]
    assert len(place_claims) > 0


def test_every_scheduled_stop_resolves_to_a_claim() -> None:
    graph = EvidenceGraph()
    adapter = SamplePlaceAdapter()
    req = PlaceSearchRequest(destination_area_id="sg_marina", max_results=1)
    candidates, _ = adapter.search_places(req)
    add_place_candidate_to_graph(graph, candidates[0], "run_1")

    # Suppose we schedule this place
    stop_artifact = Artifact(artifact_id="item_1", kind="itinerary_item", run_id="run_1", version=1)
    graph.add_artifact(stop_artifact)

    # Find the category or coordinate claim for this place
    claim_id = next(
        nid
        for nid, node in graph.claims.items()
        if getattr(node.identity, "place_id", None) == candidates[0].place_id
    )
    from gateway.evidence.edges import Edge

    graph.add_edge(Edge(src="item_1", dst=claim_id, kind="DERIVED_FROM", created_by_run="run_1"))
    check_invariants(graph)
