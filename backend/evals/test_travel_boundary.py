from __future__ import annotations

import ast
import socket
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).parent.parent / "core"


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_never_imports_gateway() -> None:
    offenders = [
        str(path)
        for path in CORE_DIR.rglob("*.py")
        if any(name == "gateway" or name.startswith("gateway.") for name in _imports_in(path))
    ]
    assert offenders == []


def test_travel_gateway_search_flights_makes_no_socket_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from core.db import SEEDS_DIR, load_kb, seed_database
    from gateway.travel.adapters.sample import SampleAdapter
    from gateway.travel.contracts import FlightSearchRequest, TravelerMix

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no socket calls allowed in gateway travel tests")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "t.sqlite"
        seed_database(SEEDS_DIR, db_path)
        kb = load_kb(db_path)
        adapter = SampleAdapter(kb, now=lambda: datetime(2026, 7, 25, tzinfo=UTC))
        quotes = asyncio.run(
            adapter.search_flights(
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
        assert quotes  # non-vacuous: proves the adapter really ran, not just imported


def test_no_secret_markers_in_travel_gateway_source() -> None:
    travel_dir = Path(__file__).parent.parent / "gateway" / "travel"
    forbidden_markers = ["sk_live", "api_key=", "Authorization: Bearer "]
    offenders = [
        str(path)
        for path in travel_dir.rglob("*.py")
        if any(marker in path.read_text() for marker in forbidden_markers)
    ]
    assert offenders == []


def test_gateway_travel_parity_module_makes_no_socket_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tempfile as _tempfile

    from agents.gateway_estimator import estimate_costed_trip_via_gateway
    from agents.models import DraftItinerary, ItineraryDay
    from core.db import SEEDS_DIR, load_kb, seed_database
    from core.models import UserWallet
    from core.trip_models import TripSpec

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no socket calls allowed anywhere in the gateway path")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    with _tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "t.sqlite"
        seed_database(SEEDS_DIR, db_path)
        kb = load_kb(db_path)
        spec = TripSpec(
            home_country="IN",
            origin_city="DEL",
            destination_city="SIN",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            travelers=2,
            style="balanced",
            wallet=UserWallet(card_ids=[]),
        )
        itinerary = DraftItinerary(
            hotel_area_id="marina_bay",
            days=[ItineraryDay(date=date(2026, 8, 1), items=[])],
        )
        result = estimate_costed_trip_via_gateway(
            spec, itinerary, kb, booking_date=date(2026, 7, 25)
        )
        assert result.costed_trip.lines
