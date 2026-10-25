"""Post-plan orchestration service (CP4): workspace creation, loading and recovery.

Everything here is deterministic orchestration over the account store. It owns the rules
for turning a finished job or a saved revision into a durable workspace and for reading
one back safely. It makes no model or provider call. HTTP concerns (status codes, error
bodies) belong to the router; this module raises typed domain errors instead.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from pydantic import ValidationError

from accounts.models import (
    PostPlanOperation,
    PostPlanResult,
    PostPlanWorkspaceSnapshot,
)
from accounts.store import AccountStore
from agents.confirmed_trip import compile_confirmed_input
from agents.models import FinalReport
from agents.post_plan_models import (
    PostPlanWorkspace,
    RetainedInventory,
    WorkspaceSource,
    report_schema_fingerprint,
)
from api.job_manager import job_manager
from planning.contracts import PlanningSession
from planning.post_plan import flight_fingerprint, hotel_fingerprint


class WorkspaceError(Exception):
    """Base for the typed outcomes the router maps to responses."""

    code = "WORKSPACE_ERROR"


class SessionNotConfirmedError(WorkspaceError):
    code = "SESSION_NOT_CONFIRMED"


class PlanUnavailableError(WorkspaceError):
    """The finished plan is no longer in memory (or never finished). Never reconstructed."""

    code = "PLAN_RESULT_UNAVAILABLE"


class SessionNotAttachedError(WorkspaceError):
    code = "SESSION_NOT_ATTACHED"


class WorkspaceRebuildRequiredError(WorkspaceError):
    """History is readable but cannot be edited through today's models; rebuild it."""

    code = "WORKSPACE_REBUILD_REQUIRED"

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class LoadedWorkspace:
    """A workspace with its opaque payloads validated on entry."""

    snapshot: PostPlanWorkspaceSnapshot
    workspace: PostPlanWorkspace
    report: FinalReport
    result: PostPlanResult


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def initialize_fingerprint(source: WorkspaceSource) -> str:
    """Identity of an initialise request: what it was built from, never generated ids."""
    canonical = json.dumps(
        {"operation": "initialize", "source": source.model_dump(mode="json")},
        sort_keys=True,
        separators=(",", ":"),
    )
    return _sha256(canonical)


def owned_finished_report(session: PlanningSession, user_id: str) -> FinalReport:
    """The report of this session's finished job, or a typed refusal. Never rebuilt."""
    if not session.confirmed_briefs or session.planning_job_id is None:
        raise SessionNotConfirmedError("confirm the brief and let planning finish first")
    state = job_manager.get_job(session.planning_job_id)
    if state is None or state.owner_id != user_id or state.session_id != session.id:
        raise PlanUnavailableError("the plan result is no longer available")
    with state._lock:
        report = state.report
    if report is None or report.travel_inventory is None:
        raise PlanUnavailableError("the plan has not finished with admitted inventory")
    return report


def parse_stored_report(report_json: str) -> FinalReport:
    """Validate stored report bytes against today's model, requiring an exact round trip.

    A stored report that today's ``FinalReport`` would coerce, default or drop fields of
    is not edited: it stays readable verbatim elsewhere and must be rebuilt.
    """
    try:
        report = FinalReport.model_validate_json(report_json)
    except ValidationError as exc:
        raise WorkspaceRebuildRequiredError("the stored plan uses an older report shape") from exc
    if json.loads(report.model_dump_json()) != json.loads(report_json):
        raise WorkspaceRebuildRequiredError("the stored plan differs from the current report shape")
    return report


def _initial_state(
    *,
    user_id: str,
    session: PlanningSession,
    report: FinalReport,
    report_json: str,
    source: WorkspaceSource,
    now: datetime,
    new_id: Callable[[], str],
    brief_override_wallet: bool,
    inventory_snapshot_json: str | None = None,
) -> tuple[PostPlanWorkspaceSnapshot, PostPlanResult, PostPlanOperation]:
    confirmed = session.confirmed_briefs[-1]
    brief = confirmed.brief
    if brief_override_wallet:
        # A saved revision may have been planned with a later wallet; the report is truth.
        brief = brief.model_copy(update={"wallet": report.trip_spec.wallet})
    area = report.itinerary.hotel_area_id
    workspace = PostPlanWorkspace(
        session_id=session.id,
        user_id=user_id,
        confirmed_brief_revision=confirmed.revision,
        source=source,
        brief=brief,
        inventory=RetainedInventory(
            flight_fingerprint=flight_fingerprint(brief),
            hotel_fingerprint=hotel_fingerprint(brief, hotel_area_id=area),
            retained_hotel_area_id=area,
            snapshot_json=inventory_snapshot_json,
        ),
        report_schema_fingerprint=report_schema_fingerprint(),
        created_at=now,
        updated_at=now,
    )
    result_id = new_id()
    snapshot = PostPlanWorkspaceSnapshot(
        session_id=session.id,
        user_id=user_id,
        version=1,
        current_result_id=result_id,
        created_at=now,
        updated_at=now,
        expires_at=session.expires_at,
        saved_trip_id=session.saved_trip_id,
        payload_json=workspace.model_dump_json(),
    )
    result = PostPlanResult(
        result_id=result_id,
        user_id=user_id,
        session_id=session.id,
        created_at=now,
        report_sha256=_sha256(report_json),
        report_json=report_json,
    )
    operation = PostPlanOperation(
        operation_id=new_id(),
        user_id=user_id,
        session_id=session.id,
        kind="initialize",
        event_id=f"init:{session.id}",
        event_source="system",
        fingerprint=initialize_fingerprint(source),
        status="complete",
        expected_workspace_version=0,
        expected_session_version=session.version,
        reserved_workspace_version=None,
        result_id=result_id,
        created_at=now,
        updated_at=now,
    )
    return snapshot, result, operation


