import pytest
from pydantic import BaseModel

from agents.discovery.controller import run_discovery
from gateway.places.contracts import PlaceCandidate, PlaceSearchRequest, PlaceClaim
from gateway.places.registry import PlaceGatewayError
from evals.test_i1_safety import _spec


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


class ScriptedLLMClient:
    def __init__(self, always_requests_another_search=False):
        self.always_requests_another_search = always_requests_another_search
        
    def execute_planner(self, spec, registry, state, **kwargs):
        if self.always_requests_another_search:
            state.record_call()
            if registry:
                candidates = registry.execute(PlaceSearchRequest(destination_area_id="mock", max_results=10))
                state.retain(candidates)
            return False
        return True


def run_pipeline(spec, registry, llm):
    # run discovery and then compose
    result = run_discovery(spec, registry, llm=llm)
    from evals.test_i5_integrity import compose_from, DiscoveryCandidate
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
    result = run_discovery(_spec(), MockRegistry(),
                           llm=ScriptedLLMClient(always_requests_another_search=True))
    assert result.partial is not None
    assert result.partial.unresolved_needs
    assert result.partial.stop_reason == "budget_exhausted"


def test_an_adapter_failure_falls_back_without_inventing_venues() -> None:
    result = run_discovery(_spec(), MockRegistry(mode="fail"), llm=ScriptedLLMClient(always_requests_another_search=True))
    assert result.partial is not None
    assert result.partial.stop_reason in ("provider_unavailable", "evidence_missing")
    assert all(c.place_id for c in result.committed_candidates)


def test_no_results_is_reported_as_an_unmet_need_not_an_empty_success() -> None:
    """Spec 12: 'Return the unmet need; do not invent a venue.'"""
    result = run_discovery(_spec(), MockRegistry(mode="empty"), llm=ScriptedLLMClient(always_requests_another_search=False))
    assert result.partial is not None
    assert result.partial.unresolved_needs
    assert result.committed_candidates == []


def test_the_pipeline_still_produces_a_plan_when_discovery_fails_entirely() -> None:
    """Spec 12: 'Compose from deterministic retrieval results; no extra hidden call site.'"""
    result = run_pipeline(_spec(), MockRegistry(mode="fail"), llm=ScriptedLLMClient(always_requests_another_search=True))
    assert result.itinerary is not None
