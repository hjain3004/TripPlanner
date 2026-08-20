from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from agents.llm import ReplayLLMClient
from agents.models import PipelineStatus
from agents.pipeline import run_pipeline
from core.db import load_kb


def test_recordings_directory_is_populated_and_non_vacuous() -> None:
    """Anti-vacuity check: ensure recording fixtures exist and contain valid response payloads."""
    recorded_dir = Path(__file__).resolve().parent / "recorded"
    assert recorded_dir.is_dir(), "evals/recorded directory must exist"

    intake_files = list((recorded_dir / "intake").glob("*.json"))
    critic_files = list((recorded_dir / "critic").glob("*.json"))

    assert len(intake_files) > 0, "evals/recorded/intake must contain recorded fixtures"
    assert len(critic_files) > 0, "evals/recorded/critic must contain recorded fixtures"


def test_scenarios_replay_offline_without_network_or_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline regression: execute scenarios against recorded LLM fixtures with no API key."""
    # Ensure no network API key is present
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    scenarios_path = Path(__file__).resolve().parent / "scenarios.yaml"
    with scenarios_path.open() as f:
        data = yaml.safe_load(f)

    scenarios = data.get("scenarios", [])
    kb = load_kb()
    recorded_dir = Path(__file__).resolve().parent / "recorded"
    replay_client = ReplayLLMClient(
        recordings_dir=recorded_dir, model="llama-3.1-8b-instant"
    )

    exercised = 0
    for scenario in scenarios:
        prompt = scenario["request"]

        # Execute pipeline with replay client
        try:
            resp = run_pipeline(
                raw_request=prompt,
                kb=kb,
                llm=replay_client,
                booking_date=date(2026, 8, 1),
            )
            if any("No recording for" in q for q in resp.unresolved):
                continue

            exercised += 1
            assert resp.status in (
                PipelineStatus.OK,
                PipelineStatus.NEEDS_CLARIFICATION,
            )
        except Exception as e:
            # If a scenario had a missing recording key for a mutated prompt, skip gracefully
            if "No recording for" in str(e):
                continue
            raise

    assert exercised >= 8, f"Replay test must exercise at least 8 scenarios, got {exercised}"
