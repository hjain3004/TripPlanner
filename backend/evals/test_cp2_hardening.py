"""CP2.1 regression tests for server-owned transitions and closed contracts."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from accounts.models import TravelPreferenceProfile
from core.models import UserWallet
from planning.answers import (
    FlightPreferencesPayload,
    HardConstraintsPayload,
    InterviewAnswer,
    PurposePartyPayload,
    QuestionId,
    TripEssentialsPayload,
)
from planning.brief import build_profile_update_proposals
from planning.contracts import PlanningSessionStatus, TravelerHomeContext
from planning.policy import (
    BackNavigationError,
    amend_answer,
    go_back,
    record_answer,
    start_interview,
)

NOW = datetime(2026, 8, 29, tzinfo=UTC)


def _session():
    return start_interview(
        user_id="u1",
        session_id="s1",
        home=TravelerHomeContext(home_country="IN", home_currency="INR", default_origin="DEL"),
        wallet=UserWallet(card_ids=[], points_balances={}),
        profile_defaults=None,
        now=NOW,
        expires_at=NOW + timedelta(days=30),
    )


def _answer(question_id: QuestionId, payload: object, event: str) -> InterviewAnswer:
    return InterviewAnswer(
        question_id=question_id,
        payload=payload,  # type: ignore[arg-type]
        client_event_id=event,
        answered_at=NOW,
    )


def test_go_back_is_server_owned_and_versioned() -> None:
    session = _session()
    essentials = _answer(
        QuestionId.TRIP_ESSENTIALS,
        TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 5),
            travelers=1,
        ),
        "e1",
    )
    session = record_answer(session, essentials, expected_version=0, now=NOW)
    session = record_answer(
        session,
        _answer(
            QuestionId.PURPOSE_AND_PARTY,
            PurposePartyPayload(purpose="leisure", adults=1),
            "e2",
        ),
        expected_version=1,
        now=NOW + timedelta(seconds=1),
    )
    back = go_back(session, expected_version=2, now=NOW + timedelta(seconds=2))
    assert back.status is PlanningSessionStatus.INTERVIEWING
    assert back.current_question_id is QuestionId.PURPOSE_AND_PARTY
    assert QuestionId.PURPOSE_AND_PARTY not in back.answers
    assert back.version == 3
    with pytest.raises(BackNavigationError):
        go_back(_session(), expected_version=0, now=NOW)


def test_amend_validates_structured_core_answers_and_preserves_snapshot_boundary() -> None:
    session = _session()
    # A review-like handoff with all core answers is assembled by the policy
    # itself; this test focuses on the typed replacement boundary.
    session = session.model_copy(
        update={
            "status": PlanningSessionStatus.REVIEWING,
            "answers": {
                QuestionId.TRIP_ESSENTIALS: _answer(
                    QuestionId.TRIP_ESSENTIALS,
                    TripEssentialsPayload(
                        origin="DEL",
                        destination="SIN",
                        start_date=date(2026, 11, 1),
                        end_date=date(2026, 11, 5),
                        travelers=2,
                    ),
                    "e1",
                ),
                QuestionId.HARD_CONSTRAINTS: _answer(
                    QuestionId.HARD_CONSTRAINTS,
                    HardConstraintsPayload(has_constraints=False),
                    "e2",
                ),
            },
            "version": 2,
        }
    )
    session = type(session).model_validate(session.model_dump())
    replacement = _answer(
        QuestionId.TRIP_ESSENTIALS,
        TripEssentialsPayload(
            origin="BOM",
            destination="SIN",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 5),
            travelers=2,
        ),
        "amend-1",
    )
    amended = amend_answer(session, replacement, expected_version=2, now=NOW + timedelta(seconds=1))
    assert amended.answers[QuestionId.TRIP_ESSENTIALS].payload.origin == "BOM"  # type: ignore[union-attr]
    assert amended.confirmed_briefs == []
    assert amended.version == 3


def test_no_preference_profile_proposal_is_omitted_instead_of_wiping_group() -> None:
    from accounts.models import FlightPreferences, PreferenceValue

    existing = TravelPreferenceProfile(
        user_id="u1",
        updated_at=NOW,
        flight=FlightPreferences(
            cabin=PreferenceValue(value="business", source="user_profile_edit", updated_at=NOW)
        ),
    )
    session = _session().model_copy(
        update={
            "profile_defaults": TravelPreferenceProfile.model_validate(existing.model_dump()),
            "answers": {
                QuestionId.FLIGHT_PREFERENCES: _answer(
                    QuestionId.FLIGHT_PREFERENCES,
                    FlightPreferencesPayload(
                        cabin="no_preference",
                        max_stops=None,
                        schedule="no_preference",
                        seat="no_preference",
                    ),
                    "f1",
                )
            },
        }
    )
    proposals = build_profile_update_proposals(session, now=NOW)
    assert proposals == []


def test_question_control_schema_is_discriminated_and_not_untyped_mapping() -> None:
    from api.conversation import QuestionOut

    schema = QuestionOut.model_json_schema()
    control = schema["properties"]["control"]
    assert control["discriminator"]["propertyName"] == "type"
    assert "oneOf" in control


def test_gondola_mcp_camel_case_aliases_are_unwrapped() -> None:
    from types import SimpleNamespace

    from gateway.travel.adapters.gondola.mcp_client import LiveGondolaTransport

    transport = LiveGondolaTransport(
        base_url="https://mcp.gondola.ai",
        get_access_token=lambda: None,
    )
    result = SimpleNamespace(isError=False, structuredContent={"result": {"ok": True}})
    assert transport._unwrap_tool_result(result) == {"result": {"ok": True}}
