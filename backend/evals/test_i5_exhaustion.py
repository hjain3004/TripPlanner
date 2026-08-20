
from agents.discovery.contracts import SearchIntent
from agents.discovery.controller import run_discovery
from agents.llm import ScriptedLLMClient
from core.trip_models import DraftItinerary
from evals.test_i1_safety import _spec
from gateway.places.contracts import PlaceCandidate, PlaceClaim, PlaceSearchRequest
from gateway.places.registry import PlaceGatewayError


class MockRegistry:
    def __init__(self, mode="success"):
        self.mode = mode
        
    def execute(self, req: PlaceSearchRequest):
        if self.mode == "fail":
            raise PlaceGatewayError("provider_unavailable", "Failed")
        elif self.mode == "empty":
            return []
        else:
            from datetime import UTC, datetime
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





def create_mock_llm(always_requests_another_search=False):
    from datetime import date

    from core.trip_models import ItineraryDay
    if always_requests_another_search:
        intent = SearchIntent(query_text="mock", destination_area_id="mock", round_index=0)
        return ScriptedLLMClient({"planner": [intent.model_dump()] * 10})
    else:
        day = ItineraryDay(date=date(2026, 8, 1), items=[])
        dump = DraftItinerary(hotel_area_id="mock", days=[day]).model_dump()
        return ScriptedLLMClient({"planner": [dump]})


def run_pipeline(spec, registry, execute_callback):
    # run discovery and then compose
    result = run_discovery(spec, registry, execute_callback)
    from evals.test_i5_integrity import DiscoveryCandidate, compose_from
    resolved = []
    for c in result.committed_candidates:
        dc = DiscoveryCandidate(mentioned_name="Mock")
        dc.resolved_place_id = c.place_id
        dc.verification_state = "verified"
        resolved.append(dc)
    
    class FakeResult:
        def __init__(self, it):
            self.itinerary = it
            
    return FakeResult(compose_from(resolved))

def test_budget_exhaustion_returns_a_typed_partial_result() -> None:
    llm = create_mock_llm(always_requests_another_search=True)
    def _execute(*args, **kwargs):
        return llm.complete_json(
            node="planner", system="", user="", schema=DraftItinerary, tools=[]
        )
        
    result = run_discovery(_spec(), MockRegistry(), _execute)
    assert result.partial is not None
    assert result.partial.unresolved_needs
    assert result.partial.stop_reason == "budget_exhausted"


def test_an_adapter_failure_falls_back_without_inventing_venues() -> None:
    llm = create_mock_llm(always_requests_another_search=True)
    def _execute(*args, **kwargs):
        return llm.complete_json(
            node="planner", system="", user="", schema=DraftItinerary, tools=[]
        )
        
    result = run_discovery(
        _spec(),
        MockRegistry(mode="fail"),
        _execute
    )
    assert result.partial is not None
    assert result.partial.stop_reason in ("provider_unavailable", "evidence_missing")
    assert all(c.place_id for c in result.committed_candidates)


def test_no_results_is_reported_as_an_unmet_need_not_an_empty_success() -> None:
    """Spec 12: 'Return the unmet need; do not invent a venue.'"""
    llm = create_mock_llm(always_requests_another_search=False)
    def _execute(*args, **kwargs):
        return llm.complete_json(
            node="planner", system="", user="", schema=DraftItinerary, tools=[]
        )
        
    result = run_discovery(
        _spec(),
        MockRegistry(mode="empty"),
        _execute
    )
    assert result.partial is not None
    assert result.partial.unresolved_needs
    assert result.committed_candidates == []


def test_the_pipeline_still_produces_a_plan_when_discovery_fails_entirely() -> None:
    """Spec 12: 'Compose from deterministic retrieval results; no extra hidden call site.'"""
    llm = create_mock_llm(always_requests_another_search=True)
    def _execute(*args, **kwargs):
        return llm.complete_json(
            node="planner", system="", user="", schema=DraftItinerary, tools=[]
        )
        
    result = run_pipeline(
        _spec(),
        MockRegistry(mode="fail"),
        _execute
    )
    assert result.itinerary is not None
