from datetime import date

import pytest
from pydantic import ValidationError

from gateway.evidence.edges import EdgeKind, EvidenceGraph
from gateway.evidence.identity import (
    AwardQuoteIdentity,
    FlightObservationIdentity,
    FlightQuoteIdentity,
    HotelQuoteIdentity,
    ReferenceFactIdentity,
)
from gateway.evidence.nodes import (
    Claim,
    FreshnessState,
    LifecycleState,
    ResolutionState,
    Source,
)
from gateway.evidence.resolution import resolve, unresolve

# --- Identity validation tests ---


def test_flight_quote_identity_constructs() -> None:
    ident = FlightQuoteIdentity(
        kind="flight_quote",
        segments=[
            {
                "origin": "DEL",
                "destination": "SIN",
                "departure_at": "2026-10-12T10:00:00Z",
                "arrival_at": "2026-10-12T16:00:00Z",
                "operating_carrier": "AI",
                "flight_number": "AI2384",
            }
        ],
        cabin="economy",
        fare_conditions="SAVER",
    )
    assert ident.kind == "flight_quote"


def test_flight_observation_identity_constructs() -> None:
    ident = FlightObservationIdentity(
        kind="flight_price_observation",
        provider="test",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 10, 12),
        return_date=None,
        cabin="economy",
        stops=0,
        observed_bucket="2026-10-11T10:00:00Z",
    )
    assert ident.kind == "flight_price_observation"


def test_hotel_quote_identity_constructs() -> None:
    ident = HotelQuoteIdentity(
        kind="hotel_quote",
        property_key="h1",
        check_in=date(2026, 10, 12),
        check_out=date(2026, 10, 15),
        occupancy_key="1r2a",
        room_type="deluxe",
        rate_plan="refundable",
    )
    assert ident.kind == "hotel_quote"


def test_award_quote_identity_constructs() -> None:
    ident = AwardQuoteIdentity(
        kind="award_quote",
        program_id="krisflyer",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 10, 12),
        return_date=None,
        cabin="economy",
        operating_carrier="SQ",
    )
    assert ident.kind == "award_quote"


def test_reference_fact_identity_constructs() -> None:
    ident = ReferenceFactIdentity(
        kind="reference_fact", namespace="poi", entity_id="sg-hawker", field="hours"
    )
    assert ident.kind == "reference_fact"


def test_empty_segment_tuple_rejected() -> None:
    with pytest.raises(ValidationError):
        FlightQuoteIdentity(
            kind="flight_quote", segments=[], cabin="economy", fare_conditions="SAVER"
        )


def test_naive_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        FlightQuoteIdentity(
            kind="flight_quote",
            segments=[
                {
                    "origin": "DEL",
                    "destination": "SIN",
                    "departure_at": "2026-10-12T10:00:00",  # naive
                    "arrival_at": "2026-10-12T16:00:00Z",
                    "operating_carrier": "AI",
                    "flight_number": "AI2384",
                }
            ],
            cabin="economy",
            fare_conditions="SAVER",
        )


# --- Resolution tests ---


