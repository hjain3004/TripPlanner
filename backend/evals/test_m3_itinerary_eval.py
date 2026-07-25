from __future__ import annotations

from datetime import date

import pytest

from core.db import SEEDS_DIR, load_kb, seed_database
from evals.itinerary_eval import GateM3Error, assert_gate_m3, run_itinerary_evaluation
from evals.itinerary_fixtures import load_anchor_itineraries, load_golden_itineraries
from evals.judge import JudgeScores, JudgeVerdict, ScriptedJudgeClient


def _kb(tmp_path):
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _verdict(
    *,
    groundedness: int = 5,
    interest_match: int = 4,
    geographic_coherence: int = 4,
    pacing: int = 4,
    budget_respect: int = 4,
    rationale: str = "scripted",
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


def _scripted_good_judge() -> ScriptedJudgeClient:
    anchors = [
        _verdict(interest_match=5, geographic_coherence=5, pacing=5, budget_respect=5),
        _verdict(interest_match=4, geographic_coherence=3, pacing=4, budget_respect=4),
        _verdict(interest_match=4, geographic_coherence=4, pacing=3, budget_respect=4),
    ]
    goldens = [_verdict() for _ in range(8 * 3)]
    return ScriptedJudgeClient({"quality": [*anchors, *goldens]})


def test_three_anchor_itineraries_are_ranked_correctly(tmp_path) -> None:
    summary = run_itinerary_evaluation(_kb(tmp_path), _scripted_good_judge())

    assert [anchor.case_id for anchor in summary.anchor_result.ranked_anchors] == [
        "anchor_good",
        "anchor_scattered",
        "anchor_overpacked",
    ]
    assert summary.anchor_result.passed is True


def test_eight_golden_itineraries_run_three_times_each(tmp_path) -> None:
    summary = run_itinerary_evaluation(_kb(tmp_path), _scripted_good_judge())

    assert len(load_golden_itineraries()) == 8
    assert len(summary.golden_aggregates) == 8
    assert all(aggregate.run_count == 3 for aggregate in summary.golden_aggregates)
    assert _scripted_good_judge().invocations == {}


def test_golden_gate_requires_mean_at_least_four_min_dimension_three_and_groundedness_five(
    tmp_path,
) -> None:
    summary = run_itinerary_evaluation(_kb(tmp_path), _scripted_good_judge())

    assert summary.gate.passed is True
    assert summary.overall_mean >= 4.0
    assert all(aggregate.dimension_means["groundedness"] == 5.0 for aggregate in summary.golden_aggregates)
    assert_gate_m3(summary)


def test_latency_percentiles_and_token_totals_are_recorded(tmp_path) -> None:
    summary = run_itinerary_evaluation(_kb(tmp_path), _scripted_good_judge())

    assert summary.latency.p50_ms >= 0
    assert summary.latency.p95_ms >= summary.latency.p50_ms
    assert summary.tokens.prompt_tokens > 0
    assert summary.tokens.completion_tokens > 0
    assert summary.tokens.total_tokens == summary.tokens.prompt_tokens + summary.tokens.completion_tokens


def test_gate_failure_lists_case_and_dimension(tmp_path) -> None:
    judge = ScriptedJudgeClient(
        {
            "quality": [
                _verdict(interest_match=5, geographic_coherence=5, pacing=5, budget_respect=5),
                _verdict(interest_match=4, geographic_coherence=3, pacing=4, budget_respect=4),
                _verdict(interest_match=4, geographic_coherence=4, pacing=3, budget_respect=4),
                *[_verdict(groundedness=4) for _ in range(8 * 3)],
            ]
        }
    )

    summary = run_itinerary_evaluation(_kb(tmp_path), judge)

    assert summary.gate.passed is False
    assert any("groundedness" in failure for failure in summary.gate.failures)
    assert any("golden_" in failure for failure in summary.gate.failures)
    with pytest.raises(GateM3Error):
        assert_gate_m3(summary)


def test_anchor_and_golden_fixture_counts() -> None:
    assert [anchor.case_id for anchor in load_anchor_itineraries()] == [
        "anchor_good",
        "anchor_scattered",
        "anchor_overpacked",
    ]
    assert len(load_golden_itineraries()) == 8
