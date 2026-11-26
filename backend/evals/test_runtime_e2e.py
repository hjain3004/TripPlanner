"""End-to-end test exercising a plan request through the pipeline with AnthropicMessagesClient.

Uses an injected MockTransport to verify that Mode A pipeline execution works,
settles the budget ledger, and produces a complete CostedTrip. Zero paid calls.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from agents.claude_client import AnthropicMessagesClient
from agents.llm import LLMNotConfigured
from agents.llm_budget import LLMSpendLedger, SpendCaps
from agents.llm_factory import ThreadingDispatchGate, build_llm_client
from agents.models import PipelineStatus
from agents.pipeline import run_pipeline
from core.db import SEEDS_DIR, load_kb, seed_database
from gateway.places.registry import get_default_place_registry


def test_pipeline_runs_with_mock_claude_client(tmp_path: Path) -> None:
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    kb = load_kb(db_path)
    registry = get_default_place_registry()

    intake_json = {
        "home_country": "IN",
        "origin_city": "DEL",
        "destination_city": "SIN",
        "start_date": "2026-11-15",
        "end_date": "2026-11-18",
        "travelers": 1,
        "budget_currency": "INR",
        "budget_minor": 15000000,
        "style": "balanced",
        "interests": ["sightseeing"],
        "wallet": {"card_ids": ["hdfc-infinia", "axis-atlas"], "points": {}},
        "unresolved": [],
    }

    planner_json = {
        "kind": "itinerary",
        "itinerary": {
            "hotel_area_id": "marina_bay",
            "days": [
                {
                    "date": "2026-11-15",
                    "items": [{"poi_id": "gardens_by_the_bay", "start_hint": "morning"}],
                },
                {
                    "date": "2026-11-16",
                    "items": [{"poi_id": "singapore_flyer", "start_hint": "morning"}],
                },
                {
                    "date": "2026-11-17",
                    "items": [{"poi_id": "sentosa", "start_hint": "morning"}],
                },
            ],
            "notes": ["Balanced Singapore itinerary"],
        },
    }

    critic_json = {
        "passed": True,
        "issues": [],
        "suggestions": ["Add evening dining"],
    }

    explainer_json = {
        "summary": "Singapore trip from Delhi",
        "daily_breakdown": [],
        "payment_strategy": "Use HDFC Infinia for dining and Axis Atlas for travel",
        "points_transfers": [],
        "warnings": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_prompt = body["messages"][0]["content"]

        if "Card catalog:" in user_prompt:
            content_json = intake_json
        elif "Trip:" in user_prompt:
            content_json = planner_json
        elif "DraftItinerary:" in user_prompt:
            content_json = critic_json
        else:
            content_json = explainer_json

        return httpx.Response(
            200,
            json={
                "id": "msg_mock",
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 120, "output_tokens": 80},
                "content": [{"type": "text", "text": json.dumps(content_json)}],
            },
        )

    caps = SpendCaps(
        per_plan_micro_usd=500_000,
        per_day_micro_usd=5_000_000,
        per_month_micro_usd=25_000_000,
        lifetime_micro_usd=45_000_000,
        paid_plans_per_user_per_day=5,
    )
    ledger = LLMSpendLedger(tmp_path / "llm_spend.sqlite3", caps)
    gate = ThreadingDispatchGate(max_concurrent=2)
    http_client = httpx.Client(transport=httpx.MockTransport(handler))

    client = AnthropicMessagesClient(
        model="claude-sonnet-5-5",
        ledger=ledger,
        gate=gate,
        plan_id="test_plan_e2e",
        run_id="test_plan_e2e",
        user_id="u_test",
        api_key="test_api_key",
        http_client=http_client,
    )

    result = run_pipeline(
        raw_request="Trip to Singapore from Delhi, 15 to 18 Nov 2026",
        kb=kb,
        llm=client,
        registry=registry,
        booking_date=date(2026, 11, 1),
        trace_dir=tmp_path / "traces",
    )

    assert result.status == PipelineStatus.OK
    assert result.report is not None
    # Verify that ledger recorded and settled real usage for nodes in the pipeline
    committed = ledger.plan_committed_micro_usd("test_plan_e2e")
    assert committed > 0
    assert ledger.lifetime_committed_micro_usd() == committed


def test_unconfigured_provider_fails_with_typed_error() -> None:
    client = build_llm_client("pipeline", env={})
    # HostedFreeTier with no env vars should raise LLMNotConfigured
    with pytest.raises(LLMNotConfigured) as exc:
        client.complete_json(
            node="intake",
            system="sys",
            user="user",
            schema=dict,  # type: ignore[arg-type]
        )
    assert exc.value.code == "LLM_NOT_CONFIGURED"
    assert "HostedFreeTier is not configured" in str(exc.value)
