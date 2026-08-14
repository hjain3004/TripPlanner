# ruff: noqa: E501, E402
from datetime import date

from core.itinerary.compose import compose_itinerary
from core.itinerary.greedy import GreedyComposer
from evals.test_i1_safety import _poi, _retrieval, _spec


def test_invariance_case_1_excludes_closed_day() -> None:
    closed_mon = _poi(
        "sg-closed-monday",
        regular_hours={0: [], **{i: ["08:00-20:00"] for i in range(1, 7)}},
        area="chinatown",
    )
    always_open = _poi("sg-always-open", area="marina_bay")
    spec = _spec(start=date(2026, 8, 3), pace="moderate")
    ctx = _retrieval([closed_mon, always_open])
    
    legacy = compose_itinerary(spec, ctx)
    wrapped = GreedyComposer().compose(spec, ctx)
    assert wrapped.model_dump_json() == legacy.model_dump_json()

def test_invariance_case_2_allows_open_day() -> None:
    closed_mon = _poi(
        "sg-closed-monday",
        regular_hours={0: [], **{i: ["08:00-20:00"] for i in range(1, 7)}},
        area="marina_bay",
    )
    spec = _spec(start=date(2026, 8, 4), pace="moderate")
    ctx = _retrieval([closed_mon])
    
    legacy = compose_itinerary(spec, ctx)
    wrapped = GreedyComposer().compose(spec, ctx)
    assert wrapped.model_dump_json() == legacy.model_dump_json()

def test_invariance_case_3_returns_composer_result() -> None:
    poi = _poi("sg-test")
    spec = _spec()
    ctx = _retrieval([poi])
    
    legacy = compose_itinerary(spec, ctx)
    wrapped = GreedyComposer().compose(spec, ctx)
    assert wrapped.model_dump_json() == legacy.model_dump_json()

def test_invariance_case_4_determinism() -> None:
    pois = [
        _poi("a", lat=1.28, lon=103.86),
        _poi("b", lat=1.29, lon=103.87),
    ]
    spec = _spec()
    ctx = _retrieval(pois)
    
    legacy = compose_itinerary(spec, ctx)
    wrapped = GreedyComposer().compose(spec, ctx)
    assert wrapped.model_dump_json() == legacy.model_dump_json()
