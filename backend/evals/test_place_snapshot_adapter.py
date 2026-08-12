from pathlib import Path

import pytest

from gateway.places.adapters.snapshot import SnapshotPlaceAdapter
from gateway.places.contracts import (
    PlaceSearchRequest,
    validate_adapter_response,
)
from gateway.places.registry import PlaceGatewayError


def test_snapshot_adapter_returns_candidates_from_the_active_catalog(
    active_catalog: Path,
) -> None:
    adapter = SnapshotPlaceAdapter(active_catalog)
    results, partial = adapter.search_places(
        PlaceSearchRequest(destination_area_id="sg", category_filters=["park"], max_results=10)
    )
    assert results and partial is None
    assert all(
        any(c.field == "category" and c.value == "park" for c in r.claims) for r in results
    )


def test_results_carry_licence_and_attribution_on_every_claim(active_catalog: Path) -> None:
    adapter = SnapshotPlaceAdapter(active_catalog)
    results, _ = adapter.search_places(
        PlaceSearchRequest(destination_area_id="sg", max_results=50)
    )
    for candidate in results:
        for claim in candidate.claims:
            assert claim.licence_id
            assert claim.attribution_requirements


def test_place_with_unknown_hours_is_verify_required_not_live(active_catalog: Path) -> None:
    """Spec 5.4 — the whole point of the phase."""
    adapter = SnapshotPlaceAdapter(active_catalog)
    results, _ = adapter.search_places(
        PlaceSearchRequest(destination_area_id="sg", max_results=50)
    )
    no_hours = [r for r in results if not any(c.field == "opening_hours" for c in r.claims)]
    assert no_hours
    assert all(r.status == "verify_required" for r in no_hours)


def test_adapter_never_broadens_the_requested_category(active_catalog: Path) -> None:
    request = PlaceSearchRequest(
        destination_area_id="sg", category_filters=["cafe"], max_results=10
    )
    adapter = SnapshotPlaceAdapter(active_catalog)
    results, _ = adapter.search_places(request)
    for r in results:
        validate_adapter_response(request, r)  # must not raise


def test_max_results_truncation_returns_a_partial_result(active_catalog: Path) -> None:
    adapter = SnapshotPlaceAdapter(active_catalog)
    results, partial = adapter.search_places(
        PlaceSearchRequest(destination_area_id="sg", max_results=1)
    )
    assert len(results) == 1
    assert partial is not None and partial.stop_reason == "budget_exhausted"


def test_missing_active_catalog_raises_a_typed_gateway_error(tmp_path: Path) -> None:
    adapter = SnapshotPlaceAdapter(tmp_path / "nope.json")
    with pytest.raises(PlaceGatewayError) as exc:
        adapter.search_places(PlaceSearchRequest(destination_area_id="sg", max_results=5))
    assert exc.value.code == "provider_unavailable"


def test_two_identical_searches_return_identical_results(active_catalog: Path) -> None:
    adapter = SnapshotPlaceAdapter(active_catalog)
    req = PlaceSearchRequest(destination_area_id="sg", max_results=20)
    a, _ = adapter.search_places(req)
    b, _ = adapter.search_places(req)
    assert [x.model_dump_json() for x in a] == [x.model_dump_json() for x in b]
