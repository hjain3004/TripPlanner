"""Server-owned facts override what the intake model read.

Mode A (runtime LLM design section 3): the intake call still runs, but when the server holds an
authoritative ``TripSpec`` (a confirmed conversational brief, or a structured wizard submission)
its identity fields must match the model's reading, and its preference fields replace it. Nothing
here calls a model, the network or the clock.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.intake import validate_trip_spec
from core.db import KnowledgeBase
from core.models import OptimizationPrefs, UserWallet
from core.trip_models import TripSpec

# The fields a model must reproduce exactly. Anything else on TripSpec is a preference.
IDENTITY_FIELDS: tuple[str, ...] = (
    "home_country",
    "origin_city",
    "destination_city",
    "start_date",
    "end_date",
    "travelers",
    "budget_minor",
    "budget_currency",
    "style",
    "wallet",
    "optimization",
)
# The fields the server's value wins on, silently, when the model's reading differs.
PREFERENCE_FIELDS: tuple[str, ...] = ("interests", "pace", "dietary")


class StructuredInputRejected(ValueError):
    """The submitted structure is not a plan the product can run; ``unresolved`` says why."""

    def __init__(self, unresolved: list[str]) -> None:
        self.unresolved = sorted(set(unresolved))
        super().__init__("; ".join(self.unresolved))


class StructuredTripInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    home_country: Literal["IN", "AE", "US"]
    origin_city: str
    destination_city: str
    start_date: date
    end_date: date
    travelers: int = Field(gt=0)
    budget_minor: int | None = Field(default=None, ge=0)
    budget_currency: str
    style: Literal["budget", "balanced", "luxury"]
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "moderate", "packed"] = "moderate"
    dietary: list[str] = Field(default_factory=list)
    wallet: UserWallet
    objective: Literal["min_cash_outlay", "max_savings", "simplicity"] = "max_savings"


def _clean(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        cleaned = value.strip()
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


def project_structured_trip_spec(inp: StructuredTripInput, kb: KnowledgeBase) -> TripSpec:
    """Build the TripSpec a structured submission denotes, or refuse with every reason at once."""
    problems: list[str] = []
    end_date = inp.end_date
    nights = (inp.end_date - inp.start_date).days
    if inp.end_date <= inp.start_date:
        problems.append("end date must be after the start date")
    if not 3 <= nights <= 7:
        problems.append("trip must be 3 to 7 nights")
        # Keep going on a valid placeholder so cards and route are reported in the same pass.
        end_date = inp.start_date + timedelta(days=3)
    try:
        spec = TripSpec(
            home_country=inp.home_country,
            origin_city=inp.origin_city,
            destination_city=inp.destination_city,
            start_date=inp.start_date,
            end_date=end_date,
            travelers=inp.travelers,
            budget_minor=inp.budget_minor,
            budget_currency=inp.budget_currency,
            style=inp.style,
            interests=_clean(inp.interests),
            pace=inp.pace,
            dietary=_clean(inp.dietary),
            wallet=inp.wallet.model_copy(deep=True),
            optimization=OptimizationPrefs(objective=inp.objective),
            unresolved=[],
        )
    except ValueError as exc:
        raise StructuredInputRejected([*problems, f"invalid trip: {exc}"]) from exc
    problems.extend(validate_trip_spec(spec, kb))
    if problems:
        raise StructuredInputRejected(problems)
    return spec


def render_structured_raw_request(inp: StructuredTripInput) -> str:
    """The deterministic text handed to intake for a structured submission (sorted JSON)."""
    return "Structured trip request (JSON):\n" + json.dumps(
        inp.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )


def _canonical(spec: TripSpec) -> dict[str, Any]:
    actual: dict[str, Any] = spec.model_dump(mode="python")
    wallet = actual["wallet"]
    wallet["card_ids"] = sorted(wallet["card_ids"])
    wallet["points_balances"] = dict(sorted(wallet["points_balances"].items()))
    actual["optimization"] = {"objective": actual["optimization"]["objective"]}
    return actual


def apply_authoritative_fields(spec: TripSpec, authority: TripSpec) -> tuple[TripSpec, list[str]]:
    """(spec with the server's preferences, names of identity fields the model got wrong)."""
    observed, expected = _canonical(spec), _canonical(authority)
    mismatched = [name for name in IDENTITY_FIELDS if observed[name] != expected[name]]
    updated = spec.model_copy(
        update={name: getattr(authority, name) for name in PREFERENCE_FIELDS}, deep=True
    )
    return updated, mismatched
