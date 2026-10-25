"""Pure post-plan action contracts, deterministic routing, and impact (CP4).

After a plan exists, a traveler asks for changes: move a stop, relax the pace, change
the dates, adopt a new wallet. This module turns such a request into one of seven typed
actions and decides — from the *validated action and the workspace context*, never from
a model — which parts of the plan it invalidates and whether provider evidence must be
queried again.

It is pure: it imports only the existing domain models, Pydantic and the standard
library. It reads no clock, draws no random value, opens no connection and holds no
database or provider handle (``evals/test_cp4_boundaries.py`` proves this statically).
Identifiers, timestamps and persistence are the caller's job.

Design rules the code enforces:

* **Deterministic first.** ``classify_command`` recognises only phrases it can resolve
  exactly against approved item ids, names and dates. Anything it does not understand
  is ``None`` (the caller may then spend one bounded interpretation call); anything
  it recognises but cannot resolve safely is a ``ClarificationRequired``, never a guess.
* **Impact is derived.** ``compute_impact`` takes the action and the workspace context
  as well as the before/after briefs, because two identical global briefs can describe
  very different work (a removal, a day-local pace override, an explanation).
* **Search semantics, not wishes.** Provider evidence is invalidated only when a
  canonical fingerprint of the search-relevant fields changes; preferences that the
  present request schema cannot encode are part of that fingerprint, so changing them
  conservatively forces a re-query instead of silently reusing mismatched evidence.
* **Scope is explicit dates.** Relative phrases ("tomorrow") are never resolved here.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from datetime import date, timedelta
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from core.models import UserWallet
from core.trip_models import (
    AddItem,
    ItineraryEdit,
    MoveItem,
    RemoveItem,
    ReorderDay,
    ReplaceItem,
)
from planning.answers import (
    ANSWER_TYPE_BY_QUESTION,
    AdaptiveDetailPayload,
    AnswerPayload,
    BudgetObjectivePayload,
    DailyRhythmPayload,
    ExperiencesFoodPayload,
    FlightPreferencesPayload,
    HardConstraintsPayload,
    QuestionId,
    StayPreferencesPayload,
    TripEssentialsPayload,
)
from planning.contracts import TripBrief

MAX_COMMAND_CHARS = 2000
MAX_DAY_THEME_CHARS = 60
MAX_CLARIFICATION_CHOICES = 8

# Itinerary days a Kernel MVP trip can have (3-7 nights, plus a possible extra day).
MAX_ITINERARY_DAYS = 8


class PostPlanInputError(ValueError):
    """The command text is unusable (empty or over the bound). Never silently truncated."""


class InvalidatedDomain(StrEnum):
    """Parts of a plan a change can invalidate (conversational design, section 9)."""

    FLIGHT = "flight"
    HOTEL = "hotel"
    AWARD = "award"
    ITINERARY = "itinerary"
    COST = "cost"
    CARD_STRATEGY = "card_strategy"


_DOMAIN_ORDER: tuple[InvalidatedDomain, ...] = tuple(InvalidatedDomain)


# --------------------------------------------------------------------------- #
# Brief patches                                                                #
# --------------------------------------------------------------------------- #

_SECTION_ATTR: dict[QuestionId, str] = {
    QuestionId.TRIP_ESSENTIALS: "trip_essentials",
    QuestionId.PURPOSE_AND_PARTY: "purpose_and_party",
    QuestionId.BUDGET_AND_OBJECTIVE: "budget_and_objective",
    QuestionId.FLIGHT_PREFERENCES: "flight_preferences",
    QuestionId.STAY_PREFERENCES: "stay_preferences",
    QuestionId.DAILY_RHYTHM: "daily_rhythm",
    QuestionId.EXPERIENCES_AND_FOOD: "experiences_and_food",
    QuestionId.HARD_CONSTRAINTS: "hard_constraints",
}

# Questions whose change only affects the itinerary and its cost lines; these are the
# only ones a scoped itinerary replan may carry.
ITINERARY_ONLY_QUESTIONS: frozenset[QuestionId] = frozenset(
    {
        QuestionId.DAILY_RHYTHM,
        QuestionId.EXPERIENCES_AND_FOOD,
        QuestionId.HARD_CONSTRAINTS,
        QuestionId.CELEBRATION_DETAILS,
        QuestionId.CHILDREN_NEEDS,
        QuestionId.MOBILITY_DETAILS,
        QuestionId.FOOD_DEPTH,
    }
)


class PatchEntry(BaseModel):
    """A complete replacement answer for one approved question."""

    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    payload: AnswerPayload

    @model_validator(mode="before")
    @classmethod
    def coerce_payload_type(cls, data: object) -> object:
        # A union of payload models cannot choose a member from a bare dict reliably, so
        # the question id (the approved key) selects the one payload type allowed.
        if isinstance(data, dict) and isinstance(data.get("payload"), dict):
            try:
                question_id = QuestionId(data["question_id"])
            except (KeyError, ValueError):
                return data
            payload_type = ANSWER_TYPE_BY_QUESTION[question_id]
            return {**data, "payload": payload_type.model_validate(data["payload"])}
        return data

    @model_validator(mode="after")
    def payload_matches_question(self) -> PatchEntry:
        expected = ANSWER_TYPE_BY_QUESTION[self.question_id]
        if not isinstance(self.payload, expected):
            raise ValueError(f"payload for {self.question_id.value} must be {expected.__name__}")
        return self


class BriefPatch(BaseModel):
    """Replace whole answer payloads by approved question id. Not a field path or JSON patch."""

    model_config = ConfigDict(extra="forbid")
    entries: Annotated[list[PatchEntry], Field(min_length=1, max_length=8)]

    @model_validator(mode="after")
    def question_ids_are_unique(self) -> BriefPatch:
        ids = [entry.question_id for entry in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("a patch may replace each question at most once")
        return self

    @property
    def question_ids(self) -> frozenset[QuestionId]:
        return frozenset(entry.question_id for entry in self.entries)


def apply_brief_patch(brief: TripBrief, patch: BriefPatch) -> TripBrief:
    """Return ``brief`` with each patched question's payload replaced; untouched sections stay.

    Cross-field consistency is re-validated: party composition must still equal the
    traveler count, and every payload keeps its own validators (trip length, constraints).
    """
    sections = brief.model_dump(mode="python")
    adaptive = dict(brief.adaptive_details)
    delegated = list(brief.delegated_questions)
    for entry in patch.entries:
        attr = _SECTION_ATTR.get(entry.question_id)
        if attr is not None:
            sections[attr] = entry.payload
        else:
            if not isinstance(entry.payload, AdaptiveDetailPayload):  # defensive
                raise ValueError(f"{entry.question_id.value} takes a free-text detail")
            adaptive[entry.question_id] = entry.payload
            delegated = [q for q in delegated if q is not entry.question_id]
    sections["adaptive_details"] = adaptive
    sections["delegated_questions"] = delegated
    patched = TripBrief.model_validate(sections)
    party = patched.purpose_and_party
    if party is not None and party.adults + len(party.children_ages) != (
        patched.trip_essentials.travelers
    ):
        raise ValueError("party adults plus children must equal the traveler count")
    return patched


# --------------------------------------------------------------------------- #
# Actions                                                                      #
# --------------------------------------------------------------------------- #


class DeterministicEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["deterministic_edit"] = "deterministic_edit"
    edit: ItineraryEdit


_THEME_PATTERN = re.compile(r"^[a-z][a-z ]{2,59}$")


class ScopedItineraryReplan(BaseModel):
    """Re-plan chosen dates for a preference, without touching flights or hotels.

    ``scope="trip"`` changes the brief itself (every date it is not overridden on is
    affected). ``scope="dates"`` records a day-local preference for the named dates only;
    the global brief is left as it is.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["scoped_itinerary_replan"] = "scoped_itinerary_replan"
    scope: Literal["trip", "dates"]
    affected_dates: Annotated[list[date], Field(min_length=1, max_length=MAX_ITINERARY_DAYS)]
    patch: BriefPatch | None = None
    day_theme: str | None = None

    @field_validator("day_theme")
    @classmethod
    def theme_is_bounded_plain_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.casefold().split())
        if len(normalized) > MAX_DAY_THEME_CHARS or not _THEME_PATTERN.match(normalized):
            raise ValueError("a day theme is 3-60 plain lowercase letters")
        return normalized

    @model_validator(mode="after")
    def scope_rules(self) -> ScopedItineraryReplan:
        if len(set(self.affected_dates)) != len(self.affected_dates):
            raise ValueError("affected_dates must be unique")
        if self.patch is None and self.day_theme is None:
            raise ValueError("a scoped replan needs a patch or a day theme")
        if self.scope == "trip" and (self.patch is None or self.day_theme is not None):
            raise ValueError("a trip-wide replan is a brief patch and carries no day theme")
        if self.patch is not None and not self.patch.question_ids <= ITINERARY_ONLY_QUESTIONS:
            raise ValueError("a scoped replan may only change itinerary-only preferences")
        return self


