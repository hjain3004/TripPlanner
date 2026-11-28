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
from pathlib import Path
from typing import Literal
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
from core.models import (
    AwardChartEntry,
    AwardTarget,
    CostedTrip,
    LoyaltyProgram,
    PointValuation,
    Provenance,
    RecommendationKind,
    SpendCategory,
    SpendLineItem,
    TransferAdvice,
)
from core.transfer.pathfinder import find_transfer_plans
from core.trip_models import TripSpec
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    Cabin,
    Completeness,
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.live_orchestrator import (
    GatewayFetchBundle,
    GatewayProviderFactories,
    fetch_gateway_inventory_sync,
    run_coro_sync,
)
from gateway.travel.product import (
    GatewayDiagnostic,
    InventoryQuoteSummary,
    QuotePriceScope,
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

    def __init__(
        self,
        estimate: EstimatorResult,
        summary: TravelInventorySummary,
        snapshot: TravelInventorySnapshot | None = None,
    ) -> None:
        self.estimate = estimate
        self.summary = summary
        self.snapshot = snapshot


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
    if (
        domain == "hotel"
        and isinstance(quote, HotelQuote)
        and evidence.provider_id.startswith("sample_")
    ):
        limitations.append(
            "Sample hotel packaging is a nightly fixture estimate; verify room "
            "availability and taxes before booking."
        )
    return InventoryQuoteSummary(
        domain=domain,
        quote_id=quote.id,
        provider_id=evidence.provider_id,
        provider_quote_id=evidence.provider_quote_id,
        property_name=quote.name if isinstance(quote, HotelQuote) else None,
        room_name=quote.room_name if isinstance(quote, HotelQuote) else None,
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
    eligible_hotels = [
        quote
        for quote in current_hotels
        if quote.id in snapshot.hotel_scopes and snapshot.hotel_scopes[quote.id].cost_eligible
    ]
    flight = min(current_flights, key=lambda q: (q.total_minor, q.id), default=None)
    hotel = min(
        eligible_hotels or current_hotels, key=lambda q: (q.total_minor, q.id), default=None
    )
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
            if (hotel is None or q.id != hotel.id) and q.id in snapshot.hotel_scopes
        ],
    ]
    return GatewayEstimateResult(
        estimate=estimate,
        snapshot=snapshot,
        summary=TravelInventorySummary(
            flight=selected_flight_summary,
            hotel=selected_hotel_summary,
            alternatives=alternatives,
            flight_observations=snapshot.flight_observations,
            diagnostics=diagnostics,
            limitations=[
                "Award guidance remains seed-backed reference only; verify "
                "availability before transfer."
            ],
        ),
    )


# --------------------------------------------------------------------------- #
# Opt-in live gateway estimator & ephemeral award bridge                       #
# --------------------------------------------------------------------------- #

_COMPLETENESS_RANK: dict[Completeness, int] = {
    "complete": 0,
    "taxes_uncertain": 1,
    "fees_uncertain": 1,
    "partial": 2,
}


class LiveGatewayEstimate:
    """Deterministic estimator output paired with live inventory metadata and award quotes."""

    def __init__(
        self,
        *,
        estimate: EstimatorResult,
        inventory_summary: TravelInventorySummary,
        award_quotes: list[AwardQuote],
        provenance_flags: list[str],
        flight_line: SpendLineItem | None,
        hotel_line: SpendLineItem | None,
        flight_assumptions: list[str],
        hotel_assumptions: list[str],
        flight_is_round_trip: bool = True,
    ) -> None:
        self.estimate = estimate
        self.inventory_summary = inventory_summary
        self.award_quotes = award_quotes
        self.provenance_flags = provenance_flags
        self.flight_line = flight_line
        self.hotel_line = hotel_line
        self.flight_assumptions = flight_assumptions
        self.hotel_assumptions = hotel_assumptions
        self.flight_is_round_trip = flight_is_round_trip


def _can_convert_currency(currency: str, home_ccy: str, kb: KnowledgeBase) -> bool:
    return currency == home_ccy or kb.fx_rate(currency, home_ccy) is not None


