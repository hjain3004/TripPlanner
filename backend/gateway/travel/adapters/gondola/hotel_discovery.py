"""Follow explicit Gondola search identifiers to dated rates in memory.

Search headings identify properties; they do not establish costable rates.
The returned rate payload stays private to the caller until normalization.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

from gateway.travel.adapters.gondola.requests import (
    build_hotel_rates_arguments,
    build_hotel_search_arguments,
)
from gateway.travel.adapters.gondola.sanitize import sanitize_provider_text
from gateway.travel.errors import TravelGatewayError

_HOTEL_HEADING = re.compile(
    r"^### (?P<name>[^\r\n]{1,400}?) \(ID: (?P<id>[0-9]{1,18})\)[ \t]*$",
    re.MULTILINE,
)
_MAX_SEARCH_BYTES = 512_000


class HotelToolTransport(Protocol):
    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class GondolaHotelCandidate:
    hotel_id: int = field(repr=False)
    name: str


@dataclass(frozen=True)
class GondolaHotelRateObservation:
    candidate: GondolaHotelCandidate
    check_in: date
    check_out: date
    adults: int
    payload: dict[str, Any] = field(repr=False)


def parse_hotel_search_candidates(
    payload: Mapping[str, object],
) -> list[GondolaHotelCandidate]:
    """Read explicit public property IDs from the observed heading grammar.

    No price or arbitrary URL number is interpreted as a property identity.
    """
    text = payload.get("result")
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_SEARCH_BYTES:
        raise TravelGatewayError("invalid_response", "Invalid Gondola hotel discovery")
    candidates: list[GondolaHotelCandidate] = []
    seen: set[int] = set()
    for match in _HOTEL_HEADING.finditer(text):
        identifier = int(match["id"])
        if identifier <= 0 or identifier in seen:
            continue
        name = sanitize_provider_text(match["name"])
        if not name:
            continue
        seen.add(identifier)
        candidates.append(GondolaHotelCandidate(identifier, name))
    return candidates


async def fetch_first_hotel_rates(
    transport: HotelToolTransport,
    *,
    location: str,
    check_in: date,
    check_out: date,
    adults: int,
) -> GondolaHotelRateObservation:
    """Execute one search and one dependent rate request, with no retries.

    The calling gateway/diagnostic must authorize and reserve both calls
    before entering this workflow. This function never enables a provider.
    The integer identifier type was verified against the live tool schema.
    """
    search = await transport.call_tool(
        "search_hotels",
        build_hotel_search_arguments(
            location=location,
            checkin=check_in,
            checkout=check_out,
            num_adults=adults,
        ),
    )
    candidates = parse_hotel_search_candidates(search)
    if not candidates:
        raise TravelGatewayError(
            "invalid_response", "Gondola search returned no explicit hotel identifier"
        )
    selected = candidates[0]
    rates = await transport.call_tool(
        "get_hotel_rates",
        build_hotel_rates_arguments(
            hotel_id=selected.hotel_id,
            checkin=check_in,
            checkout=check_out,
            num_adults=adults,
        ),
    )
    return GondolaHotelRateObservation(selected, check_in, check_out, adults, rates)
