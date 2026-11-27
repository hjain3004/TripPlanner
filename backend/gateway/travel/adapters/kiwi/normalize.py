"""Normalization from real Kiwi.com MCP ``search-flight`` payloads to Spec-16 ``FlightQuote``."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from gateway.travel.contracts import (
    EvidenceMeta,
    FlightQuote,
    FlightSearchRequest,
    FlightSegment,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.mcp_readonly import (
    REDACTED,
    RawMcpToolResponse,
    parse_decimal_to_minor,
    sanitize_untrusted_text,
    validate_deep_link,
)

PROVIDER_ID = "kiwi"
TERMS_VERSION = "kiwi_mcp_public_noncommercial_2026_11_27"
QUOTE_TTL = timedelta(minutes=15)


def _extract_kiwi_payload(raw: RawMcpToolResponse) -> dict[str, Any]:
    if raw.structured_content is not None:
        return raw.structured_content
    for block in raw.text_blocks:
        stripped = block.strip()
        if not stripped:
            continue
        try:
            parsed = json.loads(stripped, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise TravelGatewayError(
                "invalid_response", f"Kiwi payload is not valid JSON: {exc}"
            ) from exc
        if isinstance(parsed, dict):
            return parsed
    raise TravelGatewayError("invalid_response", "Kiwi returned no parsable JSON object")


def _parse_segment_datetimes(
    raw_dep: Any,
    raw_arr: Any,
    duration_seconds: int,
    *,
    notes: list[str],
) -> tuple[datetime, datetime]:
    if not isinstance(raw_dep, str) or not isinstance(raw_arr, str):
        raise TravelGatewayError("invalid_response", "Kiwi segment missing departure/arrival time")
    try:
        dep_dt = datetime.fromisoformat(raw_dep.strip())
        arr_dt = datetime.fromisoformat(raw_arr.strip())
    except ValueError as exc:
        raise TravelGatewayError(
            "invalid_response", f"Invalid Kiwi segment timestamp: {exc}"
        ) from exc

    if dep_dt.tzinfo is None:
        dep_dt = dep_dt.replace(tzinfo=UTC)
        notes.append("timestamps_airport_local_without_tz_offset")
    if arr_dt.tzinfo is None:
        arr_dt = arr_dt.replace(tzinfo=UTC)

    if arr_dt <= dep_dt:
        arr_dt = dep_dt + timedelta(seconds=duration_seconds)
        notes.append("arrival_adjusted_from_duration_due_to_local_clock_offset")
    return dep_dt, arr_dt


def _parse_leg_segments(
    leg: Any,
    *,
    fallback_cabin: str,
    notes: list[str],
) -> list[FlightSegment]:
    if not isinstance(leg, dict):
        raise TravelGatewayError("invalid_response", "Kiwi flight leg must be a JSON object")
    raw_segments = leg.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise TravelGatewayError("invalid_response", "Kiwi flight leg missing non-empty segments")

    segments: list[FlightSegment] = []
    for seg in raw_segments:
        if not isinstance(seg, dict):
            raise TravelGatewayError("invalid_response", "Kiwi segment entry is not a JSON object")
        origin = seg.get("from")
        destination = seg.get("to")
        duration_sec = seg.get("durationSeconds")
        carrier = seg.get("carrier")
        carrier_name = seg.get("carrierName")
        flight_number = seg.get("flightNumber")
        cabin_class = seg.get("cabinClass") or leg.get("cabinClass") or fallback_cabin

        if (
            not isinstance(origin, str)
            or not isinstance(destination, str)
            or isinstance(duration_sec, bool)
            or not isinstance(duration_sec, int)
            or duration_sec <= 0
            or not isinstance(carrier, str)
            or not carrier.strip()
            or not isinstance(flight_number, str)
            or not flight_number.strip()
        ):
            raise TravelGatewayError(
                "invalid_response",
                "Kiwi segment missing required airport, time, carrier, or duration",
            )

        dep_at, arr_at = _parse_segment_datetimes(
            seg.get("departureTime"),
            seg.get("arrivalTime"),
            duration_sec,
            notes=notes,
        )
        # Preserve strict non-decreasing chronology across segments when local-time
        # layovers span eastbound/westbound timezone boundaries without tz offsets.
        if segments and dep_at < segments[-1].arrival_at:
            dep_at = segments[-1].arrival_at
            if arr_at <= dep_at:
                arr_at = dep_at + timedelta(seconds=duration_sec)
            notes.append("connection_adjusted_for_missing_timezone_offset")

        marketing_airline = sanitize_untrusted_text(str(carrier_name or carrier)) or carrier.strip()
        if marketing_airline == REDACTED:
            notes.append("suspected_prompt_injection_redacted")

        segments.append(
            FlightSegment(
                origin=origin.strip().upper(),
                destination=destination.strip().upper(),
                departure_at=dep_at,
                arrival_at=arr_at,
                marketing_airline=marketing_airline,
                operating_airline=sanitize_untrusted_text(carrier.strip()),
                flight_number=sanitize_untrusted_text(flight_number.strip())
                or flight_number.strip(),
                cabin=(sanitize_untrusted_text(str(cabin_class)) or fallback_cabin).lower(),
                duration_min=max(1, duration_sec // 60),
            )
        )
    return segments


def _format_baggage(baggage: Any) -> str | None:
    if not isinstance(baggage, dict):
        return None
    parts = []
    for label, key in [
        ("personal", "personalItem"),
        ("cabin", "cabinBag"),
        ("checked", "checkedBag"),
    ]:
        val = baggage.get(key)
        if isinstance(val, int) and not isinstance(val, bool):
            parts.append(f"{label}={val}")
    return ", ".join(parts) if parts else None


def normalize_kiwi_flights(
    raw: RawMcpToolResponse,
    request: FlightSearchRequest,
    *,
    now: datetime,
) -> list[FlightQuote]:
    """Normalize real Kiwi.com ``search-flight`` itineraries into Spec-16 ``FlightQuote`` list."""
    payload = _extract_kiwi_payload(raw)
    if payload.get("error"):
        raise TravelGatewayError(
            "invalid_response",
            f"Kiwi returned top-level error: {sanitize_untrusted_text(str(payload['error']))}",
        )

    currency_raw = payload.get("currency")
    if not isinstance(currency_raw, str) or len(currency_raw.strip()) != 3:
        raise TravelGatewayError("invalid_response", "Kiwi payload missing valid 3-letter currency")
    currency = currency_raw.strip().upper()

    itineraries = payload.get("itineraries")
    if itineraries is None:
        return []
    if not isinstance(itineraries, list):
        raise TravelGatewayError("invalid_response", "Kiwi itineraries must be a list")

    quotes: list[FlightQuote] = []
    for it in itineraries:
        if not isinstance(it, dict):
            raise TravelGatewayError(
                "invalid_response", "Kiwi itinerary entry is not a JSON object"
            )

        raw_id = it.get("id")
        raw_price = it.get("price")
        if not isinstance(raw_id, str) or not raw_id.strip() or raw_price is None:
            raise TravelGatewayError("invalid_response", "Kiwi itinerary missing id or price")

        total_minor = parse_decimal_to_minor(raw_price, currency)
        notes: list[str] = ["taxes_and_baggage_ancillaries_subject_to_kiwi_checkout"]

        outbound_raw = it.get("outbound")
        if outbound_raw is None:
            raise TravelGatewayError("invalid_response", "Kiwi itinerary missing outbound leg")
        outbound_segs = _parse_leg_segments(outbound_raw, fallback_cabin=request.cabin, notes=notes)
        if outbound_segs[0].departure_at.date() != request.depart_date:
            continue
        if not request.nearby_airports and (
            outbound_segs[0].origin != request.origin
            or outbound_segs[-1].destination != request.destination
        ):
            continue
        if request.nonstop_only and len(outbound_segs) != 1:
            continue

        segments = list(outbound_segs)
        inbound_raw = it.get("inbound")
        trip_type: Literal["one_way", "round_trip"] = "one_way"
        if inbound_raw is not None:
            trip_type = "round_trip"
            inbound_segs = _parse_leg_segments(
                inbound_raw, fallback_cabin=request.cabin, notes=notes
            )
            if (
                request.return_date is not None
                and inbound_segs[0].departure_at.date() != request.return_date
            ):
                continue
            if not request.nearby_airports and (
                inbound_segs[0].origin != request.destination
                or inbound_segs[-1].destination != request.origin
            ):
                continue
            if request.nonstop_only and len(inbound_segs) != 1:
                continue
            if inbound_segs and segments and inbound_segs[0].departure_at < segments[-1].arrival_at:
                raise TravelGatewayError(
                    "invalid_response", "Kiwi inbound segment departs before outbound arrival"
                )
            segments.extend(inbound_segs)
        elif request.return_date is not None:
            raise TravelGatewayError(
                "invalid_response", "Kiwi returned one-way itinerary for round-trip request"
            )

        carriers = {seg.operating_airline or seg.marketing_airline for seg in segments}
        if "|" in raw_id or len(carriers) > 1:
            notes.append("virtual_interline_or_multi_carrier_check_baggage_and_self_transfer")

        deep_link = validate_deep_link(it.get("bookingUrl"), allowed_host_suffixes=("kiwi.com",))
        seg_sig = "|".join(
            f"{s.origin}-{s.destination}-{s.flight_number}-{s.departure_at.isoformat()}"
            for s in segments
        )
        quote_hash = hashlib.sha256(
            f"{PROVIDER_ID}:{raw_id}:{seg_sig}:{total_minor}:{currency}".encode()
        ).hexdigest()[:16]

        quotes.append(
            FlightQuote(
                id=f"kiwi:{quote_hash}",
                segments=segments,
                trip_type=trip_type,
                travelers=request.travelers,
                fare_brand=None,
                baggage_summary=_format_baggage(it.get("baggage")),
                refundable=None,
                changeable=None,
                base_minor=None,
                taxes_minor=None,
                fees_minor=None,
                total_minor=total_minor,
                currency=currency,
                purchasable_channels=["ota_generic"],
                evidence=EvidenceMeta(
                    provider_id=PROVIDER_ID,
                    provider_quote_id=raw_id.strip(),
                    source_url="https://mcp.kiwi.com",
                    deep_link_url=deep_link,
                    retrieved_at=now,
                    expires_at=now + QUOTE_TTL,
                    status="live",
                    cache_age_seconds=0,
                    terms_version=TERMS_VERSION,
                    attribution="Kiwi.com",
                    completeness="taxes_uncertain",
                    needs_verification=True,
                    notes=list(dict.fromkeys(notes)),
                ),
            )
        )

    return quotes