class ProviderInvalidatingChange(BaseModel):
    """Dates, destination, travelers, cabin, hotel needs: anything that alters a search."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["provider_invalidating_change"] = "provider_invalidating_change"
    patch: BriefPatch


class WalletOrObjectiveChange(BaseModel):
    """Adopt the stored wallet and/or change the optimization objective.

    Carries no card numbers, balances or credentials: the wallet to adopt is whatever
    the account holds when the action is approved.
    """

    model_config = ConfigDict(extra="forbid")
    kind: Literal["wallet_or_objective_change"] = "wallet_or_objective_change"
    adopt_current_wallet: bool = False
    objective: Literal["lowest_cash", "highest_value", "convenience", "balanced"] | None = None
    points_priority: Literal["save_points", "use_points", "best_value"] | None = None

    @model_validator(mode="after")
    def something_changes(self) -> WalletOrObjectiveChange:
        if not (self.adopt_current_wallet or self.objective or self.points_priority):
            raise ValueError("choose a wallet adoption or an objective change")
        return self


ExplanationTargetKind = Literal[
    "cost_line",
    "payment_assignment",
    "itinerary_item",
    "transfer_recommendation",
    "inventory_quote",
]
ExplanationTopic = Literal["why_chosen", "how_priced", "payment_card", "freshness"]


class ExplanationRequest(BaseModel):
    """Explain an existing computed artifact. Reads, never recomputes."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["explanation_request"] = "explanation_request"
    target_kind: ExplanationTargetKind
    target_id: Annotated[str, Field(min_length=1, max_length=200)]
    topic: ExplanationTopic


ProfileSection = Literal["flight", "stay", "rhythm", "experiences", "constraints", "optimization"]

_PROFILE_PAYLOAD_TYPE: dict[ProfileSection, type[AnswerPayload]] = {
    "flight": FlightPreferencesPayload,
    "stay": StayPreferencesPayload,
    "rhythm": DailyRhythmPayload,
    "experiences": ExperiencesFoodPayload,
    "constraints": HardConstraintsPayload,
    "optimization": BudgetObjectivePayload,
}


class ProfileUpdateAction(BaseModel):
    """Propose a durable preference change. Proposing writes nothing."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["profile_update_proposal"] = "profile_update_proposal"
    section: ProfileSection
    candidate: AnswerPayload

    @model_validator(mode="before")
    @classmethod
    def coerce_candidate_type(cls, data: object) -> object:
        if isinstance(data, dict) and isinstance(data.get("candidate"), dict):
            section = data.get("section")
            payload_type = _PROFILE_PAYLOAD_TYPE.get(section)  # type: ignore[arg-type]
            if payload_type is not None:
                return {**data, "candidate": payload_type.model_validate(data["candidate"])}
        return data

    @model_validator(mode="after")
    def candidate_matches_section(self) -> ProfileUpdateAction:
        if not isinstance(self.candidate, _PROFILE_PAYLOAD_TYPE[self.section]):
            raise ValueError(f"candidate for {self.section} has the wrong shape")
        return self


class ClarificationChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Annotated[str, Field(min_length=1, max_length=120)]
    label: Annotated[str, Field(min_length=1, max_length=160)]


ClarificationReason = Literal[
    "ambiguous_item",
    "not_found",
    "ambiguous_date",
    "ambiguous_amount",
    "scope_conflict",
    "needs_detail",
    "unsupported",
]


class ClarificationRequired(BaseModel):
    """Ask one focused question instead of guessing."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["clarification_required"] = "clarification_required"
    reason: ClarificationReason
    question: Annotated[str, Field(min_length=1, max_length=300)]
    choices: Annotated[list[ClarificationChoice], Field(max_length=MAX_CLARIFICATION_CHOICES)] = (
        Field(default_factory=list)
    )


PostPlanAction = Annotated[
    DeterministicEdit
    | ScopedItineraryReplan
    | ProviderInvalidatingChange
    | WalletOrObjectiveChange
    | ExplanationRequest
    | ProfileUpdateAction
    | ClarificationRequired,
    Field(discriminator="kind"),
]

ACTION_KINDS: tuple[str, ...] = (
    "deterministic_edit",
    "scoped_itinerary_replan",
    "provider_invalidating_change",
    "wallet_or_objective_change",
    "explanation_request",
    "profile_update_proposal",
    "clarification_required",
)


# --------------------------------------------------------------------------- #
# Contexts                                                                     #
# --------------------------------------------------------------------------- #


class RoutingItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poi_id: Annotated[str, Field(min_length=1, max_length=120)]
    name: Annotated[str, Field(min_length=1, max_length=160)]


class RoutingDay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    items: list[RoutingItem] = Field(default_factory=list)


class ExplainableRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ExplanationTargetKind
    ref_id: Annotated[str, Field(min_length=1, max_length=200)]
    label: Annotated[str, Field(min_length=1, max_length=160)]


class RoutingContext(BaseModel):
    """Everything the router may match against: approved ids, names, dates, choices.

    No provider handle, no raw transcript, no arbitrary model-chosen field.
    """

    model_config = ConfigDict(extra="forbid")
    days: Annotated[list[RoutingDay], Field(min_length=1, max_length=MAX_ITINERARY_DAYS)]
    candidates: list[RoutingItem] = Field(default_factory=list)
    explainable: list[ExplainableRef] = Field(default_factory=list)
    brief: TripBrief

    @model_validator(mode="after")
    def days_are_ordered(self) -> RoutingContext:
        dates = [day.date for day in self.days]
        if dates != sorted(set(dates)):
            raise ValueError("itinerary days must be unique and in date order")
        return self


class DayOverride(BaseModel):
    """An existing day-local preference: this date keeps its own value for these questions."""

    model_config = ConfigDict(extra="forbid")
    date: date
    question_ids: list[QuestionId] = Field(default_factory=list)
    day_theme: str | None = None

    @field_validator("day_theme")
    @classmethod
    def theme_is_bounded_plain_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.casefold().split())
        if len(normalized) > MAX_DAY_THEME_CHARS or not _THEME_PATTERN.match(normalized):
            raise ValueError("a day theme is 3-60 plain lowercase letters")
        return normalized

    @model_validator(mode="after")
    def has_override(self) -> DayOverride:
        if not self.question_ids and self.day_theme is None:
            raise ValueError("a day override needs a question or a day theme")
        return self


class ImpactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    poi_id: str
    day_index: Annotated[int, Field(ge=0)]


class ImpactContext(BaseModel):
    """The workspace facts impact depends on. No provider handle, no model fields."""

    model_config = ConfigDict(extra="forbid")
    itinerary_dates: Annotated[list[date], Field(min_length=1, max_length=MAX_ITINERARY_DAYS)]
    items: list[ImpactItem] = Field(default_factory=list)
    day_overrides: list[DayOverride] = Field(default_factory=list)
    retained_hotel_area_id: str | None = None
    flight_fingerprint: str | None = None
    hotel_fingerprint: str | None = None

    @model_validator(mode="after")
    def dates_are_ordered(self) -> ImpactContext:
        if self.itinerary_dates != sorted(set(self.itinerary_dates)):
            raise ValueError("itinerary dates must be unique and in date order")
        return self


