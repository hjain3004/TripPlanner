"""Normalize the observed dated-rate Markdown, never inferred search prices."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from gateway.travel.adapters.gondola.hotel_discovery import GondolaHotelRateObservation
from gateway.travel.adapters.gondola.sanitize import sanitize_provider_text
from gateway.travel.contracts import EvidenceMeta, HotelQuote, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import hotel_quote_id

_HEADER = re.compile(r"^## Hotel Rates \(ID: ([0-9]{1,18})\)[ \t]*$", re.MULTILINE)
_STAY = re.compile(
    r"^\*\*Stay:\*\* ([0-9]{4}-[0-9]{2}-[0-9]{2}) to "
    r"([0-9]{4}-[0-9]{2}-[0-9]{2}) \| ([0-9]{1,2}) adults?[ \t]*$",
    re.MULTILINE,
)
_AMOUNT = r"(?:0|[1-9][0-9]{0,8}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,3})(?:\.[0-9]{1,2})?"
_RATE = re.compile(
    r"^- \*\*(?P<label>Cheapest non-refundable|Cheapest refundable|Other rate):\*\* "
    r"`rate_id[=:][ ]?[^`\r\n]{1,8192}` \*\*(?P<currency>[A-Z]{3}) "
    + _AMOUNT
    + r"/night\*\* \(total: (?P<total_currency>[A-Z]{3}) (?P<total>"
    + _AMOUNT
    + r")\) (?P<conditions>[^\r\n]{1,4096})$"
)
# Only reviewed two-decimal currencies; never assume an exponent for a new code.
_TWO_DECIMAL = frozenset({"SGD", "INR", "USD", "EUR", "GBP", "AED"})


def _minor(text: str) -> int:
    whole, _, fraction = text.replace(",", "").partition(".")
    return int(whole) * 100 + int(fraction.ljust(2, "0") or "0")


def _public_conditions(text: str) -> str | None:
    # Keep the stated policy text, not capability URLs or additional tokens.
    text = re.sub(r"https?://[^\s<>]+", "[link omitted]", text)
    text = re.sub(
        r"(?i)(?:rate_id|selection_token|booking_token)\s*[=:]\s*[^\s|]+",
        "[token omitted]",
        text,
    )
    return sanitize_provider_text(text)


def parse_dated_hotel_rates(
    observation: GondolaHotelRateObservation,
    request: HotelSearchRequest,
    *,
    retrieved_at: datetime,
    origin: str,
) -> list[HotelQuote]:
    """Keep reported stay totals as unverified alternatives, not final costs.

    The observed rate response does not establish tax/fee coverage or a
    purchasable channel. Those fields stay unknown; no nightly multiplication
    or promotion to a complete/payable quote takes place.
    """
    text = observation.payload.get("result")
    if not isinstance(text, str) or len(text.encode("utf-8")) > 512_000:
        raise TravelGatewayError("invalid_response", "Invalid Gondola dated hotel rates")
    headers, stays = _HEADER.findall(text), _STAY.findall(text)
    if (
        headers != [str(observation.candidate.hotel_id)]
        or len(stays) != 1
        or stays[0]
        != (
            request.check_in.isoformat(),
            request.check_out.isoformat(),
            str(request.travelers.adults),
        )
        or observation.check_in != request.check_in
        or observation.check_out != request.check_out
        or observation.adults != request.travelers.adults
        or request.rooms != 1
        or request.travelers.children
        or request.travelers.infants
    ):
        raise TravelGatewayError("invalid_response", "Gondola hotel rate identity mismatch")
    room: str | None = None
    quotes: list[HotelQuote] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#### "):
            room = sanitize_provider_text(line[5:])
            continue
        match = _RATE.fullmatch(line)
        if not match or not room:
            continue
        currency = match["currency"]
        if currency != match["total_currency"] or currency not in _TWO_DECIMAL:
            continue
        amount = _minor(match["total"])
        if amount <= 0:
            continue
        conditions = _public_conditions(match["conditions"])
        if not conditions:
            continue
        refundable: bool | None = None
        if conditions.startswith("Non-refundable"):
            refundable = False
        elif conditions.startswith("Refundable"):
            refundable = True
        # Identity uses public rate semantics, never the provider's signed rate token.
        rate_plan = hashlib.sha256(
            f"{room}|{match['label']}|{currency}|{amount}|{conditions}".encode()
        ).hexdigest()[:24]
        quote_id = hotel_quote_id(
            str(observation.candidate.hotel_id),
            request.check_in,
            request.check_out,
            room,
            rate_plan,
        )
        if quote_id in seen:
            continue
        seen.add(quote_id)
        quotes.append(
            HotelQuote(
                id=quote_id,
                property_id=str(observation.candidate.hotel_id),
                name=observation.candidate.name,
                property_kind="hotel",
                city=request.city,
                check_in=request.check_in,
                check_out=request.check_out,
                travelers=request.travelers,
                rooms=1,
                room_name=room,
                rate_plan=rate_plan,
                cancellation_summary=conditions,
                refundable=refundable,
                placement="unknown",
                total_minor=amount,
                currency=currency,
                pay_timing="unknown",
                purchasable_channels=[],
                evidence=EvidenceMeta(
                    provider_id="gondola",
                    provider_quote_id=quote_id,
                    source_url="https://mcp.gondola.ai/mcp/auth",
                    retrieved_at=retrieved_at,
                    expires_at=None,
                    status="verify_required",
                    terms_version="gondola-mcp-v1",
                    attribution="Gondola",
                    completeness="taxes_uncertain",
                    needs_verification=True,
                    notes=[
                        f"origin={origin}",
                        "Provider-reported dated stay total; tax and fee coverage is unverified.",
                        "Cancellation conditions may be estimated; verify with the provider.",
                        "City-scoped discovery; requested area/style/currency filters "
                        "were not applied.",
                        "Alternative only; excluded from payable budget and card recommendations.",
                    ],
                ),
            )
        )
    if not quotes:
        raise TravelGatewayError(
            "invalid_response", "No explicit supported Gondola cash stay totals"
        )
    return quotes
