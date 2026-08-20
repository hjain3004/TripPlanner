from __future__ import annotations

from datetime import date

import pytest

from agents.models import PlaceSearchRequest
from agents.retrieval import retrieve_candidates
from agents.search import search_catalog_places
from core.db import load_kb
from core.models import OptimizationPrefs, UserWallet
from core.trip_models import TripSpec

pytestmark = pytest.mark.allow_real_catalog


def _spec(destination: str) -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city=destination,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["food", "culture"],
        pace="moderate",
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        optimization=OptimizationPrefs(),
    )


@pytest.mark.parametrize("destination", ["BOM", "DXB", "NYC", "LON", "PAR"])
def test_regional_catalog_pois_use_geo_cell_areas(destination: str) -> None:
    ctx = retrieve_candidates(_spec(destination), load_kb(), limit=16)

    assert ctx.pois
    located = [poi for poi in ctx.pois if poi.lat is not None and poi.lon is not None]
    assert located
    assert all(poi.area.startswith(f"geo-cell:{destination.casefold()}:") for poi in located)
    assert ctx.areas
    assert {poi.area for poi in located}.issubset({area.id for area in ctx.areas})


def test_buckingham_palace_exact_search_avoids_cafe_or_distant_duplicate_first() -> None:
    resp = search_catalog_places(
        PlaceSearchRequest(destination="LON", query="Buckingham Palace", limit=5),
        load_kb(),
    )

    assert resp.results
    first = resp.results[0]
    assert first.category in {"attraction", "landmark"}
    assert first.lat is not None and first.lon is not None
    assert 51.49 <= first.lat <= 51.51
    assert -0.16 <= first.lon <= -0.12


def test_metropolitan_museum_exact_search_does_not_prioritize_airport_duplicate() -> None:
    resp = search_catalog_places(
        PlaceSearchRequest(destination="NYC", query="Metropolitan Museum", limit=5),
        load_kb(),
    )

    assert resp.results
    first = resp.results[0]
    assert first.category == "museum"
    assert first.lat is not None and first.lon is not None
    assert first.lat > 40.75
    assert first.lon < -73.93
