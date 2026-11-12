"""Unit tests for AnthropicMessagesClient (design sections 5, 7, 8).

All tests use injected httpx.MockTransport. Zero paid API calls.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agents.claude_client import (
    AnthropicMessagesClient,
    DispatchGate,
)
from agents.llm import (
    LLMBudgetExceeded,
    LLMCallError,
    LLMInvalidResponse,
    LLMProviderUnavailable,
    LLMRefusal,
    LLMSchemaRejected,
    LLMTruncated,
)
from agents.llm_budget import LLMSpendLedger, SpendCaps
from agents.llm_factory import ThreadingDispatchGate
from core.trip_models import DraftItinerary


class DummySchema(BaseModel):
    city: str
    days: int


NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


def caps(**updates: int) -> SpendCaps:
    base = {
        "per_plan_micro_usd": 500_000,
        "per_day_micro_usd": 5_000_000,
        "per_month_micro_usd": 50_000_000,
        "lifetime_micro_usd": 500_000_000,
        "paid_plans_per_user_per_day": 10,
    }
    base.update(updates)
    return SpendCaps(**base)


def make_client(
    tmp_path: Path,
    handler: Any,
    gate: DispatchGate | None = None,
    deadline: float | None = None,
    clock_time: float = 0.0,
    api_key: str = "test-key",
    max_calls: int | None = None,
    **cap_updates: int,
) -> tuple[AnthropicMessagesClient, LLMSpendLedger]:
    db = LLMSpendLedger(tmp_path / "llm_spend.sqlite3", caps(**cap_updates), now=lambda: NOW)
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    dispatch_gate = gate or ThreadingDispatchGate(2)
    client = AnthropicMessagesClient(
        model="claude-sonnet-5-5",
        ledger=db,
        gate=dispatch_gate,
        plan_id="p1",
        run_id="r1",
        user_id="u1",
        api_key=api_key,
        http_client=http_client,
        deadline=deadline,
        clock=lambda: clock_time,
        max_calls=max_calls,
    )
    return client, db


def test_happy_path_settles_ledger_and_returns_model(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert "temperature" not in body
        assert body["model"] == "claude-sonnet-5-5"
        return httpx.Response(
            200,
            json={
                "id": "msg_123",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [{"type": "text", "text": json.dumps({"city": "SIN", "days": 3})}],
            },
        )

    client, db = make_client(tmp_path, handler)
    result = client.complete_json(
        node="intake",
        system="Extract trip",
        user="Singapore for 3 days",
        schema=DummySchema,
    )
    assert isinstance(result, DummySchema)
    assert result.city == "SIN"
    assert result.days == 3
    # Settled in ledger: 100 * 2 + 50 * 10 = 200 + 500 = 700 micro-USD (rounded up)
    assert db.plan_committed_micro_usd("p1") == 700


def test_gate_acquisition_happens_first_and_failure_leaves_no_reservation(tmp_path: Path) -> None:
    class FullGate:
        def acquire(self, timeout_s: float) -> bool:
            return False

        def release(self) -> None:
            pass

    client, db = make_client(tmp_path, lambda r: httpx.Response(200), gate=FullGate())
    with pytest.raises(LLMProviderUnavailable) as error:
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    assert error.value.reason == "gate_timeout"
    assert db.lifetime_committed_micro_usd() == 0


def test_refusal_settles_usage_and_raises_llm_refusal(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "stop_reason": "refusal",
                "usage": {"input_tokens": 50, "output_tokens": 10},
                "content": [{"type": "text", "text": "I decline"}],
            },
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMRefusal):
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    # The usage was consumed so it settles in ledger
    assert db.plan_committed_micro_usd("p1") > 0


def test_max_tokens_settles_usage_and_raises_llm_truncated(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 50, "output_tokens": 2048},
                "content": [{"type": "text", "text": "partial"}],
            },
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMTruncated):
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    assert db.plan_committed_micro_usd("p1") > 0


def test_spend_cap_error_releases_reservation_and_opens_breaker(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={
                "error": {
                    "type": "error",
                    "message": "Spend limit reached",
                    "details": {"error_code": "enforced_spend_limit_reached"},
                }
            },
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMBudgetExceeded) as exc:
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    assert exc.value.scope == "provider_spend_cap"
    assert db.plan_committed_micro_usd("p1") == 0
    assert "provider_spend_cap" in db.open_breakers()


def test_workspace_spend_limit_opens_breaker(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": "Your request exceeds the specified workspace API usage limits.",
                }
            },
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMBudgetExceeded) as exc:
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    assert exc.value.scope == "workspace_spend_limit"
    assert "workspace_spend_limit" in db.open_breakers()


def test_schema_too_complex_raises_schema_rejected(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": "Schema is too complex",
                }
            },
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMSchemaRejected):
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    assert db.plan_committed_micro_usd("p1") == 0


def test_auth_or_billing_opens_breaker(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"type": "authentication_error", "message": "invalid api key"}},
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMProviderUnavailable):
        client.complete_json(
            node="intake",
            system="sys",
            user="usr",
            schema=DummySchema,
        )
    assert "provider_auth_or_billing" in db.open_breakers()


def test_planner_turn_envelope_returns_draft_itinerary(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_plan",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 100, "output_tokens": 50},
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "kind": "itinerary",
                                "itinerary": {
                                    "hotel_area_id": "marina_bay",
                                    "days": [
                                        {
                                            "date": "2026-11-15",
                                            "items": [{"poi_id": "gardens_by_the_bay"}],
                                        }
                                    ],
                                    "notes": [],
                                },
                            }
                        ),
                    }
                ],
            },
        )

    client, db = make_client(tmp_path, handler)
    result = client.complete_json(
        node="planner",
        system="sys",
        user="usr",
        schema=DraftItinerary,
        tools=[{"name": "search_places"}],
    )
    assert isinstance(result, DraftItinerary)
    assert result.hotel_area_id == "marina_bay"
    assert len(result.days) == 1


def test_missing_usage_marks_uncertain_and_raises_invalid_response(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_no_usage",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": '{"city": "SIN", "days": 3}'}],
            },
        )

    client, db = make_client(tmp_path, handler)
    with pytest.raises(LLMInvalidResponse, match="missing or malformed usage"):
        client.complete_json(node="intake", system="sys", user="usr", schema=DummySchema)

    # Assert ledger has reservation in state 'uncertain', never settled to zero
    with sqlite3.connect(db.path) as conn:
        row = conn.execute(
            "SELECT state, reserved_micro_usd, settled_micro_usd FROM reservations"
        ).fetchone()
        assert row is not None
        assert row[0] == "uncertain"
        assert row[1] > 0
        assert row[2] is None or row[2] == 0


def test_plan_budget_call_ceiling_enforced(tmp_path: Path) -> None:
    calls = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(True)
        return httpx.Response(
            200,
            json={
                "id": f"msg_{len(calls)}",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "content": [{"type": "text", "text": '{"city": "SIN", "days": 3}'}],
            },
        )

    client, _ = make_client(tmp_path, handler, max_calls=1)
    res = client.complete_json(node="intake", system="sys", user="usr", schema=DummySchema)
    assert res.city == "SIN"
    assert len(calls) == 1

    # Second call should be refused without provider dispatch
    with pytest.raises(LLMBudgetExceeded, match="Plan call ceiling reached"):
        client.complete_json(node="intake", system="sys", user="usr", schema=DummySchema)
    assert len(calls) == 1


def test_provider_error_content_is_redacted(tmp_path: Path) -> None:
    # Build key with split prefix so secret scanning tests do not match static text
    secret_key = "sk-ant-" + "synthetic-test-credential-value-redacted"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": f"Bad request including {secret_key}"}},
        )

    client, db = make_client(tmp_path, handler, api_key=secret_key)
    with pytest.raises(LLMCallError) as exc_info:
        client.complete_json(node="intake", system="sys", user="usr", schema=DummySchema)

    err_str = str(exc_info.value)
    assert secret_key not in err_str
    assert "[REDACTED]" in err_str
