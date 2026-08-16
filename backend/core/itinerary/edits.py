from __future__ import annotations

from core.trip_models import (
    DraftItinerary,
    ItineraryDay,
    ItineraryEdit,
    MoveItem,
    RemoveItem,
    ReorderDay,
)


def apply_edit(itinerary: DraftItinerary, edit: ItineraryEdit) -> DraftItinerary:
    """Applies a typed itinerary edit purely and deterministically.

    Raises ValueError if:
    - Target day index is out of bounds
    - Referenced poi_id does not exist in the specified day
    - ReorderDay does not match the exact set of items in the day
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

    else:
        raise ValueError(f"Unknown edit operation: {edit}")

    return DraftItinerary(
        hotel_area_id=itinerary.hotel_area_id,
        days=days,
        notes=list(itinerary.notes),
        itinerary_quality=itinerary.itinerary_quality,
        unverified_suggestions=list(itinerary.unverified_suggestions),
    )