# --------------------------------------------------------------------------- #
# Search semantics                                                             #
# --------------------------------------------------------------------------- #


def _fingerprint(semantics: dict[str, object]) -> str:
    canonical = json.dumps(semantics, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def flight_fingerprint(brief: TripBrief) -> str:
    """Canonical identity of everything that can change a flight search.

    Includes preferences the present request schema cannot encode (baggage, seat), so a
    change to them is never mistaken for "same search".
    """
    essentials = brief.trip_essentials
    party = brief.purpose_and_party
    flight = brief.flight_preferences
    budget = brief.budget_and_objective
    return _fingerprint(
        {
            "origin": essentials.origin,
            "destination": essentials.destination,
            "start": essentials.start_date.isoformat(),
            "end": essentials.end_date.isoformat(),
            "travelers": essentials.travelers,
            "adults": party.adults if party else essentials.travelers,
            "child_ages": sorted(party.children_ages) if party else [],
            "cabin": flight.cabin if flight else "no_preference",
            "max_stops": flight.max_stops if flight else None,
            "schedule": flight.schedule if flight else "no_preference",
            "airport_flexible": flight.airport_flexible if flight else None,
            "checked_baggage": flight.checked_baggage if flight else None,
            "seat": flight.seat if flight else "no_preference",
            "style": budget.travel_style if budget else "balanced",
        }
    )


def hotel_fingerprint(brief: TripBrief, *, hotel_area_id: str | None) -> str:
    """Canonical identity of everything that can change a hotel search.

    ``hotel_area_id`` is the retained, itinerary-generated area: it is part of the
    search, so a replan cannot silently move the hotel.
    """
    essentials = brief.trip_essentials
    party = brief.purpose_and_party
    stay = brief.stay_preferences
    budget = brief.budget_and_objective
    return _fingerprint(
        {
            "destination": essentials.destination,
            "start": essentials.start_date.isoformat(),
            "end": essentials.end_date.isoformat(),
            "travelers": essentials.travelers,
            "child_ages": sorted(party.children_ages) if party else [],
            "rooms": stay.room_count if stay else 1,
            "room_needs": sorted(stay.room_needs) if stay else [],
            "lodging_styles": sorted(stay.lodging_styles) if stay else [],
            "neighborhoods": sorted(stay.neighborhood_priorities) if stay else [],
            "location_price": stay.location_price_tradeoff if stay else "no_preference",
            "style": budget.travel_style if budget else "balanced",
            "area": hotel_area_id,
        }
    )


# --------------------------------------------------------------------------- #
# Impact                                                                       #
# --------------------------------------------------------------------------- #

_D = InvalidatedDomain
_ALL: frozenset[InvalidatedDomain] = frozenset(_DOMAIN_ORDER)
_NONE: frozenset[InvalidatedDomain] = frozenset()
_ITIN: frozenset[InvalidatedDomain] = frozenset({_D.ITINERARY, _D.COST})
_FLIGHT: frozenset[InvalidatedDomain] = frozenset(
    {_D.FLIGHT, _D.AWARD, _D.COST, _D.CARD_STRATEGY}
)
_HOTEL: frozenset[InvalidatedDomain] = frozenset(
    {_D.HOTEL, _D.ITINERARY, _D.COST, _D.CARD_STRATEGY}
)
_STRATEGY: frozenset[InvalidatedDomain] = frozenset({_D.AWARD, _D.CARD_STRATEGY, _D.COST})

# (section, field) -> domains. Anything absent is treated as invalidating everything:
# an unclassified change must never be assumed harmless.
_FIELD_DOMAINS: dict[tuple[str, str], frozenset[InvalidatedDomain]] = {
    ("trip_essentials", "origin"): _ALL,
    ("trip_essentials", "destination"): _ALL,
    ("trip_essentials", "start_date"): _ALL,
    ("trip_essentials", "end_date"): _ALL,
    ("trip_essentials", "travelers"): _ALL,
    ("trip_essentials", "date_flexibility_days"): _NONE,
    ("purpose_and_party", "adults"): _ALL,
    ("purpose_and_party", "children_ages"): _ALL,
    ("purpose_and_party", "purpose"): _ITIN,
    ("purpose_and_party", "companion_notes"): _ITIN,
    ("budget_and_objective", "travel_style"): _ALL,
    ("budget_and_objective", "budget_minor"): frozenset({_D.COST}),
    ("budget_and_objective", "currency"): _STRATEGY,
    ("budget_and_objective", "objective"): _STRATEGY,
    ("budget_and_objective", "points_priority"): _STRATEGY,
    ("flight_preferences", "cabin"): _FLIGHT,
    ("flight_preferences", "max_stops"): _FLIGHT,
    ("flight_preferences", "schedule"): _FLIGHT,
    ("flight_preferences", "airport_flexible"): _FLIGHT,
    ("flight_preferences", "checked_baggage"): _FLIGHT,
    ("flight_preferences", "seat"): _FLIGHT,
    ("stay_preferences", "lodging_styles"): _HOTEL,
    ("stay_preferences", "neighborhood_priorities"): _HOTEL,
    ("stay_preferences", "room_count"): _HOTEL,
    ("stay_preferences", "room_needs"): _HOTEL,
    ("stay_preferences", "location_price_tradeoff"): _HOTEL,
    ("daily_rhythm", "pace"): _ITIN,
    ("daily_rhythm", "day_start"): _ITIN,
    ("daily_rhythm", "evening_style"): _ITIN,
    ("daily_rhythm", "downtime_minutes"): _ITIN,
    ("daily_rhythm", "transit_tolerance_minutes"): _ITIN,
    ("daily_rhythm", "day_trip_appetite"): _ITIN,
    ("experiences_and_food", "interests"): _ITIN,
    ("experiences_and_food", "food_interests"): _ITIN,
    ("experiences_and_food", "iconic_local_balance"): _ITIN,
    ("experiences_and_food", "nightlife"): _ITIN,
    ("experiences_and_food", "shopping"): _ITIN,
    ("hard_constraints", "has_constraints"): _ITIN,
    ("hard_constraints", "dietary"): _ITIN,
    ("hard_constraints", "accessibility"): _ITIN,
    ("hard_constraints", "exclusions"): _ITIN,
    ("hard_constraints", "immovable_events"): _ITIN,
    ("wallet", "card_ids"): _STRATEGY,
    ("wallet", "points_balances"): _STRATEGY,
}

_ADAPTIVE_DOMAINS: dict[QuestionId, frozenset[InvalidatedDomain]] = {
    QuestionId.CELEBRATION_DETAILS: _ITIN,
    QuestionId.CHILDREN_NEEDS: _ITIN,
    QuestionId.MOBILITY_DETAILS: _ITIN,
    QuestionId.FOOD_DEPTH: _ITIN,
    QuestionId.POINTS_STRATEGY: _STRATEGY,
    QuestionId.FLIGHT_TRADEOFF: _FLIGHT,
    QuestionId.HOTEL_TRADEOFF: _HOTEL,
}

_LIMITATIONS: dict[tuple[str, str], str] = {
    ("trip_essentials", "date_flexibility_days"): (
        "Date flexibility is recorded but not searched: plans use the exact confirmed dates."
    ),
    ("flight_preferences", "checked_baggage"): (
        "Baggage preferences are not guaranteed by the current inventory source."
    ),
    ("flight_preferences", "seat"): (
        "Seat preferences are not guaranteed by the current inventory source."
    ),
    ("hard_constraints", "accessibility"): (
        "Accessibility needs are recorded as preferences; venue accessibility is not verified."
    ),
}


class ActionImpact(BaseModel):
    """Server-derived consequences of an action. Never supplied by a caller or a model."""

    model_config = ConfigDict(extra="forbid")
    invalidated_domains: list[InvalidatedDomain]
    affected_dates: list[date]
    refetch_domains: list[Literal["flight", "hotel"]]
    inventory_reuse: Literal["full", "partial", "none"]
    requires_confirmation: bool
    changes_trip: bool
    explanation_only: bool
    limitations: list[str] = Field(default_factory=list)


def _sorted_domains(domains: set[InvalidatedDomain]) -> list[InvalidatedDomain]:
    closed = set(domains)
    if closed & {_D.FLIGHT, _D.HOTEL}:
        closed |= {_D.COST, _D.CARD_STRATEGY}
    if _D.AWARD in closed:
        closed |= {_D.COST, _D.CARD_STRATEGY}
    if _D.ITINERARY in closed:
        closed.add(_D.COST)
    return [domain for domain in _DOMAIN_ORDER if domain in closed]


def _changed_fields(before: TripBrief, after: TripBrief) -> set[tuple[str, str]]:
    if before.home != after.home:
        raise ValueError("the traveler's home context cannot change after planning")
    changed: set[tuple[str, str]] = set()
    for attr in _SECTION_ATTR.values():
        left = getattr(before, attr)
        right = getattr(after, attr)
        if left == right:
            continue
        if left is None or right is None:
            fields = (left or right).__class__.model_fields
            changed.update((attr, name) for name in fields)
            continue
        changed.update(
            (attr, name)
            for name in type(left).model_fields
            if getattr(left, name) != getattr(right, name)
        )
    for qid in set(before.adaptive_details) | set(after.adaptive_details):
        if before.adaptive_details.get(qid) != after.adaptive_details.get(qid):
            changed.add((qid.value, "detail"))
    if before.wallet.card_ids != after.wallet.card_ids:
        changed.add(("wallet", "card_ids"))
    if before.wallet.points_balances != after.wallet.points_balances:
        changed.add(("wallet", "points_balances"))
    return changed


def _domains_for(changed: set[tuple[str, str]]) -> tuple[set[InvalidatedDomain], list[str]]:
    domains: set[InvalidatedDomain] = set()
    limitations: list[str] = []
    for key in sorted(changed):
        section, field = key
        if section in {q.value for q in _ADAPTIVE_DOMAINS}:
            domains |= _ADAPTIVE_DOMAINS[QuestionId(section)]
        else:
            domains |= _FIELD_DOMAINS.get(key, _ALL)
        note = _LIMITATIONS.get(key)
        if note is not None and note not in limitations:
            limitations.append(note)
    return domains, limitations


def _dates_of(brief: TripBrief) -> list[date]:
    essentials = brief.trip_essentials
    nights = (essentials.end_date - essentials.start_date).days
    return [essentials.start_date + timedelta(days=offset) for offset in range(nights)]


def _refetch(
    before: TripBrief, after: TripBrief, context: ImpactContext
) -> list[Literal["flight", "hotel"]]:
    retained_flight = context.flight_fingerprint or flight_fingerprint(before)
    area = context.retained_hotel_area_id
    retained_hotel = context.hotel_fingerprint or hotel_fingerprint(before, hotel_area_id=area)
    refetch: list[Literal["flight", "hotel"]] = []
    if flight_fingerprint(after) != retained_flight:
        refetch.append("flight")
    if hotel_fingerprint(after, hotel_area_id=area) != retained_hotel:
        refetch.append("hotel")
    return refetch


def _reuse(refetch: list[Literal["flight", "hotel"]]) -> Literal["full", "partial", "none"]:
    if not refetch:
        return "full"
    return "partial" if len(refetch) == 1 else "none"


def _edit_dates(edit: ItineraryEdit, context: ImpactContext) -> list[date]:
    dates = context.itinerary_dates
    on_day: dict[str, set[int]] = {}
    for item in context.items:
        on_day.setdefault(item.poi_id, set()).add(item.day_index)

    def at(index: int) -> date:
        if not 0 <= index < len(dates):
            raise ValueError(f"day index {index} is outside this itinerary")
        return dates[index]

    if isinstance(edit, RemoveItem):
        if edit.day_index not in on_day.get(edit.poi_id, set()):
            raise ValueError("that item is not on that day")
        return [at(edit.day_index)]
    if isinstance(edit, MoveItem):
        if edit.from_day_index not in on_day.get(edit.poi_id, set()):
            raise ValueError("that item is not on the day it is being moved from")
        return sorted({at(edit.from_day_index), at(edit.to_day_index)})
    if isinstance(edit, ReplaceItem):
        if edit.day_index not in on_day.get(edit.old_poi_id, set()):
            raise ValueError("the item to replace is not on that day")
        return [at(edit.day_index)]
    if isinstance(edit, ReorderDay):
        expected = {i.poi_id for i in context.items if i.day_index == edit.day_index}
        if set(edit.poi_ids) != expected or len(set(edit.poi_ids)) != len(edit.poi_ids):
            raise ValueError("a reorder must list exactly the items already on that day")
        return [at(edit.day_index)]
    return [at(edit.day_index)]  # AddItem


def impact_context_from_routing(context: RoutingContext) -> ImpactContext:
    """The reference facts of a routing context, as an impact context (no fingerprints)."""
    return ImpactContext(
        itinerary_dates=[day.date for day in context.days],
        items=[
            ImpactItem(poi_id=item.poi_id, day_index=index)
            for index, day in enumerate(context.days)
            for item in day.items
        ],
    )


def validate_action_references(action: PostPlanAction, context: RoutingContext) -> None:
    """Reject an action that names anything the workspace does not contain.

    Applies to every source of actions (typed controls, deterministic routing, a model):
    ids, dates, positions and explanation targets must exist in ``context``; patches
    must apply cleanly to the current brief. Raises ``ValueError`` with a plain reason.
    """
    if isinstance(action, DeterministicEdit):
        edit = action.edit
        impact = impact_context_from_routing(context)
        _edit_dates(edit, impact)  # existing items, in-range days
        candidates = {c.poi_id for c in context.candidates}
        if isinstance(edit, AddItem):
            if edit.poi_id not in candidates:
                raise ValueError("that place is not an approved suggestion")
            if edit.position > len(context.days[edit.day_index].items):
                raise ValueError("that position is past the end of the day")
        elif isinstance(edit, ReplaceItem):
            if edit.new_poi_id not in candidates:
                raise ValueError("that place is not an approved suggestion")
        elif isinstance(edit, MoveItem):
            target = len(context.days[edit.to_day_index].items)
            if edit.from_day_index == edit.to_day_index:
                target -= 1
            if edit.position > max(target, 0):
                raise ValueError("that position is past the end of the day")
    elif isinstance(action, ScopedItineraryReplan):
        dates = [day.date for day in context.days]
        if any(d not in dates for d in action.affected_dates):
            raise ValueError("a replan names a date outside this itinerary")
        if action.scope == "trip" and sorted(action.affected_dates) != dates:
            raise ValueError("a trip-wide replan must name every itinerary date")
        if action.patch is not None:
            apply_brief_patch(context.brief, action.patch)
    elif isinstance(action, ProviderInvalidatingChange):
        apply_brief_patch(context.brief, action.patch)
    elif isinstance(action, WalletOrObjectiveChange):
        objective_patch(context.brief, action)
    elif isinstance(action, ExplanationRequest):
        known = {(ref.kind, ref.ref_id) for ref in context.explainable}
        if (action.target_kind, action.target_id) not in known:
            raise ValueError("that is not something this plan can explain")


def _no_brief_change(before: TripBrief, after: TripBrief, what: str) -> None:
    if before != after:
        raise ValueError(f"{what} cannot change the brief")


def compute_impact(
    before: TripBrief,
    after: TripBrief,
    *,
    action: PostPlanAction,
    context: ImpactContext,
) -> ActionImpact:
    """What ``action`` invalidates, from the action and the workspace — not from a caller.

    ``before`` and ``after`` are the briefs the action moves between. They are not
    enough on their own: a removal, a day-local pace override and an explanation all
    leave the global brief unchanged yet mean different work, so the validated action
    and the workspace context decide the scope and the confirmation requirement.
    """
    if before.home != after.home:
        raise ValueError("the traveler's home context cannot change after planning")
    if isinstance(action, DeterministicEdit):
        _no_brief_change(before, after, "an itinerary edit")
        return ActionImpact(
            invalidated_domains=_sorted_domains({_D.ITINERARY}),
            affected_dates=_edit_dates(action.edit, context),
            refetch_domains=[],
            inventory_reuse="full",
            requires_confirmation=False,
            changes_trip=True,
            explanation_only=False,
        )
    if isinstance(action, ExplanationRequest):
        _no_brief_change(before, after, "an explanation")
        return ActionImpact(
            invalidated_domains=[],
            affected_dates=[],
            refetch_domains=[],
            inventory_reuse="full",
            requires_confirmation=False,
            changes_trip=False,
            explanation_only=True,
        )
    if isinstance(action, ClarificationRequired):
        _no_brief_change(before, after, "a clarification")
        return ActionImpact(
            invalidated_domains=[],
            affected_dates=[],
            refetch_domains=[],
            inventory_reuse="full",
            requires_confirmation=False,
            changes_trip=False,
            explanation_only=False,
        )
    if isinstance(action, ProfileUpdateAction):
        _no_brief_change(before, after, "a profile proposal")
        return ActionImpact(
            invalidated_domains=[],
            affected_dates=[],
            refetch_domains=[],
            inventory_reuse="full",
            requires_confirmation=True,
            changes_trip=False,
            explanation_only=False,
            limitations=["Approving saves a durable preference; this trip is not changed."],
        )
    if isinstance(action, ScopedItineraryReplan):
        return _scoped_impact(before, after, action, context)
    if isinstance(action, ProviderInvalidatingChange):
        if after != apply_brief_patch(before, action.patch):
            raise ValueError("the after-brief is not the patch applied to the before-brief")
        return _brief_change_impact(before, after, context, confirm_on_wallet=False)
    return _wallet_impact(before, after, action, context)


def _scoped_impact(
    before: TripBrief, after: TripBrief, action: ScopedItineraryReplan, context: ImpactContext
) -> ActionImpact:
    unknown = [d for d in action.affected_dates if d not in context.itinerary_dates]
    if unknown:
        raise ValueError("a scoped replan names a date outside this itinerary")
    domains: set[InvalidatedDomain] = {_D.ITINERARY}
    limitations: list[str] = []
    if action.scope == "dates":
        _no_brief_change(before, after, "a day-local replan")
        affected = sorted(action.affected_dates)
        if action.patch is not None:
            fields = {
                (_SECTION_ATTR.get(e.question_id, e.question_id.value), name)
                for e in action.patch.entries
                for name in type(e.payload).model_fields
            }
            _, limitations = _domains_for(fields)
    else:
        assert action.patch is not None  # enforced by the action model
        if sorted(action.affected_dates) != context.itinerary_dates:
            raise ValueError("a trip-wide replan must name every itinerary date")
        if after != apply_brief_patch(before, action.patch):
            raise ValueError("the after-brief is not the patch applied to the before-brief")
        changed = _changed_fields(before, after)
        if not changed:
            return ActionImpact(
                invalidated_domains=[],
                affected_dates=[],
                refetch_domains=[],
                inventory_reuse="full",
                requires_confirmation=False,
                changes_trip=False,
                explanation_only=False,
                limitations=["This preference already matches the plan; nothing to replan."],
            )
        domains, limitations = _domains_for(changed)
        patched = action.patch.question_ids
        overridden = {
            override.date
            for override in context.day_overrides
            if patched <= set(override.question_ids)
        }
        affected = [d for d in context.itinerary_dates if d not in overridden]
    # Itinerary-only questions cannot alter a provider search (the action model enforces
    # it), so a scoped replan never re-queries. Whether retained evidence is still usable
    # is the service layer's decision, made before any scoped work starts.
    return ActionImpact(
        invalidated_domains=_sorted_domains(domains),
        affected_dates=affected,
        refetch_domains=[],
        inventory_reuse="full",
        requires_confirmation=False,
        changes_trip=bool(affected),
        explanation_only=False,
        limitations=limitations,
    )


def _brief_change_impact(
    before: TripBrief, after: TripBrief, context: ImpactContext, *, confirm_on_wallet: bool
) -> ActionImpact:
    changed = _changed_fields(before, after)
    domains, limitations = _domains_for(changed)
    refetch = _refetch(before, after, context)
    if "flight" in refetch:
        domains |= {_D.FLIGHT}
    if "hotel" in refetch:
        domains |= {_D.HOTEL}
    # Evidence is only invalidated when its search actually changed; a hotel-only change
    # leaves flight evidence reusable and vice versa.
    if "flight" not in refetch:
        domains.discard(_D.FLIGHT)
    if "hotel" not in refetch:
        domains.discard(_D.HOTEL)
    sorted_domains = _sorted_domains(domains)
    affected: list[date] = []
    if _D.ITINERARY in sorted_domains:
        affected = _dates_of(after)
    wallet_changed = ("wallet", "card_ids") in changed or ("wallet", "points_balances") in changed
    return ActionImpact(
        invalidated_domains=sorted_domains,
        affected_dates=affected,
        refetch_domains=refetch,
        inventory_reuse=_reuse(refetch),
        requires_confirmation=bool(refetch) or (confirm_on_wallet and wallet_changed),
        changes_trip=bool(changed),
        explanation_only=False,
        limitations=limitations,
    )


def _wallet_impact(
    before: TripBrief, after: TripBrief, action: WalletOrObjectiveChange, context: ImpactContext
) -> ActionImpact:
    expected = after
    if not action.adopt_current_wallet:
        expected = after.model_copy(update={"wallet": before.wallet})
    if expected.wallet != before.wallet and not action.adopt_current_wallet:
        raise ValueError("the wallet changed without a wallet adoption")
    if not (action.objective or action.points_priority):
        if after.model_copy(update={"wallet": before.wallet}) != before:
            raise ValueError("a wallet adoption can change only the wallet")
    impact = _brief_change_impact(before, after, context, confirm_on_wallet=True)
    if impact.refetch_domains:
        raise ValueError("a wallet or objective change cannot change a provider search")
    return impact


def objective_patch(brief: TripBrief, action: WalletOrObjectiveChange) -> BriefPatch | None:
    """The brief patch an objective change means, or ``None`` if it has none.

    Raises ``ValueError`` when the brief holds no budget/objective answer to amend: the
    caller should then ask for it rather than invent a budget and currency.
    """
    if action.objective is None and action.points_priority is None:
        return None
    current = brief.budget_and_objective
    if current is None:
        raise ValueError("there is no budget and objective answer to amend")
    updated = current.model_copy(
        update={
            "objective": action.objective or current.objective,
            "points_priority": action.points_priority or current.points_priority,
        }
    )
    return BriefPatch(
        entries=[PatchEntry(question_id=QuestionId.BUDGET_AND_OBJECTIVE, payload=updated)]
    )


def apply_wallet_or_objective(
    brief: TripBrief, action: WalletOrObjectiveChange, *, current_wallet: UserWallet | None
) -> TripBrief:
    """Apply a wallet/objective action. ``current_wallet`` is the stored wallet at approval."""
    updated = brief
    patch = objective_patch(brief, action)
    if patch is not None:
        updated = apply_brief_patch(updated, patch)
    if action.adopt_current_wallet:
        if current_wallet is None:
            raise ValueError("no current wallet was supplied to adopt")
        updated = updated.model_copy(update={"wallet": current_wallet})
    return TripBrief.model_validate(updated.model_dump(mode="python"))


# --------------------------------------------------------------------------- #
# Deterministic routing                                                        #
# --------------------------------------------------------------------------- #

_INTERESTS: tuple[str, ...] = (
    "food",
    "nature",
    "culture",
    "museums",
    "shopping",
    "nightlife",
    "history",
    "art",
    "architecture",
    "parks",
)
_WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
_MONTH_DAY = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)? (?:of )?"
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
)
_RELATIVE = re.compile(
    r"\b(today|tomorrow|tonight|yesterday|next week|this weekend|the day after"
    r"|day after tomorrow)\b"
)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_REF = re.compile(r"\bday (\d{1,2})\b")


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    folded = re.sub(r"[^\w\s:,\-/']", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


class _Clarify(Exception):  # noqa: N818 - control flow inside this module only
    def __init__(self, action: ClarificationRequired) -> None:
        super().__init__(action.question)
        self.action = action


def _clarify(
    reason: ClarificationReason,
    question: str,
    choices: list[ClarificationChoice] | None = None,
) -> _Clarify:
    return _Clarify(
        ClarificationRequired(
            reason=reason,
            question=question[:300],
            choices=(choices or [])[:MAX_CLARIFICATION_CHOICES],
        )
    )


def _prepare(text: str) -> str:
    if len(text) > MAX_COMMAND_CHARS:
        raise PostPlanInputError(f"a request is limited to {MAX_COMMAND_CHARS} characters")
    cleaned = text.strip()
    if not cleaned:
        raise PostPlanInputError("a request cannot be empty")
    return cleaned


def _find_names(
    norm: str, entries: list[tuple[str, int, RoutingItem]]
) -> list[tuple[str, int, RoutingItem]]:
    """Entries whose exact normalized name occurs in ``norm``; nested shorter names drop out."""
    spans: list[tuple[int, int, tuple[str, int, RoutingItem]]] = []
    for entry in entries:
        name = _norm(entry[2].name)
        if not name:
            continue
        for found in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", norm):
            spans.append((found.start(), found.end(), entry))
    kept: list[tuple[str, int, RoutingItem]] = []
    for start, end, entry in spans:
        contained = any(
            (s <= start and end <= e) and (s, e) != (start, end) for s, e, _ in spans
        )
        if not contained:
            kept.append(entry)
    unique: list[tuple[str, int, RoutingItem]] = []
    for entry in kept:
        if entry not in unique:
            unique.append(entry)
    return unique


def _itinerary_entries(context: RoutingContext) -> list[tuple[str, int, RoutingItem]]:
    return [
        (item.poi_id, index, item)
        for index, day in enumerate(context.days)
        for item in day.items
    ]


def _day_label(context: RoutingContext, index: int) -> str:
    return f"day {index + 1} ({context.days[index].date.isoformat()})"


def _resolve_day(norm: str, context: RoutingContext) -> int | None:
    """A day index named in the text, ``None`` if none is named, or a clarification."""
    if _RELATIVE.search(norm):
        raise _clarify(
            "ambiguous_date",
            "Which day do you mean? Please name it as 'day N' or by its date (YYYY-MM-DD).",
            [
                ClarificationChoice(id=f"day:{i}", label=_day_label(context, i))
                for i in range(len(context.days))
            ],
        )
    found: list[int] = []
    for match in _DAY_REF.finditer(norm):
        number = int(match.group(1))
        if not 1 <= number <= len(context.days):
            raise _clarify(
                "not_found",
                f"This itinerary has {len(context.days)} days; there is no day {number}.",
            )
        found.append(number - 1)
    dates = [day.date for day in context.days]
    for match in _ISO_DATE.finditer(norm):
        try:
            when = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        if when in dates:
            found.append(dates.index(when))
    for weekday in _WEEKDAYS:
        if re.search(rf"\b{weekday}\b", norm):
            matches = [i for i, d in enumerate(dates) if d.weekday() == _WEEKDAYS.index(weekday)]
            if len(matches) != 1:
                raise _clarify(
                    "ambiguous_date",
                    f"Which {weekday} do you mean?",
                    [
                        ClarificationChoice(id=f"day:{i}", label=_day_label(context, i))
                        for i in matches
                    ],
                )
            found.append(matches[0])
    if not found:
        return None
    if len(set(found)) > 1:
        raise _clarify("scope_conflict", "Please name one day at a time.")
    return found[0]


def _item_choices(
    context: RoutingContext, entries: list[tuple[str, int, RoutingItem]], verb: str
) -> list[ClarificationChoice]:
    return [
        ClarificationChoice(
            id=f"{verb}:{poi_id}:{day_index}",
            label=f"{item.name} on {_day_label(context, day_index)}",
        )
        for poi_id, day_index, item in entries
    ]


def _single_itinerary_item(
    norm: str, context: RoutingContext, *, verb: str, day: int | None
) -> tuple[str, int, RoutingItem]:
    matches = _find_names(norm, _itinerary_entries(context))
    if day is not None:
        matches = [m for m in matches if m[1] == day]
    if not matches:
        raise _clarify(
            "not_found",
            "I couldn't find that in your plan. Which stop did you mean?",
            _item_choices(context, _itinerary_entries(context), verb),
        )
    if len({m[0] for m in matches}) > 1:
        raise _clarify(
            "scope_conflict",
            "I can change one stop at a time. Which one first?",
            _item_choices(context, matches, verb),
        )
    if len(matches) > 1:
        raise _clarify("ambiguous_item", "That stop appears more than once. Which one?",
                       _item_choices(context, matches, verb))
    return matches[0]


def _rule_reorder(norm: str, context: RoutingContext) -> PostPlanAction | None:
    match = re.search(r"\breorder day (\d{1,2})\s*[:\-]\s*(.+)$", norm)
    if match is None:
        return None
    index = int(match.group(1)) - 1
    if not 0 <= index < len(context.days):
        raise _clarify("not_found", f"There is no day {index + 1} in this itinerary.")
    names = [part.strip() for part in re.split(r",| then | and ", match.group(2)) if part.strip()]
    day_items = {_norm(item.name): item for item in context.days[index].items}
    ordered: list[str] = []
    for name in names:
        item = day_items.get(name)
        if item is None:
            raise _clarify("not_found", f"'{name}' is not on {_day_label(context, index)}.")
        ordered.append(item.poi_id)
    if len(set(ordered)) != len(day_items):
        raise _clarify(
            "needs_detail", "To reorder a day, list every stop on it in the order you want."
        )
    return DeterministicEdit(edit=ReorderDay(day_index=index, poi_ids=ordered))


def _rule_replace(norm: str, context: RoutingContext) -> PostPlanAction | None:
    match = re.search(r"\b(?:replace|swap)\b\s+(.+?)\s+(?:with|for)\s+(.+)$", norm)
    if match is None:
        return None
    day = _resolve_day(norm, context)
    old_entries = _find_names(match.group(1), _itinerary_entries(context))
    if day is not None:
        old_entries = [e for e in old_entries if e[1] == day]
    if len(old_entries) != 1:
        raise _clarify(
            "not_found" if not old_entries else "ambiguous_item",
            "Which stop should be replaced?",
            _item_choices(context, old_entries or _itinerary_entries(context), "replace"),
        )
    new_matches = _find_names(
        match.group(2), [(c.poi_id, -1, c) for c in context.candidates]
    )
    if len(new_matches) != 1:
        raise _clarify("not_found", "I can only swap in a place from your suggestions list.")
    old_id, day_index, _ = old_entries[0]
    new_id = new_matches[0][0]
    if new_id == old_id:
        raise _clarify("needs_detail", "That is already the stop in your plan.")
    return DeterministicEdit(
        edit=ReplaceItem(old_poi_id=old_id, new_poi_id=new_id, day_index=day_index)
    )


def _rule_move(norm: str, context: RoutingContext) -> PostPlanAction | None:
    if not re.search(r"\bmove\b", norm):
        return None
    target = re.search(r"\bto (day \d{1,2}|\d{4}-\d{2}-\d{2}|[a-z]+day)\b", norm)
    if target is None:
        raise _clarify("needs_detail", "Which day should it move to? Say 'day N' or a date.")
    after_to = norm[target.start():]
    before_to = norm[: target.start()]
    to_index = _resolve_day(after_to, context)
    if to_index is None:
        raise _clarify("needs_detail", "Which day should it move to?")
    from_day = _resolve_day(before_to, context)
    poi_id, from_index, _item = _single_itinerary_item(
        before_to, context, verb="move", day=from_day
    )
    last = len(context.days[to_index].items)
    if from_index == to_index:
        last -= 1
    position = 0 if re.search(r"\b(first|start|beginning)\b", after_to) else max(last, 0)
    return DeterministicEdit(
        edit=MoveItem(
            poi_id=poi_id, from_day_index=from_index, to_day_index=to_index, position=position
        )
    )


def _rule_remove(norm: str, context: RoutingContext) -> PostPlanAction | None:
    if not re.search(r"\b(remove|delete|drop|skip|cancel|take out|get rid of|cut)\b", norm):
        return None
    day = _resolve_day(norm, context)
    poi_id, day_index, _ = _single_itinerary_item(norm, context, verb="remove", day=day)
    return DeterministicEdit(edit=RemoveItem(poi_id=poi_id, day_index=day_index))


def _rule_add(norm: str, context: RoutingContext) -> PostPlanAction | None:
    if not re.search(r"\b(add|include|put in)\b", norm):
        return None
    matches = _find_names(norm, [(c.poi_id, -1, c) for c in context.candidates])
    if not matches:
        return None
    if len(matches) > 1:
        raise _clarify("scope_conflict", "I can add one place at a time. Which first?")
    day = _resolve_day(norm, context)
    if day is None:
        raise _clarify(
            "needs_detail",
            f"Which day should {matches[0][2].name} go on?",
            [
                ClarificationChoice(id=f"add:{matches[0][0]}:{i}", label=_day_label(context, i))
                for i in range(len(context.days))
            ],
        )
    return DeterministicEdit(
        edit=AddItem(poi_id=matches[0][0], day_index=day, position=len(context.days[day].items))
    )


def _current_rhythm(brief: TripBrief) -> DailyRhythmPayload:
    return brief.daily_rhythm or DailyRhythmPayload(
        pace="no_preference",
        day_start="no_preference",
        evening_style="no_preference",
        day_trip_appetite="no_preference",
    )


def _rule_pace(norm: str, context: RoutingContext) -> PostPlanAction | None:
    relaxed = re.search(
        r"\b(more relaxed|relaxed|slower|slow down|less packed|less rushed|take it easy"
        r"|fewer activities|laid back)\b",
        norm,
    )
    packed = re.search(
        r"\b(more packed|packed|busier|more activities|jam packed|fuller|faster pace)\b", norm
    )
    if relaxed is None and packed is None:
        return None
    if relaxed is not None and packed is not None:
        raise _clarify("scope_conflict", "Do you want a slower or a busier pace?")
    pace: Literal["relaxed", "packed"] = "relaxed" if relaxed else "packed"
    day = _resolve_day(norm, context)
    patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.DAILY_RHYTHM,
                payload=_current_rhythm(context.brief).model_copy(update={"pace": pace}),
            )
        ]
    )
    if day is not None:
        return ScopedItineraryReplan(
            scope="dates", affected_dates=[context.days[day].date], patch=patch
        )
    return ScopedItineraryReplan(
        scope="trip", affected_dates=[d.date for d in context.days], patch=patch
    )


