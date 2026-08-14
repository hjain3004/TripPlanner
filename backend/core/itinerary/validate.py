# ruff: noqa: E501, E402
from core.itinerary.compose import check_poi_hours
from core.itinerary.contracts import (
    ItineraryConstraints,
    ItineraryValidation,
    RejectionReason,
    RouteMatrix,
)
from core.trip_models import DraftItinerary, RetrievalContext


def _parse_time(hm: str) -> int:
    if not hm:
        return 0
    parts = hm.split(":")
    if len(parts) >= 2:
        return int(parts[0]) * 60 + int(parts[1][:2])
    return 0

def validate_draft(
    draft: DraftItinerary,
    matrix: RouteMatrix,
    constraints: ItineraryConstraints,
    ctx: RetrievalContext
) -> ItineraryValidation:
    rejections = []
    
    poi_by_id = {p.id: p for p in ctx.pois}
    
    for day in draft.days:
        daily_travel_min = 0
        prev_item = None
        
        for item in day.items:
            poi = poi_by_id.get(item.poi_id)
            if not poi:
                rejections.append(RejectionReason(code="no_evidence_backed_place_id", place_id=item.poi_id))
                prev_item = item
                continue
                
            status = check_poi_hours(poi, day.date)
            if status == "closed":
                rejections.append(RejectionReason(code="closed_day", place_id=item.poi_id, detail="explicitly closed"))
            elif status == "unknown" and item.start_hint:
                rejections.append(RejectionReason(code="unknown_hours_timing_critical", place_id=item.poi_id))
                
            if "inaccessible" in poi.tags:
                rejections.append(RejectionReason(code="accessibility_excluded", place_id=item.poi_id))
                
            for tag in poi.tags:
                if tag.startswith("fixed_window_"):
                    # Format: fixed_window_0900_1000
                    parts = tag.split("_")
                    if len(parts) == 4:
                        sw = f"{parts[2][:2]}:{parts[2][2:]}"
                        ew = f"{parts[3][:2]}:{parts[3][2:]}"
                        if item.start_time != sw or item.end_time != ew:
                            rejections.append(RejectionReason(code="fixed_window_violated", place_id=item.poi_id))
                            
            if prev_item and prev_item.end_time and item.start_time:
                prev_end = _parse_time(prev_item.end_time)
                curr_start = _parse_time(item.start_time)
                
                if curr_start < prev_end:
                    rejections.append(RejectionReason(code="overlap", place_id=item.poi_id))
                else:
                    dur = matrix.duration_min(prev_item.poi_id, item.poi_id, "transit")
                    if dur is not None:
                        daily_travel_min += dur
                        if curr_start < prev_end + dur:
                            rejections.append(RejectionReason(code="travel_time_infeasible", place_id=item.poi_id, detail=f"need {dur}m"))
                            
            prev_item = item
            
        if daily_travel_min > constraints.max_daily_travel_min:
            rejections.append(RejectionReason(code="travel_budget_exceeded", detail=f"{daily_travel_min} > {constraints.max_daily_travel_min}"))
            
    return ItineraryValidation(valid=len(rejections) == 0, rejections=rejections)
