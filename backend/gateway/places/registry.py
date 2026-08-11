from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class PlaceGatewayError(Exception):
    def __init__(
        self,
        code: Literal[
            "provider_unavailable",
            "authentication_failed",
            "permission_denied",
            "rate_limited",
            "budget_exhausted",
            "timeout",
            "invalid_response",
            "no_results",
            "unsupported_domain",
            "region_restricted",
            "terms_disabled",
        ],
        message: str,
    ):
        super().__init__(message)
        self.code = code
        self.message = message


class AdapterCapabilities(BaseModel):
    domains: list[str] = Field(default_factory=list)
    supported_countries: list[str] = Field(default_factory=list)


class ProviderRegistryEntry(BaseModel):
    provider_id: str
    enabled: bool = False
    allowed_profiles: list[str] = Field(default_factory=list)
    capabilities: AdapterCapabilities = Field(default_factory=AdapterCapabilities)
    priority: int = 100
    remaining_quota: int = 0
    remaining_budget: int = 0


class ProviderRegistry(BaseModel):
    entries: list[ProviderRegistryEntry] = Field(default_factory=list)

    def select_providers(
        self,
        active_profile: str,
        domain: str,
        country: str,
    ) -> list[ProviderRegistryEntry]:
        eligible = []
        for entry in self.entries:
            if not entry.enabled:
                continue
            if active_profile not in entry.allowed_profiles:
                continue
            if domain not in entry.capabilities.domains:
                continue
            if country not in entry.capabilities.supported_countries:
                continue
            if entry.remaining_quota <= 0 and entry.remaining_budget <= 0:
                continue
            eligible.append(entry)

        # Sort by: remaining quota/budget (desc), priority (asc), provider_id (asc)
        eligible.sort(
            key=lambda x: (
                -(x.remaining_quota + x.remaining_budget),
                x.priority,
                x.provider_id,
            )
        )
        return eligible

    def get_entry(self, provider_id: str) -> ProviderRegistryEntry:
        for entry in self.entries:
            if entry.provider_id == provider_id:
                return entry
        raise PlaceGatewayError("provider_unavailable", f"Unknown provider_id: {provider_id}")


def get_default_place_registry() -> ProviderRegistry:
    sample = ProviderRegistryEntry(
        provider_id="sample_adapter",
        enabled=True,
        allowed_profiles=["student_noncommercial", "commercial_production"],
        capabilities=AdapterCapabilities(
            domains=["poi"], supported_countries=["SG", "IN", "AE", "US"]
        ),
        priority=999,
        remaining_quota=999999,
    )
    return ProviderRegistry(entries=[sample])
