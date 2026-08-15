import json
from datetime import date
from pathlib import Path

import pytest

from agents.estimator import estimate_costed_trip
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec


@pytest.mark.allow_real_catalog
def test_estimator_can_cost_a_catalog_poi_without_keyerror(
    active_catalog: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.db import load_kb, seed_database

    # get_catalog_poi resolves a region -> catalog_id and looks the catalog up
    # via active_catalog_path(). Point that lookup at this test's own fixture
    # catalog instead of relying on whatever real catalog happens to be sitting
    # in the repo's catalogs/ dir - the fixture built a place, use *that* place.
    monkeypatch.setattr(
        "gateway.catalog.activate.active_catalog_path",
        lambda catalog_root, catalog_id: active_catalog,
    )
    catalog_data = json.loads(active_catalog.read_text())
    assert catalog_data["places"], "fixture catalog produced no places"
    poi_id = catalog_data["places"][0]["place_id"]

    db_path = tmp_path / "tripwise.sqlite"
    seed_database(Path("core/seeds"), db_path)
    kb = load_kb(db_path)

    spec = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=1,
        style="balanced",
        interests=["food"],
        wallet={"card_ids": ["hdfc-infinia"]}
    )

    itinerary = DraftItinerary(
        hotel_area_id="chinatown",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1),
                items=[ItineraryItem(poi_id=poi_id)]
            )
        ]
    )

    result = estimate_costed_trip(spec, itinerary, kb, booking_date=date(2026, 7, 25))

    # We expect it to not raise KeyError and just cost the item.
    found = any(line.id == f"poi:{poi_id}" for line in result.costed_trip.lines)
    assert found
