from __future__ import annotations

from gateway.evidence.edges import Edge, EvidenceGraph
from gateway.evidence.identity import PlaceClaimIdentity
from gateway.evidence.nodes import Claim, Source
from gateway.places.contracts import PlaceCandidate


def add_place_candidate_to_graph(
    graph: EvidenceGraph, candidate: PlaceCandidate, run_id: str
) -> None:
    for pc in candidate.claims:
        source_id = pc.source_url
        if source_id not in graph.sources:
            graph.add_source(
                Source(
                    source_id=source_id,
                    run_id=run_id,
                    provider=pc.source_id,
                    adapter_id=pc.source_id,
                    retrieved_at=pc.retrieved_at,
                    source_url=pc.source_url,
                )
            )

        identity = PlaceClaimIdentity(kind="place_claim", place_id=pc.place_id, field=pc.field)
        # Find if claim already exists
        claim_node_id = None
        for nid, node in graph.claims.items():
            if node.identity == identity:
                claim_node_id = nid
                break

        if claim_node_id is None:
            from gateway.evidence.nodes import ClaimKind, FreshnessState

            claim_node_id = f"claim_{pc.place_id}_{pc.field}_{pc.source_id}"
            graph.add_claim(
                Claim(
                    claim_id=claim_node_id,
                    run_id=run_id,
                    adapter_id=pc.source_id,
                    kind=ClaimKind.PLACE_CLAIM,
                    identity=identity,
                    payload={"value": pc.value, "licence_id": pc.licence_id},
                    source_id=source_id,
                    is_inference=False,
                    status=FreshnessState.ESTIMATED
                    if pc.needs_verification
                    else FreshnessState.LIVE,
                    confidence=pc.confidence,
                    needs_verification=pc.needs_verification,
                )
            )

        graph.add_edge(
            Edge(src=source_id, dst=claim_node_id, kind="SUPPORTS", created_by_run=run_id)
        )
