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
from urllib.parse import urlsplit

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
from gateway.travel.product import (
    GatewayDiagnostic,
    InventoryQuoteSummary,
    TravelInventorySnapshot,
    TravelInventorySummary,
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


class GatewayEstimateResult:
    """Kernel estimator output plus display-safe inventory evidence."""

    def __init__(self, estimate: EstimatorResult, summary: TravelInventorySummary) -> None:
        self.estimate = estimate
        self.summary = summary


def _safe_public_url(value: str | None) -> str | None:
    if value is None or any(ord(char) < 32 for char in value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    return value


def _summary_quote(
    domain: str, quote: FlightQuote | HotelQuote, *, selected: bool, scope: object
) -> InventoryQuoteSummary:
    evidence = quote.evidence
    limitations = list(evidence.notes)
    source_url = _safe_public_url(evidence.source_url)
    deep_link_url = _safe_public_url(evidence.deep_link_url)
    if evidence.source_url is not None and source_url is None:
        limitations.append("Provider source link was omitted because it was not a safe HTTPS URL.")
    if evidence.deep_link_url is not None and deep_link_url is None:
        limitations.append("Provider detail link was omitted because it was not a safe HTTPS URL.")
    if domain == "flight" and isinstance(quote, FlightQuote) and quote.trip_type == "one_way":
        limitations.append(
            "Sample flight packaging is a per-traveler one-way estimate; "
            "it is not proof of a current return itinerary."
        )
    if domain == "hotel" and isinstance(quote, HotelQuote):
        limitations.append(
            "Sample hotel packaging is a nightly fixture estimate; verify room "
            "availability and taxes before booking."
        )
    return InventoryQuoteSummary(
        domain=domain,
        quote_id=quote.id,
        provider_id=evidence.provider_id,
        provider_quote_id=evidence.provider_quote_id,
        source_url=source_url,
        deep_link_url=deep_link_url,
        attribution=evidence.attribution,
        retrieved_at=evidence.retrieved_at,
        expires_at=evidence.expires_at,
        status=evidence.status,
        needs_verification=evidence.needs_verification,
        completeness=evidence.completeness,
        source_amount_minor=quote.total_minor,
        source_currency=quote.currency,
        converted_amount_minor=None,
        price_scope=scope,
        selected=selected,
        alternative=not selected,
        limitations=limitations,
    )


def estimate_confirmed_inventory(
    spec: TripSpec,
    itinerary: DraftItinerary,
    kb: KnowledgeBase,
    snapshot: TravelInventorySnapshot,
    *,
    booking_date: date,
) -> GatewayEstimateResult:
    """Map admitted quotes into the unchanged deterministic Kernel input.

    Sample quotes deliberately use the compatibility estimator to preserve the
    existing seed multiplier/FX-floor order.  Verified party-total quotes use
    one conversion and never manufacture a SampleFlight/SampleHotel row.
    """
    diagnostics = list(snapshot.diagnostics)
    current_flights = [quote for quote in snapshot.flights if quote.evidence.status != "stale"]
    current_hotels = [quote for quote in snapshot.hotels if quote.evidence.status != "stale"]
    flight = min(current_flights, key=lambda q: (q.total_minor, q.id), default=None)
    hotel = min(current_hotels, key=lambda q: (q.total_minor, q.id), default=None)
    flight_scope = snapshot.flight_scopes.get(flight.id) if flight else None
    hotel_scope = snapshot.hotel_scopes.get(hotel.id) if hotel else None
    if flight is not None and flight_scope is not None and not flight_scope.cost_eligible:
        diagnostics.append(
            GatewayDiagnostic(
                code="missing_price_scope",
                domain="flight",
                message=(
                    "Flight evidence is alternative-only because its price scope is not verified."
                ),
            )
        )
        flight = None
    if hotel is not None and hotel_scope is not None and not hotel_scope.cost_eligible:
        diagnostics.append(
            GatewayDiagnostic(
                code="missing_price_scope",
                domain="hotel",
                message=(
                    "Hotel evidence is alternative-only because its price scope is not verified."
                ),
            )
        )
        hotel = None

    only_sample = (
        flight is not None
        and hotel is not None
        and flight.evidence.provider_id.startswith("sample_")
        and hotel.evidence.provider_id.startswith("sample_")
    )
    if only_sample:
        home_ccy = home_currency(spec)
        external_lines: list[SpendLineItem] = []
        legacy_flight = None
        legacy_hotel = None
        flight_assumptions: list[str] = []
        hotel_assumptions: list[str] = []
        if flight is not None:
            flight_id = flight.evidence.provider_quote_id
            legacy_flight = next(
                (
                    row
                    for row in kb.sample_flights(
                        spec.origin_city, spec.destination_city, flight.segments[0].cabin
                    )
                    if row.id == flight_id
                ),
                None,
            )
            external_lines.append(
                SpendLineItem(
                    id=f"flight:{flight_id}",
                    label=f"{flight.segments[0].marketing_airline} round-trip flight",
                    category=SpendCategory.FLIGHTS,
                    amount_minor=price_in_home(flight.total_minor, flight.currency, home_ccy, kb)
                    * spec.travelers,
                    currency=home_ccy,
                    available_channels=flight.purchasable_channels,
                    merchant_hint=flight.segments[0].marketing_airline,
                )
            )
            flight_assumptions.extend(flight.evidence.notes)
        if hotel is not None:
            legacy_hotel = next(
                (
                    row
                    for row in kb.sample_hotels(destination_city(spec), spec.style)
                    if row.id == hotel.property_id
                ),
                None,
            )
            external_lines.append(
                SpendLineItem(
                    id=f"hotel:{hotel.property_id}",
                    label=f"{hotel.name} ({spec.nights} nights)",
                    category=SpendCategory.HOTELS,
                    amount_minor=price_in_home(
                        hotel.total_minor // spec.nights, hotel.currency, home_ccy, kb
                    )
                    * spec.nights,
                    currency=home_ccy,
                    available_channels=hotel.purchasable_channels,
                    merchant_hint=hotel.name,
                )
            )
            hotel_assumptions.extend(hotel.evidence.notes)
        poi, poi_assumptions = poi_lines(spec, itinerary, kb)
        per_diem, per_diem_assumptions = per_diem_lines(spec, kb)
        external_lines.extend([*poi, *per_diem])
        estimate = EstimatorResult(
            costed_trip=CostedTrip(
                id=f"{spec.origin_city}-{spec.destination_city}-{spec.start_date.isoformat()}",
                origin=spec.origin_city,
                destination=spec.destination_city,
                home_currency=home_ccy,
                booking_date=booking_date,
                trip_start_date=spec.start_date,
                lines=external_lines,
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
    else:
        home_ccy = home_currency(spec)
        admitted_lines: list[SpendLineItem] = []
        if flight is not None and flight_scope is not None:
            amount = price_in_home(flight.total_minor, flight.currency, home_ccy, kb)
            if flight.evidence.provider_id.startswith("sample_"):
                amount *= spec.travelers
            admitted_lines.append(
                SpendLineItem(
                    id=f"flight:{flight.id}",
                    label="Confirmed flight",
                    category=SpendCategory.FLIGHTS,
                    amount_minor=amount,
                    currency=home_ccy,
                    available_channels=flight.purchasable_channels,
                )
            )
        if hotel is not None and hotel_scope is not None:
            if hotel.evidence.provider_id.startswith("sample_"):
                amount = (
                    price_in_home(hotel.total_minor // spec.nights, hotel.currency, home_ccy, kb)
                    * spec.nights
                )
            else:
                amount = price_in_home(hotel.total_minor, hotel.currency, home_ccy, kb)
            admitted_lines.append(
                SpendLineItem(
                    id=f"hotel:{hotel.id}",
                    label=hotel.name,
                    category=SpendCategory.HOTELS,
                    amount_minor=amount,
                    currency=home_ccy,
                    available_channels=hotel.purchasable_channels,
                )
            )
        poi, poi_assumptions = poi_lines(spec, itinerary, kb)
        per_diem, per_diem_assumptions = per_diem_lines(spec, kb)
        admitted_lines.extend([*poi, *per_diem])
        estimate = EstimatorResult(
            costed_trip=CostedTrip(
                id=f"{spec.origin_city}-{spec.destination_city}-{spec.start_date.isoformat()}",
                origin=spec.origin_city,
                destination=spec.destination_city,
                home_currency=home_ccy,
                booking_date=booking_date,
                trip_start_date=spec.start_date,
                lines=admitted_lines,
            ),
            assumptions=[*poi_assumptions, *per_diem_assumptions],
        )
    selected_flight_summary = (
        _summary_quote("flight", flight, selected=True, scope=flight_scope) if flight else None
    )
    selected_hotel_summary = (
        _summary_quote("hotel", hotel, selected=True, scope=hotel_scope) if hotel else None
    )
    if selected_flight_summary is not None:
        flight_line = next(
            (line for line in estimate.costed_trip.lines if line.category is SpendCategory.FLIGHTS),
            None,
        )
        if flight_line is not None:
            selected_flight_summary = selected_flight_summary.model_copy(
                update={"converted_amount_minor": flight_line.amount_minor}
            )
    if selected_hotel_summary is not None:
        hotel_line = next(
            (line for line in estimate.costed_trip.lines if line.category is SpendCategory.HOTELS),
            None,
        )
        if hotel_line is not None:
            selected_hotel_summary = selected_hotel_summary.model_copy(
                update={"converted_amount_minor": hotel_line.amount_minor}
            )
    alternatives = [
        *[
            _summary_quote("flight", q, selected=False, scope=snapshot.flight_scopes[q.id])
            for q in snapshot.flights
            if flight is not None and q.id != flight.id and q.id in snapshot.flight_scopes
        ],
        *[
            _summary_quote("hotel", q, selected=False, scope=snapshot.hotel_scopes[q.id])
            for q in snapshot.hotels
            if hotel is not None and q.id != hotel.id and q.id in snapshot.hotel_scopes
        ],
    ]
    return GatewayEstimateResult(
        estimate=estimate,
        summary=TravelInventorySummary(
            flight=selected_flight_summary,
            hotel=selected_hotel_summary,
            alternatives=alternatives,
            diagnostics=diagnostics,
            limitations=[
                "Award guidance remains seed-backed reference only; verify "
                "availability before transfer."
            ],
        ),
    )