def test_resolve_same_identity_with_different_prices_resolves(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    dearer = claim_a.model_copy(
        update={"claim_id": "c-b", "payload": {**claim_a.payload, "total_minor": 9999999}}
    )
    g.add_claim(dearer)
    record = resolve(g, ["c-a", "c-b"], created_by_run="r1")
    assert record.canonical_id in ("c-a", "c-b")


def test_resolve_different_cabin_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    ident = dict(claim_a.identity)
    ident["cabin"] = "business"
    other = claim_a.model_copy(update={"claim_id": "c-b", "identity": ident})
    g.add_claim(other)
    with pytest.raises(ValueError, match="claims do not have exact same identity"):
        resolve(g, ["c-a", "c-b"], created_by_run="r1")


def test_resolve_different_fare_conditions_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    ident = dict(claim_a.identity)
    ident["fare_conditions"] = "FLEX"
    other = claim_a.model_copy(update={"claim_id": "c-b", "identity": ident})
    g.add_claim(other)
    with pytest.raises(ValueError, match="claims do not have exact same identity"):
        resolve(g, ["c-a", "c-b"], created_by_run="r1")


def test_resolve_different_flight_segment_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    ident = dict(claim_a.identity)
    ident["segments"] = [
        {
            "origin": "BOM",
            "destination": "SIN",
            "departure_at": "2026-10-12T10:00:00Z",
            "arrival_at": "2026-10-12T16:00:00Z",
            "operating_carrier": "AI",
            "flight_number": "AI2384",
        }
    ]
    other = claim_a.model_copy(update={"claim_id": "c-b", "identity": ident})
    g.add_claim(other)
    with pytest.raises(ValueError, match="claims do not have exact same identity"):
        resolve(g, ["c-a", "c-b"], created_by_run="r1")


def test_resolve_different_hotel_rate_plan_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    h_ident1 = {
        "kind": "hotel_quote",
        "property_key": "h1",
        "check_in": "2026-10-12",
        "check_out": "2026-10-15",
        "occupancy_key": "1r2a",
        "room_type": "deluxe",
        "rate_plan": "refundable",
    }
    h_ident2 = {**h_ident1, "rate_plan": "non-refundable"}
    c1 = claim_a.model_copy(update={"claim_id": "c-1", "identity": h_ident1})
    c2 = claim_a.model_copy(update={"claim_id": "c-2", "identity": h_ident2})
    g.add_claim(c1)
    g.add_claim(c2)
    with pytest.raises(ValueError, match="claims do not have exact same identity"):
        resolve(g, ["c-1", "c-2"], created_by_run="r1")


def test_resolve_different_award_program_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    a_ident1 = {
        "kind": "award_quote",
        "program_id": "krisflyer",
        "origin": "DEL",
        "destination": "SIN",
        "depart_date": "2026-10-12",
        "return_date": None,
        "cabin": "economy",
        "operating_carrier": "SQ",
    }
    a_ident2 = {**a_ident1, "program_id": "aeroplan"}
    c1 = claim_a.model_copy(update={"claim_id": "c-1", "identity": a_ident1})
    c2 = claim_a.model_copy(update={"claim_id": "c-2", "identity": a_ident2})
    g.add_claim(c1)
    g.add_claim(c2)
    with pytest.raises(ValueError, match="claims do not have exact same identity"):
        resolve(g, ["c-1", "c-2"], created_by_run="r1")


def test_resolve_mixed_identity_kinds_reject(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    other = claim_a.model_copy(
        update={
            "claim_id": "c-b",
            "identity": {
                "kind": "reference_fact",
                "namespace": "x",
                "entity_id": "y",
                "field": "z",
            },
        }
    )
    g.add_claim(other)
    with pytest.raises(ValueError, match="claims do not have exact same identity"):
        resolve(g, ["c-a", "c-b"], created_by_run="r1")


def test_resolve_missing_claim_id_rejects_before_mutation(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    with pytest.raises(ValueError, match="missing claim c-b"):
        resolve(g, ["c-a", "c-b"], created_by_run="r1")
    assert not g.resolutions
    assert not g.edges


def test_resolve_duplicate_member_id_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    with pytest.raises(ValueError, match="duplicate member id"):
        resolve(g, ["c-a", "c-a"], created_by_run="r1")


def test_resolve_superseded_member_rejects(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    superseded = claim_a.model_copy(
        update={"claim_id": "c-b", "lifecycle": LifecycleState.SUPERSEDED, "superseded_by": "c-a"}
    )
    g.add_claim(superseded)
    with pytest.raises(ValueError, match="is superseded"):
        resolve(g, ["c-a", "c-b"], created_by_run="r1")


def test_resolve_keeps_members_addressable(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))

    record = resolve(g, ["c-a", "c-b"], created_by_run="r1")

    assert record.canonical_id in ("c-a", "c-b")
    assert set(record.members) == {"c-a", "c-b"}
    assert "c-a" in g.claims and "c-b" in g.claims
    assert record.resolution_id in g.resolutions


def test_unresolve_marks_reversed_and_removes_edges_idempotent(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))
    record = resolve(g, ["c-a", "c-b"], created_by_run="r1")

    unresolve(g, record.resolution_id, reversed_by_run="r2")

    assert record.state == ResolutionState.REVERSED
    assert record.reversed_by_run == "r2"
    assert not any(e.kind is EdgeKind.RESOLVED_TO for e in g.edges)

    # Idempotent
    unresolve(g, record.resolution_id, reversed_by_run="r3")
    assert record.reversed_by_run == "r3"


def test_resolve_member_input_order_does_not_change_canonical_choice(
    claim_a: Claim, source_a: Source
) -> None:
    g1 = EvidenceGraph()
    g1.add_source(source_a)
    c_a = claim_a.model_copy(update={"claim_id": "c-a"})
    c_b = claim_a.model_copy(update={"claim_id": "c-b"})
    g1.add_claim(c_a)
    g1.add_claim(c_b)

    g2 = EvidenceGraph()
    g2.add_source(source_a)
    g2.add_claim(c_a)
    g2.add_claim(c_b)

    r1 = resolve(g1, ["c-a", "c-b"], created_by_run="r1")
    r2 = resolve(g2, ["c-b", "c-a"], created_by_run="r1")

    assert r1.canonical_id == r2.canonical_id


def test_lexicographically_smaller_stale_or_unverified_claim_fails(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)

    # c-a is lexicographically smaller but STALE and verify_required=True
    c_stale = claim_a.model_copy(
        update={"claim_id": "c-a", "status": FreshnessState.STALE, "needs_verification": True}
    )

    # c-b is lexicographically larger but LIVE and verify_required=False
    c_live = claim_a.model_copy(
        update={"claim_id": "c-b", "status": FreshnessState.LIVE, "needs_verification": False}
    )

    g.add_claim(c_stale)
    g.add_claim(c_live)

    record = resolve(g, ["c-a", "c-b"], created_by_run="r1")
    assert record.canonical_id == "c-b"

def test_unresolve_preserves_shared_edges(claim_a: Claim) -> None:
    from gateway.evidence.resolution import resolve, unresolve
    from gateway.evidence.edges import EvidenceGraph
    
    g = EvidenceGraph()
    claim_1 = claim_a.model_copy(update={"claim_id": "c-1"})
    claim_2 = claim_a.model_copy(update={"claim_id": "c-2"})
    claim_canon = claim_a.model_copy(update={"claim_id": "c-canon"})
    
    g.add_claim(claim_1)
    g.add_claim(claim_2)
    g.add_claim(claim_canon)
    
    res1 = resolve(g, ["c-1", "c-2", "c-canon"], created_by_run="r1")
    # For testing unresolve overlapping, we need to bypass the resolve guard we are adding.
    # We will manually add a second resolution overlapping.
    from gateway.evidence.nodes import ResolutionRecord, LifecycleState
    res2 = ResolutionRecord(
        resolution_id="res:overlap",
        members=["c-2", "c-canon"],
        canonical_id=res1.canonical_id,
        state=LifecycleState.ACTIVE,
        created_by_run="r1",
        rule="exact_identity",
        confidence=1.0,
    )
    g.resolutions[res2.resolution_id] = res2
    
    unresolve(g, res1.resolution_id, reversed_by_run="r2")
    
    # c-2 -> canonical edge should survive for res2
    from gateway.evidence.edges import EdgeKind, Edge
    assert Edge(kind=EdgeKind.RESOLVED_TO, src="c-2", dst=res1.canonical_id, created_by_run="r1") in g.edges

def test_resolve_rejects_claim_in_active_resolution(claim_a: Claim) -> None:
    from gateway.evidence.resolution import resolve, ClaimAlreadyResolved
    from gateway.evidence.edges import EvidenceGraph
    
    g = EvidenceGraph()
    claim_1 = claim_a.model_copy(update={"claim_id": "c-1"})
    claim_canon1 = claim_a.model_copy(update={"claim_id": "c-canon1"})
    claim_canon2 = claim_a.model_copy(update={"claim_id": "c-canon2"})
    
    g.add_claim(claim_1)
    g.add_claim(claim_canon1)
    g.add_claim(claim_canon2)
    
    resolve(g, ["c-1", "c-canon1"], created_by_run="r1")
    
    import pytest
    with pytest.raises(ClaimAlreadyResolved) as exc:
        resolve(g, ["c-1", "c-canon2"], created_by_run="r2")
    assert "c-1" in str(exc.value)

