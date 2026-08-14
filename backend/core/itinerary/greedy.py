from datetime import timedelta

from core.itinerary.compose import (
    ComposerResult,
    ScheduleWarning,
    check_poi_hours,
    validate_day_travel_budget,
)
from core.itinerary.contracts import ItineraryConstraints, RouteMatrix
from core.models import POI
from core.trip_models import DraftItinerary, ItineraryDay, ItineraryItem, RetrievalContext, TripSpec


def score_draft(
    draft: DraftItinerary,
    matrix: RouteMatrix,
    constraints: ItineraryConstraints,
    ctx: RetrievalContext,
) -> int:
    score = 0
    poi_by_id = {p.id: p for p in ctx.pois}

    for day in draft.days:
        for item in day.items:
            poi = poi_by_id.get(item.poi_id)
            if not poi:
                continue

            # Geographic coherence
            if poi.area == draft.hotel_area_id:
                score += 100

            # Must-do vs optional
            if any(t in poi.tags for t in ["must_do_tag", "must_do", "must_see"]):
                score += 500

            # Fresher evidence
            if poi.provenance and poi.provenance.last_verified:
                score += poi.provenance.last_verified.toordinal() // 100
    return score


class GreedyComposer:
    name: str = "greedy"

    def compose(
        self,
        spec: TripSpec,
        retrieval: RetrievalContext,
        matrix: RouteMatrix | None = None,
        constraints: ItineraryConstraints | None = None,
    ) -> ComposerResult:
        from core.itinerary.compose import DAILY_TRAVEL_BUDGET_MIN, PACE_ITEMS

        warnings: list[ScheduleWarning] = []
        excluded: list[str] = []

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

        def poi_score(poi: POI) -> int:
            sc = 0
            if poi.area == hotel_area_id:
                sc += 100
            if any(t in poi.tags for t in spec.interests):
                sc += 500
            if any(t in poi.tags for t in ["must_do_tag", "must_do", "must_see"]):
                sc += 500
            if poi.provenance and poi.provenance.last_verified:
                sc += poi.provenance.last_verified.toordinal() // 100
            return sc

        # Tiebreaker: (poi.area != hotel_area_id, poi.area, poi.id)
        # ensures exact match with I1 composer
        pois = sorted(
            retrieval.pois,
            key=lambda poi: (-poi_score(poi), poi.area != hotel_area_id, poi.area, poi.id),
        )
        per_day = PACE_ITEMS[spec.pace]

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

            cursor += skipped

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
