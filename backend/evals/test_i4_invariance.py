from datetime import UTC, date, datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from core.itinerary.contracts import ItineraryConstraints, RouteCell, RouteMatrix
from core.itinerary.greedy import GreedyComposer
from core.itinerary.validate import validate_draft
from evals.test_i1_safety import _poi, _retrieval, _spec


def _make_competing_candidates():
    return [
        _poi("p1", tags=["nature", "must_do_tag"], lat=1.28, lon=103.86),
        _poi("p2", tags=["nature"], lat=1.29, lon=103.87),
        _poi("p3", tags=["nature", "must_do_tag"], lat=1.30, lon=103.88),
        _poi("p4", tags=["nature"], lat=1.31, lon=103.89),
        _poi("p5", tags=["nature", "must_do_tag"], lat=1.32, lon=103.90),
        _poi("p6", tags=["nature"], lat=1.33, lon=103.91),
        _poi("p7", tags=["nature", "must_do_tag"], lat=1.34, lon=103.92),
        _poi("p8", tags=["nature"], lat=1.35, lon=103.93),
    ]


COMPETING_CANDIDATES = _make_competing_candidates()


def _matrix(pois):
    cells = []
    for p1 in pois:
        for p2 in pois:
            if p1.id != p2.id:
                cells.append(
                    RouteCell(
                        origin_place_id=p1.id,
                        destination_place_id=p2.id,
                        mode="transit",
                        duration_min=45,
                        distance_km=5,
                        retrieved_at=datetime.now(UTC),
                        source="geodesic_estimate",
                        status="estimated",
                        confidence=0.9,
                    )
                )
    return RouteMatrix(cells=cells)


def test_the_fixture_candidates_actually_compete():
    s = _spec().model_copy(
        update={"pace": "moderate", "start_date": date(2026, 8, 3), "end_date": date(2026, 8, 6)}
    )
    ctx = _retrieval(COMPETING_CANDIDATES)
    matrix = _matrix(COMPETING_CANDIDATES)
    constraints = ItineraryConstraints(max_daily_travel_min=120)

    result = GreedyComposer().compose(s, ctx, matrix, constraints)
    scheduled = {i.poi_id for d in result.itinerary.days for i in d.items}

    print(f"\nScheduled {len(scheduled)} out of {len(COMPETING_CANDIDATES)}")
    assert len(scheduled) < len(COMPETING_CANDIDATES), (
        "every candidate fit — they do not compete, so invariance is untested"
    )


@settings(max_examples=50, deadline=None)
@given(order=st.permutations(range(8)))
def test_validity_is_invariant_under_candidate_ordering(order):
    pois = [COMPETING_CANDIDATES[i] for i in order]
    s = _spec().model_copy(
        update={"pace": "moderate", "start_date": date(2026, 8, 3), "end_date": date(2026, 8, 6)}
    )
    ctx = _retrieval(pois)
    matrix = _matrix(pois)
    constraints = ItineraryConstraints(max_daily_travel_min=120)

    result = GreedyComposer().compose(s, ctx, matrix, constraints)
    validity = validate_draft(result.itinerary, matrix, constraints, ctx)
    assert validity.valid is True, (
        f"Ordering {order} produced invalid itinerary: {validity.rejections}"
    )


@settings(max_examples=50, deadline=None)
@given(order=st.permutations(range(8)))
def test_the_same_candidate_set_produces_the_same_itinerary(order):
    pois = [COMPETING_CANDIDATES[i] for i in order]
    s = _spec().model_copy(
        update={"pace": "moderate", "start_date": date(2026, 8, 3), "end_date": date(2026, 8, 6)}
    )
    ctx = _retrieval(pois)
    matrix = _matrix(pois)
    constraints = ItineraryConstraints(max_daily_travel_min=120)

    result1 = GreedyComposer().compose(s, ctx, matrix, constraints)

    # baseline is sorted order
    base_ctx = _retrieval(COMPETING_CANDIDATES)
    result2 = GreedyComposer().compose(s, base_ctx, matrix, constraints)

    assert result1.itinerary.model_dump_json() == result2.itinerary.model_dump_json(), (
        f"Ordering {order} produced a different itinerary"
    )
