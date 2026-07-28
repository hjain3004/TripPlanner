import pytest

from gateway.evidence.edges import EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim, Source
from gateway.evidence.resolution import (
    flight_identity, resolve, unresolve,
)


def test_flight_identity_ignores_price(claim_a: Claim) -> None:
    """Two quotes for the same flight differ in price but share identity."""
    dearer = claim_a.model_copy(update={
        "payload": {**claim_a.payload, "total_minor": 2610000}
    })
    assert flight_identity(claim_a) == flight_identity(dearer)


def test_flight_identity_separates_different_cabins(claim_a: Claim) -> None:
    business = claim_a.model_copy(update={
        "payload": {**claim_a.payload, "cabin": "business"}
    })
    assert flight_identity(claim_a) != flight_identity(business)


def test_resolve_keeps_members_addressable(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))

    record = resolve(g, ["c-a", "c-b"], rule="exact_itinerary_match")

    assert record.canonical_id in ("c-a", "c-b")
    assert set(record.members) == {"c-a", "c-b"}
    assert "c-a" in g.claims and "c-b" in g.claims      # never deleted
    assert any(e.kind is EdgeKind.RESOLVED_TO for e in g.edges)


def test_unresolve_reverses_a_merge_without_rebuilding(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))
    record = resolve(g, ["c-a", "c-b"], rule="exact_itinerary_match")

    unresolve(g, record.resolution_id)

    assert not any(e.kind is EdgeKind.RESOLVED_TO for e in g.edges)
    assert "c-a" in g.claims and "c-b" in g.claims


def test_resolve_rejects_fewer_than_two_members(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    with pytest.raises(ValueError):
        resolve(g, ["c-a"], rule="exact_itinerary_match")
