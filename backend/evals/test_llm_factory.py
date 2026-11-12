"""Tests for LLM client factory and dispatch limiter."""

from __future__ import annotations

from pathlib import Path

from agents.claude_client import AnthropicMessagesClient
from agents.llm import HostedFreeTier, ScriptedLLMClient
from agents.llm_factory import (
    ThreadingDispatchGate,
    build_llm_client,
)


def test_kill_switch_forces_scripted_client_for_all_roles() -> None:
    env = {"TRIPWISE_LLM_KILL_SWITCH": "1", "TRIPWISE_LLM_PROVIDER": "anthropic"}
    client_pipeline = build_llm_client("pipeline", env=env)
    client_interview = build_llm_client("interview", env=env)
    client_post_plan = build_llm_client("post_plan", env=env)

    assert isinstance(client_pipeline, ScriptedLLMClient)
    assert isinstance(client_interview, ScriptedLLMClient)
    assert isinstance(client_post_plan, ScriptedLLMClient)


def test_anthropic_provider_honored_only_for_pipeline_role(tmp_path: Path) -> None:
    env = {
        "TRIPWISE_LLM_PROVIDER": "anthropic",
        "TRIPWISE_DATA_DIR": str(tmp_path),
        "TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD": "1000",
        "TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD": "2000",
        "TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD": "3000",
        "TRIPWISE_LLM_CAP_LIFETIME_MICRO_USD": "4000",
        "TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY": "5",
        "ANTHROPIC_API_KEY": "test-key",
    }
    # Anonymous user: returns ScriptedLLMClient
    anon_client = build_llm_client("pipeline", user_id=None, env=env)
    assert isinstance(anon_client, ScriptedLLMClient)

    # Signed-in user: returns AnthropicMessagesClient
    auth_client = build_llm_client("pipeline", user_id="u123", env=env)
    assert isinstance(auth_client, AnthropicMessagesClient)

    # Paid scope = all allows anonymous users
    all_client = build_llm_client(
        "pipeline", user_id=None, env={**env, "TRIPWISE_LLM_PAID_SCOPE": "all"}
    )
    assert isinstance(all_client, AnthropicMessagesClient)

    # Other roles return ScriptedLLMClient even with signed-in user
    interview_client = build_llm_client("interview", user_id="u123", env=env)
    assert isinstance(interview_client, ScriptedLLMClient)


def test_default_provider_returns_hosted_free_tier() -> None:
    client = build_llm_client("pipeline", env={})
    assert isinstance(client, HostedFreeTier)


def test_dispatch_gate_limits_concurrency() -> None:
    gate = ThreadingDispatchGate(max_concurrent=2)
    assert gate.acquire(timeout_s=0.1) is True
    assert gate.acquire(timeout_s=0.1) is True
    # Third acquire should fail (timeout)
    assert gate.acquire(timeout_s=0.05) is False

    gate.release()
    # Now third acquire can succeed
    assert gate.acquire(timeout_s=0.1) is True
    gate.release()
    gate.release()
