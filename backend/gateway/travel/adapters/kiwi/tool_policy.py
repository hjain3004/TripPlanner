"""Frozen read-only tool allowlist and denylist for Kiwi.com MCP."""

from __future__ import annotations

from gateway.travel.mcp_readonly import assert_read_only_tool

PROVIDER_ID = "kiwi"
ALLOWED_HOSTS: frozenset[str] = frozenset({"mcp.kiwi.com"})
ALLOWED_PATHS: frozenset[str] = frozenset({"", "/"})

ALLOWED_TOOLS: frozenset[str] = frozenset({"search-flight"})

DENIED_TOOLS: frozenset[str] = frozenset(
    {
        # Mutating / external submission tool advertised in tools/list; explicitly denied.
        "feedback-to-devs",
    }
)


def assert_kiwi_tool_allowed(tool_name: str) -> None:
    assert_read_only_tool(tool_name, allowed_tools=ALLOWED_TOOLS, provider_id=PROVIDER_ID)
