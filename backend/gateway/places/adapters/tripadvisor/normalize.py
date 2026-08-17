from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from gateway.places.adapters.tripadvisor.contracts import (
    TripadvisorLocation,
)
from gateway.places.contracts import (
    ExternalId,
    Place,
    PlaceCandidate,
    PlaceClaim,
)
from gateway.places.registry import PlaceGatewayError

EvidenceStatus = Literal["live", "cached", "estimated", "stale", "verify_required"]


@dataclass(frozen=True)
class TripadvisorEvidenceContext:
    status: EvidenceStatus
    retrieved_at: datetime
    last_verified: datetime
    verified_by: str
    needs_verification: bool

# Known instruction injection patterns to strip or neutralize
_INJECTION_PATTERNS = [
    re.compile(
        r"(?i)\b(system\s*instruction|system\s*prompt|"
        r"ignore\s*(all\s*)?previous\s*(rules?|instructions?|guidelines?))\b"
    ),
    re.compile(
        r"(?i)\b(reveal\s*system\s*secrets?|"
        r"disregard\s*all\s*(prior|previous)\s*(rules?|guidelines?|instructions?))\b"
    ),
    re.compile(r"(?i)<<.*?>>"),
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]"),  # Non-printable control characters
]


def sanitize_provider_text(text: str | None, max_length: int = 1000) -> str:
    """Sanitize external provider text before it can enter LLM prompts or UI views."""
    if not text:
        return ""
    cleaned = text
    for pat in _INJECTION_PATTERNS:
        cleaned = pat.sub("[REDACTED_CONTENT]", cleaned)
    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length] + "..."
    return cleaned


def normalize_tripadvisor_category(loc: TripadvisorLocation) -> str:
    """Map Tripadvisor category tags to normalized system taxonomy."""
    top_level = ""
    sub_ids: list[str] = []
    for cat in loc.categories:
        if cat.top_level_category:
            top_level = cat.top_level_category.lower()
        if cat.id:
            sub_ids.append(cat.id.lower())

    if "eat & drink" in top_level or any(
        s in ["restaurant", "food_court", "cafe", "bar"] for s in sub_ids
    ):
        return "food"
    if "accommodation" in top_level or any(
        s in ["hotel", "resort", "hostel", "inn"] for s in sub_ids
    ):
        return "hotel"
    if "attraction" in top_level or any(
        s in ["attraction", "landmark", "museum", "park"] for s in sub_ids
    ):
        if any("park" in s or "nature" in s for s in sub_ids):
            return "nature"
        if any("museum" in s or "heritage" in s or "temple" in s for s in sub_ids):
            return "culture"
        return "attractions"

    # Default fallback
    return "other"


