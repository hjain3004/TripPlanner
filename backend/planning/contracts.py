"""Planning-session and Trip Brief contracts for the CP1 conversational domain.

``PlanningSession`` is the in-memory shape of one resumable conversational
interview: server-owned identity/version/timestamps, the traveler's answers
so far, and the bookkeeping the orchestrator needs to resume a paused
interview exactly where it left off. It is never persisted directly — see
``planning/repository.py``, which converts it to the opaque
``accounts.models.PlanningSessionSnapshot`` for storage through
``AccountStore``.

``TripBrief`` is the fully-resolved, typed output of a completed interview:
one closed answer payload per section (imported from ``planning.answers``,
never duplicated here), plus the applied durable-profile defaults and the
assumptions the system made to fill any gap. It embeds ``UserWallet`` from
``core.models`` — the same wallet shape the frozen kernel already accepts —
so a confirmed brief is always shape-compatible with the optimizer's input.

Nothing in this module stores a display name, an email address, a raw
transcript, or a provider payload: only structured, typed answer data and
bookkeeping fields the orchestrator needs to resume or replay a session.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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


class PlanningSessionStatus(StrEnum):
    INTERVIEWING = "interviewing"
    AWAITING_ASSISTANT = "awaiting_assistant"
    REVIEWING = "reviewing"
    CONFIRMED = "confirmed"
    PLANNING = "planning"
    COMPLETE = "complete"
    FAILED = "failed"
    ABANDONED = "abandoned"


class AssistanceStatus(StrEnum):
    NOT_RUN = "not_run"
    COMPLETE = "complete"
    DEGRADED = "degraded"


class ConversationEvent(BaseModel):
    """A persisted, user-visible event; never a raw transcript or model trace."""

    model_config = ConfigDict(extra="forbid")
    id: str
    kind: Literal[
        "assistant_question",
        "user_answer",
        "assistant_acknowledgement",
        "brief_review",
        "system_progress",
        "error",
    ]
    question_id: QuestionId | None = None
    text: str = Field(min_length=1, max_length=2000)
    created_at: datetime


def _normalize_iata(value: str) -> str:
    """Mirror ``accounts.models.UserProfile.normalize_iata`` exactly."""
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be a 3-letter IATA code")
    return normalized


def _normalize_currency(value: str) -> str:
    """Mirror ``accounts.models.UserProfile.normalize_currency`` exactly."""
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be a 3-letter ISO 4217 currency code")
    return normalized


class TravelerHomeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_country: Literal["IN", "AE", "US"]
    home_currency: str
    default_origin: str | None = None

    @field_validator("home_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return _normalize_currency(value)

    @field_validator("default_origin")
    @classmethod
    def normalize_default_origin(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_iata(value)


class ProfileUpdateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    section: Literal[
        "flight", "stay", "rhythm", "experiences", "constraints", "optimization"
    ]
    candidate_profile: TravelPreferenceProfile
    source_question_id: QuestionId


class TripBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home: TravelerHomeContext
    trip_essentials: TripEssentialsPayload
    purpose_and_party: PurposePartyPayload | None = None
    budget_and_objective: BudgetObjectivePayload | None = None
    flight_preferences: FlightPreferencesPayload | None = None
    stay_preferences: StayPreferencesPayload | None = None
    daily_rhythm: DailyRhythmPayload | None = None
    experiences_and_food: ExperiencesFoodPayload | None = None
    hard_constraints: HardConstraintsPayload
    adaptive_details: dict[QuestionId, AdaptiveDetailPayload] = Field(
        default_factory=dict
    )
    delegated_questions: list[QuestionId] = Field(default_factory=list)
    applied_profile_preferences: TravelPreferenceProfile | None = None
    applied_profile_sections: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    wallet: UserWallet


class ConfirmedBriefSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    brief: TripBrief
    confirmed_at: datetime


class PlanningSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    user_id: str
    status: PlanningSessionStatus
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    home: TravelerHomeContext
    wallet: UserWallet
    profile_defaults: TravelPreferenceProfile | None = None
    answers: dict[QuestionId, InterviewAnswer] = Field(default_factory=dict)
    current_question_id: QuestionId | None = None
    suggested_question_ids: list[QuestionId] = Field(default_factory=list)
    processed_event_ids: list[str] = Field(default_factory=list)
    assistance_status: AssistanceStatus = AssistanceStatus.NOT_RUN
    interview_llm_calls: int = Field(default=0, ge=0, le=2)
    pending_profile_updates: list[ProfileUpdateProposal] = Field(default_factory=list)
    confirmed_briefs: list[ConfirmedBriefSnapshot] = Field(default_factory=list)
    saved_trip_id: str | None = None
    # Set atomically when a confirmed brief is handed to the existing
    # non-live planning job.  Persisting this marker makes confirmation
    # idempotent even when two clients submit the same review concurrently.
    planning_job_id: str | None = None
    planning_error: str | None = None
    events: list[ConversationEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_session_invariants(self) -> PlanningSession:
        for value, name in (
            (self.created_at, "created_at"),
            (self.updated_at, "updated_at"),
            (self.expires_at, "expires_at"),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if self.expires_at <= self.updated_at:
            raise ValueError("expires_at must be strictly after updated_at")
        if len(set(self.processed_event_ids)) != len(self.processed_event_ids):
            raise ValueError("processed_event_ids must not contain duplicates")
        if len(set(self.suggested_question_ids)) != len(self.suggested_question_ids):
            raise ValueError("suggested_question_ids must not contain duplicates")
        revisions = [snapshot.revision for snapshot in self.confirmed_briefs]
        if revisions != sorted(revisions) or len(set(revisions)) != len(revisions):
            raise ValueError(
                "confirmed_briefs must be strictly ordered by increasing revision"
            )
        return self
