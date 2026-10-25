"""Deterministic post-plan execution (CP4).

Hosts the pieces that turn an approved action into a new report. This module has no
model, provider, or network dependency: every number comes from the frozen kernel run
over the report's own final cost lines.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from agents.confirmed_trip import build_inventory_requests, compile_confirmed_input
from agents.estimator import per_diem_lines, poi_lines
from agents.explainer import _template_explainer, build_final_report
from agents.gateway_estimator import estimate_confirmed_inventory
from agents.kernel import run_kernel
from agents.models import (
    DraftItinerary,
    EstimatorResult,
    FinalReport,
    SectionFreshness,
    SectionState,
)
from agents.retrieval import retrieve_candidates
from core.db import KnowledgeBase
from core.itinerary.compose import build_final_schedule, fallback_itinerary
from core.itinerary.edits import apply_edit
from core.models import CostedTrip, OptimizationPrefs, SpendCategory, SpendLineItem
from core.travel_taxonomy import TravelCategory, canonical_travel_category
from core.trip_models import ItineraryEdit, TripSpec
from gateway.travel.product import TravelInventorySnapshot, TravelInventorySummary
from gateway.travel.service import TravelInventoryService
from planning.contracts import ConfirmedBriefSnapshot, TripBrief
from planning.post_plan import ProviderInvalidatingChange, ScopedItineraryReplan

_ADMITTED_CATEGORIES = (SpendCategory.FLIGHTS, SpendCategory.HOTELS)


@dataclass(frozen=True)
class PostPlanExecutionResult:
    report: FinalReport
    brief: TripBrief
    inventory_snapshot: TravelInventorySnapshot | None = None


def spec_for_brief(base: TripSpec, brief: TripBrief) -> TripSpec:
    """Project a confirmed brief onto the existing kernel request shape."""
    essentials = brief.trip_essentials
    budget = brief.budget_and_objective
    rhythm = brief.daily_rhythm
    objective_map = {
        "lowest_cash": "min_cash_outlay",
        "highest_value": "max_savings",
        "balanced": "max_savings",
        "convenience": "simplicity",
    }
    return base.model_copy(
        update={
            "home_country": brief.home.home_country,
            "origin_city": essentials.origin,
            "destination_city": essentials.destination,
            "start_date": essentials.start_date,
            "end_date": essentials.end_date,
            "travelers": essentials.travelers,
            "budget_minor": budget.budget_minor if budget else None,
            "budget_currency": budget.currency if budget else brief.home.home_currency,
            "style": budget.travel_style if budget else "balanced",
            "interests": (
                brief.experiences_and_food.interests
                if brief.experiences_and_food
                else []
            ),
            "pace": rhythm.pace if rhythm else "moderate",
            "dietary": (
                brief.hard_constraints.dietary if brief.hard_constraints.has_constraints else []
            ),
            "wallet": brief.wallet,
            "optimization": OptimizationPrefs(objective=objective_map[budget.objective])
            if budget
            else base.optimization,
        }
    )


def _report_from_estimate(
    report: FinalReport,
    *,
    spec: TripSpec,
    itinerary: DraftItinerary,
    estimate: EstimatorResult,
    kb: KnowledgeBase,
    now: datetime,
    inventory: TravelInventorySummary | None = None,
) -> FinalReport:
    del now
    retrieval = retrieve_candidates(spec, kb)
    kernel = run_kernel(spec, estimate, kb, booking_date=report.costed_trip.booking_date)
    rebuilt = build_final_report(
        spec,
        itinerary,
        estimate,
        kernel,
        retrieval,
        critic_caveats=list(report.caveats),
        explainer=_template_explainer(kernel),
        trace_id=report.trace_id,
        region_capability=report.region_capability,
        freshness=report.freshness,
    )
    return rebuilt.model_copy(update={"travel_inventory": inventory})


def replan_scoped_itinerary(
    report: FinalReport,
    action: ScopedItineraryReplan,
    *,
    brief: TripBrief,
    kb: KnowledgeBase,
    now: datetime,
) -> PostPlanExecutionResult:
    """Build a local deterministic candidate and splice only approved dates."""
    spec = spec_for_brief(report.trip_spec, brief)
    retrieval = retrieve_candidates(spec, kb)
    candidate_spec = spec
    if action.day_theme:
        theme_interests = [
            token
            for token in action.day_theme.split()
            if canonical_travel_category(token) != TravelCategory.OTHER
        ]
        if theme_interests:
            candidate_spec = spec.model_copy(update={"interests": theme_interests})
            retrieval = retrieve_candidates(candidate_spec, kb)
    candidate = fallback_itinerary(candidate_spec, retrieval)
    affected = set(action.affected_dates)
    candidate_by_date = {day.date: day for day in candidate.days}
    days = [
        candidate_by_date.get(day.date, day) if day.date in affected else day
        for day in report.itinerary.days
    ]
    itinerary = report.itinerary.model_copy(update={"days": days})
    rebuilt = recompute_confirmed_report(
        report, itinerary=itinerary, spec=spec, kb=kb, now=now
    )
    return PostPlanExecutionResult(report=rebuilt, brief=brief)


def refresh_provider_inventory(
    report: FinalReport,
    action: ProviderInvalidatingChange,
    *,
    brief: TripBrief,
    retained_snapshot: TravelInventorySnapshot | None,
    kb: KnowledgeBase,
    now: datetime,
    inventory_service: TravelInventoryService,
    requested_domains: set[str],
) -> PostPlanExecutionResult:
    """Refresh only server-derived invalidated domains through the sample gateway."""
    del action
    spec = spec_for_brief(report.trip_spec, brief)
    itinerary = report.itinerary
    expected_dates = [spec.start_date + timedelta(days=offset) for offset in range(spec.nights)]
    if [day.date for day in itinerary.days] != expected_dates:
        itinerary = fallback_itinerary(spec, retrieve_candidates(spec, kb))
    confirmed = ConfirmedBriefSnapshot(revision=1, brief=brief, confirmed_at=now)
    flight_request, hotel_request = build_inventory_requests(
        compile_confirmed_input(confirmed), itinerary
    )
    # The route supplies a sample-only TravelInventoryService. The object protocol
    # keeps this module independent from API construction and makes raising test
    # transports straightforward.
    requested = set(requested_domains)
    if not requested <= {"flight", "hotel"} or not requested:
        raise ValueError("provider invalidation must name at least one inventory domain")
    if retained_snapshot is not None:
        if "flight" not in requested and flight_request != retained_snapshot.flight_request:
            raise ValueError("retained flight evidence does not match the confirmed request")
        if "hotel" not in requested and hotel_request != retained_snapshot.hotel_request:
            raise ValueError("retained hotel evidence does not match the confirmed request")
        if not retained_snapshot.is_current(now) and requested != {"flight", "hotel"}:
            raise ValueError("retained inventory evidence has expired")
        if flight_request == retained_snapshot.flight_request and "flight" not in requested:
            requested.discard("flight")
        if hotel_request == retained_snapshot.hotel_request and "hotel" not in requested:
            requested.discard("hotel")
    fresh = asyncio.run(inventory_service.search(flight_request, hotel_request, domains=requested))
    if retained_snapshot is not None:
        fresh = fresh.model_copy(
            update={
                "flights": fresh.flights if "flight" in requested else retained_snapshot.flights,
                "hotels": fresh.hotels if "hotel" in requested else retained_snapshot.hotels,
                "flight_scopes": fresh.flight_scopes
                if "flight" in requested
                else retained_snapshot.flight_scopes,
                "hotel_scopes": fresh.hotel_scopes
                if "hotel" in requested
                else retained_snapshot.hotel_scopes,
            }
        )
    fresh = fresh.model_copy(
        update={
            "inventory_revision": (
                retained_snapshot.inventory_revision + 1 if retained_snapshot else 1
            )
        }
    )
    estimate_result = estimate_confirmed_inventory(
        spec, itinerary, kb, fresh, booking_date=report.costed_trip.booking_date
    )
    rebuilt = _report_from_estimate(
        report,
        spec=spec,
        itinerary=itinerary,
        estimate=estimate_result.estimate,
        kb=kb,
        now=now,
        inventory=estimate_result.summary,
    )
    return PostPlanExecutionResult(report=rebuilt, brief=brief, inventory_snapshot=fresh)


def _without(items: list[str], remove: list[str]) -> list[str]:
    """``items`` minus one occurrence per entry of ``remove`` (order preserved)."""
    pending = Counter(remove)
    kept: list[str] = []
    for item in items:
        if pending[item] > 0:
            pending[item] -= 1
        else:
            kept.append(item)
    return kept


def recompute_confirmed_report(
    report: FinalReport,
    *,
    itinerary: DraftItinerary,
    spec: TripSpec,
    kb: KnowledgeBase,
    now: datetime,
) -> FinalReport:
    """Rebuild a confirmed report for an edited itinerary from its admitted evidence.

    The admitted flight and hotel cost lines are carried over byte for byte (their ids,
    amounts, scopes and channels were fixed when the evidence was admitted). Activity and
    per-diem lines are rebuilt for the edited itinerary. The kernel then runs **once, on
    that final costed trip**, and every total, payment allocation and transfer
    recommendation is assembled from its result. Nothing is replaced after assembly.

    ``now`` is accepted so callers pass one injected clock through the whole action;
    evidence-expiry decisions are made by the service layer before this function runs,
    because a report cannot be rebuilt "fresher" than its evidence by copying it.
    """
    del now  # this function never reads a clock
    retrieval = retrieve_candidates(spec, kb)
    scheduled = build_final_schedule(itinerary, spec, retrieval)

    admitted: list[SpendLineItem] = [
        line for line in report.costed_trip.lines if line.category in _ADMITTED_CATEGORIES
    ]
    activity_lines, activity_assumptions = poi_lines(spec, scheduled.itinerary, kb)
    per_diem, per_diem_assumptions = per_diem_lines(spec, kb)
    costed_trip = CostedTrip(
        id=f"{spec.origin_city}-{spec.destination_city}-{spec.start_date.isoformat()}",
        origin=spec.origin_city,
        destination=spec.destination_city,
        home_currency=report.costed_trip.home_currency,
        booking_date=report.costed_trip.booking_date,
        trip_start_date=spec.start_date,
        lines=[*admitted, *activity_lines, *per_diem],
    )

    # Assumptions: keep the evidence-derived ones the report already carried and replace
    # only those this module regenerates (activity and per-diem) for the edited itinerary.
    previous_estimate_assumptions = _without(
        report.assumptions, report.optimizer_result.assumptions
    )
    previous_dynamic = [
        *poi_lines(report.trip_spec, report.itinerary, kb)[1],
        *per_diem_lines(report.trip_spec, kb)[1],
    ]
    estimate = EstimatorResult(
        costed_trip=costed_trip,
        flight=report.flights_pick,
        hotel=report.hotel_pick,
        assumptions=[
            *_without(previous_estimate_assumptions, previous_dynamic),
            *activity_assumptions,
            *per_diem_assumptions,
        ],
    )
    kernel = run_kernel(spec, estimate, kb, booking_date=report.costed_trip.booking_date)

    # Caveats: drop the schedule warnings the previous itinerary produced, keep everything
    # else (planner/critic notes), and add the edited itinerary's own warnings.
    previous_warnings = [
        w.message
        for w in build_final_schedule(
            report.itinerary, report.trip_spec, retrieve_candidates(report.trip_spec, kb)
        ).warnings
    ]
    caveats = [
        *_without(report.caveats, previous_warnings),
        *(w.message for w in scheduled.warnings),
    ]
    freshness = SectionFreshness(
        budget=SectionState.RECOMPUTED,
        payment_strategy=SectionState.RECOMPUTED,
        itinerary=SectionState.RECOMPUTED,
        prose=SectionState.STALE,
        critic_verdict=SectionState.STALE,
        edit_count=report.freshness.edit_count + 1,
    )
    rebuilt = build_final_report(
        spec,
        scheduled.itinerary,
        estimate,
        kernel,
        retrieval,
        critic_caveats=caveats,
        explainer=_template_explainer(kernel),
        trace_id=report.trace_id,
        region_capability=report.region_capability,
        freshness=freshness,
    )
    inventory = report.travel_inventory
    if inventory is not None:
        # The report's edit counter, independent of evidence generation and expiry.
        inventory = inventory.model_copy(
            update={"inventory_revision": inventory.inventory_revision + 1}
        )
    return rebuilt.model_copy(update={"travel_inventory": inventory})


def recompute_confirmed_edit(
    report: FinalReport,
    edit: ItineraryEdit,
    *,
    kb: KnowledgeBase,
    now: datetime,
) -> FinalReport:
    """Apply one typed itinerary edit to a confirmed report and recompute it."""
    retrieval = retrieve_candidates(report.trip_spec, kb)
    edited = apply_edit(
        report.itinerary,
        edit,
        candidate_pois=retrieval.pois,
        poi_evidence=retrieval.poi_provenance,
    )
    return recompute_confirmed_report(
        report, itinerary=edited, spec=report.trip_spec, kb=kb, now=now
    )
