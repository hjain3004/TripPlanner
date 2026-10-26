"""Live OpenBnB transport: a narrowly allowlisted stdio MCP boundary. NEVER ACTIVE.

Nothing in this repository constructs this transport outside tests, and the tests only
ever drive it through an injected fake session. It exists so the future live path is
reviewed now, not improvised later. What it enforces before any process could start:

* **Recorded human approval.** Construction requires a ``LiveActivationApproval``; without
  one it raises ``terms_disabled``. Airbnb's Terms of Service (section 11.1, updated
  2026-02-05) prohibit bots, crawlers and scrapers, and OpenBnB is exactly such a scraper,
  so this adapter is not eligible by default and no agent may grant itself that approval.
* **A fixed launch.** ``node <absolute path>/dist/index.js`` of an already-installed,
  version-pinned server. Never ``npx`` (which would download code at call time), never a
  shell, never extra arguments -- in particular never ``--ignore-robots-txt``. The child
  environment pins ``IGNORE_ROBOTS_TXT=false`` and states the geocoding choice explicitly.
* **The two read tools only,** with the reviewed argument keys only (``tool_policy``), no
  ``tools/list`` discovery, no URL or tool name taken from provider output.
* **Bounds:** one total timeout, a payload byte bound, and a server name/version check
  after ``initialize``.

Known limits that code cannot fix (see ``reports/g3b_openbnb_offline.md``): upstream's
robots.txt handling fails *open* when robots.txt cannot be fetched or parsed, and with
geocoding enabled it sends the location text to Photon/Nominatim.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from gateway.travel.adapters.openbnb.contracts import MAX_PAYLOAD_BYTES
from gateway.travel.adapters.openbnb.fixture_transport import OpenBnBToolResult
from gateway.travel.adapters.openbnb.normalize import provider_error
from gateway.travel.adapters.openbnb.tool_policy import validate_tool_arguments
from gateway.travel.errors import TravelGatewayError

if TYPE_CHECKING:  # pragma: no cover - typing only; the SDK is imported lazily at launch
    from mcp import StdioServerParameters

SERVER_COMMAND = "node"
EXPECTED_SERVER_NAME = "airbnb"
PINNED_SERVER_VERSION = "0.3.0"
TOTAL_TIMEOUT_S = 25.0


@dataclass(frozen=True)
class OpenBnBServerConfig:
    """Where the already-installed, pinned upstream server lives."""

    entrypoint: Path
    expected_version: str = PINNED_SERVER_VERSION
    geocoding: Literal["disabled", "third_party"] = "disabled"

    def __post_init__(self) -> None:
        path = self.entrypoint
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path.name != "index.js"
            or path.parent.name != "dist"
        ):
            raise TravelGatewayError(
                "permission_denied",
                "OpenBnB entrypoint must be an absolute path to <install>/dist/index.js",
            )
        if not self.expected_version.strip():
            raise TravelGatewayError("permission_denied", "OpenBnB server version must be pinned")


@dataclass(frozen=True)
class LiveActivationApproval:
    """A human's recorded decision to allow low-volume local/demo use.

    Constructing one is a statement that a person reviewed the current Airbnb terms and the
    spec 16 student-profile checklist. No code in this repository constructs one.
    """

    reviewer: str
    approved_on: date
    terms_snapshot_ref: str
    scope: Literal["local_demo_low_volume"] = "local_demo_low_volume"

    def __post_init__(self) -> None:
        if not (self.reviewer.strip() and self.terms_snapshot_ref.strip()):
            raise TravelGatewayError(
                "terms_disabled", "an activation approval names a reviewer and a terms snapshot"
            )


def build_server_parameters(config: OpenBnBServerConfig) -> StdioServerParameters:
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=SERVER_COMMAND,
        args=[str(config.entrypoint)],  # no flags: never --ignore-robots-txt
        env={
            "NODE_ENV": "production",
            "IGNORE_ROBOTS_TXT": "false",
            "DISABLE_GEOCODING": "true" if config.geocoding == "disabled" else "false",
        },
    )


class _Session(Protocol):
    async def initialize(self) -> Any: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any: ...


SessionFactory = Callable[[Any], AbstractAsyncContextManager[_Session]]


@asynccontextmanager
async def _default_session(params: Any):  # type: ignore[no-untyped-def]  # pragma: no cover
    entrypoint = Path(params.args[0])
    if not entrypoint.is_file():
        raise TravelGatewayError("provider_unavailable", "OpenBnB server is not installed")
    from mcp import ClientSession
    from mcp.client.stdio import stdio_client

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            yield session


def _check_server(initialized: Any, expected_version: str) -> None:
    info = getattr(initialized, "serverInfo", None) or getattr(initialized, "server_info", None)
    if (
        getattr(info, "name", None) != EXPECTED_SERVER_NAME
        or getattr(info, "version", None) != expected_version
    ):
        raise TravelGatewayError(
            "invalid_response", "OpenBnB server identity or version is not the pinned one"
        )


def unwrap_tool_result(result: Any) -> dict[str, Any]:
    """The tool's JSON payload from an MCP result envelope, bounded and typed.

    Upstream returns one JSON text block; ``isError`` results carry an ``{"error": ...}``
    object whose text is classified, never echoed.
    """
    text: str | None = None
    for block in getattr(result, "content", None) or []:
        candidate = getattr(block, "text", None)
        if isinstance(candidate, str):
            text = candidate
            break
    if text is None:
        raise TravelGatewayError("invalid_response", "OpenBnB result has no text content")
    if len(text.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise TravelGatewayError(
            "invalid_response", f"OpenBnB response exceeds {MAX_PAYLOAD_BYTES} byte bound"
        )
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise TravelGatewayError("invalid_response", "OpenBnB result is not valid JSON") from None
    if not isinstance(parsed, dict):
        raise TravelGatewayError("invalid_response", "OpenBnB result is not a JSON object")
    flagged = getattr(result, "isError", getattr(result, "is_error", False))
    if flagged is True:
        raise provider_error(parsed.get("error"))
    return parsed


class StdioOpenBnBTransport:
    def __init__(
        self,
        config: OpenBnBServerConfig,
        *,
        approval: LiveActivationApproval | None,
        session_factory: SessionFactory | None = None,
        total_timeout_s: float = TOTAL_TIMEOUT_S,
    ) -> None:
        if approval is None:
            raise TravelGatewayError(
                "terms_disabled",
                "OpenBnB live transport needs a recorded human approval; Airbnb's terms "
                "prohibit automated access",
            )
        self._config = config
        self._approval = approval
        self._session_factory: SessionFactory = session_factory or _default_session
        self._timeout = total_timeout_s

    async def call_tool(self, tool_name: str, arguments: Mapping[str, Any]) -> OpenBnBToolResult:
        validated = validate_tool_arguments(tool_name, arguments)  # before any process starts
        params = build_server_parameters(self._config)
        try:
            async with asyncio.timeout(self._timeout):
                async with self._session_factory(params) as session:
                    _check_server(await session.initialize(), self._config.expected_version)
                    result = await session.call_tool(tool_name, validated)
                    payload = unwrap_tool_result(result)
        except TravelGatewayError:
            raise
        except TimeoutError:
            raise TravelGatewayError("timeout", "OpenBnB call exceeded the total timeout") from None
        except Exception:
            raise TravelGatewayError("provider_unavailable", "OpenBnB server call failed") from None
        return OpenBnBToolResult(payload=payload, origin="openbnb_stdio_live")
