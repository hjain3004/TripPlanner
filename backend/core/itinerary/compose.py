"""Deterministic itinerary composition with safety validation.

Composes a feasible day-by-day itinerary from curated POIs, enforcing:
- T4: Opening-hours feasibility (reject visits on closed days/dates)
- T5: Travel-time budget (haversine estimates, conservative multiplier)

This module lives in ``core/`` and imports nothing from ``agents/`` or ``api/``.
Money and provenance are never computed here; only schedule feasibility.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from core.models import POI
from core.trip_models import DraftItinerary, ItineraryDay, ItineraryItem, RetrievalContext, TripSpec

PACE_ITEMS = {"relaxed": 1, "moderate": 2, "packed": 3}

__all__ = [
    "ComposerResult",
    "DAILY_TRAVEL_BUDGET_MIN",
    "PACE_ITEMS",
    "ScheduleWarning",
    "build_final_schedule",
    "check_poi_hours",
    "compose_itinerary",
    "day_travel_minutes",
    "estimate_travel_min",
    "fallback_itinerary",
    "haversine_km",
    "validate_day_travel_budget",
]

# Conservative travel-time constants (Tier-C, logged in DEVIATIONS).
# Haversine gives great-circle distance; real urban transit is longer.
# 1.4x straight-line-to-route ratio + 15 min base overhead (wait/transfer).
_ROUTE_STRETCH_FACTOR: float = 1.4
_BASE_OVERHEAD_MIN: int = 15
# Average urban transit speed in km/h (conservative for bus/MRT + walking).
_TRANSIT_SPEED_KMH: float = 20.0
# Per-day travel-time budget by pace (minutes).
DAILY_TRAVEL_BUDGET_MIN = {"relaxed": 90, "moderate": 120, "packed": 180}
# Earth radius in km for haversine.
_EARTH_RADIUS_KM: float = 6371.0


class ScheduleWarning(BaseModel):
    """A deterministic feasibility warning emitted by the composer."""

    kind: str  # "closed_day", "closed_date", "travel_budget_exceeded"
    poi_id: str | None = None
    day_date: date | None = None
    message: str


class ComposerResult(BaseModel):
    """Itinerary plus deterministic validation metadata."""

    itinerary: DraftItinerary
    warnings: list[ScheduleWarning] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)  # poi_ids excluded


# --------------------------------------------------------------------------- #
# T4 — Opening-hours feasibility                                               #
# --------------------------------------------------------------------------- #


def check_poi_hours(poi: POI, visit_date: date) -> Literal["open", "closed", "unknown"]:
    """Check whether a POI is open on a given date.

    Returns 'open', 'closed', or 'unknown' (if weekday hours are missing).
    """
    hours = poi.open_hours
    visit_iso = visit_date.isoformat()
    if visit_iso in hours.closed_dates:
        return "closed"

    weekday = visit_date.weekday()
    if weekday not in hours.regular_hours:
        return "unknown"

    intervals = hours.regular_hours[weekday]
    if not intervals:
        return "closed"
    return "open"


# --------------------------------------------------------------------------- #
# T5 — Travel-time budget                                                      #
# --------------------------------------------------------------------------- #


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km.

    Uses the haversine formula.  No external dependency.
    """
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def estimate_travel_min(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Conservative travel-time estimate in minutes between two points.

    Applies a straight-line-to-route stretch factor and a base overhead to the
    haversine distance, assuming mixed walking/public-transit speed.  The result
    is always rounded **up** (ceiling) to avoid under-budgeting.
    """
    dist_km = haversine_km(lat1, lon1, lat2, lon2)
    route_km = dist_km * _ROUTE_STRETCH_FACTOR
    time_min = (route_km / _TRANSIT_SPEED_KMH) * 60 + _BASE_OVERHEAD_MIN
    return math.ceil(time_min)


def day_travel_minutes(pois_in_order: list[POI]) -> int:
    """Total estimated inter-stop travel time for a sequence of POIs."""
    total = 0
    for i in range(len(pois_in_order) - 1):
        a, b = pois_in_order[i], pois_in_order[i + 1]
        total += estimate_travel_min(a.lat, a.lon, b.lat, b.lon)
    return total


def validate_day_travel_budget(
    pois_in_order: list[POI], max_travel_min: int
) -> list[ScheduleWarning]:
    """Check whether a day's stops exceed the travel-time budget."""
    total = day_travel_minutes(pois_in_order)
    if total > max_travel_min:
        return [
            ScheduleWarning(
                kind="travel_budget_exceeded",
                message=(
                    f"Estimated travel time {total} min exceeds "
                    f"budget {max_travel_min} min for this day."
                ),
            )
        ]
    return []


# --------------------------------------------------------------------------- #
# Composer (enhanced fallback_itinerary)                                       #
# --------------------------------------------------------------------------- #


def fallback_itinerary(spec: TripSpec, retrieval: RetrievalContext) -> DraftItinerary:
    """Original deterministic fallback — unchanged interface for backward compat.

    Delegates to ``compose_itinerary`` and returns only the ``DraftItinerary``.
    """
    result = compose_itinerary(spec, retrieval)
    return result.itinerary


def compose_itinerary(spec: TripSpec, retrieval: RetrievalContext) -> ComposerResult:
    """Deterministic itinerary with T4/T5 safety validation.

    1. Selects hotel area by interest overlap + centrality.
    2. Sorts POIs by area proximity, then id.
    3. Assigns POIs to days, **skipping** any POI that is closed on that day (T4).
    4. Validates per-day travel budget and emits warnings (T5).
    """
    warnings: list[ScheduleWarning] = []
    excluded: list[str] = []

    # --- Hotel area selection (unchanged from original) ---
    if retrieval.areas:
        ranked_areas = sorted(
            retrieval.areas,
            key=lambda area: (
                -len(set(spec.interests).intersection(set(area.good_for_tags))),
                -area.centrality_score,
                area.id,
            ),
        )
        hotel_area_id = ranked_areas[0].id
    else:
        hotel_area_id = "unknown"

    # --- Build POI lookup ---
    {poi.id: poi for poi in retrieval.pois}

    # --- Sort POIs: prefer hotel area, then alphabetical by area, then id ---
    pois = sorted(retrieval.pois, key=lambda poi: (poi.area != hotel_area_id, poi.area, poi.id))
    per_day = PACE_ITEMS[spec.pace]

    # --- Assign POIs to days with T4 hours check ---
    cursor = 0
    days: list[ItineraryDay] = []
    travel_budget = DAILY_TRAVEL_BUDGET_MIN[spec.pace]

    for offset in range(spec.nights):
        visit_date = spec.start_date + timedelta(days=offset)
        items: list[ItineraryItem] = []
        day_pois: list[POI] = []
        skipped = 0

        while len(items) < per_day and cursor + skipped < len(pois):
            candidate = pois[cursor + skipped]
            status = check_poi_hours(candidate, visit_date)
            if status == "closed":
                # T4: skip closed POI, emit warning
                warnings.append(
                    ScheduleWarning(
                        kind="closed_day",
                        poi_id=candidate.id,
                        day_date=visit_date,
                        message=(
                            f"{candidate.name} ({candidate.id}) is closed "
                            f"on {visit_date.isoformat()} (weekday {visit_date.weekday()})."
                        ),
                    )
                )
                excluded.append(candidate.id)
                skipped += 1
                continue
            elif status == "unknown":
                warnings.append(
                    ScheduleWarning(
                        kind="unknown_hours",
                        poi_id=candidate.id,
                        day_date=visit_date,
                        message=f"Hours for {candidate.name} on {visit_date.isoformat()} "
                        "are unknown. Verify before visiting.",
                    )
                )

            items.append(ItineraryItem(poi_id=candidate.id))
            day_pois.append(candidate)
            cursor += 1

        # Advance cursor past any skipped items for the next day
        cursor += skipped

        # T5: validate travel budget for this day
        if len(day_pois) > 1:
            travel_warnings = validate_day_travel_budget(day_pois, travel_budget)
            for tw in travel_warnings:
                tw.day_date = visit_date
                warnings.append(tw)

        days.append(ItineraryDay(date=visit_date, items=items))

    notes = ["Deterministic fallback itinerary from curated POIs."]
    if excluded:
        notes.append(f"Excluded {len(excluded)} POI(s) due to closure on scheduled day.")
    if any(w.kind == "travel_budget_exceeded" for w in warnings):
        notes.append("One or more days exceed the estimated travel-time budget.")

    itinerary = DraftItinerary(
        hotel_area_id=hotel_area_id,
        days=days,
        notes=notes,
        itinerary_quality="fallback",
    )

    return ComposerResult(
        itinerary=itinerary,
        warnings=warnings,
        excluded_items=excluded,
    )


def build_final_schedule(
    draft: DraftItinerary, spec: TripSpec, retrieval: RetrievalContext
) -> ComposerResult:
    """Assigns times and validates an LLM-proposed itinerary."""
    warnings: list[ScheduleWarning] = []
    poi_by_id = {poi.id: poi for poi in retrieval.pois}
    travel_budget = DAILY_TRAVEL_BUDGET_MIN.get(spec.pace, 120)

    for day in draft.days:
        current_time_min = 9 * 60  # Start at 09:00 AM
        day_pois: list[POI] = []

        for i, item in enumerate(day.items):
            poi = poi_by_id.get(item.poi_id)
            if not poi:
                continue

            day_pois.append(poi)

            status = check_poi_hours(poi, day.date)
            if status == "closed":
                warnings.append(
                    ScheduleWarning(
                        kind="closed_day",
                        poi_id=poi.id,
                        day_date=day.date,
                        message=f"{poi.name} is scheduled on {day.date.isoformat()} "
                        "but is explicitly closed.",
                    )
                )
            elif status == "unknown":
                warnings.append(
                    ScheduleWarning(
                        kind="unknown_hours",
                        poi_id=poi.id,
                        day_date=day.date,
                        message=f"Hours for {poi.name} on {day.date.isoformat()} "
                        "are unknown. Verify before visiting.",
                    )
                )

            if item.start_hint:
                try:
                    parts = item.start_hint.split(":")
                    if len(parts) >= 2:
                        h, m = int(parts[0]), int(parts[1][:2])
                        hint_min = h * 60 + m
                        if hint_min < current_time_min:
                            warnings.append(
                                ScheduleWarning(
                                    kind="overlap",
                                    poi_id=poi.id,
                                    day_date=day.date,
                                    message=f"Item {poi.id} start time {item.start_hint} "
                                    "overlaps with previous items.",
                                )
                            )
                            # Do not adopt a hint that overlaps the previous item —
                            # keep the cursor moving forward from where it already is.
                        else:
                            current_time_min = hint_min
                except ValueError:
                    pass

            start_h = current_time_min // 60
            start_m = current_time_min % 60
            item.start_time = f"{start_h:02d}:{start_m:02d}"

            end_time_min = current_time_min + poi.typical_duration_min
            end_h = end_time_min // 60
            end_m = end_time_min % 60
            item.end_time = f"{end_h:02d}:{end_m:02d}"

            current_time_min = end_time_min

            # Add travel time to next POI if there is one
            if i < len(day.items) - 1:
                next_poi = poi_by_id.get(day.items[i + 1].poi_id)
                if next_poi:
                    current_time_min += estimate_travel_min(
                        poi.lat, poi.lon, next_poi.lat, next_poi.lon
                    )

        if len(day_pois) > 1:
            travel_warnings = validate_day_travel_budget(day_pois, travel_budget)
            for tw in travel_warnings:
                tw.day_date = day.date
                warnings.append(tw)

    return ComposerResult(itinerary=draft, warnings=warnings)
