from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class LLMNodeConfig(BaseModel):
    temperature: float
    max_tokens: int
    timeout_s: int
    max_replan_loops: int | None = None


class EstimatorConfig(BaseModel):
    per_diem_sgd_minor: dict[str, dict[str, int]]


class AgentConfig(BaseModel):
    llm: dict[str, LLMNodeConfig]
    estimator: EstimatorConfig


def load_agent_config(path: Path = CONFIG_PATH) -> AgentConfig:
    raw = yaml.safe_load(path.read_text())
    return AgentConfig.model_validate(raw)
