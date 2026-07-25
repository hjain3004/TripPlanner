from datetime import date

from agents.models import TripSpec
from agents.retrieval import retrieve_candidates
from core.db import load_kb
from core.models import OptimizationPrefs, UserWallet


def _spec(interests: list[str]) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=interests,
        pace="moderate",
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        optimization=OptimizationPrefs(),
    )


def test_retrieval_filters_to_destination_city_and_ranks_by_overlap() -> None:
    context = retrieve_candidates(_spec(["nature", "kids"]), load_kb())
    ids = [poi.id for poi in context.pois]
    assert ids[:2] == ["sg-gardens-by-the-bay", "sg-sentosa-skyline-luge"]
    assert {poi.city for poi in context.pois} == {"Singapore"}


def test_retrieval_returns_area_rows_and_compact_poi_rows() -> None:
    context = retrieve_candidates(_spec(["food"]), load_kb())
    assert any("chinatown" in row for row in context.area_rows)
    assert all("|" in row for row in context.poi_rows)


def test_retrieval_caps_and_is_repeatable() -> None:
    first = retrieve_candidates(_spec([]), load_kb(), limit=2)
    second = retrieve_candidates(_spec([]), load_kb(), limit=2)
    assert [poi.id for poi in first.pois] == [poi.id for poi in second.pois]
    assert len(first.pois) == 2
