"""Normalization from real Seats.aero MCP ``get_flights`` payloads to Spec-16 ``AwardQuote``."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    Completeness,
    EvidenceMeta,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.mcp_readonly import (
    RawMcpToolResponse,
    parse_decimal_to_minor,
    sanitize_untrusted_text,
    validate_deep_link,
)

PROVIDER_ID = "seats_aero"
TERMS_VERSION = "seats_aero_mcp_public_noncommercial_2026_11_27"
_TAX_SUFFIX_RE = re.compile(r"\b([A-Za-z]{3})\s*$")
_URL_LINE_RE = re.compile(r"View on seats\.aero:\s*(https://seats\.aero/\S+)")
_CARRIERS_PREFIX = "Operating Carriers:"

# Programs known by Seats.aero / points community to omit or under-report carrier taxes/surcharges.
_PROGRAMS_OMITTING_FULL_TAXES = frozenset({"singapore", "krisflyer", "qatar", "turkish"})
_VALID_CABINS: frozenset[str] = frozenset({"economy", "premium", "business", "first"})


def _parse_taxes_per_passenger(raw_taxes: Any) -> tuple[int, str, bool]:
    """Return ``(minor_per_pax, currency, missing_flag)`` using Decimal minor conversion."""
    if raw_taxes is None:
        return 0, "USD", True
    if not isinstance(raw_taxes, str):
        raise TravelGatewayError(
            "invalid_response", f"Unexpected seats_aero taxes type: {raw_taxes!r}"
        )
    text = raw_taxes.strip()
    if not text:
        return 0, "USD", True
    match = _TAX_SUFFIX_RE.search(text)
    if match is None:
        raise TravelGatewayError(
            "invalid_response", f"Seats.aero taxes missing 3-letter currency: {text!r}"
        )
    ccy = match.group(1).upper()
    minor = parse_decimal_to_minor(text, ccy)
    return minor, ccy, False


def _extract_ndjson_and_metadata(
    raw: RawMcpToolResponse,
) -> tuple[list[dict[str, Any]], str | None, dict[str, str], list[str]]:
    """Parse Seats.aero's real live ``get_flights`` NDJSON + footer text format."""
    if raw.structured_content is not None and isinstance(
        raw.structured_content.get("flights"), list
    ):
        rows = [r for r in raw.structured_content["flights"] if isinstance(r, dict)]
        url = raw.structured_content.get("url")
        return rows, str(url) if url else None, {}, []

    flights: list[dict[str, Any]] = []
    view_url: str | None = None
    carrier_names: dict[str, str] = {}
    extra_notes: list[str] = []

    for block in raw.text_blocks:
        for line in block.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith(_CARRIERS_PREFIX):
                json_part = stripped[len(_CARRIERS_PREFIX) :].strip()
                try:
                    parsed_map = json.loads(json_part)
                    if isinstance(parsed_map, dict):
                        carrier_names.update(
                            {str(k): str(v) for k, v in parsed_map.items() if isinstance(k, str)}
                        )
                except json.JSONDecodeError as exc:
                    raise TravelGatewayError(
                        "invalid_response", f"Malformed Seats.aero Operating Carriers footer: {exc}"
                    ) from exc
                continue
            url_match = _URL_LINE_RE.search(stripped)
            if url_match is not None:
                view_url = url_match.group(1)
                continue
            if stripped.startswith("{"):
                try:
                    obj = json.loads(stripped, parse_float=Decimal)
                except json.JSONDecodeError as exc:
                    raise TravelGatewayError(
                        "invalid_response", f"Malformed Seats.aero JSON line: {exc}"
                    ) from exc
                if not isinstance(obj, dict):
                    raise TravelGatewayError(
                        "invalid_response", "Seats.aero line was not a JSON object"
                    )
                if "flight_ref" in obj:
                    flights.append(obj)
                continue
            brace_pos = stripped.find('{"flight_ref"')
            if brace_pos != -1:
                prefix_note = sanitize_untrusted_text(stripped[:brace_pos])
                if prefix_note:
                    extra_notes.append(f"provider_notice:{prefix_note[:160]}")
                json_slice = stripped[brace_pos:]
                try:
                    obj = json.loads(json_slice, parse_float=Decimal)
                except json.JSONDecodeError as exc:
                    raise TravelGatewayError(
                        "invalid_response", f"Malformed Seats.aero inline JSON record: {exc}"
                    ) from exc
                if isinstance(obj, dict):
                    flights.append(obj)
                continue
            # Genuine empty-results message from live/fixture payload without failing closed.
            lowered = stripped.casefold()
            if (
                "no flights" in lowered
                or "0 results" in lowered
                or "more results not shown" in lowered
            ):
                sanitized_note = sanitize_untrusted_text(stripped)
                if sanitized_note:
                    extra_notes.append(sanitized_note[:160])
                continue
            if not flights:
                # Non-empty unstructured text that is neither an empty notice nor a JSON row.
                raise TravelGatewayError(
                    "invalid_response",
                    f"Seats.aero returned unstructured non-JSON content: {stripped[:120]!r}",
                )

    return flights, view_url, carrier_names, extra_notes


