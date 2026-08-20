from datetime import UTC, datetime

from core.itinerary.contracts import ItineraryConstraints, RouteCell, RouteMatrix
from core.itinerary.greedy import GreedyComposer, score_draft
from core.itinerary.ortools_composer import ORToolsComposer
from evals.test_i1_safety import _poi, _retrieval, _spec


def _matrix() -> RouteMatrix:
    return RouteMatrix(
        cells=[
            RouteCell(
                origin_place_id="a",
                destination_place_id="b",
                mode="transit",
                duration_min=15,
                distance_km=1,
                retrieved_at=datetime.now(UTC),
                source="geodesic_estimate",
                status="estimated",
                confidence=0.9,
            ),
        ]
    )


def test_ortools_outperforms_or_matches_greedy() -> None:
    s = _spec()
    pois = [_poi("a", lat=1.28, lon=103.86), _poi("b", lat=1.29, lon=103.87)]
    ctx = _retrieval(pois)
    constraints = ItineraryConstraints(max_daily_travel_min=120)
    matrix = _matrix()

    greedy_res = GreedyComposer().compose(s, ctx, matrix, constraints)
    ortools_res = ORToolsComposer().compose(s, ctx, matrix, constraints)

    greedy_score = score_draft(greedy_res.itinerary, matrix, constraints, ctx)
    ortools_score = score_draft(ortools_res.itinerary, matrix, constraints, ctx)

    assert ortools_score >= greedy_score, (
        f"ORTools ({ortools_score}) worse than Greedy ({greedy_score})"
    )
