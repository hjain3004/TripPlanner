from __future__ import annotations

import pytest

from gateway.travel.adapters.gondola.tool_policy import (
    ALLOWED_TOOLS,
    DENIED_TOOLS,
    assert_tool_allowed,
)
from gateway.travel.errors import TravelGatewayError

EXPECTED_DENIED = frozenset(
    {
        # Parent-task explicit denylist (booking/payment/mutation/account/ambiguous)
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
        # Recognized-but-deferred (no rental-vehicle or loyalty-account contract yet)
        "search_vehicles",
        "get_vehicle_details",
        "get_vehicle_booking_link",
        "credit_card_coverage",
        "optimize_loyalty_portfolio",
        "get_loyalty_accounts",
        "get_free_night_credits",
    }
)


def test_allowed_and_denied_tools_are_disjoint() -> None:
    assert ALLOWED_TOOLS.isdisjoint(DENIED_TOOLS)


def test_denied_tools_matches_hardcoded_expected_list() -> None:
    assert DENIED_TOOLS == EXPECTED_DENIED


def test_book_hotel_is_denied() -> None:
    assert "book_hotel" in DENIED_TOOLS


def test_search_flights_is_denied() -> None:
    assert "search_flights" not in DENIED_TOOLS


def test_get_payment_methods_is_denied() -> None:
    assert "get_payment_methods" in DENIED_TOOLS


def test_search_hotels_and_search_flights_are_allowed() -> None:
    assert "search_hotels" in ALLOWED_TOOLS
    assert "search_flights" in ALLOWED_TOOLS


def test_assert_tool_allowed_passes_for_allowed_tool() -> None:
    assert_tool_allowed("search_hotels")


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_DENIED))
def test_assert_tool_allowed_raises_for_every_denied_tool(tool_name: str) -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        assert_tool_allowed(tool_name)
    assert exc_info.value.code == "permission_denied"


@pytest.mark.parametrize(
    "unknown_tool_name",
    ["totally_made_up_tool", "search_hotelz", "SEARCH_HOTELS", "get_hotel_details_v2", ""],
)
def test_assert_tool_allowed_fails_closed_on_unknown_names(unknown_tool_name: str) -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        assert_tool_allowed(unknown_tool_name)
    assert exc_info.value.code == "permission_denied"