def _select_live_flight_candidate(
    quotes: list[FlightQuote],
    spec: TripSpec,
    kb: KnowledgeBase,
    home_ccy: str,
) -> tuple[FlightQuote | None, list[GatewayDiagnostic]]:
    diags: list[GatewayDiagnostic] = []
    eligible: list[tuple[tuple[int, int, int, str], FlightQuote]] = []
    for quote in quotes:
        if quote.evidence.status == "stale":
            continue
        if not _can_convert_currency(quote.currency, home_ccy, kb):
            diags.append(
                GatewayDiagnostic(
                    code="missing_fx_rate",
                    domain="flight",
                    provider_id=quote.evidence.provider_id,
                    message=(
                        f"Skipped {quote.evidence.provider_id} flight quote in "
                        f"{quote.currency}: no FX rate to {home_ccy}."
                    ),
                )
            )
            continue
        converted = price_in_home(quote.total_minor, quote.currency, home_ccy, kb)
        if quote.evidence.provider_id.startswith("sample_"):
            converted *= spec.travelers
        rank = (
            _COMPLETENESS_RANK[quote.evidence.completeness],
            converted,
            max(0, len(quote.segments) - 1),
            quote.id,
        )
        eligible.append((rank, quote))
    if not eligible:
        return None, diags
    eligible.sort(key=lambda item: item[0])
    return eligible[0][1], diags


