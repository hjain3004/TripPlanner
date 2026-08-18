from __future__ import annotations

from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from agents.config import load_agent_config
from agents.critic import run_critic
from agents.estimator import estimate_costed_trip
from agents.explainer import run_explainer
from agents.intake import run_intake
from agents.kernel import run_kernel
from agents.llm import LLMClient
from agents.models import PipelineStatus, PlanResponse, RegionCapability
from agents.planner import run_planner
from agents.retrieval import retrieve_candidates
from agents.trace import TraceRecorder
from core.db import KnowledgeBase
from gateway.catalog.activate import active_catalog_summary
from gateway.catalog.regions import get_region

MAX_CRITIC_REPLAN_LOOPS = load_agent_config().llm["critic"].max_replan_loops or 2


def build_region_capability(destination_iata: str, catalog_root: Path) -> RegionCapability | None:
    """Honest, request-time capability report for a destination.

    Reads the small activation summary sidecar rather than the full catalog
    (which can run tens of megabytes) just to learn a place count.
    """
    region = get_region(destination_iata)
    if region is None:
        return None

    summary = active_catalog_summary(catalog_root, catalog_id=region.catalog_id)

    if summary is not None:
        catalog_status = "active"
        place_count = summary.place_count
    elif (catalog_root / f".provisioning_{region.catalog_id}").exists():
        catalog_status = "provisioning"
        place_count = 0
    else:
        catalog_status = "absent"
        place_count = 0

    gaps: list[str] = []
    if not region.budget_supported:
        gaps.append(f"No FX rates or per-diem data for {region.currency}")

    return RegionCapability(
        region=region.iata,
        catalog_status=catalog_status,
        place_count=place_count,
        budget_supported=region.budget_supported,
        known_gaps=gaps,
    )


def run_pipeline(
    raw_request: str,
    kb: KnowledgeBase,
    llm: LLMClient,
    registry: Any = None,
    *,
    booking_date: date,
    trace_dir: Path | None = None,
    on_stage: Callable[[int, str], None] | None = None,
) -> PlanResponse:
    trace_id = uuid4().hex
    trace = TraceRecorder(trace_id, trace_dir)

    if on_stage is not None:
        on_stage(1, "intake")
    intake = run_intake(raw_request, kb, llm)
    trace.record("intake", intake, model="llm:intake")
    if intake.runtime_error is not None:
        return PlanResponse(
            status=PipelineStatus.ERROR,
            trace_id=trace_id,
            error=intake.runtime_error,
        )
    if intake.needs_clarification or intake.trip_spec is None:
        return PlanResponse(
            status=PipelineStatus.NEEDS_CLARIFICATION,
            trace_id=trace_id,
            unresolved=intake.unresolved,
        )

    spec = intake.trip_spec

    region_cap = build_region_capability(spec.destination_city, Path("catalogs"))

    retrieval = retrieve_candidates(spec, kb)
    trace.record("retrieval", retrieval)

    if on_stage is not None:
        on_stage(2, "itinerary")
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

    if on_stage is not None:
        on_stage(3, "costing")
    estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=booking_date)
    trace.record("estimator", estimate)
    if on_stage is not None:
        on_stage(4, "optimizing")
    kernel = run_kernel(spec, estimate, kb, booking_date=booking_date)
    trace.record("optimizer", kernel)

    critic_caveats: list[str] = []
    for loop_index in range(MAX_CRITIC_REPLAN_LOOPS):
        if on_stage is not None:
            on_stage(5, "critic")
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

    if on_stage is not None:
        on_stage(6, "explaining")
    report = run_explainer(
        spec,
        itinerary,
        estimate,
        kernel,
        retrieval,
        critic_caveats=[*planner_caveats, *critic_caveats],
        trace_id=trace_id,
        llm=llm,
        region_capability=region_cap,
    )
    trace.record("explainer", report, model="llm:explainer")
    return PlanResponse(status=PipelineStatus.OK, trace_id=trace_id, report=report)
