"""Safe, non-quote evidence for Gondola's provider-Markdown responses.

The live response is intentionally treated as an opaque string. This module
records only the response contract and bounded, code-owned limitations. It
never extracts prices, links, selections, personalization, or provider prose.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field

from gateway.travel.errors import TravelGatewayError

GONDOLA_SOURCE_URL = "https://mcp.gondola.ai/mcp"
MAX_DISCOVERY_TEXT_BYTES = 512_000

DiscoveryTool = Literal["search_hotels", "search_flights"]
DiscoveryProvenance = Literal["live_observation", "synthetic_fixture"]


class GondolaDiscoveryEvidence(BaseModel):
    provider_id: Literal["gondola"] = "gondola"
    tool: DiscoveryTool
    result_format: Literal["provider_markdown"] = "provider_markdown"
    observed_at: AwareDatetime
    provenance: DiscoveryProvenance
    captured_on: date | None = None
    fixture_name: str | None = None
    source_url: str = GONDOLA_SOURCE_URL
    reported_match_count: int | None = Field(default=None, ge=0)
    displayed_match_count: int | None = Field(default=None, ge=0)
    source_attribution: str | None = None
    limitations: tuple[str, ...]
    needs_verification: Literal[True] = True
    is_current_normalized_quote: Literal[False] = False
    is_costable: Literal[False] = False
    safe_links: tuple[str, ...] = ()


_LIMITATIONS: dict[DiscoveryTool, tuple[str, ...]] = {
    "search_hotels": (
        "provider_markdown_not_typed_inventory",
        "dated_rate_plan_and_room_scope_unverified",
        "tax_fee_currency_scope_unverified",
        "cancellation_terms_unverified",
    ),
    "search_flights": (
        "provider_markdown_not_typed_inventory",
        "segment_identity_and_timezone_unverified",
        "tax_fee_currency_scope_unverified",
        "fare_conditions_unverified",
        "not_bookable_through_gondola",
    ),
}


def parse_markdown_discovery(
    payload: Mapping[str, object],
    *,
    tool: DiscoveryTool,
    now: datetime,
    provenance: DiscoveryProvenance = "live_observation",
    captured_on: date | None = None,
    fixture_name: str | None = None,
) -> GondolaDiscoveryEvidence:
    if tool not in _LIMITATIONS:
        raise TravelGatewayError("invalid_response", "Unsupported Gondola discovery tool")
    raw_result = payload.get("result")
    if not isinstance(raw_result, str) or not raw_result.strip():
        raise TravelGatewayError(
            "invalid_response", "Gondola discovery response is not a non-empty result string"
        )
    if len(raw_result.encode("utf-8")) > MAX_DISCOVERY_TEXT_BYTES:
        raise TravelGatewayError(
            "invalid_response", "Gondola discovery response exceeds size bound"
        )
    return GondolaDiscoveryEvidence(
        tool=tool,
        observed_at=now,
        provenance=provenance,
        captured_on=captured_on,
        fixture_name=fixture_name,
        source_attribution="provider-reported discovery evidence; unverified",
        limitations=_LIMITATIONS[tool],
    )