def _select_live_hotel_candidate(
    quotes: list[HotelQuote],
    spec: TripSpec,
    kb: KnowledgeBase,
    home_ccy: str,
) -> tuple[HotelQuote | None, list[GatewayDiagnostic]]:
    diags: list[GatewayDiagnostic] = []
    eligible: list[tuple[tuple[int, int, int, str], HotelQuote]] = []
    for quote in quotes:
        if quote.evidence.status == "stale":
            continue
        if quote.evidence.completeness == "partial":
            # Never allow incomplete/nightly-only estimates to enter cost winner selection.
            continue
        if not _can_convert_currency(quote.currency, home_ccy, kb):
            diags.append(
                GatewayDiagnostic(
                    code="missing_fx_rate",
                    domain="hotel",
                    provider_id=quote.evidence.provider_id,
                    message=(
                        f"Skipped {quote.evidence.provider_id} hotel quote in "
                        f"{quote.currency}: no FX rate to {home_ccy}."
                    ),
                )
            )
            continue
        if quote.evidence.provider_id.startswith("sample_"):
            converted = (
                price_in_home(quote.total_minor // spec.nights, quote.currency, home_ccy, kb)
                * spec.nights
            )
        else:
            converted = price_in_home(quote.total_minor, quote.currency, home_ccy, kb)
        rank = (
            _COMPLETENESS_RANK[quote.evidence.completeness],
            1 if quote.evidence.needs_verification else 0,
            converted,
            quote.id,
        )
        eligible.append((rank, quote))
    if not eligible:
        return None, diags
    eligible.sort(key=lambda item: item[0])
    return eligible[0][1], diags


def _award_target_cabin(spec: TripSpec) -> Cabin:
    if spec.style == "luxury":
        return "business"
    return "economy"


def estimate_costed_trip_with_live_gateway(
    spec: TripSpec,
    itinerary: DraftItinerary,
    kb: KnowledgeBase,
    *,
    booking_date: date,
    plan_id: str,
    provider_factories: GatewayProviderFactories | None = None,
    budget_db_path: Path | str | None = None,
) -> LiveGatewayEstimate:
    """Resolve cash/award travel evidence via enabled MCPs with SampleAdapter fallback."""
    home_ccy = home_currency(spec)
    now = datetime.combine(booking_date, datetime.min.time(), tzinfo=UTC)
    city = destination_city(spec)
    cabin = preferred_cabin(spec.style)

    flight_request = FlightSearchRequest(
        origin=spec.origin_city,
        destination=spec.destination_city,
        depart_date=spec.start_date,
        return_date=spec.end_date,
        travelers=_traveler_mix(spec),
        cabin=cabin,
        currency=home_ccy,
    )
    hotel_request = HotelSearchRequest(
        city=city,
        check_in=spec.start_date,
        check_out=spec.end_date,
        travelers=_traveler_mix(spec),
        rooms=1,
        area_ids=[itinerary.hotel_area_id],
        style=spec.style,
        currency=home_ccy,
    )
    award_request = AwardSearchRequest(
        origin=spec.origin_city,
        destination=spec.destination_city,
        depart_date=spec.start_date,
        return_date=None,
        travelers=_traveler_mix(spec),
        cabin=_award_target_cabin(spec),
    )

    bundle: GatewayFetchBundle = fetch_gateway_inventory_sync(
        flight_request=flight_request,
        hotel_request=hotel_request,
        award_request=award_request,
        country=spec.home_country,
        booking_date=booking_date,
        plan_id=plan_id,
        now=lambda: now,
        factories=provider_factories,
        budget_db_path=budget_db_path,
    )

    diagnostics = list(bundle.diagnostics)
    status_notes = [entry.as_assumption_string() for entry in bundle.statuses]
    provenance_flags: list[str] = []

    sample_adapter = SampleAdapter(kb, now=lambda: now)
    sample_flights = run_coro_sync(sample_adapter.search_flights(flight_request))
    sample_flight_cabin_fallback = False
    if not sample_flights and cabin != "economy":
        sample_flights = run_coro_sync(
            sample_adapter.search_flights(flight_request.model_copy(update={"cabin": "economy"}))
        )
        if sample_flights:
            sample_flight_cabin_fallback = True
    sample_hotels = run_coro_sync(sample_adapter.search_hotels(hotel_request))

    flight_winner, flight_diags = _select_live_flight_candidate(
        bundle.flights, spec, kb, home_ccy
    )
    diagnostics.extend(flight_diags)
    flight_assumptions: list[str] = []
    if flight_winner is None:
        if bundle.flights:
            status_notes.append("gateway:flight:live_unusable:fallback:sample_travel_adapter")
        flight_winner, flight_assumptions = _select_flight_winner(sample_flights, spec)
        if sample_flight_cabin_fallback:
            flight_assumptions.insert(
                0,
                (
                    f"No sample {cabin} cash flight exists for this route; "
                    "pricing economy sample flight."
                ),
            )
    else:
        flight_assumptions.append(
            f"Selected live {flight_winner.evidence.provider_id} cash flight "
            f"({flight_winner.evidence.completeness})."
        )
        flight_assumptions.extend(flight_winner.evidence.notes)

    hotel_winner, hotel_diags = _select_live_hotel_candidate(bundle.hotels, spec, kb, home_ccy)
    diagnostics.extend(hotel_diags)
    hotel_assumptions: list[str] = []
    if hotel_winner is None:
        if bundle.hotels:
            status_notes.append("gateway:hotel:live_unusable:fallback:sample_travel_adapter")
        hotel_winner, hotel_assumptions = _select_hotel_winner(sample_hotels, itinerary, kb, city)
    else:
        hotel_assumptions.append(
            f"Selected live {hotel_winner.evidence.provider_id} hotel "
            f"({hotel_winner.evidence.completeness})."
        )
        hotel_assumptions.extend(hotel_winner.evidence.notes)

    lines: list[SpendLineItem] = []
    flight_line: SpendLineItem | None = None
    legacy_flight = None
    flight_amount_converted: int | None = None
    if flight_winner is not None:
        is_sample_f = flight_winner.evidence.provider_id.startswith("sample_")
        flight_amount_converted = price_in_home(
            flight_winner.total_minor, flight_winner.currency, home_ccy, kb
        )
        if is_sample_f:
            flight_amount_converted *= spec.travelers
            candidates = kb.sample_flights(
                spec.origin_city, spec.destination_city, flight_winner.segments[0].cabin
            )
            legacy_flight = next(
                (f for f in candidates if f.id == flight_winner.evidence.provider_quote_id),
                None,
            )
            f_line_id = f"flight:{flight_winner.evidence.provider_quote_id}"
            f_label = f"{flight_winner.segments[0].marketing_airline} round-trip flight"
        else:
            f_line_id = f"flight:{flight_winner.id}"
            f_label = (
                f"{flight_winner.segments[0].marketing_airline} "
                f"{flight_winner.trip_type.replace('_', '-')} flight"
            )
        flight_line = SpendLineItem(
            id=f_line_id,
            label=f_label,
            category=SpendCategory.FLIGHTS,
            amount_minor=flight_amount_converted,
            currency=home_ccy,
            available_channels=flight_winner.purchasable_channels or ["ota_generic"],
            merchant_hint=flight_winner.segments[0].marketing_airline,
        )
        lines.append(flight_line)
        if flight_winner.evidence.needs_verification:
            provenance_flags.append(
                f"flight:{flight_winner.evidence.provider_id}:{flight_winner.id}:needs_verification"
            )

    hotel_line: SpendLineItem | None = None
    legacy_hotel = None
    hotel_amount_converted: int | None = None
    if hotel_winner is not None:
        is_sample_h = hotel_winner.evidence.provider_id.startswith("sample_")
        if is_sample_h:
            nights = spec.nights
            per_night = hotel_winner.total_minor // nights
            hotel_amount_converted = (
                price_in_home(per_night, hotel_winner.currency, home_ccy, kb) * nights
            )
            legacy_hotel = next(
                (h for h in kb.sample_hotels(city, spec.style) if h.id == hotel_winner.property_id),
                None,
            )
            h_line_id = f"hotel:{hotel_winner.property_id}"
            h_label = f"{hotel_winner.name} ({nights} nights)"
        else:
            hotel_amount_converted = price_in_home(
                hotel_winner.total_minor, hotel_winner.currency, home_ccy, kb
            )
            h_line_id = f"hotel:{hotel_winner.id}"
            h_label = f"{hotel_winner.name} ({spec.nights} nights)"
        hotel_line = SpendLineItem(
            id=h_line_id,
            label=h_label,
            category=SpendCategory.HOTELS,
            amount_minor=hotel_amount_converted,
            currency=home_ccy,
            available_channels=hotel_winner.purchasable_channels or ["ota_generic"],
            merchant_hint=hotel_winner.name,
        )
        lines.append(hotel_line)
        if hotel_winner.evidence.needs_verification:
            provenance_flags.append(
                f"hotel:{hotel_winner.evidence.provider_id}:{hotel_winner.id}:needs_verification"
            )

    for award in bundle.awards:
        if award.evidence.needs_verification:
            provenance_flags.append(f"award:{award.evidence.provider_id}:{award.id}:needs_verification")

    poi_line_items, poi_assumptions = poi_lines(spec, itinerary, kb)
    per_diem_line_items, per_diem_assumptions = per_diem_lines(spec, kb)
    lines.extend([*poi_line_items, *per_diem_line_items])

    estimate = EstimatorResult(
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
            *status_notes,
            *flight_assumptions,
            *hotel_assumptions,
            *poi_assumptions,
            *per_diem_assumptions,
        ],
    )

    flight_scope = (
        QuotePriceScope(
            basis=(
                "sample_per_traveler_trip"
                if flight_winner.evidence.provider_id.startswith("sample_")
                else "party_total"
            ),
            scope_verified=True,
            travelers=spec.travelers,
        )
        if flight_winner is not None
        else QuotePriceScope(basis="unknown")
    )
    hotel_scope = (
        QuotePriceScope(
            basis=(
                "sample_nightly_stay"
                if hotel_winner.evidence.provider_id.startswith("sample_")
                else "party_total"
            ),
            scope_verified=True,
            travelers=spec.travelers,
            rooms=1,
        )
        if hotel_winner is not None
        else QuotePriceScope(basis="unknown")
    )

    selected_flight_sum = (
        _summary_quote("flight", flight_winner, selected=True, scope=flight_scope).model_copy(
            update={"converted_amount_minor": flight_amount_converted}
        )
        if flight_winner is not None
        else None
    )
    selected_hotel_sum = (
        _summary_quote("hotel", hotel_winner, selected=True, scope=hotel_scope).model_copy(
            update={"converted_amount_minor": hotel_amount_converted}
        )
        if hotel_winner is not None
        else None
    )

    alt_flights = [
        _summary_quote(
            "flight",
            q,
            selected=False,
            scope=QuotePriceScope(
                basis="party_total", scope_verified=True, travelers=spec.travelers
            ),
        )
        for q in bundle.flights
        if flight_winner is None or q.id != flight_winner.id
    ]
    alt_hotels = [
        _summary_quote(
            "hotel",
            q,
            selected=False,
            scope=(
                QuotePriceScope(
                    basis="unknown", scope_verified=False, travelers=spec.travelers, rooms=1
                )
                if q.evidence.completeness == "partial"
                else QuotePriceScope(
                    basis="party_total", scope_verified=True, travelers=spec.travelers, rooms=1
                )
            ),
        )
        for q in bundle.hotels
        if hotel_winner is None or q.id != hotel_winner.id
    ]

    summary = TravelInventorySummary(
        flight=selected_flight_sum,
        hotel=selected_hotel_sum,
        alternatives=[*alt_flights[:10], *alt_hotels[:10]],
        diagnostics=diagnostics,
        limitations=[
            "External quotes carry verify_required state; verify live totals, baggage, and award "
            "space with the issuer/merchant before booking or transferring points."
        ],
        reference_only_awards=len(bundle.awards) == 0,
    )

    return LiveGatewayEstimate(
        estimate=estimate,
        inventory_summary=summary,
        award_quotes=bundle.awards,
        provenance_flags=sorted(set(provenance_flags)),
        flight_line=flight_line,
        hotel_line=hotel_line,
        flight_assumptions=flight_assumptions,
        hotel_assumptions=hotel_assumptions,
        flight_is_round_trip=(flight_winner is None or flight_winner.trip_type == "round_trip"),
    )


