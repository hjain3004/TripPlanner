from __future__ import annotations

from datetime import date, timedelta

from agents.llm import LLMCallError, LLMClient
from agents.models import (
    DraftItinerary,
    ItineraryDay,
    ItineraryItem,
    PlannerResult,
    RetrievalContext,
    TripSpec,
)

from core.itinerary.compose import fallback_itinerary

class PlannerValidationError(ValueError):
    pass


def _trip_dates(spec: TripSpec) -> set[date]:
    return {spec.start_date + timedelta(days=offset) for offset in range(spec.nights)}


def validate_itinerary(
    itinerary: DraftItinerary, spec: TripSpec, retrieval: RetrievalContext
) -> None:
    poi_ids = {poi.id for poi in retrieval.pois}
    area_ids = {area.id for area in retrieval.areas}
    if itinerary.hotel_area_id not in area_ids:
        raise PlannerValidationError(f"unknown hotel area: {itinerary.hotel_area_id}")
    valid_dates = _trip_dates(spec)
    for day in itinerary.days:
        if day.date not in valid_dates:
            raise PlannerValidationError(f"day outside trip dates: {day.date.isoformat()}")
        for item in day.items:
            if item.poi_id not in poi_ids:
                raise PlannerValidationError(f"unknown poi: {item.poi_id}")





def _call_planner(
    llm: LLMClient,
    *,
    system: str,
    user: str,
) -> DraftItinerary:
    return llm.complete_json(
        node="planner",
        system=system,
        user=user,
        schema=DraftItinerary,
        temperature=0.0,
    )


def run_planner(
    spec: TripSpec,
    retrieval: RetrievalContext,
    llm: LLMClient,
    revision_notes: list[str] | None = None,
) -> PlannerResult:
    system = (
        "Create DraftItinerary JSON using only listed poi_id and hotel_area_id values. "
        "Do not invent attractions."
    )
    user = (
        f"Trip: {spec.model_dump_json()}\n"
        f"POIs:\n{chr(10).join(retrieval.poi_rows)}\n"
        f"Areas:\n{chr(10).join(retrieval.area_rows)}\n"
        f"Revision notes: {revision_notes or []}"
    )
    try:
        itinerary = _call_planner(llm, system=system, user=user)
        try:
            validate_itinerary(itinerary, spec, retrieval)
            return PlannerResult(itinerary=itinerary)
        except PlannerValidationError as exc:
            repair_user = f"{user}\nValidation error: {exc}. Return corrected JSON only."
            repaired = _call_planner(llm, system=system, user=repair_user)
            validate_itinerary(repaired, spec, retrieval)
            return PlannerResult(itinerary=repaired, repair_attempted=True)
    except Exception as exc:
        fallback = fallback_itinerary(spec, retrieval)
        return PlannerResult(
            itinerary=fallback,
            used_fallback=True,
            repair_attempted=True,
            caveats=[f"Planner fallback used: {exc}"],
        )