def normalize_tripadvisor_location(
    loc: TripadvisorLocation,
    is_live_transport: bool = False,
    evidence_status: EvidenceStatus | None = None,
    retrieved_at: datetime | None = None,
    last_verified_at: datetime | None = None,
    verified_by: str | None = None,
    now_dt: datetime | None = None,
) -> PlaceCandidate:
    effective_dt = retrieved_at or now_dt or datetime(2026, 8, 17, 0, 0, 0, tzinfo=UTC)
    evidence = _resolve_evidence_context(
        is_live_transport=is_live_transport,
        evidence_status=evidence_status,
        retrieved_at=effective_dt,
        last_verified_at=last_verified_at,
        verified_by=verified_by,
    )

    str_id = str(loc.id).strip()
    place_id = f"poi:ta_{str_id}"
    external_ids = [ExternalId(namespace="tripadvisor", value=str_id)]

    # Assemble Place entity
    _ = Place(place_id=place_id, external_ids=external_ids)

    claims: list[PlaceClaim] = []
    completeness_flags: list[str] = []

    # 1. Name Claim
    primary_name = ""
    for n in loc.names:
        if n.primary and n.value:
            primary_name = n.value
            break
    if not primary_name and loc.names:
        primary_name = loc.names[0].value
    if not primary_name:
        primary_name = f"Tripadvisor Location {str_id}"
        completeness_flags.append("missing_primary_name")

    clean_name = sanitize_provider_text(primary_name, max_length=200)
    claims.append(
        PlaceClaim(
            place_id=place_id,
            field="name",
            value=clean_name,
            source_id="tripadvisor_terra",
            source_url=(loc.urls.tripadvisor if loc.urls else "") or "",
            retrieved_at=evidence.retrieved_at,
            last_verified=evidence.last_verified,
            verified_by=evidence.verified_by,
            confidence=0.85,
            needs_verification=evidence.needs_verification,
            licence_id="tripadvisor-discover",
            attribution_requirements=(
                "Contains content sourced via Tripadvisor Terra. "
                "Link back to Tripadvisor page for details."
            ),
            lifecycle_state="active",
        )
    )

    # 2. Category Claim
    norm_category = normalize_tripadvisor_category(loc)
    claims.append(
        PlaceClaim(
            place_id=place_id,
            field="category",
            value=norm_category,
            source_id="tripadvisor_terra",
            source_url=(loc.urls.tripadvisor if loc.urls else "") or "",
            retrieved_at=evidence.retrieved_at,
            last_verified=evidence.last_verified,
            verified_by=evidence.verified_by,
            confidence=0.85,
            needs_verification=evidence.needs_verification,
            licence_id="tripadvisor-discover",
            attribution_requirements="Contains content sourced via Tripadvisor Terra.",
            lifecycle_state="active",
        )
    )

    # 3. Coordinates Claim (never manufactured if missing)
    if (
        loc.coordinates
        and loc.coordinates.latitude is not None
        and loc.coordinates.longitude is not None
    ):
        claims.append(
            PlaceClaim(
                place_id=place_id,
                field="coordinates",
                value={"lat": loc.coordinates.latitude, "lon": loc.coordinates.longitude},
                source_id="tripadvisor_terra",
                source_url=(loc.urls.tripadvisor if loc.urls else "") or "",
                retrieved_at=evidence.retrieved_at,
                last_verified=evidence.last_verified,
                verified_by=evidence.verified_by,
                confidence=0.90,
                needs_verification=evidence.needs_verification,
                licence_id="tripadvisor-discover",
                attribution_requirements="Contains content sourced via Tripadvisor Terra.",
                lifecycle_state="active",
            )
        )
    else:
        completeness_flags.append("missing_coordinates")

    # 4. Description Claim
    raw_desc = ""
    for d in loc.descriptions:
        if isinstance(d, dict) and "text" in d:
            raw_desc = d["text"]
            break
    if raw_desc:
        clean_desc = sanitize_provider_text(raw_desc, max_length=500)
        claims.append(
            PlaceClaim(
                place_id=place_id,
                field="description",
                value=clean_desc,
                source_id="tripadvisor_terra",
                source_url=(loc.urls.tripadvisor if loc.urls else "") or "",
                retrieved_at=evidence.retrieved_at,
                last_verified=evidence.last_verified,
                verified_by=evidence.verified_by,
                confidence=0.80,
                needs_verification=evidence.needs_verification,
                licence_id="tripadvisor-discover",
                attribution_requirements="Contains content sourced via Tripadvisor Terra.",
                lifecycle_state="active",
            )
        )

    return PlaceCandidate(
        place_id=place_id,
        claims=claims,
        completeness_flags=completeness_flags,
        status=evidence.status,
    )


def _resolve_evidence_context(
    *,
    is_live_transport: bool,
    evidence_status: EvidenceStatus | None,
    retrieved_at: datetime,
    last_verified_at: datetime | None,
    verified_by: str | None,
) -> TripadvisorEvidenceContext:
    if evidence_status == "live" and not is_live_transport:
        raise PlaceGatewayError(
            "invalid_response",
            "Non-live Tripadvisor transport cannot emit live evidence",
        )

    if is_live_transport:
        status: EvidenceStatus = evidence_status or "live"
        verifier = verified_by or "provider:tripadvisor_terra"
        return TripadvisorEvidenceContext(
            status=status,
            retrieved_at=retrieved_at,
            last_verified=last_verified_at or retrieved_at,
            verified_by=verifier,
            needs_verification=(status != "live"),
        )

    status = evidence_status or "cached"
    return TripadvisorEvidenceContext(
        status=status,
        retrieved_at=retrieved_at,
        last_verified=last_verified_at or retrieved_at,
        verified_by=verified_by or "fixture:tripadvisor_synthetic",
        needs_verification=True,
    )
