"""Observed round-trip cash fares, without inventing the unselected return leg."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Literal

from gateway.travel.adapters.gondola.adapter import GondolaAdapter
from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.hotel_discovery import HotelToolTransport
from gateway.travel.adapters.gondola.hotel_rates import parse_cash_minor
from gateway.travel.adapters.gondola.requests import build_flight_search_arguments
from gateway.travel.adapters.gondola.sanitize import REDACTED, sanitize_provider_text
from gateway.travel.contracts import (
    EvidenceMeta,
    FlexibleFlightSearchRequest,
    FlightPriceObservation,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import flight_observation_id

_OPTION = re.compile(
    r"^### [0-9]{1,2}\. (?P<carrier>[^\r\n]{1,120}?) — "
    r"(?P<currency>[A-Z]{3}) (?P<amount>[0-9][0-9,.]{0,20}) round trip[ \t]*$",
    re.MULTILINE,
)
_ROUTE = re.compile(
    r"^\*\*Outbound\*\* \*\*(?P<origin>[A-Z]{3}) -> (?P<destination>[A-Z]{3})\*\* "
    r"\([0-9]{1,2}h [0-9]{1,2}m\) (?P<stops>Nonstop|[0-9]{1,2} stops?) · "
    r"(?P<cabin>Economy|Premium Economy|Business|First)[ \t]*$",
    re.MULTILINE,
)
_LOCAL = (
    r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) "
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"(?:[1-9]|[12][0-9]|3[01]) (?:[01][0-9]|2[0-3]):[0-5][0-9]"
)
_TIME = re.compile(rf"^(?P<departure>{_LOCAL}) -> (?P<arrival>{_LOCAL})[ \t]*$", re.MULTILINE)
_RETURN = re.compile(
    r"^_Returns (?P<day>(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Z][a-z]{2} [0-9]{1,2}) "
    r"— price covers both directions\. Pick the return flight on Google Flights\._$",
    re.MULTILINE,
)
_CABINS = {
    "Economy": "economy",
    "Premium Economy": "premium",
    "Business": "business",
    "First": "first",
}
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _display_day(value: datetime) -> str:
    return f"{_DAYS[value.weekday()]} {_MONTHS[value.month - 1]} {value.day}"


def parse_flight_discovery(
    payload: Mapping[str, object],
    request: FlexibleFlightSearchRequest,
    *,
    retrieved_at: datetime,
    origin: str,
) -> list[FlightPriceObservation]:
    """Parse explicit fares as observations; never synthesize FlightSegments."""
    text = payload.get("result")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 512_000:
        raise TravelGatewayError("invalid_response", "Invalid Gondola flight discovery")
    if (
        not text.startswith("## Round-trip options — cash prices (")
        or "_Source: Google Flights. These results cannot be booked through Gondola._" not in text
        or "Each price is the total for both directions, shown against its outbound itinerary."
        not in text
        or request.depart_window_start != request.depart_window_end
        or request.return_window_start is None
        or request.return_window_start != request.return_window_end
        or request.travelers.adults != 1
        or request.travelers.children
        or request.travelers.infants
        or request.cabin != "economy"
        or request.nearby_airports
        or request.return_window_start < request.depart_window_start
    ):
        raise TravelGatewayError("invalid_response", "Unestablished Gondola fare scope")
    departure = datetime.combine(request.depart_window_start, datetime.min.time())
    return_day = datetime.combine(request.return_window_start, datetime.min.time())
    matches = list(_OPTION.finditer(text))
    observations: list[FlightPriceObservation] = []
    for index, match in enumerate(matches[:20]):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end]
        routes, times, returns = (
            list(_ROUTE.finditer(block)),
            list(_TIME.finditer(block)),
            list(_RETURN.finditer(block)),
        )
        if len(routes) != 1 or len(times) != 1 or len(returns) != 1:
            continue
        route, timing = routes[0], times[0]
        if (
            route["origin"] != request.origin
            or route["destination"] != request.destination
            or _CABINS[route["cabin"]] != request.cabin
            or timing["departure"].rsplit(" ", 1)[0] != _display_day(departure)
            or returns[0]["day"] != _display_day(return_day)
        ):
            continue
        stops = 0 if route["stops"] == "Nonstop" else int(route["stops"].split()[0])
        if request.nonstop_only and stops != 0:
            continue
        carrier = sanitize_provider_text(match["carrier"])
        if not carrier or carrier == REDACTED:
            continue
        try:
            amount = parse_cash_minor(match["amount"], match["currency"])
        except TravelGatewayError:
            continue
        if amount <= 0:
            continue
        semantic_id = hashlib.sha256(
            f"{carrier}|{timing['departure']}|{timing['arrival']}|{amount}|{match['currency']}".encode()
        ).hexdigest()[:12]
        identity = (
            flight_observation_id(
                provider_id="gondola",
                origin=request.origin,
                destination=request.destination,
                depart_date=request.depart_window_start,
                return_date=request.return_window_start,
                cabin=request.cabin,
                stops=stops,
                observed_time_bucket=retrieved_at.isoformat(),
            )
            + "_"
            + semantic_id
        )
        observations.append(
            FlightPriceObservation(
                id=identity,
                origin=request.origin,
                destination=request.destination,
                depart_date=request.depart_window_start,
                return_date=request.return_window_start,
                cabin=request.cabin,
                stops=stops,
                observed_total_minor=amount,
                currency=match["currency"],
                observed_at=retrieved_at,
                itinerary_detail="partial",
                carrier_name=carrier,
                outbound_departure_local=timing["departure"],
                outbound_arrival_local=timing["arrival"],
                price_scope="round_trip_total",
                return_itinerary_confirmed=False,
                evidence=EvidenceMeta(
                    provider_id="gondola",
                    provider_quote_id=identity,
                    source_url="https://mcp.gondola.ai/mcp/auth",
                    retrieved_at=retrieved_at,
                    expires_at=None,
                    status="verify_required",
                    terms_version="gondola-mcp-v1",
                    attribution="Gondola; source: Google Flights",
                    completeness="partial",
                    needs_verification=True,
                    notes=[
                        f"origin={origin}",
                        "Provider states this fare covers both directions for the requested dates.",
                        "Return flight is unselected; flight numbers and timezones are unknown.",
                        "Displayed times are source-local strings, "
                        "not timezone-aware flight segments.",
                        "Tax/fee coverage, fare conditions and source cache age are unverified.",
                        "Not bookable through Gondola; excluded from final costing and rewards.",
                    ],
                ),
            )
        )
    if not observations:
        raise TravelGatewayError("invalid_response", "No supported flight observations matched")
    return observations


class GondolaFlightDiscoveryAdapter(GondolaAdapter):
    capabilities = GondolaAdapter.capabilities.model_copy(update={"domains": {"flight_trend"}})

    def __init__(
        self,
        *,
        transport: HotelToolTransport,
        budget: GondolaCallBudget,
        plan_id: str,
        now: Callable[[], datetime],
        live_enabled: bool = False,
        origin: Literal["synthetic_fixture", "live_capture_replay"] | None = None,
    ) -> None:
        from gateway.travel.adapters.gondola.mcp_client import LiveGondolaTransport

        super().__init__(
            fetch_hotels=None,
            fetch_flights=None,
            budget=budget,
            plan_id=plan_id,
            now=now,
            live_enabled=live_enabled,
        )
        self._transport = transport
        self._origin = origin or (
            "live_observation"
            if isinstance(transport, LiveGondolaTransport)
            else "synthetic_fixture"
        )

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        if (
            request.travelers.adults != 1
            or request.travelers.children
            or request.travelers.infants
            or request.nearby_airports
            or request.cabin != "economy"
            or request.depart_window_start != request.depart_window_end
            or request.return_window_start is None
            or request.return_window_start != request.return_window_end
        ):
            raise TravelGatewayError(
                "unsupported_domain", "Unsupported flight observation dimensions"
            )
        self._guard()
        try:
            payload = await self._transport.call_tool(
                "search_flights",
                build_flight_search_arguments(
                    origin=request.origin,
                    destination=request.destination,
                    departure_date=request.depart_window_start,
                    return_date=request.return_window_start,
                    num_passengers=1,
                    cabin_class=request.cabin,
                ),
            )
            observations = parse_flight_discovery(
                payload, request, retrieved_at=self._now(), origin=self._origin
            )
        except Exception:
            self._circuit_breaker.record_failure()
            raise
        self._circuit_breaker.record_success()
        return observations
