"""Required enabled-by-default SampleAdapter — spec 16 §5/§7.

Maps the *existing* repository sample fixtures (``core.db.KnowledgeBase``
seed tables — not invented real-world data) into normalized flight/hotel
quotes. Every result is ``status="estimated"``, ``needs_verification=True``,
uses deterministic synthetic timestamps, and never modifies the original
seed amount. See Task 9 ambiguity notes in
docs/superpowers/plans/2026-08-20-g1-travel-inventory-gateway.md for the
synthetic-segment-timing and no-adapter-side-FX-conversion decisions.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from core.db import KnowledgeBase
from core.models import SampleFlight, SampleHotel
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    EvidenceMeta,
    FlexibleFlightSearchRequest,
    FlightPriceObservation,
    FlightQuote,
    FlightSearchRequest,
    FlightSegment,
    HotelQuote,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import flight_quote_id, hotel_quote_id
from gateway.travel.protocol import AdapterCapabilities

PROVIDER_ID = "sample_travel_adapter"
TERMS_VERSION = "sample-fixture-v1"
ATTRIBUTION = "TripPlanner sample fixture data (not real inventory)"


class SampleAdapter:
    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"flight", "hotel", "award"},
        countries="configured",
        live_data=False,
        supports_cache=False,
        supports_commercial_use=False,
        allowed_profiles={"student_noncommercial", "commercial_production"},
        source_method="sample",
        stability="stable",
        requires_user_initiated_search=False,
        max_concurrency=1,
    )

    def __init__(self, kb: KnowledgeBase, *, now: Callable[[], datetime]) -> None:
        self.kb = kb
        self.now = now

    def _evidence(self, provider_quote_id: str, notes: list[str]) -> EvidenceMeta:
        return EvidenceMeta(
            provider_id=PROVIDER_ID,
            provider_quote_id=provider_quote_id,
            source_url=None,
            deep_link_url=None,
            retrieved_at=self.now(),
            expires_at=None,
            status="estimated",
            cache_age_seconds=None,
            terms_version=TERMS_VERSION,
            attribution=ATTRIBUTION,
            completeness="taxes_uncertain",
            needs_verification=True,
            notes=notes,
        )

    def _map_flight(
        self, flight: SampleFlight, depart_date: date, cabin: str, travelers: TravelerMix
    ) -> FlightQuote:
        departure_at = datetime.combine(depart_date, time(9, 0), tzinfo=UTC)
        duration_min = 240 + 120 * flight.stops
        segment = FlightSegment(
            origin=flight.origin,
            destination=flight.destination,
            departure_at=departure_at,
            arrival_at=departure_at + timedelta(minutes=duration_min),
            marketing_airline=flight.airline,
            operating_airline=None,
            flight_number=f"SAMPLE-{flight.id.upper()}",
            cabin=cabin,
            duration_min=duration_min,
        )
        segments = [segment]
        notes = [
            f"Sample fixture models {flight.stops} stop(s) as a single normalized segment; "
            "intermediate routing not available.",
            "Departure/arrival times and flight number are synthetic (not a real schedule).",
            "Tax/fee breakdown not available in sample fixture; total price only.",
        ]
        if flight.notes:
            notes.append(f"Seed note: {flight.notes}")
        return FlightQuote(
            id=flight_quote_id(segments, travelers, fare_brand=None),
            segments=segments,
            trip_type="one_way",
            travelers=travelers,
            fare_brand=None,
            baggage_summary=None,
            refundable=None,
            changeable=None,
            base_minor=None,
            taxes_minor=None,
            fees_minor=None,
            total_minor=flight.price_minor,
            currency=flight.currency,
            purchasable_channels=list(flight.purchasable_channels),
            evidence=self._evidence(flight.id, notes),
        )

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]:
        rows = self.kb.sample_flights(request.origin, request.destination, request.cabin)
        return [
            self._map_flight(row, request.depart_date, request.cabin, request.travelers)
            for row in rows
        ]

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        raise TravelGatewayError(
            "unsupported_domain", f"{PROVIDER_ID} does not support flight_trend"
        )

    def _map_hotel(self, hotel: SampleHotel, request: HotelSearchRequest) -> HotelQuote:
        nights = (request.check_out - request.check_in).days
        notes = [
            "Sample fixture provides one all-in nightly rate; tax/fee breakdown not available.",
            f"total_minor is the unconverted seed nightly rate x {nights} nights "
            "(synthetic packaging, not a live quote).",
        ]
        return HotelQuote(
            id=hotel_quote_id(hotel.id, request.check_in, request.check_out, None, None),
            property_id=hotel.id,
            name=hotel.name,
            property_kind="hotel",
            city=hotel.city,
            area_id=hotel.area,
            lat=None,
            lon=None,
            check_in=request.check_in,
            check_out=request.check_out,
            travelers=request.travelers,
            rooms=request.rooms,
            room_name=None,
            rate_plan=None,
            cancellation_summary=None,
            refundable=None,
            review_score_scaled=None,
            review_scale_source=None,
            review_count=None,
            placement="organic",
            base_minor=None,
            taxes_minor=None,
            fees_minor=None,
            total_minor=hotel.price_per_night_minor * nights,
            currency=hotel.currency,
            pay_timing="unknown",
            purchasable_channels=list(hotel.purchasable_channels),
            evidence=self._evidence(hotel.id, notes),
        )

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        # request.area_ids/property_kinds are deliberately NOT filtered here:
        # the sample seed data has no property_kind other than "hotel", and
        # area filtering happens deterministically downstream in the
        # orchestration boundary (agents/gateway_estimator.py), matching how
        # the legacy direct-sample path structures the same two-step lookup
        # (broad style match, then area selection with centrality fallback).
        rows = self.kb.sample_hotels(request.city, request.style)
        return [self._map_hotel(row, request) for row in rows]

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]:
        # No genuine sample award-availability fixture exists in this repo (spec
        # 16 §4/G1 scope): honestly return empty rather than fabricate availability.
        return []
