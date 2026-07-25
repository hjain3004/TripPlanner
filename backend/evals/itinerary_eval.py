from __future__ import annotations

import statistics
import time
from typing import Iterable

from pydantic import BaseModel, Field

from agents.models import DraftItinerary, TripSpec
from agents.retrieval import retrieve_candidates
from core.db import KnowledgeBase
from evals.itinerary_fixtures import (
    AnchorItinerary,
    GoldenItineraryCase,
    load_anchor_itineraries,
    load_golden_itineraries,
)
from evals.judge import (
    JudgeClient,
    JudgeRunResult,
    JudgeScores,
    LatencySummary,
    TokenTotals,
    build_judge_prompt,
    complete_judge_with_repair,
)

DIMENSIONS = [
    "groundedness",
    "interest_match",
    "geographic_coherence",
    "pacing",
    "budget_respect",
]


class GateM3Error(AssertionError):
    pass


class RankedAnchor(BaseModel):
    case_id: str
    overall_mean: float
    expected_rank: int


class AnchorValidationResult(BaseModel):
    ranked_anchors: list[RankedAnchor]
    passed: bool
    failures: list[str] = Field(default_factory=list)


class ItineraryAggregate(BaseModel):
    case_id: str
    run_count: int
    overall_mean: float
    dimension_means: dict[str, float]
    dimension_mins: dict[str, int]
    dimension_variance: dict[str, float]
    runs: list[JudgeRunResult]


