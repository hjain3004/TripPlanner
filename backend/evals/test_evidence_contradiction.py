from gateway.evidence.contradiction import (
    CONTRADICTION_THRESHOLD_BPS, detect_contradictions,
)
from gateway.evidence.edges import EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim, ClaimKind, Source


def test_same_flight_similar_price_is_not_a_contradiction(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)                                        # 2_450_000
    g.add_claim(claim_a.model_copy(update={
        "claim_id": "c-b",
        "payload": {**claim_a.payload, "total_minor": 2455000},  # +0.2%
    }))
    assert detect_contradictions(g, ["c-a", "c-b"], created_by_run="r1") == []


def test_same_flight_divergent_price_is_a_contradiction(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)                                        # 2_450_000
    g.add_claim(claim_a.model_copy(update={
        "claim_id": "c-b",
        "payload": {**claim_a.payload, "total_minor": 2610000},  # +6.5%
    }))
    edges = detect_contradictions(g, ["c-a", "c-b"], created_by_run="r1")
    assert len(edges) == 1
    assert edges[0].kind is EdgeKind.CONTRADICTS


def test_different_flights_are_never_contradictions(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={
        "claim_id": "c-b",
        "payload": {**claim_a.payload, "flight_number": "AI9999",
                    "total_minor": 9999000},
    }))
    assert detect_contradictions(g, ["c-a", "c-b"], created_by_run="r1") == []


def test_threshold_is_defined_per_kind() -> None:
    assert ClaimKind.CASH_QUOTE in CONTRADICTION_THRESHOLD_BPS
    assert CONTRADICTION_THRESHOLD_BPS[ClaimKind.CASH_QUOTE] > 0
