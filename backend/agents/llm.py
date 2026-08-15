from __future__ import annotations

import json
import os
from collections import defaultdict
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMCallError(RuntimeError):
    pass


class LLMTimeoutError(LLMCallError):
    pass


class LLMClient(Protocol):
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
    ) -> T | Any: ...


class ScriptedLLMClient:
    def __init__(self, scripts: dict[str, list[object]]) -> None:
        self._scripts = {node: list(rows) for node, rows in scripts.items()}
        self.invocations: dict[str, int] = defaultdict(int)

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
        self.invocations[node] += 1
        queue = self._scripts.get(node, [])
        if not queue:
            raise LLMCallError(f"no scripted response for {node}")
        response = queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        if response == "__timeout__":
            raise LLMTimeoutError(f"{node} timed out")
        if isinstance(response, schema):
            return response
        if isinstance(response, str):
            return schema.model_validate_json(response)
        if isinstance(response, dict):
            try:
                return schema.model_validate(response)
            except ValidationError:
                if tools is not None:
                    from agents.discovery.contracts import SearchIntent
                    return SearchIntent.model_validate(response)
                raise
        raise LLMCallError(f"unsupported scripted response for {node}: {type(response).__name__}")


def _strip_code_fence(text: str) -> str:
    """Some models wrap JSON in ```json fences despite JSON mode."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:]
    if body.lower().startswith("json"):
        body = body[4:]
    end = body.rfind("```")
    return (body[:end] if end != -1 else body).strip()


def _validate_or_intent(
    payload: Any, schema: type[T], tools: list[dict[str, Any]] | None
) -> T | Any:
    """The planner call site accepts EITHER its target schema or a SearchIntent
    (a tool call). Mirrors ScriptedLLMClient so both clients behave identically.

    ValidationError is deliberately allowed to escape: complete_with_repair
    catches it and retries once with the error appended to the prompt.
    """
    try:
        return schema.model_validate(payload)
    except ValidationError:
        if tools is None:
            raise
        from agents.discovery.contracts import SearchIntent

        return SearchIntent.model_validate(payload)


class HostedFreeTier:
    """Real chat-completions client for any OpenAI-compatible endpoint.

    Provider-agnostic on purpose: works against anything exposing
    POST {base_url}/chat/completions with the OpenAI request/response shape.
    Configured entirely from the environment:

        TRIPWISE_LLM_BASE_URL   provider's OpenAI-compatible base URL
        TRIPWISE_LLM_MODEL      model name
        TRIPWISE_LLM_API_KEY    provider key - read from env, never logged
        TRIPWISE_LLM_JSON_MODE  optional; "0" disables response_format
                                json_object for providers that reject it
        TRIPWISE_LLM_MAX_CALLS  optional; per-instance call ceiling

    Zero-spend (CLAUDE.md): point this at a free tier where overage is
    mechanically impossible - a key with no billing method attached, which
    hard-stops on rate limits instead of billing. Code cannot verify a
    property of someone's provider account, so it enforces what it can: a
    per-instance call ceiling, so a runaway loop cannot silently drain a
    quota. One instance serves one plan request (api/main.py), and the
    pipeline's four call sites plus I5's bounded discovery loop stay well
    under the default.

    Uses stdlib urllib rather than httpx to avoid promoting a dev-only
    dependency into the runtime dependency set.
    """

    DEFAULT_MAX_CALLS = 25

    def __init__(self) -> None:
        self.base_url = os.getenv("TRIPWISE_LLM_BASE_URL")
        self.model = os.getenv("TRIPWISE_LLM_MODEL")
        self.api_key = os.getenv("TRIPWISE_LLM_API_KEY")
        self.json_mode = os.getenv("TRIPWISE_LLM_JSON_MODE", "1") != "0"
        self.max_calls = int(os.getenv("TRIPWISE_LLM_MAX_CALLS", str(self.DEFAULT_MAX_CALLS)))
        self.calls_made = 0

    def _endpoint(self) -> str:
        missing = [
            name
            for name, value in (
                ("TRIPWISE_LLM_BASE_URL", self.base_url),
                ("TRIPWISE_LLM_MODEL", self.model),
                ("TRIPWISE_LLM_API_KEY", self.api_key),
            )
            if not value
        ]
        if missing:
            raise LLMCallError("HostedFreeTier is not configured; set " + ", ".join(missing))
        assert self.base_url is not None
        return self.base_url.rstrip("/") + "/chat/completions"

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
        import urllib.error
        import urllib.request

        endpoint = self._endpoint()

        if self.calls_made >= self.max_calls:
            raise LLMCallError(
                f"HostedFreeTier call ceiling reached ({self.max_calls}); "
                "refusing further provider calls to protect the free-tier quota"
            )
        self.calls_made += 1

        system_prompt = system
        if tools:
            system_prompt = (
                f"{system}\n\nYou may either return the requested JSON object, or call a "
                "tool by returning ONLY that tool's argument object as JSON.\n"
                f"Available tools:\n{json.dumps(tools, indent=2)}"
            )

        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}

        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            raise LLMTimeoutError(f"{node} timed out after {timeout_s}s") from exc
        except urllib.error.HTTPError as exc:
            # Never surface request headers - they carry the API key.
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMCallError(f"{node} provider returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise LLMTimeoutError(f"{node} timed out after {timeout_s}s") from exc
            raise LLMCallError(f"{node} provider unreachable: {exc.reason}") from exc

        envelope = json.loads(raw)
        try:
            content = envelope["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMCallError(f"{node} provider returned an unexpected envelope") from exc
        if not content:
            raise LLMCallError(f"{node} provider returned empty content")

        payload = json.loads(_strip_code_fence(content))
        return _validate_or_intent(payload, schema, tools)


class OllamaLocal:
    """Unimplemented alternative client, kept as a documented seam.

    It fails loudly and immediately rather than pretending to work: there is
    no transport here. HostedFreeTier is the implemented runtime client. If a
    local, no-credential model is ever wanted, implement this against
    Ollama's /api/chat and point api/main.py at it.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("TRIPWISE_OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("TRIPWISE_OLLAMA_MODEL", "llama3.1")

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
        raise LLMCallError(
            "OllamaLocal has no transport; use HostedFreeTier, or implement this client"
        )


def complete_with_repair(
    client: LLMClient,
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
    try:
        return client.complete_json(
            node=node,
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            tools=tools,
        )
    except ValidationError as exc:
        repair_user = f"{user}\n\nSchema validation error, return corrected JSON only:\n{exc}"
        try:
            return client.complete_json(
                node=node,
                system=system,
                user=repair_user,
                schema=schema,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
                tools=tools,
            )
        except (ValidationError, json.JSONDecodeError) as retry_exc:
            raise LLMCallError(f"{node} schema repair failed") from retry_exc
    except json.JSONDecodeError as exc:
        raise LLMCallError(f"{node} returned invalid JSON") from exc