def _rule_interests(norm: str, context: RoutingContext) -> PostPlanAction | None:
    match = re.search(rf"\bmore ({'|'.join(_INTERESTS)})\b", norm)
    if match is None:
        return None
    interest = match.group(1)
    day = _resolve_day(norm, context)
    if day is not None:
        return ScopedItineraryReplan(
            scope="dates", affected_dates=[context.days[day].date], day_theme=interest
        )
    current = context.brief.experiences_and_food or ExperiencesFoodPayload(
        iconic_local_balance="no_preference"
    )
    interests = list(current.interests)
    if interest not in [i.casefold() for i in interests]:
        interests.append(interest)
    patch = BriefPatch(
        entries=[
            PatchEntry(
                question_id=QuestionId.EXPERIENCES_AND_FOOD,
                payload=current.model_copy(update={"interests": interests}),
            )
        ]
    )
    return ScopedItineraryReplan(
        scope="trip", affected_dates=[d.date for d in context.days], patch=patch
    )


def _rule_theme(norm: str, context: RoutingContext) -> PostPlanAction | None:
    match = re.search(
        rf"\bmake day (\d{{1,2}}) (?:about|a|more)\s+({'|'.join(_INTERESTS)})\b", norm
    )
    if match is None:
        return None
    index = int(match.group(1)) - 1
    if not 0 <= index < len(context.days):
        raise _clarify("not_found", f"There is no day {index + 1} in this itinerary.")
    return ScopedItineraryReplan(
        scope="dates", affected_dates=[context.days[index].date], day_theme=match.group(2)
    )