def reprice_live_estimate_for_itinerary(
    spec: TripSpec,
    itinerary: DraftItinerary,
    kb: KnowledgeBase,
    previous: LiveGatewayEstimate,
    *,
    booking_date: date,
) -> LiveGatewayEstimate:
    """Recompute POI and per-diem lines on critic replan without re-fetching providers."""
    home_ccy = home_currency(spec)
    lines: list[SpendLineItem] = []
    if previous.flight_line is not None:
        lines.append(previous.flight_line)
    if previous.hotel_line is not None:
        lines.append(previous.hotel_line)
    poi_line_items, poi_assumptions = poi_lines(spec, itinerary, kb)
    per_diem_line_items, per_diem_assumptions = per_diem_lines(spec, kb)
    lines.extend([*poi_line_items, *per_diem_line_items])

    status_notes = [
        a for a in previous.estimate.assumptions if a.startswith("gateway:")
    ]
    estimate = EstimatorResult(
        costed_trip=CostedTrip(
            id=previous.estimate.costed_trip.id,
            origin=spec.origin_city,
            destination=spec.destination_city,
            home_currency=home_ccy,
            booking_date=booking_date,
            trip_start_date=spec.start_date,
            lines=lines,
        ),
        flight=previous.estimate.flight,
        hotel=previous.estimate.hotel,
        assumptions=[
            *status_notes,
            *previous.flight_assumptions,
            *previous.hotel_assumptions,
            *poi_assumptions,
            *per_diem_assumptions,
        ],
    )
    return LiveGatewayEstimate(
        estimate=estimate,
        inventory_summary=previous.inventory_summary,
        award_quotes=previous.award_quotes,
        provenance_flags=previous.provenance_flags,
        flight_line=previous.flight_line,
        hotel_line=previous.hotel_line,
        flight_assumptions=previous.flight_assumptions,
        hotel_assumptions=previous.hotel_assumptions,
        flight_is_round_trip=previous.flight_is_round_trip,
    )


