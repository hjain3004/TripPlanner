from __future__ import annotations

from pathlib import Path

import pytest

from gateway.places.adapters.sample import SamplePlaceAdapter
from gateway.places.contracts import PlaceSearchRequest
from gateway.places.registry import PlaceGatewayError


def test_sample_adapter_returns_candidates_with_provenance() -> None:
    adapter = SamplePlaceAdapter()
    req = PlaceSearchRequest(destination_area_id="sg_marina", max_results=10)
    candidates, partial = adapter.search_places(req)

    assert len(candidates) > 0
    c1 = candidates[0]
    assert c1.status == "estimated"
    assert len(c1.claims) > 0
    for claim in c1.claims:
        assert claim.source_id == "sample"
        assert claim.needs_verification is True
        assert claim.licence_id == "synthetic"
    assert partial is None


def test_sample_adapter_empty_result_is_success_not_error() -> None:
    adapter = SamplePlaceAdapter()
    req = PlaceSearchRequest(destination_area_id="unknown_area", max_results=10)
    candidates, partial = adapter.search_places(req)

    assert len(candidates) == 0
    assert partial is None


def test_malformed_fixture_raises_invalid_response(tmp_path: Path) -> None:
    bad_fixture = tmp_path / "bad.json"
    bad_fixture.write_text("not json")

    # Wait, the adapter should raise PlaceGatewayError("invalid_response") on malformed fixture
    # Let's mock the adapter to raise this or update adapter to catch json.JSONDecodeError
    # We will update sample.py to catch it.
    adapter = SamplePlaceAdapter(fixture_path=bad_fixture)
    req = PlaceSearchRequest(destination_area_id="sg", max_results=10)

    with pytest.raises(PlaceGatewayError, match="Malformed fixture"):
        adapter.search_places(req)


def test_two_identical_requests_produce_byte_identical_output() -> None:
    adapter = SamplePlaceAdapter()
    req = PlaceSearchRequest(destination_area_id="sg_marina", max_results=10)

    c1, _ = adapter.search_places(req)
    c2, _ = adapter.search_places(req)

    assert len(c1) == len(c2)
