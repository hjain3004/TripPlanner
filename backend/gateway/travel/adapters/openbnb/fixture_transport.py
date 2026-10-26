"""Fixture transport for OpenBnB -- the only transport the adapter is tested with.

Defines the small ``OpenBnBTransport`` protocol the adapter depends on (so the adapter never
imports an MCP SDK or a subprocess helper) and a replay implementation that reuses G1's
``FixtureTravelTransport`` envelope handling (payload bound, "cannot claim live", typed
error envelopes). Every call passes the static tool/argument policy *before* a fixture is
looked up, exactly as the live transport must.

Fixture files are synthetic: they follow the key paths upstream's source copies but no
leaf value was captured from a live listing. They can never carry live origin.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from gateway.travel.adapters.openbnb.tool_policy import (
    DETAIL_TOOL,
    SEARCH_TOOL,
    validate_tool_arguments,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.fixtures.transport import FixtureTravelTransport

OPENBNB_FIXTURES_DIR = Path(__file__).parent / "fixtures"
Origin = Literal["synthetic_fixture", "openbnb_stdio_live"]
_FIXTURE_NAME = re.compile(r"[a-z0-9_]{1,80}")
DEFAULT_FIXTURES: dict[str, str] = {
    SEARCH_TOOL: "search_success",
    DETAIL_TOOL: "details_success",
}


@dataclass(frozen=True)
class OpenBnBToolResult:
    """A tool's native JSON payload and where it truthfully came from."""

    payload: dict[str, Any]
    origin: Origin


class OpenBnBTransport(Protocol):
    async def call_tool(
        self, tool_name: str, arguments: Mapping[str, Any]
    ) -> OpenBnBToolResult: ...


class FixtureOpenBnBTransport:
    def __init__(
        self,
        fixtures: Mapping[str, str] | None = None,
        *,
        now: Callable[[], datetime],
        fixture_dir: Path | None = None,
    ) -> None:
        chosen = dict(DEFAULT_FIXTURES if fixtures is None else fixtures)
        for name in chosen.values():
            if not _FIXTURE_NAME.fullmatch(name):
                raise ValueError(f"fixture name {name!r} is not a plain identifier")
        self._fixtures = chosen
        self._inner = FixtureTravelTransport(fixture_dir or OPENBNB_FIXTURES_DIR, now=now)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> OpenBnBToolResult:
        validated = validate_tool_arguments(tool_name, arguments)  # policy before any I/O
        self.calls.append((tool_name, validated))
        name = self._fixtures.get(tool_name)
        if name is None:
            raise TravelGatewayError(
                "unsupported_domain", f"no fixture is configured for {tool_name}"
            )
        envelope = self._inner.load(name)
        meta = envelope.get("_fixture_meta", {})
        if not isinstance(meta, dict) or meta.get("origin") != "synthetic_fixture":
            raise TravelGatewayError(
                "invalid_response", f"fixture {name} does not declare synthetic origin"
            )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise TravelGatewayError("invalid_response", f"fixture {name} has no payload object")
        return OpenBnBToolResult(payload=payload, origin="synthetic_fixture")
