from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

IdentifierNamespace = Literal["overture", "osm", "wikidata", "tomtom", "internal"]


class ExternalId(BaseModel):
    namespace: IdentifierNamespace
    value: str = Field(min_length=1)


class Place(BaseModel):
    """An entity assembled from claims. Deliberately has no `name` field: spec 5.1
    forbids names as primary keys. The display name is a claim like any other."""

    place_id: str = Field(min_length=1)
    external_ids: list[ExternalId] = Field(default_factory=list)


class PlaceClaim(BaseModel):
    place_id: str = Field(min_length=1)
    field: Literal[
        "coordinates",
        "category",
        "name",
        "description",
        "opening_hours",
        "accessibility",
        "admission",
    ]
    value: Any

    source_id: str
    source_url: str
    retrieved_at: AwareDatetime
    source_release: str | None = None
    last_verified: AwareDatetime
    verified_by: str
    confidence: float = Field(ge=0.0, le=1.0)
    needs_verification: bool
    licence_id: str
    attribution_requirements: str | None = None
    lifecycle_state: Literal["active", "stale", "superseded"] = "active"


class CompactClaim(BaseModel):
    place_id: str = Field(min_length=1)
    field: Literal[
        "coordinates",
        "category",
        "name",
        "description",
        "opening_hours",
        "accessibility",
        "admission",
    ]
    value: Any
    source_id: str
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    needs_verification: bool = False
    lifecycle_state: Literal["active", "stale", "superseded"] = "active"


class PlaceCandidate(BaseModel):
    place_id: str
    claims: list[PlaceClaim]
    completeness_flags: list[str] = Field(default_factory=list)
    status: Literal["live", "cached", "estimated", "stale", "verify_required"]


class PlaceSearchRequest(BaseModel):
    destination_area_id: str
    category_filters: list[str] = Field(default_factory=list)
    max_results: int = Field(le=50)
    budget_context_id: str | None = None
    origin_lat: float | None = None
    origin_lon: float | None = None
    timeout_ms: int | None = None


class PartialPlaceResult(BaseModel):
    unresolved_needs: list[str] = Field(min_length=1)
    stop_reason: Literal["budget_exhausted", "evidence_missing", "rate_limited", "timeout"]


def validate_adapter_response(request: PlaceSearchRequest, candidate: PlaceCandidate) -> None:
    if not request.category_filters:
        return

    category_claims = [c.value for c in candidate.claims if c.field == "category"]
    if not category_claims:
        return

    for cat in category_claims:
        if cat not in request.category_filters:
            raise ValueError(f"Adapter broadened scope: category {cat} not in request filters ")
