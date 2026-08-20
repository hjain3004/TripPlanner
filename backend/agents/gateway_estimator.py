"""Orchestration boundary routing sample travel inventory through the gateway.

Builds typed spec 16 search requests from ``TripSpec``, selects the eligible
``SampleAdapter`` through the registry, applies the *same* winner-selection
rule the legacy ``agents.estimator`` uses, and maps the winning quote back
into a ``SpendLineItem`` using the same currency-conversion order — so this
function is a drop-in, numerically-identical alternative to
``agents.estimator.estimate_costed_trip`` (proven by
``evals/test_travel_gateway_parity.py``).

Gateway/provider objects (``FlightQuote``, ``HotelQuote``, ...) never leave
this module: everything downstream (``core.optimizer``,
``core.transfer.pathfinder``) still only sees ``SpendLineItem``/
``SampleFlight``/``SampleHotel`` — the same kernel input types the legacy
path already produces.

Production wiring: ``agents/pipeline.py`` still calls
``agents.estimator.estimate_costed_trip`` (the legacy path), not this
function. See DEVIATIONS.md's G1 "wiring decision" entry for the rationale
(conservative choice — this milestone proves the gateway seam works, it does
not yet have a product reason to become the request-time default).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from agents.estimator import (
    area_by_id,
    destination_city,
    home_currency,
    per_diem_lines,
    poi_lines,
    preferred_cabin,
    price_in_home,
)
from agents.models import DraftItinerary, EstimatorResult
from core.db import KnowledgeBase
from core.models import CostedTrip, SpendCategory, SpendLineItem
from core.trip_models import TripSpec
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import (
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.registry import get_default_travel_registry


def _traveler_mix(spec: TripSpec) -> TravelerMix:
    return TravelerMix(adults=spec.travelers)


def _flight_stops(quote: FlightQuote) -> int:
    """Recovers the seed's original stop count from SampleAdapter's
    deterministic duration_min encoding (duration_min = 240 + 120 * stops,
    see gateway/travel/adapters/sample.py). Used only for winner tie-
    breaking, matching the legacy estimator's (price, stops, id) ordering
    -- never for money."""
    return max(0, (quote.segments[0].duration_min - 240) // 120)


def _select_flight_winner(
    quotes: list[FlightQuote], spec: TripSpec
) -> tuple[FlightQuote | None, list[str]]:
    if not quotes:
        return None, [f"No sample flight exists for {spec.origin_city}-{spec.destination_city}."]
    winner = min(
        quotes,
        key=lambda q: (q.total_minor, _flight_stops(q), q.evidence.provider_quote_id or ""),
    )
    return winner, []


def _select_hotel_winner(
    quotes: list[HotelQuote], itinerary: DraftItinerary, kb: KnowledgeBase, city: str
) -> tuple[HotelQuote | None, list[str]]:
    if not quotes:
        return None, [f"No sample hotel exists for {city}."]
    # Casefold to match legacy KnowledgeBase.sample_hotels(city, style, area)'s
    # own casefold comparison (core/db.py) -- SampleAdapter does not filter by
    # area itself, so area matching happens here and must use the same
    # case-insensitive semantics as the direct-sample path.
    wanted_area = itinerary.hotel_area_id.casefold()
    exact = [q for q in quotes if (q.area_id or "").casefold() == wanted_area]
    if exact:
        return min(exact, key=lambda q: (q.total_minor, q.property_id)), []

    selected_area = area_by_id(kb, city, itinerary.hotel_area_id)
    centrality = selected_area.centrality_score if selected_area is not None else 1.0
    area_scores = {area.id: area.centrality_score for area in kb.areas(city)}
    winner = min(
        quotes,
        key=lambda q: (
            abs(area_scores.get(q.area_id or "", 1.0) - centrality),
            q.total_minor,
            q.property_id,
        ),
    )
    return winner, [
        f"No sample hotel exists in {itinerary.hotel_area_id}; "
        "used closest available area by centrality fallback."
    ]


def estimate_costed_trip_via_gateway(
    spec: TripSpec,
    itinerary: DraftItinerary,
    kb: KnowledgeBase,
    *,
    booking_date: date,
) -> EstimatorResult:
    home_ccy = home_currency(spec)
    now = datetime.combine(booking_date, datetime.min.time(), tzinfo=UTC)
    adapter = SampleAdapter(kb, now=lambda: now)
    registry = get_default_travel_registry()
    eligible = registry.select_providers(
        active_profile="student_noncommercial", domain="flight", country=spec.home_country
    )
    assert any(e.provider_id == "sample_travel_adapter" for e in eligible)

    cabin = preferred_cabin(spec.style)
    flight_quotes = asyncio.run(
        adapter.search_flights(
            FlightSearchRequest(
                origin=spec.origin_city,
                destination=spec.destination_city,
                depart_date=spec.start_date,
                return_date=spec.end_date,
                travelers=_traveler_mix(spec),
                cabin=cabin,
                currency=home_ccy,
            )
        )
    )
    flight_winner, flight_assumptions = _select_flight_winner(flight_quotes, spec)
    if flight_winner is None and cabin != "economy":
        fallback_quotes = asyncio.run(
            adapter.search_flights(
                FlightSearchRequest(
                    origin=spec.origin_city,
                    destination=spec.destination_city,
                    depart_date=spec.start_date,
                    return_date=spec.end_date,
                    travelers=_traveler_mix(spec),
                    cabin="economy",
                    currency=home_ccy,
                )
            )
        )
        alt, _ = _select_flight_winner(fallback_quotes, spec)
        if alt is not None:
            flight_winner = alt
            flight_assumptions = [
                f"No sample {cabin} cash flight exists for "
                f"{spec.origin_city}-{spec.destination_city}; "
                "using the cheapest economy fixture."
            ]

    city = destination_city(spec)
    hotel_quotes = asyncio.run(
        adapter.search_hotels(
            HotelSearchRequest(
                city=city,
                check_in=spec.start_date,
                check_out=spec.end_date,
                travelers=_traveler_mix(spec),
                rooms=1,
                area_ids=[itinerary.hotel_area_id],
                style=spec.style,
                currency=home_ccy,
            )
        )
    )
    hotel_winner, hotel_assumptions = _select_hotel_winner(hotel_quotes, itinerary, kb, city)

    lines: list[SpendLineItem] = []

    # EstimatorResult.flight/.hotel reconstruct the original SampleFlight/
    # SampleHotel seed row by id: a deliberate compatibility shim so
    # EstimatorResult's existing typed contract (flight: SampleFlight | None)
    # is unchanged for any other caller, not a design endorsement for future
    # gateway-native result types.
    legacy_flight = None
    if flight_winner is not None:
        candidates = kb.sample_flights(
            spec.origin_city, spec.destination_city, flight_winner.segments[0].cabin
        )
        legacy_flight = next(
            (f for f in candidates if f.id == flight_winner.evidence.provider_quote_id), None
        )
        lines.append(
            SpendLineItem(
                id=f"flight:{flight_winner.evidence.provider_quote_id}",
                label=f"{flight_winner.segments[0].marketing_airline} round-trip flight",
                category=SpendCategory.FLIGHTS,
                amount_minor=price_in_home(
                    flight_winner.total_minor, flight_winner.currency, home_ccy, kb
                )
                * spec.travelers,
                currency=home_ccy,
                available_channels=flight_winner.purchasable_channels,
                merchant_hint=flight_winner.segments[0].marketing_airline,
            )
        )

    legacy_hotel = None
    if hotel_winner is not None:
        nights = spec.nights
        # total_minor was built by SampleAdapter as price_per_night_minor * nights
        # (exact integer multiplication, no FX involved yet -- see Task 9), so
        # this division is exact. Converting the recovered per-night amount
        # first, then multiplying by nights, matches the legacy estimator's
        # floor-rounding order and is required for byte-identical parity when
        # a future sample corridor's hotel currency differs from home currency.
        per_night_original = hotel_winner.total_minor // nights
        legacy_hotel = next(
            (h for h in kb.sample_hotels(city, spec.style) if h.id == hotel_winner.property_id),
            None,
        )
        lines.append(
            SpendLineItem(
                id=f"hotel:{hotel_winner.property_id}",
                label=f"{hotel_winner.name} ({nights} nights)",
                category=SpendCategory.HOTELS,
                amount_minor=price_in_home(per_night_original, hotel_winner.currency, home_ccy, kb)
                * nights,
                currency=home_ccy,
                available_channels=hotel_winner.purchasable_channels,
                merchant_hint=hotel_winner.name,
            )
        )

    poi_line_items, poi_assumptions = poi_lines(spec, itinerary, kb)
    lines.extend(poi_line_items)
    per_diem_line_items, per_diem_assumptions = per_diem_lines(spec, kb)
    lines.extend(per_diem_line_items)

    return EstimatorResult(
        costed_trip=CostedTrip(
            id=f"{spec.origin_city}-{spec.destination_city}-{spec.start_date.isoformat()}",
            origin=spec.origin_city,
            destination=spec.destination_city,
            home_currency=home_ccy,
            booking_date=booking_date,
            trip_start_date=spec.start_date,
            lines=lines,
        ),
        flight=legacy_flight,
        hotel=legacy_hotel,
        assumptions=[
            *flight_assumptions,
            *hotel_assumptions,
            *poi_assumptions,
            *per_diem_assumptions,
        ],
    )
