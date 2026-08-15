import pytest
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec
from agents.estimator import estimate_costed_trip
from datetime import date
from core.db import KnowledgeBase
from pathlib import Path

def test_estimator_can_cost_a_catalog_poi_without_keyerror(active_catalog, tmp_path):
    from core.db import load_kb, seed_database
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
                items=[ItineraryItem(poi_id="pl_00013d64e216d5e9")]
            )
        ]
    )
    
    result = estimate_costed_trip(spec, itinerary, kb, booking_date=date(2026, 7, 25))
    
    # We expect it to not raise KeyError and just cost the item.
    found = False
    for line in result.costed_trip.lines:
        if line.id == "poi:pl_00013d64e216d5e9":
            found = True
            break
    assert found
