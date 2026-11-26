"""Factory and process-wide dispatch limiter for LLM clients.

Design: docs/superpowers/specs/2026-11-11-runtime-llm-design.md sections 5, 7.3.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import httpx

from agents.claude_client import (
    AnthropicMessagesClient,
    AnthropicNodeSettings,
    DispatchGate,
    PlanBudget,
)
from agents.config import load_agent_config
from agents.llm import (
    HostedFreeTier,
    LLMClient,
    LLMNotConfigured,
    LLMProviderUnavailable,
    LLMSignInRequired,
    RefusalLLMClient,
    ScriptedLLMClient,
)
from agents.llm_budget import LLMSpendLedger, SpendCaps

LLMProvider = Literal["scripted", "replay", "openai_compatible", "anthropic"]
LLMRole = Literal["pipeline", "interview", "post_plan"]


class ThreadingDispatchGate:
    """One process-wide BoundedSemaphore gating all concurrent model dispatches."""

    def __init__(self, max_concurrent: int = 2) -> None:
        self._semaphore = threading.BoundedSemaphore(max(1, max_concurrent))
        self._max_concurrent = max(1, max_concurrent)

    def acquire(self, timeout_s: float) -> bool:
        return self._semaphore.acquire(timeout=max(0.0, timeout_s))

    def release(self) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            pass  # Avoid crash if release is called more times than acquire


_GLOBAL_GATE: ThreadingDispatchGate | None = None
_GATE_LOCK = threading.Lock()


def get_dispatch_gate(max_concurrent: int = 2) -> ThreadingDispatchGate:
    global _GLOBAL_GATE
    with _GATE_LOCK:
        if _GLOBAL_GATE is None:
            _GLOBAL_GATE = ThreadingDispatchGate(max_concurrent)
        return _GLOBAL_GATE


def reset_dispatch_gate() -> None:
    global _GLOBAL_GATE
    with _GATE_LOCK:
        _GLOBAL_GATE = None


def build_llm_client(
    role: LLMRole = "pipeline",
    *,
    plan_id: str | None = None,
    run_id: str | None = None,
    user_id: str | None = None,
    env: Mapping[str, str] = os.environ,
    gate: DispatchGate | None = None,
    ledger: LLMSpendLedger | None = None,
    http_client: httpx.Client | None = None,
    budget: PlanBudget | None = None,
    deadline: float | None = None,
) -> LLMClient:
    """Single factory building the configured LLM client.

    Never crashes on startup if nothing is configured: returns a client that fails
    with a typed error at call time.
    """
    if env.get("TRIPWISE_LLM_KILL_SWITCH", "").strip() == "1":
        return RefusalLLMClient(
            LLMProviderUnavailable("LLM kill switch is active", reason="kill_switch")
        )

    provider = env.get("TRIPWISE_LLM_PROVIDER", "").strip().lower() or "openai_compatible"

    max_concurrent_str = env.get("TRIPWISE_LLM_MAX_CONCURRENT_DISPATCH", "2").strip()
    max_concurrent = int(max_concurrent_str) if max_concurrent_str.isdigit() else 2
    dispatch_gate = gate or get_dispatch_gate(max_concurrent)

    if provider == "scripted":
        return ScriptedLLMClient({})

    if provider == "replay":
        return ScriptedLLMClient({})

    if provider == "anthropic":
        # Anthropic is honored ONLY for role="pipeline"
        if role != "pipeline":
            return RefusalLLMClient(
                LLMProviderUnavailable(
                    f"Anthropic provider is not enabled for role {role!r}", reason="role_disabled"
                )
            )

        # Enforce explicit no-overage confirmation guard (§6.1)
        if env.get("TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED", "").strip() != "1":
            return RefusalLLMClient(
                LLMNotConfigured(
                    "TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED=1 is required "
                    "(operator attestation that provider workspace spend limit is set)"
                )
            )

        # Anthropic with anonymous user returns typed refusal unless paid scope is 'all'
        paid_scope = env.get("TRIPWISE_LLM_PAID_SCOPE", "").strip().lower()
        if user_id is None and paid_scope != "all":
            return RefusalLLMClient(
                LLMSignInRequired(
                    "Sign-in required for planning; paid model dispatch is reserved for users"
                )
            )

        caps = SpendCaps.from_env(env)
        data_dir_str = env.get("TRIPWISE_DATA_DIR", "").strip()
        data_dir = Path(data_dir_str) if data_dir_str else Path("/tmp")
        db_path = data_dir / "llm_spend.sqlite3"
        spend_ledger = ledger or LLMSpendLedger(db_path, caps)

        model = env.get("TRIPWISE_ANTHROPIC_MODEL", "claude-sonnet-5-5").strip()
        api_key = env.get("ANTHROPIC_API_KEY", "").strip()
        refusal_fallback = env.get("TRIPWISE_ANTHROPIC_REFUSAL_FALLBACK_MODEL", "").strip() or None

        node_settings: dict[str, AnthropicNodeSettings] = {}
        try:
            cfg = load_agent_config()
            raw_anthropic = getattr(cfg, "anthropic", None)
            if isinstance(raw_anthropic, dict):
                for node_name, node_val in raw_anthropic.items():
                    if isinstance(node_val, AnthropicNodeSettings):
                        node_settings[node_name] = node_val
                    elif isinstance(node_val, dict):
                        node_settings[node_name] = AnthropicNodeSettings(**node_val)
        except Exception:
            pass

        return AnthropicMessagesClient(
            model=model,
            ledger=spend_ledger,
            gate=dispatch_gate,
            plan_id=plan_id,
            run_id=run_id,
            user_id=user_id,
            role=role,
            node_settings=node_settings,
            api_key=api_key,
            http_client=http_client,
            budget=budget,
            deadline=deadline,
            refusal_fallback_model=refusal_fallback,
        )

    # Default: openai_compatible (HostedFreeTier)
    if role == "interview":
        cost = env.get("TRIPWISE_INTERVIEW_LLM_COST_MICRO_USD", "0").strip()
        confirmed = env.get("TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED", "").strip() == "1"
        if not confirmed or cost != "0":
            return ScriptedLLMClient({})
        client = HostedFreeTier(max_retries=0, gate=dispatch_gate)
        model = env.get("TRIPWISE_INTERVIEW_LLM_MODEL", "").strip() or (client.model or "")
        if model:
            client.model = model
            client.models = [model]
        client.max_calls = 1
        return client

    if role == "post_plan":
        cost = env.get("TRIPWISE_POST_PLAN_LLM_COST_MICRO_USD", "0").strip()
        confirmed = env.get("TRIPWISE_POST_PLAN_LLM_ZERO_SPEND_CONFIRMED", "").strip() == "1"
        if not confirmed or cost != "0":
            return ScriptedLLMClient({})
        client = HostedFreeTier(max_retries=0, gate=dispatch_gate)
        model = env.get("TRIPWISE_POST_PLAN_LLM_MODEL", "").strip() or (client.model or "")
        if model:
            client.model = model
            client.models = [model]
        client.max_calls = 1
        return client

    return HostedFreeTier(gate=dispatch_gate)
