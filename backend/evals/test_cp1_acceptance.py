"""CP1 end-to-end acceptance: one real conversational-planning session, start
to a confirmed, persisted, reopened ``TripBrief`` (task 7).

This is deliberately not another unit test of ``planning.policy`` or
``planning.brief`` -- those already have deep focused coverage in
``test_cp1_policy.py`` and ``test_cp1_brief.py``. This test proves the whole
CP1 stack composes: a real temporary SQLite-backed ``AccountStore``, a real
user, a real wallet, a full interview driven exclusively through the public
``planning.policy``/``planning.brief``/``planning.repository`` surface, a
persisted-and-reopened database, and a byte-identical confirmed brief on the
other side.

The persona below is deliberately exact (see
``.superpowers/sdd/2026-08-21-cp1-conversational-domain/task-7-brief.md``):
its answers are chosen so that exactly three of the seven adaptive
predicates in ``planning.policy._adaptive_applicable`` fire --
``celebration_details``, ``points_strategy``, and ``food_depth`` -- and no
others:

- ``celebration_details`` fires because purpose is ``"celebration"``.
- ``children_needs`` does NOT fire: no children (``children_ages=[]``).
- ``mobility_details`` does NOT fire: ``hard_constraints`` carries no
  accessibility needs (``has_constraints=False``, every list empty).
- ``points_strategy`` fires because the wallet has a positive points balance
  and ``points_priority="best_value"`` (not ``"save_points"``).
- ``flight_tradeoff`` does NOT fire: ``max_stops=1`` is not ``None``.
- ``hotel_tradeoff`` does NOT fire: ``location_price_tradeoff="location"``,
  not ``"balanced"``.
- ``food_depth`` fires because ``food_interests`` is non-empty.

8 core + 3 adaptive = 11 decisions, asserted exactly (not merely bounded by
the 8-12 range) so a future catalog or predicate change cannot silently drop
or add coverage without failing this test.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

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
from planning.brief import assemble_trip_brief, confirm_trip_brief
from planning.contracts import PlanningSession, PlanningSessionStatus, TravelerHomeContext
from planning.policy import record_answer, record_assistant_suggestions, start_interview
from planning.repository import PlanningSessionRepository

NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
EXPIRES_AT = NOW + timedelta(days=30)
CONFIRM_NOW = NOW + timedelta(minutes=20)

USER_ID = "traveler-1"
SESSION_ID = "acceptance-session-1"


def _answer(
    question_id: QuestionId,
    payload: object,
    *,
    event_id: str,
) -> InterviewAnswer:
    return InterviewAnswer(
        question_id=question_id,
        payload=payload,  # type: ignore[arg-type]
        delegated=False,
        memory_scope="trip_only",
        client_event_id=event_id,
        answered_at=NOW,
    )


def test_full_interview_persists_and_reopens_to_a_byte_identical_confirmed_brief(
    tmp_path: Path,
) -> None:
    # -- 1. Real temporary SQLite-backed AccountStore + real user -------------
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    store.create_user(email="traveler@example.com", now=NOW, user_id=USER_ID)
    repository = PlanningSessionRepository(store)

    # -- 2. Wallet: one card, a positive HDFC points balance -------------------
    wallet = UserWallet(card_ids=["hdfc-infinia"], points_balances={"hdfc-reward-points": 75_000})
    home = TravelerHomeContext(home_country="IN", home_currency="INR", default_origin="DEL")

    # -- 3. Start the interview and persist the brand-new session -------------
    session: PlanningSession = start_interview(
        user_id=USER_ID,
        session_id=SESSION_ID,
        home=home,
        wallet=wallet,
        profile_defaults=None,
        now=NOW,
        expires_at=EXPIRES_AT,
    )
    assert session.version == 0
    repository.create(session)

    # -- 4. Answer all 8 core questions with the exact calibrated persona -----
    core_steps: list[tuple[QuestionId, object]] = [
        (
            QuestionId.TRIP_ESSENTIALS,
            TripEssentialsPayload(
                origin="DEL",
                destination="SIN",
                start_date=date(2026, 11, 10),
                end_date=date(2026, 11, 14),
                travelers=2,
            ),
        ),
        (
            QuestionId.PURPOSE_AND_PARTY,
            PurposePartyPayload(purpose="celebration", adults=2, children_ages=[]),
        ),
        (
            QuestionId.BUDGET_AND_OBJECTIVE,
            BudgetObjectivePayload(
                currency="INR",
                travel_style="balanced",
                objective="balanced",
                points_priority="best_value",
            ),
        ),
        (
            QuestionId.FLIGHT_PREFERENCES,
            FlightPreferencesPayload(cabin="economy", max_stops=1, schedule="no_preference"),
        ),
        (
            QuestionId.STAY_PREFERENCES,
            StayPreferencesPayload(location_price_tradeoff="location"),
        ),
        (
            QuestionId.DAILY_RHYTHM,
            DailyRhythmPayload(
                pace="moderate",
                day_start="normal",
                evening_style="flexible",
                day_trip_appetite="one",
            ),
        ),
        (
            QuestionId.EXPERIENCES_AND_FOOD,
            ExperiencesFoodPayload(
                interests=["food", "culture"],
                food_interests=["hawker centres"],
                iconic_local_balance="balanced",
            ),
        ),
        (
            QuestionId.HARD_CONSTRAINTS,
            HardConstraintsPayload(has_constraints=False),
        ),
    ]

    for index, (question_id, payload) in enumerate(core_steps):
        assert session.current_question_id == question_id
        prior_version = session.version
        session = record_answer(
            session,
            _answer(question_id, payload, event_id=f"core-{index}"),
            expected_version=prior_version,
            now=NOW,
        )
        repository.save(session, expected_version=prior_version)

    assert session.status == PlanningSessionStatus.AWAITING_ASSISTANT
    assert len(session.answers) == 8

    # -- 5. Honest, zero-call, degraded assistant result -----------------------
    # This activates the deterministic adaptive-applicability rules without
    # pretending CP1 invoked an LLM (it did not -- CP1 has no LLM call site).
    prior_version = session.version
    session = record_assistant_suggestions(
        session,
        [],
        assistance_status="degraded",
        llm_calls=0,
        expected_version=prior_version,
        now=NOW,
    )
    repository.save(session, expected_version=prior_version)

    assert session.status == PlanningSessionStatus.INTERVIEWING
    # Exactly the three calibrated adaptive branches, in catalog-priority order.
    assert session.suggested_question_ids == [
        QuestionId.CELEBRATION_DETAILS,
        QuestionId.POINTS_STRATEGY,
        QuestionId.FOOD_DEPTH,
    ]

    # -- 6. Answer the three adaptive questions the persona was calibrated for -
    adaptive_steps: list[tuple[QuestionId, str]] = [
        (QuestionId.CELEBRATION_DETAILS, "A small anniversary dinner would be lovely."),
        (QuestionId.POINTS_STRATEGY, "Use HDFC points where they clearly beat cash."),
        (QuestionId.FOOD_DEPTH, "Go deep on hawker centres, plus a couple of iconic spots."),
    ]
    for index, (question_id, detail) in enumerate(adaptive_steps):
        assert session.current_question_id == question_id
        prior_version = session.version
        session = record_answer(
            session,
            _answer(
                question_id,
                AdaptiveDetailPayload(detail=detail),
                event_id=f"adaptive-{index}",
            ),
            expected_version=prior_version,
            now=NOW,
        )
        repository.save(session, expected_version=prior_version)

    assert session.status == PlanningSessionStatus.REVIEWING
    assert session.current_question_id is None
    # The load-bearing count: exactly 11, not merely `<= 12`.
    assert len(session.answers) == 11

    # -- 7. Assemble and confirm the Trip Brief ---------------------------------
    brief = assemble_trip_brief(session)
    assert set(brief.adaptive_details) == {
        QuestionId.CELEBRATION_DETAILS,
        QuestionId.POINTS_STRATEGY,
        QuestionId.FOOD_DEPTH,
    }
    assert brief.delegated_questions == []

    prior_version = session.version
    confirmed = confirm_trip_brief(
        session, brief, expected_version=prior_version, now=CONFIRM_NOW
    )
    repository.save(confirmed, expected_version=prior_version)

    assert confirmed.status == PlanningSessionStatus.CONFIRMED
    assert len(confirmed.confirmed_briefs) == 1
    assert confirmed.confirmed_briefs[0].revision == 1
    assert confirmed.confirmed_briefs[0].brief.model_dump_json() == brief.model_dump_json()

    # -- 8. Reopen a genuinely new AccountStore against the same SQLite file ---
    reopened_store = AccountStore.open(db_path)
    reopened_repository = PlanningSessionRepository(reopened_store)
    fetched = reopened_repository.get(user_id=USER_ID, session_id=SESSION_ID)

    assert fetched is not None
    assert fetched == confirmed
    assert len(fetched.answers) == 11
    assert fetched.confirmed_briefs[0].revision == 1
    assert fetched.confirmed_briefs[0].brief.model_dump_json() == brief.model_dump_json()