def normalize_seats_aero_awards(
    raw: RawMcpToolResponse,
    request: AwardSearchRequest,
    *,
    now: datetime,
) -> list[AwardQuote]:
    """Normalize real Seats.aero ``get_flights`` rows into Spec-16 ``AwardQuote`` list."""
    if request.return_date is not None:
        raise TravelGatewayError(
            "unsupported_domain",
            "seats_aero searches one-way awards only; compose return leg separately",
        )

    rows, raw_view_url, carrier_names, extra_notes = _extract_ndjson_and_metadata(raw)
    source_url = (
        validate_deep_link(raw_view_url, allowed_host_suffixes=("seats.aero",))
        or "https://seats.aero/mcp"
    )

    party_seats = request.travelers.adults + request.travelers.children
    if party_seats <= 0:
        party_seats = 1

    requested_programs = {p.strip().lower() for p in request.program_ids if p.strip()}
    quotes: list[AwardQuote] = []

    for row in rows:
        flight_ref = row.get("flight_ref")
        origin = row.get("origin")
        destination = row.get("destination")
        cabin_raw = row.get("cabin")
        departs_at = row.get("departs_at")
        miles_price = row.get("miles_price")
        mileage_program = row.get("mileage_program")

        if (
            not isinstance(flight_ref, str)
            or not flight_ref.strip()
            or not isinstance(origin, str)
            or not isinstance(destination, str)
            or not isinstance(cabin_raw, str)
            or not isinstance(departs_at, str)
            or isinstance(miles_price, bool)
            or not isinstance(miles_price, int)
            or miles_price < 0
            or not isinstance(mileage_program, str)
            or not mileage_program.strip()
        ):
            raise TravelGatewayError(
                "invalid_response",
                "Seats.aero flight row missing required fields or invalid miles_price",
            )

        cabin_norm = cabin_raw.strip().lower()
        if cabin_norm not in _VALID_CABINS:
            raise TravelGatewayError("invalid_response", f"Invalid Seats.aero cabin: {cabin_raw!r}")
        program_norm = mileage_program.strip().lower()

        if (
            origin.strip().upper() != request.origin
            or destination.strip().upper() != request.destination
        ):
            continue
        if cabin_norm != request.cabin:
            continue
        if requested_programs and program_norm not in requested_programs:
            continue

        try:
            depart_dt = date.fromisoformat(departs_at.strip()[:10])
        except ValueError as exc:
            raise TravelGatewayError(
                "invalid_response", f"Invalid Seats.aero departs_at date: {departs_at!r}"
            ) from exc
        if depart_dt != request.depart_date:
            continue

        minutes_old_raw = row.get("minutes_old")
        if (
            minutes_old_raw is None
            or isinstance(minutes_old_raw, bool)
            or not isinstance(minutes_old_raw, int)
        ):
            raise TravelGatewayError(
                "invalid_response", "Seats.aero row missing integer minutes_old"
            )
        if minutes_old_raw < 0:
            raise TravelGatewayError("invalid_response", f"Negative minutes_old: {minutes_old_raw}")

        remaining = row.get("remaining_seats")
        if remaining is not None and (
            isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0
        ):
            raise TravelGatewayError("invalid_response", f"Invalid remaining_seats: {remaining!r}")
        if remaining is not None and remaining < party_seats:
            continue

        tax_per_pax_minor, fees_ccy, taxes_missing = _parse_taxes_per_passenger(row.get("taxes"))
        total_miles = miles_price * party_seats
        total_fees_minor = tax_per_pax_minor * party_seats

        carriers_raw = row.get("operating_carriers") or []
        if not isinstance(carriers_raw, list):
            raise TravelGatewayError(
                "invalid_response", "Seats.aero operating_carriers must be a list"
            )
        sanitized_carriers = [
            sanitized
            for c in carriers_raw
            if isinstance(c, str) and (sanitized := sanitize_untrusted_text(c))
        ]
        operating_airline = ", ".join(sanitized_carriers) if sanitized_carriers else None

        mixed_pct = row.get("mixed_cabin_pct")
        mixed_cabin = (
            bool(mixed_pct > 0)
            if isinstance(mixed_pct, int) and not isinstance(mixed_pct, bool)
            else None
        )

        notes = list(extra_notes)
        completeness: Completeness = "complete"
        if taxes_missing:
            completeness = "fees_uncertain"
            notes.append("taxes_absent_from_provider")
        elif program_norm in _PROGRAMS_OMITTING_FULL_TAXES:
            completeness = "fees_uncertain"
            notes.append(f"program_may_omit_taxes:{program_norm}")

        if row.get("stops") is not None:
            notes.append(f"stops:{row['stops']}")
        if row.get("flights"):
            flights_str = sanitize_untrusted_text(str(row["flights"]))
            if flights_str:
                notes.append(f"flights:{flights_str}")
        if sanitized_carriers:
            expanded = [
                f"{c}={sanitize_untrusted_text(carrier_names[c])}"
                for c in sanitized_carriers
                if c in carrier_names
            ]
            if expanded:
                notes.append(f"carriers:{','.join(expanded)}")
        notes.append("cached_availability_verify_with_mileage_program_before_transfer")

        deep_link = (
            validate_deep_link(
                f"https://seats.aero/i/{flight_ref.strip()}", allowed_host_suffixes=("seats.aero",)
            )
            or source_url
        )
        quote_hash = hashlib.sha256(
            f"{PROVIDER_ID}:{flight_ref}:{program_norm}:{party_seats}".encode()
        ).hexdigest()[:16]

        quotes.append(
            AwardQuote(
                id=f"seats_aero:{quote_hash}",
                program_id=program_norm,
                origin=origin.strip().upper(),
                destination=destination.strip().upper(),
                depart_date=depart_dt,
                return_date=None,
                cabin=request.cabin,
                travelers=request.travelers,
                seats_available=remaining,
                miles_total=total_miles,
                fees_minor=total_fees_minor,
                fees_currency=fees_ccy,
                operating_airline=operating_airline,
                mixed_cabin=mixed_cabin,
                evidence=EvidenceMeta(
                    provider_id=PROVIDER_ID,
                    provider_quote_id=flight_ref.strip(),
                    source_url=source_url,
                    deep_link_url=deep_link,
                    retrieved_at=now,
                    expires_at=None,
                    status="cached",
                    cache_age_seconds=minutes_old_raw * 60,
                    terms_version=TERMS_VERSION,
                    attribution="Seats.aero",
                    completeness=completeness,
                    needs_verification=True,
                    notes=notes,
                ),
            )
        )

    return quotes
