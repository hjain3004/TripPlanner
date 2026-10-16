"""Durable CP3 call reservations around the pure interview domain.

The reservation is committed by CAS before any model invocation. An interrupted
request cannot be dispatched again, including after reopening the database.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from agents.interview_assistant import InterviewAssistant, InvalidInterviewResponse, compact_state
from agents.llm import LLMClient
from planning.answers import QuestionId
from planning.assistance import (
    AssistanceDiagnostic,
    AssistanceRequestRecord,
)
from planning.contracts import AssistanceStatus, ConversationEvent, PlanningSession
from planning.policy import StaleSessionVersionError, record_assistant_suggestions
from planning.repository import PlanningSessionRepository


class AssistanceIdempotencyConflict(ValueError):
    pass


class AssistanceInProgress(ValueError):
    pass


def fingerprint(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _changed(session: PlanningSession, now: datetime, **changes: Any) -> PlanningSession:
    return PlanningSession.model_validate(
        session.model_copy(
            update={
                **changes,
                "version": session.version + 1,
                "updated_at": now,
            }
        ).model_dump()
    )


def _reserve(
    repo: PlanningSessionRepository,
    session: PlanningSession,
    *,
    key: str,
    request_hash: str,
    expected_version: int,
    limit: int,
    now: datetime,
) -> tuple[PlanningSession, bool]:
    existing = session.assistance_requests.get(key)
    if existing:
        if existing.fingerprint != request_hash:
            raise AssistanceIdempotencyConflict("Event id belongs to another assistance request")
        return session, False
    if expected_version != session.version:
        raise StaleSessionVersionError("Session version is stale")
    if any(row.status == "reserved" for row in session.assistance_requests.values()):
        raise AssistanceInProgress("Another assistance request is in progress")
    permitted = session.interview_llm_calls < limit
    diagnostic: AssistanceDiagnostic = "interrupted" if permitted else "budget_exhausted"
    record = AssistanceRequestRecord(
        fingerprint=request_hash,
        status="reserved" if permitted else "degraded",
        diagnostic=diagnostic,
        reserved_at=now,
    )
    reserved = _changed(
        session,
        now,
        interview_llm_calls=session.interview_llm_calls + int(permitted),
        assistance_status=AssistanceStatus.DEGRADED,
        assistance_diagnostics=[*session.assistance_diagnostics, diagnostic],
        assistance_requests={**session.assistance_requests, key: record},
        pending_answer=None,
        events=[
            *session.events,
            ConversationEvent(
                id=f"{session.id}:assistance:{key}:reserved",
                kind="system_progress",
                text="Tailored assistance requested."
                if permitted
                else "Tailored assistance is limited; typed answers remain available.",
                created_at=now,
            ),
        ],
    )
    repo.save(reserved, expected_version=session.version)
    return reserved, permitted


def _diagnostic(exc: Exception) -> AssistanceDiagnostic:
    return "invalid_response" if isinstance(exc, InvalidInterviewResponse) else "unavailable"


def recover_interrupted_requests(
    repo: PlanningSessionRepository,
    session: PlanningSession,
    now: datetime,
) -> PlanningSession:
    """A read during the bounded call never steals the active reservation.

    After the timeout plus grace period, retain the spent slot and turn the
    reservation into a durable degraded result without dispatching again.
    """
    expired = {
        key
        for key, row in session.assistance_requests.items()
        if row.status == "reserved"
        and now - (row.reserved_at or session.updated_at) >= timedelta(seconds=30)
    }
    if not expired:
        return session
    updated = _changed(
        session,
        now,
        assistance_requests={
            key: row.model_copy(update={"status": "degraded", "diagnostic": "interrupted"})
            if key in expired
            else row
            for key, row in session.assistance_requests.items()
        },
        assistance_status=AssistanceStatus.DEGRADED,
        assistance_diagnostics=[*session.assistance_diagnostics, "interrupted"],
        events=[
            *session.events,
            ConversationEvent(
                id=f"{session.id}:assistance:interrupted:{session.version}",
                kind="system_progress",
                text="Tailored assistance was interrupted. Typed controls remain available.",
                created_at=now,
            ),
        ],
    )
    repo.save(updated, expected_version=session.version)
    return updated


def run_adaptive_review(
    repo: PlanningSessionRepository,
    session: PlanningSession,
    client: LLMClient | None,
    clock: Callable[[], datetime],
) -> PlanningSession:
    request_hash = fingerprint(compact_state(session))
    key = f"review:{request_hash}"
    existing = session.assistance_requests.get(key)
    review = existing.review if existing and existing.status == "complete" else None
    diagnostic = existing.diagnostic if existing else None
    current = session
    if existing is None:
        # A changed core answer is not permission for an ordinary third/repeated
        # review. The second call is reserved for unresolved free text only.
        prior_review = any(name.startswith("review:") for name in session.assistance_requests)
        current, invoke = _reserve(
            repo,
            session,
            key=key,
            request_hash=request_hash,
            expected_version=session.version,
            limit=session.interview_llm_calls if prior_review else 2,
            now=clock(),
        )
        if invoke and client is not None:
            try:
                review = InterviewAssistant(client).review(current)
                diagnostic = None
            except Exception as exc:
                diagnostic = _diagnostic(exc)
        else:
            diagnostic = "budget_exhausted" if not invoke else "interrupted"
    elif existing.status == "reserved":
        diagnostic = "interrupted"
    applied = record_assistant_suggestions(
        current,
        review.question_ids if review else [],
        assistance_status="complete" if review else "degraded",
        llm_calls=current.interview_llm_calls,
        expected_version=current.version,
        now=clock(),
    )
    events = list(applied.events)
    if review and review.acknowledgement:
        events.append(
            ConversationEvent(
                id=f"{session.id}:assistance:{key}:ack:{applied.version}",
                kind="assistant_acknowledgement",
                text=review.acknowledgement,
                created_at=clock(),
            )
        )
    elif not review:
        events.append(
            ConversationEvent(
                id=f"{session.id}:assistance:{key}:degraded:{applied.version}",
                kind="system_progress",
                text=(
                    "Tailored follow-ups were unavailable. "
                    "You can continue with the standard questions."
                ),
                created_at=clock(),
            )
        )
    row = AssistanceRequestRecord(
        fingerprint=request_hash,
        status="complete" if review else "degraded",
        review=review,
        diagnostic=diagnostic,
    )
    applied = PlanningSession.model_validate(
        applied.model_copy(
            update={
                "personalized_wording": review.wording if review else {},
                "contradictions": review.contradictions if review else [],
                "assistance_diagnostics": [
                    d for d in current.assistance_diagnostics if d != "interrupted"
                ]
                + ([diagnostic] if diagnostic else []),
                "assistance_requests": {**current.assistance_requests, key: row},
                "events": events,
            }
        ).model_dump()
    )
    repo.save(applied, expected_version=current.version)
    return applied


def interpret_answer(
    repo: PlanningSessionRepository,
    session: PlanningSession,
    client: LLMClient,
    *,
    question_id: QuestionId,
    text: str,
    client_event_id: str,
    expected_version: int,
    clock: Callable[[], datetime],
) -> PlanningSession:
    key = f"interpret:{client_event_id}"
    request_hash = fingerprint(
        {
            "question_id": question_id.value,
            "text": text,
            "expected_version": expected_version,
        }
    )
    reviewed = any(name.startswith("review:") for name in session.assistance_requests)
    review_complete = any(
        name.startswith("review:") and row.status == "complete" and row.review is not None
        for name, row in session.assistance_requests.items()
    )
    current, invoke = _reserve(
        repo,
        session,
        key=key,
        request_hash=request_hash,
        expected_version=expected_version,
        limit=2 if reviewed else 1,
        now=clock(),
    )
    if not invoke:
        return current
    candidate = None
    diagnostic = None
    try:
        candidate = InterviewAssistant(client).interpret(current, question_id, text)
    except Exception as exc:
        diagnostic = _diagnostic(exc)
    record = AssistanceRequestRecord(
        fingerprint=request_hash,
        status="complete" if candidate else "degraded",
        candidate=candidate,
        diagnostic=diagnostic,
    )
    finished = _changed(
        current,
        clock(),
        pending_answer=candidate,
        # A candidate does not substitute for the mandatory adaptive review.
        assistance_status=AssistanceStatus.COMPLETE
        if candidate and review_complete
        else (
            AssistanceStatus.NOT_RUN if candidate and not reviewed else AssistanceStatus.DEGRADED
        ),
        assistance_diagnostics=[d for d in current.assistance_diagnostics if d != "interrupted"]
        + ([diagnostic] if diagnostic else []),
        assistance_requests={**current.assistance_requests, key: record},
        events=[
            *current.events,
            ConversationEvent(
                id=f"{session.id}:assistance:{key}:result",
                kind="assistant_acknowledgement" if candidate else "system_progress",
                text="Review the proposed answer before saving it."
                if candidate
                else "That answer could not be interpreted. Typed controls remain available.",
                question_id=question_id,
                created_at=clock(),
            ),
        ],
    )
    repo.save(finished, expected_version=current.version)
    return finished
