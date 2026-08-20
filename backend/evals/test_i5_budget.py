import pytest

from agents.discovery.contracts import LoopBudget, LoopState
from agents.discovery.controller import BudgetExceeded
from gateway.places.contracts import PlaceCandidate


def candidate(i: int) -> PlaceCandidate:
    from datetime import UTC, datetime

    from gateway.places.contracts import PlaceClaim
    return PlaceCandidate(
        place_id=f"pl_{i}",
        status="live",
        claims=[
            PlaceClaim(
                place_id=f"pl_{i}",
                field="name",
                value=f"Place {i}",
                source_id="mock",
                source_url="",
                retrieved_at=datetime.now(UTC),
                last_verified=datetime.now(UTC),
                verified_by="mock",
                confidence=1.0,
                needs_verification=False,
                licence_id="mock"
            )
        ]
    )

shuffled_sixty = [
    candidate(i) for i in [
        13, 42, 7, 59, 1, 33, 25, 48, 19, 56, 3, 38, 22, 51, 8, 45, 16, 54,
        28, 5, 31, 11, 41, 14, 49, 21, 57, 36, 0, 39, 24, 53, 9, 44, 20, 50,
        10, 43, 17, 55, 30, 2, 34, 27, 47, 18, 52, 6, 37, 23, 46, 15, 58, 29,
        4, 32, 12, 40, 26, 35
    ]
]

def test_a_fourth_round_is_refused() -> None:
    state = LoopState(budget=LoopBudget())
    for _ in range(3):
        state.begin_round()
    with pytest.raises(BudgetExceeded, match="max_rounds"):
        state.begin_round()


def test_a_seventh_call_is_refused() -> None:
    state = LoopState(budget=LoopBudget())
    for _ in range(6):
        state.record_call()
    with pytest.raises(BudgetExceeded, match="max_calls"):
        state.record_call()


def test_retained_candidates_are_capped_at_forty() -> None:
    state = LoopState(budget=LoopBudget())
    state.retain([candidate(i) for i in range(60)])
    assert len(state.retained) == 40


def test_candidates_sent_to_the_composer_are_capped_per_day() -> None:
    state = LoopState(budget=LoopBudget())
    state.retain([candidate(i) for i in range(20)])
    selected = state.select_for_day(day_index=0)
    assert len(selected) <= 12


def test_truncation_is_deterministic_not_arbitrary() -> None:
    a = LoopState(budget=LoopBudget())
    a.retain(shuffled_sixty)
    
    b = LoopState(budget=LoopBudget())
    b.retain(list(reversed(shuffled_sixty)))
    
    assert [c.place_id for c in a.retained] == [c.place_id for c in b.retained]


def test_a_scripted_model_that_loops_forever_still_terminates() -> None:
    """The bound is enforced by code, not by the model's cooperation."""

    from datetime import UTC, datetime

    from agents.discovery.controller import run_discovery
    from agents.llm import ScriptedLLMClient
    from evals.test_i1_safety import _spec
    from gateway.places.contracts import PlaceCandidate, PlaceClaim
    
    class MockRegistry:
        def execute(self, req):
            return [PlaceCandidate(
                place_id="mock_id",
                status="live",
                claims=[
                    PlaceClaim(
                        place_id="mock_id",
                        field="name",
                        value="Mock",
                        source_id="mock",
                        source_url="",
                        retrieved_at=datetime.now(UTC),
                        last_verified=datetime.now(UTC),
                        verified_by="mock",
                        confidence=1.0,
                        needs_verification=False,
                        licence_id="mock"
                    )
                ]
            )]
            
    from agents.discovery.contracts import SearchIntent
    
    intent = SearchIntent(query_text="mock", destination_area_id="mock", round_index=0)
    # Feed exactly 10 intents. 10 > 6, so it must terminate at 6 (max_calls).
    llm = ScriptedLLMClient({
        "planner": [intent.model_dump()] * 10
    })
    
    def _execute(*args, **kwargs):
        from core.trip_models import DraftItinerary
        return llm.complete_json(
            node="planner", system="", user="", schema=DraftItinerary, tools=[]
        )
        
    result = run_discovery(_spec(), MockRegistry(), _execute)
    assert result.stop_reason in ("budget_exhausted", "rounds_exhausted")
    assert result.calls_made <= 6


def test_repairs_count_against_discovery_call_budget_and_refuse_seventh_call() -> None:
    """Every provider call (including schema repair retries) must count against max_calls=6."""
    from agents.discovery.contracts import SearchIntent
    from agents.discovery.controller import run_discovery
    from core.trip_models import DraftItinerary
    from evals.test_i1_safety import _spec

    class MockRegistry:
        def execute(self, req: object) -> list[object]:
            return []

    real_provider_calls = 0

    def alternating_execute(prompt: str) -> object:
        nonlocal real_provider_calls
        real_provider_calls += 1
        # Odd calls fail schema validation to trigger repair
        if real_provider_calls % 2 == 1:
            DraftItinerary.model_validate({"invalid_field": 123})
        # Even repair calls return a valid SearchIntent so the loop continues
        return SearchIntent(query_text="mock", destination_area_id="mock", round_index=0)

    result = run_discovery(_spec(), MockRegistry(), alternating_execute)
    assert result.stop_reason == "budget_exhausted"
    assert real_provider_calls == 6
    assert result.calls_made == 6

