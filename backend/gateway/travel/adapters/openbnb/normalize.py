"""Normalize an ``airbnb_search`` payload into ``HotelQuote`` evidence.

Rules that make the result honest rather than merely well-typed:

* The response's own ``searchUrl`` must echo the requested dates and occupancy. A mismatch
  rejects the whole payload; an unconfirmable echo yields no priced quote at all.
* Only a stated *stay total* becomes ``total_minor``. A nightly rate is reported as an
  ``IncompleteListing`` and never multiplied, summed or shown as a total.
* Currency comes from the label (never guessed); the request's currency is not applied.
* ``completeness`` is ``complete`` only when an itemization reconciles exactly to the total
  and includes a taxes line. Otherwise it is ``taxes_uncertain`` or ``partial``.
* Status is always ``verify_required``; fixture-origin evidence is labelled as such.
* Coordinates, cancellation terms, refundability, amenities, placement and payment timing
  are left unset: the search tool does not provide them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

from pydantic import ValidationError

from gateway.travel.adapters.openbnb.contracts import (
    MAX_RESULTS,
    IncompleteListing,
    IncompleteReason,
    OpenBnBSearchResult,
    RentalSearchOutcome,
)
from gateway.travel.adapters.openbnb.links import parse_search_url, validated_listing_url
from gateway.travel.adapters.openbnb.price import (
    Breakdown,
    Money,
    PriceLabel,
    classify_price_label,
    reconcile_breakdown,
)
from gateway.travel.adapters.openbnb.requests import stay_nights
from gateway.travel.adapters.openbnb.sanitize import REDACTED, sanitize_text
from gateway.travel.adapters.openbnb.tool_policy import LISTING_ID_PATTERN
from gateway.travel.contracts import Completeness, EvidenceMeta, HotelQuote, HotelSearchRequest
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import hotel_quote_id

PROVIDER_ID = "openbnb"
Origin = Literal["synthetic_fixture", "openbnb_stdio_live"]
TERMS_VERSION = (
    "unreviewed: airbnb-tos-2026-02-05 s11.1 prohibits automated access; "
    "openbnb-mcp-0.3.0 MIT; no human approval recorded"
)
ATTRIBUTION = "Listing data from Airbnb via the unaffiliated OpenBnB community MCP"
SOURCE_METHOD_WARNING = (
    "Source method: community MCP that scrapes Airbnb web pages (not an official API). "
    "Experimental; verify price, availability and terms on Airbnb before relying on it."
)
NAME_MAX_CHARS = 120

_RATING = re.compile(r"(\d(?:\.\d{1,2})?) out of 5\b(?:[^,]*,\s*(\d[\d,]*) reviews?)?")

_BLOCKING_REASON: dict[str, IncompleteReason] = {
    "ambiguous": "price_ambiguous",
    "currency_ambiguous": "currency_ambiguous",
    "nights_mismatch": "nights_mismatch",
    "zero_price": "zero_price",
    "invalid": "price_invalid",
}


def provider_error(message: object) -> TravelGatewayError:
    """Classify an upstream ``{"error": ...}`` payload without echoing its text."""
    text = message.casefold()[:400] if isinstance(message, str) else ""
    if "robots" in text:
        return TravelGatewayError(
            "permission_denied", "OpenBnB was blocked by robots.txt; no override is permitted"
        )
    if "timeout" in text or "timed out" in text:
        return TravelGatewayError("timeout", "OpenBnB upstream request timed out")
    if "429" in text or "too many" in text:
        return TravelGatewayError("rate_limited", "OpenBnB upstream was rate limited")
    if re.search(r"http (?:401|403)\b", text):
        return TravelGatewayError("permission_denied", "OpenBnB upstream refused the request")
    if re.search(r"http 5\d\d\b", text):
        return TravelGatewayError("provider_unavailable", "OpenBnB upstream was unavailable")
    return TravelGatewayError("invalid_response", "OpenBnB upstream returned an unusable result")


def _check_search_url(url: object, request: HotelSearchRequest) -> tuple[str, bool]:
    """Return ``(url, verified)``; raise if the echo contradicts the request."""
    params = parse_search_url(url)
    if params is None:
        raise TravelGatewayError("invalid_response", "OpenBnB response has no usable search URL")
    expected = {
        "checkin": request.check_in.isoformat(),
        "checkout": request.check_out.isoformat(),
        "adults": str(request.travelers.adults),
        "children": str(request.travelers.children),
        "infants": str(request.travelers.infants),
    }
    verified = True
    for key, wanted in expected.items():
        got = params.get(key)
        if got is None:
            verified = False
        elif got != wanted:
            raise TravelGatewayError(
                "invalid_response", f"OpenBnB search URL does not match the requested {key}"
            )
    assert isinstance(url, str)
    # Keep only the parameters just verified: provider-chosen extras are not stored.
    parts = urlsplit(url)
    kept = urlencode({key: params[key] for key in expected if key in params})
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{kept}", verified


def _rating(label: str | None) -> tuple[int | None, int | None]:
    if label is None:
        return None, None
    match = _RATING.match(label)
    if match is None:
        return None, None
    score = Decimal(match.group(1))
    if not Decimal(0) <= score <= Decimal(5):
        return None, None
    scaled = int(score * 2000)  # 0..5 -> 0..10_000
    count = int(match.group(2).replace(",", "")) if match.group(2) else None
    return scaled, count


def _incomplete(
    reason: IncompleteReason,
    *,
    listing_id: str | None = None,
    title: str | None = None,
    url: str | None = None,
    nightly: Money | None = None,
) -> IncompleteListing:
    return IncompleteListing(
        listing_id=listing_id,
        title=title,
        reason=reason,
        advertised_nightly_minor=nightly.minor if nightly else None,
        currency=nightly.currency if nightly else None,
        url=url,
    )


def _choose_price(
    labels: list[PriceLabel],
) -> tuple[PriceLabel | None, IncompleteReason | None, Money | None]:
    """The single stay-total label, or a reason (and any nightly rate) why there is none."""
    for label in labels:
        reason = _BLOCKING_REASON.get(label.kind)
        if reason is not None:
            return None, reason, None
    totals = [label for label in labels if label.kind == "stay_total"]
    if totals:
        if len({label.money for label in totals}) > 1:
            return None, "price_ambiguous", None
        # The same total stated twice: a caveat on either statement applies to both.
        merged = replace(totals[0], before_taxes=any(label.before_taxes for label in totals))
        return merged, None, None
    nightly = next((label.money for label in labels if label.kind == "nightly"), None)
    if nightly is not None:
        return None, "price_nightly_only", nightly
    if any(label.kind == "unknown" for label in labels):
        return None, "price_unknown", None
    return None, "price_missing", None


def _normalize_one(
    item: OpenBnBSearchResult,
    request: HotelSearchRequest,
    *,
    now: datetime,
    origin: Origin,
    search_url: str,
    bare_dollar_currency: str | None,
) -> HotelQuote | IncompleteListing:
    if not LISTING_ID_PATTERN.fullmatch(item.id):
        return _incomplete("invalid_listing_id")
    listing_id = item.id
    link = validated_listing_url(item.url, listing_id)
    primary = item.structuredContent.primaryLine if item.structuredContent else None
    title = sanitize_text(primary.body if primary else None, max_chars=NAME_MAX_CHARS)
    if title is None:
        return _incomplete("missing_name", listing_id=listing_id, url=link)

    price = item.structuredDisplayPrice
    label_texts = [
        line.accessibilityLabel
        for line in (price.primaryLine if price else None, price.secondaryLine if price else None)
        if line is not None and line.accessibilityLabel is not None
    ]
    nights = stay_nights(request)
    labels = [
        classify_price_label(text, nights=nights, bare_dollar_currency=bare_dollar_currency)
        for text in label_texts
    ]
    chosen, reason, nightly = _choose_price(labels)
    if chosen is None or chosen.money is None:
        assert reason is not None
        return _incomplete(reason, listing_id=listing_id, title=title, url=link, nightly=nightly)
    total = chosen.money

    notes = [
        SOURCE_METHOD_WARNING,
        f"origin={origin}",
        "Total is the provider's stated stay price for the requested dates and occupancy; "
        "mandatory fees and taxes are included only as far as the completeness flag says.",
        "Provider-side location resolution is unverified; the query city is reported as given.",
    ]
    if origin == "synthetic_fixture":
        notes.append("Synthetic offline fixture; not live inventory.")
    if title == REDACTED:
        notes.append("Listing title was redacted: suspected prompt injection in host text.")
    if chosen.assumed_currency:
        notes.append(f"Currency '$' interpreted as {total.currency} by explicit configuration.")
    if total.currency != request.currency:
        notes.append(
            f"Provider currency {total.currency} kept; request currency {request.currency}; "
            "not converted."
        )
    if link is None:
        notes.append("Listing link failed validation and was dropped.")

    breakdown: Breakdown | None = None
    items_value = (
        price.explanationData.priceDetails.items
        if price and price.explanationData and price.explanationData.priceDetails
        else None
    )
    if items_value is not None:
        breakdown, why = reconcile_breakdown(
            items_value, total=total, nights=nights, bare_dollar_currency=bare_dollar_currency
        )
        if why in {"breakdown_mismatch", "nights_mismatch"}:
            return _incomplete(
                "breakdown_mismatch" if why == "breakdown_mismatch" else "nights_mismatch",
                listing_id=listing_id,
                title=title,
                url=link,
            )
        if breakdown is None:
            notes.append("Price itemization was unreadable and was ignored.")
    else:
        notes.append("Provider gave no price itemization.")

    completeness: Completeness
    if chosen.before_taxes:
        completeness = "taxes_uncertain"
        notes.append("Provider states the total is before taxes.")
    elif breakdown is None:
        completeness = "partial"
    elif breakdown.taxes_minor is None:
        completeness = "taxes_uncertain"
        notes.append("Itemization has no taxes line; taxes are unknown, not zero.")
    else:
        completeness = "complete"

    score, count = _rating(item.avgRatingA11yLabel)
    if score is not None:
        notes.append("Rating scaled from the provider label that states an out-of-5 scale.")

    property_id = f"openbnb:{listing_id}"
    evidence = EvidenceMeta(
        provider_id=PROVIDER_ID,
        provider_quote_id=listing_id,
        source_url=search_url,
        deep_link_url=link,
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
        id=hotel_quote_id(property_id, request.check_in, request.check_out, None, None),
        property_id=property_id,
        name=title,
        property_kind="vacation_rental",
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
        cancellation_summary=None,
        refundable=None,
        review_score_scaled=score,
        review_scale_source="airbnb_avg_rating_label_out_of_5" if score is not None else None,
        review_count=count if score is not None else None,
        placement="unknown",
        base_minor=breakdown.base_minor if breakdown else None,
        taxes_minor=breakdown.taxes_minor if breakdown else None,
        fees_minor=breakdown.fees_minor if breakdown else None,
        total_minor=total.minor,
        currency=total.currency,
        pay_timing="unknown",
        purchasable_channels=[],
        evidence=evidence,
    )


def parse_search_payload(
    payload: Mapping[str, Any],
    request: HotelSearchRequest,
    *,
    now: datetime,
    origin: Origin,
    bare_dollar_currency: str | None = None,
) -> RentalSearchOutcome:
    if "error" in payload:
        raise provider_error(payload.get("error"))
    raw_results = payload.get("searchResults")
    if not isinstance(raw_results, list):
        raise TravelGatewayError("invalid_response", "OpenBnB payload has no search result list")
    search_url, verified = _check_search_url(payload.get("searchUrl"), request)

    truncated = len(raw_results) > MAX_RESULTS
    quotes: list[HotelQuote] = []
    incomplete: list[IncompleteListing] = []
    seen: set[str] = set()
    malformed = 0
    for raw in raw_results[:MAX_RESULTS]:
        try:
            item = OpenBnBSearchResult.model_validate(raw)
        except ValidationError:
            malformed += 1
            incomplete.append(_incomplete("malformed_listing"))
            continue
        if item.id in seen:
            continue
        seen.add(item.id)
        if not verified:
            incomplete.append(_incomplete("request_not_verified", listing_id=item.id))
            continue
        outcome = _normalize_one(
            item,
            request,
            now=now,
            origin=origin,
            search_url=search_url,
            bare_dollar_currency=bare_dollar_currency,
        )
        if isinstance(outcome, HotelQuote):
            quotes.append(outcome)
        else:
            incomplete.append(outcome)
    if raw_results and malformed == len(raw_results[:MAX_RESULTS]):
        raise TravelGatewayError(
            "invalid_response", "OpenBnB results do not match the reviewed schema"
        )
    return RentalSearchOutcome(
        quotes=quotes, incomplete=incomplete, search_url=search_url, truncated=truncated
    )
