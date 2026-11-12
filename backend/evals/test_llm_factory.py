"""Tests for LLM client factory and dispatch limiter."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from agents.claude_client import AnthropicMessagesClient
from agents.llm import (
    HostedFreeTier,
    LLMNotConfigured,
    LLMProviderUnavailable,
    LLMSignInRequired,
    RefusalLLMClient,
)
from agents.llm_factory import (
    ThreadingDispatchGate,
    build_llm_client,
)


class DummySchema(BaseModel):
    foo: str


def test_kill_switch_forces_refusal_for_all_roles() -> None:
    env = {"TRIPWISE_LLM_KILL_SWITCH": "1", "TRIPWISE_LLM_PROVIDER": "anthropic"}
    client_pipeline = build_llm_client("pipeline", env=env)
    client_interview = build_llm_client("interview", env=env)
    client_post_plan = build_llm_client("post_plan", env=env)

    assert isinstance(client_pipeline, RefusalLLMClient)
    assert isinstance(client_interview, RefusalLLMClient)
    assert isinstance(client_post_plan, RefusalLLMClient)
    try:
        client_pipeline.complete_json(node="intake", system="s", user="u", schema=DummySchema)
        pytest.fail("Expected LLMProviderUnavailable")
    except LLMProviderUnavailable as exc:
        assert exc.reason == "kill_switch"


def test_anthropic_provider_honored_only_for_pipeline_role(tmp_path: Path) -> None:
    env = {
        "TRIPWISE_LLM_PROVIDER": "anthropic",
        "TRIPWISE_DATA_DIR": str(tmp_path),
        "TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD": "1000",
        "TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD": "2000",
        "TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD": "3000",
        "TRIPWISE_LLM_CAP_LIFETIME_MICRO_USD": "4000",
        "TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY": "5",
        "TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED": "1",
        "ANTHROPIC_API_KEY": "test-key",
    }
    # Anonymous user: returns RefusalLLMClient with LLMSignInRequired
    anon_client = build_llm_client("pipeline", user_id=None, env=env)
    assert isinstance(anon_client, RefusalLLMClient)
    try:
        anon_client.complete_json(node="intake", system="s", user="u", schema=DummySchema)
        pytest.fail("Expected LLMSignInRequired")
    except LLMSignInRequired:
        pass

    # Signed-in user: returns AnthropicMessagesClient
    auth_client = build_llm_client("pipeline", user_id="u123", env=env)
    assert isinstance(auth_client, AnthropicMessagesClient)

    # Paid scope = all allows anonymous users
    all_client = build_llm_client(
        "pipeline", user_id=None, env={**env, "TRIPWISE_LLM_PAID_SCOPE": "all"}
    )
    assert isinstance(all_client, AnthropicMessagesClient)

    # Missing no-overage confirmation fails closed with typed refusal
    no_attest_env = dict(env)
    del no_attest_env["TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED"]
    no_attest_client = build_llm_client("pipeline", user_id="u123", env=no_attest_env)
    assert isinstance(no_attest_client, RefusalLLMClient)
    try:
        no_attest_client.complete_json(node="intake", system="s", user="u", schema=DummySchema)
        pytest.fail("Expected LLMNotConfigured")
    except LLMNotConfigured:
        pass

    # Other roles return typed refusal in anthropic mode
    interview_client = build_llm_client("interview", user_id="u123", env=env)
    assert isinstance(interview_client, RefusalLLMClient)


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


def test_nonplan_roles_share_process_wide_dispatch_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents.interview_assistant import get_interview_llm
    from agents.post_plan_interpreter import get_post_plan_llm

    monkeypatch.setenv("TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED", "1")
    monkeypatch.setenv("TRIPWISE_POST_PLAN_LLM_ZERO_SPEND_CONFIRMED", "1")
    monkeypatch.setenv("TRIPWISE_LLM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("TRIPWISE_LLM_MODEL", "fixture")
    monkeypatch.setenv("TRIPWISE_LLM_API_KEY", "synthetic")

    i_llm = get_interview_llm()
    p_llm = get_post_plan_llm()
    assert isinstance(i_llm, HostedFreeTier)
    assert isinstance(p_llm, HostedFreeTier)
    assert i_llm.gate is not None
    assert p_llm.gate is not None
    assert i_llm.gate is p_llm.gate