def _essentials_patch(
    brief: TripBrief, **changes: object
) -> list[PatchEntry]:
    updated = brief.trip_essentials.model_copy(update=changes)
    # Re-run the payload validators (trip length, ordering, IATA) on the new values.
    validated = TripEssentialsPayload.model_validate(updated.model_dump())
    return [PatchEntry(question_id=QuestionId.TRIP_ESSENTIALS, payload=validated)]


def _rule_dates(
    norm: str, original: str, context: RoutingContext
) -> PostPlanAction | None:
    if not re.search(r"\b(dates?|trip|travel|leave|depart|return|from)\b", norm):
        return None
    isos = []
    for match in _ISO_DATE.finditer(norm):
        try:
            isos.append(date(int(match.group(1)), int(match.group(2)), int(match.group(3))))
        except ValueError:
            raise _clarify("ambiguous_date", "That is not a valid date. Use YYYY-MM-DD.") from None
    wants_change = re.search(r"\b(change|move|shift|reschedule|make)\b", norm) and re.search(
        r"\b(dates?|trip)\b", norm
    )
    month_named = _MONTH_DAY.search(norm) is not None
    if not wants_change:
        return None
    if month_named and len(isos) != 2:
        raise _clarify(
            "ambiguous_date",
            "Please give the new dates as YYYY-MM-DD to YYYY-MM-DD so I don't guess the year.",
        )
    if len(isos) != 2:
        if not isos and not month_named:
            return None
        raise _clarify(
            "ambiguous_date", "I need both the new start and end dates, as YYYY-MM-DD."
        )
    start, end = sorted(isos)
    try:
        entries = _essentials_patch(context.brief, start_date=start, end_date=end)
    except ValueError:
        raise _clarify(
            "ambiguous_date", "Trips here run 3 to 7 nights. What start and end dates do you want?"
        ) from None
    return ProviderInvalidatingChange(patch=BriefPatch(entries=entries))