def _clone_kb_with_award_quotes(
    kb: KnowledgeBase,
    award_quotes: list[AwardQuote],
) -> tuple[KnowledgeBase, dict[str, int], list[AwardQuote]]:
    """Create an in-memory ephemeral KnowledgeBase copy augmented with valid AwardQuotes."""
    card_ids = [c.id for c in kb.cards()]
    valuations: list[PointValuation] = []
    baseline_by_currency: dict[str, int] = {}
    for cid in card_ids:
        card_vals = kb.valuations_for_card(cid)
        valuations.extend(card_vals)
        best = kb.best_valuation(cid)
        if best is not None:
            baseline_by_currency[cid] = best[0]
    voyager_best = kb.best_valuation("voyager-prime")
    if voyager_best is not None:
        baseline_by_currency["voyager-prime"] = voyager_best[0]

    existing_programs = {p.id: p for p in kb.programs()}
    ephemeral_programs: list[LoyaltyProgram] = list(existing_programs.values())
    ephemeral_awards: list[AwardChartEntry] = []
    usable_quotes: list[AwardQuote] = []

    for quote in award_quotes:
        party_size = max(1, quote.travelers.adults + quote.travelers.children)
        miles_cost = quote.miles_total // party_size
        if miles_cost <= 0:
            continue
        usable_quotes.append(quote)
        source_link = _safe_public_url(quote.evidence.deep_link_url) or _safe_public_url(
            quote.evidence.source_url
        )
        prov = Provenance(
            source_url=source_link,
            source_type="manual_curation",
            last_verified=quote.evidence.retrieved_at.date(),
            verified_by="UNVERIFIED",
            needs_verification=True,
            confidence=0.8,
            notes=f"Ephemeral gateway award quote from {quote.evidence.provider_id}",
        )
        if quote.program_id not in existing_programs:
            prog = LoyaltyProgram(
                id=quote.program_id,
                kind="airline",
                name=quote.program_id.replace("_", " ").title(),
                booking_url=source_link,
                provenance=prov,
            )
            existing_programs[quote.program_id] = prog
            ephemeral_programs.append(prog)
        elif source_link is not None:
            updated_prog = existing_programs[quote.program_id].model_copy(
                update={"booking_url": source_link}
            )
            existing_programs[quote.program_id] = updated_prog
            ephemeral_programs = [
                updated_prog if p.id == quote.program_id else p for p in ephemeral_programs
            ]
        ephemeral_awards.append(
            AwardChartEntry(
                id=quote.id,
                program_id=quote.program_id,
                origin=quote.origin,
                destination=quote.destination,
                cabin=quote.cabin,
                trip_type="one_way" if quote.return_date is None else "round_trip",
                miles_cost=miles_cost,
                fees_minor=quote.fees_minor // party_size,
                fees_currency=quote.fees_currency,
                provenance=prov,
            )
        )

    all_awards = [
        *list(getattr(kb, "_award_chart_entries", [])),
        *ephemeral_awards,
    ]
    ephemeral_kb = KnowledgeBase.from_models(
        cards=kb.cards(),
        reward_rules=kb.rules_for_cards(card_ids),
        offers=list(getattr(kb, "_offers", [])),
        point_valuations=valuations,
        fx_rates=list(getattr(kb, "_fx", {}).values()),
        pois=[],
        areas=[],
        sample_flights=[],
        sample_hotels=[],
        loyalty_programs=ephemeral_programs,
        transfer_edges=list(getattr(kb, "_transfer_edges", [])),
        transfer_bonuses=list(getattr(kb, "_transfer_bonuses", [])),
        award_chart_entries=all_awards,
    )
    return ephemeral_kb, baseline_by_currency, usable_quotes


