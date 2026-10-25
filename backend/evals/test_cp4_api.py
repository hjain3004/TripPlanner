"""Task 5 route contract and proposal/approval smoke coverage."""

from __future__ import annotations

from api.main import app


def test_post_plan_routes_are_mounted() -> None:
    paths = set(app.openapi()["paths"])
    assert "/planning/sessions/{session_id}/workspace" in paths
    assert "/planning/sessions/{session_id}/actions" in paths
    assert "/planning/sessions/{session_id}/actions/{proposal_id}/approve" in paths
    assert "/planning/sessions/{session_id}/actions/{proposal_id}/reject" in paths


def test_action_request_rejects_more_than_one_input() -> None:
    from api.post_plan import ActionIn

    schema = ActionIn
    try:
        schema.model_validate(
            {
                "client_event_id": "e1",
                "expected_session_version": 1,
                "expected_workspace_version": 1,
                "text": "move it",
                "action": {
                    "kind": "clarification_required",
                    "reason": "unsupported",
                    "question": "?",
                },
            }
        )
    except Exception:
        return
    raise AssertionError("action requests must contain exactly one of text or action")
