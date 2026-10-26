"""Code-owned request builders for the two verified OpenBnB tools.

A normalized request dimension the provider cannot express fails with
``unsupported_domain`` before any dispatch rather than being dropped or silently
narrowed (spec 16 §4: adapters never reinterpret the request).

``style`` is a ranking preference, not a provider filter, and ``currency`` is not an
upstream argument at all: the provider's own currency is preserved on the quote and the
deterministic FX path converts later (spec 16 §9).
"""

from __future__ import annotations

from typing import Any

from gateway.travel.adapters.openbnb.tool_policy import (
    LISTING_ID_PATTERN,
    MAX_ADULTS,
    MAX_OTHER_GUESTS,
    PROPERTY_TYPE,
    valid_city,
    validate_tool_arguments,
)
from gateway.travel.contracts import HotelSearchRequest
from gateway.travel.errors import TravelGatewayError

MAX_NIGHTS = 28


def stay_nights(request: HotelSearchRequest) -> int:
    return (request.check_out - request.check_in).days


def _check_supported(request: HotelSearchRequest) -> None:
    if request.property_kinds != {"vacation_rental"}:
        raise TravelGatewayError(
            "unsupported_domain", "OpenBnB serves vacation-rental searches only"
        )
    if request.rooms != 1:
        raise TravelGatewayError(
            "unsupported_domain", "OpenBnB advertises no unit-count dimension; rooms must be 1"
        )
    if request.area_ids:
        raise TravelGatewayError(
            "unsupported_domain", "OpenBnB advertises no neighbourhood dimension"
        )
    travelers = request.travelers
    if (
        travelers.adults < 1
        or travelers.adults > MAX_ADULTS
        or travelers.children > MAX_OTHER_GUESTS
        or travelers.infants > MAX_OTHER_GUESTS
    ):
        raise TravelGatewayError(
            "unsupported_domain", "OpenBnB occupancy needs 1-16 adults and bounded other guests"
        )
    if not valid_city(request.city):
        raise TravelGatewayError("invalid_response", "OpenBnB location is not a plain place name")
    if stay_nights(request) > MAX_NIGHTS:
        raise TravelGatewayError(
            "invalid_response", f"OpenBnB stays are limited to {MAX_NIGHTS} nights"
        )


def build_search_arguments(request: HotelSearchRequest) -> dict[str, Any]:
    _check_supported(request)
    return validate_tool_arguments(
        "airbnb_search",
        {
            "location": request.city,
            "checkin": request.check_in.isoformat(),
            "checkout": request.check_out.isoformat(),
            "adults": request.travelers.adults,
            "children": request.travelers.children,
            "infants": request.travelers.infants,
            "propertyType": PROPERTY_TYPE,
        },
    )


def build_detail_arguments(listing_id: str, request: HotelSearchRequest) -> dict[str, Any]:
    if not LISTING_ID_PATTERN.fullmatch(listing_id):
        raise TravelGatewayError("invalid_response", "OpenBnB listing id must be 1-20 digits")
    _check_supported(request)
    return validate_tool_arguments(
        "airbnb_listing_details",
        {
            "id": listing_id,
            "checkin": request.check_in.isoformat(),
            "checkout": request.check_out.isoformat(),
            "adults": request.travelers.adults,
            "children": request.travelers.children,
            "infants": request.travelers.infants,
        },
    )
