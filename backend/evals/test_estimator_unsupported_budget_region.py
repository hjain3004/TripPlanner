"""I7 Task 7 finding: registering a real second region (Mumbai) exposed a
crash. _per_diem_lines() unconditionally applied Singapore's SGD per-diem
constants and raised ValueError when no FX rate existed for the destination
currency - the estimator would 500 on any real trip to a budget_supported=false
region, not degrade gracefully like _pick_flight/_pick_hotel already do.
"""

from __future__ import annotations

from datetime import date

import pytest

from agents.estimator import estimate_costed_trip
from agents.models import DraftItinerary, ItineraryDay, TripSpec
from core.db import SEEDS_DIR, load_kb, seed_database
from gateway.catalog.regions import Region


def _kb(tmp_path):
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _spec() -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="BOM",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        style="balanced",
        interests=["food"],
        wallet={"card_ids": ["hdfc-infinia"]},
    )


def test_a_budget_unsupported_region_does_not_crash_the_estimator(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fake = Region(
        iata="BOM", city_name="Mumbai", country_code="IN", timezone="Asia/Kolkata",
        catalog_id="bom-core", centroid_lat=19.0760, centroid_lon=72.8777,
        currency="INR", budget_supported=False,
    )
    monkeypatch.setattr(
        "gateway.catalog.regions.get_region", lambda iata: fake if iata == "BOM" else None
    )

    kb = _kb(tmp_path)
    itinerary = DraftItinerary(
        hotel_area_id="marina_bay",
        days=[ItineraryDay(date=date(2026, 8, 1), items=[])],
    )

    result = estimate_costed_trip(_spec(), itinerary, kb, booking_date=date(2026, 7, 25))

    assert not any(line.id.startswith("per_diem:") for line in result.costed_trip.lines)
    assert any("Mumbai" in a for a in result.assumptions)
