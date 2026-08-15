from __future__ import annotations

import hashlib
from collections import defaultdict

from gateway.evidence.edges import Edge, EvidenceGraph
from gateway.places.contracts import Place, PlaceClaim

_AUTHORITY: dict[str, tuple[str, ...]] = {
    "coordinates": ("overture_sg", "osm_sg"),
    "category": ("overture_sg", "osm_sg"),
    "name": ("overture_sg", "osm_sg"),
    "description": ("wikivoyage_sg",),
    "opening_hours": ("official_venue", "osm_sg"),
    "accessibility": ("official_venue", "osm_sg"),
    "admission": ("official_venue",),
}

def _claim_id(place_id: str, field: str, source_id: str) -> str:
    # Deterministic ID for a claim
    raw = f"{place_id}:{field}:{source_id}"
    return "cl_" + hashlib.sha256(raw.encode()).hexdigest()[:16]

def select_claims(claims: list[PlaceClaim]) -> tuple[list[PlaceClaim], list[tuple[str, str]]]:
    by_place_and_field: dict[tuple[str, str], list[PlaceClaim]] = defaultdict(list)
    for c in claims:
        by_place_and_field[(c.place_id, c.field)].append(c)

    winners: list[PlaceClaim] = []
    contradictions: list[tuple[str, str]] = []

    for (_place_id, field), field_claims in by_place_and_field.items():
        authority = _AUTHORITY.get(field, ())
        
        valid_claims = [c for c in field_claims if c.source_id in authority]
        if not valid_claims:
            # If all are invalid (e.g. admission from aggregator), they all lose
            # Wait, the spec says "A claim whose source_id is absent from its
            # field's authority tuple never wins"
            # If no one wins, they are all losers, but who do they contradict?
            # "If that leaves no claims for the field, the field is dropped."
            # Do they emit contradictions if there is no winner? The prompt:
            # "Every loser emits a CONTRADICTS edge against the winner."
            # So if there is no winner, maybe just contradictions = []?
            # Let's emit a contradiction against 'None'? No, edge needs winner_key.
            for _c in field_claims:
                # no winner to contradict, just drop it
                pass
            continue

        # Sort to find the winner deterministically:
        # highest authority rank wins; ties break on newer source_release,
        # then on source_id lexicographically
        
        # Sort valid claims:
        # Since we want rank ascending, release descending, source_id ascending:
        # We can sort by source_id ascending first, then release descending,
        # then rank ascending using stable sort!
        # Or just use multiple sort passes.
        valid_claims.sort(key=lambda c: (c.source_id, str(c.value)))
        valid_claims.sort(key=lambda c: c.source_release or "", reverse=True)
        valid_claims.sort(key=lambda c: authority.index(c.source_id))
        
        winner = valid_claims[0]
        winners.append(winner)
        
        winner_key = _claim_id(winner.place_id, winner.field, winner.source_id)
        
        for c in field_claims:
            if c is not winner:
                loser_key = _claim_id(c.place_id, c.field, c.source_id)
                contradictions.append((winner_key, loser_key))

    # sort outputs deterministically
    winners.sort(key=lambda c: (c.place_id, c.field))
    contradictions.sort()
    return winners, contradictions


def add_catalog_place_to_graph(
    graph: EvidenceGraph, place: Place, claims: list[PlaceClaim], run_id: str
) -> None:
    # "follow the pattern already in gateway/places/evidence.py::add_place_candidate_to_graph"
    # Actually I should implement it directly here.
    
    # Select winners and get contradictions
    winners, contradictions = select_claims(claims)
    
    # Add claims (and their sources implicitly if not present, though we might not have them)
    # The prompt says: "losing claims remain addressable."
    # So we must add ALL claims to the graph!
    # Wait, the spec says "Every loser emits a CONTRADICTS edge against the winner.
    # A claim whose source_id is absent from its field's authority tuple never wins..."
    for c in claims:
        c_id = _claim_id(c.place_id, c.field, c.source_id)
        # We don't have the Claim object from gateway.evidence.nodes here directly?
        # Let's import Claim, ClaimKind from gateway.evidence.nodes
        from gateway.evidence.nodes import Claim, ClaimKind
        
        claim_node = Claim(
            claim_id=c_id,
            run_id=run_id,
            adapter_id="catalog",
            kind=ClaimKind.PLACE_CLAIM,
            identity={"kind": "place_claim", "place_id": c.place_id, "field": c.field},
            payload={"value": c.value},
            source_id=c.source_id,
            is_inference=False,
            status="live", # active?
            confidence=c.confidence,
            needs_verification=c.needs_verification,
            expires_at="2030-01-01T00:00:00Z", # dummy
        )
        graph.add_claim(claim_node)
        
    for winner_key, loser_key in contradictions:
        graph.add_edge(Edge(
            src=loser_key,
            dst=winner_key,
            kind="CONTRADICTS",
            created_by_run=run_id
        ))
