import json
from datetime import UTC, datetime

from agents.discovery.contracts import LoopBudget, LoopState, SearchIntent
from agents.discovery.tool import (
    MODEL_TOOLS,
    SEARCH_PLACES_TOOL,
    execute_search_places,
    project_for_model,
)
from gateway.places.contracts import PlaceCandidate, PlaceClaim


def test_exactly_one_tool_is_exposed_to_the_model() -> None:
    assert [t["name"] for t in MODEL_TOOLS] == ["search_places"]


def test_the_tool_schema_names_no_provider() -> None:
    """Spec 4: provider selection stays outside the prompt."""
    blob = json.dumps(SEARCH_PLACES_TOOL).lower()
    for banned in (
        "overture",
        "osm",
        "wikivoyage",
        "tripadvisor",
        "gondola",
        "snapshot_adapter",
        "sample_adapter",
        "http",
    ):
        assert banned not in blob


class MockRegistry:
    def execute(self, req):
        c = PlaceCandidate(
            place_id="pl_1",
            status="live",
            claims=[
                PlaceClaim(
                    place_id="pl_1",
                    field="name",
                    value="Mock Place",
                    source_id="overture:123",
                    source_url="https://example.com/1",
                    retrieved_at=datetime.now(UTC),
                    last_verified=datetime.now(UTC),
                    verified_by="system",
                    confidence=1.0,
                    needs_verification=False,
                    licence_id="ODbL",
                )
            ],
        )
        return [c]


def test_the_gateway_selects_the_adapter_not_the_caller() -> None:
    intent = SearchIntent(query_text="food", destination_area_id="dummy", round_index=0)
    state = LoopState(budget=LoopBudget())
    candidates, result = execute_search_places(intent, MockRegistry(), state)
    assert result.adapter_selected_by == "registry"


def test_returned_candidates_carry_claim_level_provenance() -> None:
    intent = SearchIntent(query_text="food", destination_area_id="dummy", round_index=0)
    state = LoopState(budget=LoopBudget())
    candidates, _ = execute_search_places(intent, MockRegistry(), state)
    for c in candidates:
        assert c.claims and all(cl.licence_id and cl.source_id for cl in c.claims)


def test_raw_payloads_never_reach_the_model_facing_projection() -> None:
    """Spec 10: 'Keep raw payloads out of normal model context.'"""
    candidates = MockRegistry().execute(None)
    projection = project_for_model(candidates)
    blob = json.dumps(projection).lower()
    assert "source_url" not in blob and "http" not in blob
    assert all("place_id" in item for item in projection)