def evaluate_live_awards(
    spec: TripSpec,
    estimate: EstimatorResult,
    kb: KnowledgeBase,
    base_advice: TransferAdvice | None,
    award_quotes: list[AwardQuote],
    *,
    booking_date: date,
    cash_flight_is_round_trip: bool = True,
) -> TransferAdvice | None:
    """Evaluate ephemeral Seats.aero AwardQuotes without mutating the SQLite KB."""
    if not award_quotes:
        return base_advice
    if not spec.wallet.points_balances:
        return base_advice

    flight_line = next(
        (line for line in estimate.costed_trip.lines if line.id.startswith("flight:")),
        None,
    )
    if flight_line is None or flight_line.amount_minor <= 0:
        return base_advice

    ephemeral_kb, card_baselines, usable_quotes = _clone_kb_with_award_quotes(kb, award_quotes)
    if not usable_quotes:
        return base_advice
    baselines: dict[str, int] = {"voyager-prime": 1_000_000, **card_baselines}
    usable_baselines = {
        cid: baselines[cid] for cid in spec.wallet.points_balances if cid in baselines
    }
    if not usable_baselines:
        return base_advice

    sample_q = usable_quotes[0]
    live_trip_type: Literal["one_way", "round_trip"] = (
        "one_way" if sample_q.return_date is None else "round_trip"
    )
    award_target = AwardTarget(
        origin=spec.origin_city,
        destination=spec.destination_city,
        cabin=sample_q.cabin,
        trip_type=live_trip_type,
        travelers=spec.travelers,
        home_currency=estimate.costed_trip.home_currency,
    )
    # Match one-way live awards against half of a round-trip cash ticket so savings are not doubled.
    cash_baseline_minor = (
        flight_line.amount_minor // 2
        if live_trip_type == "one_way" and cash_flight_is_round_trip
        else flight_line.amount_minor
    )
    live_advice = find_transfer_plans(
        award_target,
        spec.wallet,
        ephemeral_kb,
        usable_baselines,
        cash_baseline_minor,
        booking_date,
    )

    if live_advice.plans and (
        base_advice is None
        or base_advice.recommendation.kind != RecommendationKind.REDEEM
        or live_advice.recommendation.kind == RecommendationKind.REDEEM
    ):
        return live_advice
    if base_advice is None:
        return live_advice
    merged_infeasible = sorted(
        [*base_advice.infeasible, *live_advice.infeasible],
        key=lambda row: (row.award_id, "+".join(row.best_path), row.shortfall_currency),
    )
    return base_advice.model_copy(update={"infeasible": merged_infeasible})