def _rule_destination(norm: str, original: str, context: RoutingContext) -> PostPlanAction | None:
    if not re.search(r"\b(change|switch|go to|fly to)\b", norm) or "destination" not in norm:
        return None
    codes = re.findall(r"\b([A-Z]{3})\b", original)
    codes = [c for c in codes if c != context.brief.trip_essentials.destination]
    if len(codes) != 1:
        raise _clarify("needs_detail", "Give the new destination as a 3-letter airport code.")
    try:
        entries = _essentials_patch(context.brief, destination=codes[0])
    except ValueError:
        raise _clarify("needs_detail", "That is not a valid airport code.") from None
    return ProviderInvalidatingChange(patch=BriefPatch(entries=entries))


def _rule_travelers(norm: str, context: RoutingContext) -> PostPlanAction | None:
    match = re.search(r"\b(\d{1,2}) (?:travell?ers|people|adults|passengers|guests)\b", norm)
    if match is None or not re.search(r"\b(change|make|for|now|update)\b", norm):
        return None
    total = int(match.group(1))
    brief = context.brief
    party = brief.purpose_and_party
    try:
        entries = _essentials_patch(brief, travelers=total)
        if party is not None:
            adults = total - len(party.children_ages)
            if adults < 1:
                raise ValueError("no adults")
            entries.append(
                PatchEntry(
                    question_id=QuestionId.PURPOSE_AND_PARTY,
                    payload=party.model_copy(update={"adults": adults}),
                )
            )
    except ValueError:
        raise _clarify(
            "ambiguous_amount",
            "I can't fit that group size with the children already listed. How many adults?",
        ) from None
    return ProviderInvalidatingChange(patch=BriefPatch(entries=entries))


