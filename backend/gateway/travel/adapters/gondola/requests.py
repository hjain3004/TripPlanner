"""Code-owned request shapes for Gondola's verified MCP tools.

These builders deliberately accept only dimensions the live schemas advertise.
Unsupported application dimensions fail before transport dispatch instead of
being silently dropped by the provider.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError


def build_hotel_search_arguments(
    *, location: str, checkin: date, checkout: date, num_adults: int, rooms: int = 1
) -> dict[str, Any]:
    if not location.strip() or checkout <= checkin or num_adults < 1:
        raise TravelGatewayError("invalid_response", "Gondola hotel search dimensions are invalid")
    if rooms != 1:
        raise TravelGatewayError(
            "unsupported_domain",
            "Gondola search_hotels does not advertise a room-count dimension",
        )
    return {
        "location": location,
        "checkin": checkin.isoformat(),
        "checkout": checkout.isoformat(),
        "num_adults": num_adults,
    }


def build_flight_search_arguments(
    *,
    origin: str,
    destination: str,
    departure_date: date,
    num_passengers: int,
    cabin_class: str,
    return_date: date | None = None,
    points: bool = False,
    test: bool = False,
    page: int = 1,
) -> dict[str, Any]:
    if (
        len(origin) != 3
        or len(destination) != 3
        or num_passengers < 1
        or not cabin_class.strip()
        or page < 1
    ):
        raise TravelGatewayError("invalid_response", "Gondola flight search dimensions are invalid")
    if return_date is not None and return_date < departure_date:
        raise TravelGatewayError("invalid_response", "Gondola return_date precedes departure_date")
    arguments: dict[str, Any] = {
        "origin": origin.upper(),
        "destination": destination.upper(),
        "departure_date": departure_date.isoformat(),
        "num_passengers": num_passengers,
        "cabin_class": cabin_class,
        "points": points,
        "test": test,
        "page": page,
    }
    if return_date is not None:
        arguments["return_date"] = return_date.isoformat()
    return arguments


def build_hotel_request_arguments(request: HotelSearchRequest) -> dict[str, Any]:
    if request.travelers.children or request.travelers.infants:
        raise TravelGatewayError(
            "unsupported_domain",
            "Gondola hotel search does not advertise child or infant occupancy dimensions",
        )
    if request.area_ids or request.style or request.currency or request.property_kinds != {"hotel"}:
        raise TravelGatewayError(
            "unsupported_domain",
            "Gondola hotel search does not advertise area, style, property-kind, or "
            "currency dimensions",
        )
    return build_hotel_search_arguments(
        location=request.city,
        checkin=request.check_in,
        checkout=request.check_out,
        num_adults=request.travelers.adults,
        rooms=request.rooms,
    )


def build_flight_request_arguments(request: FlightSearchRequest) -> dict[str, Any]:
    if request.travelers.children or request.travelers.infants:
        raise TravelGatewayError(
            "unsupported_domain",
            "Gondola flight search does not advertise child or infant passenger dimensions",
        )
    if request.nearby_airports or request.nonstop_only or request.currency:
        raise TravelGatewayError(
            "unsupported_domain",
            "Gondola flight search does not advertise nearby-airport, nonstop, or "
            "currency dimensions",
        )
    return build_flight_search_arguments(
        origin=request.origin,
        destination=request.destination,
        departure_date=request.depart_date,
        num_passengers=request.travelers.adults,
        cabin_class=request.cabin,
        return_date=request.return_date,
    )
