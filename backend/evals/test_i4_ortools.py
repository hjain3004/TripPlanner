from datetime import UTC, date, datetime

from core.itinerary.contracts import ItineraryConstraints, RouteCell, RouteMatrix
from core.itinerary.ortools_composer import ORToolsComposer
from core.itinerary.validate import validate_draft
from core.models import UserWallet
from core.trip_models import TripSpec
from evals.test_i1_safety import _poi, _retrieval


def _matrix() -> RouteMatrix:
    return RouteMatrix(
        cells=[
            RouteCell(
                origin_place_id="p1",
                destination_place_id="p2",
                mode="transit",
                duration_min=15,
                distance_km=1,
                retrieved_at=datetime.now(UTC),
                source="geodesic_estimate",
                status="estimated",
                confidence=0.9,
            ),
            RouteCell(
                origin_place_id="p2",
                destination_place_id="p3",
                mode="transit",
                duration_min=20,
                distance_km=1.5,
                retrieved_at=datetime.now(UTC),
                source="geodesic_estimate",
                status="estimated",
                confidence=0.9,
            ),
            RouteCell(
                origin_place_id="p1",
                destination_place_id="p3",
                mode="transit",
                duration_min=30,
                distance_km=2,
                retrieved_at=datetime.now(UTC),
                source="geodesic_estimate",
                status="estimated",
                confidence=0.9,
            ),
        ]
    )


def test_ortools_composer_produces_valid_itinerary():
    s = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 7),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature"],
        pace="moderate",
        wallet=UserWallet(card_ids=[]),
    )
    ctx = _retrieval([_poi("p1"), _poi("p2"), _poi("p3")])
    composer = ORToolsComposer()
    result = composer.compose(s, ctx, _matrix(), ItineraryConstraints(max_daily_travel_min=120))

    valid = validate_draft(
        result.itinerary, _matrix(), ItineraryConstraints(max_daily_travel_min=120), ctx
    )
    assert valid.valid is True, f"Rejections: {valid.rejections}"


def test_ortools_composer_ignores_none_poi():
    s = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 7),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature"],
        pace="moderate",
        wallet=UserWallet(card_ids=[]),
    )
    # Give it multiple items, and since nodes=[None]+pois, the node at index 0 is None.
    # OR-Tools routing visits the depot (0) and then visits other nodes.
    # The fix ensures that poi is not None when reading node_index.
    ctx = _retrieval([_poi("p1")])
    composer = ORToolsComposer()
    result = composer.compose(s, ctx, _matrix(), ItineraryConstraints(max_daily_travel_min=120))
    assert len(result.itinerary.days) > 0

    # Needs to schedule at least something
    scheduled = [i.poi_id for d in result.itinerary.days for i in d.items]
    assert len(scheduled) > 0
