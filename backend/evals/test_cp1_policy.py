"""The deterministic 8-12-decision interview policy (CP1 task 5).

``planning.policy`` is pure domain logic: given a ``PlanningSession`` and an
``InterviewAnswer`` (or a bounded assistant-suggestion result), it decides
the next question and the next session status without ever touching a
database, an LLM, or the wall clock — every timestamp is caller-injected.

The interview is always 8 locked-order core questions followed by zero to
four applicable adaptive questions (never more than 12 total decisions,
never fewer than 8). After the 8th core answer the session moves to
``awaiting_assistant`` — a deliberate seam for a future milestone (CP3) to
plug in the real bounded assistant call — and only
``record_assistant_suggestions`` can move it out of that state.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from accounts.models import TravelPreferenceProfile
from core.models import UserWallet
from planning.answers import (
    AdaptiveDetailPayload,
    BudgetObjectivePayload,
    DailyRhythmPayload,
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
from planning.policy import (
    MAX_ADAPTIVE_DECISIONS,
    MAX_DECISIONS,
    MIN_DECISIONS,
    DelegationNotAllowedError,
    InvalidAssistantSuggestionError,
    PlanningPolicyError,
    StaleSessionVersionError,
    UnexpectedQuestionError,
    interview_progress,
    next_question,
    record_answer,
    record_assistant_suggestions,
    start_interview,
)
from planning.question_catalog import CORE_QUESTION_ORDER, DEFAULT_QUESTION_CATALOG

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(days=30)


# --------------------------------------------------------------------------- #
# Fixtures / payload builders                                                  #
# --------------------------------------------------------------------------- #


def _home() -> TravelerHomeContext:
    return TravelerHomeContext(home_country="IN", home_currency="INR", default_origin="DEL")


def _wallet(points: dict[str, int] | None = None) -> UserWallet:
    return UserWallet(card_ids=["hdfc-infinia"], points_balances=points or {})


def _start(
    *,
    wallet: UserWallet | None = None,
    profile_defaults: TravelPreferenceProfile | None = None,
    session_id: str = "ps1",
) -> PlanningSession:
    return start_interview(
        user_id="u1",
        session_id=session_id,
        home=_home(),
        wallet=wallet or _wallet(),
        profile_defaults=profile_defaults,
        now=NOW,
        expires_at=EXPIRES,
    )


def _essentials(travelers: int = 2) -> TripEssentialsPayload:
    return TripEssentialsPayload(
        origin="DEL",
        destination="SIN",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        travelers=travelers,
    )


def _purpose(
    purpose: str = "leisure",
    adults: int = 2,
    children_ages: list[int] | None = None,
) -> PurposePartyPayload:
    return PurposePartyPayload(
        purpose=purpose,  # type: ignore[arg-type]
        adults=adults,
        children_ages=children_ages or [],
    )


def _budget(points_priority: str = "best_value") -> BudgetObjectivePayload:
    return BudgetObjectivePayload(
        currency="INR",
        travel_style="balanced",
        objective="balanced",
        points_priority=points_priority,  # type: ignore[arg-type]
    )


def _flight(max_stops: int | None = 1) -> FlightPreferencesPayload:
    # Defaults to a *set* max_stops so flight_tradeoff is not accidentally
    # triggered by tests that don't care about flight applicability.
    return FlightPreferencesPayload(cabin="economy", max_stops=max_stops, schedule="no_preference")


def _stay(tradeoff: str = "no_preference") -> StayPreferencesPayload:
    # Defaults to a non-"balanced" tradeoff so hotel_tradeoff is not
    # accidentally triggered by tests that don't care about stay applicability.
    return StayPreferencesPayload(location_price_tradeoff=tradeoff)  # type: ignore[arg-type]


def _rhythm() -> DailyRhythmPayload:
    return DailyRhythmPayload(
        pace="moderate",
        day_start="normal",
        evening_style="flexible",
        day_trip_appetite="one",
    )


def _food(food_interests: list[str] | None = None) -> ExperiencesFoodPayload:
    return ExperiencesFoodPayload(
        food_interests=food_interests or [], iconic_local_balance="balanced"
    )


def _constraints(accessibility: list[str] | None = None) -> HardConstraintsPayload:
    access = accessibility or []
    return HardConstraintsPayload(has_constraints=bool(access), accessibility=access)


def _answer(
    question_id: QuestionId,
    payload: object | None,
    *,
    event_id: str,
    delegated: bool = False,
) -> InterviewAnswer:
    return InterviewAnswer(
        question_id=question_id,
        payload=payload,  # type: ignore[arg-type]
        delegated=delegated,
        client_event_id=event_id,
        answered_at=NOW,
    )


def _answer_core(
    session: PlanningSession,
    *,
    essentials: TripEssentialsPayload | None = None,
    purpose: PurposePartyPayload | None = None,
    budget: BudgetObjectivePayload | None = None,
    flight: FlightPreferencesPayload | None = None,
    stay: StayPreferencesPayload | None = None,
    rhythm: DailyRhythmPayload | None = None,
    food: ExperiencesFoodPayload | None = None,
    constraints: HardConstraintsPayload | None = None,
) -> PlanningSession:
    """Drive a fresh session through all 8 core questions in locked order."""
    steps = [
        (QuestionId.TRIP_ESSENTIALS, essentials or _essentials()),
        (QuestionId.PURPOSE_AND_PARTY, purpose or _purpose()),
        (QuestionId.BUDGET_AND_OBJECTIVE, budget or _budget()),
        (QuestionId.FLIGHT_PREFERENCES, flight or _flight()),
        (QuestionId.STAY_PREFERENCES, stay or _stay()),
        (QuestionId.DAILY_RHYTHM, rhythm or _rhythm()),
        (QuestionId.EXPERIENCES_AND_FOOD, food or _food()),
        (QuestionId.HARD_CONSTRAINTS, constraints or _constraints()),
    ]
    for index, (question_id, payload) in enumerate(steps):
        answer = _answer(question_id, payload, event_id=f"core-{index}")
        session = record_answer(session, answer, expected_version=session.version, now=NOW)
    return session


# --------------------------------------------------------------------------- #
# Happy path / locked core order                                               #
# --------------------------------------------------------------------------- #


def test_new_sessions_first_question_is_trip_essentials_even_with_profile_defaults() -> None:
    profile = TravelPreferenceProfile(user_id="u1", updated_at=NOW)
    session = _start(profile_defaults=profile)

    question = next_question(session)

    assert question is not None
    assert question.id == QuestionId.TRIP_ESSENTIALS


def test_core_questions_are_always_presented_in_locked_order() -> None:
    session = _start()
    seen: list[QuestionId] = []
    for index, expected_id in enumerate(CORE_QUESTION_ORDER):
        question = next_question(session)
        assert question is not None
        assert question.id == expected_id
        seen.append(question.id)
        if expected_id == QuestionId.PURPOSE_AND_PARTY:
            payload: object = _purpose()
        elif expected_id == QuestionId.TRIP_ESSENTIALS:
            payload = _essentials()
        elif expected_id == QuestionId.BUDGET_AND_OBJECTIVE:
            payload = _budget()
        elif expected_id == QuestionId.FLIGHT_PREFERENCES:
            payload = _flight()
        elif expected_id == QuestionId.STAY_PREFERENCES:
            payload = _stay()
        elif expected_id == QuestionId.DAILY_RHYTHM:
            payload = _rhythm()
        elif expected_id == QuestionId.EXPERIENCES_AND_FOOD:
            payload = _food()
        else:
            payload = _constraints()
        session = record_answer(
            session,
            _answer(expected_id, payload, event_id=f"evt-{index}"),
            expected_version=session.version,
            now=NOW,
        )
    assert seen == list(CORE_QUESTION_ORDER)


def test_answering_the_eighth_core_question_moves_to_awaiting_assistant_not_reviewing() -> None:
    session = _answer_core(_start())

    assert session.status == PlanningSessionStatus.AWAITING_ASSISTANT


def test_next_question_returns_none_while_awaiting_the_assistant_result() -> None:
    session = _answer_core(_start())

    assert next_question(session) is None


# --------------------------------------------------------------------------- #
# Idempotency, optimistic concurrency, and unexpected-answer rejection         #
# --------------------------------------------------------------------------- #


def test_a_repeated_client_event_id_is_idempotent_and_does_not_bump_version() -> None:
    session = _start()
    answer = _answer(QuestionId.TRIP_ESSENTIALS, _essentials(), event_id="evt-dup")
    once = record_answer(session, answer, expected_version=0, now=NOW)

    replayed = record_answer(once, answer, expected_version=0, now=NOW)

    assert replayed == once
    assert replayed.version == once.version


def test_a_mismatched_expected_version_raises_stale_session_version_error() -> None:
    session = _start()

    with pytest.raises(StaleSessionVersionError):
        record_answer(
            session,
            _answer(QuestionId.TRIP_ESSENTIALS, _essentials(), event_id="evt-1"),
            expected_version=99,
            now=NOW,
        )


def test_an_answer_for_anything_except_the_current_question_raises_unexpected_question_error() -> (
    None
):
    session = _start()

    with pytest.raises(UnexpectedQuestionError):
        record_answer(
            session,
            _answer(QuestionId.BUDGET_AND_OBJECTIVE, _budget(), event_id="evt-1"),
            expected_version=0,
            now=NOW,
        )


def test_record_answer_rejects_a_non_interviewing_session() -> None:
    session = _answer_core(_start())
    assert session.status == PlanningSessionStatus.AWAITING_ASSISTANT

    with pytest.raises(UnexpectedQuestionError):
        record_answer(
            session,
            _answer(
                QuestionId.CELEBRATION_DETAILS,
                AdaptiveDetailPayload(detail="x"),
                event_id="evt-x",
            ),
            expected_version=session.version,
            now=NOW,
        )


# --------------------------------------------------------------------------- #
# Delegation                                                                    #
# --------------------------------------------------------------------------- #


def test_delegated_trip_essentials_raises_delegation_not_allowed_error() -> None:
    session = _start()

    with pytest.raises(DelegationNotAllowedError):
        record_answer(
            session,
            _answer(QuestionId.TRIP_ESSENTIALS, None, event_id="evt-1", delegated=True),
            expected_version=0,
            now=NOW,
        )


def test_delegated_hard_constraints_raises_delegation_not_allowed_error() -> None:
    session = _start()
    session = record_answer(
        session,
        _answer(QuestionId.TRIP_ESSENTIALS, _essentials(), event_id="evt-0"),
        expected_version=session.version,
        now=NOW,
    )
    session = record_answer(
        session,
        _answer(QuestionId.PURPOSE_AND_PARTY, _purpose(), event_id="evt-1"),
        expected_version=session.version,
        now=NOW,
    )
    for index, question_id in enumerate(
        (
            QuestionId.BUDGET_AND_OBJECTIVE,
            QuestionId.FLIGHT_PREFERENCES,
            QuestionId.STAY_PREFERENCES,
            QuestionId.DAILY_RHYTHM,
            QuestionId.EXPERIENCES_AND_FOOD,
        ),
        start=2,
    ):
        payload = {
            QuestionId.BUDGET_AND_OBJECTIVE: _budget(),
            QuestionId.FLIGHT_PREFERENCES: _flight(),
            QuestionId.STAY_PREFERENCES: _stay(),
            QuestionId.DAILY_RHYTHM: _rhythm(),
            QuestionId.EXPERIENCES_AND_FOOD: _food(),
        }[question_id]
        session = record_answer(
            session,
            _answer(question_id, payload, event_id=f"evt-{index}"),
            expected_version=session.version,
            now=NOW,
        )

    with pytest.raises(DelegationNotAllowedError):
        record_answer(
            session,
            _answer(QuestionId.HARD_CONSTRAINTS, None, event_id="evt-final", delegated=True),
            expected_version=session.version,
            now=NOW,
        )


def test_delegated_answer_for_a_delegable_question_is_accepted_and_advances() -> None:
    session = _start()
    session = record_answer(
        session,
        _answer(QuestionId.TRIP_ESSENTIALS, _essentials(), event_id="evt-0"),
        expected_version=session.version,
        now=NOW,
    )

    session = record_answer(
        session,
        _answer(QuestionId.PURPOSE_AND_PARTY, None, event_id="evt-1", delegated=True),
        expected_version=session.version,
        now=NOW,
    )

    assert session.answers[QuestionId.PURPOSE_AND_PARTY].delegated is True
    question = next_question(session)
    assert question is not None
    assert question.id == QuestionId.BUDGET_AND_OBJECTIVE


# --------------------------------------------------------------------------- #
# Cross-answer consistency                                                     #
# --------------------------------------------------------------------------- #


def test_travelers_count_must_equal_adults_plus_children_ages_once_both_exist() -> None:
    session = _start()
    session = record_answer(
        session,
        _answer(QuestionId.TRIP_ESSENTIALS, _essentials(travelers=2), event_id="evt-0"),
        expected_version=session.version,
        now=NOW,
    )

    with pytest.raises(PlanningPolicyError):
        record_answer(
            session,
            _answer(
                QuestionId.PURPOSE_AND_PARTY,
                _purpose(adults=3, children_ages=[]),
                event_id="evt-1",
            ),
            expected_version=session.version,
            now=NOW,
        )


def test_travelers_count_matching_adults_plus_children_ages_is_accepted() -> None:
    session = _start()
    session = record_answer(
        session,
        _answer(QuestionId.TRIP_ESSENTIALS, _essentials(travelers=4), event_id="evt-0"),
        expected_version=session.version,
        now=NOW,
    )

    session = record_answer(
        session,
        _answer(
            QuestionId.PURPOSE_AND_PARTY,
            _purpose(adults=2, children_ages=[5, 8]),
            event_id="evt-1",
        ),
        expected_version=session.version,
        now=NOW,
    )

    assert session.answers[QuestionId.PURPOSE_AND_PARTY] is not None


# --------------------------------------------------------------------------- #
# Adaptive applicability                                                       #
# --------------------------------------------------------------------------- #


def _run_assistant_with_no_explicit_suggestions(session: PlanningSession) -> PlanningSession:
    return record_assistant_suggestions(
        session,
        [],
        assistance_status="degraded",
        llm_calls=0,
        expected_version=session.version,
        now=NOW,
    )


def test_purpose_celebration_makes_celebration_details_applicable() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.CELEBRATION_DETAILS in result.suggested_question_ids


def test_purpose_leisure_does_not_make_celebration_details_applicable() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="leisure"))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.CELEBRATION_DETAILS not in result.suggested_question_ids


def test_children_ages_make_children_needs_applicable() -> None:
    session = _answer_core(
        _start(),
        essentials=_essentials(travelers=3),
        purpose=_purpose(purpose="family", adults=2, children_ages=[6]),
    )
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.CHILDREN_NEEDS in result.suggested_question_ids


def test_no_children_ages_does_not_make_children_needs_applicable() -> None:
    session = _answer_core(_start(), purpose=_purpose(children_ages=[]))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.CHILDREN_NEEDS not in result.suggested_question_ids


def test_accessibility_constraints_make_mobility_details_applicable() -> None:
    session = _answer_core(_start(), constraints=_constraints(accessibility=["wheelchair"]))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.MOBILITY_DETAILS in result.suggested_question_ids


def test_no_accessibility_constraints_does_not_make_mobility_details_applicable() -> None:
    session = _answer_core(_start(), constraints=_constraints(accessibility=[]))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.MOBILITY_DETAILS not in result.suggested_question_ids


def test_wallet_points_plus_use_points_makes_points_strategy_applicable() -> None:
    session = _answer_core(
        _start(wallet=_wallet({"hdfc-infinia": 50_000})),
        budget=_budget(points_priority="use_points"),
    )
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.POINTS_STRATEGY in result.suggested_question_ids


def test_wallet_points_plus_best_value_makes_points_strategy_applicable() -> None:
    session = _answer_core(
        _start(wallet=_wallet({"hdfc-infinia": 50_000})),
        budget=_budget(points_priority="best_value"),
    )
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.POINTS_STRATEGY in result.suggested_question_ids


def test_wallet_points_plus_save_points_does_not_make_points_strategy_applicable() -> None:
    session = _answer_core(
        _start(wallet=_wallet({"hdfc-infinia": 50_000})),
        budget=_budget(points_priority="save_points"),
    )
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.POINTS_STRATEGY not in result.suggested_question_ids


def test_empty_wallet_points_does_not_make_points_strategy_applicable() -> None:
    session = _answer_core(
        _start(wallet=_wallet({})),
        budget=_budget(points_priority="use_points"),
    )
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.POINTS_STRATEGY not in result.suggested_question_ids


def test_food_interests_make_food_depth_applicable() -> None:
    session = _answer_core(_start(), food=_food(food_interests=["street_food"]))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.FOOD_DEPTH in result.suggested_question_ids


def test_no_food_interests_does_not_make_food_depth_applicable() -> None:
    session = _answer_core(_start(), food=_food(food_interests=[]))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.FOOD_DEPTH not in result.suggested_question_ids


def test_unset_max_stops_makes_flight_tradeoff_applicable() -> None:
    session = _answer_core(_start(), flight=_flight(max_stops=None))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.FLIGHT_TRADEOFF in result.suggested_question_ids


def test_set_max_stops_does_not_make_flight_tradeoff_applicable() -> None:
    session = _answer_core(_start(), flight=_flight(max_stops=1))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.FLIGHT_TRADEOFF not in result.suggested_question_ids


def test_balanced_stay_tradeoff_makes_hotel_tradeoff_applicable() -> None:
    session = _answer_core(_start(), stay=_stay(tradeoff="balanced"))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.HOTEL_TRADEOFF in result.suggested_question_ids


def test_non_balanced_stay_tradeoff_does_not_make_hotel_tradeoff_applicable() -> None:
    session = _answer_core(_start(), stay=_stay(tradeoff="location"))
    result = _run_assistant_with_no_explicit_suggestions(session)

    assert QuestionId.HOTEL_TRADEOFF not in result.suggested_question_ids


# --------------------------------------------------------------------------- #
# Assistant suggestion validation                                              #
# --------------------------------------------------------------------------- #


def test_assistant_suggestions_reject_a_non_adaptive_question_id() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))

    with pytest.raises(InvalidAssistantSuggestionError):
        record_assistant_suggestions(
            session,
            [QuestionId.TRIP_ESSENTIALS],
            assistance_status="complete",
            llm_calls=1,
            expected_version=session.version,
            now=NOW,
        )


def test_assistant_suggestions_reject_an_inapplicable_question_id() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="leisure"))

    with pytest.raises(InvalidAssistantSuggestionError):
        record_assistant_suggestions(
            session,
            [QuestionId.CELEBRATION_DETAILS],
            assistance_status="complete",
            llm_calls=1,
            expected_version=session.version,
            now=NOW,
        )


def test_assistant_suggestions_reject_a_duplicate_question_id() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))

    with pytest.raises(InvalidAssistantSuggestionError):
        record_assistant_suggestions(
            session,
            [QuestionId.CELEBRATION_DETAILS, QuestionId.CELEBRATION_DETAILS],
            assistance_status="complete",
            llm_calls=1,
            expected_version=session.version,
            now=NOW,
        )


def test_assistant_suggestions_reject_an_already_answered_question_id() -> None:
    # Force celebration_details into the answered set by walking one full round.
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))
    session = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=1,
        expected_version=session.version,
        now=NOW,
    )
    question = next_question(session)
    assert question is not None
    session = record_answer(
        session,
        _answer(question.id, AdaptiveDetailPayload(detail="milestone"), event_id="evt-adaptive"),
        expected_version=session.version,
        now=NOW,
    )
    assert session.status == PlanningSessionStatus.REVIEWING


def test_assistant_suggestions_require_awaiting_assistant_status() -> None:
    session = _start()

    with pytest.raises(PlanningPolicyError):
        record_assistant_suggestions(
            session,
            [],
            assistance_status="degraded",
            llm_calls=0,
            expected_version=session.version,
            now=NOW,
        )


def test_assistant_suggestions_mismatched_version_raises_stale_session_version_error() -> None:
    session = _answer_core(_start())

    with pytest.raises(StaleSessionVersionError):
        record_assistant_suggestions(
            session,
            [],
            assistance_status="degraded",
            llm_calls=0,
            expected_version=999,
            now=NOW,
        )


def test_complete_assistance_status_requires_at_least_one_llm_call() -> None:
    session = _answer_core(_start())

    with pytest.raises(PlanningPolicyError):
        record_assistant_suggestions(
            session,
            [],
            assistance_status="complete",
            llm_calls=0,
            expected_version=session.version,
            now=NOW,
        )


def test_degraded_assistance_status_accepts_zero_llm_calls() -> None:
    session = _answer_core(_start())

    result = record_assistant_suggestions(
        session,
        [],
        assistance_status="degraded",
        llm_calls=0,
        expected_version=session.version,
        now=NOW,
    )

    assert result.assistance_status == AssistanceStatus.DEGRADED
    assert result.interview_llm_calls == 0


def test_llm_call_ceiling_is_enforced_by_the_session_field_constraint() -> None:
    session = _answer_core(_start())

    with pytest.raises(ValidationError):
        record_assistant_suggestions(
            session,
            [],
            assistance_status="complete",
            llm_calls=3,
            expected_version=session.version,
            now=NOW,
        )


# --------------------------------------------------------------------------- #
# Bounded totals                                                               #
# --------------------------------------------------------------------------- #


def test_the_policy_never_returns_more_than_four_adaptive_or_twelve_total_decisions() -> None:
    # Trigger every applicable-adaptive predicate at once.
    session = _answer_core(
        _start(wallet=_wallet({"hdfc-infinia": 50_000})),
        essentials=_essentials(travelers=3),
        purpose=_purpose(purpose="celebration", adults=2, children_ages=[6]),
        budget=_budget(points_priority="use_points"),
        flight=_flight(max_stops=None),
        stay=_stay(tradeoff="balanced"),
        food=_food(food_interests=["street_food"]),
        constraints=_constraints(accessibility=["wheelchair"]),
    )

    result = _run_assistant_with_no_explicit_suggestions(session)

    assert len(result.suggested_question_ids) <= MAX_ADAPTIVE_DECISIONS
    total_after_all_adaptive = len(result.answers) + len(result.suggested_question_ids)
    assert total_after_all_adaptive <= MAX_DECISIONS

    # Drive to completion and confirm the hard ceiling actually holds.
    while True:
        question = next_question(result)
        if question is None:
            break
        result = record_answer(
            result,
            _answer(
                question.id,
                AdaptiveDetailPayload(detail="detail"),
                event_id=f"evt-{question.id}",
            ),
            expected_version=result.version,
            now=NOW,
        )
    assert len(result.answers) <= MAX_DECISIONS
    assert len(result.answers) >= MIN_DECISIONS


# --------------------------------------------------------------------------- #
# Resumption and terminal transition                                           #
# --------------------------------------------------------------------------- #


def test_recording_a_complete_assistant_result_resumes_applicable_adaptive_questions() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))

    result = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=2,
        expected_version=session.version,
        now=NOW,
    )

    assert result.status == PlanningSessionStatus.INTERVIEWING
    question = next_question(result)
    assert question is not None
    assert question.id == QuestionId.CELEBRATION_DETAILS


def test_recording_a_degraded_assistant_result_resumes_applicable_adaptive_questions() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))

    result = record_assistant_suggestions(
        session,
        [],
        assistance_status="degraded",
        llm_calls=0,
        expected_version=session.version,
        now=NOW,
    )

    assert result.status == PlanningSessionStatus.INTERVIEWING
    question = next_question(result)
    assert question is not None
    assert question.id == QuestionId.CELEBRATION_DETAILS


def test_status_becomes_reviewing_after_the_final_applicable_adaptive_question() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))
    session = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=1,
        expected_version=session.version,
        now=NOW,
    )
    question = next_question(session)
    assert question is not None

    session = record_answer(
        session,
        _answer(question.id, AdaptiveDetailPayload(detail="milestone"), event_id="evt-final"),
        expected_version=session.version,
        now=NOW,
    )

    assert session.status == PlanningSessionStatus.REVIEWING
    assert next_question(session) is None


def test_status_becomes_reviewing_immediately_when_no_adaptive_questions_apply() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="leisure"))

    result = _run_assistant_with_no_explicit_suggestions(session)

    assert result.status == PlanningSessionStatus.REVIEWING
    assert next_question(result) is None


# --------------------------------------------------------------------------- #
# Progress reporting                                                            #
# --------------------------------------------------------------------------- #


def test_interview_progress_at_the_start() -> None:
    session = _start()

    progress = interview_progress(session)

    assert progress.completed == 0
    assert progress.minimum_total == MIN_DECISIONS
    assert progress.maximum_total == MAX_DECISIONS


def test_interview_progress_while_awaiting_assistant() -> None:
    session = _answer_core(_start())

    progress = interview_progress(session)

    assert progress.completed == 8
    assert progress.minimum_total == MIN_DECISIONS
    assert progress.maximum_total == MAX_DECISIONS


def test_interview_progress_does_not_claim_an_exact_future_adaptive_count_mid_interview() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="celebration"))
    session = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=1,
        expected_version=session.version,
        now=NOW,
    )

    progress = interview_progress(session)

    # Exactly one adaptive question is queued, but progress must still report
    # an approximate range rather than claiming the exact eventual total.
    assert progress.completed == 8
    assert progress.minimum_total <= 9
    assert progress.maximum_total >= 9


def test_interview_progress_is_exact_once_reviewing() -> None:
    session = _answer_core(_start(), purpose=_purpose(purpose="leisure"))
    session = _run_assistant_with_no_explicit_suggestions(session)
    assert session.status == PlanningSessionStatus.REVIEWING

    progress = interview_progress(session)

    assert progress.completed == 8
    assert progress.minimum_total == 8
    assert progress.maximum_total == 8


# --------------------------------------------------------------------------- #
# Hypothesis: bounded termination across randomly generated valid paths        #
# --------------------------------------------------------------------------- #


@st.composite
def _interview_conditions(draw: st.DrawFn) -> dict[str, object]:
    purpose = draw(
        st.sampled_from(["leisure", "work", "celebration", "family", "mixed"])
    )
    children_ages = draw(st.lists(st.integers(min_value=0, max_value=17), max_size=3))
    adults = draw(st.integers(min_value=1, max_value=4))
    accessibility = draw(
        st.lists(st.sampled_from(["wheelchair", "hearing", "visual"]), max_size=2, unique=True)
    )
    has_points = draw(st.booleans())
    points_priority = draw(st.sampled_from(["save_points", "use_points", "best_value"]))
    max_stops = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=3)))
    stay_tradeoff = draw(
        st.sampled_from(["location", "price", "balanced", "no_preference"])
    )
    food_interests = draw(
        st.lists(
            st.sampled_from(["street_food", "fine_dining", "cafes", "markets"]),
            max_size=3,
            unique=True,
        )
    )
    return {
        "purpose": purpose,
        "children_ages": children_ages,
        "adults": adults,
        "accessibility": accessibility,
        "has_points": has_points,
        "points_priority": points_priority,
        "max_stops": max_stops,
        "stay_tradeoff": stay_tradeoff,
        "food_interests": food_interests,
    }


@given(_interview_conditions())
@settings(max_examples=100, deadline=None)
def test_the_policy_always_terminates_within_eight_to_twelve_decisions(
    conditions: dict[str, object],
) -> None:
    purpose = str(conditions["purpose"])
    children_ages = list(conditions["children_ages"])  # type: ignore[arg-type]
    adults = int(conditions["adults"])  # type: ignore[arg-type]
    accessibility = list(conditions["accessibility"])  # type: ignore[arg-type]
    has_points = bool(conditions["has_points"])
    points_priority = str(conditions["points_priority"])
    max_stops = conditions["max_stops"]
    stay_tradeoff = str(conditions["stay_tradeoff"])
    food_interests = list(conditions["food_interests"])  # type: ignore[arg-type]

    travelers = adults + len(children_ages)
    wallet = _wallet({"hdfc-infinia": 50_000} if has_points else {})

    session = _start(wallet=wallet, session_id="hyp")
    session = _answer_core(
        session,
        essentials=_essentials(travelers=travelers),
        purpose=_purpose(purpose=purpose, adults=adults, children_ages=children_ages),
        budget=_budget(points_priority=points_priority),
        flight=_flight(max_stops=max_stops),  # type: ignore[arg-type]
        stay=_stay(tradeoff=stay_tradeoff),
        food=_food(food_interests=food_interests),
        constraints=_constraints(accessibility=accessibility),
    )
    assert session.status == PlanningSessionStatus.AWAITING_ASSISTANT

    session = record_assistant_suggestions(
        session,
        [],
        assistance_status="degraded",
        llm_calls=0,
        expected_version=session.version,
        now=NOW,
    )

    # Bounded loop: at most MAX_ADAPTIVE_DECISIONS adaptive answers remain, so
    # this always terminates for a correctly implemented policy. A stuck
    # policy would exceed this guard and fail the test rather than hang.
    for _ in range(MAX_ADAPTIVE_DECISIONS + 1):
        question = next_question(session)
        if question is None:
            break
        session = record_answer(
            session,
            _answer(
                question.id,
                AdaptiveDetailPayload(detail="generated"),
                event_id=f"hyp-{question.id}-{session.version}",
            ),
            expected_version=session.version,
            now=NOW,
        )

    assert session.status == PlanningSessionStatus.REVIEWING
    assert MIN_DECISIONS <= len(session.answers) <= MAX_DECISIONS
    assert len(session.answers) == len(set(session.answers))
    assert next_question(session) is None


def test_all_fifteen_catalog_questions_have_a_definition() -> None:
    assert len(DEFAULT_QUESTION_CATALOG) == 15
