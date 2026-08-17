from __future__ import annotations

from datetime import date

import pytest

from core.itinerary.edits import apply_edit
from core.trip_models import (
    AddItem,
    DraftItinerary,
    ItineraryDay,
    ItineraryItem,
    MoveItem,
    RemoveItem,
    ReorderDay,
    ReplaceItem,
)


def _sample_itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="area:marina-bay",
        days=[
            ItineraryDay(
                date=date(2026, 9, 1),
                items=[
                    ItineraryItem(poi_id="poi:gardens-by-the-bay", name="Gardens by the Bay"),
                    ItineraryItem(poi_id="poi:cloud-forest", name="Cloud Forest"),
                    ItineraryItem(poi_id="poi:satay-by-the-bay", name="Satay by the Bay"),
                ],
            ),
            ItineraryDay(
                date=date(2026, 9, 2),
                items=[
                    ItineraryItem(poi_id="poi:national-gallery", name="National Gallery"),
                    ItineraryItem(poi_id="poi:lau-pa-sat", name="Lau Pa Sat"),
                ],
            ),
        ],
    )


def test_move_item_within_same_day() -> None:
    itin = _sample_itinerary()
    edit = MoveItem(
        poi_id="poi:gardens-by-the-bay",
        from_day_index=0,
        to_day_index=0,
        position=2,
    )
    result = apply_edit(itin, edit)

    # In day 0, gardens-by-the-bay moved to position 2 (last)
    day0_ids = [item.poi_id for item in result.days[0].items]
    assert day0_ids == ["poi:cloud-forest", "poi:satay-by-the-bay", "poi:gardens-by-the-bay"]


def test_move_item_between_days() -> None:
    itin = _sample_itinerary()
    edit = MoveItem(
        poi_id="poi:cloud-forest",
        from_day_index=0,
        to_day_index=1,
        position=0,
    )
    result = apply_edit(itin, edit)

    day0_ids = [item.poi_id for item in result.days[0].items]
    day1_ids = [item.poi_id for item in result.days[1].items]
    assert day0_ids == ["poi:gardens-by-the-bay", "poi:satay-by-the-bay"]
    assert day1_ids == ["poi:cloud-forest", "poi:national-gallery", "poi:lau-pa-sat"]


def test_remove_item() -> None:
    itin = _sample_itinerary()
    edit = RemoveItem(
        poi_id="poi:cloud-forest",
        day_index=0,
    )
    result = apply_edit(itin, edit)

    day0_ids = [item.poi_id for item in result.days[0].items]
    assert day0_ids == ["poi:gardens-by-the-bay", "poi:satay-by-the-bay"]


def test_reorder_day() -> None:
    itin = _sample_itinerary()
    edit = ReorderDay(
        day_index=0,
        poi_ids=["poi:satay-by-the-bay", "poi:gardens-by-the-bay", "poi:cloud-forest"],
    )
    result = apply_edit(itin, edit)

    day0_ids = [item.poi_id for item in result.days[0].items]
    assert day0_ids == ["poi:satay-by-the-bay", "poi:gardens-by-the-bay", "poi:cloud-forest"]


def test_unknown_poi_id_raises_value_error() -> None:
    itin = _sample_itinerary()
    edit = MoveItem(
        poi_id="poi:unknown-place",
        from_day_index=0,
        to_day_index=1,
        position=0,
    )
    with pytest.raises(ValueError, match="not found in day"):
        apply_edit(itin, edit)


def test_remove_unknown_poi_raises_value_error() -> None:
    itin = _sample_itinerary()
    edit = RemoveItem(
        poi_id="poi:unknown-place",
        day_index=0,
    )
    with pytest.raises(ValueError, match="not found in day"):
        apply_edit(itin, edit)


def test_reorder_with_mismatched_pois_raises_value_error() -> None:
    itin = _sample_itinerary()
    edit = ReorderDay(
        day_index=0,
        poi_ids=["poi:satay-by-the-bay", "poi:unknown-place"],
    )
    with pytest.raises(ValueError, match="must exactly match"):
        apply_edit(itin, edit)


def test_out_of_bounds_day_index_raises_value_error() -> None:
    itin = _sample_itinerary()
    edit = MoveItem(
        poi_id="poi:cloud-forest",
        from_day_index=0,
        to_day_index=5,
        position=0,
    )
    with pytest.raises(ValueError, match="out of bounds"):
        apply_edit(itin, edit)


def test_apply_edit_does_not_mutate_original() -> None:
    itin = _sample_itinerary()
    orig_day0_len = len(itin.days[0].items)
    edit = RemoveItem(poi_id="poi:cloud-forest", day_index=0)
    apply_edit(itin, edit)
    assert len(itin.days[0].items) == orig_day0_len


def test_add_item_to_day() -> None:
    itin = _sample_itinerary()
    edit = AddItem(poi_id="poi:jewel-changi", day_index=0, position=1)
    result = apply_edit(itin, edit)
    day0_ids = [item.poi_id for item in result.days[0].items]
    assert day0_ids == [
        "poi:gardens-by-the-bay",
        "poi:jewel-changi",
        "poi:cloud-forest",
        "poi:satay-by-the-bay",
    ]


def test_add_item_duplicate_raises_value_error() -> None:
    itin = _sample_itinerary()
    edit = AddItem(poi_id="poi:cloud-forest", day_index=0, position=0)
    with pytest.raises(ValueError, match="already present"):
        apply_edit(itin, edit)


def test_replace_item_in_day() -> None:
    itin = _sample_itinerary()
    edit = ReplaceItem(old_poi_id="poi:cloud-forest", new_poi_id="poi:jewel-changi", day_index=0)
    result = apply_edit(itin, edit)
    day0_ids = [item.poi_id for item in result.days[0].items]
    assert day0_ids == ["poi:gardens-by-the-bay", "poi:jewel-changi", "poi:satay-by-the-bay"]


def test_replace_item_duplicate_raises_value_error() -> None:
    itin = _sample_itinerary()
    edit = ReplaceItem(
        old_poi_id="poi:cloud-forest", new_poi_id="poi:satay-by-the-bay", day_index=0
    )
    with pytest.raises(ValueError, match="already present"):
        apply_edit(itin, edit)
