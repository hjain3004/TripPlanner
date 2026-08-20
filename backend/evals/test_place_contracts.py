from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from gateway.places.contracts import (
    PartialPlaceResult,
    PlaceCandidate,
    PlaceClaim,
    PlaceSearchRequest,
)
from gateway.places.identity import ExternalId, PlaceIdentityData, resolve_place_identity


def test_external_id_namespace_validation() -> None:
    # Valid
    ext1 = ExternalId(namespace="overture", value="123")
    assert ext1.urn == "overture:123"

    ext2 = ExternalId(namespace="osm:node", value="456")
    assert ext2.urn == "osm:node/456"

    ext3 = ExternalId(namespace="wikidata", value="Q123")
    assert ext3.urn == "wikidata:Q123"

    # Invalid
    with pytest.raises(ValidationError):
        ExternalId(namespace="google", value="789")  # type: ignore


def test_places_sharing_exact_external_id_merge() -> None:
    p1 = PlaceIdentityData(
        name="Gardens by the Bay",
        category="attraction",
        external_ids=[ExternalId(namespace="osm:node", value="111")],
    )
    p2 = PlaceIdentityData(
        name="Gardens by the bay (Flower Dome)",
        category="attraction",
        external_ids=[ExternalId(namespace="osm:node", value="111")],
    )
    assert resolve_place_identity(p1, p2, distance_m=100.0) == "merge"


def test_places_with_similar_names_but_no_shared_id_do_not_merge() -> None:
    p1 = PlaceIdentityData(
        name="Gardens by the Bay",
        category="attraction",
        external_ids=[ExternalId(namespace="osm:node", value="111")],
    )
    p2 = PlaceIdentityData(
        name="Gardens by the Bay East",
        category="attraction",
        external_ids=[ExternalId(namespace="osm:node", value="222")],
    )
    # Similar name, same category, very close, but no shared ID -> ambiguous
    assert resolve_place_identity(p1, p2, distance_m=10.0) == "ambiguous"

    p3 = PlaceIdentityData(name="National Museum", category="museum", external_ids=[])
    p4 = PlaceIdentityData(name="National Museum of Art", category="museum", external_ids=[])
    assert resolve_place_identity(p3, p4, distance_m=40.0) == "ambiguous"


def test_ambiguous_match_is_retained_as_ambiguous() -> None:
    p1 = PlaceIdentityData(name="Starbucks", category="cafe", external_ids=[])
    p2 = PlaceIdentityData(name="Starbucks Reserve", category="cafe", external_ids=[])
    # They shouldn't silently merge
    assert resolve_place_identity(p1, p2, distance_m=10.0) == "ambiguous"


def test_claim_class_carries_full_provenance() -> None:
    now = datetime.now(UTC)
    claim = PlaceClaim(
        place_id="p1",
        field="coordinates",
        value={"lat": 1.2, "lon": 103.8},
        source_id="s1",
        source_url="https://example.com",
        retrieved_at=now,
        last_verified=now,
        verified_by="test",
        confidence=0.9,
        needs_verification=False,
        licence_id="CC-BY-4.0",
    )
    assert claim.licence_id == "CC-BY-4.0"


def test_claim_with_missing_licence_id_is_rejected() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        PlaceClaim(
            place_id="p1",
            field="coordinates",
            value={"lat": 1.2, "lon": 103.8},
            source_id="s1",
            source_url="https://example.com",
            retrieved_at=now,
            last_verified=now,
            verified_by="test",
            confidence=0.9,
            needs_verification=False,
            # licence_id missing
        )


def test_search_request_max_results_ceiling() -> None:
    with pytest.raises(ValidationError):
        PlaceSearchRequest(destination_area_id="a1", max_results=100)

    req = PlaceSearchRequest(destination_area_id="a1", max_results=50)
    assert req.max_results == 50


def test_place_candidate_roundtrips_through_json() -> None:
    now = datetime.now(UTC)
    claim = PlaceClaim(
        place_id="p1",
        field="category",
        value="museum",
        source_id="s1",
        source_url="https://example.com",
        retrieved_at=now,
        last_verified=now,
        verified_by="test",
        confidence=1.0,
        needs_verification=False,
        licence_id="CC0",
    )
    candidate = PlaceCandidate(place_id="p1", claims=[claim], status="live")

    js = candidate.model_dump_json()
    restored = PlaceCandidate.model_validate_json(js)

    assert restored.place_id == "p1"
    assert restored.claims[0].licence_id == "CC0"
    assert restored.claims[0].retrieved_at == now


def test_raw_provider_dict_cannot_be_constructed_as_place_candidate() -> None:
    raw_dict = {"id": "123", "name": "Museum", "lat": 1.0, "lon": 2.0}
    with pytest.raises(ValidationError):
        PlaceCandidate.model_validate(raw_dict)


def test_partial_result_carries_non_empty_stop_reason() -> None:
    pr = PartialPlaceResult(unresolved_needs=["missing category"], stop_reason="budget_exhausted")
    assert pr.stop_reason == "budget_exhausted"

    with pytest.raises(ValidationError):
        PartialPlaceResult(unresolved_needs=[], stop_reason="budget_exhausted")


def test_adapter_broadening_scope_is_rejected() -> None:
    req = PlaceSearchRequest(
        destination_area_id="a1", category_filters=["museum", "park"], max_results=10
    )
    now = datetime.now(UTC)
    claim = PlaceClaim(
        place_id="p1",
        field="category",
        value="restaurant",  # Not in the requested filters
        source_id="s1",
        source_url="https://example.com",
        retrieved_at=now,
        last_verified=now,
        verified_by="test",
        confidence=1.0,
        needs_verification=False,
        licence_id="CC0",
    )
    candidate = PlaceCandidate(place_id="p1", claims=[claim], status="live")

    from gateway.places.contracts import validate_adapter_response

    with pytest.raises(ValueError, match="Adapter broadened scope"):
        validate_adapter_response(req, candidate)
