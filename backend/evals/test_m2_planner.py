from datetime import date

from agents.llm import ScriptedLLMClient
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec
from agents.planner import run_planner
from agents.retrieval import retrieve_candidates
from core.db import load_kb
from core.models import OptimizationPrefs, UserWallet


def _spec() -> TripSpec:
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
        interests=["nature", "food"],
        pace="moderate",
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        optimization=OptimizationPrefs(),
    )


def _valid_itinerary() -> dict[str, object]:
    return {
        "hotel_area_id": "marina_bay",
        "days": [
            {
                "date": "2026-08-01",
                "items": [{"poi_id": "sg-gardens-by-the-bay", "start_hint": "10:00"}],
            },
            {
                "date": "2026-08-02",
                "items": [{"poi_id": "sg-hawker-maxwell", "start_hint": "12:00"}],
            },
        ],
        "notes": ["clustered by area"],
    }


def test_planner_accepts_valid_referential_output() -> None:
    spec = _spec()
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient({"planner": [_valid_itinerary()]}),
    )
    assert result.used_fallback is False
    assert result.itinerary.hotel_area_id == "marina_bay"


def test_planner_repairs_unknown_poi_once() -> None:
    spec = _spec()
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient(
            {
                "planner": [
                    {
                        **_valid_itinerary(),
                        "days": [{"date": "2026-08-01", "items": [{"poi_id": "made-up"}]}],
                    },
                    _valid_itinerary(),
                ]
            }
        ),
    )
    assert result.repair_attempted is True
    assert result.used_fallback is False
    assert result.itinerary.days[0].items[0].poi_id == "sg-gardens-by-the-bay"


def test_planner_falls_back_after_exceptions() -> None:
    spec = _spec()
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient({"planner": [RuntimeError("planner down")]}),
    )
    assert result.used_fallback is True
    assert result.itinerary.itinerary_quality == "fallback"
    assert result.caveats


def test_planner_rejects_wrong_date_and_falls_back_after_retry() -> None:
    spec = _spec()
    bad = {
        **_valid_itinerary(),
        "days": [{"date": "2026-09-01", "items": [{"poi_id": "sg-gardens-by-the-bay"}]}],
    }
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient({"planner": [bad, bad]}),
    )
    assert result.used_fallback is True


def test_fallback_uses_curated_pois_without_duplicates() -> None:
    spec = _spec()
    result = run_planner(spec, retrieve_candidates(spec, load_kb()), ScriptedLLMClient({}))
    seen = [
        item.poi_id
        for day in result.itinerary.days
        for item in day.items
    ]
    assert len(seen) == len(set(seen))
    assert result.itinerary.itinerary_quality == "fallback"
