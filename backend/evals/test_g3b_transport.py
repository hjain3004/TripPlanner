"""Fixture replay and the (never-active) stdio boundary: policy first, nothing launched."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from evals.g3b_support import request
from gateway.travel.adapters.openbnb.budget import OpenBnBCallBudget
from gateway.travel.adapters.openbnb.contracts import MAX_PAYLOAD_BYTES
from gateway.travel.adapters.openbnb.fixture_transport import (
    OPENBNB_FIXTURES_DIR,
    FixtureOpenBnBTransport,
)
from gateway.travel.adapters.openbnb.mcp_client import (
    LiveActivationApproval,
    OpenBnBServerConfig,
    StdioOpenBnBTransport,
    build_server_parameters,
    unwrap_tool_result,
)
from gateway.travel.adapters.openbnb.requests import build_search_arguments
from gateway.travel.errors import TravelGatewayError

NOW = datetime(2026, 10, 26, tzinfo=UTC)
ENTRY = Path("/opt/openbnb/node_modules/@openbnb/mcp-server-airbnb/dist/index.js")
APPROVAL = LiveActivationApproval(
    reviewer="test-reviewer", approved_on=date(2026, 10, 26), terms_snapshot_ref="synthetic-test"
)


def _search_args() -> dict[str, Any]:
    return build_search_arguments(request())


def _fixture(name: str | None = None, tool: str = "airbnb_search") -> FixtureOpenBnBTransport:
    fixtures = {tool: name} if name else None
    return FixtureOpenBnBTransport(fixtures, now=lambda: NOW)


# --------------------------------------------------------------------------- #
# Fixture transport
# --------------------------------------------------------------------------- #


def test_a_fixture_call_returns_the_payload_with_synthetic_origin() -> None:
    transport = _fixture()
    result = asyncio.run(transport.call_tool("airbnb_search", _search_args()))
    assert result.origin == "synthetic_fixture"
    assert result.payload["searchResults"]
    assert [name for name, _ in transport.calls] == ["airbnb_search"]


@pytest.mark.parametrize("tool", ["book_listing", "message_host", "tools/list", ""])
def test_a_forbidden_tool_is_refused_before_any_fixture_is_loaded(tool: str) -> None:
    transport = _fixture()
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(transport.call_tool(tool, _search_args()))
    assert raised.value.code == "permission_denied"
    assert transport.calls == []


def test_the_robots_override_argument_is_refused_before_any_fixture_is_loaded() -> None:
    transport = _fixture()
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(
            transport.call_tool("airbnb_search", {**_search_args(), "ignoreRobotsText": True})
        )
    assert raised.value.code == "permission_denied"
    assert transport.calls == []


@pytest.mark.parametrize(
    ("fixture", "code"),
    [("error_rate_limited", "rate_limited"), ("error_timeout", "timeout")],
)
def test_typed_error_fixtures_surface_their_code(fixture: str, code: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(_fixture(fixture).call_tool("airbnb_search", _search_args()))
    assert raised.value.code == code


@pytest.mark.parametrize("fixture", ["fixture_claims_live", "fixture_wrong_origin"])
def test_a_fixture_can_never_claim_live_status_or_origin(fixture: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(_fixture(fixture).call_tool("airbnb_search", _search_args()))
    assert raised.value.code == "invalid_response"


def test_fixture_names_are_plain_identifiers_never_paths() -> None:
    with pytest.raises(ValueError):
        FixtureOpenBnBTransport({"airbnb_search": "../../etc/passwd"}, now=lambda: NOW)


def test_a_tool_without_a_configured_fixture_is_unsupported() -> None:
    transport = FixtureOpenBnBTransport({}, now=lambda: NOW)
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(transport.call_tool("airbnb_search", _search_args()))
    assert raised.value.code == "unsupported_domain"


def test_every_shipped_fixture_is_synthetic_and_says_so() -> None:
    files = sorted(OPENBNB_FIXTURES_DIR.glob("*.json"))
    assert len(files) >= 10
    for path in files:
        envelope = json.loads(path.read_text())
        assert "synthetic" in envelope["_fixture_provenance"], path.name
        assert (
            envelope["_fixture_meta"].get("status") != "live"
            or path.name == "fixture_claims_live.json"
        )
        assert path.stat().st_size < 50_000


# --------------------------------------------------------------------------- #
# Stdio boundary (never launches anything here)
# --------------------------------------------------------------------------- #


def test_the_live_transport_cannot_be_built_without_a_recorded_human_approval() -> None:
    with pytest.raises(TravelGatewayError) as raised:
        StdioOpenBnBTransport(OpenBnBServerConfig(ENTRY), approval=None)
    assert raised.value.code == "terms_disabled"


@pytest.mark.parametrize("reviewer", ["", "   "])
def test_an_approval_must_name_a_reviewer(reviewer: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        LiveActivationApproval(
            reviewer=reviewer, approved_on=date(2026, 10, 26), terms_snapshot_ref="x"
        )
    assert raised.value.code == "terms_disabled"


@pytest.mark.parametrize(
    "entrypoint",
    [
        Path("dist/index.js"),  # relative
        Path("/opt/x/../etc/dist/index.js"),
        Path("/opt/openbnb/dist/other.js"),
        Path("/opt/openbnb/src/index.js"),
        Path("/usr/bin/npx"),
    ],
)
def test_the_server_entrypoint_must_be_an_absolute_installed_dist_index(entrypoint: Path) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        OpenBnBServerConfig(entrypoint)
    assert raised.value.code == "permission_denied"


def test_the_launch_is_a_fixed_node_command_with_no_flags_and_robots_respected() -> None:
    params = build_server_parameters(OpenBnBServerConfig(ENTRY))
    assert params.command == "node"
    assert params.args == [str(ENTRY)]
    assert all("robots" not in arg for arg in params.args)
    assert params.env is not None
    assert params.env["IGNORE_ROBOTS_TXT"] == "false"
    assert params.env["DISABLE_GEOCODING"] == "true"  # no third-party egress by default
    third_party = build_server_parameters(OpenBnBServerConfig(ENTRY, geocoding="third_party"))
    assert third_party.env is not None and third_party.env["DISABLE_GEOCODING"] == "false"


class _Session:
    def __init__(
        self,
        result: Any = None,
        *,
        name: str = "airbnb",
        version: str = "0.3.0",
        delay: float = 0.0,
        raises: Exception | None = None,
    ) -> None:
        self._result = result
        self._info = SimpleNamespace(name=name, version=version)
        self._delay = delay
        self._raises = raises
        self.calls: list[str] = []

    async def initialize(self) -> Any:
        self.calls.append("initialize")
        return SimpleNamespace(serverInfo=self._info)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append(f"call_tool:{name}")
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._raises:
            raise self._raises
        return self._result


def _result(payload: Any, *, is_error: bool = False, raw: str | None = None) -> Any:
    text = raw if raw is not None else json.dumps(payload)
    return SimpleNamespace(content=[SimpleNamespace(text=text)], isError=is_error)


def _transport(
    session: _Session, launched: list[Any], timeout: float = 5.0
) -> StdioOpenBnBTransport:
    @asynccontextmanager
    async def factory(params: Any) -> AsyncIterator[_Session]:
        launched.append(params)
        yield session

    return StdioOpenBnBTransport(
        OpenBnBServerConfig(ENTRY),
        approval=APPROVAL,
        session_factory=factory,
        total_timeout_s=timeout,
    )


def test_an_allowed_call_goes_through_one_session_and_is_labelled_live_origin() -> None:
    launched: list[Any] = []
    session = _Session(_result({"searchUrl": "x", "searchResults": []}))
    result = asyncio.run(_transport(session, launched).call_tool("airbnb_search", _search_args()))
    assert result.origin == "openbnb_stdio_live"
    assert result.payload == {"searchUrl": "x", "searchResults": []}
    assert session.calls == ["initialize", "call_tool:airbnb_search"]  # no tools/list discovery
    assert len(launched) == 1


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("book_listing", {}),
        ("airbnb_search", {"location": "Singapore", "ignoreRobotsText": True}),
        ("airbnb_search", {"location": "Singapore", "placeId": "x"}),
        ("airbnb_listing_details", {"id": "../1"}),
    ],
)
def test_policy_violations_never_launch_a_process(tool: str, arguments: dict[str, Any]) -> None:
    launched: list[Any] = []
    session = _Session(_result({}))
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(_transport(session, launched).call_tool(tool, arguments))
    assert raised.value.code in {"permission_denied", "invalid_response"}
    assert launched == [] and session.calls == []


@pytest.mark.parametrize(
    ("name", "version"), [("evil", "0.3.0"), ("airbnb", "9.9.9"), ("airbnb", "")]
)
def test_an_unexpected_server_identity_or_version_is_rejected(name: str, version: str) -> None:
    session = _Session(_result({"searchResults": []}), name=name, version=version)
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(_transport(session, []).call_tool("airbnb_search", _search_args()))
    assert raised.value.code == "invalid_response"
    assert session.calls == ["initialize"]  # the tool was never called


def test_an_error_result_is_classified_without_echoing_provider_text() -> None:
    text = "This path is disallowed by Airbnb's robots.txt"
    session = _Session(_result({"error": text}, is_error=True))
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(_transport(session, []).call_tool("airbnb_search", _search_args()))
    assert raised.value.code == "permission_denied"
    assert text not in str(raised.value)


def test_the_total_timeout_is_enforced() -> None:
    session = _Session(_result({}), delay=1.0)
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(
            _transport(session, [], timeout=0.05).call_tool("airbnb_search", _search_args())
        )
    assert raised.value.code == "timeout"


def test_an_arbitrary_session_failure_is_a_generic_unavailable_error() -> None:
    session = _Session(raises=RuntimeError("secret path /Users/someone/key"))
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(_transport(session, []).call_tool("airbnb_search", _search_args()))
    assert raised.value.code == "provider_unavailable"
    assert "secret" not in str(raised.value) and "/Users" not in str(raised.value)


@pytest.mark.parametrize(
    "result",
    [
        SimpleNamespace(content=[], isError=False),
        SimpleNamespace(content=[SimpleNamespace(text=None)], isError=False),
        SimpleNamespace(content=None, isError=False),
        _result(None, raw="not json"),
        _result(None, raw="[1, 2]"),
        _result(None, raw=json.dumps({"x": "y" * (MAX_PAYLOAD_BYTES + 1)})),
    ],
)
def test_malformed_or_oversized_results_are_invalid_responses(result: Any) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        unwrap_tool_result(result)
    assert raised.value.code == "invalid_response"


def test_the_default_session_factory_is_never_used_by_the_tests() -> None:
    # Injecting a factory is the only way these tests drive the transport; this guards the
    # contract that a missing install fails closed instead of reaching for a process.
    transport = StdioOpenBnBTransport(
        OpenBnBServerConfig(ENTRY), approval=APPROVAL, total_timeout_s=1.0
    )
    with pytest.raises(TravelGatewayError) as raised:
        asyncio.run(transport.call_tool("airbnb_search", _search_args()))
    assert raised.value.code == "provider_unavailable"  # ENTRY does not exist on this machine


def test_call_budget_is_independent_per_plan_and_has_a_lifetime_ceiling() -> None:
    budget = OpenBnBCallBudget(calls_per_plan=2, total_ceiling=3)
    assert [budget.reserve_call("a") for _ in range(3)] == [True, True, False]
    assert budget.reserve_call("b") is True
    assert budget.reserve_call("b") is False  # lifetime ceiling of 3 reached
    assert budget.total_calls() == 3
