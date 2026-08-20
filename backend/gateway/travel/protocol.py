"""Travel provider adapter protocol — spec 16 §6.

An adapter may implement only its declared domains; unsupported calls raise a
typed ``unsupported_domain`` error (see ``gateway.travel.errors``). Provider
SDK objects never escape the adapter — every method returns spec 16 normalized
contracts only.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    FlexibleFlightSearchRequest,
    FlightPriceObservation,
    FlightQuote,
    FlightSearchRequest,
    HotelQuote,
    HotelSearchRequest,
)

Domain = Literal["flight", "flight_trend", "hotel", "award", "fx", "poi"]
SourceMethod = Literal[
    "sample", "official_api", "provider_mcp", "community_mcp", "scraper_wrapper", "open_data"
]


class AdapterCapabilities(BaseModel):
    provider_id: str = Field(min_length=1)
    domains: set[Domain]
    countries: set[str] | Literal["configured"]
    live_data: bool
    supports_cache: bool
    supports_commercial_use: bool
    allowed_profiles: set[Literal["student_noncommercial", "commercial_production"]]
    source_method: SourceMethod
    stability: Literal["stable", "experimental"]
    requires_user_initiated_search: bool
    max_concurrency: int = Field(ge=1)


class TravelProviderAdapter(Protocol):
    capabilities: AdapterCapabilities

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]: ...

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]: ...

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]: ...

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]: ...
