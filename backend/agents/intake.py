from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from agents.llm import LLMClient, complete_with_repair
from agents.models import TripSpec
from core.db import KnowledgeBase
from gateway.catalog.regions import load_regions

# India is the initial corridor origin (CLAUDE.md). Unrelated to which regional
# catalogs exist - this is the traveler's home airport, not a destination.
ORIGIN_CITIES = {"DEL", "BOM"}

_REGIONS_PATH = Path(__file__).parent.parent / "gateway" / "catalog" / "fixtures" / "regions.yaml"


def _supported_destinations() -> set[str]:
    """A destination is supported when it has a registered Region entry.

    Derived from regions.yaml rather than hardcoded, so Task 7/8 additions make
    a destination selectable without another edit here. Whether that region's
    catalog is actually *built* is a separate, request-time concern reported by
    RegionCapability - not something intake-time route validation checks.
    """
    return set(load_regions(_REGIONS_PATH).keys())


class IntakeResult(BaseModel):
    trip_spec: TripSpec | None = None
    unresolved: list[str] = Field(default_factory=list)
    needs_clarification: bool = False


def _card_catalog(kb: KnowledgeBase) -> str:
    return "\n".join(f"{card.id} | {card.issuer} | {card.name}" for card in kb.cards())


def _validate_intake(spec: TripSpec, kb: KnowledgeBase) -> list[str]:
    unresolved = list(spec.unresolved)
    for card_id in spec.wallet.card_ids:
        if not kb.has_card(card_id):
            unresolved.append(f"unknown card id: {card_id}")
    unsupported_origin = spec.origin_city not in ORIGIN_CITIES
    unsupported_destination = spec.destination_city not in _supported_destinations()
    if unsupported_origin or unsupported_destination:
        unresolved.append(f"unsupported route: {spec.origin_city}->{spec.destination_city}")
    return sorted(set(unresolved))


def run_intake(raw_request: str, kb: KnowledgeBase, llm: LLMClient) -> IntakeResult:
    system = (
        "You convert a travel request into strict TripSpec JSON. "
        "Use only card IDs from the catalog. Put ambiguity in unresolved."
    )
    user = f"Request:\n{raw_request}\n\nCard catalog:\n{_card_catalog(kb)}"
    try:
        spec = complete_with_repair(
            llm,
            node="intake",
            system=system,
            user=user,
            schema=TripSpec,
            temperature=0.0,
        )
    except Exception as exc:
        return IntakeResult(
            unresolved=[f"intake failed: {exc}"],
            needs_clarification=True,
        )

    unresolved = _validate_intake(spec, kb)
    if unresolved:
        return IntakeResult(unresolved=unresolved, needs_clarification=True)
    return IntakeResult(trip_spec=spec, unresolved=[], needs_clarification=False)
