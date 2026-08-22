from __future__ import annotations

import socket
from datetime import UTC, datetime

import pytest

from gateway.travel.adapters.gondola.fixture_transport import FixtureGondolaTransport
from gateway.travel.errors import TravelGatewayError


def _transport() -> FixtureGondolaTransport:
    return FixtureGondolaTransport(now=lambda: datetime(2026, 8, 21, tzinfo=UTC))


def test_successful_hotel_search() -> None:
    envelope = _transport().call_tool("search_hotels", "search_hotels_success")
    assert envelope["results"]
    assert "synthetic" in envelope["_fixture_provenance"]


def test_successful_flight_search() -> None:
    envelope = _transport().call_tool("search_flights", "search_flights_success")
    assert envelope["results"]


def test_empty_results() -> None:
    envelope = _transport().call_tool("search_hotels", "search_hotels_empty")
    assert envelope["results"] == []


def test_authentication_required() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_flights", "authentication_required")
    assert exc_info.value.code == "authentication_failed"


def test_token_refresh_failure() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_flights", "token_refresh_failure")
    assert exc_info.value.code == "authentication_failed"


def test_rate_limiting() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_hotels", "rate_limited")
    assert exc_info.value.code == "rate_limited"


def test_timeout() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_hotels", "timeout")
    assert exc_info.value.code == "timeout"


def test_malformed_mcp_result() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_hotels", "malformed_result")
    assert exc_info.value.code == "invalid_response"


def test_unknown_tool_is_rejected_before_any_fixture_load() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("delete_rate_alert", "search_hotels_success")
    assert exc_info.value.code == "permission_denied"


def test_oversized_payload() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_hotels", "oversized_payload")
    assert exc_info.value.code == "invalid_response"


def test_partial_hotel_price() -> None:
    envelope = _transport().call_tool("search_hotels", "search_hotels_partial_price")
    result = envelope["results"][0]
    assert result["cash_rate_minor"] is not None
    assert result["cancellation_text"] is None


def test_incomplete_flight_segments() -> None:
    envelope = _transport().call_tool("search_flights", "search_flights_incomplete_segments")
    segment = envelope["results"][0]["segments"][0]
    assert segment["arrival_at"] is None


def test_stale_response() -> None:
    envelope = _transport().call_tool("search_hotels", "search_hotels_stale")
    assert envelope["_fixture_meta"]["status"] == "stale"


def test_hostile_prompt_injection_text() -> None:
    envelope = _transport().call_tool("search_hotels", "search_hotels_prompt_injection")
    result = envelope["results"][0]
    assert "ignore previous instructions" in result["name"].lower()


def test_missing_booking_link() -> None:
    envelope = _transport().call_tool("search_hotels", "search_hotels_missing_booking_link")
    assert envelope["results"][0]["booking_link"] is None


def test_provider_outage() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().call_tool("search_hotels", "provider_outage")
    assert exc_info.value.code == "provider_unavailable"


def test_no_network_socket_is_never_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FixtureGondolaTransport must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    _transport().call_tool("search_hotels", "search_hotels_success")
