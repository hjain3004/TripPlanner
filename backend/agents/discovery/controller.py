from typing import Any

from pydantic import BaseModel, Field

from agents.discovery.contracts import BudgetExceeded, LoopBudget, LoopState
from core.trip_models import TripSpec
from gateway.places.contracts import PlaceCandidate
from gateway.places.registry import PlaceGatewayError


class PartialDiscoveryResult(BaseModel):
    unresolved_needs: list[str] = Field(default_factory=list)
    stop_reason: str

class DiscoveryResult(BaseModel):
    committed_candidates: list[PlaceCandidate] = Field(default_factory=list)
    partial: PartialDiscoveryResult | None = None
    stop_reason: str = "success"
    calls_made: int = 0

def run_discovery(spec: TripSpec, registry: Any, llm: Any) -> DiscoveryResult:
    state = LoopState(budget=LoopBudget())
    
    try:
        while True:
            state.begin_round()
            
            # Simulated model loop. In reality, we would call the LLM, and the LLM
            # would call tools. If the LLM doesn't call tools or finishes its logic,
            # we break.
            if hasattr(llm, "execute_planner"):
                done = llm.execute_planner(spec, registry, state)
            else:
                done = True
            if done:
                break
    except BudgetExceeded:
        return DiscoveryResult(
            committed_candidates=state.retained,
            partial=PartialDiscoveryResult(
                unresolved_needs=["budget exceeded"],
                stop_reason="budget_exhausted"
            ),
            stop_reason="budget_exhausted",
            calls_made=state.calls_made
        )
    except PlaceGatewayError as e:
        return DiscoveryResult(
            committed_candidates=state.retained,
            partial=PartialDiscoveryResult(
                unresolved_needs=[e.message],
                stop_reason=e.code
            ),
            stop_reason=e.code,
            calls_made=state.calls_made
        )
        
        
    if not state.retained:
        return DiscoveryResult(
            committed_candidates=[],
            partial=PartialDiscoveryResult(
                unresolved_needs=["No places discovered"],
                stop_reason="no_results"
            ),
            stop_reason="no_results",
            calls_made=state.calls_made
        )
        
    return DiscoveryResult(
        committed_candidates=state.retained,
        stop_reason="success",
        calls_made=state.calls_made
    )
