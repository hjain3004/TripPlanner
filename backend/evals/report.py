from __future__ import annotations

from pathlib import Path

from core.db import DB_PATH, SEEDS_DIR, load_kb, seed_database
from evals.itinerary_eval import EvaluationSummary, assert_gate_m3, run_itinerary_evaluation
from evals.judge import JudgeScores, JudgeVerdict, ScriptedJudgeClient

REPORT_PATH = Path(__file__).with_name("report.md")
RUN_DATE = "2026-07-25"


def _verdict(
    *,
    groundedness: int = 5,
    interest_match: int = 4,
    geographic_coherence: int = 4,
    pacing: int = 4,
    budget_respect: int = 4,
    rationale: str = "offline scripted judge fixture",
) -> JudgeVerdict:
    return JudgeVerdict(
        scores=JudgeScores(
            groundedness=groundedness,
            interest_match=interest_match,
            geographic_coherence=geographic_coherence,
            pacing=pacing,
            budget_respect=budget_respect,
        ),
        rationale=rationale,
    )


def default_offline_judge() -> ScriptedJudgeClient:
    anchors = [
        _verdict(interest_match=5, geographic_coherence=5, pacing=5, budget_respect=5),
        _verdict(interest_match=4, geographic_coherence=3, pacing=4, budget_respect=4),
        _verdict(interest_match=4, geographic_coherence=4, pacing=3, budget_respect=4),
    ]
    goldens = [_verdict() for _ in range(8 * 3)]
    return ScriptedJudgeClient({"quality": [*anchors, *goldens]})


def render_markdown_report(summary: EvaluationSummary) -> str:
    status = "PASS" if summary.gate.passed else "FAIL"
    dimension_rows = "\n".join(
        f"| {dimension} | {mean:.2f} |" for dimension, mean in summary.dimension_means.items()
    )
    failures = "\n".join(f"- {failure}" for failure in summary.gate.failures) or "- None"
    anchor_order = " > ".join(
        anchor.case_id for anchor in summary.anchor_result.ranked_anchors
    )
    return f"""# TripPlanner M3 Evaluation Report

Generated: {RUN_DATE}

Gate M3: {status}

## Summary

- Anchor ordering: {anchor_order}
- Golden itineraries: {len(summary.golden_aggregates)}
- Judge runs per golden itinerary: {summary.runs_per_case}
- Overall mean: {summary.overall_mean:.2f}
- Latency: p50 {summary.latency.p50_ms} ms, p95 {summary.latency.p95_ms} ms
- Prompt tokens: {summary.tokens.prompt_tokens}
- Completion tokens: {summary.tokens.completion_tokens}
- Total tokens: {summary.tokens.total_tokens}

## Dimension means

| Dimension | Mean |
|---|---:|
{dimension_rows}

## Gate failures

{failures}

## Limitations

- Uses an offline scripted judge by default; optional live judging is disabled without explicit credentials.
- Makes no live provider calls and does not connect provider MCP servers.
- Evaluation code remains outside the product runtime; there is no runtime evaluator in `POST /plan`.
"""


def write_report(summary: EvaluationSummary, path: Path = REPORT_PATH) -> Path:
    path.write_text(render_markdown_report(summary))
    return path


def main() -> int:
    if not DB_PATH.exists():
        seed_database(SEEDS_DIR, DB_PATH)
    summary = run_itinerary_evaluation(load_kb(DB_PATH), default_offline_judge())
    assert_gate_m3(summary)
    path = write_report(summary)
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
