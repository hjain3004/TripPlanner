"""The deterministic 8-12-decision conversational interview policy (CP1).

Every function here is a pure, referentially transparent transformation:
``PlanningSession`` (plus whatever the caller injects — an answer, a bounded
assistant-suggestion result, or the current wall clock) in, a *new*
validated ``PlanningSession`` out. Nothing here calls ``datetime.now()``,
``uuid4()``, a random API, an LLM, or the network — ``now`` is always a
parameter, and ``record_assistant_suggestions`` only ever *applies*
deterministic catalog rules to an already-computed assistance result; it
performs no LLM operation itself.

The interview is always exactly the 8 locked-order core questions in
``question_catalog.CORE_QUESTION_ORDER``, followed by zero to
``MAX_ADAPTIVE_DECISIONS`` applicable adaptive questions — never fewer than
``MIN_DECISIONS`` total, never more than ``MAX_DECISIONS``. After the 8th
core answer the session moves to ``awaiting_assistant`` rather than directly
to ``reviewing``: this is a deliberate seam for a future milestone (CP3) to
plug in the real bounded assistant call, and ``record_assistant_suggestions``
is the only function that can move a session out of that state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict

from accounts.models import TravelPreferenceProfile
from core.models import UserWallet
from planning.answers import (
    BudgetObjectivePayload,
    ExperiencesFoodPayload,
    FlightPreferencesPayload,
    HardConstraintsPayload,
    InterviewAnswer,
    PurposePartyPayload,
    QuestionId,
    StayPreferencesPayload,
    TripEssentialsPayload,
)
from planning.contracts import (
    AssistanceStatus,
    PlanningSession,
    PlanningSessionStatus,
    TravelerHomeContext,
)
from planning.question_catalog import (
    ADAPTIVE_QUESTION_IDS,
    CORE_QUESTION_ORDER,
    DEFAULT_QUESTION_CATALOG,
    QuestionDefinition,
)

MIN_DECISIONS = 8
MAX_DECISIONS = 12
MAX_ADAPTIVE_DECISIONS = 4
SESSION_RETENTION = timedelta(days=30)


class PlanningPolicyError(ValueError):
    """Base error for deterministic interview-policy violations."""


class StaleSessionVersionError(PlanningPolicyError):
    """The supplied session version is no longer current."""


class UnexpectedQuestionError(PlanningPolicyError):
    """The answer does not belong to the question currently being asked."""


class DelegationNotAllowedError(PlanningPolicyError):
    """A required question cannot be delegated to the planner."""


class InvalidAssistantSuggestionError(PlanningPolicyError):
    """An assistant suggestion is unknown, inapplicable, repeated, or already answered."""


class InterviewProgress(BaseModel):
    """A caller-facing progress summary: completed decisions and an honest range.

    ``minimum_total``/``maximum_total`` deliberately describe a *range*, not a
    single predicted number, until the session reaches ``reviewing`` (or
    later) — before then the exact adaptive count is not yet knowable (or, if
    the assistant has already run, is knowable but is still reported as a
    range rather than as a false promise that no further adaptive question
    could ever be added by a future milestone).
    """

    model_config = ConfigDict(extra="forbid")
    completed: int
    minimum_total: int
    maximum_total: int
    status: PlanningSessionStatus


_CATALOG_BY_ID: dict[QuestionId, QuestionDefinition] = {
    definition.id: definition for definition in DEFAULT_QUESTION_CATALOG
}

_ADAPTIVE_BY_PRIORITY: tuple[QuestionId, ...] = tuple(
    definition.id
    for definition in sorted(
        (d for d in DEFAULT_QUESTION_CATALOG if d.phase == "adaptive"),
        key=lambda d: d.priority,
    )
)

_FINISHED_STATUSES: frozenset[PlanningSessionStatus] = frozenset(
    {
        PlanningSessionStatus.REVIEWING,
        PlanningSessionStatus.CONFIRMED,
        PlanningSessionStatus.PLANNING,
        PlanningSessionStatus.COMPLETE,
    }
)

T = TypeVar("T", bound=BaseModel)


def _definition(question_id: QuestionId) -> QuestionDefinition:
    return _CATALOG_BY_ID[question_id]


def _payload(session: PlanningSession, question_id: QuestionId, payload_type: type[T]) -> T | None:
    answer = session.answers.get(question_id)
    if answer is None:
        return None
    payload = answer.payload
    if isinstance(payload, payload_type):
        return payload
    return None


def _adaptive_applicable(question_id: QuestionId, session: PlanningSession) -> bool:
    purpose = _payload(session, QuestionId.PURPOSE_AND_PARTY, PurposePartyPayload)
    budget = _payload(session, QuestionId.BUDGET_AND_OBJECTIVE, BudgetObjectivePayload)
    flight = _payload(session, QuestionId.FLIGHT_PREFERENCES, FlightPreferencesPayload)
    stay = _payload(session, QuestionId.STAY_PREFERENCES, StayPreferencesPayload)
    food = _payload(session, QuestionId.EXPERIENCES_AND_FOOD, ExperiencesFoodPayload)
    constraints = _payload(session, QuestionId.HARD_CONSTRAINTS, HardConstraintsPayload)

    if question_id is QuestionId.CELEBRATION_DETAILS:
        return purpose is not None and purpose.purpose == "celebration"
    if question_id is QuestionId.CHILDREN_NEEDS:
        return purpose is not None and bool(purpose.children_ages)
    if question_id is QuestionId.MOBILITY_DETAILS:
        return constraints is not None and bool(constraints.accessibility)
    if question_id is QuestionId.POINTS_STRATEGY:
        has_points = any(session.wallet.points_balances.values())
        return budget is not None and has_points and budget.points_priority != "save_points"
    if question_id is QuestionId.FLIGHT_TRADEOFF:
        return flight is not None and flight.max_stops is None
    if question_id is QuestionId.HOTEL_TRADEOFF:
        return stay is not None and stay.location_price_tradeoff == "balanced"
    if question_id is QuestionId.FOOD_DEPTH:
        return food is not None and bool(food.food_interests)
    return False


def _bump(session: PlanningSession, now: datetime, **changes: object) -> PlanningSession:
    """Apply ``changes`` on top of ``session``, bump ``version``/``updated_at``,
    and round-trip the result through full Pydantic validation.

    ``model_copy(update=...)`` alone does not re-run validators, so every
    caller of this helper gets the session's own invariants (no duplicate
    processed/suggested ids, timezone-aware timestamps, ordered timestamps,
    ...) re-checked on every mutation rather than trusting unchecked output.
    """
    candidate = session.model_copy(
        update={**changes, "version": session.version + 1, "updated_at": now}
    )
    return PlanningSession.model_validate(candidate.model_dump())


def start_interview(
    *,
    user_id: str,
    session_id: str,
    home: TravelerHomeContext,
    wallet: UserWallet,
    profile_defaults: TravelPreferenceProfile | None,
    now: datetime,
    expires_at: datetime,
) -> PlanningSession:
    """Start a brand-new interview.

    The first question is always ``trip_essentials`` regardless of any
    durable ``profile_defaults`` the traveler already has on file — required
    facts are always asked fresh, never silently pre-filled.
    """
    return PlanningSession(
        id=session_id,
        user_id=user_id,
        status=PlanningSessionStatus.INTERVIEWING,
        version=0,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        home=home,
        wallet=wallet,
        profile_defaults=profile_defaults,
        current_question_id=QuestionId.TRIP_ESSENTIALS,
    )


def next_question(session: PlanningSession) -> QuestionDefinition | None:
    """The question currently being asked, or ``None`` if none is pending.

    ``None`` covers both "the interview just finished" (``reviewing`` and
    beyond) and the deliberate ``awaiting_assistant`` seam, where no question
    is asked until ``record_assistant_suggestions`` resumes the interview.
    """
    if session.current_question_id is None:
        return None
    return _definition(session.current_question_id)


def _validate_traveler_consistency(answers: dict[QuestionId, InterviewAnswer]) -> None:
    essentials_answer = answers.get(QuestionId.TRIP_ESSENTIALS)
    purpose_answer = answers.get(QuestionId.PURPOSE_AND_PARTY)
    if essentials_answer is None or purpose_answer is None:
        return
    essentials = essentials_answer.payload
    purpose = purpose_answer.payload
    if not isinstance(essentials, TripEssentialsPayload) or not isinstance(
        purpose, PurposePartyPayload
    ):
        # One or both are delegated (payload is None) -- nothing to cross-check yet.
        return
    if purpose.adults + len(purpose.children_ages) != essentials.travelers:
        raise PlanningPolicyError(
            "purpose_and_party adults + children_ages must equal "
            "trip_essentials travelers once both are answered"
        )


def _advance_after_answer(
    session: PlanningSession,
    new_answers: dict[QuestionId, InterviewAnswer],
    answered_id: QuestionId,
) -> tuple[QuestionId | None, PlanningSessionStatus, list[QuestionId]]:
    """Selection-algorithm steps 1-2 (core) and the adaptive-queue resumption
    that mirrors steps 4-5, applied to the single answer just recorded.
    """
    if answered_id in CORE_QUESTION_ORDER:
        for candidate in CORE_QUESTION_ORDER:
            if candidate not in new_answers:
                return candidate, PlanningSessionStatus.INTERVIEWING, session.suggested_question_ids
        # The eighth and final core answer was just recorded: this is the
        # mandatory CP3 semantic-review seam. Do not silently skip across it.
        return None, PlanningSessionStatus.AWAITING_ASSISTANT, session.suggested_question_ids

    remaining = [qid for qid in session.suggested_question_ids if qid != answered_id]
    if remaining:
        return remaining[0], PlanningSessionStatus.INTERVIEWING, remaining
    return None, PlanningSessionStatus.REVIEWING, remaining


def record_answer(
    session: PlanningSession,
    answer: InterviewAnswer,
    *,
    expected_version: int,
    now: datetime,
) -> PlanningSession:
    """Record one answer to the current question.

    Idempotent on ``answer.client_event_id``: a replayed event returns the
    identical session, unchanged, before the version check even runs (a
    genuine retry legitimately carries the ``expected_version`` that was
    valid *before* the first successful attempt, which is now stale by
    definition -- idempotency must win that race).
    """
    if answer.client_event_id in session.processed_event_ids:
        return session
    if expected_version != session.version:
        raise StaleSessionVersionError(
            f"expected_version={expected_version} does not match "
            f"session.version={session.version}"
        )
    if (
        session.status != PlanningSessionStatus.INTERVIEWING
        or answer.question_id != session.current_question_id
    ):
        raise UnexpectedQuestionError(
            f"{answer.question_id.value} is not the question currently being asked"
        )

    definition = _definition(answer.question_id)
    if answer.delegated and not definition.allow_delegate:
        raise DelegationNotAllowedError(
            f"{answer.question_id.value} is a required fact and cannot be delegated"
        )

    new_answers = dict(session.answers)
    new_answers[answer.question_id] = answer
    _validate_traveler_consistency(new_answers)

    next_id, next_status, next_suggested = _advance_after_answer(
        session, new_answers, answer.question_id
    )
    return _bump(
        session,
        now,
        answers=new_answers,
        processed_event_ids=[*session.processed_event_ids, answer.client_event_id],
        current_question_id=next_id,
        status=next_status,
        suggested_question_ids=next_suggested,
    )


def record_assistant_suggestions(
    session: PlanningSession,
    question_ids: list[QuestionId],
    *,
    assistance_status: Literal["complete", "degraded"],
    llm_calls: int,
    expected_version: int,
    now: datetime,
) -> PlanningSession:
    """Apply an already-computed bounded assistant result to an
    ``awaiting_assistant`` session.

    This performs no LLM operation itself -- it only accepts
    ``question_ids`` (the assistant's suggested adaptive questions),
    validates each one deterministically against the catalog, and appends
    any other deterministically applicable adaptive question by catalog
    priority. Assistant suggestions affect *order* only; they can never make
    an inapplicable question applicable.
    """
    if expected_version != session.version:
        raise StaleSessionVersionError(
            f"expected_version={expected_version} does not match "
            f"session.version={session.version}"
        )
    if session.status != PlanningSessionStatus.AWAITING_ASSISTANT:
        raise PlanningPolicyError(
            "record_assistant_suggestions is only valid while awaiting_assistant "
            f"(session is {session.status.value})"
        )
    if not 0 <= llm_calls <= 2:
        # Keeps this module's own error taxonomy as the rejection boundary
        # for out-of-range input. `PlanningSession.interview_llm_calls` also
        # carries `Field(..., ge=0, le=2)` and the mandated `_bump` round-trip
        # below re-validates it as a backstop -- this pre-check just ensures a
        # caller catching `PlanningPolicyError` never sees a raw
        # `pydantic.ValidationError` escape instead.
        raise PlanningPolicyError(
            f"llm_calls={llm_calls} must respect the 0-2 call ceiling"
        )
    if assistance_status == "complete" and llm_calls < 1:
        raise PlanningPolicyError(
            "a complete assistance result requires at least one llm_call"
        )

    seen: set[QuestionId] = set()
    approved: list[QuestionId] = []
    for question_id in question_ids:
        if question_id not in ADAPTIVE_QUESTION_IDS:
            raise InvalidAssistantSuggestionError(
                f"{question_id.value} is not an approved adaptive catalog question"
            )
        if question_id in seen:
            raise InvalidAssistantSuggestionError(
                f"{question_id.value} was suggested more than once"
            )
        seen.add(question_id)
        # Defense-in-depth: through the public API, `awaiting_assistant` is
        # only ever entered with exactly the 8 core answers present
        # (`_advance_after_answer`'s core branch), so no adaptive id can
        # already be in `session.answers` here in normal flow. Kept anyway in
        # case a future caller hand-constructs or replays a tampered session;
        # exercised directly by
        # `test_assistant_suggestions_reject_an_already_answered_question_id`.
        if question_id in session.answers:
            raise InvalidAssistantSuggestionError(
                f"{question_id.value} has already been answered"
            )
        if not _adaptive_applicable(question_id, session):
            raise InvalidAssistantSuggestionError(
                f"{question_id.value} is not applicable to this session"
            )
        approved.append(question_id)

    auto_filled = [
        question_id
        for question_id in _ADAPTIVE_BY_PRIORITY
        if question_id not in approved
        and question_id not in session.answers
        and _adaptive_applicable(question_id, session)
    ]
    queue = approved + auto_filled

    total_answered = len(session.answers)
    budget = min(MAX_ADAPTIVE_DECISIONS, MAX_DECISIONS - total_answered)
    queue = queue[: max(budget, 0)]

    next_status = (
        PlanningSessionStatus.INTERVIEWING if queue else PlanningSessionStatus.REVIEWING
    )
    next_current = queue[0] if queue else None

    return _bump(
        session,
        now,
        assistance_status=AssistanceStatus(assistance_status),
        interview_llm_calls=llm_calls,
        suggested_question_ids=queue,
        current_question_id=next_current,
        status=next_status,
    )


def interview_progress(session: PlanningSession) -> InterviewProgress:
    """Completed decisions plus an honest (never over-claimed) total range."""
    completed = len(session.answers)
    if session.status in _FINISHED_STATUSES:
        minimum_total = completed
        maximum_total = completed
    else:
        minimum_total = max(MIN_DECISIONS, completed)
        maximum_total = MAX_DECISIONS
    return InterviewProgress(
        completed=completed,
        minimum_total=minimum_total,
        maximum_total=maximum_total,
        status=session.status,
    )
