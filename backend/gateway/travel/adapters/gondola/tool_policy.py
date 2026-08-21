"""Frozen, code-owned Gondola MCP tool allowlist/denylist.

Tool availability returned by a live ``tools/list`` call never authorizes a
call by itself — every ``tools/call`` passes through ``assert_tool_allowed``
first, which fails closed on any name not explicitly in ``ALLOWED_TOOLS``,
including every name in ``DENIED_TOOLS`` and every unrecognized name. No LLM
ever selects a tool name; both sets are hardcoded module-level constants,
never runtime-configurable.
"""

from __future__ import annotations

from gateway.travel.errors import TravelGatewayError

ALLOWED_TOOLS: frozenset[str] = frozenset(
    {
        "search_hotels",
        "get_hotel_details",
        "compare_rates",
        "get_booking_link",
        "predict_price",
        "get_hotel_stats",
        "get_multi_night_rates",
        "get_similar_hotels",
        "get_hotel_reviews",
        "diagnose_rates",
        "search_flights",
    }
)

DENIED_TOOLS: frozenset[str] = frozenset(
    {
        # Booking / payment / mutation / account tools (parent-task explicit denylist)
        "book_hotel",
        "book_vehicle",
        "get_payment_methods",
        "cancel_vehicle_booking",
        "create_rate_alert",
        "delete_rate_alert",
        "update_traveler_profile",
        "get_booking",
        "get_vehicle_booking",
        "get_vehicle_booking_coverage",
        "get_upcoming_trips",
        "get_past_trips",
        "get_travel_profiles",
        "get_traveler_context",
        # Recognized-but-deferred domains (no rental-vehicle or loyalty-account
        # contract exists yet in this codebase — see the parent milestone's
        # "Recognized but deferred" section, not force-fit into HotelQuote/FlightQuote)
        "search_vehicles",
        "get_vehicle_details",
        "get_vehicle_booking_link",
        "credit_card_coverage",
        "optimize_loyalty_portfolio",
        "get_loyalty_accounts",
        "get_free_night_credits",
    }
)


def assert_tool_allowed(tool_name: str) -> None:
    if tool_name in ALLOWED_TOOLS:
        return
    raise TravelGatewayError(
        "permission_denied", f"Gondola tool '{tool_name}' is not in the reviewed allowlist"
    )
