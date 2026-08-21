"""Proves the Gondola offline path is zero-network end to end, from the
fixture transport through native-contract parsing. HotelQuote/FlightQuote
normalization (Phases 4-5) adds its own end-to-end tests once it exists.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

import pytest

from gateway.travel.adapters.gondola.contracts import parse_flight_results, parse_hotel_results
from gateway.travel.adapters.gondola.fixture_transport import FixtureGondolaTransport


def test_offline_hotel_search_path_is_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Gondola offline path must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    transport = FixtureGondolaTransport(now=lambda: datetime(2026, 8, 21, tzinfo=UTC))
    envelope = transport.call_tool("search_hotels", "search_hotels_success")
    results = parse_hotel_results(envelope["results"])

    assert len(results) >= 1
    assert results[0].cash_rate_minor is not None


def test_offline_flight_search_path_is_zero_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Gondola offline path must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    transport = FixtureGondolaTransport(now=lambda: datetime(2026, 8, 21, tzinfo=UTC))
    envelope = transport.call_tool("search_flights", "search_flights_success")
    results = parse_flight_results(envelope["results"])

    assert len(results) >= 1
    assert results[0].segments
