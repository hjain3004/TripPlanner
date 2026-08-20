from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import AwareDatetime, BaseModel, Field, PrivateAttr


def redact_secret(text: str) -> str:
    """Scrub potential API keys, bearer tokens, headers and secrets from error messages and logs."""
    if not text:
        return ""
    env_key = os.environ.get("TRIPWISE_TRIPADVISOR_API_KEY", "")
    redacted = text
    if env_key and len(env_key) >= 6:
        redacted = redacted.replace(env_key, "[REDACTED_API_KEY]")
    redacted = re.sub(
        r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{6,}(['\"]?)",
        r"\1[REDACTED_KEY]\2",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{6,}",
        r"\1[REDACTED_TOKEN]",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.\s]{6,}(['\"]?)",
        r"\1[REDACTED_AUTH]\2",
        redacted,
    )
    redacted = re.sub(
        r"\b(?:sk_|gsk_|key-|secret_)[a-zA-Z0-9_\-]{6,}\b",
        "[REDACTED_SECRET]",
        redacted,
    )
    return redacted


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
        sanitized = redact_secret(message)
        super().__init__(sanitized)
        self.code = code
        self.message = sanitized

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"PlaceGatewayError(code='{self.code}', message='{self.message}')"


class TripadvisorQuotaLedger(Protocol):
    @property
    def is_billable(self) -> bool: ...

    @property
    def is_in_memory(self) -> bool: ...

    @property
    def db_path(self) -> str: ...

    def get_status(self) -> dict[str, int]: ...


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
    _remaining_quota_getter: Callable[[], int] | None = PrivateAttr(default=None)

    def bind_remaining_quota_getter(self, getter: Callable[[], int]) -> None:
        self._remaining_quota_getter = getter
        self.refresh_remaining_quota()

    def refresh_remaining_quota(self) -> None:
        if self._remaining_quota_getter is None:
            return
        self.remaining_quota = max(0, self._remaining_quota_getter())


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
            entry.refresh_remaining_quota()
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
                entry.refresh_remaining_quota()
                return entry
        raise PlaceGatewayError("provider_unavailable", f"Unknown provider_id: {provider_id}")

    def get_provider_manifest(self, active_profile: str) -> list[SourceLicenceManifest]:
        manifests = []
        for entry in self.entries:
            entry.refresh_remaining_quota()
            if not entry.enabled or active_profile not in entry.allowed_profiles:
                continue
            licence = "unknown"
            if entry.provider_id == "sample_adapter":
                licence = "synthetic"
            elif entry.provider_id == "tripadvisor_terra":
                licence = "tripadvisor-discover"
            manifests.append(
                SourceLicenceManifest(
                    provider_id=entry.provider_id,
                    licences=[licence],
                )
            )
        return manifests


class SourceLicenceManifest(BaseModel):
    provider_id: str
    domains: list[str] = Field(default_factory=list)
    licences: list[str] = Field(default_factory=list)
    # Spec 11: the manifest records these for every activated catalog input.
    source_url: str | None = None
    licence_id: str | None = None
    source_release: str | None = None
    checksum: str | None = None
    retrieved_at: AwareDatetime | None = None
    geographic_scope: str | None = None
    allowed_purpose: str | None = None
    attribution_text: str | None = None


def _trusted_tripadvisor_quota_getter(
    ledger: TripadvisorQuotaLedger | None,
) -> Callable[[], int] | None:
    from gateway.places.adapters.tripadvisor.budget import TripadvisorEntityLedger

    if not isinstance(ledger, TripadvisorEntityLedger):
        return None
    if not ledger.is_billable or ledger.is_in_memory or ledger.db_path == ":memory:":
        return None

    def _remaining() -> int:
        status = ledger.get_status()
        remaining = status.get("remaining", 0)
        return int(remaining)

    return _remaining


def get_default_place_registry(ledger: TripadvisorQuotaLedger | None = None) -> ProviderRegistry:
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
    snapshot = ProviderRegistryEntry(
        provider_id="snapshot_adapter",
        enabled=True,
        allowed_profiles=["student_noncommercial"],
        capabilities=AdapterCapabilities(domains=["poi"], supported_countries=["SG"]),
        priority=100,
        remaining_quota=999999,
    )

    ta_quota_getter = _trusted_tripadvisor_quota_getter(ledger)
    ta_quota = ta_quota_getter() if ta_quota_getter is not None else 0

    tripadvisor = ProviderRegistryEntry(
        provider_id="tripadvisor_terra",
        enabled=False,  # Disabled by default
        allowed_profiles=["student_noncommercial"],
        capabilities=AdapterCapabilities(
            domains=["poi"], supported_countries=["SG", "IN", "AE", "US", "GB", "FR"]
        ),
        priority=50,
        remaining_quota=ta_quota,
        remaining_budget=0,
    )
    if ta_quota_getter is not None:
        tripadvisor.bind_remaining_quota_getter(ta_quota_getter)
    return ProviderRegistry(entries=[sample, snapshot, tripadvisor])
