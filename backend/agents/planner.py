from __future__ import annotations

import logging
from datetime import date, timedelta

from agents.llm import LLMClient
from agents.models import (
    DraftItinerary,
    PlannerResult,
    RetrievalContext,
    TripSpec,
)
from core.itinerary.compose import (
    ComposerResult,
    ScheduleWarning,
    build_final_schedule,
)

logger = logging.getLogger(__name__)

class PlannerValidationError(ValueError):
    pass


def _trip_dates(spec: TripSpec) -> set[date]:
    return {spec.start_date + timedelta(days=offset) for offset in range(spec.nights)}


def validate_itinerary(
    itinerary: DraftItinerary, spec: TripSpec, retrieval: RetrievalContext, discovered_poi_ids: set[str] | None = None
) -> None:
    poi_ids = {poi.id for poi in retrieval.pois}
    if discovered_poi_ids:
        poi_ids.update(discovered_poi_ids)
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
    spec: TripSpec,
    registry: Any = None,
) -> tuple[DraftItinerary, set[str]]:
    from agents.discovery.controller import run_discovery
    from agents.discovery.tool import MODEL_TOOLS
    from core.trip_models import DraftItinerary
    from gateway.places.registry import get_default_place_registry
    
    def _execute():
        return llm.complete_json(
            node="planner",
            system=system,
            user=user,
            schema=DraftItinerary,
            tools=MODEL_TOOLS,
        )
    
    reg = registry or get_default_place_registry()
    discovery_result = run_discovery(spec, reg, _execute)
    
    if discovery_result.itinerary is not None:
        discovered = {c.place_id for c in discovery_result.committed_candidates}
        return discovery_result.itinerary, discovered
        
    raise PlannerValidationError("Discovery loop exhausted without producing a plan: " + discovery_result.stop_reason)


# Gate I1 (itinerary design §14): "no overlap, known-closed visits or
# impossible transitions." unknown_hours is deliberately excluded — design
# §5.4 requires it to surface as a visible verification task, not a rejection.
_UNSAFE_WARNING_KINDS = frozenset({"overlap", "closed_day", "travel_budget_exceeded"})


def _unsafe_warnings(result: ComposerResult) -> list[ScheduleWarning]:
    return [w for w in result.warnings if w.kind in _UNSAFE_WARNING_KINDS]


def _unsafe_warning_message(unsafe: list[ScheduleWarning]) -> str:
    return "; ".join(w.message for w in unsafe)


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
        itinerary, discovered = _call_planner(llm, system=system, user=user, spec=spec)
        try:
            validate_itinerary(itinerary, spec, retrieval, discovered)
            result = build_final_schedule(itinerary, spec, retrieval)
            unsafe = _unsafe_warnings(result)
            if unsafe:
                raise PlannerValidationError(_unsafe_warning_message(unsafe))
            return PlannerResult(
                itinerary=result.itinerary,
                caveats=[w.message for w in result.warnings]
            )
        except PlannerValidationError as exc:
            repair_user = f"{user}\nValidation error: {exc}. Return corrected JSON only."
            repaired, repaired_discovered = _call_planner(llm, system=system, user=repair_user, spec=spec)
            validate_itinerary(repaired, spec, retrieval, repaired_discovered)
            result = build_final_schedule(repaired, spec, retrieval)
            unsafe = _unsafe_warnings(result)
            if unsafe:
                raise PlannerValidationError(
                    f"Repaired schedule still unsafe: {_unsafe_warning_message(unsafe)}"
                )
            return PlannerResult(
                itinerary=result.itinerary,
                repair_attempted=True,
                caveats=[w.message for w in result.warnings]
            )
    except Exception as exc:

        from core.itinerary.compose import DAILY_TRAVEL_BUDGET_MIN
        from core.itinerary.contracts import ItineraryConstraints
        from core.itinerary.fallback import ComposeStrategy
        from core.itinerary.routing import build_geodesic_matrix_with_gaps
        
        matrix, _ = build_geodesic_matrix_with_gaps(retrieval.pois, "transit")
        constraints = ItineraryConstraints(max_daily_travel_min=DAILY_TRAVEL_BUDGET_MIN[spec.pace])
        
        logger.debug("Routing matrix: %s, constraints: %s", matrix, constraints)
        
        strategy = ComposeStrategy()
        result = strategy.compose(spec, retrieval, matrix, constraints)
        
        return PlannerResult(
            itinerary=result.itinerary,
            used_fallback=True,
            repair_attempted=True,
            caveats=[f"Planner fallback used: {exc}"] + [w.message for w in result.warnings],
        )
