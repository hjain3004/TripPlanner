"""OpenBnB-native response contracts, kept apart from the normalized ``HotelQuote``.

Only the key paths that upstream's ``allowSearchResultSchema`` / ``allowSectionSchema``
copy are modelled (source-verified at v0.3.0). The *leaf value shapes* beneath them -- the
wording of price and rating labels, whether ``location`` carries coordinates -- have not
been captured from a live response, so everything here is bounded, strict about types, and
ignores unknown keys; the fixtures that exercise it are synthetic and say so.

Provider payloads are untrusted: every string has a length bound, and a result that does
not fit is reported as malformed rather than coerced.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from gateway.travel.contracts import HotelQuote

MAX_PAYLOAD_BYTES = 512_000
MAX_RESULTS = 40


class _Native(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class OpenBnBPriceLine(_Native):
    accessibilityLabel: StrictStr | None = Field(default=None, max_length=300)


class OpenBnBBodyLine(_Native):
    body: StrictStr | None = Field(default=None, max_length=400)


class OpenBnBPriceDetails(_Native):
    # Upstream flattens ``items`` arrays to one ", "-joined string; the list form is kept
    # only in case a future version stops flattening.
    items: StrictStr | list[dict[str, Any]] | None = None


class OpenBnBExplanation(_Native):
    title: StrictStr | None = Field(default=None, max_length=200)
    priceDetails: OpenBnBPriceDetails | None = None


class OpenBnBStructuredPrice(_Native):
    primaryLine: OpenBnBPriceLine | None = None
    secondaryLine: OpenBnBPriceLine | None = None
    explanationData: OpenBnBExplanation | None = None


class OpenBnBStructuredContent(_Native):
    primaryLine: OpenBnBBodyLine | None = None


class OpenBnBSearchResult(_Native):
    id: StrictStr = Field(max_length=64)
    url: StrictStr | None = Field(default=None, max_length=2048)
    structuredContent: OpenBnBStructuredContent | None = None
    avgRatingA11yLabel: StrictStr | None = Field(default=None, max_length=300)
    structuredDisplayPrice: OpenBnBStructuredPrice | None = None


IncompleteReason = Literal[
    "malformed_listing",
    "invalid_listing_id",
    "missing_name",
    "request_not_verified",
    "price_missing",
    "price_unknown",
    "price_nightly_only",
    "price_ambiguous",
    "price_invalid",
    "currency_ambiguous",
    "nights_mismatch",
    "zero_price",
    "breakdown_mismatch",
]


class IncompleteListing(BaseModel):
    """A discovered listing that cannot honestly become a ``HotelQuote``.

    The shared ``HotelQuote`` requires a stay total; a nightly advertised rate or an
    unverifiable price is *discovery-only* evidence. It is reported here, labelled, and
    never turned into a priced quote (a documented gap in the shared contract, not
    something this adapter papers over).
    """

    model_config = ConfigDict(frozen=True)
    listing_id: str | None = None
    title: str | None = None
    reason: IncompleteReason
    advertised_nightly_minor: int | None = Field(default=None, gt=0)
    currency: str | None = None
    url: str | None = None


class RentalSearchOutcome(BaseModel):
    quotes: list[HotelQuote] = Field(default_factory=list)
    incomplete: list[IncompleteListing] = Field(default_factory=list)
    search_url: str | None = None
    truncated: bool = False


class OpenBnBListingDetail(BaseModel):
    """Read-only facts from ``airbnb_listing_details`` (coordinates, amenity text)."""

    model_config = ConfigDict(frozen=True)
    listing_id: str
    lat: float | None = None
    lon: float | None = None
    location_title: str | None = None
    amenities: list[str] = Field(default_factory=list)
    unavailable_amenities: list[str] = Field(default_factory=list)
