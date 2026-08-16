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


IATA_ALIASES: dict[str, str] = {
    "CDG": "PAR",
    "ORY": "PAR",
    "LHR": "LON",
    "LGW": "LON",
    "STN": "LON",
    "LCY": "LON",
    "LTN": "LON",
    "JFK": "NYC",
    "EWR": "NYC",
    "LGA": "NYC",
    "DWC": "DXB",
}


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
    spec.destination_city = IATA_ALIASES.get(spec.destination_city, spec.destination_city)
    spec.origin_city = IATA_ALIASES.get(spec.origin_city, spec.origin_city)
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
        "You convert a travel request into strict JSON conforming to TripSpec. "
        "Convert origin_city and destination_city to 3-letter uppercase IATA codes "
        "(e.g. DEL, BOM, SIN, DXB, LON, PAR, NYC). "
        "Use only card IDs from the catalog. "
        "If the user explicitly specifies a card not present in the card catalog, "
        "add 'unknown card: <name>' to `unresolved`. "
        "If required travel dates or origin city are completely omitted from the request, "
        "add 'missing travel dates' or 'missing origin' to `unresolved`. "
        "Otherwise, leave `unresolved` empty unless a REQUIRED field genuinely cannot be "
        "determined from the request. Vague-but-usable preferences such as "
        "interests or style are not unresolved - record your best reading."
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
