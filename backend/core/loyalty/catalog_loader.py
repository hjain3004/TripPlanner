"""Read-only reference catalog loader and pure in-memory KnowledgeBase overlay."""

from __future__ import annotations

from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import yaml

from core.db import KnowledgeBase
from core.loyalty.contracts import (
    AlliancePartnerEdge,
    HotelAwardStayRule,
    HotelChainBrandRule,
    LoyaltyReferenceCatalog,
)
from core.models import LoyaltyProgram, PointValuation, TransferEdge

REFERENCE_CATALOG_PATH = Path(__file__).resolve().parent / "reference_catalog.yaml"


@lru_cache(maxsize=2)
def _load_catalog_cached(catalog_path: Path) -> LoyaltyReferenceCatalog:
    raw = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    catalog = LoyaltyReferenceCatalog.model_validate(raw)
    for program in catalog.programs:
        if (
            program.provenance.verified_by != "UNVERIFIED"
            or not program.provenance.needs_verification
        ):
            raise ValueError(
                f"Reference program {program.id!r} must carry UNVERIFIED / needs_verification=True"
            )
    for edge in catalog.transfer_edges:
        if edge.provenance.verified_by != "UNVERIFIED" or not edge.provenance.needs_verification:
            raise ValueError(
                f"Reference edge {edge.id!r} must carry UNVERIFIED / needs_verification=True"
            )
    for brand_rule in catalog.hotel_brand_rules:
        if (
            brand_rule.provenance.verified_by != "UNVERIFIED"
            or not brand_rule.provenance.needs_verification
        ):
            raise ValueError(
                f"Hotel brand rule {brand_rule.chain_id!r} must remain UNVERIFIED reference data"
            )
    for stay_rule in catalog.hotel_award_stay_rules:
        if (
            stay_rule.provenance.verified_by != "UNVERIFIED"
            or not stay_rule.provenance.needs_verification
        ):
            raise ValueError(
                f"Hotel award stay rule {stay_rule.program_id!r} must remain UNVERIFIED"
            )
    for partner in catalog.alliance_partner_edges:
        if (
            partner.provenance.verified_by != "UNVERIFIED"
            or not partner.provenance.needs_verification
        ):
            raise ValueError(
                f"Partner edge {partner.operating_carrier_iata}->{partner.booking_program_id} "
                "must remain UNVERIFIED"
            )
    return catalog


def load_loyalty_reference_catalog(
    path: Path | None = None,
) -> LoyaltyReferenceCatalog:
    """Load and validate the unverified real-world loyalty ecosystem reference catalog."""
    return _load_catalog_cached((path or REFERENCE_CATALOG_PATH).resolve()).model_copy(deep=True)


def default_hotel_brand_rules() -> tuple[HotelChainBrandRule, ...]:
    """Return curated hotel chain brand rules from the reference catalog."""
    return load_loyalty_reference_catalog().hotel_brand_rules


def default_hotel_award_stay_rules() -> tuple[HotelAwardStayRule, ...]:
    """Return curated hotel multi-night award stay rules from the reference catalog."""
    return load_loyalty_reference_catalog().hotel_award_stay_rules


def hotel_award_stay_rule_for_program(program_id: str) -> HotelAwardStayRule | None:
    """Look up an award stay rule by loyalty ``program_id``."""
    target = program_id.strip().lower()
    for rule in default_hotel_award_stay_rules():
        if rule.program_id.lower() == target:
            return rule
    return None


def default_alliance_partner_edges() -> tuple[AlliancePartnerEdge, ...]:
    """Return curated airline alliance and bilateral partner ticketing relationships."""
    return load_loyalty_reference_catalog().alliance_partner_edges


def load_loyalty_overlay_kb(
    base_kb: KnowledgeBase,
    *,
    extra_edges: Sequence[TransferEdge] = (),
    catalog_path: Path | None = None,
) -> KnowledgeBase:
    """Return a pure in-memory ``KnowledgeBase`` merging the loyalty reference overlay.

    Never mutates ``base_kb``, ``backend/core/seeds/``, or SQLite. Existing programs and
    transfer edges on ``base_kb`` take precedence on colliding identifiers.
    """
    catalog = load_loyalty_reference_catalog(catalog_path)

    card_ids = [card.id for card in base_kb.cards()]
    valuations: list[PointValuation] = []
    seen_val_keys: set[str] = set()
    for cid in card_ids:
        for val in base_kb.valuations_for_card(cid):
            valuations.append(val)
            seen_val_keys.add(val.id)
    for card_vals in getattr(base_kb, "_valuations_by_card", {}).values():
        for val in card_vals:
            if val.id not in seen_val_keys:
                valuations.append(val)
                seen_val_keys.add(val.id)

    programs_by_id: dict[str, LoyaltyProgram] = {prog.id: prog for prog in base_kb.programs()}
    for prog in catalog.programs:
        programs_by_id.setdefault(prog.id, prog)

    existing_edges: Sequence[TransferEdge] = getattr(base_kb, "_transfer_edges", ())
    edges_by_id: dict[str, TransferEdge] = {edge.id: edge for edge in existing_edges}
    for edge in extra_edges:
        edges_by_id.setdefault(edge.id, edge)
    for edge in catalog.transfer_edges:
        edges_by_id.setdefault(edge.id, edge)

    return KnowledgeBase.from_models(
        cards=base_kb.cards(),
        reward_rules=base_kb.rules_for_cards(card_ids),
        offers=list(getattr(base_kb, "_offers", ())),
        point_valuations=valuations,
        fx_rates=list(getattr(base_kb, "_fx", {}).values()),
        pois=list(getattr(base_kb, "_pois", ())),
        areas=list(getattr(base_kb, "_areas", ())),
        sample_flights=list(getattr(base_kb, "_flights", ())),
        sample_hotels=list(getattr(base_kb, "_hotels", ())),
        loyalty_programs=list(programs_by_id.values()),
        transfer_edges=list(edges_by_id.values()),
        transfer_bonuses=list(getattr(base_kb, "_transfer_bonuses", ())),
        award_chart_entries=list(getattr(base_kb, "_award_chart_entries", ())),
    )
