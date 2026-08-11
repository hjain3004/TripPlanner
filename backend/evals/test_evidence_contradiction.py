from gateway.evidence.contradiction import (
    CONTRADICTION_THRESHOLD_BPS,
    detect_contradictions,
)
from gateway.evidence.edges import EdgeKind, EvidenceGraph
from gateway.evidence.nodes import Claim, ClaimKind, Source


def test_same_flight_similar_price_is_not_a_contradiction(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)  # 2_450_000
    g.add_claim(
        claim_a.model_copy(
            update={
                "claim_id": "c-b",
                "payload": {**claim_a.payload, "total_minor": 2455000},  # +0.2%
            }
        )
    )
    res = detect_contradictions(g, ["c-a", "c-b"], created_by_run="r1")
    assert res.edges == []


def test_same_flight_divergent_price_is_a_contradiction(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)  # 2_450_000
    g.add_claim(
        claim_a.model_copy(
            update={
                "claim_id": "c-b",
                "payload": {**claim_a.payload, "total_minor": 2610000},  # +6.5%
            }
        )
    )
    res = detect_contradictions(g, ["c-a", "c-b"], created_by_run="r1")
    assert len(res.edges) == 1
    assert res.edges[0].kind is EdgeKind.CONTRADICTS


def test_different_flights_are_never_contradictions(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    ident = dict(claim_a.identity)
    ident["segments"] = [
        {
            "origin": "DEL",
            "destination": "SIN",
            "departure_at": "2026-10-12T10:00:00Z",
            "arrival_at": "2026-10-12T16:00:00Z",
            "operating_carrier": "AI",
            "flight_number": "AI9999",
        }
    ]
    g.add_claim(
        claim_a.model_copy(
            update={
                "claim_id": "c-b",
                "identity": ident,
                "payload": {**claim_a.payload, "flight_number": "AI9999", "total_minor": 9999000},
            }
        )
    )
    res = detect_contradictions(g, ["c-a", "c-b"], created_by_run="r1")
    assert res.edges == []
    assert any("different identities" in s for s in res.skipped)


def test_threshold_is_defined_per_kind() -> None:
    assert ClaimKind.CASH_QUOTE in CONTRADICTION_THRESHOLD_BPS
    assert CONTRADICTION_THRESHOLD_BPS[ClaimKind.CASH_QUOTE] > 0


# --- New tests for Task 4 ---


def test_reversing_claim_ids_and_input_order_produces_same_result(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    c1 = claim_a.model_copy(
        update={"claim_id": "c-1", "payload": {**claim_a.payload, "total_minor": 100}}
    )
    c2 = claim_a.model_copy(
        update={"claim_id": "c-2", "payload": {**claim_a.payload, "total_minor": 150}}
    )  # 50% diff
    g.add_claim(c1)
    g.add_claim(c2)

    res1 = detect_contradictions(g, ["c-1", "c-2"], created_by_run="r1")
    res2 = detect_contradictions(g, ["c-2", "c-1"], created_by_run="r1")

    assert len(res1.edges) == 1
    assert len(res2.edges) == 1
    assert res1.edges[0] == res2.edges[0]


def test_award_claims_compare_points_required(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    ident = {
        "kind": "award_quote",
        "program_id": "krisflyer",
        "origin": "DEL",
        "destination": "SIN",
        "depart_date": "2026-10-12",
        "return_date": None,
        "cabin": "economy",
        "operating_carrier": "SQ",
    }
    c1 = claim_a.model_copy(
        update={
            "claim_id": "c-1",
            "kind": ClaimKind.AWARD_AVAILABILITY,
            "identity": ident,
            "payload": {"points_required": 10000},
        }
    )
    c2 = claim_a.model_copy(
        update={
            "claim_id": "c-2",
            "kind": ClaimKind.AWARD_AVAILABILITY,
            "identity": ident,
            "payload": {"points_required": 10001},
        }
    )
    g.add_claim(c1)
    g.add_claim(c2)

    res = detect_contradictions(g, ["c-1", "c-2"], created_by_run="r1")
    assert len(res.edges) == 1  # 0 bp threshold means any difference is a contradiction


def test_observations_and_current_quotes_never_compare(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    c1 = claim_a.model_copy(update={"claim_id": "c-1", "kind": ClaimKind.CASH_QUOTE})
    c2 = claim_a.model_copy(update={"claim_id": "c-2", "kind": ClaimKind.PRICE_OBSERVATION})
    g.add_claim(c1)
    g.add_claim(c2)

    res = detect_contradictions(g, ["c-1", "c-2"], created_by_run="r1")
    assert res.edges == []
    assert any("different kinds" in s for s in res.skipped)


def test_different_typed_identities_never_compare(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    # Even if they are both cash quotes, if identity structures differ
    c1 = claim_a.model_copy(update={"claim_id": "c-1"})
    c2 = claim_a.model_copy(
        update={
            "claim_id": "c-2",
            "identity": {
                "kind": "hotel_quote",
                "property_key": "h1",
                "check_in": "2026-10-12",
                "check_out": "2026-10-15",
                "occupancy_key": "1r2a",
                "room_type": "deluxe",
                "rate_plan": "refundable",
            },
        }
    )
    g.add_claim(c1)
    g.add_claim(c2)

    res = detect_contradictions(g, ["c-1", "c-2"], created_by_run="r1")
    assert res.edges == []
    assert any("different identities" in s for s in res.skipped)


def test_exact_threshold_does_not_contradict_one_bp_above_does(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    # Threshold for CASH_QUOTE is 200 bps (2%)
    base = 100_000
    exact = 102_000  # exactly 2% higher than 100_000. abs(102000-100000)*10000 / 100000 = 200
    above = 102_010  # slightly above 2% (201 bps)

    c1 = claim_a.model_copy(update={"claim_id": "c-1", "payload": {"total_minor": base}})
    c2 = claim_a.model_copy(update={"claim_id": "c-2", "payload": {"total_minor": exact}})
    c3 = claim_a.model_copy(update={"claim_id": "c-3", "payload": {"total_minor": above}})

    g.add_claim(c1)
    g.add_claim(c2)
    g.add_claim(c3)

    res_exact = detect_contradictions(g, ["c-1", "c-2"], created_by_run="r1")
    assert res_exact.edges == []

    res_above = detect_contradictions(g, ["c-1", "c-3"], created_by_run="r1")
    assert len(res_above.edges) == 1


def test_invalid_comparison_values_skipped(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)

    invalid_payloads = [
        {},  # missing
        {"total_minor": 0},  # zero
        {"total_minor": -5},  # negative
        {"total_minor": "100"},  # string
        {"total_minor": True},  # bool
    ]

    claims = []
    for i, payload in enumerate(invalid_payloads):
        c = claim_a.model_copy(update={"claim_id": f"c-{i}", "payload": payload})
        g.add_claim(c)
        claims.append(f"c-{i}")

    c_valid = claim_a.model_copy(update={"claim_id": "c-valid", "payload": {"total_minor": 100}})
    g.add_claim(c_valid)
    claims.append("c-valid")

    res = detect_contradictions(g, claims, created_by_run="r1")
    assert res.edges == []
    assert len(res.skipped) > 0
    assert any("invalid comparison value" in s for s in res.skipped)


def test_sandbox_and_reference_facts_unsupported(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    c1 = claim_a.model_copy(
        update={
            "claim_id": "c-1",
            "kind": ClaimKind.REFERENCE_FACT,
            "identity": {
                "kind": "reference_fact",
                "namespace": "x",
                "entity_id": "y",
                "field": "z",
            },
        }
    )
    c2 = claim_a.model_copy(
        update={
            "claim_id": "c-2",
            "kind": ClaimKind.REFERENCE_FACT,
            "identity": {
                "kind": "reference_fact",
                "namespace": "x",
                "entity_id": "y",
                "field": "z",
            },
        }
    )
    g.add_claim(c1)
    g.add_claim(c2)

    res = detect_contradictions(g, ["c-1", "c-2"], created_by_run="r1")
    assert res.edges == []
    assert any("unsupported kind" in s for s in res.skipped)
