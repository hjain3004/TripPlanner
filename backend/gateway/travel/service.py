"""Bounded, profile-aware inventory selection for confirmed trips."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal, cast
from urllib.parse import urlsplit

from gateway.travel.contracts import (
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
)
from gateway.travel.product import GatewayDiagnostic, QuotePriceScope, TravelInventorySnapshot
from gateway.travel.protocol import Domain, TravelProviderAdapter
from gateway.travel.registry import TravelProviderRegistry


def _safe_link(value: str | None) -> str | None:
    if value is None or any(ord(char) < 32 for char in value):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    return value


class TravelInventoryService:
    def __init__(
        self,
        *,
        registry: TravelProviderRegistry,
        adapters: dict[str, TravelProviderAdapter],
        plan_id: str,
        country: str,
        now: Callable[[], datetime],
        active_profile: str = "student_noncommercial",
    ) -> None:
        self.registry = registry
        self.adapters = dict(adapters)
        self.plan_id = plan_id
        self.country = country
        self.now = now
        self.active_profile = active_profile

    def _eligible(self, domain: str) -> list[tuple[str, TravelProviderAdapter]]:
        rows: list[tuple[str, TravelProviderAdapter]] = []
        for entry in self.registry.select_providers(
            active_profile=self.active_profile, domain=cast(Domain, domain), country=self.country
        ):
            adapter = self.adapters.get(entry.provider_id)
            if entry.monthly_cost_minor != 0 or adapter is None:
                continue
            if adapter.capabilities.provider_id != entry.provider_id:
                continue
            if domain not in adapter.capabilities.domains:
                continue
            rows.append((entry.provider_id, adapter))
        return rows

    async def search(
        self,
        flight: FlightSearchRequest,
        hotel: HotelSearchRequest,
        *,
        domains: set[str] | None = None,
    ) -> TravelInventorySnapshot:
        requested = {"flight", "hotel"} if domains is None else set(domains)
        if not requested <= {"flight", "hotel"}:
            raise ValueError("unsupported inventory domain")
        retrieved = self.now()
        flights: list[FlightQuote] = []
        hotels: list[HotelQuote] = []
        diagnostics: list[GatewayDiagnostic] = []
        scopes: dict[str, QuotePriceScope] = {}
        hotel_scopes: dict[str, QuotePriceScope] = {}
        for provider_id, adapter in self._eligible("flight") if "flight" in requested else []:
            try:
                candidates = await adapter.search_flights(flight)
            except Exception:
                diagnostics.append(
                    GatewayDiagnostic(
                        code="provider_unavailable",
                        domain="flight",
                        provider_id=provider_id,
                        message="Flight inventory was unavailable; using an eligible fallback.",
                    )
                )
                continue
            for quote in candidates:
                if flight.nonstop_only and not self._sample_stops_allowed(adapter, quote):
                    diagnostics.append(
                        GatewayDiagnostic(
                            code="unsupported_preference",
                            domain="flight",
                            provider_id=provider_id,
                            message=(
                                "The eligible sample inventory has no confirmed nonstop option."
                            ),
                        )
                    )
                    continue
                if quote.travelers != flight.travelers or quote.currency != flight.currency:
                    diagnostics.append(
                        GatewayDiagnostic(
                            code="mismatched_response",
                            domain="flight",
                            provider_id=provider_id,
                            message="Flight response did not match the confirmed request.",
                        )
                    )
                    continue
                segment = quote.segments[0]
                if segment.origin != flight.origin or segment.destination != flight.destination:
                    continue
                if not provider_id.startswith("sample_") and segment.cabin != flight.cabin:
                    continue
                if (
                    not provider_id.startswith("sample_")
                    and flight.return_date is not None
                    and quote.trip_type != "round_trip"
                ):
                    continue
                if quote.evidence.provider_id != provider_id:
                    continue
                flights.append(quote)
                flight_basis: Literal["sample_per_traveler_trip", "party_total"] = (
                    "sample_per_traveler_trip"
                    if provider_id.startswith("sample_")
                    else "party_total"
                )
                scopes[quote.id] = QuotePriceScope(
                    basis=flight_basis,
                    scope_verified=provider_id.startswith("sample_"),
                    travelers=flight.travelers.adults
                    + flight.travelers.children
                    + flight.travelers.infants,
                )
            if flights:
                break
        for provider_id, adapter in self._eligible("hotel") if "hotel" in requested else []:
            try:
                hotel_candidates = await adapter.search_hotels(hotel)
            except Exception:
                diagnostics.append(
                    GatewayDiagnostic(
                        code="provider_unavailable",
                        domain="hotel",
                        provider_id=provider_id,
                        message="Hotel inventory was unavailable; using an eligible fallback.",
                    )
                )
                continue
            for hotel_quote in hotel_candidates:
                if (
                    hotel_quote.travelers != hotel.travelers
                    or hotel_quote.currency != hotel.currency
                    or hotel_quote.check_in != hotel.check_in
                    or hotel_quote.check_out != hotel.check_out
                ):
                    diagnostics.append(
                        GatewayDiagnostic(
                            code="mismatched_response",
                            domain="hotel",
                            provider_id=provider_id,
                            message="Hotel response did not match the confirmed request.",
                        )
                    )
                    continue
                if hotel_quote.evidence.provider_id != provider_id:
                    continue
                hotels.append(hotel_quote)
                hotel_basis: Literal["sample_nightly_stay", "party_total"] = (
                    "sample_nightly_stay" if provider_id.startswith("sample_") else "party_total"
                )
                hotel_scopes[hotel_quote.id] = QuotePriceScope(
                    basis=hotel_basis,
                    scope_verified=provider_id.startswith("sample_"),
                    rooms=hotel_quote.rooms,
                )
                if not provider_id.startswith("sample_") and (
                    hotel_quote.evidence.completeness != "complete"
                    or not hotel_quote.purchasable_channels
                ):
                    hotel_scopes[hotel_quote.id] = QuotePriceScope(
                        basis="unknown", scope_verified=False, rooms=hotel_quote.rooms
                    )
                if hotel.rooms > 1 and provider_id.startswith("sample_"):
                    hotel_scopes[hotel_quote.id] = QuotePriceScope(
                        basis="unknown", scope_verified=False, rooms=hotel_quote.rooms
                    )
            if hotels:
                break
        if hotel.rooms > 1 and hotels:
            diagnostics.append(
                GatewayDiagnostic(
                    code="missing_price_scope",
                    domain="hotel",
                    message="The sample fixture does not establish multi-room pricing.",
                )
            )
        return TravelInventorySnapshot(
            flight_request=flight,
            hotel_request=hotel,
            flights=flights,
            hotels=hotels,
            flight_scopes=scopes,
            hotel_scopes=hotel_scopes,
            diagnostics=diagnostics,
            retrieved_at=retrieved,
            expires_at=retrieved + timedelta(minutes=15),
        )

    @staticmethod
    def _sample_stops_allowed(adapter: TravelProviderAdapter, quote: FlightQuote) -> bool:
        kb = getattr(adapter, "kb", None)
        if kb is None or not quote.evidence.provider_quote_id:
            return True
        rows = kb.sample_flights(
            quote.segments[0].origin,
            quote.segments[0].destination,
            quote.segments[0].cabin,
        )
        row = next(
            (candidate for candidate in rows if candidate.id == quote.evidence.provider_quote_id),
            None,
        )
        return row is None or row.stops == 0

    def revalidate(self, snapshot: TravelInventorySnapshot) -> TravelInventorySnapshot:
        now = self.now()
        if snapshot.expires_at is not None and now >= snapshot.expires_at:
            flights = [
                quote.model_copy(
                    update={"evidence": quote.evidence.model_copy(update={"status": "stale"})}
                )
                for quote in snapshot.flights
            ]
            hotels = [
                quote.model_copy(
                    update={"evidence": quote.evidence.model_copy(update={"status": "stale"})}
                )
                for quote in snapshot.hotels
            ]
            return snapshot.model_copy(
                update={
                    "flights": flights,
                    "hotels": hotels,
                    "diagnostics": [
                        *snapshot.diagnostics,
                        GatewayDiagnostic(
                            code="stale_inventory",
                            domain="general",
                            message="Inventory evidence expired before final assembly.",
                        ),
                    ],
                }
            )
        return snapshot
