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

    from agents.discovery.controller import run_discovery
    
    class ScriptedLLMClient:
        def __init__(self, always_requests_another_search=True):
            self.always_requests_another_search = always_requests_another_search
            self.calls = 0
            
        def execute_planner(self, spec, registry, state, **kwargs):
            self.calls += 1
            if self.always_requests_another_search:
                state.record_call()
                return False  # False means continue searching
            return True # True means done
            
    llm = ScriptedLLMClient(always_requests_another_search=True)
    from evals.test_i1_safety import _spec
    spec = _spec()
    registry = None
    result = run_discovery(spec, registry, llm=llm)
    assert result.stop_reason in ("budget_exhausted", "rounds_exhausted")
    assert result.calls_made <= 6
