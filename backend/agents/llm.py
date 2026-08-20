from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path
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


# Honest self-identification on every outbound provider call (spec 05's Fetcher
# rule: "identify honestly via user agent"). Also load-bearing: urllib's default
# UA is rejected by some providers' edge protection.
_USER_AGENT = "TripPlanner/0.1 (non-commercial student project)"


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
        fallback_models = [
            value.strip()
            for value in os.getenv("TRIPWISE_LLM_FALLBACK_MODELS", "").split(",")
            if value.strip()
        ]
        ordered_models = [
            value.strip()
            for value in os.getenv("TRIPWISE_LLM_MODELS", "").split(",")
            if value.strip()
        ]
        if ordered_models:
            self.models = ordered_models
            self.model = ordered_models[0]
        elif self.model:
            self.models = [self.model, *fallback_models]
        else:
            self.models = []
        self.api_key = os.getenv("TRIPWISE_LLM_API_KEY")
        self.json_mode = os.getenv("TRIPWISE_LLM_JSON_MODE", "1") != "0"
        self.max_calls = int(os.getenv("TRIPWISE_LLM_MAX_CALLS", str(self.DEFAULT_MAX_CALLS)))
        self.calls_made = 0

    def _endpoint(self) -> str:
        missing = [
            name
            for name, value in (
                ("TRIPWISE_LLM_BASE_URL", self.base_url),
                ("TRIPWISE_LLM_MODEL", self.models[0] if self.models else None),
                ("TRIPWISE_LLM_API_KEY", self.api_key),
            )
            if not value
        ]
        if missing:
            raise LLMCallError("HostedFreeTier is not configured; set " + ", ".join(missing))
        assert self.base_url is not None
        return self.base_url.rstrip("/") + "/chat/completions"

    def _reserve_provider_call(self) -> None:
        if self.calls_made >= self.max_calls:
            raise LLMCallError(
                f"HostedFreeTier call ceiling reached ({self.max_calls}); "
                "refusing further provider calls to protect the free-tier quota"
            )
        self.calls_made += 1

    def _redact_provider_detail(self, detail: str) -> str:
        redacted = detail
        if self.api_key:
            redacted = redacted.replace(self.api_key, "[REDACTED]")
        redacted = re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", redacted)
        redacted = re.sub(r"sk-[A-Za-z0-9._~+/=-]+", "[REDACTED]", redacted)
        return redacted[:500]

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

        system_prompt = system
        if self.json_mode:
            # Provider adaptation, deliberately here and not in the four call
            # sites' prompts (those are Tier-F structure; their phrasing stays
            # theirs). OpenAI-style json_object mode returns *some* object, not
            # necessarily the right shape: asked for "strict TripSpec JSON",
            # llama-3.3-70b returned {"trip_spec": {...}} - reading the model
            # name as a wrapper key - and did it again on the repair retry, so
            # intake failed outright. Naming the fields removes the guess.
            system_prompt = (
                f"{system_prompt}\n\n"
                "Return ONE JSON object conforming to this JSON Schema. Emit the "
                "properties at the TOP LEVEL. Do not nest them under a wrapper "
                "key, and do not echo the schema itself.\n"
                f"{json.dumps(schema.model_json_schema())}"
            )
        if tools:
            system_prompt = (
                f"{system}\n\nYou may either return the requested JSON object, or call a "
                "tool by returning ONLY that tool's argument object as JSON.\n"
                f"Available tools:\n{json.dumps(tools, indent=2)}"
            )

        body: dict[str, Any] = {
            "model": self.models[0],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}

        import time

        max_retries = 3
        raw = ""
        last_model_error: LLMCallError | None = None
        for model_index, model in enumerate(self.models):
            body["model"] = model
            request = urllib.request.Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    # Identify honestly (spec 05's Fetcher rule), and because
                    # urllib's default "Python-urllib/x.y" is blocked outright by
                    # some providers' edge protection - Groq returns HTTP 403
                    # Cloudflare error 1010 for it, while the identical request
                    # with a real UA succeeds.
                    "User-Agent": _USER_AGENT,
                },
                method="POST",
            )

            for attempt in range(max_retries + 1):
                try:
                    self._reserve_provider_call()
                    with urllib.request.urlopen(request, timeout=timeout_s) as response:
                        raw = response.read().decode("utf-8")
                    last_model_error = None
                    break
                except TimeoutError as exc:
                    if attempt == max_retries:
                        raise LLMTimeoutError(f"{node} timed out after {timeout_s}s") from exc
                    time.sleep(2)
                except urllib.error.HTTPError as exc:
                    detail = (
                        exc.read().decode("utf-8", errors="replace")
                        if getattr(exc, "fp", None)
                        else str(exc)
                    )
                    safe_detail = self._redact_provider_detail(detail)
                    if exc.code == 429 and attempt < max_retries:
                        retry_after = exc.headers.get("Retry-After") if exc.headers else None
                        delay = float(retry_after) if retry_after else float(2**attempt * 3)
                        time.sleep(min(60.0, delay))
                        continue
                    if exc.code == 404 and model_index < len(self.models) - 1:
                        last_model_error = LLMCallError(
                            f"{node} provider rejected configured model {model}: "
                            f"HTTP {exc.code}: {safe_detail}"
                        )
                        break
                    raise LLMCallError(
                        f"{node} provider returned HTTP {exc.code}: {safe_detail}"
                    ) from exc
                except urllib.error.URLError as exc:
                    if isinstance(exc.reason, TimeoutError):
                        if attempt == max_retries:
                            raise LLMTimeoutError(
                                f"{node} timed out after {timeout_s}s"
                            ) from exc
                        time.sleep(2)
                        continue
                    raise LLMCallError(f"{node} provider unreachable: {exc.reason}") from exc
            if raw and last_model_error is None:
                break
        if not raw and last_model_error is not None:
            raise LLMCallError(f"{node} no configured hosted free-tier model succeeded") from (
                last_model_error
            )

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