def initialize_from_job(
    store: AccountStore,
    *,
    user_id: str,
    session: PlanningSession,
    now: datetime,
    new_id: Callable[[], str] = lambda: uuid4().hex,
) -> tuple[PostPlanWorkspaceSnapshot, bool]:
    """Create the workspace from this session's finished job. Calls nothing external."""
    report = owned_finished_report(session, user_id)
    assert session.planning_job_id is not None
    job = job_manager.get_job(session.planning_job_id)
    inventory_snapshot_json = (
        job.inventory_snapshot.model_dump_json()
        if job is not None and job.inventory_snapshot is not None
        else None
    )
    source = WorkspaceSource(kind="job", job_id=session.planning_job_id)
    snapshot, result, operation = _initial_state(
        user_id=user_id,
        session=session,
        report=report,
        report_json=report.model_dump_json(),
        source=source,
        now=now,
        new_id=new_id,
        brief_override_wallet=False,
        inventory_snapshot_json=inventory_snapshot_json,
    )
    return store.create_post_plan_workspace(
        workspace=snapshot, result=result, operation=operation
    )


def initialize_from_saved_revision(
    store: AccountStore,
    *,
    user_id: str,
    session: PlanningSession,
    trip_id: str,
    revision: int,
    now: datetime,
    new_id: Callable[[], str] = lambda: uuid4().hex,
) -> tuple[PostPlanWorkspaceSnapshot, bool]:
    """Create the workspace from a saved revision of the trip this session is attached to.

    The stored report bytes are used verbatim. They must round-trip through today's
    report model and agree with the session's confirmed brief on the trip's identity;
    otherwise a typed rebuild requirement is raised and nothing is written.
    """
    if session.saved_trip_id != trip_id:
        raise SessionNotAttachedError("this session is not the one the trip was saved from")
    if not session.confirmed_briefs:
        raise SessionNotConfirmedError("this session has no confirmed brief")
    stored = store.get_revision(user_id, trip_id, revision)  # 404-equivalent when not ours
    report = parse_stored_report(stored.report_json)
    expected = compile_confirmed_input(session.confirmed_briefs[-1]).expected_fields
    actual = report.trip_spec.model_dump(mode="python")
    for name in (
        "home_country",
        "origin_city",
        "destination_city",
        "start_date",
        "end_date",
        "travelers",
    ):
        if actual[name] != expected[name]:
            raise WorkspaceRebuildRequiredError(
                "the saved revision was planned for a different trip than this session's brief"
            )
    source = WorkspaceSource(kind="saved_revision", trip_id=trip_id, revision=revision)
    snapshot, result, operation = _initial_state(
        user_id=user_id,
        session=session,
        report=report,
        report_json=stored.report_json,
        source=source,
        now=now,
        new_id=new_id,
        brief_override_wallet=True,
    )
    return store.create_post_plan_workspace(
        workspace=snapshot, result=result, operation=operation
    )


def load_workspace(
    store: AccountStore, *, user_id: str, session_id: str
) -> LoadedWorkspace | None:
    """Read a workspace and validate its opaque payloads. ``None`` if there is none.

    A workspace built under a different report shape raises the rebuild requirement
    rather than being loaded through a model that would coerce it.
    """
    snapshot = store.get_post_plan_workspace(user_id=user_id, session_id=session_id)
    if snapshot is None:
        return None
    try:
        workspace = PostPlanWorkspace.model_validate_json(snapshot.payload_json)
    except ValidationError as exc:
        raise WorkspaceRebuildRequiredError("the workspace uses an older shape") from exc
    if workspace.report_schema_fingerprint != report_schema_fingerprint():
        raise WorkspaceRebuildRequiredError(
            "the workspace was built under a different report shape"
        )
    result = store.get_post_plan_result(
        user_id=user_id, session_id=session_id, result_id=snapshot.current_result_id
    )
    if result is None:
        raise WorkspaceRebuildRequiredError("the workspace's current result is missing")
    report = parse_stored_report(result.report_json)
    return LoadedWorkspace(snapshot=snapshot, workspace=workspace, report=report, result=result)


# Reservations this process is genuinely running. Anything the store holds as "reserved"
# that is not in here belongs to a worker that no longer exists (a restart) and is
# marked interrupted rather than dispatched again.
_ACTIVE: set[str] = set()
_ACTIVE_LOCK = threading.Lock()


def mark_active(operation_id: str) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE.add(operation_id)


def mark_finished(operation_id: str) -> None:
    with _ACTIVE_LOCK:
        _ACTIVE.discard(operation_id)


def active_operation_ids() -> frozenset[str]:
    with _ACTIVE_LOCK:
        return frozenset(_ACTIVE)


def recover_interrupted(
    store: AccountStore, *, user_id: str, session_id: str, now: datetime
) -> list[PostPlanOperation]:
    """Mark reservations that outlived their worker as interrupted. Never redispatches."""
    return store.interrupt_stale_post_plan_operations(
        user_id=user_id,
        session_id=session_id,
        active_operation_ids=active_operation_ids(),
        updated_at=now,
    )
