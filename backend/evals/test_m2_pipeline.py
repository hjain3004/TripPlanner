from __future__ import annotations

import json
from datetime import date

from agents.llm import ScriptedLLMClient
from agents.models import (
    CriticIssue,
    CriticVerdict,
    DraftItinerary,
    ExplainerOutput,
    ItineraryDay,
    ItineraryItem,
    PipelineStatus,
    TripSpec,
)
from agents.pipeline import run_pipeline
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet


def _kb(tmp_path):
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _spec(unresolved: list[str] | None = None) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature", "food"],
        wallet=UserWallet(
            card_ids=["hdfc-infinia", "axis-atlas"],
            points_balances={"voyager-prime": 140000},
        ),
        unresolved=unresolved or [],
    )


def _itinerary(*, extra_note: str = "initial") -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1),
                items=[
                    ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                    ItineraryItem(poi_id="sg-hawker-maxwell"),
                ],
            ),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
            ItineraryDay(date=date(2026, 8, 4), items=[]),
        ],
        notes=[extra_note],
    )


def test_pipeline_runs_fixed_graph_and_writes_trace(tmp_path) -> None:
    llm = ScriptedLLMClient(
        {
            "intake": [_spec()],
            "planner": [_itinerary()],
            "critic": [CriticVerdict(passed=True)],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded summary.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ],
        }
    )

    response = run_pipeline(
        "Delhi to Singapore Aug 1-5",
        _kb(tmp_path),
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )

    assert response.status == PipelineStatus.OK
    assert response.report is not None
    assert response.report.trace_id == response.trace_id
    assert llm.invocations == {"intake": 1, "planner": 1, "critic": 1, "explainer": 1}

    trace_file = tmp_path / f"{response.trace_id}.json"
    events = json.loads(trace_file.read_text())
    assert [event["name"] for event in events] == [
        "intake",
        "discovery",
        "retrieval",
        "planner",
        "estimator",
        "optimizer",
        "critic",
        "explainer",
    ]
    assert all(event["artifact_hash"] for event in events)


def test_pipeline_returns_clarification_without_downstream_calls(tmp_path) -> None:
    llm = ScriptedLLMClient({"intake": [_spec(["Need exact dates."])]})

    response = run_pipeline(
        "Singapore sometime",
        _kb(tmp_path),
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )

    assert response.status == PipelineStatus.NEEDS_CLARIFICATION
    assert response.unresolved == ["Need exact dates."]
    assert response.report is None
    assert llm.invocations == {"intake": 1}


def test_pipeline_fails_soft_when_intake_llm_errors(tmp_path) -> None:
    llm = ScriptedLLMClient({"intake": [RuntimeError("intake down")]})

    response = run_pipeline(
        "Singapore sometime",
        _kb(tmp_path),
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )

    assert response.status == PipelineStatus.NEEDS_CLARIFICATION
    assert response.report is None
    assert response.unresolved[0].startswith("intake failed:")


def test_pipeline_uses_planner_fallback_when_planner_llm_errors(tmp_path) -> None:
    llm = ScriptedLLMClient(
        {
            "intake": [_spec()],
            "planner": [RuntimeError("planner down")],
            "critic": [CriticVerdict(passed=True)],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded summary.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ],
        }
    )

    response = run_pipeline(
        "Delhi to Singapore Aug 1-5",
        _kb(tmp_path),
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )

    assert response.status == PipelineStatus.OK
    assert response.report is not None
    assert response.report.itinerary.itinerary_quality == "fallback"
    assert any("planner fallback" in caveat.casefold() for caveat in response.report.caveats)


def test_pipeline_skips_critic_failure_and_falls_back_for_explainer_failure(tmp_path) -> None:
    llm = ScriptedLLMClient(
        {
            "intake": [_spec()],
            "planner": [_itinerary()],
            "critic": [RuntimeError("critic down")],
            "explainer": [RuntimeError("explainer down")],
        }
    )

    response = run_pipeline(
        "Delhi to Singapore Aug 1-5",
        _kb(tmp_path),
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )

    assert response.status == PipelineStatus.OK
    assert response.report is not None
    assert any("critic unavailable" in caveat.casefold() for caveat in response.report.caveats)
    assert any("explainer unavailable" in caveat.casefold() for caveat in response.report.caveats)


def test_pipeline_replans_once_for_blocking_critic_issue(tmp_path) -> None:
    llm = ScriptedLLMClient(
        {
            "intake": [_spec()],
            "planner": [_itinerary(extra_note="first"), _itinerary(extra_note="revised")],
            "critic": [
                CriticVerdict(
                    passed=False,
                    issues=[
                        CriticIssue(
                            severity="blocking",
                            kind="pace",
                            message="Too packed for the selected pace.",
                        )
                    ],
                ),
                CriticVerdict(passed=True),
            ],
            "explainer": [
                ExplainerOutput(
                    summary="Grounded summary.",
                    itinerary_overview="Grounded itinerary.",
                    payment_overview="Grounded payments.",
                )
            ],
        }
    )

    response = run_pipeline(
        "Delhi to Singapore Aug 1-5",
        _kb(tmp_path),
        llm,
        booking_date=date(2026, 7, 25),
        trace_dir=tmp_path,
    )

    assert response.status == PipelineStatus.OK
    assert response.report is not None
    assert response.report.itinerary.notes == ["revised"]
    assert llm.invocations["planner"] == 2
    assert llm.invocations["critic"] == 2
