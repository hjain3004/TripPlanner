"""Authenticated CP2 conversational planning API.

This module is a thin HTTP adapter around the pure planning domain and the
bounded CP3 assistant service. It owns no provider discovery. In particular,
the only transition that starts the legacy planner is an explicit, successful
confirmation of a server-assembled Trip Brief.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
from agents.interview_assistant import INTERPRETABLE_QUESTIONS, get_interview_llm
from agents.llm import LLMClient
from agents.models import FinalReport, PlanJobStatus
from agents.pipeline import build_region_capability
from api.auth import current_user, get_store, now_utc, require_csrf
from api.interview_assistance import (
    AssistanceIdempotencyConflict,
    AssistanceInProgress,
    fingerprint,
    interpret_answer,
    recover_interrupted_requests,
    run_adaptive_review,
)
from core.models import UserWallet
from core.trip_models import ItineraryEdit
from planning.answers import (
    AnswerPayload,
    InterviewAnswer,
    QuestionId,
)
from planning.assistance import AnswerCandidate, AssistanceDiagnostic, InterviewContradiction
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
    BackNavigationError,
    DelegationNotAllowedError,
    PlanningPolicyError,
    StaleSessionVersionError,
    UnexpectedQuestionError,
    amend_answer,
    go_back,
    interview_progress,
    next_question,
    record_answer,
    start_interview,
)
from planning.question_catalog import DEFAULT_QUESTION_CATALOG, QuestionDefinition
from planning.repository import PlanningSessionRepository

router = APIRouter(prefix="/planning", tags=["planning"])


class _ConfirmLockEntry:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.references = 0


_CONFIRM_LOCKS: dict[str, _ConfirmLockEntry] = {}
_CONFIRM_LOCKS_GUARD = threading.Lock()
_MAX_CONFIRM_LOCKS = 1024
_PREFERENCES_LOCK = threading.Lock()


@contextmanager
def _confirmation_guard(session_id: str) -> Iterator[None]:
    with _CONFIRM_LOCKS_GUARD:
        entry = _CONFIRM_LOCKS.setdefault(session_id, _ConfirmLockEntry())
        entry.references += 1
        # Waiting callers count as references too. Eviction therefore cannot
        # create two locks for one session id while a waiter holds an old ref.
        if len(_CONFIRM_LOCKS) > _MAX_CONFIRM_LOCKS:
            for key, candidate in list(_CONFIRM_LOCKS.items()):
                if key != session_id and candidate.references == 0:
                    del _CONFIRM_LOCKS[key]
                    if len(_CONFIRM_LOCKS) <= _MAX_CONFIRM_LOCKS:
                        break
    try:
        with entry.lock:
            yield
    finally:
        with _CONFIRM_LOCKS_GUARD:
            entry.references -= 1
            if entry.references == 0 and len(_CONFIRM_LOCKS) > _MAX_CONFIRM_LOCKS:
                # Opportunistically trim the oldest idle entries. No active or
                # waiting entry is ever removed.
                for key, candidate in list(_CONFIRM_LOCKS.items()):
                    if candidate.references == 0:
                        del _CONFIRM_LOCKS[key]
                        if len(_CONFIRM_LOCKS) <= _MAX_CONFIRM_LOCKS:
                            break


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


class BackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=0)
    client_event_id: str = Field(min_length=1, max_length=128)


class AmendRequest(AnswerRequest):
    expected_version: int = Field(ge=0)


class InterpretRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    expected_version: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=1000)
    client_event_id: str = Field(min_length=1, max_length=128)


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


class ControlOption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    value: str
    label: str


class SelectControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal[
        "purpose_party",
        "budget_objective",
        "flight",
        "stay",
        "rhythm",
        "experiences_food",
    ]
    allow_skip: bool
    options: list[ControlOption]


class TripEssentialsControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["trip_essentials"]
    allow_skip: Literal[False]
    fields: list[
        Literal[
            "origin",
            "destination",
            "start_date",
            "end_date",
            "travelers",
            "date_flexibility_days",
        ]
    ]
    options: list[ControlOption] = Field(default_factory=list)
    optional_fields: list[Literal["date_flexibility_days"]] = Field(default_factory=list)


class HardConstraintsControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["hard_constraints"]
    allow_skip: Literal[False]
    fields: list[
        Literal[
            "has_constraints",
            "dietary",
            "accessibility",
            "exclusions",
            "immovable_events",
        ]
    ]
    options: list[ControlOption] = Field(default_factory=list)


class AdaptiveTextControl(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["text"]
    allow_skip: bool
    options: list[ControlOption] = Field(default_factory=list)


QuestionControl = Annotated[
    SelectControl | TripEssentialsControl | HardConstraintsControl | AdaptiveTextControl,
    Field(discriminator="type"),
]


class QuestionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: QuestionId
    prompt: str
    phase: str
    answer_kind: str
    required: bool
    allow_delegate: bool
    control: QuestionControl


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
    interview_llm_calls: int = 0
    assistance_pending: bool = False
    assistance_diagnostics: list[AssistanceDiagnostic] = Field(default_factory=list)
    pending_answer: AnswerCandidate | None = None
    contradictions: list[InterviewContradiction] = Field(default_factory=list)
    pending_profile_updates: list[ProfileUpdateProposal]
    # The wallet this session will actually plan with. Snapshotted from the
    # account's wallet entries when the session started (A3) -- deliberately
    # the session's copy rather than a live re-read, so the review step shows
    # what confirmation will really use even if the account changed since.
    wallet: UserWallet
    brief: TripBrief | None = None
    planning_job_id: str | None = None
    planning_error: str | None = None
    question_catalog: list[QuestionOut] = Field(default_factory=list)


class PreferenceOut(BaseModel):
    profile: TravelPreferenceProfile


class ConfirmOut(SessionOut):
    job_id: str


class ConfirmedEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    edit: ItineraryEdit
    expected_inventory_revision: int = Field(ge=1)


class ConfirmedProseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_inventory_revision: int = Field(ge=1)


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
    options = [ControlOption(**option) for option in option_sets.get(definition.answer_kind, [])]
    control: QuestionControl
    if definition.answer_kind == "trip_essentials":
        control = TripEssentialsControl(
            type="trip_essentials",
            fields=[
                "origin",
                "destination",
                "start_date",
                "end_date",
                "travelers",
            ],
            allow_skip=False,
            optional_fields=["date_flexibility_days"],
        )
    elif definition.answer_kind == "hard_constraints":
        control = HardConstraintsControl(
            type="hard_constraints",
            fields=[
                "has_constraints",
                "dietary",
                "accessibility",
                "exclusions",
                "immovable_events",
            ],
            allow_skip=False,
        )
    elif definition.answer_kind == "adaptive_detail":
        control = AdaptiveTextControl(type="text", allow_skip=definition.allow_delegate)
    else:
        # Every non-structured answer kind is a closed select control above.
        control = SelectControl(
            type=definition.answer_kind,
            allow_skip=definition.allow_delegate,
            options=options,
        )
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
    catalog: list[QuestionOut] = []
    for definition in DEFAULT_QUESTION_CATALOG:
        rendered = _question_out(definition)
        if rendered is not None:
            catalog.append(rendered)
    current_question = _question_out(next_question(session))
    if current_question and current_question.id in session.personalized_wording:
        current_question = current_question.model_copy(
            update={"prompt": session.personalized_wording[current_question.id]}
        )
    return SessionOut(
        id=session.id,
        user_id=session.user_id,
        status=session.status,
        version=session.version,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
        current_question=current_question,
        suggested_question_ids=session.suggested_question_ids,
        progress=ProgressOut(**progress.model_dump()),
        answers=session.answers,
        events=session.events,
        assistance_status=session.assistance_status.value,
        interview_llm_calls=session.interview_llm_calls,
        assistance_pending=any(
            row.status == "reserved" for row in session.assistance_requests.values()
        ),
        assistance_diagnostics=session.assistance_diagnostics,
        pending_answer=session.pending_answer,
        contradictions=session.contradictions,
        pending_profile_updates=session.pending_profile_updates,
        wallet=session.wallet,
        brief=brief,
        planning_job_id=session.planning_job_id,
        planning_error=session.planning_error,
        question_catalog=catalog,
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
    with _PREFERENCES_LOCK:
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
    with _PREFERENCES_LOCK:
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
    repo = _repo(store)
    session = _get_session(repo, user, session_id)
    # Recovery is deterministic: a reserved/interrupted review never dispatches
    # again. CAS prevents overwriting an in-flight successful result.
    try:
        stalled = now_utc() - session.updated_at >= timedelta(seconds=30)
        recovered = recover_interrupted_requests(repo, session, now_utc())
        if recovered != session:
            stalled = True
        session = recovered
        active = any(row.status == "reserved" for row in session.assistance_requests.values())
        if session.status is PlanningSessionStatus.AWAITING_ASSISTANT and stalled and not active:
            session = run_adaptive_review(repo, session, None, now_utc)
    except (StalePlanningSessionError, AssistanceInProgress):
        session = _get_session(repo, user, session_id)
    return _session_out(session)


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
    updated = updated.model_copy(
        update={
            "pending_answer": None,
            "contradictions": [
                c for c in updated.contradictions if body.question_id not in c.answer_ids
            ],
        }
    )
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
            text=updated.personalized_wording.get(definition.id, definition.prompt),
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
    llm: Annotated[LLMClient, Depends(get_interview_llm)],
) -> SessionOut:
    require_csrf(request)
    repo = _repo(store)
    session = _get_session(repo, user, session_id)
    if body.client_event_id in session.processed_event_ids:
        return _session_out(session)
    if any(row.status == "reserved" for row in session.assistance_requests.values()):
        raise _error(409, "ASSISTANCE_IN_PROGRESS", "Tailored assistance is in progress")
    try:
        updated = _apply_answer(session, body, now=now_utc())
        repo.save(updated, expected_version=session.version)
        if updated.status is PlanningSessionStatus.AWAITING_ASSISTANT:
            updated = run_adaptive_review(repo, updated, llm, now_utc)
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
    llm: Annotated[LLMClient, Depends(get_interview_llm)],
) -> SessionOut:
    require_csrf(request)
    body_as_answer = AnswerRequest(
        question_id=body.question_id,
        expected_version=body.expected_version,
        delegated=True,
        client_event_id=body.client_event_id,
    )
    return answer_session(session_id, body_as_answer, request, user, store, llm)


@router.post("/sessions/{session_id}/interpret", response_model=SessionOut)
def interpret_session(
    session_id: str,
    body: InterpretRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    llm: Annotated[LLMClient, Depends(get_interview_llm)],
) -> SessionOut:
    require_csrf(request)
    repo = _repo(store)
    session = _get_session(repo, user, session_id)
    key = f"interpret:{body.client_event_id}"
    existing = session.assistance_requests.get(key)
    if existing:
        request_hash = fingerprint(
            {
                "question_id": body.question_id.value,
                "text": body.text,
                "expected_version": body.expected_version,
            }
        )
        if existing.fingerprint != request_hash:
            raise _error(409, "IDEMPOTENCY_CONFLICT", "Event id belongs to another request")
        return _session_out(session)
    if body.question_id not in INTERPRETABLE_QUESTIONS or not body.text.strip():
        raise _error(422, "TYPED_ANSWER_REQUIRED", "Use typed controls for this answer")
    eligible = (
        session.status is PlanningSessionStatus.INTERVIEWING
        and body.question_id == session.current_question_id
    ) or (session.status is PlanningSessionStatus.REVIEWING and body.question_id in session.answers)
    if not eligible or session.confirmed_briefs:
        raise _error(
            422,
            "INVALID_QUESTION",
            "Only the current or an unconfirmed review answer can be interpreted",
        )
    try:
        updated = interpret_answer(
            repo,
            session,
            llm,
            question_id=body.question_id,
            text=body.text,
            client_event_id=body.client_event_id,
            expected_version=body.expected_version,
            clock=now_utc,
        )
    except AssistanceIdempotencyConflict as exc:
        raise _error(409, "IDEMPOTENCY_CONFLICT", str(exc)) from None
    except (StaleSessionVersionError, StalePlanningSessionError) as exc:
        raise _error(409, "STALE_SESSION", str(exc)) from None
    except AssistanceInProgress as exc:
        raise _error(409, "ASSISTANCE_IN_PROGRESS", str(exc)) from None
    return _session_out(updated)


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
        updated = amend_answer(
            session, answer, expected_version=body.expected_version, now=now_utc()
        )
        updated = PlanningSession.model_validate(
            updated.model_copy(
                update={
                    "pending_answer": None,
                    "contradictions": [
                        c for c in updated.contradictions if body.question_id not in c.answer_ids
                    ],
                }
            ).model_dump()
        )
        repo.save(updated, expected_version=session.version)
    except StalePlanningSessionError as exc:
        raise _error(409, "STALE_SESSION", str(exc)) from None
    except PlanningPolicyError as exc:
        raise _error(422, "INVALID_AMENDMENT", str(exc)) from None
    return _session_out(updated)


@router.post("/sessions/{session_id}/back", response_model=SessionOut)
def back_session(
    session_id: str,
    body: BackRequest,
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
        updated = go_back(session, expected_version=body.expected_version, now=now_utc())
        updated = updated.model_copy(
            update={"processed_event_ids": [*updated.processed_event_ids, body.client_event_id]}
        )
        updated = PlanningSession.model_validate(updated.model_dump())
        repo.save(updated, expected_version=session.version)
    except (StaleSessionVersionError, StalePlanningSessionError) as exc:
        raise _error(409, "STALE_SESSION", str(exc)) from None
    except (BackNavigationError, PlanningPolicyError) as exc:
        raise _error(422, "INVALID_BACK", str(exc)) from None
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
    from api.confirmed_planning import start_confirmed_job

    start_confirmed_job(session, job_id)


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
    with _confirmation_guard(session_id):
        session = _get_session(repo, user, session_id)
        if session.contradictions and not session.confirmed_briefs:
            raise _error(
                422,
                "UNRESOLVED_CONTRADICTIONS",
                "Review the conflicting answers before confirming",
            )
        if session.planning_job_id is not None:
            return ConfirmOut(**_session_out(session).model_dump(), job_id=session.planning_job_id)
        if (
            body.client_event_id in session.processed_event_ids
            and session.confirmed_briefs
            and session.status is not PlanningSessionStatus.FAILED
        ):
            raise _error(409, "CONFIRMATION_IN_PROGRESS", "Confirmation is already being processed")
        try:
            if session.status is PlanningSessionStatus.FAILED and session.confirmed_briefs:
                if body.expected_version != session.version:
                    raise StaleSessionVersionError("Session version is stale")
                existing_json = session.confirmed_briefs[-1].brief.model_dump_json()
                if body.brief.model_dump_json() != existing_json:
                    raise BriefMismatchError("brief does not match the confirmed snapshot")
                confirmed = session.model_copy(
                    update={"version": session.version + 1, "updated_at": now_utc()}
                )
            else:
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
                    "planning_error": None,
                    "processed_event_ids": (
                        confirmed.processed_event_ids
                        if body.client_event_id in confirmed.processed_event_ids
                        else [*confirmed.processed_event_ids, body.client_event_id]
                    ),
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
        try:
            _start_legacy_job(confirmed, job_id)
        except Exception:
            failed = confirmed.model_copy(
                update={
                    "status": PlanningSessionStatus.FAILED,
                    "planning_job_id": None,
                    "planning_error": "Planning job could not be started; retry confirmation.",
                    "version": confirmed.version + 1,
                    "updated_at": now_utc(),
                }
            )
            failed = PlanningSession.model_validate(failed.model_dump())
            try:
                repo.save(failed, expected_version=confirmed.version)
            except StalePlanningSessionError:
                pass
            raise _error(
                503,
                "PLANNING_START_FAILED",
                failed.planning_error or "Planning job could not be started",
            ) from None
        return ConfirmOut(**_session_out(confirmed).model_dump(), job_id=job_id)


@router.get("/sessions/{session_id}/job", response_model=PlanJobStatus)
def session_job(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> PlanJobStatus:
    session = _get_session(_repo(store), user, session_id)
    if session.planning_job_id is None:
        raise _error(404, "JOB_NOT_STARTED", "Planning has not started")
    from api.job_manager import job_manager

    state = job_manager.get_job(session.planning_job_id)
    if state is None:
        return PlanJobStatus(job_id=session.planning_job_id, status="queued")
    status = state.to_status(session.planning_job_id)
    if status.status == "failed" and session.status is PlanningSessionStatus.PLANNING:
        failed = PlanningSession.model_validate(
            session.model_dump(
                mode="python",
                exclude={"planning_job_id", "planning_error", "status", "version", "updated_at"},
            )
            | {
                "status": PlanningSessionStatus.FAILED,
                "planning_job_id": None,
                "planning_error": status.error.message if status.error else "Planning failed.",
                "version": session.version + 1,
                "updated_at": now_utc(),
            }
        )
        try:
            _repo(store).save(failed, expected_version=session.version)
        except StalePlanningSessionError:
            pass
    return status


def _owned_job_report(session: PlanningSession, user: User) -> tuple[Any, Any]:
    if session.planning_job_id is None:
        raise _error(404, "JOB_NOT_STARTED", "Planning has not started")
    from api.job_manager import job_manager

    state = job_manager.get_job(session.planning_job_id)
    if state is None or state.owner_id != user.id or state.session_id != session.id:
        raise _error(404, "JOB_NOT_FOUND", "Planning job not found")
    if state.report is None or state.report.travel_inventory is None:
        raise _error(409, "INVENTORY_REVIEW_REQUIRED", "Inventory evidence is not available")
    return state, state.report


@router.post("/sessions/{session_id}/recompute", response_model=FinalReport)
def recompute_confirmed_session(
    session_id: str,
    body: ConfirmedEditRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> Any:
    require_csrf(request)
    session = _get_session(_repo(store), user, session_id)
    state, report = _owned_job_report(session, user)
    current_revision = report.travel_inventory.inventory_revision
    if body.expected_inventory_revision != current_revision:
        raise _error(
            409,
            "INVENTORY_REVIEW_REQUIRED",
            "Inventory evidence changed; review the current report",
        )
    from agents.post_plan_execution import recompute_confirmed_edit

    # Flight/hotel lines were admitted from provider evidence when the job completed.
    # Rebuild the report from those exact lines and run the kernel once on the final
    # costed trip, so every total, allocation and transfer recommendation matches
    # the prices the user sees.
    updated = recompute_confirmed_edit(
        report, body.edit, kb=get_kb_for_conversation(), now=now_utc()
    )
    with state._lock:
        state.report = updated
    return updated


def get_kb_for_conversation() -> Any:
    from api.main import get_kb

    return get_kb()


@router.post("/sessions/{session_id}/refresh-prose", response_model=FinalReport)
def refresh_confirmed_session_prose(
    session_id: str,
    body: ConfirmedProseRequest,
    request: Request,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> FinalReport:
    require_csrf(request)
    session = _get_session(_repo(store), user, session_id)
    state, report = _owned_job_report(session, user)
    if body.expected_inventory_revision != report.travel_inventory.inventory_revision:
        raise _error(
            409,
            "INVENTORY_REVIEW_REQUIRED",
            "Inventory evidence changed; review the current report",
        )
    from pathlib import Path

    from agents.explainer import run_explainer
    from agents.models import EstimatorResult, KernelResult
    from agents.retrieval import retrieve_candidates
    from api.main import get_kb, get_llm

    estimate = EstimatorResult(
        costed_trip=report.costed_trip,
        flight=report.flights_pick,
        hotel=report.hotel_pick,
    )
    kernel = KernelResult(
        optimizer_result=report.optimizer_result,
        transfer_advice=report.transfer_advice,
    )
    refreshed = run_explainer(
        report.trip_spec,
        report.itinerary,
        estimate,
        kernel,
        retrieve_candidates(report.trip_spec, get_kb()),
        critic_caveats=report.caveats,
        trace_id=report.trace_id,
        llm=get_llm(),
        region_capability=build_region_capability(
            report.trip_spec.destination_city, Path("catalogs")
        ),
        freshness=report.freshness,
    )
    refreshed = refreshed.model_copy(update={"travel_inventory": report.travel_inventory})
    with state._lock:
        state.report = refreshed
    return refreshed
