from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

from agents.estimator import estimate_costed_trip
from agents.explainer import _template_explainer, build_final_report, run_explainer
from agents.kernel import run_kernel
from agents.llm import LLMClient
from agents.models import FinalReport, KernelResult, SectionFreshness, SectionState
from agents.pipeline import build_region_capability
from agents.retrieval import retrieve_candidates
from core.db import KnowledgeBase
from core.itinerary.compose import build_final_schedule
from core.itinerary.edits import apply_edit
from core.trip_models import DraftItinerary, ItineraryEdit, TripSpec


def recompute_itinerary(
    spec: TripSpec,
    itinerary: DraftItinerary,
    edit: ItineraryEdit,
    kb: KnowledgeBase,
    *,
    booking_date: date,
    trace_id: str | None = None,
    previous_freshness: SectionFreshness | None = None,
) -> FinalReport:
    """Deterministically recomputes cost, card/offer allocation, and validation warnings

    after a user itinerary edit without making any LLM calls.
    """
    retrieval = retrieve_candidates(spec, kb)
    edited_draft = apply_edit(
        itinerary,
        edit,
        candidate_pois=retrieval.pois,
        poi_evidence=retrieval.poi_provenance,
    )
    scheduled = build_final_schedule(edited_draft, spec, retrieval)

    estimate = estimate_costed_trip(
        spec, scheduled.itinerary, kb, booking_date=booking_date
    )
    kernel = run_kernel(spec, estimate, kb, booking_date=booking_date)

    region_cap = build_region_capability(spec.destination_city, Path("catalogs"))

    caveats = [w.message for w in scheduled.warnings]
    explainer = _template_explainer(kernel)

    prev_count = previous_freshness.edit_count if previous_freshness else 0
    freshness = SectionFreshness(
        budget=SectionState.RECOMPUTED,
        payment_strategy=SectionState.RECOMPUTED,
        itinerary=SectionState.RECOMPUTED,
        prose=SectionState.STALE,
        critic_verdict=SectionState.STALE,
        edit_count=prev_count + 1,
    )

    return build_final_report(
        spec,
        scheduled.itinerary,
        estimate,
        kernel,
        retrieval,
        critic_caveats=caveats,
        explainer=explainer,
        trace_id=trace_id or uuid4().hex,
        region_capability=region_cap,
        freshness=freshness,
    )


def refresh_prose(
    spec: TripSpec,
    itinerary: DraftItinerary,
    kernel_result: KernelResult,
    kb: KnowledgeBase,
    llm: LLMClient,
    *,
    booking_date: date,
    trace_id: str | None = None,
    previous_freshness: SectionFreshness | None = None,
) -> FinalReport:
    """Refreshes prose by running only the explainer LLM call site."""
    retrieval = retrieve_candidates(spec, kb)
    estimate = estimate_costed_trip(spec, itinerary, kb, booking_date=booking_date)
    region_cap = build_region_capability(spec.destination_city, Path("catalogs"))

    prev = previous_freshness or SectionFreshness()
    freshness = SectionFreshness(
        budget=prev.budget,
        payment_strategy=prev.payment_strategy,
        itinerary=prev.itinerary,
        prose=SectionState.FRESH,
        critic_verdict=prev.critic_verdict,
        edit_count=prev.edit_count,
    )

    return run_explainer(
        spec,
        itinerary,
        estimate,
        kernel_result,
        retrieval,
        critic_caveats=[],
        trace_id=trace_id or uuid4().hex,
        llm=llm,
        region_capability=region_cap,
        freshness=freshness,
    )
