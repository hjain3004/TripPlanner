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
import threading
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy.exc import OperationalError

import accounts.store as account_store
from accounts.models import ACCOUNTS_SCHEMA_VERSION, SavedTrip, TripRevision, User
from accounts.projection import build_user_wallet
from accounts.store import (
    AccountStore,
    ReportTooLargeError,
    RevisionLimitReachedError,
    RevisionMeta,
    SavedTripResult,
    StalePlanningSessionError,
    TripIdempotencyConflictError,
    TripLimitReachedError,
    TripOverview,
    TripRevisionConflictError,
    UnknownRevisionError,
    UnknownTripError,
    trip_event_fingerprint,
)
from agents.confirmed_trip import compile_confirmed_input
from agents.models import FinalReport, JobError, TripIntakeRequest
from api.auth import current_user, get_store, now_utc, require_csrf
from api.confirmed_planning import build_travel_service
from api.job_manager import job_manager
from planning.contracts import PlanningSession
from planning.repository import PlanningSessionRepository

router = APIRouter(prefix="/account/trips", tags=["saved-trips"])

EventId = Annotated[str, StringConstraints(min_length=1, max_length=128)]
TripTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


# --------------------------------------------------------------------------- #
# Errors                                                                        #
# --------------------------------------------------------------------------- #


SavedTripErrorCode = Literal[
    "IDEMPOTENCY_KEY_REUSED",
    "PLAN_RESULT_UNAVAILABLE",
    "REPORT_TOO_LARGE",
    "RERUN_IN_PROGRESS",
    "RERUN_NOT_FOUND",
    "REVISION_LIMIT_REACHED",
    "REVISION_NOT_FOUND",
    "SAVED_TRIP_INVALID",
    "SAVED_TRIPS_UNAVAILABLE",
    "SESSION_ALREADY_SAVED",
    "SESSION_EXPIRED",
    "SESSION_NOT_ATTACHED",
    "SESSION_NOT_CONFIRMED",
    "SESSION_NOT_FOUND",
    "STALE_SESSION",
    "TRIP_LIMIT_REACHED",
    "TRIP_NOT_FOUND",
    "TRIP_NOT_RERUNNABLE",
    "TRIP_REVISION_CONFLICT",
]


class ApiErrorBody(BaseModel):
    """The ``detail`` of every typed saved-trip failure.

    ``code`` is a closed set, so a generated client can switch on it exhaustively.
    ``trip_id`` is present only on ``SESSION_ALREADY_SAVED``.
    """

    model_config = ConfigDict(extra="forbid")

    code: SavedTripErrorCode
    message: str
    trip_id: str | None = None


class SavedTripErrorResponse(BaseModel):
    """A typed saved-trip failure as it goes over the wire (FastAPI wraps it in ``detail``)."""

    model_config = ConfigDict(extra="forbid")

    detail: ApiErrorBody


class AuthErrorResponse(BaseModel):
    """401 (no or expired session) and 403 (CSRF check) carry a plain-string detail."""

    model_config = ConfigDict(extra="forbid")

    detail: str


class ValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class RequestValidationErrorResponse(BaseModel):
    """FastAPI's own 422 for a malformed request (before any handler runs)."""

    detail: list[ValidationIssue]


_ERROR_MODELS: dict[int, Any] = {
    401: AuthErrorResponse,
    403: AuthErrorResponse,
    404: SavedTripErrorResponse,
    409: SavedTripErrorResponse,
    410: SavedTripErrorResponse,
    413: SavedTripErrorResponse,
    # A malformed request is FastAPI's shape; a well-formed but rejected one is ours.
    422: SavedTripErrorResponse | RequestValidationErrorResponse,
    503: SavedTripErrorResponse,
}


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    """The ``responses=`` declaration for a route's documented failure statuses."""
    return {status_code: {"model": _ERROR_MODELS[status_code]} for status_code in statuses}


def _error(
    status_code: int, code: SavedTripErrorCode, message: str, **extra: str
) -> HTTPException:
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
    except UnknownRevisionError as exc:
        raise _error(
            status.HTTP_404_NOT_FOUND, "REVISION_NOT_FOUND", "No such revision."
        ) from exc
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
    def of(cls, revision: RevisionMeta) -> RevisionSummaryOut:
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
    def of_stored(cls, revision: TripRevision) -> RevisionOut:
        summary = RevisionSummaryOut.of(RevisionMeta.of(revision))
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
    def of(cls, trip: SavedTrip, revisions: list[RevisionMeta]) -> TripSummaryOut:
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

    @classmethod
    def detail(cls, overview: TripOverview) -> TripDetailOut:
        summary = TripSummaryOut.of(overview.trip, overview.revisions)
        return cls(
            **summary.model_dump(),
            revisions=[RevisionSummaryOut.of(m) for m in overview.revisions],
        )


class SavedTripCreatedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trip: TripSummaryOut
    revision: RevisionOut


def _created(result: SavedTripResult) -> SavedTripCreatedOut:
    return SavedTripCreatedOut(
        trip=TripSummaryOut.of(result.trip, [RevisionMeta.of(result.revision)]),
        revision=RevisionOut.of_stored(result.revision),
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
    # Same rule as the conversation API: attaching a trip exempts a session from
    # expiry for good, so an expired, unattached session must not be revivable.
    if session.expires_at <= now_utc() and session.saved_trip_id is None:
        raise _error(status.HTTP_410_GONE, "SESSION_EXPIRED", "Planning session has expired")
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


@router.post(
    "",
    response_model=SavedTripCreatedOut,
    status_code=201,
    responses=_errors(401, 403, 404, 409, 410, 413, 422, 503),
)
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


@router.post(
    "/{trip_id}/revisions",
    response_model=RevisionOut,
    status_code=201,
    responses=_errors(401, 403, 404, 409, 410, 413, 422, 503),
)
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
            return RevisionOut.of_stored(TripRevision.model_validate_json(replay))

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
        return RevisionOut.of_stored(revision)

    appended: RevisionOut = _handle(call)
    return appended


# --------------------------------------------------------------------------- #
# Read routes                                                                   #
# --------------------------------------------------------------------------- #


@router.get("", response_model=list[TripSummaryOut], responses=_errors(401, 503))
def list_trips(
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> list[TripSummaryOut]:
    """The caller's saved trips, newest first. Summaries only: no report bodies."""
    listing: list[TripSummaryOut] = _handle(
        lambda: [TripSummaryOut.of(o.trip, o.revisions) for o in store.trip_overviews(user.id)]
    )
    return listing


@router.get(
    "/{trip_id}", response_model=TripDetailOut, responses=_errors(401, 404, 422, 503)
)
def get_trip(
    trip_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> TripDetailOut:
    detail: TripDetailOut = _handle(
        lambda: TripDetailOut.detail(store.trip_overview(user.id, trip_id))
    )
    return detail


@router.delete(
    "/{trip_id}", status_code=204, responses=_errors(401, 403, 404, 409, 422, 503)
)
def delete_trip(
    request: Request,
    trip_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
    client_event_id: Annotated[EventId | None, Query()] = None,
) -> Response:
    """Hard-delete a trip, all its revisions and the planning session attached to it.

    There is no tombstone. With a ``client_event_id`` a retried delete replays as 204
    rather than reporting the 404 a genuine second delete gets.
    """
    require_csrf(request)
    removed: bool = _handle(
        lambda: store.delete_trip(
            user.id,
            trip_id,
            client_event_id=client_event_id,
            request_fingerprint=trip_event_fingerprint("delete", trip_id=trip_id),
            now=now_utc(),
        )
    )
    if not removed:
        raise _trip_not_found()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{trip_id}/revisions/{revision}",
    response_model=RevisionOut,
    responses=_errors(401, 404, 422, 503),
)
def get_revision(
    trip_id: str,
    revision: int,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> RevisionOut:
    """One stored revision, with its report returned exactly as it was stored.

    The report is parsed as a plain JSON object and **not** validated through
    ``FinalReport``: a snapshot written under an older schema must read back as it
    was computed, flagged by ``is_current_schema``, not silently reshaped.
    """
    stored: RevisionOut = _handle(
        lambda: RevisionOut.of_stored(store.get_revision(user.id, trip_id, revision))
    )
    return stored


# --------------------------------------------------------------------------- #
# Re-run: fresh prices, appended server-side as the next revision                #
# --------------------------------------------------------------------------- #
#
# Jobs are process-local (``api.job_manager``), so everything below is too: after a
# restart a status request for a lost job is a typed 404 and the trip is simply
# unchanged. A revision is only ever appended by the worker once the job has
# completed with a report, so a half-written revision is impossible.

_MAX_REMEMBERED_RERUNS = 256
_RERUN_LOCK = threading.Lock()


@dataclass
class _Rerun:
    job_id: str
    trip_id: str
    user_id: str
    revision: int | None = None
    error: tuple[str, str] | None = None
    finished: bool = False


_RERUNS: dict[str, _Rerun] = {}
_ACTIVE_BY_TRIP: dict[str, str] = {}
# (user_id, client_event_id) -> (request fingerprint, job_id). In memory only: a
# restart forgets the job anyway, so there is nothing durable to deduplicate.
_START_EVENTS: dict[tuple[str, str], tuple[str, str]] = {}


class RerunIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    client_event_id: EventId


class RerunStartedOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str


class RerunErrorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class RerunStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: Literal["queued", "running", "complete", "failed", "needs_clarification"]
    stage: str | None = None
    revision: int | None = None
    error: RerunErrorOut | None = None


def _prune_reruns() -> None:
    """Forget the oldest *finished* re-runs once too many are remembered (lock held)."""
    if len(_RERUNS) <= _MAX_REMEMBERED_RERUNS:
        return
    for job_id in [j for j, r in _RERUNS.items() if r.finished]:
        if len(_RERUNS) <= _MAX_REMEMBERED_RERUNS:
            break
        del _RERUNS[job_id]
        for key in [k for k, (_, j) in _START_EVENTS.items() if j == job_id]:
            del _START_EVENTS[key]


def _release_rerun(record: _Rerun, event_key: tuple[str, str] | None = None) -> None:
    with _RERUN_LOCK:
        if _ACTIVE_BY_TRIP.get(record.trip_id) == record.job_id:
            del _ACTIVE_BY_TRIP[record.trip_id]
        if event_key is not None:
            _START_EVENTS.pop(event_key, None)
            _RERUNS.pop(record.job_id, None)


def _append_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, UnknownTripError):
        return "TRIP_NOT_FOUND", "The trip was deleted before the re-run finished."
    if isinstance(exc, RevisionLimitReachedError):
        return "REVISION_LIMIT_REACHED", "This trip has reached its maximum number of revisions."
    if isinstance(exc, ReportTooLargeError):
        return "REPORT_TOO_LARGE", "This plan is too large to store."
    return "RERUN_NOT_SAVED", "The re-run finished but could not be saved."


def _append_rerun_result(record: _Rerun, store: AccountStore) -> None:
    """Append a completed re-run as the next revision, once, never raising.

    Idempotent on the job id (``rerun:<job_id>``), so a completion that fires twice
    appends one revision. A failed, clarification-needing or report-less job appends
    nothing.
    """
    state = job_manager.get_job(record.job_id)
    if state is None:
        return
    with state._lock:
        report = state.report if state.status == "complete" else None
    if report is None:
        return
    try:
        revision = store.add_revision(
            user_id=record.user_id,
            trip_id=record.trip_id,
            trace_id=report.trace_id,
            report_json=report.model_dump_json(),
            now=now_utc(),
            system_event_id=f"rerun:{record.job_id}",
            request_fingerprint=trip_event_fingerprint(
                "rerun_complete", trip_id=record.trip_id, fields={"job_id": record.job_id}
            ),
            operation="rerun_complete",
        )
        record.revision = revision.revision
    except Exception as exc:  # a worker thread must never die with an unrecorded outcome
        record.error = _append_error(exc)


def _rerun_worker(
    record: _Rerun, store: AccountStore, run_args: tuple[Any, ...], run_kwargs: Any
) -> None:
    from api.main import _run_job

    try:
        _run_job(record.job_id, *run_args, **run_kwargs)
        _append_rerun_result(record, store)
    finally:
        with _RERUN_LOCK:
            record.finished = True
            if _ACTIVE_BY_TRIP.get(record.trip_id) == record.job_id:
                del _ACTIVE_BY_TRIP[record.trip_id]


def _launch_rerun(store: AccountStore, user: User, record: _Rerun) -> None:
    snapshot = store.planning_session_for_trip(user.id, record.trip_id)
    session = (
        PlanningSession.model_validate_json(snapshot.payload_json) if snapshot is not None else None
    )
    if session is None or not session.confirmed_briefs:
        raise _error(
            status.HTTP_409_CONFLICT,
            "TRIP_NOT_RERUNNABLE",
            "This trip has no confirmed brief to plan again from.",
        )
    # Fresh prices means fresh inputs: the caller's *current* wallet replaces the one
    # frozen in the brief; everything else about the confirmed brief is kept.
    wallet = build_user_wallet(store.wallet_entries(user.id))
    latest = session.confirmed_briefs[-1]
    confirmed = compile_confirmed_input(
        latest.model_copy(update={"brief": latest.brief.model_copy(update={"wallet": wallet})})
    )
    from api.main import (
        get_booking_date,
        get_kb,
        get_llm,
        get_place_registry,
        get_trace_dir,
    )

    kb = get_kb()
    service = build_travel_service(
        kb,
        plan_id=f"{session.id}:rerun:{record.job_id}",
        country=session.home.home_country,
        now=lambda: datetime.now(UTC),
    )
    request = TripIntakeRequest(raw_request=confirmed.raw_request, wallet=wallet)
    job_manager.create_job(record.job_id, owner_id=user.id, session_id=session.id)
    thread = threading.Thread(
        target=_rerun_worker,
        args=(
            record,
            store,
            (request, kb, get_llm(), get_place_registry(), get_booking_date(), get_trace_dir()),
            {"confirmed_input": confirmed, "inventory_service": service},
        ),
        daemon=True,
    )
    thread.start()


@router.post(
    "/{trip_id}/reruns",
    response_model=RerunStartedOut,
    status_code=202,
    responses=_errors(401, 403, 404, 409, 422, 503),
)
def start_rerun(
    request: Request,
    trip_id: str,
    payload: RerunIn,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> RerunStartedOut:
    """Plan a saved trip again with current prices; the result becomes the next revision."""
    require_csrf(request)
    overview: TripOverview = _handle(lambda: store.trip_overview(user.id, trip_id))
    fingerprint = trip_event_fingerprint("rerun", trip_id=trip_id)
    event_key = (user.id, payload.client_event_id)
    record = _Rerun(job_id=uuid4().hex, trip_id=trip_id, user_id=user.id)
    with _RERUN_LOCK:
        prior = _START_EVENTS.get(event_key)
        if prior is not None:
            if prior[0] != fingerprint:
                raise _error(
                    status.HTTP_409_CONFLICT,
                    "IDEMPOTENCY_KEY_REUSED",
                    "This client event id was already used for a different request.",
                )
            return RerunStartedOut(job_id=prior[1])
        if trip_id in _ACTIVE_BY_TRIP:
            raise _error(
                status.HTTP_409_CONFLICT,
                "RERUN_IN_PROGRESS",
                "This trip is already being planned again. Wait for it to finish.",
            )
        if len(overview.revisions) >= account_store.revision_limit():
            raise _error(
                status.HTTP_409_CONFLICT,
                "REVISION_LIMIT_REACHED",
                "This trip has reached its maximum number of revisions.",
            )
        _ACTIVE_BY_TRIP[trip_id] = record.job_id
        _RERUNS[record.job_id] = record
        _START_EVENTS[event_key] = (fingerprint, record.job_id)
        _prune_reruns()
    try:
        # Its store reads (attached session, wallet) are database work like any other:
        # a locked database must be the typed 503, not an unmapped 500.
        _handle(lambda: _launch_rerun(store, user, record))
    except BaseException:
        _release_rerun(record, event_key)
        raise
    return RerunStartedOut(job_id=record.job_id)


@router.get(
    "/{trip_id}/reruns/{job_id}",
    response_model=RerunStatusOut,
    responses=_errors(401, 404, 422, 503),
)
def rerun_status(
    trip_id: str,
    job_id: str,
    user: Annotated[User, Depends(current_user)],
    store: Annotated[AccountStore, Depends(get_store)],
) -> RerunStatusOut:
    """Progress of a re-run. After a restart the job is unknown (404); the trip is unchanged."""
    _handle(lambda: store.get_trip(user.id, trip_id))
    record = _RERUNS.get(job_id)
    state = job_manager.get_job(job_id)
    if record is None or state is None or record.user_id != user.id or record.trip_id != trip_id:
        raise _error(status.HTTP_404_NOT_FOUND, "RERUN_NOT_FOUND", "No such re-run.")
    with state._lock:
        job_status = state.status
        stage = state.stage
        job_error = state.error
    error: RerunErrorOut | None = None
    if job_status == "failed" and job_error is not None:
        # The job manager stores whatever the worker handed it (a dict), validated
        # only when a status is built; do the same here.
        typed = JobError.model_validate(job_error)
        error = RerunErrorOut(code=typed.code, message=typed.message)
    elif job_status == "failed":
        error = RerunErrorOut(code="PIPELINE_ERROR", message="Planning failed.")
    if job_status == "complete":
        if not record.finished:
            job_status = "running"  # computed, not yet saved as a revision
        elif record.error is not None:
            job_status = "failed"
            error = RerunErrorOut(code=record.error[0], message=record.error[1])
    return RerunStatusOut(
        job_id=job_id,
        status=job_status,
        stage=stage,
        revision=record.revision if job_status == "complete" else None,
        error=error,
    )
