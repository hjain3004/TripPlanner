from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

from agents.estimator import estimate_costed_trip
from agents.explainer import _template_explainer, build_final_report
from agents.kernel import run_kernel
from agents.models import FinalReport
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
) -> FinalReport:
    """Deterministically recomputes cost, card/offer allocation, and validation warnings

    after a user itinerary edit without making any LLM calls.
    """
    edited_draft = apply_edit(itinerary, edit)
    retrieval = retrieve_candidates(spec, kb)
    scheduled = build_final_schedule(edited_draft, spec, retrieval)

    estimate = estimate_costed_trip(
        spec, scheduled.itinerary, kb, booking_date=booking_date
    )
    kernel = run_kernel(spec, estimate, kb, booking_date=booking_date)

    region_cap = build_region_capability(spec.destination_city, Path("catalogs"))

    caveats = [w.message for w in scheduled.warnings]
    explainer = _template_explainer(kernel)

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
    )
