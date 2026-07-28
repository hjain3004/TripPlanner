from gateway.evidence.edges import EdgeKind, EvidenceGraph
from gateway.evidence.freshness import is_expired, mark_stale, supersede
from gateway.evidence.nodes import Claim, FreshnessState, LifecycleState, Source


def test_claim_expires_after_its_expiry_timestamp(claim_a: Claim) -> None:
    assert is_expired(claim_a, now="2026-10-12T10:19:00Z") is False
    assert is_expired(claim_a, now="2026-10-12T10:21:00Z") is True


def test_claim_without_expiry_never_expires(claim_a: Claim) -> None:
    no_expiry = claim_a.model_copy(update={"payload": {"total_minor": 1}})
    assert is_expired(no_expiry, now="2099-01-01T00:00:00Z") is False


def test_mark_stale_changes_status_but_keeps_the_claim(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    mark_stale(g, "c-a", now="2026-10-12T10:21:00Z")
    assert g.claims["c-a"].status is FreshnessState.STALE
    assert "c-a" in g.claims          # never deleted


def test_supersede_keeps_the_old_claim_addressable(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    replacement = claim_a.model_copy(update={
        "claim_id": "c-a2",
        "payload": {**claim_a.payload, "total_minor": 2510000},
    })
    supersede(g, old_id="c-a", new_claim=replacement)

    assert g.claims["c-a"].lifecycle is LifecycleState.SUPERSEDED
    assert g.claims["c-a"].superseded_by == "c-a2"
    assert g.claims["c-a2"].lifecycle is LifecycleState.ACTIVE
    assert any(
        e.kind is EdgeKind.SUPERSEDES and e.src == "c-a2" and e.dst == "c-a"
        for e in g.edges
    )
