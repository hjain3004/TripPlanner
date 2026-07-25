from __future__ import annotations

import os
from collections import defaultdict
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agents.models import DraftItinerary, RetrievalContext, TripSpec
from core.models import SampleFlight, SampleHotel


class JudgeCallError(RuntimeError):
    pass


class JudgeScores(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groundedness: int = Field(ge=1, le=5)
    interest_match: int = Field(ge=1, le=5)
    geographic_coherence: int = Field(ge=1, le=5)
    pacing: int = Field(ge=1, le=5)
    budget_respect: int = Field(ge=1, le=5)

    def dimensions(self) -> dict[str, int]:
        return {
            "groundedness": self.groundedness,
            "interest_match": self.interest_match,
            "geographic_coherence": self.geographic_coherence,
            "pacing": self.pacing,
            "budget_respect": self.budget_respect,
        }


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores: JudgeScores
    rationale: str = Field(min_length=1)


class TokenTotals(BaseModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LatencySummary(BaseModel):
    p50_ms: int = Field(ge=0)
    p95_ms: int = Field(ge=0)


class JudgeRunResult(BaseModel):
    case_id: str
    run_index: int = Field(ge=0)
    verdict: JudgeVerdict
    latency_ms: int = Field(default=0, ge=0)
    tokens: TokenTotals = Field(default_factory=TokenTotals)


class JudgeClient(Protocol):
    def complete_json(
        self,
        *,
        node: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout_s: int = 20,
    ) -> JudgeVerdict: ...


class ScriptedJudgeClient:
    def __init__(self, scripts: dict[str, list[object]]) -> None:
        self._scripts = {node: list(rows) for node, rows in scripts.items()}
        self.invocations: dict[str, int] = defaultdict(int)

    def complete_json(
        self,
        *,
        node: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout_s: int = 20,
    ) -> JudgeVerdict:
        self.invocations[node] += 1
        queue = self._scripts.get(node, [])
        if not queue:
            raise JudgeCallError(f"no scripted judge response for {node}")
        response = queue.pop(0)
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, JudgeVerdict):
            return response
        if isinstance(response, str):
            return JudgeVerdict.model_validate_json(response)
        if isinstance(response, dict):
            return JudgeVerdict.model_validate(response)
        raise JudgeCallError(
            f"unsupported scripted judge response for {node}: {type(response).__name__}"
        )


class HostedJudgeClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("TRIPWISE_JUDGE_BASE_URL")
        self.model = os.getenv("TRIPWISE_JUDGE_MODEL")
        self.api_key = os.getenv("TRIPWISE_JUDGE_API_KEY")

    def complete_json(
        self,
        *,
        node: str,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout_s: int = 20,
    ) -> JudgeVerdict:
        if not self.api_key:
            raise JudgeCallError("HostedJudgeClient disabled without TRIPWISE_JUDGE_API_KEY")
        raise JudgeCallError("HostedJudgeClient live calls are not implemented for offline tests")


def complete_judge_with_repair(
    client: JudgeClient,
    *,
    node: str,
    system: str,
    user: str,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    timeout_s: int = 20,
) -> JudgeVerdict:
    try:
        return client.complete_json(
            node=node,
            system=system,
            user=user,
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
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            )
        except ValidationError as retry_exc:
            raise JudgeCallError(f"{node} judge schema repair failed") from retry_exc


def build_judge_prompt(
    spec: TripSpec,
    itinerary: DraftItinerary,
    retrieval: RetrievalContext,
    *,
    flight: SampleFlight | None = None,
    hotel: SampleHotel | None = None,
) -> tuple[str, str]:
    system = (
        "You are the TripPlanner itinerary quality judge. Return only JudgeVerdict JSON. "
        "Score exactly these dimensions from 1 to 5: groundedness, interest_match, "
        "geographic_coherence, pacing, budget_respect. Use temperature 0. "
        "Use only supplied evidence. Do not reward prose style. "
        "Do not infer unstated attraction facts. "
        "Groundedness is 5 only if all POIs and areas are supplied and no factual claim "
        "is invented. Geographic coherence concerns area clustering. "
        "Pacing concerns item count, durations and trip pace. "
        "Budget respect concerns style/budget consistency with selected facts."
    )
    user = (
        "TripSpec:\n"
        f"{spec.model_dump_json()}\n"
        "DraftItinerary:\n"
        f"{itinerary.model_dump_json()}\n"
        "POI rows:\n"
        f"{chr(10).join(retrieval.poi_rows)}\n"
        "Area rows:\n"
        f"{chr(10).join(retrieval.area_rows)}\n"
        "Selected flight:\n"
        f"{flight.model_dump_json() if flight is not None else 'NONE'}\n"
        "Selected hotel:\n"
        f"{hotel.model_dump_json() if hotel is not None else 'NONE'}"
    )
    return system, user
