from __future__ import annotations

from core.models import POI
from core.trip_models import (
    AddItem,
    DraftItinerary,
    ItineraryDay,
    ItineraryEdit,
    ItineraryItem,
    MoveItem,
    POIEvidence,
    RemoveItem,
    ReorderDay,
    ReplaceItem,
)


def apply_edit(
    itinerary: DraftItinerary,
    edit: ItineraryEdit,
    candidate_pois: list[POI] | None = None,
    poi_evidence: list[POIEvidence] | None = None,
) -> DraftItinerary:
    """Applies a typed itinerary edit purely and deterministically.

    Raises ValueError if:
    - Target day index is out of bounds
    - Referenced poi_id does not exist in the specified day
    - ReorderDay does not match the exact set of items in the day
    - AddItem/ReplaceItem references an already present POI on that day
    """
    days = [
        ItineraryDay(
            date=day.date,
            items=[item.model_copy(deep=True) for item in day.items],
            unmet_needs=list(day.unmet_needs),
            rejections=list(day.rejections),
        )
        for day in itinerary.days
    ]

    pois_by_id = {p.id: p for p in candidate_pois or []}
    evidence_by_id = {e.poi_id: e for e in poi_evidence or []}

    def _make_item(poi_id: str, start_hint: str | None = None) -> ItineraryItem:
        poi = pois_by_id.get(poi_id)
        ev = evidence_by_id.get(poi_id)
        return ItineraryItem(
            poi_id=poi_id,
            start_hint=start_hint,
            name=poi.name if poi else None,
            category=poi.tags[0] if poi and poi.tags else None,
            lat=poi.lat if poi else None,
            lon=poi.lon if poi else None,
            evidence=ev,
        )

    if isinstance(edit, MoveItem):
        if edit.from_day_index < 0 or edit.from_day_index >= len(days):
            raise ValueError(
                f"from_day_index {edit.from_day_index} out of bounds (0..{len(days) - 1})"
            )
        if edit.to_day_index < 0 or edit.to_day_index >= len(days):
            raise ValueError(
                f"to_day_index {edit.to_day_index} out of bounds (0..{len(days) - 1})"
            )

        source_items = days[edit.from_day_index].items
        item_idx = next(
            (i for i, item in enumerate(source_items) if item.poi_id == edit.poi_id),
            None,
        )
        if item_idx is None:
            raise ValueError(
                f"poi_id '{edit.poi_id}' not found in day {edit.from_day_index}"
            )

        target_item = source_items.pop(item_idx)
        target_items = days[edit.to_day_index].items
        insert_pos = max(0, min(edit.position, len(target_items)))
        target_items.insert(insert_pos, target_item)

    elif isinstance(edit, RemoveItem):
        if edit.day_index < 0 or edit.day_index >= len(days):
            raise ValueError(
                f"day_index {edit.day_index} out of bounds (0..{len(days) - 1})"
            )

        source_items = days[edit.day_index].items
        item_idx = next(
            (i for i, item in enumerate(source_items) if item.poi_id == edit.poi_id),
            None,
        )
        if item_idx is None:
            raise ValueError(
                f"poi_id '{edit.poi_id}' not found in day {edit.day_index}"
            )

        source_items.pop(item_idx)

    elif isinstance(edit, ReorderDay):
        if edit.day_index < 0 or edit.day_index >= len(days):
            raise ValueError(
                f"day_index {edit.day_index} out of bounds (0..{len(days) - 1})"
            )

        day_items = days[edit.day_index].items
        existing_by_id = {item.poi_id: item for item in day_items}

        if len(edit.poi_ids) != len(day_items) or set(edit.poi_ids) != set(existing_by_id.keys()):
            raise ValueError(
                "ReorderDay poi_ids must exactly match the set of items in the day"
            )

        days[edit.day_index].items = [existing_by_id[poi_id] for poi_id in edit.poi_ids]

    elif isinstance(edit, AddItem):
        if edit.day_index < 0 or edit.day_index >= len(days):
            raise ValueError(
                f"day_index {edit.day_index} out of bounds (0..{len(days) - 1})"
            )

        day_items = days[edit.day_index].items
        if any(item.poi_id == edit.poi_id for item in day_items):
            raise ValueError(
                f"poi_id '{edit.poi_id}' is already present in day {edit.day_index}"
            )

        new_item = _make_item(edit.poi_id)
        insert_pos = max(0, min(edit.position, len(day_items)))
        day_items.insert(insert_pos, new_item)

    elif isinstance(edit, ReplaceItem):
        if edit.day_index < 0 or edit.day_index >= len(days):
            raise ValueError(
                f"day_index {edit.day_index} out of bounds (0..{len(days) - 1})"
            )

        day_items = days[edit.day_index].items
        item_idx = next(
            (i for i, item in enumerate(day_items) if item.poi_id == edit.old_poi_id),
            None,
        )
        if item_idx is None:
            raise ValueError(
                f"old_poi_id '{edit.old_poi_id}' not found in day {edit.day_index}"
            )

        if edit.new_poi_id != edit.old_poi_id and any(
            item.poi_id == edit.new_poi_id for item in day_items
        ):
            raise ValueError(
                f"new_poi_id '{edit.new_poi_id}' is already present in day {edit.day_index}"
            )

        old_item = day_items[item_idx]
        new_item = _make_item(edit.new_poi_id, start_hint=old_item.start_hint)
        day_items[item_idx] = new_item

    else:
        raise ValueError(f"Unknown edit operation: {edit}")

    return DraftItinerary(
        hotel_area_id=itinerary.hotel_area_id,
        days=days,
        notes=list(itinerary.notes),
        itinerary_quality=itinerary.itinerary_quality,
        unverified_suggestions=list(itinerary.unverified_suggestions),
    )
