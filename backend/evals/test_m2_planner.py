from datetime import date

from agents.llm import ScriptedLLMClient
from agents.models import TripSpec
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
    seen = [item.poi_id for day in result.itinerary.days for item in day.items]
    assert len(seen) == len(set(seen))
    assert result.itinerary.itinerary_quality == "fallback"

def test_planner_rejects_overlapping_and_falls_back_after_retry() -> None:
    spec = _spec()
    overlapping = {
        **_valid_itinerary(),
        "days": [
            {
                "date": "2026-08-01",
                "items": [
                    {"poi_id": "sg-gardens-by-the-bay", "start_hint": "10:00"},
                    {"poi_id": "sg-hawker-maxwell", "start_hint": "10:30"}
                ]
            }
        ]
    }
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient({"planner": [overlapping, overlapping]}),
    )
    assert result.used_fallback is True
    assert result.itinerary.itinerary_quality == "fallback"


def test_planner_rejects_closed_day_and_falls_back_after_retry() -> None:
    """sg-hawker-maxwell is closed on Mondays (core/seeds/pois.yaml:
    regular_hours 0: []). 2026-08-03 is a Monday and is inside this trip's
    window (start 2026-08-01, nights=4 -> valid dates 08-01..08-04)."""
    spec = _spec()
    closed_day = {
        **_valid_itinerary(),
        "days": [
            {
                "date": "2026-08-03",
                "items": [{"poi_id": "sg-hawker-maxwell", "start_hint": "12:00"}],
            }
        ],
    }
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient({"planner": [closed_day, closed_day]}),
    )
    assert result.used_fallback is True
    assert result.itinerary.itinerary_quality == "fallback"


def test_planner_rejects_travel_budget_exceeded_and_falls_back_after_retry() -> None:
    """Zigzagging between all 4 seed POIs in one day totals ~99 estimated
    travel minutes (verified via core.itinerary.compose.day_travel_minutes),
    which exceeds the 90-minute "relaxed" pace budget. All 4 POIs are open
    all week, so only the travel budget is exercised here."""
    spec = _spec().model_copy(update={"pace": "relaxed"})
    over_budget = {
        **_valid_itinerary(),
        "days": [
            {
                "date": "2026-08-01",
                "items": [
                    {"poi_id": "sg-gardens-by-the-bay"},
                    {"poi_id": "sg-sentosa-skyline-luge"},
                    {"poi_id": "sg-marina-bay-sands-skypark"},
                    {"poi_id": "sg-hawker-maxwell"},
                ],
            }
        ],
    }
    result = run_planner(
        spec,
        retrieve_candidates(spec, load_kb()),
        ScriptedLLMClient({"planner": [over_budget, over_budget]}),
    )
    assert result.used_fallback is True
    assert result.itinerary.itinerary_quality == "fallback"
