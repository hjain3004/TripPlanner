"""Normalization from real Trivago MCP search responses to Spec-16 ``HotelQuote``."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal

from gateway.travel.contracts import EvidenceMeta, HotelQuote, HotelSearchRequest, PropertyKind
from gateway.travel.errors import TravelGatewayError
from gateway.travel.mcp_readonly import (
    REDACTED,
    RawMcpToolResponse,
    parse_decimal_to_minor,
    sanitize_untrusted_text,
    validate_deep_link,
)

PROVIDER_ID = "trivago"
TERMS_VERSION = "trivago_mcp_public_noncommercial_2026_11_27"
REVIEW_SCALE_SOURCE = "trivago_0_10_rating_index"
QUOTE_TTL = timedelta(minutes=15)
_TRIVAGO_DEEP_LINK_SUFFIXES = (
    "trivago.com",
    "trivago.in",
    "trivago.co.uk",
    "trivago.de",
    "trivago.sg",
)


def _extract_trivago_hotels(raw: RawMcpToolResponse) -> list[dict[str, Any]]:
    """Strip prompt preamble / discard ``system_message`` and parse ``output`` list."""
    outer: dict[str, Any] | None = None
    if raw.structured_content is not None:
        outer = raw.structured_content
    else:
        for block in raw.text_blocks:
            stripped = block.strip()
            if not stripped:
                continue
            brace_idx = stripped.find("{")
            if brace_idx == -1:
                continue
            try:
                candidate = json.loads(stripped[brace_idx:], parse_float=Decimal)
            except json.JSONDecodeError as exc:
                raise TravelGatewayError(
                    "invalid_response", f"Trivago outer payload is not valid JSON: {exc}"
                ) from exc
            if isinstance(candidate, dict):
                outer = candidate
                break

    if outer is None:
        raise TravelGatewayError("invalid_response", "Trivago returned no parsable JSON payload")

    # Discard untrusted ``system_message`` formatting prompt; read only structured ``output``.
    output = outer.get("output")
    if output is None:
        return []
    if isinstance(output, str):
        stripped_out = output.strip()
        if not stripped_out:
            return []
        try:
            output = json.loads(stripped_out, parse_float=Decimal)
        except json.JSONDecodeError as exc:
            raise TravelGatewayError(
                "invalid_response", f"Trivago output field is not valid JSON: {exc}"
            ) from exc
    if not isinstance(output, list):
        raise TravelGatewayError("invalid_response", "Trivago output field is not a JSON list")
    return [row for row in output if isinstance(row, dict)]


def _parse_review_score(raw_rating: Any) -> tuple[int | None, str | None]:
    if raw_rating is None or isinstance(raw_rating, bool):
        return None, None
    try:
        dec = Decimal(str(raw_rating).strip())
    except InvalidOperation:
        return None, None
    if not dec.is_finite() or dec < Decimal("0") or dec > Decimal("10"):
        return None, None
    scaled = int((dec * Decimal("1000")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return scaled, REVIEW_SCALE_SOURCE


def _parse_review_count(raw_count: Any) -> int | None:
    if raw_count is None or isinstance(raw_count, bool):
        return None
    if isinstance(raw_count, int):
        return raw_count if raw_count >= 0 else None
    if isinstance(raw_count, str):
        digits = raw_count.replace(",", "").strip()
        if digits.isdigit():
            return int(digits)
    return None


def _infer_property_kind(name: str) -> PropertyKind:
    lowered = name.casefold()
    if "hostel" in lowered:
        return "hostel"
    if "serviced apartment" in lowered or "apart" in lowered:
        return "serviced_apartment"
    return "hotel"


def _parse_lat_lon(val: Any) -> float | None:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, (int, Decimal)):
        return float(val)
    return None


def normalize_trivago_hotels(
    raw: RawMcpToolResponse,
    request: HotelSearchRequest,
    *,
    now: datetime,
) -> list[HotelQuote]:
    """Normalize real Trivago MCP accommodation deals into Spec-16 ``HotelQuote`` list."""
    hotels = _extract_trivago_hotels(raw)
    quotes: list[HotelQuote] = []

    for hotel in hotels:
        acc_id = hotel.get("accommodation_id")
        raw_name = hotel.get("accommodation_name")
        arrival_raw = hotel.get("arrival")
        departure_raw = hotel.get("departure")
        deals = hotel.get("deals")

        if (
            not isinstance(acc_id, str)
            or not acc_id.strip()
            or not isinstance(raw_name, str)
            or not raw_name.strip()
            or not isinstance(arrival_raw, str)
            or not isinstance(departure_raw, str)
            or not isinstance(deals, list)
        ):
            raise TravelGatewayError(
                "invalid_response", "Trivago hotel row missing required identity, dates, or deals"
            )

        try:
            check_in = date.fromisoformat(arrival_raw.strip()[:10])
            check_out = date.fromisoformat(departure_raw.strip()[:10])
        except ValueError as exc:
            raise TravelGatewayError(
                "invalid_response", f"Invalid Trivago stay dates: {exc}"
            ) from exc
        if check_out <= check_in:
            raise TravelGatewayError("invalid_response", "Trivago check_out must be after check_in")
        if (check_in, check_out) != (request.check_in, request.check_out):
            raise TravelGatewayError(
                "invalid_response",
                f"Trivago stay dates {check_in}..{check_out} mismatch request "
                f"{request.check_in}..{request.check_out}",
            )

        name = sanitize_untrusted_text(raw_name) or ""
        if not name:
            raise TravelGatewayError("invalid_response", "Trivago accommodation_name empty")

        city_raw = hotel.get("country_city")
        city = sanitize_untrusted_text(str(city_raw)) if city_raw else request.city
        city_clean = city or request.city

        prop_kind = _infer_property_kind(name)
        if request.property_kinds and prop_kind not in request.property_kinds:
            continue

        review_scaled, review_scale_source = _parse_review_score(hotel.get("review_rating"))
        review_count = _parse_review_count(hotel.get("review_count"))
        lat = _parse_lat_lon(hotel.get("latitude"))
        lon = _parse_lat_lon(hotel.get("longitude"))

        base_notes: list[str] = ["taxes_and_resort_fees_scope_unconfirmed_check_advertiser"]
        if name == REDACTED:
            base_notes.append("suspected_prompt_injection_redacted")
        if hotel.get("top_amenities"):
            amenities = sanitize_untrusted_text(str(hotel["top_amenities"]))
            if amenities:
                base_notes.append(f"amenities:{amenities}")
                if amenities == REDACTED:
                    base_notes.append("suspected_prompt_injection_redacted")
        if hotel.get("distance"):
            dist = sanitize_untrusted_text(str(hotel["distance"]))
            if dist:
                base_notes.append(f"location:{dist}")

        for deal_idx, deal in enumerate(deals):
            if not isinstance(deal, dict):
                raise TravelGatewayError("invalid_response", "Trivago deal item is not an object")
            price_stay = deal.get("price_per_stay")
            currency_raw = deal.get("currency")
            advertiser_raw = deal.get("advertiser")
            if (
                price_stay is None
                or not isinstance(currency_raw, str)
                or len(currency_raw.strip()) != 3
                or not isinstance(advertiser_raw, str)
                or not advertiser_raw.strip()
            ):
                raise TravelGatewayError(
                    "invalid_response",
                    "Trivago deal missing price_per_stay, 3-letter currency, or advertiser",
                )

            deal_ccy = currency_raw.strip().upper()
            total_minor = parse_decimal_to_minor(price_stay, deal_ccy)
            advertiser = sanitize_untrusted_text(advertiser_raw) or "Trivago partner"

            attr_ids: set[str] = set()
            attr_names: list[str] = []
            for attr in deal.get("price_attributes") or []:
                if isinstance(attr, dict):
                    aid = attr.get("id")
                    aname = attr.get("name")
                    if isinstance(aid, str):
                        attr_ids.add(aid)
                    if isinstance(aname, str):
                        s_name = sanitize_untrusted_text(aname)
                        if s_name:
                            attr_names.append(s_name)

            refundable: bool | None = None
            cancellation_summary: str | None = None
            if "freeCancellation" in attr_ids:
                refundable = True
                cancellation_summary = "Free cancellation"
            elif "nonRefundable" in attr_ids:
                refundable = False
                cancellation_summary = "Non-refundable"

            pay_timing: Literal["now", "property", "mixed", "unknown"] = (
                "property" if "payAtProperty" in attr_ids else "unknown"
            )
            rate_plan = " · ".join([advertiser, *attr_names]) if attr_names else advertiser
            deep_link = validate_deep_link(
                deal.get("deal_url"),
                allowed_host_suffixes=_TRIVAGO_DEEP_LINK_SUFFIXES,
            )

            deal_notes = list(base_notes)
            if advertiser == REDACTED:
                deal_notes.append("suspected_prompt_injection_redacted")
            if deal_ccy != request.currency:
                deal_notes.append(
                    f"source_currency_differs_from_request:{deal_ccy}!={request.currency}"
                )

            quote_hash = hashlib.sha256(
                f"{PROVIDER_ID}:{acc_id}:{check_in.isoformat()}:{check_out.isoformat()}:"
                f"{deal_idx}:{advertiser}:{total_minor}:{deal_ccy}".encode()
            ).hexdigest()[:16]

            quotes.append(
                HotelQuote(
                    id=f"trivago:{quote_hash}",
                    property_id=acc_id.strip(),
                    name=name,
                    property_kind=prop_kind,
                    city=city_clean,
                    area_id=None,
                    lat=lat,
                    lon=lon,
                    check_in=check_in,
                    check_out=check_out,
                    travelers=request.travelers,
                    rooms=request.rooms,
                    room_name=None,
                    rate_plan=rate_plan,
                    cancellation_summary=cancellation_summary,
                    refundable=refundable,
                    review_score_scaled=review_scaled,
                    review_scale_source=review_scale_source,
                    review_count=review_count,
                    placement="unknown",
                    base_minor=None,
                    taxes_minor=None,
                    fees_minor=None,
                    total_minor=total_minor,
                    currency=deal_ccy,
                    pay_timing=pay_timing,
                    purchasable_channels=["ota_generic"],
                    evidence=EvidenceMeta(
                        provider_id=PROVIDER_ID,
                        provider_quote_id=f"{acc_id.strip()}:{advertiser}",
                        source_url="https://mcp.trivago.com/mcp",
                        deep_link_url=deep_link,
                        retrieved_at=now,
                        expires_at=now + QUOTE_TTL,
                        status="live",
                        cache_age_seconds=0,
                        terms_version=TERMS_VERSION,
                        attribution=f"Trivago ({advertiser})",
                        completeness="taxes_uncertain",
                        needs_verification=True,
                        notes=list(dict.fromkeys(deal_notes)),
                    ),
                )
            )

    return quotes
