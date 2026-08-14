from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field

from agents.discovery.contracts import BudgetExceeded, LoopBudget, LoopState, SearchIntent
from core.trip_models import DraftItinerary, TripSpec
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
    itinerary: DraftItinerary | None = None

def run_discovery(
    spec: TripSpec, 
    registry: Any, 
    execute_planner_call: Callable[[], DraftItinerary | SearchIntent | Any],
) -> DiscoveryResult:
    state = LoopState(budget=LoopBudget())
    
    try:
        while True:
            state.begin_round()
            
            from agents.discovery.tool import execute_search_places
            
            response = execute_planner_call()
            
            if isinstance(response, DraftItinerary):
                proposed_ids = [
                    item.poi_id
                    for day in response.days
                    for item in day.items
                    if str(item.poi_id).startswith("pl_")
                ]
                returned_ids = {c.place_id for c in state.retained}
                from agents.discovery.integrity import assert_ids_returned_by_gateway
                assert_ids_returned_by_gateway(proposed_ids, returned_ids)
                
                if not state.retained:
                    return DiscoveryResult(
                        committed_candidates=[],
                        partial=PartialDiscoveryResult(
                            unresolved_needs=["No places discovered"],
                            stop_reason="no_results"
                        ),
                        stop_reason="no_results",
                        calls_made=state.calls_made,
                        itinerary=response
                    )
                return DiscoveryResult(
                    committed_candidates=state.retained,
                    stop_reason="success",
                    calls_made=state.calls_made,
                    itinerary=response
                )
            
            # Must be a tool call intent
            if hasattr(response, "query_text"):
                state.record_call()
                candidates, _ = execute_search_places(response, registry, state)
                state.retain(candidates)
                # Note: The real system would rebuild the user prompt with new candidates here.
                # For the Kernel MVP, the loop does exactly one simulated pass (or zero) and exits.
                # Since we don't rebuild the prompt, the model shouldn't be asked to continue
                # if it just loops forever, but the budget handles exhaustion.
            else:
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
