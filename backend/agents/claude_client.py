"""Anthropic Messages REST client conforming to agents.llm.LLMClient.

Design: docs/superpowers/specs/2026-11-11-runtime-llm-design.md sections 5, 7, 8.
Zero-spend: uses an injected httpx.Client(transport=...) for offline/mock testing.
Never talks to a paid API during development.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

import httpx
from pydantic import BaseModel

from agents.llm import (
    LLMBudgetExceeded,
    LLMCallError,
    LLMInvalidResponse,
    LLMProviderUnavailable,
    LLMRefusal,
    LLMSchemaRejected,
    LLMTimeoutError,
    LLMTruncated,
)
from agents.llm_budget import (
    LLMSpendLedger,
    UsageCounts,
    input_token_upper_bound,
    price_for,
    reservation_micro_usd,
    settled_micro_usd,
)
from agents.llm_wire import (
    PlannerTurn,
    from_wire,
    to_wire_schema,
)
from core.trip_models import DraftItinerary

T = TypeVar("T", bound=BaseModel)


class DispatchGate(Protocol):
    def acquire(self, timeout_s: float) -> bool: ...
    def release(self) -> None: ...


@dataclass(frozen=True)
class AnthropicNodeSettings:
    max_tokens: int
    effort: Literal["low", "medium", "high"] = "medium"
    thinking: Literal["off", "adaptive"] = "off"


class AnthropicMessagesClient:
    """Satisfies agents.llm.LLMClient for the Anthropic Messages API."""

    def __init__(
        self,
        *,
        model: str,
        ledger: LLMSpendLedger,
        gate: DispatchGate,
        plan_id: str | None = None,
        run_id: str | None = None,
        user_id: str | None = None,
        role: str = "pipeline",
        node_settings: Mapping[str, AnthropicNodeSettings] | None = None,
        api_key: str | None = None,
        base_url: str = "https://api.anthropic.com",
        http_client: httpx.Client | None = None,
        deadline: float | None = None,
        clock: Callable[[], float] = time.monotonic,
        refusal_fallback_model: str | None = None,
    ) -> None:
        self.model = model
        self.ledger = ledger
        self.gate = gate
        self.plan_id = plan_id
        self.run_id = run_id or plan_id
        self.user_id = user_id
        self.role = role
        self.node_settings = dict(node_settings or {})
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http_client = http_client
        self.deadline = deadline
        self.clock = clock
        self.refusal_fallback_model = refusal_fallback_model

    def _get_client(self, timeout_s: float) -> httpx.Client:
        if self._http_client is not None:
            return self._http_client
        return httpx.Client(timeout=timeout_s)

    def _remaining_deadline(self) -> float:
        if self.deadline is None:
            return 60.0
        return max(0.0, self.deadline - self.clock())

    def _format_thinking(
        self, model: str, settings: AnthropicNodeSettings | None
    ) -> dict[str, Any] | None:
        if settings is None or settings.thinking == "off":
            if "sonnet" in model:
                return {"type": "between_tools"}
            if "haiku" in model:
                return {"type": "disabled"}
            return None
        return {"type": "adaptive"}

    def complete_json(
        self,
        *,
        node: str,
        system: str,
        user: str,
        schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: int = 20,
        tools: list[dict[str, Any]] | None = None,
    ) -> T | Any:
        settings = self.node_settings.get(node)
        effective_max_tokens = settings.max_tokens if settings else max_tokens

        use_envelope = tools is not None or (
            node == "planner" and issubclass(schema, DraftItinerary)
        )
        target_schema: type[BaseModel] = PlannerTurn if use_envelope else schema

        wire_schema = to_wire_schema(target_schema)
        wire_json = json.dumps(wire_schema, sort_keys=True, separators=(",", ":"))
        input_upper = input_token_upper_bound(system=system, user=user, wire_schema_json=wire_json)
        model_price = price_for(self.model)
        reserve_amount = reservation_micro_usd(
            model_price, input_upper=input_upper, max_tokens=effective_max_tokens
        )
        if self.refusal_fallback_model:
            fb_price = price_for(self.refusal_fallback_model)
            reserve_amount += reservation_micro_usd(
                fb_price, input_upper=input_upper, max_tokens=effective_max_tokens
            )

        headers: dict[str, str] = {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.refusal_fallback_model:
            headers["anthropic-beta"] = "server-side-fallback-2026-07-01"

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": effective_max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": wire_schema,
                }
            },
        }
        thinking_conf = self._format_thinking(self.model, settings)
        if thinking_conf is not None:
            payload["thinking"] = thinking_conf
        if self.refusal_fallback_model:
            payload["fallbacks"] = [{"model": self.refusal_fallback_model}]

        # Retry loop: at most 1 retry (max 2 attempts)
        for attempt in range(2):
            rem = self._remaining_deadline()
            if rem < timeout_s:
                raise LLMTimeoutError("deadline exceeded before dispatch")

            # 1. Acquire gate FIRST
            acquired = self.gate.acquire(timeout_s=min(rem, 5.0))
            if not acquired:
                raise LLMProviderUnavailable("overloaded", reason="gate_timeout")

            try:
                # Re-check deadline once gate acquired
                rem = self._remaining_deadline()
                if rem < timeout_s:
                    raise LLMTimeoutError("deadline exceeded after gate acquisition")

                # 2. Reserve in ledger immediately before dispatch
                reservation_id = self.ledger.reserve(
                    plan_id=self.plan_id,
                    run_id=self.run_id,
                    role=self.role,
                    user_id=self.user_id,
                    node=node,
                    model=self.model,
                    amount_micro_usd=reserve_amount,
                )

                client = self._get_client(timeout_s)
                try:
                    response = client.post(
                        f"{self.base_url}/v1/messages",
                        headers=headers,
                        json=payload,
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    self.ledger.mark_uncertain(reservation_id)
                    if isinstance(exc, httpx.TimeoutException):
                        raise LLMTimeoutError(f"{node} timed out: {exc}") from exc
                    raise LLMProviderUnavailable(
                        f"{node} connection error: {exc}", reason="network_error"
                    ) from exc

                status = response.status_code
                if status == 200:
                    data = response.json()
                    usage_data = data.get("usage", {})
                    usage = UsageCounts(
                        input_tokens=usage_data.get("input_tokens", 0),
                        output_tokens=usage_data.get("output_tokens", 0),
                        cache_creation_input_tokens=usage_data.get(
                            "cache_creation_input_tokens", 0
                        ),
                        cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
                    )
                    settled_cost = settled_micro_usd(model_price, usage)
                    self.ledger.settle(reservation_id, usage, settled_cost)

                    stop_reason = data.get("stop_reason")
                    if stop_reason == "refusal":
                        raise LLMRefusal("model declined request")
                    if stop_reason == "max_tokens":
                        raise LLMTruncated("model reached max_tokens limit")

                    content_blocks = data.get("content", [])
                    raw_text = ""
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "text":
                            raw_text = block.get("text", "")
                            break
                    try:
                        parsed_json = json.loads(raw_text)
                    except json.JSONDecodeError as exc:
                        raise LLMInvalidResponse(f"invalid JSON from {node}: {exc}") from exc

                    if use_envelope:
                        turn = PlannerTurn.model_validate(parsed_json)
                        if turn.kind == "itinerary":
                            assert turn.itinerary is not None
                            return turn.itinerary
                        if turn.kind == "search":
                            assert turn.search_intent is not None
                            return turn.search_intent
                        raise LLMInvalidResponse("unexpected planner turn kind")

                    folded = from_wire(parsed_json, schema)
                    return schema.model_validate(folded)

                # HTTP error handling per Section 8.1
                self.ledger.release(reservation_id)
                error_body = response.text
                try:
                    error_json = response.json()
                except Exception:
                    error_json = {}

                error_detail = error_json.get("error", {})
                error_code = (
                    error_detail.get("details", {}).get("error_code")
                    if isinstance(error_detail, dict)
                    else None
                )
                error_msg = (
                    error_detail.get("message", "")
                    if isinstance(error_detail, dict)
                    else error_body
                )

                if status == 429:
                    if error_code == "enforced_spend_limit_reached" or "spend_limit" in error_msg:
                        self.ledger.open_breaker(
                            "provider_spend_cap", "enforced_spend_limit_reached"
                        )
                        raise LLMBudgetExceeded(
                            "provider spend cap reached", scope="provider_spend_cap"
                        )

                    retry_after_str = response.headers.get("retry-after")
                    retry_after = (
                        float(retry_after_str)
                        if retry_after_str and retry_after_str.isdigit()
                        else 2.0
                    )
                    rem = self._remaining_deadline()
                    if attempt == 0 and (retry_after + timeout_s <= rem):
                        time.sleep(retry_after)
                        continue
                    raise LLMProviderUnavailable("rate limit exceeded", reason="rate_limited")

                if status == 400:
                    if "specified" in error_msg and "API usage limits" in error_msg:
                        self.ledger.open_breaker(
                            "workspace_spend_limit", "specified API usage limits"
                        )
                        raise LLMBudgetExceeded(
                            "workspace spend limit reached", scope="workspace_spend_limit"
                        )
                    if "Schema is too complex" in error_msg:
                        raise LLMSchemaRejected("Schema is too complex")
                    raise LLMCallError(f"HTTP 400 from {node}: {error_msg}")

                if status in (401, 402, 403):
                    self.ledger.open_breaker(
                        "provider_auth_or_billing", f"HTTP {status}: {error_msg}"
                    )
                    raise LLMProviderUnavailable(
                        "provider auth or billing error", reason="auth_or_billing"
                    )

                if status == 404:
                    raise LLMProviderUnavailable(
                        f"model {self.model} not found: {error_msg}", reason="model_not_found"
                    )

                if status in (500, 502, 503, 529):
                    rem = self._remaining_deadline()
                    if attempt == 0 and (2.0 + timeout_s <= rem):
                        time.sleep(2.0)
                        continue
                    raise LLMProviderUnavailable(
                        f"provider server error {status}: {error_msg}", reason="server_error"
                    )

                raise LLMCallError(f"HTTP {status} from {node}: {error_body}")
            finally:
                self.gate.release()

        raise LLMProviderUnavailable("max retries exceeded", reason="retries_exhausted")
