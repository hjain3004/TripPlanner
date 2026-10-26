"""Shared synthetic builders for the G3b tests (not itself a test module).

Every payload here follows the key paths that upstream's ``allowSearchResultSchema`` copies
(source-verified at v0.3.0) with the array-flattening ``flattenArraysInObject`` applies.
Leaf wording (price labels, rating text) is synthetic: no live listing has been captured.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from typing import Any

from gateway.travel.contracts import HotelSearchRequest, TravelerMix

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
CHECK_IN = date(2026, 11, 10)
CHECK_OUT = date(2026, 11, 13)
NIGHTS = 3

SEARCH_URL = (
    "https://www.airbnb.com/s/Singapore/homes?checkin=2026-11-10&checkout=2026-11-13"
    "&adults=2&children=0&infants=0&pets=0&l2_property_type_ids%5B%5D=1"
)


def request(**overrides: Any) -> HotelSearchRequest:
    fields: dict[str, Any] = {
        "city": "Singapore",
        "check_in": CHECK_IN,
        "check_out": CHECK_OUT,
        "travelers": TravelerMix(adults=2),
        "rooms": 1,
        "style": "balanced",
        "currency": "USD",
        "property_kinds": {"vacation_rental"},
    }
    fields.update(overrides)
    return HotelSearchRequest(**fields)


def listing(
    listing_id: str = "12345678",
    *,
    title: str | None = "Entire rental unit in Kallang",
    primary_label: str | None = "US$150 per night",
    secondary_label: str | None = "US$640 total",
    items: Any = "3 nights x US$150: US$450, Cleaning fee: US$60, Service fee: US$90, Taxes: US$40",
    rating: str | None = "4.92 out of 5 average rating, 1,204 reviews",
    url: str | None = "",
) -> dict[str, Any]:
    """One search result, shaped like upstream's picked-and-flattened output."""
    result: dict[str, Any] = {
        "id": listing_id,
        "url": f"https://www.airbnb.com/rooms/{listing_id}" if url == "" else url,
        "demandStayListing": {"id": "RGVtYW5kU3RheUxpc3Rpbmc6MTIzNDU2Nzg="},
        "badges": "Guest favorite",
        "structuredContent": {"primaryLine": {"body": title}} if title is not None else {},
        "structuredDisplayPrice": {
            "primaryLine": {"accessibilityLabel": primary_label},
            "secondaryLine": {"accessibilityLabel": secondary_label},
            "explanationData": {"title": "Price details", "priceDetails": {"items": items}},
        },
    }
    if rating is not None:
        result["avgRatingA11yLabel"] = rating
    return result


def payload(*results: dict[str, Any], search_url: str | None = SEARCH_URL) -> dict[str, Any]:
    body: dict[str, Any] = {
        "searchResults": [copy.deepcopy(r) for r in (results or (listing(),))],
        "paginationInfo": {"nextPageCursor": "x"},
    }
    if search_url is not None:
        body["searchUrl"] = search_url
    return body
