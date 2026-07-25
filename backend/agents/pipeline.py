from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

from agents.critic import run_critic
from agents.estimator import estimate_costed_trip
from agents.explainer import run_explainer
from agents.intake import run_intake
from agents.kernel import run_kernel
from agents.llm import LLMClient
from agents.models import PipelineStatus, PlanResponse
from agents.planner import run_planner
from agents.retrieval import retrieve_candidates
from agents.trace import TraceRecorder
from core.db import KnowledgeBase

MAX_CRITIC_REPLAN_LOOPS = 2


def run_pipeline(
    raw_request: str,
    kb: KnowledgeBase,
    llm: LLMClient,
    *,
    booking_date: date,
    trace_dir: Path | None = None,
) -> PlanResponse:
    trace_id = uuid4().hex
    trace = TraceRecorder(trace_id, trace_dir)

    intake = run_intake(raw_request, kb, llm)
    trace.record("intake", intake, model="llm:intake")
    if intake.needs_clarification or intake.trip_spec is None:
        return PlanResponse(
            status=PipelineStatus.NEEDS_CLARIFICATION,
            trace_id=trace_id,
            unresolved=intake.unresolved,
        )

    spec = intake.trip_spec
    retrieval = retrieve_candidates(spec, kb)
    trace.record("retrieval", retrieval)

    planner = run_planner(spec, retrieval, llm)
    trace.record(
        "planner",
        planner,
        model="llm:planner",
        attributes={
            "used_fallback": planner.used_fallback,
            "repair_attempted": planner.repair_attempted,
        },
    )
    itinerary = planner.itinerary
    planner_caveats = list(planner.caveats)

    estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=booking_date)
    trace.record("estimator", estimate)
    kernel = run_kernel(spec, estimate, kb, booking_date=booking_date)
    trace.record("optimizer", kernel)

    critic_caveats: list[str] = []
    for loop_index in range(MAX_CRITIC_REPLAN_LOOPS):
        critic = run_critic(spec, itinerary, estimate, kb, llm)
        trace.record(
            "critic",
            critic,
            model="llm:critic",
            attributes={"loop_index": loop_index},
        )
        critic_caveats.extend(critic.caveats)
        blocking = critic.verdict.blocking_issues
        if not blocking:
            break
        if loop_index == MAX_CRITIC_REPLAN_LOOPS - 1:
            critic_caveats.extend(issue.message for issue in blocking)
            break

        planner = run_planner(
            spec,
            retrieval,
            llm,
            revision_notes=[issue.message for issue in blocking],
        )
        trace.record(
            "planner",
            planner,
            model="llm:planner",
            attributes={
                "used_fallback": planner.used_fallback,
                "repair_attempted": planner.repair_attempted,
                "revision_count": loop_index + 1,
            },
        )
        itinerary = planner.itinerary
        planner_caveats.extend(planner.caveats)
        estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=booking_date)
        trace.record("estimator", estimate, attributes={"revision_count": loop_index + 1})
        kernel = run_kernel(spec, estimate, kb, booking_date=booking_date)
        trace.record("optimizer", kernel, attributes={"revision_count": loop_index + 1})

    report = run_explainer(
        spec,
        itinerary,
        estimate,
        kernel,
        critic_caveats=[*planner_caveats, *critic_caveats],
        trace_id=trace_id,
        llm=llm,
    )
    trace.record("explainer", report, model="llm:explainer")
    return PlanResponse(status=PipelineStatus.OK, trace_id=trace_id, report=report)