class GateStatus(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    anchor_result: AnchorValidationResult
    golden_aggregates: list[ItineraryAggregate]
    overall_mean: float
    dimension_means: dict[str, float]
    latency: LatencySummary
    tokens: TokenTotals
    gate: GateStatus
    runs_per_case: int


def _score_values(scores: JudgeScores) -> dict[str, int]:
    return scores.dimensions()


def _overall(scores: JudgeScores) -> float:
    values = list(_score_values(scores).values())
    return sum(values) / len(values)


def _percentile(sorted_values: list[int], percentile: float) -> int:
    if not sorted_values:
        return 0
    index = round((len(sorted_values) - 1) * percentile)
    return sorted_values[index]


def _token_estimate(system: str, user: str, rationale: str) -> TokenTotals:
    return TokenTotals(
        prompt_tokens=len(system.split()) + len(user.split()),
        completion_tokens=len(rationale.split()) + len(DIMENSIONS) * 4,
    )


def _run_case(
    case_id: str,
    spec: TripSpec,
    itinerary: DraftItinerary,
    kb: KnowledgeBase,
    judge: JudgeClient,
    run_index: int,
) -> JudgeRunResult:
    retrieval = retrieve_candidates(spec, kb)
    system, user = build_judge_prompt(spec, itinerary, retrieval)
    started = time.perf_counter()
    verdict = complete_judge_with_repair(
        judge,
        node="quality",
        system=system,
        user=user,
        temperature=0.0,
    )
    latency_ms = max(0, int((time.perf_counter() - started) * 1000))
    return JudgeRunResult(
        case_id=case_id,
        run_index=run_index,
        verdict=verdict,
        latency_ms=latency_ms,
        tokens=_token_estimate(system, user, verdict.rationale),
    )


def _aggregate(case_id: str, runs: list[JudgeRunResult]) -> ItineraryAggregate:
    by_dimension = {
        dimension: [getattr(run.verdict.scores, dimension) for run in runs]
        for dimension in DIMENSIONS
    }
    dimension_means = {
        dimension: sum(values) / len(values) for dimension, values in by_dimension.items()
    }
    return ItineraryAggregate(
        case_id=case_id,
        run_count=len(runs),
        overall_mean=sum(dimension_means.values()) / len(dimension_means),
        dimension_means=dimension_means,
        dimension_mins={dimension: min(values) for dimension, values in by_dimension.items()},
        dimension_variance={
            dimension: statistics.pvariance(values) for dimension, values in by_dimension.items()
        },
        runs=runs,
    )


def _anchor_result(
    anchors: list[AnchorItinerary],
    runs: list[JudgeRunResult],
) -> AnchorValidationResult:
    ranked = sorted(
        [
            RankedAnchor(
                case_id=anchor.case_id,
                expected_rank=anchor.expected_rank,
                overall_mean=_overall(run.verdict.scores),
            )
            for anchor, run in zip(anchors, runs, strict=True)
        ],
        key=lambda row: (-row.overall_mean, row.expected_rank, row.case_id),
    )
    expected = [anchor.case_id for anchor in sorted(anchors, key=lambda row: row.expected_rank)]
    got = [row.case_id for row in ranked]
    failures = [] if got == expected else [f"anchor ranking {got} != {expected}"]
    return AnchorValidationResult(ranked_anchors=ranked, passed=not failures, failures=failures)


def _gate(anchor_result: AnchorValidationResult, aggregates: list[ItineraryAggregate]) -> GateStatus:
    failures = list(anchor_result.failures)
    for aggregate in aggregates:
        if aggregate.overall_mean < 4.0:
            failures.append(f"{aggregate.case_id}: overall_mean {aggregate.overall_mean:.2f} < 4.0")
        for dimension, mean in aggregate.dimension_means.items():
            if mean < 3.0:
                failures.append(f"{aggregate.case_id}: {dimension} mean {mean:.2f} < 3.0")
        if aggregate.dimension_mins["groundedness"] != 5:
            failures.append(f"{aggregate.case_id}: groundedness score below 5")
    return GateStatus(passed=not failures, failures=failures)


def _summary_means(aggregates: list[ItineraryAggregate]) -> dict[str, float]:
    return {
        dimension: sum(aggregate.dimension_means[dimension] for aggregate in aggregates)
        / len(aggregates)
        for dimension in DIMENSIONS
    }


def _latency(runs: Iterable[JudgeRunResult]) -> LatencySummary:
    values = sorted(run.latency_ms for run in runs)
    return LatencySummary(p50_ms=_percentile(values, 0.50), p95_ms=_percentile(values, 0.95))


def _tokens(runs: Iterable[JudgeRunResult]) -> TokenTotals:
    prompt = 0
    completion = 0
    for run in runs:
        prompt += run.tokens.prompt_tokens
        completion += run.tokens.completion_tokens
    return TokenTotals(prompt_tokens=prompt, completion_tokens=completion)


def run_itinerary_evaluation(
    kb: KnowledgeBase,
    judge: JudgeClient,
    *,
    runs_per_case: int = 3,
) -> EvaluationSummary:
    anchors = load_anchor_itineraries()
    anchor_runs = [
        _run_case(anchor.case_id, anchor.trip_spec, anchor.itinerary, kb, judge, 0)
        for anchor in anchors
    ]
    anchor_result = _anchor_result(anchors, anchor_runs)

    aggregates: list[ItineraryAggregate] = []
    for case in load_golden_itineraries():
        case_runs = [
            _run_case(case.case_id, case.trip_spec, case.itinerary, kb, judge, run_index)
            for run_index in range(runs_per_case)
        ]
        aggregates.append(_aggregate(case.case_id, case_runs))

    all_runs = [*anchor_runs, *[run for aggregate in aggregates for run in aggregate.runs]]
    dimension_means = _summary_means(aggregates)
    gate = _gate(anchor_result, aggregates)
    return EvaluationSummary(
        anchor_result=anchor_result,
        golden_aggregates=aggregates,
        overall_mean=sum(aggregate.overall_mean for aggregate in aggregates) / len(aggregates),
        dimension_means=dimension_means,
        latency=_latency(all_runs),
        tokens=_tokens(all_runs),
        gate=gate,
        runs_per_case=runs_per_case,
    )


def assert_gate_m3(summary: EvaluationSummary) -> None:
    if not summary.gate.passed:
        raise GateM3Error("; ".join(summary.gate.failures))
