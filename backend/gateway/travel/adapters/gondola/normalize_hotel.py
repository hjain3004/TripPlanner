"""Normalize Gondola hotel evidence into the project's ``HotelQuote``.

``evidence.status`` is hard-coded ``"verify_required"`` regardless of what
Gondola's own response claims — the preflight reassessment treats Gondola
evidence as experimental. Points-rate evidence from Gondola is preserved on
the native ``GondolaHotelResult`` only (never smuggled into any cash field
or converted to a value here — that conversion, if it ever happens, is the
kernel's job alone, on a future reviewed hotel-award-rate model). Provider
free text is sanitized for prompt-injection markers before it reaches any
field a future LLM call site might read.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from gateway.travel.adapters.gondola.contracts import GondolaHotelResult
from gateway.travel.adapters.gondola.sanitize import sanitize_provider_text
from gateway.travel.contracts import EvidenceMeta, HotelQuote, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import hotel_quote_id

PROVIDER_ID = "gondola"
TERMS_VERSION = "gondola-mcp-v1"
ATTRIBUTION = "Gondola"
TRUSTED_LINK_HOSTS = ("gondola.ai", "www.gondola.ai")


def _trusted_link(url: str | None) -> str | None:
    if url is None:
        return None
    hostname = urlparse(url).hostname
    if hostname in TRUSTED_LINK_HOSTS:
        return url
    return None


def normalize_gondola_hotel(
    raw: GondolaHotelResult, request: HotelSearchRequest, *, now: datetime
) -> HotelQuote:
    if raw.cash_rate_minor is None or raw.cash_currency is None:
        raise TravelGatewayError(
            "invalid_response",
            f"Gondola hotel result {raw.hotel_id} has no cash rate; cannot normalize a price",
        )

    sanitized_name = sanitize_provider_text(raw.name)
    assert sanitized_name is not None  # raw.name is a required (min_length=1) field
    sanitized_cancellation = sanitize_provider_text(raw.cancellation_text)
    sanitized_notes = [
        n for n in (sanitize_provider_text(note) for note in raw.raw_notes) if n is not None
    ]

    notes = list(sanitized_notes)
    if raw.review_score is not None:
        notes.append(
            f"Provider review_score={raw.review_score} (scale unconfirmed — not mapped "
            "to review_score_scaled without a verified scale)"
        )
    if raw.points_rate is not None:
        notes.append(
            "Provider also returned a points-rate figure for this property; not represented "
            "on this quote (no reviewed hotel-award-rate contract exists yet)"
        )

    completeness = "partial" if sanitized_cancellation is None else "taxes_uncertain"

    evidence = EvidenceMeta(
        provider_id=PROVIDER_ID,
        provider_quote_id=raw.hotel_id,
        source_url=None,
        deep_link_url=_trusted_link(raw.booking_link),
        retrieved_at=now,
        expires_at=None,
        status="verify_required",
        cache_age_seconds=None,
        terms_version=TERMS_VERSION,
        attribution=ATTRIBUTION,
        completeness=completeness,
        needs_verification=True,
        notes=notes,
    )

    return HotelQuote(
        id=hotel_quote_id(raw.hotel_id, request.check_in, request.check_out, None, None),
        property_id=raw.hotel_id,
        name=sanitized_name,
        property_kind="hotel",
        city=request.city,
        area_id=None,
        lat=None,
        lon=None,
        check_in=request.check_in,
        check_out=request.check_out,
        travelers=request.travelers,
        rooms=request.rooms,
        room_name=None,
        rate_plan=None,
        cancellation_summary=sanitized_cancellation,
        refundable=None,
        review_score_scaled=None,
        review_scale_source=None,
        review_count=raw.review_count,
        placement="unknown",
        base_minor=None,
        taxes_minor=None,
        fees_minor=None,
        total_minor=raw.cash_rate_minor,
        currency=raw.cash_currency,
        pay_timing="unknown",
        purchasable_channels=[],
        evidence=evidence,
    )
