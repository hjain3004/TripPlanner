"""Strict, typed answer contracts for the CP1 conversational interview.

Every answer to an interview question is one of nine closed payload shapes
(``AnswerPayload``), tied to its question by ``ANSWER_TYPE_BY_QUESTION`` and
enforced by ``InterviewAnswer``'s own model validator — a mismatched payload,
a delegated answer carrying a payload, a non-delegated answer missing one, or
a profile-update request from a question that has no durable profile section
are all hard validation errors, not caller conventions.

``TripEssentialsPayload`` mirrors ``core.trip_models.TripSpec``'s IATA
normalization (``field_validator`` on origin/destination: strip, uppercase,
require a 3-letter alphabetic code) and its 3-to-7-night Kernel MVP range
check, so an answered trip-essentials payload is always shape-compatible
with what the frozen kernel accepts. Currency normalization mirrors
``TripSpec.budget_currency`` exactly (strip + uppercase, no format
assertion) for the same reason.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class QuestionId(StrEnum):
    # Core (asked on every trip).
    TRIP_ESSENTIALS = "trip_essentials"
    PURPOSE_AND_PARTY = "purpose_and_party"
    BUDGET_AND_OBJECTIVE = "budget_and_objective"
    FLIGHT_PREFERENCES = "flight_preferences"
    STAY_PREFERENCES = "stay_preferences"
    DAILY_RHYTHM = "daily_rhythm"
    EXPERIENCES_AND_FOOD = "experiences_and_food"
    HARD_CONSTRAINTS = "hard_constraints"
    # Adaptive (asked only when applicable; zero to four per interview).
    CELEBRATION_DETAILS = "celebration_details"
    CHILDREN_NEEDS = "children_needs"
    MOBILITY_DETAILS = "mobility_details"
    POINTS_STRATEGY = "points_strategy"
    FLIGHT_TRADEOFF = "flight_tradeoff"
    HOTEL_TRADEOFF = "hotel_tradeoff"
    FOOD_DEPTH = "food_depth"


def _normalize_iata(value: str) -> str:
    """Mirror ``core.trip_models.TripSpec.normalize_iata`` exactly."""
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be a 3-letter IATA code")
    return normalized


def _normalize_currency(value: str) -> str:
    """Mirror ``core.trip_models.TripSpec.normalize_currency`` exactly."""
    return value.strip().upper()


def _normalize_string_list(values: list[str]) -> list[str]:
    """Trim whitespace and drop empty entries from a free-text list field."""
    return [item.strip() for item in values if item.strip()]


class TripEssentialsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str
    destination: str
    start_date: date
    end_date: date
    date_flexibility_days: int = Field(default=0, ge=0, le=14)
    travelers: int = Field(ge=1, le=20)

    @field_validator("origin", "destination")
    @classmethod
    def normalize_iata(cls, value: str) -> str:
        return _normalize_iata(value)

    @model_validator(mode="after")
    def validate_kernel_range(self) -> TripEssentialsPayload:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        nights = (self.end_date - self.start_date).days
        if not 3 <= nights <= 7:
            raise ValueError("Kernel MVP supports trips of 3 to 7 nights")
        return self


class PurposePartyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["leisure", "work", "celebration", "family", "mixed"]
    adults: int = Field(ge=1, le=20)
    children_ages: list[int] = Field(default_factory=list)
    companion_notes: str | None = Field(default=None, max_length=500)


class BudgetObjectivePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_minor: int | None = Field(default=None, ge=0)
    currency: str
    travel_style: Literal["budget", "balanced", "luxury"]
    objective: Literal["lowest_cash", "highest_value", "convenience", "balanced"]
    points_priority: Literal["save_points", "use_points", "best_value"]

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return _normalize_currency(value)


class FlightPreferencesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cabin: Literal["economy", "premium_economy", "business", "first", "no_preference"]
    max_stops: int | None = Field(default=None, ge=0, le=3)
    schedule: Literal["morning", "afternoon", "evening", "overnight", "no_preference"]
    checked_baggage: bool | None = None
    airport_flexible: bool | None = None
    seat: Literal["aisle", "window", "middle", "no_preference"] = "no_preference"


class StayPreferencesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lodging_styles: list[str] = Field(default_factory=list)
    neighborhood_priorities: list[str] = Field(default_factory=list)
    room_count: int = Field(default=1, ge=1, le=10)
    room_needs: list[str] = Field(default_factory=list)
    location_price_tradeoff: Literal["location", "price", "balanced", "no_preference"]

    @field_validator("lodging_styles", "neighborhood_priorities", "room_needs")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)


class DailyRhythmPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pace: Literal["relaxed", "moderate", "packed", "no_preference"]
    day_start: Literal["early", "normal", "late", "no_preference"]
    evening_style: Literal["quiet", "flexible", "late", "no_preference"]
    downtime_minutes: int | None = Field(default=None, ge=0, le=360)
    transit_tolerance_minutes: int | None = Field(default=None, ge=0, le=240)
    day_trip_appetite: Literal["none", "one", "multiple", "no_preference"]


class ExperiencesFoodPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interests: list[str] = Field(default_factory=list)
    food_interests: list[str] = Field(default_factory=list)
    iconic_local_balance: Literal["iconic", "balanced", "local", "no_preference"]
    nightlife: bool | None = None
    shopping: bool | None = None

    @field_validator("interests", "food_interests")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)


class HardConstraintsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    has_constraints: bool
    dietary: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    immovable_events: list[str] = Field(default_factory=list)

    @field_validator("dietary", "accessibility", "exclusions", "immovable_events")
    @classmethod
    def normalize_lists(cls, values: list[str]) -> list[str]:
        return _normalize_string_list(values)

    @model_validator(mode="after")
    def validate_consistency(self) -> HardConstraintsPayload:
        has_any = bool(
            self.dietary or self.accessibility or self.exclusions or self.immovable_events
        )
        if not self.has_constraints and has_any:
            raise ValueError(
                "has_constraints=False cannot carry dietary/accessibility/"
                "exclusion/event details"
            )
        if self.has_constraints and not has_any:
            raise ValueError(
                "has_constraints=True requires at least one constraint, "
                "exclusion, or immovable event"
            )
        return self


class AdaptiveDetailPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: str = Field(min_length=1, max_length=1000)

    @field_validator("detail")
    @classmethod
    def normalize_detail(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("detail must not be empty or whitespace-only")
        return trimmed


AnswerPayload = (
    TripEssentialsPayload
    | PurposePartyPayload
    | BudgetObjectivePayload
    | FlightPreferencesPayload
    | StayPreferencesPayload
    | DailyRhythmPayload
    | ExperiencesFoodPayload
    | HardConstraintsPayload
    | AdaptiveDetailPayload
)

ANSWER_TYPE_BY_QUESTION: dict[QuestionId, type[AnswerPayload]] = {
    QuestionId.TRIP_ESSENTIALS: TripEssentialsPayload,
    QuestionId.PURPOSE_AND_PARTY: PurposePartyPayload,
    QuestionId.BUDGET_AND_OBJECTIVE: BudgetObjectivePayload,
    QuestionId.FLIGHT_PREFERENCES: FlightPreferencesPayload,
    QuestionId.STAY_PREFERENCES: StayPreferencesPayload,
    QuestionId.DAILY_RHYTHM: DailyRhythmPayload,
    QuestionId.EXPERIENCES_AND_FOOD: ExperiencesFoodPayload,
    QuestionId.HARD_CONSTRAINTS: HardConstraintsPayload,
    QuestionId.CELEBRATION_DETAILS: AdaptiveDetailPayload,
    QuestionId.CHILDREN_NEEDS: AdaptiveDetailPayload,
    QuestionId.MOBILITY_DETAILS: AdaptiveDetailPayload,
    QuestionId.POINTS_STRATEGY: AdaptiveDetailPayload,
    QuestionId.FLIGHT_TRADEOFF: AdaptiveDetailPayload,
    QuestionId.HOTEL_TRADEOFF: AdaptiveDetailPayload,
    QuestionId.FOOD_DEPTH: AdaptiveDetailPayload,
}

# Only these payload kinds carry a durable profile section (see
# ``QuestionDefinition.profile_sections`` in ``question_catalog.py``:
# optimization, flight, stay, rhythm, experiences, constraints). Trip
# essentials, purpose/party, and every adaptive free-text detail are
# trip-scoped only and can never propose a profile update.
PROFILE_UPDATE_ELIGIBLE_TYPES: frozenset[type[AnswerPayload]] = frozenset(
    {
        BudgetObjectivePayload,
        FlightPreferencesPayload,
        StayPreferencesPayload,
        DailyRhythmPayload,
        ExperiencesFoodPayload,
        HardConstraintsPayload,
    }
)


class InterviewAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    payload: AnswerPayload | None = None
    delegated: bool = False
    memory_scope: Literal["trip_only", "propose_profile_update"] = "trip_only"
    client_event_id: str = Field(min_length=1, max_length=128)
    answered_at: datetime

    @model_validator(mode="after")
    def validate_consistency(self) -> InterviewAnswer:
        if self.delegated:
            if self.payload is not None:
                raise ValueError("a delegated answer must not include a payload")
        else:
            if self.payload is None:
                raise ValueError("a non-delegated answer requires a payload")
            expected_type = ANSWER_TYPE_BY_QUESTION[self.question_id]
            if not isinstance(self.payload, expected_type):
                raise ValueError(
                    f"payload for {self.question_id.value} must be an instance "
                    f"of {expected_type!r}"
                )
        if self.memory_scope == "propose_profile_update":
            if self.payload is None or type(self.payload) not in PROFILE_UPDATE_ELIGIBLE_TYPES:
                raise ValueError(
                    "only budget, flight, stay, rhythm, experiences, or "
                    "constraints answers may propose a profile update"
                )
        return self
