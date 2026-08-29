"""Authenticated CP2 conversational planning API.

This module is deliberately a thin HTTP adapter around the pure CP1 planning
domain.  It owns no provider discovery and makes no LLM call.  In particular,
the only transition that starts the legacy planner is an explicit, successful
confirmation of a server-assembled Trip Brief.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from accounts.models import (
    ConstraintPreferences,
    ExperiencePreferences,
    FlightPreferences,
    OptimizationPreferences,
    RhythmPreferences,
    StayPreferences,
    TravelPreferenceProfile,
    User,
)
from accounts.projection import build_user_wallet
from accounts.store import AccountStore, StalePlanningSessionError
from agents.models import TripIntakeRequest
from api.auth import current_user, get_store, now_utc, require_csrf
from core.models import UserWallet
from planning.answers import (
    AnswerPayload,
    InterviewAnswer,
    QuestionId,
)
from planning.brief import (
    BriefAlreadyConfirmedError,
    BriefMismatchError,
    BriefNotReadyError,
    assemble_trip_brief,
    confirm_trip_brief,
)
from planning.contracts import (
    ConversationEvent,
    PlanningSession,
    PlanningSessionStatus,
    ProfileUpdateProposal,
    TravelerHomeContext,
    TripBrief,
)
from planning.policy import (
    DelegationNotAllowedError,
    PlanningPolicyError,
    StaleSessionVersionError,
    UnexpectedQuestionError,
    interview_progress,
    next_question,
    record_answer,
    record_assistant_suggestions,
    start_interview,
)
from planning.question_catalog import QuestionDefinition
from planning.repository import PlanningSessionRepository

router = APIRouter(prefix="/planning", tags=["planning"])
_CONFIRM_LOCKS: dict[str, threading.Lock] = {}
_CONFIRM_LOCKS_GUARD = threading.Lock()


class ErrorOut(BaseModel):
    code: str
    message: str


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    expected_version: int = Field(ge=0)
    payload: AnswerPayload | None = None
    delegated: bool = False
    memory_scope: Literal["trip_only", "propose_profile_update"] = "trip_only"
    client_event_id: str = Field(min_length=1, max_length=128)


class SkipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    expected_version: int = Field(ge=0)
    client_event_id: str = Field(min_length=1, max_length=128)


class AmendRequest(AnswerRequest):
    expected_version: int = Field(ge=0)


class VersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)


class ConfirmRequest(VersionRequest):
    brief: TripBrief
    client_event_id: str = Field(min_length=1, max_length=128)


class PreferencePatch(BaseModel):
    """Partial group replacement. Unspecified groups are preserved."""

    model_config = ConfigDict(extra="forbid")
    flight: FlightPreferences | None = None
    stay: StayPreferences | None = None
    rhythm: RhythmPreferences | None = None
    experiences: ExperiencePreferences | None = None
    constraints: ConstraintPreferences | None = None
    optimization: OptimizationPreferences | None = None


class QuestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: QuestionId
    prompt: str
    phase: str
    answer_kind: str
    required: bool
    allow_delegate: bool
    control: dict[str, Any]


class ProgressOut(BaseModel):
    completed: int
    minimum_total: int
    maximum_total: int
    status: PlanningSessionStatus


class SessionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    user_id: str
    status: PlanningSessionStatus
    version: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    current_question: QuestionOut | None
    suggested_question_ids: list[QuestionId]
    progress: ProgressOut
    answers: dict[QuestionId, InterviewAnswer]
    events: list[ConversationEvent]
    assistance_status: str
    pending_profile_updates: list[ProfileUpdateProposal]
    brief: TripBrief | None = None
    planning_job_id: str | None = None


class PreferenceOut(BaseModel):
    profile: TravelPreferenceProfile


class ConfirmOut(SessionOut):
    job_id: str


PreferenceSection = Literal[
    "flight", "stay", "rhythm", "experiences", "constraints", "optimization"
]


def _question_out(definition: QuestionDefinition | None) -> QuestionOut | None:
    if definition is None:
        return None
    # Controls are declarative and closed; the client renders them without
    # parsing assistant prose. Option vocabularies remain in the typed payload
    # models and are intentionally not duplicated as business logic here.
    option_sets: dict[str, list[dict[str, str]]] = {
        "purpose_party": [
            {"value": value, "label": label}
            for value, label in (
                ("leisure", "Leisure"),
                ("work", "Work"),
                ("celebration", "Celebration"),
                ("family", "Family"),
                ("mixed", "A mix"),
            )
        ],
        "budget_objective": [
            {"value": value, "label": label}
            for value, label in (
                ("lowest_cash", "Lowest cash"),
                ("highest_value", "Best value"),
                ("convenience", "Convenience"),
                ("balanced", "Balanced"),
            )
        ],
        "flight": [
            {"value": value, "label": label}
            for value, label in (
                ("economy", "Economy"),
                ("premium_economy", "Premium economy"),
                ("business", "Business"),
                ("first", "First"),
                ("no_preference", "No preference"),
            )
        ],
        "stay": [
            {"value": value, "label": label}
            for value, label in (
                ("location", "Location first"),
                ("price", "Price first"),
                ("balanced", "Balanced"),
                ("no_preference", "No preference"),
            )
        ],
        "rhythm": [
            {"value": value, "label": label}
            for value, label in (
                ("relaxed", "Relaxed"),
                ("moderate", "Moderate"),
                ("packed", "Packed"),
                ("no_preference", "No preference"),
            )
        ],
        "experiences_food": [
            {"value": value, "label": label}
            for value, label in (
                ("iconic", "Iconic highlights"),
                ("balanced", "A mix"),
                ("local", "Local and hidden"),
                ("no_preference", "No preference"),
            )
        ],
    }
    control: dict[str, Any] = {
        "type": definition.answer_kind,
        "allow_skip": definition.allow_delegate,
        "options": option_sets.get(definition.answer_kind, []),
    }
    if definition.answer_kind == "trip_essentials":
        control.update(
            {
                "type": "trip_essentials",
                "fields": ["origin", "destination", "start_date", "end_date", "travelers"],
                "allow_skip": False,
            }
        )
    elif definition.answer_kind == "hard_constraints":
        control.update(
            {
                "type": "hard_constraints",
                "fields": ["dietary", "accessibility", "exclusions", "immovable_events"],
                "allow_skip": False,
            }
        )
    elif definition.answer_kind == "adaptive_detail":
        control.update({"type": "text", "allow_skip": definition.allow_delegate})
    return QuestionOut(
        id=definition.id,
        prompt=definition.prompt,
        phase=definition.phase,
        answer_kind=definition.answer_kind,
        required=definition.required,
        allow_delegate=definition.allow_delegate,
        control=control,
    )


def _session_out(session: PlanningSession) -> SessionOut:
    brief: TripBrief | None = None
    if session.status is PlanningSessionStatus.REVIEWING:
        brief = assemble_trip_brief(session)
    elif session.confirmed_briefs:
        brief = session.confirmed_briefs[-1].brief
    progress = interview_progress(session)
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        version=session.version,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
        current_question=_question_out(next_question(session)),
        suggested_question_ids=session.suggested_question_ids,
        progress=ProgressOut(**progress.model_dump()),
        answers=session.answers,
        events=session.events,
        assistance_status=session.assistance_status.value,
        pending_profile_updates=session.pending_profile_updates,
        brief=brief,
        planning_job_id=session.planning_job_id,
    )


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _repo(store: AccountStore) -> PlanningSessionRepository:
    return PlanningSessionRepository(store)


def _get_session(repo: PlanningSessionRepository, user: User, session_id: str) -> PlanningSession:
    session = repo.get(user_id=user.id, session_id=session_id)
    if session is None:
        raise _error(404, "SESSION_NOT_FOUND", "Planning session not found")
    if session.expires_at <= now_utc() and session.saved_trip_id is None:
        raise _error(410, "SESSION_EXPIRED", "Planning session has expired")
    return session


def _append_event(
    session: PlanningSession,
    *,
    event_id: str,
    kind: Literal[
        "assistant_question",
        "user_answer",
        "assistant_acknowledgement",
        "brief_review",
        "system_progress",
        "error",
    ],
    text: str,
    now: datetime,
    question_id: QuestionId | None = None,
) -> PlanningSession:
    if any(event.id == event_id for event in session.events):
        return session
    candidate = session.model_copy(
        update={
            "events": [
                *session.events,
                ConversationEvent(
                    id=event_id,
                    kind=kind,
                    text=text,
                    question_id=question_id,
                    created_at=now,
                ),
            ]
        }
    )
    return PlanningSession.model_validate(candidate.model_dump())


def _profile_for_user(
    store: AccountStore, user: User
) -> tuple[TravelerHomeContext, TravelPreferenceProfile | None, UserWallet]:
    profile = store.get_profile(user.id)
    preferences = store.get_travel_preferences(user.id)
    entries = store.wallet_entries(user.id)
    wallet = build_user_wallet(entries)
    if profile is None:
        return TravelerHomeContext(home_country="IN", home_currency="INR"), preferences, wallet
    return (
        TravelerHomeContext(
            home_country=profile.home_country,
            home_currency=profile.home_currency,
            default_origin=profile.origin_city,
        ),
        preferences,
        wallet,
    )


@router.get("/preferences", response_model=PreferenceOut)
def get_preferences(
    user: Annotated[User, Depends(current_user)], store: Annotated[AccountStore, Depends(get_store)]
) -> PreferenceOut:
    profile = store.get_travel_preferences(user.id)
    if profile is None:
        now = now_utc()
        profile = TravelPreferenceProfile(user_id=user.id, updated_at=now)
    return PreferenceOut(profile=profile)


@router.patch("/preferences", response_model=PreferenceOut)
def patch_preferences(
    body: PreferencePatch,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> PreferenceOut:
    require_csrf(request)
    existing = store.get_travel_preferences(user.id)
    now = now_utc()
    if existing is None:
        existing = TravelPreferenceProfile(user_id=user.id, updated_at=now)
    # Use model instances, not ``model_dump`` dictionaries, so Pydantic's
    # nested validators remain authoritative during the replacement.
    updates = {name: getattr(body, name) for name in body.model_fields_set}
    candidate = existing.model_copy(update={**updates, "updated_at": now})
    profile = TravelPreferenceProfile.model_validate(candidate.model_dump())
    store.put_travel_preferences(profile)
    return PreferenceOut(profile=profile)


@router.put("/preferences", response_model=PreferenceOut)
def replace_preferences(
    body: TravelPreferenceProfile,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> PreferenceOut:
    require_csrf(request)
    if body.user_id != user.id:
        raise _error(403, "USER_SCOPE", "Preference profile belongs to another user")
    profile = body.model_copy(update={"updated_at": now_utc()})
    store.put_travel_preferences(profile)
    return PreferenceOut(profile=profile)


@router.delete("/preferences/{section}", response_model=PreferenceOut)
def remove_preferences(
    section: PreferenceSection,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> PreferenceOut:
    """Explicitly remove one durable preference group; never an implicit reset."""
    require_csrf(request)
    existing = store.get_travel_preferences(user.id)
    now = now_utc()
    if existing is None:
        existing = TravelPreferenceProfile(user_id=user.id, updated_at=now)
    empty_groups: dict[str, Any] = {
        "flight": FlightPreferences(),
        "stay": StayPreferences(),
        "rhythm": RhythmPreferences(),
        "experiences": ExperiencePreferences(),
        "constraints": ConstraintPreferences(),
        "optimization": OptimizationPreferences(),
    }
    candidate = existing.model_copy(update={section: empty_groups[section], "updated_at": now})
    profile = TravelPreferenceProfile.model_validate(candidate.model_dump())
    store.put_travel_preferences(profile)
    return PreferenceOut(profile=profile)


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    require_csrf(request)
    home, preferences, wallet = _profile_for_user(store, user)
    now = now_utc()
    session = start_interview(
        user_id=user.id,
        session_id=uuid4().hex,
        home=home,
        wallet=wallet,
        profile_defaults=preferences,
        now=now,
        expires_at=now + timedelta(days=30),
    )
    first_question = next_question(session)
    session = _append_event(
        session,
        event_id=f"{session.id}:question:0",
        kind="assistant_question",
        question_id=session.current_question_id,
        text=first_question.prompt if first_question is not None else "Let's plan your trip.",
        now=now,
    )
    _repo(store).create(session)
    return _session_out(session)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def read_session(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    return _session_out(_get_session(_repo(store), user, session_id))


def _apply_answer(
    session: PlanningSession,
    body: AnswerRequest,
    *,
    now: datetime,
) -> PlanningSession:
    answer = InterviewAnswer(
        question_id=body.question_id,
        payload=body.payload,
        delegated=body.delegated,
        memory_scope=body.memory_scope,
        client_event_id=body.client_event_id,
        answered_at=now,
    )
    updated = record_answer(session, answer, expected_version=body.expected_version, now=now)
    updated = _append_event(
        updated,
        event_id=f"event:{body.client_event_id}",
        kind="user_answer",
        question_id=body.question_id,
        text="Answer recorded.",
        now=now,
    )
    if updated.current_question_id is not None:
        definition = next_question(updated)
        if definition is None:
            raise PlanningPolicyError("current question is missing from catalog")
        updated = _append_event(
            updated,
            event_id=f"{updated.id}:question:{updated.version}",
            kind="assistant_question",
            question_id=updated.current_question_id,
            text=definition.prompt,
            now=now,
        )
    return updated


@router.post("/sessions/{session_id}/answers", response_model=SessionOut)
def answer_session(
    session_id: str,
    body: AnswerRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    require_csrf(request)
    repo = _repo(store)
    session = _get_session(repo, user, session_id)
    if body.client_event_id in session.processed_event_ids:
        return _session_out(session)
    try:
        updated = _apply_answer(session, body, now=now_utc())
        repo.save(updated, expected_version=session.version)
        # CP2 deliberately has no interview LLM call.  At the CP1 assistant
        # seam, record a truthful degraded result and let deterministic catalog
        # predicates add only applicable adaptive questions.
        if updated.status is PlanningSessionStatus.AWAITING_ASSISTANT:
            assistant_now = now_utc()
            updated = record_assistant_suggestions(
                updated,
                [],
                assistance_status="degraded",
                llm_calls=0,
                expected_version=updated.version,
                now=assistant_now,
            )
            repo.save(updated, expected_version=updated.version - 1)
    except (StaleSessionVersionError, StalePlanningSessionError) as exc:
        raise _error(409, "STALE_SESSION", str(exc)) from None
    except (UnexpectedQuestionError, DelegationNotAllowedError, PlanningPolicyError) as exc:
        raise _error(422, "INVALID_ANSWER", str(exc)) from None
    return _session_out(updated)


@router.post("/sessions/{session_id}/skip", response_model=SessionOut)
def skip_session(
    session_id: str,
    body: SkipRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    require_csrf(request)
    body_as_answer = AnswerRequest(
        question_id=body.question_id,
        expected_version=body.expected_version,
        delegated=True,
        client_event_id=body.client_event_id,
    )
    return answer_session(session_id, body_as_answer, request, user, store)


@router.post("/sessions/{session_id}/amend", response_model=SessionOut)
def amend_session(
    session_id: str,
    body: AmendRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    require_csrf(request)
    repo = _repo(store)
    session = _get_session(repo, user, session_id)
    if session.status is not PlanningSessionStatus.REVIEWING:
        raise _error(409, "NOT_REVIEWING", "Only a reviewable session can be amended")
    if body.expected_version != session.version:
        raise _error(409, "STALE_SESSION", "Session version is stale")
    try:
        answer = InterviewAnswer(
            question_id=body.question_id,
            payload=body.payload,
            delegated=body.delegated,
            memory_scope=body.memory_scope,
            client_event_id=body.client_event_id,
            answered_at=now_utc(),
        )
        if body.question_id not in session.answers:
            raise PlanningPolicyError("cannot amend an unanswered question")
        updated = session.model_copy(
            update={
                "answers": {**session.answers, body.question_id: answer},
                "processed_event_ids": [*session.processed_event_ids, body.client_event_id],
                "version": session.version + 1,
                "updated_at": now_utc(),
            }
        )
        updated = PlanningSession.model_validate(updated.model_dump())
        repo.save(updated, expected_version=session.version)
    except StalePlanningSessionError as exc:
        raise _error(409, "STALE_SESSION", str(exc)) from None
    except PlanningPolicyError as exc:
        raise _error(422, "INVALID_AMENDMENT", str(exc)) from None
    return _session_out(updated)


@router.post(
    "/sessions/{session_id}/profile-updates/{proposal_id}/approve", response_model=SessionOut
)
def approve_profile_update(
    session_id: str,
    proposal_id: str,
    body: VersionRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    require_csrf(request)
    repo = _repo(store)
    session = _get_session(repo, user, session_id)
    if body.expected_version != session.version:
        raise _error(409, "STALE_SESSION", "Session version is stale")
    proposal = next(
        (p for p in session.pending_profile_updates if p.proposal_id == proposal_id), None
    )
    if proposal is None:
        raise _error(404, "PROPOSAL_NOT_FOUND", "Profile update proposal not found")
    # Persist only after an explicit user action.  A failed profile write
    # raises before the trip/session answer is changed.
    store.put_travel_preferences(proposal.candidate_profile)
    updated = session.model_copy(
        update={
            "pending_profile_updates": [
                p for p in session.pending_profile_updates if p.proposal_id != proposal_id
            ],
            "version": session.version + 1,
            "updated_at": now_utc(),
        }
    )
    updated = PlanningSession.model_validate(updated.model_dump())
    try:
        repo.save(updated, expected_version=session.version)
    except StalePlanningSessionError as exc:
        raise _error(409, "STALE_SESSION", str(exc)) from None
    return _session_out(updated)


@router.get("/sessions/{session_id}/review", response_model=SessionOut)
def review_session(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SessionOut:
    session = _get_session(_repo(store), user, session_id)
    if session.status is not PlanningSessionStatus.REVIEWING:
        raise _error(409, "NOT_READY", "Session is not ready for review")
    return _session_out(session)


def _start_legacy_job(session: PlanningSession, job_id: str) -> None:
    # Imports are local to avoid api.main <-> this router import cycles.  This
    # is the existing non-live pipeline boundary; no provider is touched here.
    from api.job_manager import job_manager
    from api.main import (
        _run_job,
        get_booking_date,
        get_kb,
        get_llm,
        get_place_registry,
        get_trace_dir,
    )

    kb = get_kb()
    llm = get_llm()
    registry = get_place_registry()
    brief = session.confirmed_briefs[-1].brief
    essentials = brief.trip_essentials
    brief_json = brief.model_dump_json(exclude={"wallet", "home"})
    request = TripIntakeRequest(
        raw_request=(
            f"{essentials.origin} to {essentials.destination} "
            f"{essentials.start_date.isoformat()} to {essentials.end_date.isoformat()} "
            f"for {essentials.travelers} traveler(s); "
            f"confirmed preferences: {brief_json}"
        ),
        wallet=session.wallet,
    )
    # The job manager is process-local in the Kernel MVP.  It is deliberately
    # created before the daemon starts so a client can poll immediately.
    job_manager.create_job(job_id)
    thread = threading.Thread(
        target=_run_job,
        args=(job_id, request, kb, llm, registry, get_booking_date(), get_trace_dir()),
        daemon=True,
    )
    thread.start()


@router.post("/sessions/{session_id}/confirm", response_model=ConfirmOut, status_code=202)
def confirm_session(
    session_id: str,
    body: ConfirmRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> ConfirmOut:
    require_csrf(request)
    repo = _repo(store)
    with _CONFIRM_LOCKS_GUARD:
        lock = _CONFIRM_LOCKS.setdefault(session_id, threading.Lock())
    with lock:
        session = _get_session(repo, user, session_id)
        if session.planning_job_id is not None:
            return ConfirmOut(**_session_out(session).model_dump(), job_id=session.planning_job_id)
        if body.client_event_id in session.processed_event_ids and session.confirmed_briefs:
            raise _error(409, "CONFIRMATION_IN_PROGRESS", "Confirmation is already being processed")
        try:
            confirmed = confirm_trip_brief(
                session,
                body.brief,
                expected_version=body.expected_version,
                now=now_utc(),
            )
            job_id = uuid4().hex
            confirmed = confirmed.model_copy(
                update={
                    "status": PlanningSessionStatus.PLANNING,
                    "planning_job_id": job_id,
                    "processed_event_ids": [*confirmed.processed_event_ids, body.client_event_id],
                    "updated_at": now_utc(),
                    "events": [
                        *confirmed.events,
                        ConversationEvent(
                            id=f"event:{body.client_event_id}",
                            kind="system_progress",
                            text="Trip confirmed. Planning has started.",
                            created_at=now_utc(),
                        ),
                    ],
                }
            )
            confirmed = PlanningSession.model_validate(confirmed.model_dump())
            repo.save(confirmed, expected_version=session.version)
        except (BriefNotReadyError, BriefMismatchError) as exc:
            raise _error(422, "BRIEF_NOT_READY", str(exc)) from None
        except BriefAlreadyConfirmedError as exc:
            raise _error(409, "ALREADY_CONFIRMED", str(exc)) from None
        except StaleSessionVersionError as exc:
            raise _error(409, "STALE_SESSION", str(exc)) from None
        except StalePlanningSessionError as exc:
            raise _error(409, "STALE_SESSION", str(exc)) from None
        _start_legacy_job(confirmed, job_id)
        return ConfirmOut(**_session_out(confirmed).model_dump(), job_id=job_id)


@router.get("/sessions/{session_id}/job", response_model=dict[str, Any])
def session_job(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> dict[str, Any]:
    session = _get_session(_repo(store), user, session_id)
    if session.planning_job_id is None:
        raise _error(404, "JOB_NOT_STARTED", "Planning has not started")
    from api.job_manager import job_manager

    state = job_manager.get_job(session.planning_job_id)
    if state is None:
        return {"job_id": session.planning_job_id, "status": "queued"}
    return state.to_status(session.planning_job_id).model_dump()
