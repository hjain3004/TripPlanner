"""Parse ``airbnb_listing_details`` output and enrich a quote with coordinates.

Source-verified key paths (upstream ``allowSectionSchema``, v0.3.0): ``LOCATION_DEFAULT``
carries ``lat``/``lng``/``title``/``subtitle`` and ``AMENITIES_DEFAULT`` carries
``seeAllAmenitiesGroups`` keyed by category, with struck-through amenities under a
``"Not included"`` category. Upstream issue #55 notes coordinates can be stubbed, so a
missing or implausible pair simply stays ``None``.

Details never carry a price in this adapter's use: enrichment can add coordinates and
nothing else to a quote -- not money, not status, not completeness.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gateway.travel.adapters.openbnb.contracts import OpenBnBListingDetail
from gateway.travel.adapters.openbnb.links import parse_detail_url
from gateway.travel.adapters.openbnb.normalize import provider_error
from gateway.travel.adapters.openbnb.sanitize import sanitize_text
from gateway.travel.contracts import HotelQuote, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError

MAX_AMENITIES = 60
AMENITY_MAX_CHARS = 60
MAX_AMENITY_TEXT_CHARS = 8000
TITLE_MAX_CHARS = 120
_NOT_INCLUDED = "not included"


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return float(value)
    except (OverflowError, ValueError):
        return None


def _coordinates(section: Mapping[str, Any]) -> tuple[float | None, float | None]:
    lat, lon = _number(section.get("lat")), _number(section.get("lng"))
    if lat is None or lon is None:
        return None, None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or (lat == 0.0 and lon == 0.0):
        return None, None
    return lat, lon


def _amenity_names(text: object) -> list[str]:
    if not isinstance(text, str):
        return []
    names: list[str] = []
    for part in text[:MAX_AMENITY_TEXT_CHARS].split(", "):
        cleaned = sanitize_text(part, max_chars=AMENITY_MAX_CHARS)
        if cleaned:
            names.append(cleaned)
        if len(names) >= MAX_AMENITIES:
            break
    return names


def _check_listing_url(url: object, listing_id: str, request: HotelSearchRequest) -> None:
    parsed = parse_detail_url(url)
    if parsed is None or parsed[0] != listing_id:
        raise TravelGatewayError(
            "invalid_response", "OpenBnB details are not for the requested listing"
        )
    query = parsed[1]
    expected = {
        "check_in": request.check_in.isoformat(),
        "check_out": request.check_out.isoformat(),
        "adults": str(request.travelers.adults),
        "children": str(request.travelers.children),
        "infants": str(request.travelers.infants),
    }
    for key, wanted in expected.items():
        if key in query and query[key] != wanted:
            raise TravelGatewayError(
                "invalid_response", f"OpenBnB details do not match the requested {key}"
            )


def parse_detail_payload(
    payload: Mapping[str, Any], listing_id: str, request: HotelSearchRequest
) -> OpenBnBListingDetail:
    if "error" in payload:
        raise provider_error(payload.get("error"))
    sections = payload.get("details")
    if not isinstance(sections, list):
        raise TravelGatewayError("invalid_response", "OpenBnB payload has no details list")
    _check_listing_url(payload.get("listingUrl"), listing_id, request)

    lat = lon = None
    location_title: str | None = None
    available: list[str] = []
    unavailable: list[str] = []
    for section in sections:
        if not isinstance(section, Mapping):
            continue
        if section.get("id") == "LOCATION_DEFAULT":
            lat, lon = _coordinates(section)
            title = section.get("title")
            location_title = (
                sanitize_text(title, max_chars=TITLE_MAX_CHARS) if isinstance(title, str) else None
            )
        elif section.get("id") == "AMENITIES_DEFAULT":
            groups = section.get("seeAllAmenitiesGroups")
            if isinstance(groups, Mapping):
                for category, names in groups.items():
                    target = (
                        unavailable
                        if isinstance(category, str) and category.casefold() == _NOT_INCLUDED
                        else available
                    )
                    target.extend(_amenity_names(names))
    return OpenBnBListingDetail(
        listing_id=listing_id,
        lat=lat,
        lon=lon,
        location_title=location_title,
        amenities=available[:MAX_AMENITIES],
        unavailable_amenities=unavailable[:MAX_AMENITIES],
    )


def enrich_quote_with_detail(quote: HotelQuote, detail: OpenBnBListingDetail) -> HotelQuote:
    """Add coordinates from ``detail`` to ``quote``; change nothing else."""
    if quote.property_id != f"openbnb:{detail.listing_id}":
        raise TravelGatewayError(
            "invalid_response", "OpenBnB details belong to a different listing than the quote"
        )
    if detail.lat is None or detail.lon is None:
        return quote
    notes = [*quote.evidence.notes, "Coordinates from airbnb_listing_details (provider-stated)."]
    return quote.model_copy(
        update={
            "lat": detail.lat,
            "lon": detail.lon,
            "evidence": quote.evidence.model_copy(update={"notes": notes}),
        }
    )
