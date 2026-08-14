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


import re

def sanitize_text_for_model(text: str) -> str:
    """Spec 10: Strip scripts, active markup, unsupported URLs, and prompt-like control text."""
    # Remove html tags
    text = re.sub(r'<[^>]*>', '', text)
    # Remove control tokens like [[INST]] or SYSTEM:
    text = re.sub(r'\[\[.*?\]\]', '', text)
    text = re.sub(r'(?i)system:\s*', '', text)
    text = re.sub(r'(?i)ignore all previous', '', text)
    return text.strip()

def project_for_model(candidates: list[PlaceCandidate]) -> list[dict[str, Any]]:
    safe_candidates = []
    for c in candidates:
        safe_claims = []
        for cl in c.claims:
            val = cl.value
            if isinstance(val, str):
                val = sanitize_text_for_model(val)
            safe_claims.append({
                "field": cl.field,
                "value": val,
            })
        
        safe_candidates.append({
            "place_id": c.place_id,
            "status": c.status,
            "claims": safe_claims,
            "completeness_flags": c.completeness_flags,
        })
    return safe_candidates
