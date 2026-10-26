"""Frozen, code-owned OpenBnB MCP tool and argument allowlist.

Verified from upstream ``index.ts`` at v0.3.0 (``d5a8f18``): the server advertises exactly
two tools. A name or argument that is not listed here never reaches a transport, whatever
a live ``tools/list`` might one day return; no model or user input selects either set.

Deliberately absent from the argument sets even though upstream accepts them:

* ``ignoreRobotsText`` -- a per-call robots.txt override. Spec 09 G3b: never enable any
  robots override or blocking circumvention. The key is refused whatever its value.
* ``placeId`` / ``cursor`` / ``minPrice`` / ``maxPrice`` / ``pets`` -- unreviewed free-form
  inputs, extra pages (more provider calls) or dimensions the normalized request lacks.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from gateway.travel.errors import TravelGatewayError

SEARCH_TOOL = "airbnb_search"
DETAIL_TOOL = "airbnb_listing_details"
ALLOWED_TOOLS: frozenset[str] = frozenset({SEARCH_TOOL, DETAIL_TOOL})

SEARCH_ARGUMENTS: frozenset[str] = frozenset(
    {"location", "checkin", "checkout", "adults", "children", "infants", "propertyType"}
)
DETAIL_ARGUMENTS: frozenset[str] = frozenset(
    {"id", "checkin", "checkout", "adults", "children", "infants"}
)
_ARGUMENTS_BY_TOOL: dict[str, frozenset[str]] = {
    SEARCH_TOOL: SEARCH_ARGUMENTS,
    DETAIL_TOOL: DETAIL_ARGUMENTS,
}
# The only upstream property filter this adapter sends: an entire home or apartment is the
# closest verified match to the normalized ``vacation_rental`` kind.
PROPERTY_TYPE = "entire_home"

LISTING_ID_PATTERN = re.compile(r"[0-9]{1,20}")
MAX_ADULTS = 16
MAX_OTHER_GUESTS = 16
MAX_CITY_CHARS = 80
# Letters (any script), spaces and a few separators. Nothing that can restructure a URL,
# a query string, a header or markup.
CITY_PATTERN = re.compile(r"[^\W\d_](?:[\w .,'’\-]*[^\W_])?")


def assert_tool_allowed(tool_name: str) -> None:
    if tool_name in ALLOWED_TOOLS:
        return
    raise TravelGatewayError(
        "permission_denied", "OpenBnB tool is not in the reviewed read-only allowlist"
    )


def valid_city(value: str) -> bool:
    candidate = value.strip()
    return (
        value == candidate
        and 0 < len(candidate) <= MAX_CITY_CHARS
        and ".." not in candidate
        and CITY_PATTERN.fullmatch(candidate) is not None
    )


def _bad(message: str) -> TravelGatewayError:
    return TravelGatewayError("invalid_response", f"OpenBnB argument rejected: {message}")


def _int_in(value: object, low: int, high: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _bad(f"{name} must be an integer {low}..{high}")
    return value


def _iso_date(value: object, name: str) -> date:
    if not isinstance(value, str):
        raise _bad(f"{name} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise _bad(f"{name} must be an ISO date") from None
    if parsed.isoformat() != value:
        raise _bad(f"{name} must be an ISO date")
    return parsed


def validate_tool_arguments(tool_name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Return a validated copy of ``arguments`` or raise before any dispatch.

    Unknown or forbidden keys are a policy violation (``permission_denied``); a permitted
    key with a bad value is an ``invalid_response`` (the request builder is at fault).
    """
    assert_tool_allowed(tool_name)
    unexpected = sorted(set(arguments) - _ARGUMENTS_BY_TOOL[tool_name])
    if unexpected:
        raise TravelGatewayError(
            "permission_denied",
            f"OpenBnB {tool_name} does not accept argument(s): {', '.join(unexpected)}",
        )
    clean = dict(arguments)
    if tool_name == SEARCH_TOOL:
        location = clean.get("location")
        if not isinstance(location, str) or not valid_city(location):
            raise _bad("location is not a plain place name")
        if clean.get("propertyType", PROPERTY_TYPE) != PROPERTY_TYPE:
            raise _bad("propertyType is not the reviewed value")
    else:
        listing_id = clean.get("id")
        if not isinstance(listing_id, str) or not LISTING_ID_PATTERN.fullmatch(listing_id):
            raise _bad("id must be 1-20 digits")
    check_in = _iso_date(clean.get("checkin"), "checkin")
    check_out = _iso_date(clean.get("checkout"), "checkout")
    if check_out <= check_in:
        raise _bad("checkout must follow checkin")
    _int_in(clean.get("adults"), 1, MAX_ADULTS, "adults")
    _int_in(clean.get("children"), 0, MAX_OTHER_GUESTS, "children")
    _int_in(clean.get("infants"), 0, MAX_OTHER_GUESTS, "infants")
    return clean
