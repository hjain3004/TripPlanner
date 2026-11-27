"""Frozen read-only tool allowlist and denylist for Trivago MCP."""

from __future__ import annotations

from gateway.travel.mcp_readonly import assert_read_only_tool

PROVIDER_ID = "trivago"
ALLOWED_HOSTS: frozenset[str] = frozenset({"mcp.trivago.com"})
ALLOWED_PATHS: frozenset[str] = frozenset({"/mcp"})

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "trivago-accommodation-radius-search",
        "trivago-accommodation-search",
        "trivago-destination-price-trends",
    }
)

DENIED_TOOLS: frozenset[str] = frozenset(
    {
        "book_hotel",
        "create_booking",
        "create_price_alert",
        "update_user_preferences",
    }
)


def assert_trivago_tool_allowed(tool_name: str) -> None:
    assert_read_only_tool(tool_name, allowed_tools=ALLOWED_TOOLS, provider_id=PROVIDER_ID)
