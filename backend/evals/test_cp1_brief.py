"""Deterministic Trip Brief assembly and confirmation (CP1 task 6).

``planning.brief`` turns a completed (``reviewing``) ``PlanningSession`` into
a fully-resolved, typed ``TripBrief`` -- and, separately, into typed
``ProfileUpdateProposal`` data -- with no LLM call anywhere. Confirmation
requires the caller's ``TripBrief`` to byte-match a brief freshly reassembled
from the session's current state (the anti-tamper/anti-staleness mechanism)
before it is allowed to become the session's first (and, in CP1, only)
``ConfirmedBriefSnapshot``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from accounts.models import (
    Cabin,
    FlightPreferences,
    PreferenceValue,
    StayPreferences,
    TravelPreferenceProfile,
)
from accounts.store import AccountStore
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
from planning.brief import (
    BriefAlreadyConfirmedError,
    BriefMismatchError,
    BriefNotReadyError,
    assemble_trip_brief,
    build_profile_update_proposals,
    confirm_trip_brief,
)
from planning.contracts import (
    ConfirmedBriefSnapshot,
    PlanningSession,
    PlanningSessionStatus,
    TravelerHomeContext,
)
from planning.policy import (
    StaleSessionVersionError,
    record_answer,
    record_assistant_suggestions,
    start_interview,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(minutes=5)
CONFIRM_NOW = NOW + timedelta(minutes=10)
EXPIRES = NOW + timedelta(days=30)


# --------------------------------------------------------------------------- #
# Fixtures / payload builders (mirrors evals/test_cp1_policy.py's style)       #
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
    return FlightPreferencesPayload(cabin="economy", max_stops=max_stops, schedule="no_preference")


def _stay(tradeoff: str = "no_preference") -> StayPreferencesPayload:
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
    memory_scope: str = "trip_only",
) -> InterviewAnswer:
    return InterviewAnswer(
        question_id=question_id,
        payload=payload,  # type: ignore[arg-type]
        delegated=delegated,
        memory_scope=memory_scope,  # type: ignore[arg-type]
        client_event_id=event_id,
        answered_at=NOW,
    )


def _record(session: PlanningSession, answer: InterviewAnswer) -> PlanningSession:
    return record_answer(session, answer, expected_version=session.version, now=NOW)


def _core_answered_session(
    *,
    wallet: UserWallet | None = None,
    profile_defaults: TravelPreferenceProfile | None = None,
    essentials: InterviewAnswer | None = None,
    purpose: InterviewAnswer | None = None,
    budget: InterviewAnswer | None = None,
    flight: InterviewAnswer | None = None,
    stay: InterviewAnswer | None = None,
    rhythm: InterviewAnswer | None = None,
    food: InterviewAnswer | None = None,
    constraints: InterviewAnswer | None = None,
    session_id: str = "ps1",
) -> PlanningSession:
    """Drive a fresh session through all 8 core questions, leaving it
    ``awaiting_assistant`` -- the caller decides what to do about adaptive
    questions from there (skip them entirely, or explicitly queue some via
    ``record_assistant_suggestions``).
    """
    session = _start(wallet=wallet, profile_defaults=profile_defaults, session_id=session_id)
    steps = [
        essentials or _answer(QuestionId.TRIP_ESSENTIALS, _essentials(), event_id="core-0"),
        purpose or _answer(QuestionId.PURPOSE_AND_PARTY, _purpose(), event_id="core-1"),
        budget or _answer(QuestionId.BUDGET_AND_OBJECTIVE, _budget(), event_id="core-2"),
        flight or _answer(QuestionId.FLIGHT_PREFERENCES, _flight(), event_id="core-3"),
        stay or _answer(QuestionId.STAY_PREFERENCES, _stay(), event_id="core-4"),
        rhythm or _answer(QuestionId.DAILY_RHYTHM, _rhythm(), event_id="core-5"),
        food or _answer(QuestionId.EXPERIENCES_AND_FOOD, _food(), event_id="core-6"),
        constraints or _answer(QuestionId.HARD_CONSTRAINTS, _constraints(), event_id="core-7"),
    ]
    for answer in steps:
        session = _record(session, answer)
    assert session.status == PlanningSessionStatus.AWAITING_ASSISTANT
    return session


def _reviewing_session(
    *,
    wallet: UserWallet | None = None,
    profile_defaults: TravelPreferenceProfile | None = None,
    essentials: InterviewAnswer | None = None,
    purpose: InterviewAnswer | None = None,
    budget: InterviewAnswer | None = None,
    flight: InterviewAnswer | None = None,
    stay: InterviewAnswer | None = None,
    rhythm: InterviewAnswer | None = None,
    food: InterviewAnswer | None = None,
    constraints: InterviewAnswer | None = None,
    session_id: str = "ps1",
) -> PlanningSession:
    """As ``_core_answered_session``, then skip straight to ``reviewing``.

    Only safe when the caller's overrides are known not to trigger any of
    the 7 adaptive predicates (the module-level defaults are chosen not
    to); callers that need an adaptive question queued should use
    ``_core_answered_session`` and drive ``record_assistant_suggestions``
    themselves instead.
    """
    session = _core_answered_session(
        wallet=wallet,
        profile_defaults=profile_defaults,
        essentials=essentials,
        purpose=purpose,
        budget=budget,
        flight=flight,
        stay=stay,
        rhythm=rhythm,
        food=food,
        constraints=constraints,
        session_id=session_id,
    )
    session = record_assistant_suggestions(
        session,
        [],
        assistance_status="degraded",
        llm_calls=0,
        expected_version=session.version,
        now=NOW,
    )
    assert session.status == PlanningSessionStatus.REVIEWING
    return session


def _profile_with_flight_default(*, source: str = "user_profile_edit") -> TravelPreferenceProfile:
    return TravelPreferenceProfile(
        user_id="u1",
        flight=FlightPreferences(
            cabin=PreferenceValue[Cabin](value="business", source=source, updated_at=NOW)  # type: ignore[arg-type]
        ),
        updated_at=NOW,
    )


# --------------------------------------------------------------------------- #
# assemble_trip_brief: readiness gate                                          #
# --------------------------------------------------------------------------- #


def test_assembly_rejects_a_session_that_is_not_reviewing() -> None:
    session = _start()

    with pytest.raises(BriefNotReadyError):
        assemble_trip_brief(session)


def test_assembly_rejects_an_awaiting_assistant_session() -> None:
    session = _start()
    for index, (question_id, payload) in enumerate(
        [
            (QuestionId.TRIP_ESSENTIALS, _essentials()),
            (QuestionId.PURPOSE_AND_PARTY, _purpose()),
            (QuestionId.BUDGET_AND_OBJECTIVE, _budget()),
            (QuestionId.FLIGHT_PREFERENCES, _flight()),
            (QuestionId.STAY_PREFERENCES, _stay()),
            (QuestionId.DAILY_RHYTHM, _rhythm()),
            (QuestionId.EXPERIENCES_AND_FOOD, _food()),
            (QuestionId.HARD_CONSTRAINTS, _constraints()),
        ]
    ):
        session = _record(session, _answer(question_id, payload, event_id=f"core-{index}"))
    assert session.status == PlanningSessionStatus.AWAITING_ASSISTANT

    with pytest.raises(BriefNotReadyError):
        assemble_trip_brief(session)


# --------------------------------------------------------------------------- #
# assemble_trip_brief: essentials + hard constraints always present            #
# --------------------------------------------------------------------------- #


def test_essentials_and_hard_constraints_are_always_present() -> None:
    session = _reviewing_session()

    brief = assemble_trip_brief(session)

    assert brief.trip_essentials == _essentials()
    assert brief.hard_constraints == _constraints()


# --------------------------------------------------------------------------- #
# assemble_trip_brief: delegation -> None + delegated_questions + assumption   #
# --------------------------------------------------------------------------- #


def test_a_delegated_optional_answer_becomes_none_in_the_brief() -> None:
    session = _reviewing_session(
        purpose=_answer(QuestionId.PURPOSE_AND_PARTY, None, event_id="core-1", delegated=True)
    )

    brief = assemble_trip_brief(session)

    assert brief.purpose_and_party is None


def test_a_delegated_optional_answer_appears_in_delegated_questions() -> None:
    session = _reviewing_session(
        purpose=_answer(QuestionId.PURPOSE_AND_PARTY, None, event_id="core-1", delegated=True)
    )

    brief = assemble_trip_brief(session)

    assert brief.delegated_questions == [QuestionId.PURPOSE_AND_PARTY]


def test_a_delegated_optional_answer_produces_a_calm_deterministic_assumption() -> None:
    session = _reviewing_session(
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True)
    )

    brief = assemble_trip_brief(session)

    assert len(brief.assumptions) == 1
    assert isinstance(brief.assumptions[0], str)
    assert brief.assumptions[0].strip() != ""


def test_assembling_the_same_session_twice_produces_identical_assumptions() -> None:
    session = _reviewing_session(
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True)
    )

    first = assemble_trip_brief(session)
    second = assemble_trip_brief(session)

    assert first.assumptions == second.assumptions
    assert first.model_dump_json() == second.model_dump_json()


def test_delegated_questions_are_ordered_by_catalog_order_not_answer_order() -> None:
    # stay is answered before flight in the catalog (priority 40 vs 50), but
    # both are delegated here in the opposite order of how a hand-rolled dict
    # would iterate them if keyed by insertion.
    session = _reviewing_session(
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True),
        stay=_answer(QuestionId.STAY_PREFERENCES, None, event_id="core-4", delegated=True),
    )

    brief = assemble_trip_brief(session)

    assert brief.delegated_questions == [
        QuestionId.FLIGHT_PREFERENCES,
        QuestionId.STAY_PREFERENCES,
    ]


# --------------------------------------------------------------------------- #
# assemble_trip_brief: profile defaults applied for a delegated section        #
# --------------------------------------------------------------------------- #


def test_delegated_section_with_profile_defaults_appears_in_applied_profile_sections() -> None:
    profile = _profile_with_flight_default()
    session = _reviewing_session(
        profile_defaults=profile,
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True),
    )

    brief = assemble_trip_brief(session)

    assert brief.applied_profile_sections == ["flight"]


def test_applied_profile_preferences_snapshot_carries_the_delegated_sections_values() -> None:
    profile = _profile_with_flight_default()
    session = _reviewing_session(
        profile_defaults=profile,
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True),
    )

    brief = assemble_trip_brief(session)

    assert brief.applied_profile_preferences is not None
    assert brief.applied_profile_preferences.flight.cabin is not None
    assert brief.applied_profile_preferences.flight.cabin.value == "business"


def test_applied_profile_preferences_preserves_the_original_provenance_untouched() -> None:
    profile = _profile_with_flight_default(source="user_profile_edit")
    session = _reviewing_session(
        profile_defaults=profile,
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True),
    )

    brief = assemble_trip_brief(session)

    assert brief.applied_profile_preferences is not None
    applied_cabin = brief.applied_profile_preferences.flight.cabin
    assert applied_cabin is not None
    # Provenance is copied verbatim from the stored profile default -- never
    # re-stamped as though the assembler just learned this preference itself.
    assert applied_cabin.source == "user_profile_edit"
    assert applied_cabin.updated_at == NOW


def test_delegated_section_without_any_profile_defaults_applies_nothing() -> None:
    session = _reviewing_session(
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True)
    )

    brief = assemble_trip_brief(session)

    assert brief.applied_profile_sections == []
    assert brief.applied_profile_preferences is None


def test_delegated_section_with_an_empty_profile_group_applies_nothing() -> None:
    # A profile exists, but its `flight` group has never actually been set.
    empty_profile = TravelPreferenceProfile(user_id="u1", updated_at=NOW)
    session = _reviewing_session(
        profile_defaults=empty_profile,
        flight=_answer(QuestionId.FLIGHT_PREFERENCES, None, event_id="core-3", delegated=True),
    )

    brief = assemble_trip_brief(session)

    assert brief.applied_profile_sections == []
    assert brief.applied_profile_preferences is None


# --------------------------------------------------------------------------- #
# assemble_trip_brief: adaptive details survive keyed by question id           #
# --------------------------------------------------------------------------- #


def test_adaptive_details_survive_keyed_by_their_approved_question_id() -> None:
    session = _core_answered_session(
        purpose=_answer(
            QuestionId.PURPOSE_AND_PARTY, _purpose(purpose="celebration"), event_id="core-1"
        )
    )
    session = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=1,
        expected_version=session.version,
        now=NOW,
    )
    session = _record(
        session,
        _answer(
            QuestionId.CELEBRATION_DETAILS,
            AdaptiveDetailPayload(detail="milestone anniversary"),
            event_id="adaptive-0",
        ),
    )
    assert session.status == PlanningSessionStatus.REVIEWING

    brief = assemble_trip_brief(session)

    assert brief.adaptive_details == {
        QuestionId.CELEBRATION_DETAILS: AdaptiveDetailPayload(detail="milestone anniversary")
    }


def test_a_delegated_adaptive_question_has_no_entry_in_adaptive_details() -> None:
    session = _core_answered_session(
        purpose=_answer(
            QuestionId.PURPOSE_AND_PARTY, _purpose(purpose="celebration"), event_id="core-1"
        )
    )
    session = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=1,
        expected_version=session.version,
        now=NOW,
    )
    session = _record(
        session,
        _answer(
            QuestionId.CELEBRATION_DETAILS, None, event_id="adaptive-0", delegated=True
        ),
    )
    assert session.status == PlanningSessionStatus.REVIEWING

    brief = assemble_trip_brief(session)

    assert brief.adaptive_details == {}
    assert brief.delegated_questions == [QuestionId.CELEBRATION_DETAILS]


# --------------------------------------------------------------------------- #
# assemble_trip_brief: wallet copied verbatim                                  #
# --------------------------------------------------------------------------- #


def test_wallet_is_copied_from_the_session_without_summing_or_changing_balances() -> None:
    wallet = _wallet({"hdfc-infinia": 50_000, "amex-platinum": 12_345})
    # points_priority="save_points" keeps points_strategy inapplicable so this
    # session reaches `reviewing` with no adaptive question queued.
    session = _reviewing_session(
        wallet=wallet,
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(points_priority="save_points"),
            event_id="core-2",
        ),
    )

    brief = assemble_trip_brief(session)

    assert brief.wallet == wallet
    assert brief.wallet.points_balances == {"hdfc-infinia": 50_000, "amex-platinum": 12_345}


# --------------------------------------------------------------------------- #
# build_profile_update_proposals: only propose_profile_update answers qualify  #
# --------------------------------------------------------------------------- #


def test_only_answers_marked_propose_profile_update_produce_proposals() -> None:
    session = _reviewing_session(
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(),
            event_id="core-2",
            memory_scope="propose_profile_update",
        )
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert len(proposals) == 1
    assert proposals[0].section == "optimization"
    assert proposals[0].source_question_id == QuestionId.BUDGET_AND_OBJECTIVE


def test_a_trip_only_answer_produces_no_proposal() -> None:
    session = _reviewing_session()  # every core answer defaults to trip_only

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert proposals == []


def test_multiple_propose_profile_update_answers_produce_one_proposal_each_in_catalog_order() -> (
    None
):
    session = _reviewing_session(
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(),
            event_id="core-2",
            memory_scope="propose_profile_update",
        ),
        flight=_answer(
            QuestionId.FLIGHT_PREFERENCES,
            _flight(),
            event_id="core-3",
            memory_scope="propose_profile_update",
        ),
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert [p.source_question_id for p in proposals] == [
        QuestionId.BUDGET_AND_OBJECTIVE,
        QuestionId.FLIGHT_PREFERENCES,
    ]
    assert [p.section for p in proposals] == ["optimization", "flight"]


def test_proposal_ids_are_deterministic_and_formatted_from_session_id_version_and_section() -> (
    None
):
    session = _reviewing_session(
        session_id="ps-42",
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(),
            event_id="core-2",
            memory_scope="propose_profile_update",
        ),
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert len(proposals) == 1
    assert proposals[0].proposal_id == f"ps-42:{session.version}:optimization"


def test_wrapped_preference_values_carry_user_confirmed_from_trip_source_and_now() -> None:
    session = _reviewing_session(
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(points_priority="use_points"),
            event_id="core-2",
            memory_scope="propose_profile_update",
        )
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    optimization = proposals[0].candidate_profile.optimization
    assert optimization.objective is not None
    assert optimization.objective.source == "user_confirmed_from_trip"
    assert optimization.objective.updated_at == CONFIRM_NOW
    assert optimization.points_priority is not None
    assert optimization.points_priority.value == "use_points"


def test_purpose_party_trip_essentials_celebration_and_children_details_never_propose_updates() -> (
    None
):
    # These four answer kinds are structurally ineligible: InterviewAnswer's
    # own validator (planning/answers.py) rejects memory_scope=
    # "propose_profile_update" for any payload type outside its closed
    # 6-kind allowlist, so none of the four below can ever produce a
    # proposal, no matter how the interview was answered.
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.PURPOSE_AND_PARTY,
            payload=_purpose(),
            memory_scope="propose_profile_update",
            client_event_id="evt-x",
            answered_at=NOW,
        )
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.TRIP_ESSENTIALS,
            payload=_essentials(),
            memory_scope="propose_profile_update",
            client_event_id="evt-y",
            answered_at=NOW,
        )
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.CELEBRATION_DETAILS,
            payload=AdaptiveDetailPayload(detail="x"),
            memory_scope="propose_profile_update",
            client_event_id="evt-z",
            answered_at=NOW,
        )
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.CHILDREN_NEEDS,
            payload=AdaptiveDetailPayload(detail="x"),
            memory_scope="propose_profile_update",
            client_event_id="evt-w",
            answered_at=NOW,
        )

    # And, correspondingly, a normal reviewing session (all trip_only) never
    # yields a proposal for any of these sections.
    session = _core_answered_session(
        purpose=_answer(
            QuestionId.PURPOSE_AND_PARTY, _purpose(purpose="celebration"), event_id="core-1"
        )
    )
    session = record_assistant_suggestions(
        session,
        [QuestionId.CELEBRATION_DETAILS],
        assistance_status="complete",
        llm_calls=1,
        expected_version=session.version,
        now=NOW,
    )
    session = _record(
        session,
        _answer(
            QuestionId.CELEBRATION_DETAILS, AdaptiveDetailPayload(detail="x"), event_id="adaptive-0"
        ),
    )
    assert session.status == PlanningSessionStatus.REVIEWING

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)
    assert proposals == []


def test_stay_preference_proposal_maps_neighborhood_priorities_to_location_priorities() -> None:
    session = _reviewing_session(
        stay=_answer(
            QuestionId.STAY_PREFERENCES,
            StayPreferencesPayload(
                lodging_styles=["boutique"],
                neighborhood_priorities=["central"],
                location_price_tradeoff="location",
            ),
            event_id="core-4",
            memory_scope="propose_profile_update",
        )
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert len(proposals) == 1
    stay_prefs = proposals[0].candidate_profile.stay
    assert stay_prefs.lodging_styles is not None
    assert stay_prefs.lodging_styles.value == ["boutique"]
    assert stay_prefs.location_priorities is not None
    assert stay_prefs.location_priorities.value == ["central"]


def test_no_preference_sentinel_values_are_not_persisted_as_a_durable_preference() -> None:
    session = _reviewing_session(
        flight=_answer(
            QuestionId.FLIGHT_PREFERENCES,
            # max_stops=1 keeps flight_tradeoff inapplicable so this session
            # reaches `reviewing` with no adaptive question queued.
            FlightPreferencesPayload(
                cabin="no_preference", max_stops=1, schedule="no_preference"
            ),
            event_id="core-3",
            memory_scope="propose_profile_update",
        )
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert len(proposals) == 1
    assert proposals[0].candidate_profile.flight.cabin is None


def test_candidate_profile_replaces_only_the_matching_group_preserving_other_sections() -> None:
    profile = TravelPreferenceProfile(
        user_id="u1",
        stay=StayPreferences(
            lodging_styles=PreferenceValue[list[str]](
                value=["boutique"], source="user_profile_edit", updated_at=NOW
            )
        ),
        updated_at=NOW,
    )
    session = _reviewing_session(
        profile_defaults=profile,
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(),
            event_id="core-2",
            memory_scope="propose_profile_update",
        ),
    )

    proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert len(proposals) == 1
    candidate = proposals[0].candidate_profile
    assert candidate.optimization.objective is not None
    # The untouched `stay` group from the existing profile survives verbatim.
    assert candidate.stay.lodging_styles is not None
    assert candidate.stay.lodging_styles.value == ["boutique"]
    assert candidate.stay.lodging_styles.source == "user_profile_edit"


def test_build_profile_update_proposals_does_not_call_put_travel_preferences() -> None:
    session = _reviewing_session(
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(),
            event_id="core-2",
            memory_scope="propose_profile_update",
        )
    )

    with patch.object(AccountStore, "put_travel_preferences") as mocked:
        proposals = build_profile_update_proposals(session, now=CONFIRM_NOW)

    assert len(proposals) == 1
    mocked.assert_not_called()


# --------------------------------------------------------------------------- #
# confirm_trip_brief: byte-equivalence, revision 1, status/version transition  #
# --------------------------------------------------------------------------- #


def test_confirm_requires_byte_equivalence_with_a_freshly_assembled_brief() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)

    tampered = brief.model_copy(update={"assumptions": ["a fabricated assumption"]})

    with pytest.raises(BriefMismatchError):
        confirm_trip_brief(session, tampered, expected_version=session.version, now=CONFIRM_NOW)


def test_confirm_appends_revision_one() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)

    result = confirm_trip_brief(session, brief, expected_version=session.version, now=CONFIRM_NOW)

    assert result.confirmed_briefs == [
        ConfirmedBriefSnapshot(revision=1, brief=brief, confirmed_at=CONFIRM_NOW)
    ]


def test_confirm_changes_status_to_confirmed() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)

    result = confirm_trip_brief(session, brief, expected_version=session.version, now=CONFIRM_NOW)

    assert result.status == PlanningSessionStatus.CONFIRMED


def test_confirm_increments_the_session_version() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)
    original_version = session.version

    result = confirm_trip_brief(session, brief, expected_version=session.version, now=CONFIRM_NOW)

    assert result.version == original_version + 1


def test_confirm_preserves_all_answers() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)
    original_answers = dict(session.answers)

    result = confirm_trip_brief(session, brief, expected_version=session.version, now=CONFIRM_NOW)

    assert result.answers == original_answers


def test_confirm_does_not_mutate_the_input_session() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)
    original_status = session.status
    original_version = session.version

    confirm_trip_brief(session, brief, expected_version=session.version, now=CONFIRM_NOW)

    assert session.status == original_status
    assert session.version == original_version
    assert session.confirmed_briefs == []


def test_confirm_sets_pending_profile_updates_from_the_proposal_builder() -> None:
    session = _reviewing_session(
        budget=_answer(
            QuestionId.BUDGET_AND_OBJECTIVE,
            _budget(),
            event_id="core-2",
            memory_scope="propose_profile_update",
        )
    )
    brief = assemble_trip_brief(session)

    result = confirm_trip_brief(session, brief, expected_version=session.version, now=CONFIRM_NOW)

    assert len(result.pending_profile_updates) == 1
    assert result.pending_profile_updates[0].section == "optimization"


# --------------------------------------------------------------------------- #
# confirm_trip_brief: cannot reconfirm / cannot overwrite                      #
# --------------------------------------------------------------------------- #


def test_an_already_confirmed_session_cannot_be_reconfirmed() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)
    confirmed = confirm_trip_brief(
        session, brief, expected_version=session.version, now=CONFIRM_NOW
    )
    assert confirmed.status == PlanningSessionStatus.CONFIRMED

    with pytest.raises(BriefAlreadyConfirmedError):
        confirm_trip_brief(
            confirmed, brief, expected_version=confirmed.version, now=CONFIRM_NOW
        )


def test_a_hand_tampered_reviewing_session_with_an_existing_snapshot_cannot_be_confirmed() -> (
    None
):
    """Defense-in-depth: through the public API a `reviewing` session can never
    already carry a `ConfirmedBriefSnapshot` (confirming always flips status
    away from `reviewing`). This hand-builds that otherwise-unreachable state
    to prove the `confirmed_briefs`-must-be-empty guard fires even then, not
    only via the ordinary post-confirm status check.
    """
    session = _reviewing_session()
    brief = assemble_trip_brief(session)
    stale_snapshot = ConfirmedBriefSnapshot(revision=1, brief=brief, confirmed_at=NOW)
    tampered = PlanningSession.model_validate(
        {
            **session.model_dump(),
            "status": PlanningSessionStatus.REVIEWING.value,
            "confirmed_briefs": [stale_snapshot.model_dump()],
        }
    )

    with pytest.raises(BriefAlreadyConfirmedError):
        confirm_trip_brief(tampered, brief, expected_version=tampered.version, now=CONFIRM_NOW)


# --------------------------------------------------------------------------- #
# confirm_trip_brief: fail closed on stale version / tampered brief            #
# --------------------------------------------------------------------------- #


def test_confirm_fails_closed_on_a_stale_expected_version() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)

    with pytest.raises(StaleSessionVersionError):
        confirm_trip_brief(session, brief, expected_version=session.version + 1, now=CONFIRM_NOW)


def test_confirm_fails_closed_on_a_mismatched_brief() -> None:
    session = _reviewing_session()
    other_session = _reviewing_session(
        session_id="ps-other",
        essentials=_answer(
            QuestionId.TRIP_ESSENTIALS, _essentials(travelers=4), event_id="core-0"
        ),
        purpose=_answer(
            QuestionId.PURPOSE_AND_PARTY, _purpose(adults=4), event_id="core-1"
        ),
    )
    other_brief = assemble_trip_brief(other_session)

    with pytest.raises(BriefMismatchError):
        confirm_trip_brief(session, other_brief, expected_version=session.version, now=CONFIRM_NOW)


def test_confirm_fails_closed_when_the_session_advanced_since_the_brief_was_assembled() -> None:
    session = _reviewing_session()
    brief = assemble_trip_brief(session)
    # Simulate the session having moved on (e.g. re-answered) since assembly:
    # tamper trip_essentials travelers count in a hand-copied brief.
    stale_brief = brief.model_copy(
        update={"trip_essentials": brief.trip_essentials.model_copy(update={"travelers": 4})}
    )

    with pytest.raises(BriefMismatchError):
        confirm_trip_brief(session, stale_brief, expected_version=session.version, now=CONFIRM_NOW)
