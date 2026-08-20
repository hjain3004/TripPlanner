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
    seen = _patch_urlopen(
        monkeypatch, lambda request: _FakeResponse(_envelope('{"answer": "ok"}'))
    )
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
    seen = _patch_urlopen(
        monkeypatch, lambda request: _FakeResponse(_envelope('{"answer": "ok"}'))
    )

    HostedFreeTier().complete_json(node="intake", system="s", user="u", schema=Tiny)

    body = json.loads(seen["request"].data.decode("utf-8"))
    assert "response_format" not in body
