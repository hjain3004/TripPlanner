import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from agents.llm import (
    LLMCallError,
    RecordingLLMClient,
    ReplayLLMClient,
    compute_recording_key,
)


class DummySchema(BaseModel):
    greeting: str
    count: int


class StubTransport:
    def __init__(self, response_payload: dict[str, Any], model: str = "stub-model") -> None:
        self.response_payload = response_payload
        self.model = model
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self,
        *,
        node: str,
        system: str,
        user: str,
        schema: type[Any],
        temperature: float = 0.0,
        max_tokens: int = 2048,
        timeout_s: int = 20,
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        self.calls.append({"node": node, "system": system, "user": user})
        return schema.model_validate(self.response_payload)


def test_record_and_replay_round_trip(tmp_path: Path) -> None:
    rec_dir = tmp_path / "recorded"
    stub = StubTransport({"greeting": "Hello", "count": 42})
    rec_client = RecordingLLMClient(stub, recordings_dir=rec_dir)

    # 1. Record call
    res1 = rec_client.complete_json(
        node="intake",
        system="System prompt 1",
        user="User prompt 1",
        schema=DummySchema,
    )
    assert res1.greeting == "Hello"
    assert res1.count == 42
    assert len(stub.calls) == 1

    # Check file exists on disk
    key = compute_recording_key("System prompt 1", "User prompt 1", "stub-model")
    target_file = rec_dir / "intake" / f"{key}.json"
    assert target_file.exists()

    # 2. Replay call
    replay_client = ReplayLLMClient(recordings_dir=rec_dir, model="stub-model")
    res2 = replay_client.complete_json(
        node="intake",
        system="System prompt 1",
        user="User prompt 1",
        schema=DummySchema,
    )
    assert res2.greeting == "Hello"
    assert res2.count == 42
    # Transport was NOT called again on replay
    assert len(stub.calls) == 1

    # 3. Prompt change invalidates key and causes clear error on replay
    with pytest.raises(LLMCallError, match="No recording for intake"):
        replay_client.complete_json(
            node="intake",
            system="Modified system prompt",
            user="User prompt 1",
            schema=DummySchema,
        )


def test_no_api_key_stored_in_recordings(tmp_path: Path) -> None:
    fake_secret = "gsk_test_super_secret_key_12345"
    os.environ["TRIPWISE_LLM_API_KEY"] = fake_secret

    rec_dir = tmp_path / "recorded"
    stub = StubTransport({"greeting": "Hi", "count": 1})
    rec_client = RecordingLLMClient(stub, recordings_dir=rec_dir)

    rec_client.complete_json(
        node="intake",
        system="System prompt with secret in memory",
        user="User query",
        schema=DummySchema,
    )

    for p in rec_dir.glob("**/*.json"):
        content = p.read_text(encoding="utf-8")
        assert fake_secret not in content, f"Secret leaked into recording fixture: {p}"
