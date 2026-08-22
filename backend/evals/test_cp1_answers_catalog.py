"""Strict interview-answer contracts and the approved CP1 question catalog.

The conversational interview has exactly 15 approved questions: 8 core
questions asked on every trip, plus up to 7 adaptive follow-ups asked only
when applicable. Required facts and the hard-constraint acknowledgement
cannot be delegated to the system — that is enforced here structurally via
``QuestionDefinition.allow_delegate``, not left to caller discipline.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from planning.answers import (
    ANSWER_TYPE_BY_QUESTION,
    AdaptiveDetailPayload,
    BudgetObjectivePayload,
    HardConstraintsPayload,
    InterviewAnswer,
    PurposePartyPayload,
    QuestionId,
    TripEssentialsPayload,
)
from planning.question_catalog import (
    ADAPTIVE_QUESTION_IDS,
    CORE_QUESTION_ORDER,
    DEFAULT_QUESTION_CATALOG,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

EXPECTED_CORE = (
    "trip_essentials",
    "purpose_and_party",
    "budget_and_objective",
    "flight_preferences",
    "stay_preferences",
    "daily_rhythm",
    "experiences_and_food",
    "hard_constraints",
)
EXPECTED_ADAPTIVE = {
    "celebration_details",
    "children_needs",
    "mobility_details",
    "points_strategy",
    "flight_tradeoff",
    "hotel_tradeoff",
    "food_depth",
}

ADAPTIVE_ORDER = (
    QuestionId.CELEBRATION_DETAILS,
    QuestionId.CHILDREN_NEEDS,
    QuestionId.MOBILITY_DETAILS,
    QuestionId.POINTS_STRATEGY,
    QuestionId.FLIGHT_TRADEOFF,
    QuestionId.HOTEL_TRADEOFF,
    QuestionId.FOOD_DEPTH,
)


def _essentials_payload() -> TripEssentialsPayload:
    return TripEssentialsPayload(
        origin="DEL",
        destination="SIN",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        travelers=2,
    )


# --------------------------------------------------------------------------- #
# QuestionId / catalog completeness
# --------------------------------------------------------------------------- #


def test_question_id_contains_exactly_the_approved_15_values() -> None:
    values = {member.value for member in QuestionId}
    assert values == set(EXPECTED_CORE) | EXPECTED_ADAPTIVE
    assert len(values) == 15


def test_core_question_order_is_byte_stable_and_has_eight_ids() -> None:
    assert tuple(q.value for q in CORE_QUESTION_ORDER) == EXPECTED_CORE
    assert len(CORE_QUESTION_ORDER) == 8


def test_adaptive_question_ids_match_the_approved_set() -> None:
    assert {q.value for q in ADAPTIVE_QUESTION_IDS} == EXPECTED_ADAPTIVE


def test_default_catalog_has_exactly_15_unique_entries() -> None:
    ids = [definition.id for definition in DEFAULT_QUESTION_CATALOG]
    assert len(ids) == 15
    assert len(set(ids)) == 15
    assert set(ids) == set(CORE_QUESTION_ORDER) | ADAPTIVE_QUESTION_IDS


def test_every_catalog_entry_has_nonempty_prompt_kind_domains_and_unique_priority() -> None:
    priorities = [definition.priority for definition in DEFAULT_QUESTION_CATALOG]
    assert len(priorities) == len(set(priorities))
    for definition in DEFAULT_QUESTION_CATALOG:
        assert definition.prompt.strip() != ""
        assert definition.answer_kind != ""
        assert len(definition.impact_domains) > 0


def test_only_trip_essentials_and_hard_constraints_disallow_delegation() -> None:
    non_delegable = {
        definition.id for definition in DEFAULT_QUESTION_CATALOG if not definition.allow_delegate
    }
    assert non_delegable == {QuestionId.TRIP_ESSENTIALS, QuestionId.HARD_CONSTRAINTS}


def test_core_priorities_are_10_through_80_in_listed_order() -> None:
    by_id = {definition.id: definition.priority for definition in DEFAULT_QUESTION_CATALOG}
    assert [by_id[q] for q in CORE_QUESTION_ORDER] == [10, 20, 30, 40, 50, 60, 70, 80]


def test_adaptive_priorities_are_110_through_170_in_listed_order() -> None:
    by_id = {definition.id: definition.priority for definition in DEFAULT_QUESTION_CATALOG}
    assert [by_id[q] for q in ADAPTIVE_ORDER] == [110, 120, 130, 140, 150, 160, 170]


def test_answer_type_by_question_covers_all_question_ids() -> None:
    assert set(ANSWER_TYPE_BY_QUESTION) == set(QuestionId)


# --------------------------------------------------------------------------- #
# TripEssentialsPayload
# --------------------------------------------------------------------------- #


def test_trip_essentials_normalizes_iata_casing_and_whitespace() -> None:
    payload = TripEssentialsPayload(
        origin="  del ",
        destination="sin",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        travelers=2,
    )
    assert payload.origin == "DEL"
    assert payload.destination == "SIN"


def test_trip_essentials_rejects_non_iata_origin() -> None:
    with pytest.raises(ValidationError):
        TripEssentialsPayload(
            origin="Delhi",
            destination="SIN",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            travelers=2,
        )


def test_trip_essentials_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError):
        TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=date(2026, 10, 5),
            end_date=date(2026, 10, 1),
            travelers=2,
        )


def test_trip_essentials_rejects_zero_travelers() -> None:
    with pytest.raises(ValidationError):
        TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            travelers=0,
        )


def test_trip_essentials_rejects_trips_shorter_than_three_nights() -> None:
    with pytest.raises(ValidationError):
        TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 3),
            travelers=2,
        )


def test_trip_essentials_rejects_trips_longer_than_seven_nights() -> None:
    with pytest.raises(ValidationError):
        TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 10),
            travelers=2,
        )


def test_trip_essentials_accepts_the_three_and_seven_night_boundaries() -> None:
    three_nights = TripEssentialsPayload(
        origin="DEL",
        destination="SIN",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 4),
        travelers=2,
    )
    seven_nights = TripEssentialsPayload(
        origin="DEL",
        destination="SIN",
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 8),
        travelers=2,
    )
    assert (three_nights.end_date - three_nights.start_date).days == 3
    assert (seven_nights.end_date - seven_nights.start_date).days == 7


# --------------------------------------------------------------------------- #
# BudgetObjectivePayload currency normalization
# --------------------------------------------------------------------------- #


def test_budget_objective_normalizes_currency_casing_and_whitespace() -> None:
    payload = BudgetObjectivePayload(
        budget_minor=500_000,
        currency=" inr ",
        travel_style="balanced",
        objective="balanced",
        points_priority="best_value",
    )
    assert payload.currency == "INR"


# --------------------------------------------------------------------------- #
# HardConstraintsPayload consistency
# --------------------------------------------------------------------------- #


def test_hard_constraints_false_rejects_nonempty_dietary_list() -> None:
    with pytest.raises(ValidationError):
        HardConstraintsPayload(has_constraints=False, dietary=["vegetarian"])


def test_hard_constraints_true_requires_at_least_one_item() -> None:
    with pytest.raises(ValidationError):
        HardConstraintsPayload(has_constraints=True)


def test_hard_constraints_true_accepts_one_populated_list() -> None:
    payload = HardConstraintsPayload(has_constraints=True, dietary=["vegetarian"])
    assert payload.dietary == ["vegetarian"]


def test_hard_constraints_false_accepts_all_lists_empty() -> None:
    payload = HardConstraintsPayload(has_constraints=False)
    assert payload.dietary == []
    assert payload.accessibility == []
    assert payload.exclusions == []
    assert payload.immovable_events == []


# --------------------------------------------------------------------------- #
# AdaptiveDetailPayload free text
# --------------------------------------------------------------------------- #


def test_adaptive_detail_is_trimmed() -> None:
    payload = AdaptiveDetailPayload(detail="  celebrating a 30th birthday  ")
    assert payload.detail == "celebrating a 30th birthday"


def test_adaptive_detail_rejects_whitespace_only() -> None:
    with pytest.raises(ValidationError):
        AdaptiveDetailPayload(detail="    ")


def test_adaptive_detail_rejects_over_1000_characters() -> None:
    with pytest.raises(ValidationError):
        AdaptiveDetailPayload(detail="a" * 1001)


def test_adaptive_detail_accepts_exactly_1000_characters() -> None:
    payload = AdaptiveDetailPayload(detail="a" * 1000)
    assert len(payload.detail) == 1000


# --------------------------------------------------------------------------- #
# InterviewAnswer consistency
# --------------------------------------------------------------------------- #


def test_interview_answer_accepts_a_matching_payload() -> None:
    answer = InterviewAnswer(
        question_id=QuestionId.TRIP_ESSENTIALS,
        payload=_essentials_payload(),
        delegated=False,
        client_event_id="evt-1",
        answered_at=NOW,
    )
    assert answer.payload == _essentials_payload()


def test_interview_answer_rejects_payload_type_mismatch() -> None:
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.TRIP_ESSENTIALS,
            payload=PurposePartyPayload(purpose="leisure", adults=2),
            delegated=False,
            client_event_id="evt-2",
            answered_at=NOW,
        )


def test_interview_answer_delegated_rejects_a_payload() -> None:
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.PURPOSE_AND_PARTY,
            payload=PurposePartyPayload(purpose="leisure", adults=2),
            delegated=True,
            client_event_id="evt-3",
            answered_at=NOW,
        )


def test_interview_answer_nondelegated_requires_a_payload() -> None:
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.PURPOSE_AND_PARTY,
            payload=None,
            delegated=False,
            client_event_id="evt-4",
            answered_at=NOW,
        )


def test_interview_answer_delegated_without_payload_is_valid() -> None:
    answer = InterviewAnswer(
        question_id=QuestionId.PURPOSE_AND_PARTY,
        payload=None,
        delegated=True,
        client_event_id="evt-5",
        answered_at=NOW,
    )
    assert answer.delegated is True
    assert answer.payload is None


def test_memory_scope_profile_update_rejected_for_trip_essentials() -> None:
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.TRIP_ESSENTIALS,
            payload=_essentials_payload(),
            delegated=False,
            memory_scope="propose_profile_update",
            client_event_id="evt-6",
            answered_at=NOW,
        )


def test_memory_scope_profile_update_rejected_for_purpose_and_party() -> None:
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.PURPOSE_AND_PARTY,
            payload=PurposePartyPayload(purpose="leisure", adults=2),
            delegated=False,
            memory_scope="propose_profile_update",
            client_event_id="evt-7",
            answered_at=NOW,
        )


def test_memory_scope_profile_update_allowed_for_budget_and_objective() -> None:
    answer = InterviewAnswer(
        question_id=QuestionId.BUDGET_AND_OBJECTIVE,
        payload=BudgetObjectivePayload(
            budget_minor=500_000,
            currency="INR",
            travel_style="balanced",
            objective="balanced",
            points_priority="best_value",
        ),
        delegated=False,
        memory_scope="propose_profile_update",
        client_event_id="evt-8",
        answered_at=NOW,
    )
    assert answer.memory_scope == "propose_profile_update"


def test_memory_scope_profile_update_rejected_for_adaptive_detail() -> None:
    with pytest.raises(ValidationError):
        InterviewAnswer(
            question_id=QuestionId.CELEBRATION_DETAILS,
            payload=AdaptiveDetailPayload(detail="milestone birthday"),
            delegated=False,
            memory_scope="propose_profile_update",
            client_event_id="evt-9",
            answered_at=NOW,
        )
