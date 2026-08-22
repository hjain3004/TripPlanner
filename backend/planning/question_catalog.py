"""The approved CP1 interview question catalog.

Fifteen questions, fixed by design (see
``docs/superpowers/plans/2026-08-21-cp1-conversational-domain.md``):

- 8 **core** questions, asked on every trip, in ``CORE_QUESTION_ORDER``,
  priorities 10-80.
- 7 **adaptive** questions in ``ADAPTIVE_QUESTION_IDS``, priorities 110-170,
  asked only when the orchestrator (a later task) decides they apply. A
  normal interview surfaces zero to four of them, for a total of 8-12
  decisions.

Only ``trip_essentials`` and ``hard_constraints`` disallow delegation
(``allow_delegate=False``): the trip's basic shape and the traveler's
explicit hard-constraint acknowledgement are required facts that cannot be
silently defaulted on the traveler's behalf. Every other question may be
delegated to the system's best judgment.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from planning.answers import QuestionId


class QuestionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: QuestionId
    phase: Literal["core", "adaptive"]
    prompt: str = Field(min_length=1)
    answer_kind: Literal[
        "trip_essentials",
        "purpose_party",
        "budget_objective",
        "flight",
        "stay",
        "rhythm",
        "experiences_food",
        "hard_constraints",
        "adaptive_detail",
    ]
    required: bool
    allow_delegate: bool
    priority: int = Field(ge=1)
    impact_domains: list[
        Literal["flight", "hotel", "award", "itinerary", "cost", "rewards", "profile"]
    ]
    profile_sections: list[
        Literal["flight", "stay", "rhythm", "experiences", "constraints", "optimization"]
    ] = Field(default_factory=list)


CORE_QUESTION_ORDER: tuple[QuestionId, ...] = (
    QuestionId.TRIP_ESSENTIALS,
    QuestionId.PURPOSE_AND_PARTY,
    QuestionId.BUDGET_AND_OBJECTIVE,
    QuestionId.FLIGHT_PREFERENCES,
    QuestionId.STAY_PREFERENCES,
    QuestionId.DAILY_RHYTHM,
    QuestionId.EXPERIENCES_AND_FOOD,
    QuestionId.HARD_CONSTRAINTS,
)

ADAPTIVE_QUESTION_IDS: frozenset[QuestionId] = frozenset(
    {
        QuestionId.CELEBRATION_DETAILS,
        QuestionId.CHILDREN_NEEDS,
        QuestionId.MOBILITY_DETAILS,
        QuestionId.POINTS_STRATEGY,
        QuestionId.FLIGHT_TRADEOFF,
        QuestionId.HOTEL_TRADEOFF,
        QuestionId.FOOD_DEPTH,
    }
)

DEFAULT_QUESTION_CATALOG: tuple[QuestionDefinition, ...] = (
    QuestionDefinition(
        id=QuestionId.TRIP_ESSENTIALS,
        phase="core",
        prompt="Where are you headed, and what are your travel dates?",
        answer_kind="trip_essentials",
        required=True,
        allow_delegate=False,
        priority=10,
        impact_domains=["flight", "hotel", "award", "itinerary", "cost", "rewards"],
        profile_sections=[],
    ),
    QuestionDefinition(
        id=QuestionId.PURPOSE_AND_PARTY,
        phase="core",
        prompt="What's the occasion for this trip, and who's traveling with you?",
        answer_kind="purpose_party",
        required=True,
        allow_delegate=True,
        priority=20,
        impact_domains=["hotel", "itinerary"],
        profile_sections=[],
    ),
    QuestionDefinition(
        id=QuestionId.BUDGET_AND_OBJECTIVE,
        phase="core",
        prompt=(
            "What's your budget for this trip, and what matters most — "
            "saving cash, maximizing value, or convenience?"
        ),
        answer_kind="budget_objective",
        required=True,
        allow_delegate=True,
        priority=30,
        impact_domains=["flight", "hotel", "award", "cost", "rewards"],
        profile_sections=["optimization"],
    ),
    QuestionDefinition(
        id=QuestionId.FLIGHT_PREFERENCES,
        phase="core",
        prompt=(
            "Any preferences for your flights — cabin class, number of "
            "stops, or time of day?"
        ),
        answer_kind="flight",
        required=True,
        allow_delegate=True,
        priority=40,
        impact_domains=["flight", "award", "cost"],
        profile_sections=["flight"],
    ),
    QuestionDefinition(
        id=QuestionId.STAY_PREFERENCES,
        phase="core",
        prompt="What kind of place do you want to stay, and where — central or better value?",
        answer_kind="stay",
        required=True,
        allow_delegate=True,
        priority=50,
        impact_domains=["hotel", "itinerary", "cost"],
        profile_sections=["stay"],
    ),
    QuestionDefinition(
        id=QuestionId.DAILY_RHYTHM,
        phase="core",
        prompt="How do you like your days paced — relaxed, moderate, or packed?",
        answer_kind="rhythm",
        required=True,
        allow_delegate=True,
        priority=60,
        impact_domains=["itinerary"],
        profile_sections=["rhythm"],
    ),
    QuestionDefinition(
        id=QuestionId.EXPERIENCES_AND_FOOD,
        phase="core",
        prompt="What experiences and food are you most excited about on this trip?",
        answer_kind="experiences_food",
        required=True,
        allow_delegate=True,
        priority=70,
        impact_domains=["itinerary", "cost"],
        profile_sections=["experiences"],
    ),
    QuestionDefinition(
        id=QuestionId.HARD_CONSTRAINTS,
        phase="core",
        prompt=(
            "Are there any hard constraints we must plan around — dietary "
            "needs, accessibility requirements, or fixed events?"
        ),
        answer_kind="hard_constraints",
        required=True,
        allow_delegate=False,
        priority=80,
        impact_domains=["flight", "hotel", "itinerary"],
        profile_sections=["constraints"],
    ),
    QuestionDefinition(
        id=QuestionId.CELEBRATION_DETAILS,
        phase="adaptive",
        prompt="Tell us more about the celebration — what would make it memorable?",
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=110,
        impact_domains=["hotel", "itinerary"],
        profile_sections=[],
    ),
    QuestionDefinition(
        id=QuestionId.CHILDREN_NEEDS,
        phase="adaptive",
        prompt="What should we know about traveling with children on this trip?",
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=120,
        impact_domains=["flight", "hotel", "itinerary"],
        profile_sections=[],
    ),
    QuestionDefinition(
        id=QuestionId.MOBILITY_DETAILS,
        phase="adaptive",
        prompt="Tell us about any mobility needs so we can plan accessible routes and stays.",
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=130,
        impact_domains=["flight", "hotel", "itinerary"],
        profile_sections=["constraints"],
    ),
    QuestionDefinition(
        id=QuestionId.POINTS_STRATEGY,
        phase="adaptive",
        prompt="Do you have a points or miles strategy you'd like us to follow?",
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=140,
        impact_domains=["award", "rewards"],
        profile_sections=["optimization"],
    ),
    QuestionDefinition(
        id=QuestionId.FLIGHT_TRADEOFF,
        phase="adaptive",
        prompt=(
            "If we have to trade off price against convenience on flights, "
            "which way should we lean?"
        ),
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=150,
        impact_domains=["flight", "award", "cost"],
        profile_sections=["flight"],
    ),
    QuestionDefinition(
        id=QuestionId.HOTEL_TRADEOFF,
        phase="adaptive",
        prompt=(
            "If we have to trade off location against price on your hotel, "
            "which way should we lean?"
        ),
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=160,
        impact_domains=["hotel", "itinerary", "cost"],
        profile_sections=["stay"],
    ),
    QuestionDefinition(
        id=QuestionId.FOOD_DEPTH,
        phase="adaptive",
        prompt=(
            "How deep do you want to go on food — must-try local spots, "
            "iconic restaurants, or both?"
        ),
        answer_kind="adaptive_detail",
        required=False,
        allow_delegate=True,
        priority=170,
        impact_domains=["itinerary", "cost"],
        profile_sections=["experiences"],
    ),
)
