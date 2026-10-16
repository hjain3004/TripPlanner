"""Internal and display-safe G3.4 inventory products.

Raw adapter objects are intentionally kept behind these contracts.  The public
summary is additive to the Kernel report and contains no SDK payloads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from gateway.travel.contracts import (
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
    Status,
)
from gateway.travel.freshness import compute_status


class QuotePriceScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    basis: Literal["sample_per_traveler_trip", "sample_nightly_stay", "party_total", "unknown"]
    scope_verified: bool = False
    travelers: int | None = Field(default=None, ge=1)
    rooms: int | None = Field(default=None, ge=1)

    @property
    def cost_eligible(self) -> bool:
        return self.basis in {"sample_per_traveler_trip", "sample_nightly_stay"} or (
            self.basis == "party_total" and self.scope_verified
        )


class GatewayDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    domain: Literal["flight", "hotel", "general"]
    message: str
    provider_id: str | None = None


class InventoryQuoteSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: Literal["flight", "hotel"]
    quote_id: str
    provider_id: str
    provider_quote_id: str | None = None
    status: str
    needs_verification: bool
    source_url: str | None = None
    deep_link_url: str | None = None
    attribution: str | None = None
    retrieved_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    completeness: str
    source_amount_minor: int
    source_currency: str
    converted_amount_minor: int | None = None
    price_scope: QuotePriceScope
    selected: bool = False
    alternative: bool = True
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def public_evidence_is_honest(self) -> InventoryQuoteSummary:
        if self.provider_id.startswith("sample_") and self.status == "live":
            raise ValueError("sample evidence cannot claim live status")
        if self.source_url is not None and not self.source_url.startswith("https://"):
            raise ValueError("public source links must be HTTPS")
        if self.deep_link_url is not None and not self.deep_link_url.startswith("https://"):
            raise ValueError("public deep links must be HTTPS")
        return self


class TravelInventorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight: InventoryQuoteSummary | None = None
    hotel: InventoryQuoteSummary | None = None
    alternatives: list[InventoryQuoteSummary] = Field(default_factory=list)
    diagnostics: list[GatewayDiagnostic] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    reference_only_awards: bool = True
    inventory_revision: int = Field(default=1, ge=1)


class TravelInventorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flight_request: FlightSearchRequest
    hotel_request: HotelSearchRequest
    flights: list[FlightQuote] = Field(default_factory=list)
    hotels: list[HotelQuote] = Field(default_factory=list)
    flight_scopes: dict[str, QuotePriceScope] = Field(default_factory=dict)
    hotel_scopes: dict[str, QuotePriceScope] = Field(default_factory=dict)
    diagnostics: list[GatewayDiagnostic] = Field(default_factory=list)
    retrieved_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    inventory_revision: int = Field(default=1, ge=1)

    def is_current(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at

    def status(
        self,
        quote_status: Status,
        retrieved_at: datetime,
        now: datetime,
        expires_at: datetime | None,
    ) -> Status:
        return compute_status(
            source_status=quote_status, retrieved_at=retrieved_at, expires_at=expires_at, now=now
        )
