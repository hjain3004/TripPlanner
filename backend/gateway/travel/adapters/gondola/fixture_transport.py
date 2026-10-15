"""Fixture transport for Gondola — the only transport wired by default.

Reuses G1's ``FixtureTravelTransport`` envelope (512KB payload bound,
"cannot claim live" rejection, error-code mapping) by pointing it at this
adapter's own fixture directory, rather than reimplementing the same
envelope-parsing logic. Every call passes through the static tool policy
before a fixture is even loaded, so an unrecognized or denied tool name
never reaches disk I/O.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from gateway.travel.adapters.gondola.discovery import (
    DiscoveryTool,
    GondolaDiscoveryEvidence,
    parse_markdown_discovery,
)
from gateway.travel.adapters.gondola.tool_policy import assert_tool_allowed
from gateway.travel.fixtures.transport import FixtureTravelTransport

GONDOLA_FIXTURES_DIR = Path(__file__).parent / "fixtures"


class FixtureGondolaTransport:
    def __init__(self, fixture_dir: Path | None = None, *, now: Callable[[], datetime]) -> None:
        self._inner = FixtureTravelTransport(fixture_dir or GONDOLA_FIXTURES_DIR, now=now)

    def call_tool(self, tool_name: str, fixture_name: str) -> dict[str, Any]:
        assert_tool_allowed(tool_name)
        return self._inner.load(fixture_name)

    def load_discovery(
        self, tool_name: DiscoveryTool, fixture_name: str
    ) -> GondolaDiscoveryEvidence:
        assert_tool_allowed(tool_name)
        payload = self._inner.load(fixture_name)
        # The captured contract fixture keeps hotel and flight excerpts under
        # separate top-level keys so one file can replay both searches.
        if "result" not in payload:
            branch = payload.get("hotel" if tool_name == "search_hotels" else "flight")
            if isinstance(branch, dict) and isinstance(branch.get("excerpt"), dict):
                payload = branch["excerpt"]
        return parse_markdown_discovery(payload, tool=tool_name, now=self._inner.now())
