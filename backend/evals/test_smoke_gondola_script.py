"""Offline safety tests for backend/scripts/smoke_gondola.py. The script
itself makes real, bounded network calls and is never executed by the
normal test suite (matching the parent milestone's explicit "never
invoked automatically by an agent" instruction). These tests exercise its
gate logic and static structure only -- no socket is ever opened.
"""

from __future__ import annotations

import inspect
import socket
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).parent.parent
SCRIPT_PATH = BACKEND / "scripts" / "smoke_gondola.py"

sys.path.insert(0, str(BACKEND / "scripts"))
import smoke_gondola as smoke  # noqa: E402


def _source() -> str:
    return inspect.getsource(smoke)


def test_missing_acknowledge_flag_exits_nonzero_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("require_gates must never touch a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    with pytest.raises(SystemExit) as exc_info:
        smoke.require_gates(acknowledged=False)
    assert exc_info.value.code == 2


def test_acknowledge_flag_without_env_var_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(smoke.LIVE_SMOKE_ENV_VAR, raising=False)
    with pytest.raises(SystemExit) as exc_info:
        smoke.require_gates(acknowledged=True)
    assert exc_info.value.code == 2


def test_both_gates_present_does_not_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(smoke.LIVE_SMOKE_ENV_VAR, "1")
    smoke.require_gates(acknowledged=True)  # must not raise


def test_call_budget_ceiling_is_two_per_exercise_phase() -> None:
    from gateway.travel.adapters.gondola.budget import CALLS_PER_PLAN

    assert CALLS_PER_PLAN == 2


def test_never_prints_a_raw_token_or_authorization_header() -> None:
    source = _source()
    assert "print(tokens.access_token" not in source
    assert 'print(f"Authorization' not in source
    assert "Bearer {" not in source  # header construction lives only in mcp_client.py


def test_never_prints_a_full_raw_mcp_response() -> None:
    source = _source()
    assert "print(result)" not in source
    assert 'print(f"{result}")' not in source


def test_uses_only_the_existing_gondola_transport_never_raw_http() -> None:
    source = _source()
    assert "LiveGondolaTransport" in source
    assert "requests.get" not in source
    assert "urllib.request" not in source
    assert "httpx2.get(" not in source
    assert "httpx2.AsyncClient(" not in source  # only mcp_client.py constructs the http client


def test_uses_the_static_tool_policy_reuse_not_a_new_allowlist() -> None:
    source = _source()
    assert "from gateway.travel.adapters.gondola.tool_policy import" in source


def test_never_calls_a_booking_mutation_or_payment_tool() -> None:
    source = _source()
    for forbidden in (
        '"book_hotel"',
        '"book_vehicle"',
        '"cancel_vehicle_booking"',
        '"get_payment_methods"',
        '"create_rate_alert"',
        '"delete_rate_alert"',
        '"update_traveler_profile"',
    ):
        assert f"call_tool({forbidden}" not in source


def test_script_requires_exactly_mcp_read_scope_for_authenticated_phase() -> None:
    source = _source()
    assert "REQUIRED_SCOPE" in source
    assert "tokens.scope != REQUIRED_SCOPE" in source


def test_script_is_never_imported_by_core_accounts_agents_or_api() -> None:
    for package in ("core", "accounts", "agents", "api"):
        for py_file in (BACKEND / package).rglob("*.py"):
            content = py_file.read_text()
            assert "smoke_gondola" not in content


def test_extract_travel_gateway_error_finds_plain_error() -> None:
    from gateway.travel.errors import TravelGatewayError

    err = TravelGatewayError("invalid_response", "boom")
    assert smoke.extract_travel_gateway_error(err) is err


def test_extract_travel_gateway_error_unwraps_exception_group() -> None:
    # Reproduces exactly what anyio's task group raised live (G3.2): a
    # BaseExceptionGroup wrapping the real TravelGatewayError, which a plain
    # `except TravelGatewayError` clause does not match.
    from gateway.travel.errors import TravelGatewayError

    inner = TravelGatewayError("invalid_response", "Gondola tool call returned isError=true")
    group = BaseExceptionGroup("unhandled errors in a TaskGroup", [inner])
    found = smoke.extract_travel_gateway_error(group)
    assert found is inner


def test_extract_travel_gateway_error_returns_none_for_unrelated_exception() -> None:
    assert smoke.extract_travel_gateway_error(ValueError("unrelated")) is None


def test_script_is_not_collected_by_pytest_testpaths() -> None:
    import tomllib

    pyproject = tomllib.loads((BACKEND / "pyproject.toml").read_text())
    testpaths = pyproject["tool"]["pytest"]["ini_options"]["testpaths"]
    assert testpaths == ["evals"]
    assert "scripts" not in testpaths
