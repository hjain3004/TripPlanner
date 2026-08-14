import pytest

from agents.discovery.contracts import DiscoveryCandidate
from agents.discovery.integrity import (
    UnknownCandidate,
    assert_ids_returned_by_gateway,
    resolve_discovery_candidate,
)
from core.trip_models import DraftItinerary
from evals.test_i1_safety import _spec
from gateway.places.contracts import PlaceCandidate, PlaceClaim


class MockRegistry:
    def __init__(self, candidates=None):
        self.candidates = candidates or []

    def lookup_exact_or_alias(self, name: str):
        for c in self.candidates:
            if name == c.place_id or name == getattr(c, "mentioned_name", ""):
                return c
            # check alias
            for cl in getattr(c, "claims", []):
                if cl.field == "name" and cl.value == name:
                    return c
        return None

def compose_from(resolved_candidates: list[DiscoveryCandidate]) -> DraftItinerary:
    from core.trip_models import ItineraryDay, ItineraryItem
    items = []
    unverified = []
    for rc in resolved_candidates:
        if rc.verification_state == "unresolved":
            unverified.append(rc.mentioned_name)
        else:
            items.append(ItineraryItem(poi_id=rc.resolved_place_id))
    
    return DraftItinerary(
        hotel_area_id="dummy",
        days=[ItineraryDay(date=_spec().start_date, items=items)],
        notes=[],
        itinerary_quality="fallback",
        unverified_suggestions=unverified
    )

def scheduled_names(draft: DraftItinerary) -> set[str]:
    names = set()
    for d in draft.days:
        for item in d.items:
            names.add(item.poi_id)
    return names

def test_a_hallucinated_place_id_is_rejected() -> None:
    returned = {"pl_real_1", "pl_real_2"}
    with pytest.raises(UnknownCandidate, match="pl_invented"):
        assert_ids_returned_by_gateway(["pl_real_1", "pl_invented"], returned)


def test_a_remembered_name_resolves_only_through_an_exact_gateway_lookup() -> None:
    from datetime import UTC, datetime
    c = PlaceCandidate(
        place_id="pl_maxwell",
        status="live",
        claims=[
            PlaceClaim(
                place_id="pl_maxwell",
                field="name",
                value="Maxwell Food Centre",
                source_id="mock",
                source_url="",
                retrieved_at=datetime.now(UTC),
                last_verified=datetime.now(UTC),
                verified_by="mock",
                confidence=1.0,
                needs_verification=False,
                licence_id="mock"
            ),
            PlaceClaim(
                place_id="pl_maxwell",
                field="coordinates",
                value="coords",
                source_id="mock",
                source_url="",
                retrieved_at=datetime.now(UTC),
                last_verified=datetime.now(UTC),
                verified_by="mock",
                confidence=1.0,
                needs_verification=False,
                licence_id="mock"
            )
        ]
    )
    registry = MockRegistry([c])
    d = DiscoveryCandidate(mentioned_name="Maxwell Food Centre")
    resolved = resolve_discovery_candidate(d, registry)
    assert resolved.resolved_place_id is not None
    assert resolved.verification_state == "verified"


def test_an_unresolvable_name_is_excluded_from_the_schedule() -> None:
    """Spec 4: excluded from the committed schedule; may appear only as an
    explicitly unverified suggestion OUTSIDE the plan."""
    registry = MockRegistry([])
    d = DiscoveryCandidate(mentioned_name="Restaurant That Does Not Exist")
    resolved = resolve_discovery_candidate(d, registry)
    assert resolved.resolved_place_id is None
    assert resolved.verification_state == "unresolved"
    draft = compose_from(resolved_candidates=[resolved])
    assert "Restaurant That Does Not Exist" not in scheduled_names(draft)
    assert "Restaurant That Does Not Exist" in draft.unverified_suggestions


def test_alias_lookup_matches_a_known_alternate_name() -> None:
    from datetime import UTC, datetime
    c = PlaceCandidate(
        place_id="pl_maxwell",
        status="live",
        claims=[
            PlaceClaim(
                place_id="pl_maxwell",
                field="name",
                value="Maxwell Hawker Centre",
                source_id="mock",
                source_url="",
                retrieved_at=datetime.now(UTC),
                last_verified=datetime.now(UTC),
                verified_by="mock",
                confidence=1.0,
                needs_verification=False,
                licence_id="mock"
            ),
            PlaceClaim(
                place_id="pl_maxwell",
                field="coordinates",
                value="coords",
                source_id="mock",
                source_url="",
                retrieved_at=datetime.now(UTC),
                last_verified=datetime.now(UTC),
                verified_by="mock",
                confidence=1.0,
                needs_verification=False,
                licence_id="mock"
            )
        ]
    )
    registry = MockRegistry([c])
    d = DiscoveryCandidate(mentioned_name="Maxwell Hawker Centre")  # alias
    assert resolve_discovery_candidate(d, registry).resolved_place_id is not None


def test_a_candidate_below_minimum_evidence_is_not_committed() -> None:
    from datetime import UTC, datetime
    candidate_no_coordinates = PlaceCandidate(
        place_id="pl_incomplete",
        status="live",
        claims=[
            PlaceClaim(
                place_id="pl_incomplete",
                field="name",
                value="Incomplete",
                source_id="mock",
                source_url="",
                retrieved_at=datetime.now(UTC),
                last_verified=datetime.now(UTC),
                verified_by="mock",
                confidence=1.0,
                needs_verification=False,
                licence_id="mock"
            )
        ]
    )
    registry = MockRegistry([candidate_no_coordinates])
    resolved = resolve_discovery_candidate(
        DiscoveryCandidate(mentioned_name="Incomplete"), registry
    )
    assert resolved.verification_state == "unresolved"
