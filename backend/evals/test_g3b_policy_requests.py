"""G3b tool allowlist and request builders: only the two verified read tools, and only
the verified arguments, ever reach a transport."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from gateway.travel.adapters.openbnb.requests import (
    MAX_NIGHTS,
    build_detail_arguments,
    build_search_arguments,
    stay_nights,
)
from gateway.travel.adapters.openbnb.tool_policy import (
    ALLOWED_TOOLS,
    assert_tool_allowed,
    validate_tool_arguments,
)
from gateway.travel.contracts import HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError


def _request(**overrides: object) -> HotelSearchRequest:
    fields: dict[str, object] = {
        "city": "Singapore",
        "check_in": date(2026, 11, 10),
        "check_out": date(2026, 11, 13),
        "travelers": TravelerMix(adults=2),
        "rooms": 1,
        "style": "balanced",
        "currency": "USD",
        "property_kinds": {"vacation_rental"},
    }
    fields.update(overrides)
    return HotelSearchRequest(**fields)  # type: ignore[arg-type]


def test_only_the_two_verified_read_tools_are_allowed() -> None:
    assert ALLOWED_TOOLS == {"airbnb_search", "airbnb_listing_details"}


@pytest.mark.parametrize(
    "name",
    [
        "book_listing",
        "message_host",
        "airbnb_book",
        "pay",
        "fetch_url",
        "airbnb_search ",  # whitespace is not a spelling of the allowed name
        "AIRBNB_SEARCH",
        "",
        "tools/list",
    ],
)
def test_every_other_tool_name_is_refused_before_dispatch(name: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        assert_tool_allowed(name)
    assert raised.value.code == "permission_denied"


@pytest.mark.parametrize(
    "extra",
    [
        {"ignoreRobotsText": True},
        {"ignoreRobotsText": False},  # the key itself is forbidden, whatever its value
        {"ignore_robots_txt": True},
        {"placeId": "ChIJabc"},
        {"cursor": "abc"},
        {"minPrice": 1},
        {"maxPrice": 99},
        {"pets": 1},
        {"url": "https://example.com"},
        {"headers": {"X": "1"}},
    ],
)
def test_forbidden_and_unknown_search_arguments_are_refused(extra: dict[str, object]) -> None:
    arguments = {**build_search_arguments(_request()), **extra}
    with pytest.raises(TravelGatewayError) as raised:
        validate_tool_arguments("airbnb_search", arguments)
    assert raised.value.code == "permission_denied"


def test_built_search_arguments_pass_validation_and_use_only_verified_keys() -> None:
    arguments = build_search_arguments(_request(travelers=TravelerMix(adults=2, children=1)))
    assert arguments == {
        "location": "Singapore",
        "checkin": "2026-11-10",
        "checkout": "2026-11-13",
        "adults": 2,
        "children": 1,
        "infants": 0,
        "propertyType": "entire_home",
    }
    assert validate_tool_arguments("airbnb_search", arguments) == arguments


def test_detail_arguments_carry_the_same_dates_and_occupancy() -> None:
    arguments = build_detail_arguments("1234567890", _request())
    assert arguments == {
        "id": "1234567890",
        "checkin": "2026-11-10",
        "checkout": "2026-11-13",
        "adults": 2,
        "children": 0,
        "infants": 0,
    }
    assert validate_tool_arguments("airbnb_listing_details", arguments) == arguments


@pytest.mark.parametrize("listing_id", ["", "undefined", "12 34", "../1", "1" * 21, "abc", "-5"])
def test_detail_arguments_refuse_a_listing_id_that_is_not_digits(listing_id: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        build_detail_arguments(listing_id, _request())
    assert raised.value.code == "invalid_response"


@pytest.mark.parametrize(
    "city",
    [
        "",
        "   ",
        "Paris/../admin",
        "Paris?x=1",
        "Paris#frag",
        "Paris%20",
        "a&b=c",
        "<script>",
        "Bad\nCity",
        "http://evil.example",
        "x" * 81,
        "12345",
    ],
)
def test_city_text_that_could_alter_a_url_or_query_is_refused(city: str) -> None:
    with pytest.raises(TravelGatewayError) as raised:
        build_search_arguments(_request(city=city))
    assert raised.value.code == "invalid_response"


@pytest.mark.parametrize(
    "city", ["Singapore", "Paris, France", "São Paulo", "Saint-Denis", "St. John's"]
)
def test_ordinary_city_names_are_accepted(city: str) -> None:
    assert build_search_arguments(_request(city=city))["location"] == city


def test_a_request_the_provider_cannot_express_is_unsupported_not_silently_narrowed() -> None:
    cases: list[dict[str, object]] = [
        {"rooms": 2},
        {"area_ids": ["marina_bay"]},
        {"property_kinds": {"hotel"}},
        {"property_kinds": {"vacation_rental", "hotel"}},
        {"property_kinds": {"serviced_apartment"}},
        {"travelers": TravelerMix(adults=0, children=2)},
    ]
    for overrides in cases:
        with pytest.raises(TravelGatewayError) as raised:
            build_search_arguments(_request(**overrides))
        assert raised.value.code == "unsupported_domain", overrides


def test_stay_length_is_bounded() -> None:
    assert stay_nights(_request()) == 3
    with pytest.raises(TravelGatewayError) as raised:
        too_long = date(2026, 11, 10) + timedelta(days=MAX_NIGHTS + 1)
        build_search_arguments(_request(check_out=too_long))
    assert raised.value.code == "invalid_response"


def test_occupancy_is_bounded() -> None:
    with pytest.raises(TravelGatewayError) as raised:
        build_search_arguments(_request(travelers=TravelerMix(adults=17)))
    assert raised.value.code == "unsupported_domain"
