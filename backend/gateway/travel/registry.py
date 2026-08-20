"""Static validated travel provider registry — spec 16 §7/§15.

Built as typed Python (mirroring the existing gateway/places/registry.py
precedent) rather than loaded from YAML, so no second registry-loading
mechanism is introduced in this codebase. Unknown cost means disabled:
``monthly_cost_minor`` has no default, so a caller that cannot state a
monthly ceiling cannot construct an enabled entry.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Domain = Literal["flight", "flight_trend", "hotel", "award", "fx", "poi"]
SourceMethod = Literal[
    "sample", "official_api", "provider_mcp", "community_mcp", "scraper_wrapper", "open_data"
]


class TravelProviderRegistryEntry(BaseModel):
    provider_id: str = Field(min_length=1)
    enabled: bool = False
    allowed_profiles: set[Literal["student_noncommercial", "commercial_production"]]
    domains: set[Domain]
    countries: set[str] | Literal["configured"] = "configured"
    source_method: SourceMethod
    live_data: bool = False
    monthly_cost_minor: int = Field(ge=0)
    priority: int = 100


class TravelProviderRegistry(BaseModel):
    entries: list[TravelProviderRegistryEntry] = Field(default_factory=list)

    def select_providers(
        self, *, active_profile: str, domain: Domain, country: str
    ) -> list[TravelProviderRegistryEntry]:
        eligible = []
        for entry in self.entries:
            if not entry.enabled:
                continue
            if active_profile not in entry.allowed_profiles:
                continue
            if domain not in entry.domains:
                continue
            if entry.countries != "configured" and country not in entry.countries:
                continue
            eligible.append(entry)
        eligible.sort(key=lambda e: (e.priority, e.provider_id))
        return eligible

    def get_entry(self, provider_id: str) -> TravelProviderRegistryEntry:
        for entry in self.entries:
            if entry.provider_id == provider_id:
                return entry
        from gateway.travel.errors import TravelGatewayError

        raise TravelGatewayError("provider_unavailable", f"Unknown provider_id: {provider_id}")


def get_default_travel_registry() -> TravelProviderRegistry:
    sample = TravelProviderRegistryEntry(
        provider_id="sample_travel_adapter",
        enabled=True,
        allowed_profiles={"student_noncommercial", "commercial_production"},
        domains={"flight", "hotel", "award"},
        countries="configured",
        source_method="sample",
        live_data=False,
        monthly_cost_minor=0,
        priority=999,
    )
    return TravelProviderRegistry(entries=[sample])
