"""HostedFreeTier is the first real LLM client in this project - until now both
runtime clients raised unconditionally and every test used ScriptedLLMClient,
so the four pipeline call sites had never executed against a real provider.

These tests never touch the network: urlopen is monkeypatched. They exist to
pin the contract (returns a validated schema, or a SearchIntent when tools are
offered), the failure mapping, and - importantly - that the API key never
leaks into an error message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO
from typing import Any

import pytest
from pydantic import BaseModel

from agents.discovery.contracts import SearchIntent
from agents.llm import HostedFreeTier, LLMCallError, LLMTimeoutError

_SECRET = "sk-test-do-not-leak-me"


class Tiny(BaseModel):
    answer: str


def _configure(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    env = {
        "TRIPWISE_LLM_BASE_URL": "https://provider.invalid/v1",
        "TRIPWISE_LLM_MODEL": "test-model",
        "TRIPWISE_LLM_API_KEY": _SECRET,
    }
    env.update(overrides)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


class _FakeResponse:
    def __init__(self, body: str) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body.encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _envelope(content: str) -> str:
    return json.dumps({"choices": [{"message": {"content": content}}]})


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, handler: Any) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def _fake(request: Any, timeout: float | None = None) -> Any:
        seen["request"] = request
        seen["timeout"] = timeout
        seen["called"] = seen.get("called", 0) + 1
        return handler(request)

    monkeypatch.setattr(urllib.request, "urlopen", _fake)
    return seen


def test_missing_configuration_names_every_missing_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in ("TRIPWISE_LLM_BASE_URL", "TRIPWISE_LLM_MODEL", "TRIPWISE_LLM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    client = HostedFreeTier()

    with pytest.raises(LLMCallError) as exc:
        client.complete_json(node="intake", system="s", user="u", schema=Tiny)

    message = str(exc.value)
    assert "TRIPWISE_LLM_BASE_URL" in message
    assert "TRIPWISE_LLM_MODEL" in message
    assert "TRIPWISE_LLM_API_KEY" in message


def test_a_valid_response_is_parsed_into_the_requested_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch)
    seen = _patch_urlopen(
        monkeypatch, lambda request: _FakeResponse(_envelope('{"answer": "yes"}'))
    )

    result = HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert isinstance(result, Tiny)
    assert result.answer == "yes"
    # Anti-vacuity: the request actually went through the mocked transport.
    assert seen["called"] == 1
    body = json.loads(seen["request"].data.decode("utf-8"))
    assert body["model"] == "test-model"
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"] == "u"


def test_code_fenced_json_is_still_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)
    fenced = '```json\n{"answer": "fenced"}\n```'
    _patch_urlopen(monkeypatch, lambda request: _FakeResponse(_envelope(fenced)))

    result = HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert isinstance(result, Tiny)
    assert result.answer == "fenced"


def test_a_tool_call_payload_becomes_a_search_intent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The planner accepts EITHER its target schema or a SearchIntent. A payload
    that fails the target schema must fall through to SearchIntent when tools
    were offered - matching ScriptedLLMClient's behaviour exactly."""
    _configure(monkeypatch)
    intent = '{"query_text": "rooftop bars", "destination_area_id": "a1", "round_index": 0}'
    _patch_urlopen(monkeypatch, lambda request: _FakeResponse(_envelope(intent)))

    result = HostedFreeTier().complete_json(
        node="planner",
        system="s",
        user="u",
        schema=Tiny,
        tools=[{"name": "search_places", "description": "d", "parameters": {}}],
    )

    assert isinstance(result, SearchIntent)
    assert result.query_text == "rooftop bars"


def test_without_tools_a_bad_payload_raises_validation_error_for_the_repair_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """complete_with_repair catches ValidationError and retries once. The client
    must let it escape rather than swallowing it."""
    from pydantic import ValidationError

    _configure(monkeypatch)
    _patch_urlopen(monkeypatch, lambda request: _FakeResponse(_envelope('{"wrong": 1}')))

    with pytest.raises(ValidationError):
        HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)


