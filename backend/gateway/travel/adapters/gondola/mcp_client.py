"""Live Gondola MCP transport — disabled by default, never constructed by
the default registry (Phase 7). Uses the official ``mcp`` Python SDK's
Streamable HTTP client, never a hand-rolled ``urllib`` request.

Every boundary check below (host allowlist, tool policy, payload size) runs
before any network dispatch and is exercised by
``evals/test_gondola_live_transport_boundary.py`` without a real connection.
The actual session/streaming call (``call_tool``) is exercised only during
the human-supervised bounded live-acceptance step — never in the normal
test suite, and never autonomously by an agent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from gateway.travel.adapters.gondola.tool_policy import assert_tool_allowed
from gateway.travel.errors import TravelGatewayError

ALLOWED_HOST = "mcp.gondola.ai"
MAX_PAYLOAD_BYTES = 512_000
CONNECT_TIMEOUT_S = 10.0
TOTAL_TIMEOUT_S = 20.0


class LiveGondolaTransport:
    def __init__(self, *, base_url: str, get_access_token: Callable[[], str | None]) -> None:
        """``get_access_token`` may return ``None`` for anonymous-only use
        (e.g. ``tools/list`` discovery, ``search_hotels``) — no Authorization
        header is sent in that case. Authenticated tools (``search_flights``)
        require a callable that returns a real ``mcp:read`` token."""
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise TravelGatewayError(
                "permission_denied",
                f"Gondola live transport refuses non-allowlisted endpoint: {base_url!r}",
            )
        self._base_url = base_url
        self._get_access_token = get_access_token

    def _build_http_client(self) -> Any:
        import httpx2

        token = self._get_access_token()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        return httpx2.AsyncClient(
            headers=headers, timeout=httpx2.Timeout(TOTAL_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)
        )

    def build_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Validate a tool call before any dispatch. Returns (name, arguments)
        unchanged when allowed; raises TravelGatewayError otherwise."""
        assert_tool_allowed(tool_name)
        return tool_name, arguments

    def validate_payload_size(self, raw: bytes) -> None:
        if len(raw) > MAX_PAYLOAD_BYTES:
            raise TravelGatewayError(
                "invalid_response", f"Gondola response exceeds {MAX_PAYLOAD_BYTES} byte bound"
            )

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Perform one real MCP tool call. Only reachable when explicitly
        enabled (Phase 7) — never exercised in the normal test suite."""
        name, validated_arguments = self.build_tool_call(tool_name, arguments)

        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        http_client = self._build_http_client()
        try:
            async with streamable_http_client(self._base_url, http_client=http_client) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(name, validated_arguments)
                    payload_bytes = json.dumps(result.model_dump()).encode("utf-8")
                    self.validate_payload_size(payload_bytes)
                    payload: dict[str, Any] = json.loads(payload_bytes)
                    return payload
        finally:
            await http_client.aclose()

    async def list_tools(self) -> list[dict[str, Any]]:
        """Perform one real ``tools/list`` discovery call. Read-only by MCP
        protocol definition — does not itself require ``assert_tool_allowed``
        (that gate applies to ``tools/call``), but the caller must never use
        the result to authorize calling anything outside ``ALLOWED_TOOLS``:
        tool availability is information, never authorization."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        http_client = self._build_http_client()
        try:
            async with streamable_http_client(self._base_url, http_client=http_client) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    payload_bytes = json.dumps(result.model_dump()).encode("utf-8")
                    self.validate_payload_size(payload_bytes)
                    payload: dict[str, Any] = json.loads(payload_bytes)
                    tools: list[dict[str, Any]] = payload.get("tools", [])
                    return tools
        finally:
            await http_client.aclose()
