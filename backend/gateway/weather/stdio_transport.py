"""Real MCP transport for the weather adapter: a stdio client to one fixed server.

This is the *only* module in the package that starts a process or speaks the
MCP wire protocol, and it does so exclusively through the official ``mcp``
SDK's stdio client — there are no hand-rolled HTTP calls anywhere in the
package.

What is fixed, and enforced here rather than trusted:

* the executable and entrypoint — built only by ``pinned_upstream_launch``,
  which refuses a tree that does not match the audited lockfile hash, the
  pinned package name/version/licence, or that resolves outside the install
  root;
* the environment — a minimal, code-owned set (official base URLs, storage
  features off). The SDK adds only a tiny default allowlist (HOME/PATH/...),
  so nothing secret is inherited from the parent process;
* the tool set and arguments — ``validate_tool_call`` runs before any process
  is started, so a forbidden tool or out-of-policy argument never leaves this
  process;
* the server identity — checked after ``initialize`` and *before* any tool
  call is sent;
* size and time — response bytes are bounded, the whole call (spawn,
  handshake, call) runs under one deadline, and the process is torn down on
  exit.

Evidence is stamped ``origin="live"`` only for the pinned upstream launch. Any
other launch (the offline MCP test double) can only produce
``fixture_synthetic`` evidence, so test data can never be mistaken for live.
No dynamic discovery: ``tools/list`` is never called.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession, types
from mcp.client.stdio import StdioServerParameters, stdio_client

from gateway.weather.contracts import (
    MAX_RESPONSE_BYTES,
    UPSTREAM_SERVER_NAME,
    UPSTREAM_SERVER_VERSION,
    EvidenceOrigin,
)
from gateway.weather.errors import ErrorCode, WeatherGatewayError
from gateway.weather.sanitize import sanitize_provider_text
from gateway.weather.tool_policy import validate_tool_call
from gateway.weather.transport import ToolResult
from gateway.weather.upstream_pin import (
    AUDITED_LOCKFILE_SHA256,
    FIXED_SERVER_ENV,
    OFFICIAL_BASE_URLS,
    UPSTREAM_LICENSE,
    UPSTREAM_PACKAGE,
    UPSTREAM_VERSION,
)

DEFAULT_TOTAL_TIMEOUT_S = 12.0  # spawn + handshake + call (spec 16: total <= 12s)
_SECRET_KEY_RE = re.compile(r"(?i)(key|token|secret|passw|credential|auth)")


@dataclass(frozen=True)
class ServerLaunch:
    command: str
    args: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()
    expected_server_name: str = UPSTREAM_SERVER_NAME
    expected_server_version: str = UPSTREAM_SERVER_VERSION
    # True only when built by ``pinned_upstream_launch``.
    is_pinned_upstream: bool = False


def _refuse(message: str) -> WeatherGatewayError:
    return WeatherGatewayError("permission_denied", message)


def pinned_upstream_launch(install_root: Path, node_executable: Path) -> ServerLaunch:
    """Build the one approved launch of the audited upstream server.

    ``install_root`` is an out-of-repo directory provisioned with
    ``npm ci --ignore-scripts`` from the audited lockfile (see the G4 report).
    """
    if not install_root.is_absolute() or not node_executable.is_absolute():
        raise WeatherGatewayError("invalid_request", "launch paths must be absolute")
    root = install_root.resolve()
    node = node_executable.resolve()
    if not root.is_dir() or not node.is_file() or not os.access(node, os.X_OK):
        raise _refuse("the install root or node executable is missing")

    lockfile = root / "package-lock.json"
    if not lockfile.is_file() or (
        hashlib.sha256(lockfile.read_bytes()).hexdigest() != AUDITED_LOCKFILE_SHA256
    ):
        raise _refuse("the install does not match the audited lockfile")

    pkg_dir = (root / "node_modules" / UPSTREAM_PACKAGE).resolve()
    if not pkg_dir.is_relative_to(root) or not pkg_dir.is_dir():
        raise _refuse("the pinned server package is not installed under the install root")
    try:
        manifest = json.loads((pkg_dir / "package.json").read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise _refuse("the pinned server package manifest is unreadable") from exc
    if (
        manifest.get("name") != UPSTREAM_PACKAGE
        or manifest.get("version") != UPSTREAM_VERSION
        or manifest.get("license") != UPSTREAM_LICENSE
    ):
        raise _refuse("the installed server is not the pinned package/version/licence")

    entry = (pkg_dir / "dist" / "index.js").resolve()
    if not entry.is_relative_to(pkg_dir) or not entry.is_file():
        raise _refuse("the pinned server entrypoint is missing")

    return ServerLaunch(
        command=str(node),
        args=(str(entry),),
        env=tuple(sorted(FIXED_SERVER_ENV.items())),
        is_pinned_upstream=True,
    )


def _assert_launch_safe(launch: ServerLaunch) -> None:
    if not os.path.isabs(launch.command):
        raise _refuse("the server command must be an absolute path")
    env = dict(launch.env)
    for key, value in env.items():
        if key in OFFICIAL_BASE_URLS and value != OFFICIAL_BASE_URLS[key]:
            raise _refuse("a base URL other than the official Open-Meteo endpoint was configured")
        if key.startswith("OPEN_METEO_") and key not in OFFICIAL_BASE_URLS:
            raise _refuse("an unknown Open-Meteo setting was configured")
        if _SECRET_KEY_RE.search(key):
            raise _refuse("credentials are never passed to the weather server")
    if env.get("CANVAS_PROVIDER_TYPE", "none") != "none":
        raise _refuse("server-side storage must stay disabled")
    if env.get("OPENMETEO_DATAFRAME_DROP_ENABLED", "false") != "false":
        raise _refuse("server-side storage must stay disabled")


def _leaves(exc: BaseException) -> Iterator[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc


class StdioWeatherTransport:
    def __init__(
        self, launch: ServerLaunch, *, total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_S
    ) -> None:
        _assert_launch_safe(launch)
        self._launch = launch
        self._timeout_s = total_timeout_s

    @property
    def origin(self) -> EvidenceOrigin:
        return "live" if self._launch.is_pinned_upstream else "fixture_synthetic"

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        validate_tool_call(tool_name, arguments)  # before any process exists
        launch = self._launch
        params = StdioServerParameters(
            command=launch.command, args=list(launch.args), env=dict(launch.env)
        )
        identity_ok = False
        raw: Any = None
        try:
            with anyio.fail_after(self._timeout_s), open(os.devnull, "w") as errlog:
                async with stdio_client(params, errlog=errlog) as (read, write):
                    async with ClientSession(read, write) as session:
                        init = await session.initialize()
                        info = init.server_info
                        identity_ok = (
                            info.name == launch.expected_server_name
                            and info.version == launch.expected_server_version
                        )
                        if identity_ok:
                            raw = await session.call_tool(tool_name, arguments)
        except TimeoutError as exc:
            raise WeatherGatewayError("timeout", "the weather server timed out") from exc
        except BaseExceptionGroup as group:
            leaves = list(_leaves(group))
            for leaf in leaves:
                if isinstance(leaf, WeatherGatewayError):
                    raise leaf from None
            if any(isinstance(leaf, TimeoutError) for leaf in leaves):
                raise WeatherGatewayError("timeout", "the weather server timed out") from None
            raise WeatherGatewayError(
                "provider_unavailable", "the weather server could not be reached"
            ) from None
        except OSError as exc:
            raise WeatherGatewayError(
                "provider_unavailable", "the weather server could not be started"
            ) from exc
        except Exception as exc:
            raise WeatherGatewayError(
                "provider_unavailable", "the weather server failed during the call"
            ) from exc

        if not identity_ok:
            raise _refuse("the MCP server is not the pinned Open-Meteo server")
        return ToolResult(payload=self._unwrap(raw), origin=self.origin)

    @staticmethod
    def _unwrap(result: Any) -> dict[str, Any]:
        """Turn the MCP envelope into the tool's native payload, fail-closed."""
        if not isinstance(result, types.CallToolResult):
            raise WeatherGatewayError("invalid_response", "unexpected MCP result type")
        if result.is_error:
            raise WeatherGatewayError(_classify_error(result), "the weather tool reported an error")

        if result.structured_content is not None:
            try:
                data = json.dumps(result.structured_content).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise WeatherGatewayError(
                    "invalid_response", "structured content is not JSON-serialisable"
                ) from exc
            _bound(data)
            payload = json.loads(data)
        else:
            text = next((b.text for b in result.content if isinstance(b, types.TextContent)), None)
            if text is None:
                raise WeatherGatewayError("invalid_response", "the tool result carried no data")
            _bound(text.encode("utf-8"))
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                raise WeatherGatewayError(
                    "invalid_response", "the tool result text is not JSON"
                ) from exc
        if not isinstance(payload, dict):
            raise WeatherGatewayError("invalid_response", "the tool result is not an object")
        return payload


def _bound(data: bytes) -> None:
    if len(data) > MAX_RESPONSE_BYTES:
        raise WeatherGatewayError("invalid_response", "the tool result exceeds the response bound")


def _classify_error(result: types.CallToolResult) -> ErrorCode:
    """Map an MCP error result to a typed code. Provider text is only *read* to
    classify; it is never stored, logged, or returned."""
    text = " ".join(b.text for b in result.content if isinstance(b, types.TextContent))
    lowered = (sanitize_provider_text(text) or "").casefold()
    if "429" in lowered or ("rate" in lowered and "limit" in lowered):
        return "rate_limited"
    if "timeout" in lowered or "timed out" in lowered:
        return "timeout"
    return "invalid_response"
