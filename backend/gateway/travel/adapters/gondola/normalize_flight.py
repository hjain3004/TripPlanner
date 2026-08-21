"""Normalize authenticated Gondola flight evidence into the project's
``FlightQuote``.

Every field the project's frozen ``FlightSegment``/``FlightQuote`` contracts
require (real segments, carrier, flight number, cabin, duration, total
price, currency) must be present in Gondola's response or normalization
fails closed with a typed ``invalid_response`` error — no missing segment,
carrier, or price is ever fabricated. ``evidence.status`` is hard-coded
``"verify_required"``; a cash quote from Gondola is never represented as
award availability (Tier-F-P rule 9 — a distinct ``AwardQuote`` contract
would be required for that, and none exists for Gondola in this milestone).
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from gateway.travel.adapters.gondola.contracts import GondolaFlightResult
from gateway.travel.adapters.gondola.sanitize import sanitize_provider_text
from gateway.travel.contracts import EvidenceMeta, FlightQuote, FlightSearchRequest, FlightSegment
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import flight_quote_id

PROVIDER_ID = "gondola"
TERMS_VERSION = "gondola-mcp-v1"
ATTRIBUTION = "Gondola"
TRUSTED_LINK_HOSTS = ("gondola.ai", "www.gondola.ai")


def _trusted_link(url: str | None) -> str | None:
    if url is None:
        return None
    if urlparse(url).hostname in TRUSTED_LINK_HOSTS:
        return url
    return None


def _require_segment(raw_segment: object, quote_id: str) -> FlightSegment:
    fields = {
        "origin": getattr(raw_segment, "origin", None),
        "destination": getattr(raw_segment, "destination", None),
        "departure_at": getattr(raw_segment, "departure_at", None),
        "arrival_at": getattr(raw_segment, "arrival_at", None),
        "marketing_airline": getattr(raw_segment, "marketing_airline", None),
        "flight_number": getattr(raw_segment, "flight_number", None),
        "cabin": getattr(raw_segment, "cabin", None),
        "duration_min": getattr(raw_segment, "duration_min", None),
    }
    missing = [name for name, value in fields.items() if value is None]
    if missing:
        raise TravelGatewayError(
            "invalid_response",
            f"Gondola flight result {quote_id} has an incomplete segment; "
            f"missing required fields: {', '.join(missing)}",
        )
    return FlightSegment(
        origin=fields["origin"],
        destination=fields["destination"],
        departure_at=fields["departure_at"],
        arrival_at=fields["arrival_at"],
        marketing_airline=fields["marketing_airline"],
        operating_airline=getattr(raw_segment, "operating_airline", None),
        flight_number=fields["flight_number"],
        cabin=fields["cabin"],
        duration_min=fields["duration_min"],
    )


def normalize_gondola_flight(
    raw: GondolaFlightResult, request: FlightSearchRequest, *, now: datetime
) -> FlightQuote:
    if not raw.segments:
        raise TravelGatewayError(
            "invalid_response", f"Gondola flight result {raw.quote_id} has no segments"
        )
    if raw.total_price_minor is None or raw.currency is None:
        raise TravelGatewayError(
            "invalid_response",
            f"Gondola flight result {raw.quote_id} has no total price; cannot normalize",
        )
    if raw.trip_type is None:
        raise TravelGatewayError(
            "invalid_response", f"Gondola flight result {raw.quote_id} has no trip_type"
        )

    segments = [_require_segment(seg, raw.quote_id) for seg in raw.segments]

    evidence = EvidenceMeta(
        provider_id=PROVIDER_ID,
        provider_quote_id=raw.quote_id,
        source_url=None,
        deep_link_url=_trusted_link(raw.booking_link),
        retrieved_at=now,
        expires_at=None,
        status="verify_required",
        cache_age_seconds=None,
        terms_version=TERMS_VERSION,
        attribution=ATTRIBUTION,
        completeness="taxes_uncertain",
        needs_verification=True,
        notes=[
            n for n in (sanitize_provider_text(note) for note in raw.raw_notes) if n is not None
        ],
    )

    return FlightQuote(
        id=flight_quote_id(segments, request.travelers, fare_brand=None),
        segments=segments,
        trip_type=raw.trip_type,
        travelers=request.travelers,
        fare_brand=None,
        baggage_summary=None,
        refundable=None,
        changeable=None,
        base_minor=None,
        taxes_minor=None,
        fees_minor=None,
        total_minor=raw.total_price_minor,
        currency=raw.currency,
        purchasable_channels=[],
        evidence=evidence,
    )
