"""Typed milestone facts and conservative, resource-aware bundle pruning.

The solver is opt-in; these models never modify the frozen kernel allocator.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models import Channel, Provenance, SpendCategory


class SpendMilestone(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    card_id: str = Field(min_length=1)
    threshold_minor: int = Field(gt=0)
    bonus_points: int | None = Field(default=None, gt=0)
    fee_waiver_minor: int | None = Field(default=None, gt=0)
    eligible_categories: tuple[SpendCategory, ...] = Field(min_length=1)
    period_type: Literal["annual", "quarterly", "monthly", "statement_cycle"]
    prior_spend_minor: int = Field(default=0, ge=0)
    provenance: Provenance

    @model_validator(mode="after")
    def one_reward(self) -> Self:
        if (self.bonus_points is None) == (self.fee_waiver_minor is None):
            raise ValueError("exactly one of bonus_points and fee_waiver_minor is required")
        if len(set(self.eligible_categories)) != len(self.eligible_categories):
            raise ValueError("eligible categories must be unique")
        return self


class Bundle(BaseModel):
    """An already evaluated option for one indivisible line.

    ``resource_signature`` names every scarce pool/promo use and its draw. Only
    options with identical resource and milestone effects can dominate each other.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1)
    line_id: str = Field(min_length=1)
    card_id: str = Field(min_length=1)
    channel: Channel
    category: SpendCategory
    spend_minor: int = Field(ge=0)
    currency_id: str = Field(min_length=1)
    nominal_minor: int
    floor_minor: int
    resource_signature: tuple[tuple[str, int], ...] = ()

    @model_validator(mode="after")
    def valid_floor_and_resources(self) -> Self:
        if self.floor_minor > self.nominal_minor:
            raise ValueError("guaranteed floor cannot exceed nominal value")
        if tuple(sorted(self.resource_signature)) != self.resource_signature:
            raise ValueError("resource signature must be sorted")
        if any(not key or draw < 0 for key, draw in self.resource_signature):
            raise ValueError("resource draws must be nonnegative and named")
        if len({key for key, _ in self.resource_signature}) != len(self.resource_signature):
            raise ValueError("resource names must be unique")
        return self


def prune_dominated_bundles(bundles: list[Bundle]) -> list[Bundle]:
    """Remove only options dominated in nominal and guaranteed value.

    Different cards, spend, currencies or resource footprints are incomparable:
    they can change milestone feasibility, risk, or future offer/cap availability.
    """
    groups: dict[tuple[object, ...], list[Bundle]] = defaultdict(list)
    for b in bundles:
        groups[
            (
                b.line_id,
                b.card_id,
                b.channel,
                b.category,
                b.spend_minor,
                b.currency_id,
                b.resource_signature,
            )
        ].append(b)
    retained: list[Bundle] = []
    for group in groups.values():
        ordered = sorted(group, key=lambda b: (-b.nominal_minor, -b.floor_minor, b.id))
        best_floor: int | None = None
        best_nominal = 0
        for b in ordered:
            if best_floor is not None and (
                b.floor_minor < best_floor
                or (b.floor_minor == best_floor and b.nominal_minor < best_nominal)
            ):
                continue
            retained.append(b)
            if best_floor is None or b.floor_minor > best_floor:
                best_floor, best_nominal = b.floor_minor, b.nominal_minor
    return sorted(retained, key=lambda b: (b.line_id, b.id))