def test_an_http_error_never_leaks_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: None)  # the 429 backoff is real otherwise
    _configure(monkeypatch)

    def _raise(request: Any) -> Any:
        raise urllib.error.HTTPError(
            url="https://provider.invalid/v1/chat/completions",
            code=429,
            msg="Too Many Requests",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )

    _patch_urlopen(monkeypatch, _raise)

    with pytest.raises(LLMCallError) as exc:
        HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    message = str(exc.value)
    assert "429" in message
    assert _SECRET not in message
    assert "Bearer" not in message


def test_http_error_response_body_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def _raise(request: Any) -> Any:
        raise urllib.error.HTTPError(
            url="https://provider.invalid/v1/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=BytesIO(f'{{"error":"bad bearer token {_SECRET}"}}'.encode()),
        )

    _patch_urlopen(monkeypatch, _raise)

    with pytest.raises(LLMCallError) as exc:
        HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    message = str(exc.value)
    assert "401" in message
    assert _SECRET not in message
    assert "bearer token" not in message.casefold()


def test_model_not_found_uses_next_configured_free_tier_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(
        monkeypatch,
        TRIPWISE_LLM_MODEL="retired-model",
        TRIPWISE_LLM_FALLBACK_MODELS="working-model",
    )
    models_seen: list[str] = []

    def _handler(request: Any) -> Any:
        body = json.loads(request.data.decode("utf-8"))
        models_seen.append(body["model"])
        if body["model"] == "retired-model":
            raise urllib.error.HTTPError(
                url="https://provider.invalid/v1/chat/completions",
                code=404,
                msg="Not Found",
                hdrs=None,  # type: ignore[arg-type]
                fp=BytesIO(b'{"error":{"message":"model not found"}}'),
            )
        return _FakeResponse(_envelope('{"answer": "fallback-ok"}'))

    _patch_urlopen(monkeypatch, _handler)

    result = HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert isinstance(result, Tiny)
    assert result.answer == "fallback-ok"
    assert models_seen == ["retired-model", "working-model"]


def test_a_timeout_maps_to_llm_timeout_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure(monkeypatch)

    def _raise(request: Any) -> Any:
        raise TimeoutError("timed out")

    _patch_urlopen(monkeypatch, _raise)

    with pytest.raises(LLMTimeoutError):
        HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)


def test_the_call_ceiling_refuses_further_provider_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zero-spend guard: a runaway loop must not silently drain a free-tier
    quota. The ceiling is per-instance, and one instance serves one request."""
    _configure(monkeypatch, TRIPWISE_LLM_MAX_CALLS="2")
    seen = _patch_urlopen(monkeypatch, lambda request: _FakeResponse(_envelope('{"answer": "ok"}')))
    client = HostedFreeTier()

    client.complete_json(node="intake", system="s", user="u", schema=Tiny)
    client.complete_json(node="intake", system="s", user="u", schema=Tiny)

    with pytest.raises(LLMCallError, match="ceiling"):
        client.complete_json(node="intake", system="s", user="u", schema=Tiny)

    # The refused call never reached the transport.
    assert seen["called"] == 2


def test_json_mode_can_be_disabled_for_providers_that_reject_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, TRIPWISE_LLM_JSON_MODE="0")
    seen = _patch_urlopen(monkeypatch, lambda request: _FakeResponse(_envelope('{"answer": "ok"}')))

    HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    body = json.loads(seen["request"].data.decode("utf-8"))
    assert "response_format" not in body


def _http_error(code: int, headers: dict[str, str] | None = None) -> urllib.error.HTTPError:
    from email.message import Message

    hdrs = Message()
    for key, value in (headers or {}).items():
        hdrs[key] = value
    return urllib.error.HTTPError(
        url="https://provider.invalid/v1/chat/completions",
        code=code,
        msg="error",
        hdrs=hdrs,
        fp=BytesIO(b'{"error":"limited"}'),
    )


def test_tools_instruction_keeps_the_json_schema_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offering tools used to rebuild the system prompt from the raw system text and so
    dropped the schema/top-level-properties instruction json_mode adds."""
    _configure(monkeypatch)
    seen = _patch_urlopen(monkeypatch, lambda r: _FakeResponse(_envelope('{"answer": "ok"}')))

    HostedFreeTier().complete_json(
        node="planner",
        system="NODE-PROMPT",
        user="u",
        schema=Tiny,
        tools=[{"name": "search_places", "description": "d", "parameters": {}}],
    )

    system_prompt = json.loads(seen["request"].data)["messages"][0]["content"]
    assert system_prompt.startswith("NODE-PROMPT")
    assert "conforming to this JSON Schema" in system_prompt
    assert json.dumps(Tiny.model_json_schema()) in system_prompt
    assert "call a tool" in system_prompt
    assert "search_places" in system_prompt


