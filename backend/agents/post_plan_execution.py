"""Deterministic post-plan execution (CP4).

Hosts the pieces that turn an approved action into a new report. This module has no
model, provider, or network dependency: every number comes from the frozen kernel run
over the report's own final cost lines.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from agents.estimator import per_diem_lines, poi_lines
from agents.explainer import _template_explainer, build_final_report
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
from core.itinerary.compose import build_final_schedule
from core.itinerary.edits import apply_edit
from core.models import CostedTrip, SpendCategory, SpendLineItem
from core.trip_models import ItineraryEdit, TripSpec

_ADMITTED_CATEGORIES = (SpendCategory.FLIGHTS, SpendCategory.HOTELS)


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
