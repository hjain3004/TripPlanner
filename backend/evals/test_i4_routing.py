# ruff: noqa: E501, E402
from dataclasses import dataclass

from core.itinerary.routing import build_geodesic_matrix, build_geodesic_matrix_with_gaps


@dataclass
class FakePlace:
    id: str
    lat: float | None
    lon: float | None

three_places = [
    FakePlace("pl_1", 1.28, 103.85),
    FakePlace("pl_2", 1.29, 103.86),
    FakePlace("pl_3", 1.30, 103.87),
]

two_places = [
    FakePlace("pl_1", 1.28, 103.85),
    FakePlace("pl_2", 1.29, 103.86),
]

places_one_missing_coords = [
    FakePlace("pl_1", 1.28, 103.85),
    FakePlace("pl_nocoord", None, None),
    FakePlace("pl_2", 1.29, 103.86),
]

def test_every_generated_cell_is_marked_estimated() -> None:
    m = build_geodesic_matrix(three_places, mode="transit")
    assert all(c.status == "estimated" for c in m.cells)
    assert all(c.source == "geodesic_estimate" for c in m.cells)


def test_matrix_covers_every_ordered_pair() -> None:
    m = build_geodesic_matrix(three_places, mode="transit")
    assert m.duration_min("pl_1", "pl_2", "transit") is not None
    assert m.duration_min("pl_2", "pl_3", "transit") is not None


def test_durations_match_the_existing_i1_estimator_exactly() -> None:
    """I4 must not silently re-tune I1's travel constants."""
    from core.itinerary.compose import estimate_travel_min
    m = build_geodesic_matrix(two_places, mode="transit")
    expected = estimate_travel_min(1.28, 103.85, 1.29, 103.86)
    assert m.duration_min("pl_1", "pl_2", "transit") == expected


def test_matrix_construction_is_order_independent() -> None:
    a = build_geodesic_matrix(three_places, mode="transit")
    b = build_geodesic_matrix(list(reversed(three_places)), mode="transit")
    assert sorted(c.model_dump_json() for c in a.cells) == \
           sorted(c.model_dump_json() for c in b.cells)


def test_a_place_without_coordinates_is_reported_not_guessed() -> None:
    m, unroutable = build_geodesic_matrix_with_gaps(places_one_missing_coords, mode="transit")
    assert "pl_nocoord" in unroutable
