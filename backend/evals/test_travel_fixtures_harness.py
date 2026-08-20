from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gateway.travel.errors import TravelGatewayError
from gateway.travel.fixtures.transport import FixtureTravelTransport

FIXTURES = Path(__file__).parent.parent / "gateway" / "travel" / "fixtures" / "data"


def _transport() -> FixtureTravelTransport:
    return FixtureTravelTransport(FIXTURES, now=lambda: datetime(2026, 8, 1, tzinfo=UTC))


def test_success_fixture_loads_and_carries_source_method() -> None:
    envelope = _transport().load("flight_success")
    assert envelope["_fixture_meta"]["source_method"] == "sample"
    assert envelope["_fixture_meta"]["status"] != "live"
    assert envelope["results"]


def test_empty_fixture_is_a_successful_empty_result() -> None:
    envelope = _transport().load("flight_empty")
    assert envelope["results"] == []


def test_malformed_fixture_raises_invalid_response() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_malformed")
    assert exc_info.value.code == "invalid_response"


def test_partial_price_fixture_marks_completeness() -> None:
    envelope = _transport().load("flight_partial_price")
    assert envelope["results"]
    assert envelope["results"][0]["completeness"] in {
        "taxes_uncertain",
        "fees_uncertain",
        "partial",
    }


def test_stale_fixture_status_is_stale() -> None:
    envelope = _transport().load("flight_stale")
    assert envelope["_fixture_meta"]["status"] == "stale"


def test_rate_limited_fixture_raises_rate_limited() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_rate_limited")
    assert exc_info.value.code == "rate_limited"


def test_auth_failed_fixture_raises_authentication_failed() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_auth_failed")
    assert exc_info.value.code == "authentication_failed"


def test_timeout_fixture_raises_timeout() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_timeout")
    assert exc_info.value.code == "timeout"


def test_fixture_cannot_claim_live_status(tmp_path: Path) -> None:
    data = json.loads((FIXTURES / "flight_success.json").read_text())
    data["_fixture_meta"]["status"] = "live"
    (tmp_path / "claims_live.json").write_text(json.dumps(data))
    transport = FixtureTravelTransport(tmp_path, now=lambda: datetime(2026, 8, 1, tzinfo=UTC))
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.load("claims_live")
    assert exc_info.value.code == "invalid_response"


def test_no_network_socket_is_never_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FixtureTravelTransport must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    _transport().load("flight_success")


def test_payload_size_is_bounded(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_text(
        json.dumps(
            {
                "_fixture_meta": {"status": "estimated", "source_method": "sample"},
                "results": ["x" * 600_000],
            }
        )
    )
    transport = FixtureTravelTransport(tmp_path, now=lambda: datetime(2026, 8, 1, tzinfo=UTC))
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.load("huge")
    assert exc_info.value.code == "invalid_response"


def test_no_credentials_are_read_by_transport() -> None:
    import inspect

    from gateway.travel.fixtures import transport as transport_module

    source = inspect.getsource(transport_module)
    assert "os.environ" not in source
    assert "getenv" not in source
