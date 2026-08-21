from __future__ import annotations

import json
from pathlib import Path

from gateway.travel.adapters.gondola.contracts import (
    GondolaFlightResult,
    GondolaHotelResult,
    parse_hotel_results,
)

FIXTURES = Path(__file__).parent.parent / "gateway" / "travel" / "adapters" / "gondola" / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_search_hotels_success_fixture_declares_synthetic_provenance() -> None:
    envelope = _load("search_hotels_success")
    assert "synthetic" in envelope["_fixture_provenance"]


def test_search_hotels_success_round_trips_into_native_contract() -> None:
    envelope = _load("search_hotels_success")
    results = parse_hotel_results(envelope["results"])
    assert len(results) >= 1
    first = results[0]
    assert isinstance(first, GondolaHotelResult)
    assert isinstance(first.cash_rate_minor, int)
    assert isinstance(first.points_rate, int | None)


def test_search_flights_success_fixture_declares_synthetic_provenance() -> None:
    envelope = _load("search_flights_success")
    assert "synthetic" in envelope["_fixture_provenance"]


def test_search_flights_success_round_trips_into_native_contract() -> None:
    envelope = _load("search_flights_success")
    result = GondolaFlightResult.model_validate(envelope["results"][0])
    assert result.segments
    assert isinstance(result.total_price_minor, int)
    for segment in result.segments:
        assert isinstance(segment.duration_min, int)
