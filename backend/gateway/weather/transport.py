"""Weather transports — replay transport and the transport contract (G4).

``WeatherToolTransport`` is the single seam between the adapter and an MCP
server. Two implementations exist:

* ``FixtureWeatherTransport`` (this module) — deterministic replay of
  committed, clearly labelled fixtures. Never opens a socket, subprocess, or
  the wall clock. A fixture that claims ``status="live"`` is refused, and the
  evidence origin always reflects what the fixture really is
  (``fixture_synthetic`` for authored data, ``fixture_captured`` only for a
  sanitized capture of real provider output).
* ``StdioWeatherTransport`` (``stdio_transport.py``) — a real MCP client over
  stdio to a fixed, pinned server, disabled by default.

Both validate the call against the frozen tool policy *before* doing anything
else, so a forbidden tool or an out-of-policy argument never reaches a fixture
read or a server.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from gateway.weather.contracts import MAX_RESPONSE_BYTES, EvidenceOrigin
from gateway.weather.errors import ErrorCode, WeatherGatewayError
from gateway.weather.tool_policy import (
    CLIMATE_TOOL,
    FORECAST_TOOL,
    HISTORICAL_TOOL,
    validate_tool_call,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_TOOL_SHORT = {FORECAST_TOOL: "forecast", HISTORICAL_TOOL: "historical", CLIMATE_TOOL: "climate"}
_SCENARIO_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_FIXTURE_ORIGINS: dict[str, EvidenceOrigin] = {
    "authored_synthetic": "fixture_synthetic",
    "sanitized_capture": "fixture_captured",
}
_REPLAYABLE_ERRORS: frozenset[str] = frozenset(
    {"rate_limited", "timeout", "provider_unavailable", "invalid_response", "permission_denied"}
)


@dataclass(frozen=True)
class ToolResult:
    """The unwrapped native payload of one tool call plus what produced it."""

    payload: Any
    origin: EvidenceOrigin


class WeatherToolTransport(Protocol):
    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult: ...


class FixtureWeatherTransport:
    def __init__(self, scenario: str, *, fixture_dir: Path | None = None) -> None:
        if not _SCENARIO_RE.fullmatch(scenario):
            raise WeatherGatewayError("invalid_request", "fixture scenario name is not permitted")
        self._scenario = scenario
        self._dir = fixture_dir or FIXTURES_DIR

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        validate_tool_call(tool_name, arguments)
        path = self._dir / f"{self._scenario}.{_TOOL_SHORT[tool_name]}.json"
        if not path.is_file():
            raise WeatherGatewayError("provider_unavailable", "no replay fixture for this call")
        raw = path.read_bytes()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise WeatherGatewayError("invalid_response", "fixture exceeds the response bound")
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise WeatherGatewayError("invalid_response", "fixture is not valid JSON") from exc
        if not isinstance(envelope, dict):
            raise WeatherGatewayError("invalid_response", "fixture envelope is not an object")

        meta = envelope.get("_fixture_meta")
        if not isinstance(meta, dict):
            raise WeatherGatewayError("invalid_response", "fixture lacks _fixture_meta")
        if meta.get("status") == "live":
            raise WeatherGatewayError("invalid_response", "a fixture may never claim status=live")
        declared = meta.get("origin")
        if declared not in _FIXTURE_ORIGINS:
            raise WeatherGatewayError("invalid_response", "fixture origin is not recognised")
        if declared == "sanitized_capture" and not all(
            meta.get(k) for k in ("captured_at", "upstream_version", "sanitization")
        ):
            raise WeatherGatewayError(
                "invalid_response", "a captured fixture must record how and when it was captured"
            )
        if envelope.get("tool") != tool_name:
            raise WeatherGatewayError("invalid_response", "fixture was recorded for another tool")

        error = envelope.get("error")
        if error is not None:
            code = error.get("code") if isinstance(error, dict) else None
            if code not in _REPLAYABLE_ERRORS:
                raise WeatherGatewayError("invalid_response", "fixture error is not replayable")
            replay_code: ErrorCode = code
            raise WeatherGatewayError(replay_code, f"simulated {code} from replay fixture")
        if "payload" not in envelope:
            raise WeatherGatewayError("invalid_response", "fixture carries no payload")
        return ToolResult(payload=envelope["payload"], origin=_FIXTURE_ORIGINS[declared])
