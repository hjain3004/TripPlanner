from typing import Any

from agents.discovery.contracts import LoopState, SearchIntent
from gateway.places.contracts import PlaceCandidate, PlaceSearchRequest


SEARCH_PLACES_TOOL = {
    "name": "search_places",
    "description": "Search for places and venues to add to the itinerary.",
    "parameters": {
        "type": "object",
        "properties": {
            "query_text": {"type": "string"},
            "destination_area_id": {"type": "string"}
        },
        "required": ["query_text", "destination_area_id"],
    },
}

MODEL_TOOLS = [SEARCH_PLACES_TOOL]


class SearchExecutionResult:
    def __init__(self, candidates: list[PlaceCandidate], adapter_selected_by: str) -> None:
        self.candidates = candidates
        self.adapter_selected_by = adapter_selected_by


def execute_search_places(
    intent: SearchIntent, registry: Any, state: LoopState
) -> tuple[list[PlaceCandidate], SearchExecutionResult]:
    # Real implementation would call the gateway here.
    res = SearchExecutionResult([], adapter_selected_by="registry")
    return [], res


def project_for_model(candidates: list[PlaceCandidate]) -> list[dict[str, Any]]:
    # Filter out anything with source_url or http
    # Specifically, only return safe fields
    safe_candidates = []
    for c in candidates:
        safe_claims = []
        for cl in c.claims:
            safe_claims.append({
                "field": cl.field,
                "value": cl.value,
            })
        
        safe_candidates.append({
            "place_id": c.place_id,
            "status": c.status,
            "claims": safe_claims,
            "completeness_flags": c.completeness_flags,
        })
    return safe_candidates
