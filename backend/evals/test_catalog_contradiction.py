from datetime import UTC, datetime

from gateway.catalog.claims import add_catalog_place_to_graph, select_claims
from gateway.evidence.edges import EvidenceGraph
from gateway.places.contracts import Place, PlaceClaim


def _c(field: str, value: str, source_id: str, release: str = "1") -> PlaceClaim:
    return PlaceClaim(
        place_id="pl_1",
        field=field,  # type: ignore
        value=value,
        source_id=source_id,
        source_url="http://x",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_release=release,
        last_verified=datetime(2026, 1, 1, tzinfo=UTC),
        verified_by="test",
        confidence=0.9,
        needs_verification=False,
        licence_id="L",
        attribution_requirements="A",
    )


overture_hours = [_c("opening_hours", "08:00-18:00", "overture_sg")]
osm_hours_conflicting = [_c("opening_hours", "09:00-17:00", "osm_sg")]
osm_hours = osm_hours_conflicting
official_hours = [_c("opening_hours", "10:00-16:00", "official_venue")]

wikivoyage_coords = [_c("coordinates", "1.28,103.8", "wikivoyage_sg")]
overture_coords = [_c("coordinates", "1.280,103.84", "overture_sg")]

wikivoyage_admission = [_c("admission", "Free", "wikivoyage_sg")]
claims_tied = [
    _c("name", "Cafe A", "osm_sg", "1"),
    _c("name", "Cafe B", "osm_sg", "1"),
    _c("name", "Cafe C", "osm_sg", "1"),
]


def test_conflicting_hours_from_two_sources_are_both_retained() -> None:
    """Spec 5.3: losing claims remain addressable."""
    winners, contradictions = select_claims(overture_hours + osm_hours_conflicting)
    assert len(contradictions) == 1
    assert len([c for c in winners if c.field == "opening_hours"]) == 1


def test_official_source_wins_hours_over_osm() -> None:
    """Spec 5.3 authority order for hours: official venue source, then current OSM."""
    winners, _ = select_claims(osm_hours + official_hours)
    hours = next(c for c in winners if c.field == "opening_hours")
    assert hours.source_id == "official_venue"


def test_overture_wins_coordinates_over_wikivoyage() -> None:
    winners, _ = select_claims(wikivoyage_coords + overture_coords)
    coords = next(c for c in winners if c.field == "coordinates")
    assert coords.source_id == "overture_sg"


def test_aggregator_admission_claim_is_never_trusted() -> None:
    """Spec 5.3: admission is official-source-only; other text is discovery-only."""
    winners, contradictions = select_claims(wikivoyage_admission)
    assert not [c for c in winners if c.field == "admission"]
    assert not contradictions


def test_contradiction_becomes_a_graph_edge() -> None:
    graph = EvidenceGraph()
    place = Place(place_id="pl_1", external_ids=[])
    conflicting_claims = overture_hours + osm_hours_conflicting
    add_catalog_place_to_graph(graph, place, conflicting_claims, run_id="r1")
    assert any(e.kind == "CONTRADICTS" for e in graph.edges)


def test_ties_are_broken_deterministically_not_by_input_order() -> None:
    a, _ = select_claims(claims_tied)
    b, _ = select_claims(list(reversed(claims_tied)))
    assert [(c.place_id, c.field, c.source_id) for c in a] == [
        (c.place_id, c.field, c.source_id) for c in b
    ]


def test_authority_recognizes_any_region_not_just_singapore() -> None:
    """I7 Task 7 finding: _AUTHORITY was a hardcoded ("overture_sg", "osm_sg")
    tuple. A real Mumbai build (source_id "overture_bom") lost every single
    claim silently - select_claims returned zero winners from 38,700 valid
    claims, because "overture_bom" != "overture_sg". Authority must recognize
    the provider family (overture/osm/wikivoyage), not one hardcoded region's
    literal source_id string."""
    mumbai_category = _c("category", "restaurant", "overture_bom")
    winners, _ = select_claims([mumbai_category])
    assert winners == [mumbai_category]

    mumbai_name = _c("name", "Cafe Mumbai", "osm_bom")
    winners, _ = select_claims([mumbai_name])
    assert winners == [mumbai_name]
