"""Tests for provider wire schema derivation and client-side validation.

Ensures that TripSpec, PlannerTurn, DraftItinerary, CriticVerdict,
ExplainerOutput, and SearchIntent all fit within Anthropic structured output limits
(optional parameters <= 24, anyOf <= 16) and round-trip successfully.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agents.discovery.contracts import SearchIntent
from agents.explainer import ExplainerOutput
from agents.llm_wire import (
    PlannerTurn,
    find_wire_problems,
    to_wire_schema,
    wire_schema_json,
)
from agents.models import CriticVerdict, TripSpec
from core.trip_models import DraftItinerary


def test_all_runtime_models_have_zero_wire_problems() -> None:
    models = [TripSpec, PlannerTurn, DraftItinerary, CriticVerdict, ExplainerOutput, SearchIntent]
    for model in models:
        schema = to_wire_schema(model)
        problems = find_wire_problems(schema)
        assert problems == [], f"{model.__name__} has wire problems: {problems}"


def test_planner_turn_round_trips_itinerary() -> None:
    wire_data = {
        "kind": "itinerary",
        "itinerary": {
            "hotel_area_id": "marina_bay",
            "days": [
                {
                    "date": "2026-11-15",
                    "items": [
                        {"poi_id": "gardens_by_the_bay", "start_hint": "morning"},
                        {"poi_id": "singapore_flyer"},
                    ],
                }
            ],
            "notes": ["Relaxed pace"],
        },
    }
    turn = PlannerTurn.model_validate(wire_data)
    assert turn.kind == "itinerary"
    assert turn.itinerary is not None
    assert turn.itinerary.hotel_area_id == "marina_bay"
    assert len(turn.itinerary.days) == 1
    assert turn.itinerary.days[0].items[0].poi_id == "gardens_by_the_bay"
    assert turn.search_intent is None


def test_planner_turn_round_trips_search_intent() -> None:
    wire_data = {
        "kind": "search",
        "search_intent": {
            "query_text": "vegetarian dining in Chinatown",
            "destination_area_id": "chinatown",
            "round_index": 0,
        },
    }
    turn = PlannerTurn.model_validate(wire_data)
    assert turn.kind == "search"
    assert turn.search_intent is not None
    assert turn.search_intent.query_text == "vegetarian dining in Chinatown"
    assert turn.search_intent.destination_area_id == "chinatown"
    assert turn.itinerary is None


def test_planner_turn_fails_on_mismatched_pairing() -> None:
    with pytest.raises(ValidationError):
        PlannerTurn.model_validate({"kind": "itinerary", "itinerary": None})

    with pytest.raises(ValidationError):
        PlannerTurn.model_validate(
            {
                "kind": "itinerary",
                "itinerary": {
                    "hotel_area_id": "marina_bay",
                    "days": [{"date": "2026-11-15", "items": [{"poi_id": "p1"}]}],
                },
                "search_intent": {
                    "query": "parks",
                    "category": "attraction",
                    "target_day_index": 0,
                },
            }
        )


def test_wire_schema_json_is_deterministic() -> None:
    s1 = wire_schema_json(PlannerTurn)
    s2 = wire_schema_json(PlannerTurn)
    assert s1 == s2
    assert "additionalProperties" in s1