_DEFAULT_RECORDINGS_DIR = Path(__file__).parent.parent / "evals" / "recorded"


def compute_recording_key(system: str, user: str, model: str = "") -> str:
    raw = f"{system}\n---USER---\n{user}\n---MODEL---\n{model}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]


class RecordingLLMClient:
    """Wraps an LLMClient, recording raw response payloads to disk under
    evals/recorded/{node}/{key}.json."""

    def __init__(
        self, inner: LLMClient | Any, recordings_dir: Path = _DEFAULT_RECORDINGS_DIR
    ) -> None:
        self.inner = inner
        self.recordings_dir = recordings_dir
        self.calls_recorded = 0

    @property
    def model(self) -> str:
        return str(getattr(self.inner, "model", "") or "")

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
        result = self.inner.complete_json(
            node=node,
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
            tools=tools,
        )

        key = compute_recording_key(system, user, self.model)
        target_dir = self.recordings_dir / node
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"{key}.json"

        if isinstance(result, BaseModel):
            response_payload: Any = result.model_dump(mode="json")
        elif isinstance(result, (dict, list, str, int, float, bool)):
            response_payload = result
        else:
            response_payload = str(result)

        data = {
            "key": key,
            "node": node,
            "model": self.model,
            "system": system,
            "user": user,
            "response": response_payload,
        }
        target_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self.calls_recorded += 1
        return result


class ReplayLLMClient:
    """Replays recorded LLM responses from evals/recorded/ with zero network calls."""

    def __init__(
        self, recordings_dir: Path = _DEFAULT_RECORDINGS_DIR, model: str = ""
    ) -> None:
        self.recordings_dir = recordings_dir
        self.model = model
        self.calls_replayed = 0

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
        key = compute_recording_key(system, user, self.model)
        target_file = self.recordings_dir / node / f"{key}.json"

        if not target_file.exists():
            raise LLMCallError(
                f"No recording for {node} (key={key}, model={self.model}). "
                "Run in --record mode with a live client to capture this prompt response."
            )

        data = json.loads(target_file.read_text(encoding="utf-8"))
        payload = data.get("response")
        self.calls_replayed += 1
        return _validate_or_intent(payload, schema, tools)
