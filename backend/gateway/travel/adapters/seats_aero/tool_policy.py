"""Frozen read-only tool allowlist and denylist for Seats.aero MCP."""

from __future__ import annotations

from gateway.travel.mcp_readonly import assert_read_only_tool

PROVIDER_ID = "seats_aero"
ALLOWED_HOSTS: frozenset[str] = frozenset({"seats.aero"})
ALLOWED_PATHS: frozenset[str] = frozenset({"/mcp"})

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "get_capabilities",
        "get_flights",
        "get_flight_details",
        "list_routes",
        "list_transfer_partners",
        "list_transfer_program_mileage_programs",
        "search_airports",
    }
)

DENIED_TOOLS: frozenset[str] = frozenset(
    {
        "create_alert",
        "expire_alert",
        "book_flight",
        "live_search",
        "update_settings",
        "search_help_docs",
    }
)


def assert_seats_aero_tool_allowed(tool_name: str) -> None:
    assert_read_only_tool(tool_name, allowed_tools=ALLOWED_TOOLS, provider_id=PROVIDER_ID)
