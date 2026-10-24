"""Authenticated, user-scoped saved-trip routes (spec 17 §5, A4).

A saved trip is an immutable travel record: saving a finished plan stores the exact
report the user was looking at, and a later re-run appends a new revision instead of
changing an old one. Invariants the handlers exist to protect:

* **Authority comes from the session cookie, never the payload.** Request models are
  ``extra="forbid"`` and the store is always called with ``user.id``.
* **Wrong owner is indistinguishable from missing.** Every route answers a trip or
  planning-session id the caller does not own exactly as it answers one that does not
  exist.
* **Stored reports are returned verbatim.** A revision's ``report`` is the stored JSON
  parsed as a plain object; it is never re-validated through today's ``FinalReport``,
  which would silently coerce, default or drop fields of an older snapshot.
* **Nothing is reconstructed.** A plan whose in-memory result is gone (process
  restart) cannot be saved; the route says so rather than recomputing something the
  user never saw.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Any, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.exc import OperationalError

from accounts.models import ACCOUNTS_SCHEMA_VERSION, SavedTrip, TripRevision, User
from accounts.store import (
    AccountStore,
    ReportTooLargeError,
    RevisionLimitReachedError,
    SavedTripResult,
    StalePlanningSessionError,
    TripIdempotencyConflictError,
    TripLimitReachedError,
    TripRevisionConflictError,
    UnknownTripError,
    trip_event_fingerprint,
)
from agents.confirmed_trip import compile_confirmed_input
from agents.models import FinalReport
from api.auth import current_user, get_store, now_utc, require_csrf
from api.job_manager import job_manager
from planning.contracts import PlanningSession
from planning.repository import PlanningSessionRepository

router = APIRouter(prefix="/account/trips", tags=["saved-trips"])

EventId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
TripTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


# --------------------------------------------------------------------------- #
# Errors                                                                        #
# --------------------------------------------------------------------------- #


class ApiErrorBody(BaseModel):
    """The ``detail`` of every typed saved-trip failure."""

    code: str
    message: str
    trip_id: str | None = None


def _error(status_code: int, code: str, message: str, **extra: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message, **extra}
    )


def _trip_not_found() -> HTTPException:
    """One fixed response for "missing" and "not yours" alike."""
    return _error(status.HTTP_404_NOT_FOUND, "TRIP_NOT_FOUND", "No such saved trip.")


def _session_not_found() -> HTTPException:
    return _error(status.HTTP_404_NOT_FOUND, "SESSION_NOT_FOUND", "Planning session not found")


def _handle(call: Any) -> Any:
    """Run a store call, mapping its typed failures onto typed HTTP responses.

    Order matters: every store error below is a ``ValueError`` subclass, so the broad
    ``ValueError`` arm has to come last or it would swallow them and report a 422 for
    a genuine 404 or 409.
    """
    try:
        return call()
    except UnknownTripError as exc:
        raise _trip_not_found() from exc
    except TripIdempotencyConflictError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "IDEMPOTENCY_KEY_REUSED",
            "This client event id was already used for a different request.",
        ) from exc
    except TripLimitReachedError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "TRIP_LIMIT_REACHED",
            "You have reached the maximum number of saved trips. Delete one to save another.",
        ) from exc
    except RevisionLimitReachedError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "REVISION_LIMIT_REACHED",
            "This trip has reached its maximum number of revisions.",
        ) from exc
    except TripRevisionConflictError as exc:
        raise _error(
            status.HTTP_409_CONFLICT,
            "TRIP_REVISION_CONFLICT",
            "This trip changed while it was being updated. Please retry.",
        ) from exc
    except ReportTooLargeError as exc:
        raise _error(
            status.HTTP_413_CONTENT_TOO_LARGE,
            "REPORT_TOO_LARGE",
            "This plan is too large to store.",
        ) from exc
    except OperationalError as exc:
        # Lock contention or another operational fault. Never surface the driver
        # exception; the client should retry, not read a stack trace.
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SAVED_TRIPS_UNAVAILABLE",
            "Saved trips are temporarily unavailable. Please retry.",
        ) from exc
    except ValueError as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "SAVED_TRIP_INVALID",
            "That saved-trip request is not valid.",
        ) from exc


# --------------------------------------------------------------------------- #
# Wire models                                                                   #
# --------------------------------------------------------------------------- #


class SaveTripIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    title: TripTitle | None = None
    client_event_id: EventId


class AppendRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    client_event_id: EventId


class RevisionSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int
    computed_at: str
    trace_id: str
    schema_version: str
    is_current_schema: bool

    @classmethod
    def of(cls, revision: TripRevision) -> RevisionSummaryOut:
        return cls(
            revision=revision.revision,
            computed_at=revision.created_at.isoformat(),
            trace_id=revision.trace_id,
            schema_version=revision.schema_version,
            is_current_schema=revision.schema_version == ACCOUNTS_SCHEMA_VERSION,
        )


class RevisionOut(RevisionSummaryOut):
    """One stored revision. ``report`` is the stored JSON object, verbatim."""

    report: dict[str, Any]

    @classmethod
    def of(cls, revision: TripRevision) -> RevisionOut:
        summary = RevisionSummaryOut.of(revision)
        return cls(**summary.model_dump(), report=json.loads(revision.report_json))


class TripSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    origin_city: str
    destination_city: str
    start_date: date
    end_date: date
    created_at: str
    revision_count: int
    latest_revision: int
    latest_computed_at: str

    @classmethod
    def of(cls, trip: SavedTrip, revisions: list[TripRevision]) -> TripSummaryOut:
        latest = revisions[-1]
        return cls(
            id=trip.id,
            title=trip.title,
            origin_city=trip.origin_city,
            destination_city=trip.destination_city,
            start_date=trip.start_date,
            end_date=trip.end_date,
            created_at=trip.created_at.isoformat(),
            revision_count=len(revisions),
            latest_revision=latest.revision,
            latest_computed_at=latest.created_at.isoformat(),
        )


class TripDetailOut(TripSummaryOut):
    revisions: list[RevisionSummaryOut]


class SavedTripCreatedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip: TripSummaryOut
    revision: RevisionOut


def _created(result: SavedTripResult) -> SavedTripCreatedOut:
    return SavedTripCreatedOut(
        trip=TripSummaryOut.of(result.trip, [result.revision]),
        revision=RevisionOut.of(result.revision),
    )


def _created_from_event(payload: str) -> SavedTripCreatedOut:
    """Rebuild the *original* save response from its recorded outcome."""
    data = json.loads(payload)
    return _created(
        SavedTripResult(
            trip=SavedTrip.model_validate(data["trip"]),
            revision=TripRevision.model_validate(data["revision"]),
        )
    )


# --------------------------------------------------------------------------- #
# Session and plan lookup                                                       #
# --------------------------------------------------------------------------- #


def _owned_session(store: AccountStore, user: User, session_id: str) -> PlanningSession:
    session = PlanningSessionRepository(store).get(user_id=user.id, session_id=session_id)
    if session is None:
        raise _session_not_found()
    return session


def _finished_report(session: PlanningSession, user: User) -> FinalReport:
    """The report the user is looking at, or a typed refusal. Never a reconstruction."""
    if not session.confirmed_briefs or session.planning_job_id is None:
        raise _error(
            status.HTTP_409_CONFLICT,
            "SESSION_NOT_CONFIRMED",
            "Confirm the trip brief and let planning finish before saving.",
        )
    state = job_manager.get_job(session.planning_job_id)
    if state is None or state.owner_id != user.id or state.session_id != session.id:
        _plan_unavailable()
    with state._lock:
        report = state.report
    if report is None:
        _plan_unavailable()
    return report


def _plan_unavailable() -> NoReturn:
    raise _error(
        status.HTTP_409_CONFLICT,
        "PLAN_RESULT_UNAVAILABLE",
        "This plan's result is no longer available to save. Plan the trip again.",
    )


def _already_saved(trip_id: str) -> HTTPException:
    return _error(
        status.HTTP_409_CONFLICT,
        "SESSION_ALREADY_SAVED",
        "This plan is already saved. Add the current plan to that trip as a new revision.",
        trip_id=trip_id,
    )


# --------------------------------------------------------------------------- #
# Routes                                                                        #
# --------------------------------------------------------------------------- #


@router.post("", response_model=SavedTripCreatedOut, status_code=201)
def save_trip(
    request: Request,
    payload: SaveTripIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> SavedTripCreatedOut:
    """Save the confirmed session's current plan as a new trip with revision 1."""
    require_csrf(request)
    # The fingerprint is the request's *intent*. The report it will store can differ
    # between honest retries (the user edited in between), so it must not be part of it.
    fingerprint = trip_event_fingerprint(
        "save", fields={"session_id": payload.session_id, "title": payload.title}
    )

    def call() -> SavedTripCreatedOut:
        replay = store.trip_event_result(
            user_id=user.id,
            client_event_id=payload.client_event_id,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return _created_from_event(replay)

        session = _owned_session(store, user, payload.session_id)
        if session.saved_trip_id is not None:
            raise _already_saved(session.saved_trip_id)
        report = _finished_report(session, user)
        spec = report.trip_spec
        trip_id = uuid4().hex
        now = now_utc()
        attached = PlanningSession.model_validate(
            session.model_copy(
                update={
                    "saved_trip_id": trip_id,
                    "version": session.version + 1,
                    "updated_at": now,
                }
            ).model_dump()
        )
        try:
            result = store.save_trip_with_revision(
                user_id=user.id,
                trip_id=trip_id,
                title=payload.title
                or f"{spec.origin_city} → {spec.destination_city} · {spec.start_date.isoformat()}",
                origin_city=spec.origin_city,
                destination_city=spec.destination_city,
                start_date=spec.start_date,
                end_date=spec.end_date,
                raw_request=compile_confirmed_input(session.confirmed_briefs[-1]).raw_request,
                trip_spec_json=spec.model_dump_json(),
                trace_id=report.trace_id,
                report_json=report.model_dump_json(),
                now=now,
                attach_session=PlanningSessionRepository.snapshot_of(attached),
                expected_session_version=session.version,
                client_event_id=payload.client_event_id,
                request_fingerprint=fingerprint,
            )
        except StalePlanningSessionError:
            # Someone advanced the session first. If that was a competing save the
            # session now names its trip; either way nothing of ours was written.
            current = _owned_session(store, user, payload.session_id)
            if current.saved_trip_id is not None:
                raise _already_saved(current.saved_trip_id) from None
            raise _error(
                status.HTTP_409_CONFLICT,
                "STALE_SESSION",
                "This planning session changed. Reload it and try again.",
            ) from None
        return _created(result)

    created: SavedTripCreatedOut = _handle(call)
    return created


@router.post("/{trip_id}/revisions", response_model=RevisionOut, status_code=201)
def append_revision(
    request: Request,
    trip_id: str,
    payload: AppendRevisionIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> RevisionOut:
    """Append the attached session's *current* plan to the trip as the next revision."""
    require_csrf(request)
    fingerprint = trip_event_fingerprint(
        "append_revision", trip_id=trip_id, fields={"session_id": payload.session_id}
    )

    def call() -> RevisionOut:
        store.get_trip(user.id, trip_id)  # 404 for missing and for not-yours alike
        replay = store.trip_event_result(
            user_id=user.id,
            client_event_id=payload.client_event_id,
            request_fingerprint=fingerprint,
        )
        if replay is not None:
            return RevisionOut.of(TripRevision.model_validate_json(replay))

        session = _owned_session(store, user, payload.session_id)
        if session.saved_trip_id != trip_id:
            raise _error(
                status.HTTP_409_CONFLICT,
                "SESSION_NOT_ATTACHED",
                "That planning session is not the one this trip was saved from.",
            )
        report = _finished_report(session, user)
        revision = store.add_revision(
            user_id=user.id,
            trip_id=trip_id,
            trace_id=report.trace_id,
            report_json=report.model_dump_json(),
            now=now_utc(),
            client_event_id=payload.client_event_id,
            request_fingerprint=fingerprint,
        )
        return RevisionOut.of(revision)

    appended: RevisionOut = _handle(call)
    return appended
