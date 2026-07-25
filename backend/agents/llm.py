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
    ) -> T: ...


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
    ) -> T:
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
            return schema.model_validate(response)
        raise LLMCallError(f"unsupported scripted response for {node}: {type(response).__name__}")


class HostedFreeTier:
    def __init__(self) -> None:
        self.base_url = os.getenv("TRIPWISE_LLM_BASE_URL")
        self.model = os.getenv("TRIPWISE_LLM_MODEL")
        self.api_key = os.getenv("TRIPWISE_LLM_API_KEY")

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
    ) -> T:
        raise LLMCallError("HostedFreeTier is configured for runtime use, not test execution")


class OllamaLocal:
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
    ) -> T:
        raise LLMCallError("OllamaLocal is configured for runtime use, not test execution")


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
) -> T:
    try:
        return client.complete_json(
            node=node,
            system=system,
            user=user,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout_s=timeout_s,
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
            )
        except (ValidationError, json.JSONDecodeError) as retry_exc:
            raise LLMCallError(f"{node} schema repair failed") from retry_exc
    except json.JSONDecodeError as exc:
        raise LLMCallError(f"{node} returned invalid JSON") from exc
