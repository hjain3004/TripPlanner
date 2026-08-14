from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.itinerary.contracts import (
    ItineraryConstraints,
    ItineraryValidation,
    RouteCell,
    RouteMatrix,
)


def _cell(**over: object) -> RouteCell:
    base = dict(
        origin_place_id="pl_a", destination_place_id="pl_b", mode="transit",
        duration_min=18, distance_km=4.2, retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="geodesic_estimate", status="estimated", confidence=0.6,
    )
    base.update(over)
    return RouteCell(**base)  # type: ignore[arg-type]


def test_every_route_cell_carries_source_and_status() -> None:
    """Spec 8: each cell carries origin/destination, mode, duration, distance,
    retrieval time, source and confidence."""
    c = _cell()
    assert c.status == "estimated" and c.source and c.confidence is not None


def test_a_cell_cannot_claim_routed_status_without_a_routing_source() -> None:
    """Spec 5.3: 'An estimate is never labeled routed travel time.'"""
    with pytest.raises(ValidationError):
        _cell(status="routed", source="geodesic_estimate")


def test_route_matrix_lookup_is_symmetric_for_estimates() -> None:
    m = RouteMatrix(cells=[_cell()])
    assert m.duration_min("pl_a", "pl_b", "transit") == 18
    assert m.duration_min("pl_b", "pl_a", "transit") == 18


def test_missing_cell_returns_none_rather_than_zero() -> None:
    """A missing route must never silently read as 'no travel time'."""
    m = RouteMatrix(cells=[_cell()])
    assert m.duration_min("pl_a", "pl_zzz", "transit") is None


def test_constraints_reject_a_negative_travel_budget() -> None:
    with pytest.raises(ValidationError):
        ItineraryConstraints(max_daily_travel_min=-1)


def test_validation_result_lists_structured_reasons_not_prose() -> None:
    v = ItineraryValidation(
        valid=False,
        rejections=[{"code": "closed_day", "place_id": "pl_a", "detail": "closed Monday"}],
    )
    assert v.valid is False
    assert v.rejections[0].code == "closed_day"