def _flight_payload(brief: TripBrief) -> FlightPreferencesPayload:
    return brief.flight_preferences or FlightPreferencesPayload(
        cabin="no_preference", schedule="no_preference"
    )


def _rule_cabin(norm: str, context: RoutingContext) -> PostPlanAction | None:
    if not re.search(r"\b(cabin|class|fly|flights?|upgrade)\b", norm):
        return None
    cabins = {
        "premium economy": "premium_economy",
        "business": "business",
        "first": "first",
        "economy": "economy",
    }
    for phrase, value in cabins.items():
        if re.search(rf"\b{phrase}\b", norm):
            payload = _flight_payload(context.brief).model_copy(update={"cabin": value})
            return ProviderInvalidatingChange(
                patch=BriefPatch(
                    entries=[PatchEntry(question_id=QuestionId.FLIGHT_PREFERENCES, payload=payload)]
                )
            )
    if re.search(r"\b(non ?stop|direct flights? only)\b", norm):
        payload = _flight_payload(context.brief).model_copy(update={"max_stops": 0})
        return ProviderInvalidatingChange(
            patch=BriefPatch(
                entries=[PatchEntry(question_id=QuestionId.FLIGHT_PREFERENCES, payload=payload)]
            )
        )
    return None


def _rule_rooms(norm: str, context: RoutingContext) -> PostPlanAction | None:
    match = re.search(r"\b(\d{1,2}) rooms?\b", norm)
    if match is None:
        return None
    stay = context.brief.stay_preferences or StayPreferencesPayload(
        location_price_tradeoff="no_preference"
    )
    try:
        payload = stay.model_copy(update={"room_count": int(match.group(1))})
        payload = StayPreferencesPayload.model_validate(payload.model_dump())
    except ValueError:
        raise _clarify("ambiguous_amount", "How many rooms (1 to 10)?") from None
    return ProviderInvalidatingChange(
        patch=BriefPatch(
            entries=[PatchEntry(question_id=QuestionId.STAY_PREFERENCES, payload=payload)]
        )
    )


