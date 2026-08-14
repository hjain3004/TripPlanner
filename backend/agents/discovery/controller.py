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
    execute_planner_call: Callable[[str], DraftItinerary | SearchIntent],
    base_prompt: str = ""
) -> DiscoveryResult:
    state = LoopState(budget=LoopBudget())
    
    try:
        while True:
            state.begin_round()
            
            import json

            from agents.discovery.tool import execute_search_places, project_for_model
            
            prompt = base_prompt
            if state.retained:
                safe_cands = project_for_model(state.retained)
                prompt += f"\n\nDiscovered Candidates:\n{json.dumps(safe_cands, indent=2)}"
                
            response = execute_planner_call(prompt)
            
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
