"""Deterministic non-points card perks & rental-car benefit valuation (pure integer math)."""

from __future__ import annotations

from core.perks.contracts import (
    AirlineBagPerk,
    CardGrantedStatus,
    CardPerkProfile,
    ReferenceRentalProgram,
    RentalCarCardBreakdown,
    RentalCarCardCandidate,
    RentalCarCardComparison,
    RentalCarProtection,
    StatementCreditPerk,
    TripItemPerkBreakdown,
    TripPerkItem,
    TripPerksValuation,
)
from core.perks.evaluator import evaluate_rental_car_cards, evaluate_trip_perks
from core.perks.reference_perks import (
    get_reference_perk_profile,
    reference_car_rental_programs,
    reference_card_perk_profiles,
)

__all__ = [
    "AirlineBagPerk",
    "CardGrantedStatus",
    "CardPerkProfile",
    "ReferenceRentalProgram",
    "RentalCarCardBreakdown",
    "RentalCarCardCandidate",
    "RentalCarCardComparison",
    "RentalCarProtection",
    "StatementCreditPerk",
    "TripItemPerkBreakdown",
    "TripPerkItem",
    "TripPerksValuation",
    "evaluate_rental_car_cards",
    "evaluate_trip_perks",
    "get_reference_perk_profile",
    "reference_card_perk_profiles",
    "reference_car_rental_programs",
]
