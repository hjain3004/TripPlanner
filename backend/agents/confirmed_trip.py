"""Deterministic projection of a confirmed conversational brief.

This module is deliberately data-only.  It is the authority boundary between
the authenticated planning conversation and the existing intake/pipeline: the
LLM still parses the request, but its result must match these confirmed facts
before any inventory adapter can be called.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.trip_models import DraftItinerary, TripSpec
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from planning.contracts import ConfirmedBriefSnapshot

OBJECTIVE_MAP = {
    "lowest_cash": "min_cash_outlay",
    "highest_value": "max_savings",
    "balanced": "max_savings",
    "convenience": "simplicity",
}


class ConfirmedInputMismatchError(ValueError):
    """The intake model contradicted server-confirmed facts."""

    def __init__(self, fields: list[str]) -> None:
        self.fields = tuple(sorted(set(fields)))
        super().__init__("Confirmed trip facts do not match intake: " + ", ".join(self.fields))


@dataclass(frozen=True)
class ConfirmedTripInput:
    snapshot: ConfirmedBriefSnapshot
    raw_request: str
    expected_fields: dict[str, object]
    planner_notes: tuple[str, ...]
    limitations: tuple[str, ...]


def _canonical_wallet(snapshot: ConfirmedBriefSnapshot) -> dict[str, object]:
    wallet = snapshot.brief.wallet.model_dump(mode="json")
    wallet["card_ids"] = sorted(wallet["card_ids"])
    wallet["points_balances"] = dict(sorted(wallet["points_balances"].items()))
    return wallet


def compile_confirmed_input(snapshot: ConfirmedBriefSnapshot) -> ConfirmedTripInput:
    brief = snapshot.brief
    essentials = brief.trip_essentials
    budget = brief.budget_and_objective
    flight = brief.flight_preferences
    stay = brief.stay_preferences
    rhythm = brief.daily_rhythm
    objective = OBJECTIVE_MAP.get(budget.objective if budget else "balanced", "max_savings")
    cabin = flight.cabin if flight and flight.cabin != "no_preference" else "economy"
    cabin_label = {"premium_economy": "premium", "economy": "economy"}.get(cabin, cabin)
    travelers = essentials.travelers
    limitations = [
        "Provider child/infant age pricing is unverified until its response schema is reviewed.",
        "Baggage, seat, schedule, accessibility, and property-kind preferences "
        "are not guaranteed by the sample gateway.",
    ]
    if budget and budget.points_priority != "best_value":
        limitations.append(
            f"Points preference '{budget.points_priority}' is retained as guidance; "
            "the Kernel cannot express it as a hard inventory filter."
        )
    if essentials.date_flexibility_days:
        limitations.append(
            "Confirmed inventory uses the exact confirmed dates; date flexibility "
            "is not fanned out in this milestone."
        )
    expected = {
        "home_country": brief.home.home_country,
        "origin_city": essentials.origin,
        "destination_city": essentials.destination,
        "start_date": essentials.start_date,
        "end_date": essentials.end_date,
        "travelers": travelers,
        "budget_minor": budget.budget_minor if budget else None,
        "budget_currency": budget.currency if budget else brief.home.home_currency,
        "style": budget.travel_style if budget else "balanced",
        "wallet": _canonical_wallet(snapshot),
        "optimization": {"objective": objective},
    }
    payload = {
        "trip": {
            "origin": essentials.origin,
            "destination": essentials.destination,
            "start_date": essentials.start_date.isoformat(),
            "end_date": essentials.end_date.isoformat(),
            "travelers": travelers,
        },
        "home": brief.home.model_dump(mode="json"),
        "wallet": _canonical_wallet(snapshot),
        "preferences": {
            "style": expected["style"],
            "objective": objective,
            "cabin": cabin,
            "max_stops": flight.max_stops if flight else None,
            "rooms": stay.room_count if stay else 1,
            "pace": rhythm.pace if rhythm and rhythm.pace != "no_preference" else "moderate",
            "interests": brief.experiences_and_food.interests if brief.experiences_and_food else [],
        },
    }
    raw_request = "Confirmed trip facts (JSON):\n" + json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    )
    notes = (
        f"Confirmed cabin preference: {cabin_label}.",
        f"Confirmed objective: {objective}.",
        *limitations,
    )
    return ConfirmedTripInput(
        snapshot=snapshot,
        raw_request=raw_request,
        expected_fields=expected,
        planner_notes=notes,
        limitations=tuple(limitations),
    )


def _actual_fields(spec: TripSpec) -> dict[str, Any]:
    actual: dict[str, Any] = spec.model_dump(mode="python")
    wallet = actual["wallet"]
    wallet["card_ids"] = sorted(wallet["card_ids"])
    wallet["points_balances"] = dict(sorted(wallet["points_balances"].items()))
    return actual


def validate_confirmed_intake(spec: TripSpec, inputs: ConfirmedTripInput) -> TripSpec:
    actual = _actual_fields(spec)
    mismatches: list[str] = []
    for name, expected in inputs.expected_fields.items():
        observed = actual.get(name)
        if name == "optimization":
            observed = {"objective": actual["optimization"]["objective"]}
        if observed != expected:
            mismatches.append(name)
    if mismatches:
        raise ConfirmedInputMismatchError(mismatches)
    return spec


def build_inventory_requests(
    inputs: ConfirmedTripInput, itinerary: DraftItinerary
) -> tuple[FlightSearchRequest, HotelSearchRequest]:
    brief = inputs.snapshot.brief
    essentials = brief.trip_essentials
    flight = brief.flight_preferences
    stay = brief.stay_preferences
    party = brief.purpose_and_party
    ages = party.children_ages if party else []
    traveler_mix = TravelerMix(
        adults=party.adults if party else essentials.travelers,
        children=sum(age >= 2 for age in ages),
        infants=sum(age < 2 for age in ages),
    )
    cabin = (
        flight.cabin
        if flight and flight.cabin != "premium_economy"
        else ("premium" if flight else "economy")
    )
    if cabin == "no_preference":
        cabin = "economy"
    currency = (
        brief.budget_and_objective.currency
        if brief.budget_and_objective
        else brief.home.home_currency
    )
    flight_request = FlightSearchRequest(
        origin=essentials.origin,
        destination=essentials.destination,
        depart_date=essentials.start_date,
        return_date=essentials.end_date,
        travelers=traveler_mix,
        cabin=cabin,
        nonstop_only=bool(flight and flight.max_stops == 0),
        nearby_airports=bool(flight and flight.airport_flexible),
        currency=currency,
    )
    hotel_request = HotelSearchRequest(
        city=essentials.destination,
        check_in=essentials.start_date,
        check_out=essentials.end_date,
        travelers=traveler_mix,
        rooms=stay.room_count if stay else 1,
        area_ids=[itinerary.hotel_area_id],
        style=(
            brief.budget_and_objective.travel_style if brief.budget_and_objective else "balanced"
        ),
        currency=currency,
    )
    return flight_request, hotel_request
