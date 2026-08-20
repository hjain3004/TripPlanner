from __future__ import annotations

import asyncio
import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from core.db import SEEDS_DIR, load_kb, seed_database
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import (
    AwardSearchRequest,
    FlexibleFlightSearchRequest,
    FlightSearchRequest,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.errors import TravelGatewayError


def _kb(tmp_path: Path):  # type: ignore[no-untyped-def]
    db_path = tmp_path / "t.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _adapter(tmp_path: Path) -> SampleAdapter:
    return SampleAdapter(_kb(tmp_path), now=lambda: datetime(2026, 7, 25, tzinfo=UTC))


def test_search_flights_maps_seed_row_and_preserves_amount(tmp_path: Path) -> None:
    quotes = asyncio.run(
        _adapter(tmp_path).search_flights(
            FlightSearchRequest(
                origin="DEL",
                destination="SIN",
                depart_date=date(2026, 8, 1),
                return_date=date(2026, 8, 5),
                travelers=TravelerMix(adults=2),
                cabin="economy",
                currency="INR",
            )
        )
    )
    assert quotes
    winner = next(q for q in quotes if q.evidence.provider_quote_id == "del-sin-6e-eco")
    assert winner.total_minor == 4_100_000
    assert winner.currency == "INR"
    assert winner.segments[0].marketing_airline == "IndiGo"
    assert winner.travelers.adults == 2
    assert all(q.evidence.status == "estimated" for q in quotes)
    assert all(q.evidence.needs_verification for q in quotes)


def test_search_flights_deterministic_ids_and_timestamps(tmp_path: Path) -> None:
    req = FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=None,
        travelers=TravelerMix(adults=1),
        cabin="economy",
        currency="INR",
    )
    first = asyncio.run(_adapter(tmp_path).search_flights(req))
    second = asyncio.run(_adapter(tmp_path).search_flights(req))
    assert [q.id for q in first] == [q.id for q in second]
    assert [q.evidence.retrieved_at for q in first] == [q.evidence.retrieved_at for q in second]


def test_search_flights_empty_route_returns_empty_list_not_error(tmp_path: Path) -> None:
    quotes = asyncio.run(
        _adapter(tmp_path).search_flights(
            FlightSearchRequest(
                origin="NYC",
                destination="LON",
                depart_date=date(2026, 8, 1),
                return_date=None,
                travelers=TravelerMix(adults=1),
                cabin="economy",
                currency="USD",
            )
        )
    )
    assert quotes == []


def test_search_hotels_maps_seed_row(tmp_path: Path) -> None:
    quotes = asyncio.run(
        _adapter(tmp_path).search_hotels(
            HotelSearchRequest(
                city="Singapore",
                check_in=date(2026, 8, 1),
                check_out=date(2026, 8, 5),
                travelers=TravelerMix(adults=2),
                rooms=1,
                area_ids=["marina_bay"],
                style="balanced",
                currency="INR",
            )
        )
    )
    winner = next(q for q in quotes if q.property_id == "sg-hotel-marina-balanced")
    assert winner.total_minor == 1_600_000 * 4
    assert winner.currency == "INR"
    assert winner.evidence.status == "estimated"
    assert winner.evidence.needs_verification is True


def test_search_awards_returns_empty_no_fabricated_availability(tmp_path: Path) -> None:
    quotes = asyncio.run(
        _adapter(tmp_path).search_awards(
            AwardSearchRequest(
                origin="DEL",
                destination="SIN",
                depart_date=date(2026, 8, 1),
                return_date=date(2026, 8, 5),
                travelers=TravelerMix(adults=2),
                cabin="business",
                program_ids=["lionmiles"],
            )
        )
    )
    assert quotes == []


def test_search_flight_price_trends_is_unsupported_domain(tmp_path: Path) -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(
            _adapter(tmp_path).search_flight_price_trends(
                FlexibleFlightSearchRequest(
                    origin="DEL",
                    destination="SIN",
                    depart_window_start=date(2026, 8, 1),
                    depart_window_end=date(2026, 8, 3),
                    return_window_start=None,
                    return_window_end=None,
                    trip_length_nights=4,
                    travelers=TravelerMix(adults=1),
                    cabin="economy",
                    currency="INR",
                    max_date_pairs=5,
                )
            )
        )
    assert exc_info.value.code == "unsupported_domain"


def test_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("SampleAdapter must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    quotes = asyncio.run(
        _adapter(tmp_path).search_flights(
            FlightSearchRequest(
                origin="DEL",
                destination="SIN",
                depart_date=date(2026, 8, 1),
                return_date=None,
                travelers=TravelerMix(adults=1),
                cabin="economy",
                currency="INR",
            )
        )
    )
    assert quotes


def test_notes_document_synthetic_timing_and_incomplete_price(tmp_path: Path) -> None:
    quotes = asyncio.run(
        _adapter(tmp_path).search_flights(
            FlightSearchRequest(
                origin="DEL",
                destination="SIN",
                depart_date=date(2026, 8, 1),
                return_date=None,
                travelers=TravelerMix(adults=1),
                cabin="economy",
                currency="INR",
            )
        )
    )
    notes_text = " ".join(quotes[0].evidence.notes).casefold()
    assert "synthetic" in notes_text
    assert quotes[0].evidence.completeness == "taxes_uncertain"


def test_seed_amount_is_never_modified(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    seed_row = kb.sample_flights("DEL", "SIN", "economy")[0]
    quotes = asyncio.run(
        SampleAdapter(kb, now=lambda: datetime(2026, 7, 25, tzinfo=UTC)).search_flights(
            FlightSearchRequest(
                origin="DEL",
                destination="SIN",
                depart_date=date(2026, 8, 1),
                return_date=None,
                travelers=TravelerMix(adults=1),
                cabin="economy",
                currency="INR",
            )
        )
    )
    match = next(q for q in quotes if q.evidence.provider_quote_id == seed_row.id)
    assert match.total_minor == seed_row.price_minor


def test_capabilities_declare_sample_source_method_and_no_live_data(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    assert adapter.capabilities.source_method == "sample"
    assert adapter.capabilities.live_data is False
    assert adapter.capabilities.domains == {"flight", "hotel", "award"}


def test_flight_terms_version_and_attribution_are_explicit(tmp_path: Path) -> None:
    quotes = asyncio.run(
        _adapter(tmp_path).search_flights(
            FlightSearchRequest(
                origin="DEL",
                destination="SIN",
                depart_date=date(2026, 8, 1),
                return_date=None,
                travelers=TravelerMix(adults=1),
                cabin="economy",
                currency="INR",
            )
        )
    )
    assert quotes[0].evidence.terms_version
    assert quotes[0].evidence.attribution