def test_system_prompt_without_tools_or_json_mode_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure(monkeypatch, TRIPWISE_LLM_JSON_MODE="0")
    seen = _patch_urlopen(monkeypatch, lambda r: _FakeResponse(_envelope('{"answer": "ok"}')))

    HostedFreeTier().complete_json(node="intake", system="NODE-PROMPT", user="u", schema=Tiny)

    assert json.loads(seen["request"].data)["messages"][0]["content"] == "NODE-PROMPT"


def test_rate_limit_falls_through_to_next_model_without_sleeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    _configure(
        monkeypatch, TRIPWISE_LLM_MODEL="busy-model", TRIPWISE_LLM_FALLBACK_MODELS="free-model"
    )
    models_seen: list[str] = []

    def _handler(request: Any) -> Any:
        model = json.loads(request.data)["model"]
        models_seen.append(model)
        if model == "busy-model":
            raise _http_error(429, {"Retry-After": "30"})
        return _FakeResponse(_envelope('{"answer": "fallback-ok"}'))

    seen = _patch_urlopen(monkeypatch, _handler)
    client = HostedFreeTier()

    result = client.complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert isinstance(result, Tiny) and result.answer == "fallback-ok"
    assert models_seen == ["busy-model", "free-model"]  # the limited model is not re-called
    assert sleeps == []
    assert seen["called"] == 2 and client.calls_made == 2


def test_rate_limit_on_every_model_is_bounded_by_chain_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    _configure(monkeypatch, TRIPWISE_LLM_MODELS="m1,m2,m3")
    seen = _patch_urlopen(monkeypatch, lambda r: (_ for _ in ()).throw(_http_error(429)))
    client = HostedFreeTier()

    with pytest.raises(LLMCallError):
        client.complete_json(node="intake", system="s", user="u", schema=Tiny)

    # m1 and m2 fall through immediately; only the last model retries in place, and
    # every attempt counts against the ceiling: 2 + (1 + max_retries), not 3 * (1 + max_retries).
    assert seen["called"] == 2 + 1 + client.max_retries
    assert client.calls_made == seen["called"]
    assert sum(sleeps) <= client.max_backoff_seconds


def test_single_model_429_honors_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    _configure(monkeypatch)
    attempts = {"n": 0}

    def _handler(request: Any) -> Any:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _http_error(429, {"Retry-After": "7"})
        return _FakeResponse(_envelope('{"answer": "ok"}'))

    _patch_urlopen(monkeypatch, _handler)

    result = HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert isinstance(result, Tiny)
    assert sleeps == [7.0]


def test_retry_after_beyond_the_backoff_budget_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    _configure(monkeypatch)
    seen = _patch_urlopen(
        monkeypatch, lambda r: (_ for _ in ()).throw(_http_error(429, {"Retry-After": "3600"}))
    )

    with pytest.raises(LLMCallError, match="backoff budget"):
        HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert sleeps == []
    assert seen["called"] == 1


def test_retry_after_accepts_an_http_date_and_ignores_garbage() -> None:
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    soon = format_datetime(datetime.now(UTC) + timedelta(seconds=30), usegmt=True)
    parsed = HostedFreeTier._retry_after_seconds({"Retry-After": soon})
    assert parsed is not None and 20 <= parsed <= 31
    assert HostedFreeTier._retry_after_seconds({"Retry-After": "not-a-date"}) is None
    assert HostedFreeTier._retry_after_seconds({}) is None
    assert HostedFreeTier._retry_after_seconds(None) is None


def test_rate_limit_fallthrough_respects_the_call_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: None)
    _configure(monkeypatch, TRIPWISE_LLM_MODELS="m1,m2,m3", TRIPWISE_LLM_MAX_CALLS="2")
    seen = _patch_urlopen(monkeypatch, lambda r: (_ for _ in ()).throw(_http_error(429)))

    with pytest.raises(LLMCallError, match="ceiling"):
        HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    assert seen["called"] == 2