def _rule_wallet(norm: str, context: RoutingContext) -> PostPlanAction | None:
    adopt = re.search(
        r"\b(use|adopt|refresh|update|sync|switch to)\b.*\b(my )?(current |latest |saved |new )?"
        r"(wallet|cards)\b",
        norm,
    )
    objective: Literal["lowest_cash", "highest_value", "convenience", "balanced"] | None = None
    if re.search(r"\b(optimi[sz]e|prioriti[sz]e|focus)\b.*\b(lowest cash|least cash|cash)\b", norm):
        objective = "lowest_cash"
    elif re.search(r"\b(optimi[sz]e|prioriti[sz]e|focus)\b.*\b(value|rewards)\b", norm):
        objective = "highest_value"
    elif re.search(
        r"\b(optimi[sz]e|prioriti[sz]e|focus)\b.*\b(convenience|simplicity|simple)\b", norm
    ):
        objective = "convenience"
    priority: Literal["save_points", "use_points", "best_value"] | None = None
    if re.search(r"\bsave (my )?points\b", norm):
        priority = "save_points"
    elif re.search(r"\buse (my )?points\b", norm) and adopt is None:
        priority = "use_points"
    if adopt is None and objective is None and priority is None:
        return None
    if (objective or priority) and context.brief.budget_and_objective is None:
        raise _clarify(
            "needs_detail",
            "Your plan has no budget and objective yet. What budget and style should I assume?",
        )
    return WalletOrObjectiveChange(
        adopt_current_wallet=adopt is not None, objective=objective, points_priority=priority
    )


def _rule_explanation(norm: str, context: RoutingContext) -> PostPlanAction | None:
    asks = re.search(
        r"^(why|how|explain|which card|what card|how much)\b|\bwhy (did|was|is|are|were)\b", norm
    )
    if asks is None or not context.explainable:
        return None
    labelled = [
        (ref.ref_id, -1, RoutingItem(poi_id=ref.ref_id, name=ref.label))
        for ref in context.explainable
    ]
    matches = _find_names(norm, labelled)
    if len(matches) != 1:
        if matches:
            raise _clarify("ambiguous_item", "Which one should I explain?")
        return None
    ref = next(r for r in context.explainable if r.ref_id == matches[0][0])
    if re.search(r"\b(which card|what card|pay with|payment)\b", norm):
        topic: ExplanationTopic = "payment_card"
    elif re.search(r"\b(how much|priced|price|cost|why is .* expensive)\b", norm):
        topic = "how_priced"
    elif re.search(r"\b(fresh|current|up to date|expire|stale)\b", norm):
        topic = "freshness"
    else:
        topic = "why_chosen"
    return ExplanationRequest(target_kind=ref.kind, target_id=ref.ref_id, topic=topic)


def _rule_profile(norm: str, context: RoutingContext) -> PostPlanAction | None:
    if not re.search(r"\b(remember|save|always|from now on|going forward|in future)\b", norm):
        return None
    if re.search(r"\b(window|aisle) seat\b", norm):
        seat = "window" if "window" in norm else "aisle"
        flight = _flight_payload(context.brief).model_copy(update={"seat": seat})
        return ProfileUpdateAction(section="flight", candidate=flight)
    if re.search(r"\b(relaxed|slower|laid back)\b", norm):
        rhythm = _current_rhythm(context.brief).model_copy(update={"pace": "relaxed"})
        return ProfileUpdateAction(section="rhythm", candidate=rhythm)
    return None


def _rule_unsupported(norm: str, context: RoutingContext) -> PostPlanAction | None:
    if re.search(
        r"\b(wheelchair|step[- ]free|accessible|accessibility|mobility)\b.*"
        r"\b(guarantee|ensure|make sure|only)\b"
        r"|\b(guarantee|ensure|make sure)\b.*\b(wheelchair|step[- ]free|accessible)\b",
        norm,
    ):
        raise _clarify(
            "unsupported",
            "I can note an accessibility need, but I can't verify that every venue is "
            "step-free, so I won't promise it. Do you want it recorded as a preference?",
        )
    return None


_Rule = Callable[[str, str, RoutingContext], "PostPlanAction | None"]

# Order matters: durable-preference and explanation phrasing is recognised before the
# edit verbs they share words with; quantity/date rules precede the generic edits.
_RULES: tuple[_Rule, ...] = (
    lambda norm, orig, ctx: _rule_profile(norm, ctx),
    lambda norm, orig, ctx: _rule_explanation(norm, ctx),
    lambda norm, orig, ctx: _rule_reorder(norm, ctx),
    lambda norm, orig, ctx: _rule_replace(norm, ctx),
    lambda norm, orig, ctx: _rule_move(norm, ctx),
    lambda norm, orig, ctx: _rule_theme(norm, ctx),
    lambda norm, orig, ctx: _rule_interests(norm, ctx),
    lambda norm, orig, ctx: _rule_wallet(norm, ctx),
    _rule_dates,
    _rule_destination,
    lambda norm, orig, ctx: _rule_travelers(norm, ctx),
    lambda norm, orig, ctx: _rule_cabin(norm, ctx),
    lambda norm, orig, ctx: _rule_rooms(norm, ctx),
    lambda norm, orig, ctx: _rule_pace(norm, ctx),
    lambda norm, orig, ctx: _rule_remove(norm, ctx),
    lambda norm, orig, ctx: _rule_add(norm, ctx),
    lambda norm, orig, ctx: _rule_unsupported(norm, ctx),
)


def classify_command(text: str, context: RoutingContext) -> PostPlanAction | None:
    """Resolve ``text`` to a typed action, ask a focused question, or return ``None``.

    ``None`` means "not recognised deterministically" — the caller may then use at most
    one semantic interpretation. Whenever the text is recognised but cannot be resolved
    exactly against ``context`` the result is a ``ClarificationRequired``, never a guess.
    """
    original = _prepare(text)
    norm = _norm(original)
    try:
        for rule in _RULES:
            result = rule(norm, original, context)
            if result is not None:
                return result
    except _Clarify as clarification:
        return clarification.action
    return None
