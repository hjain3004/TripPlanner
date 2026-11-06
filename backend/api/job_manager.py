"""Planning-job lifecycle: durable for owned jobs, in memory for anonymous ones.

Two kinds of job exist and they do not have the same persistence needs:

* **Owned jobs** (a confirmed brief, or a saved-trip re-run) belong to an authenticated
  user, are bounded by that user's privacy export/deletion, and are stored in the accounts
  database (``accounts.PlanningJob``). Their status and report survive a restart.
* **Anonymous jobs** (``POST /plan`` without an account) have no owner to export, delete or
  authorize, so persisting them would create ownerless personal data with no lifecycle. They
  stay process-local and are simply gone after a restart (404), as before.

Execution is single process: one thread per job, started only after the row is committed.
A queued or running row whose ``process_id`` is not this process has lost its worker; it is
reported as interrupted (``JOB_INTERRUPTED``) and is **never** resumed or dispatched again,
because whether model or provider calls were already made cannot be established. Retrying is
a new, explicit traveler action that creates a new job. Only the process that owns a live
row can publish to it, and every write is a guarded update, so a late or stale completion
cannot overwrite newer state or recreate deleted data.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from accounts.models import JOB_INTERRUPTED_CODE, PlanningJob
from accounts.store import AccountStore
from agents.models import PIPELINE_STAGES, FinalReport, JobError, PlanJobStatus
from gateway.travel.product import TravelInventorySnapshot, TravelInventorySummary

logger = logging.getLogger(__name__)

_WRITE_ATTEMPTS = 3


class JobFinalizeError(Exception):
    """A finalizer could not complete the job's side effect; the job is published failed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


Finalizer = Callable[[FinalReport], dict[str, int]]


class JobState:
    """A job as callers see it. For owned jobs this is a snapshot read from the database."""

    def __init__(
        self,
        *,
        owner_id: str | None = None,
        session_id: str | None = None,
        kind: str = "confirmed",
        trip_id: str | None = None,
    ) -> None:
        self.owner_id = owner_id
        self.session_id = session_id
        self.kind = kind
        self.trip_id = trip_id
        self.revision: int | None = None
        self.interrupted = False
        self.status: str = "queued"
        self.stage: str | None = None
        self.stage_index: int | None = None
        self.stages_total: int = len(PIPELINE_STAGES)
        self.unresolved: list[str] | None = None
        self.report: FinalReport | None = None
        self.error: JobError | dict[str, str] | None = None
        self.inventory_summary: TravelInventorySummary | None = None
        self.inventory_snapshot: TravelInventorySnapshot | None = None
        self._lock = threading.Lock()

    @classmethod
    def from_record(cls, job: PlanningJob) -> JobState:
        state = cls(
            owner_id=job.user_id,
            session_id=job.session_id,
            kind=job.kind,
            trip_id=job.trip_id,
        )
        state.revision = job.revision
        state.interrupted = job.status == "interrupted"
        # The public status vocabulary is unchanged: an interrupted job reads as "failed"
        # carrying the JOB_INTERRUPTED code, which is what existing consumers already treat
        # as terminal and retryable through the normal confirm / re-run action.
        state.status = "failed" if state.interrupted else job.status
        state.stage = job.stage
        state.stage_index = job.stage_index
        state.unresolved = job.unresolved
        if job.error_code is not None:
            state.error = {
                "code": job.error_code,
                "message": job.error_message or "",
                "trace_id": job.error_trace_id or "",
            }
        if job.report_json is not None:
            try:
                state.report = FinalReport.model_validate_json(job.report_json)
            except ValidationError:
                # A stored plan this build can no longer read is reported, not reshaped.
                state.report = None
                state.status = "failed"
                state.error = {
                    "code": "REPORT_UNREADABLE",
                    "message": "The stored plan can no longer be read; plan again.",
                    "trace_id": "",
                }
        if job.inventory_snapshot_json is not None:
            try:
                state.inventory_snapshot = TravelInventorySnapshot.model_validate_json(
                    job.inventory_snapshot_json
                )
            except ValidationError:
                state.inventory_snapshot = None
        return state

    def to_status(self, job_id: str) -> PlanJobStatus:
        with self._lock:
            return PlanJobStatus(
                job_id=job_id,
                status=self.status,
                stage=self.stage,
                stage_index=self.stage_index,
                stages_total=self.stages_total,
                unresolved=self.unresolved,
                report=self.report,
                error=JobError.model_validate(self.error) if self.error is not None else None,
            )


class JobManager:
    def __init__(self, process_id: str | None = None) -> None:
        # Identifies this process's executions. A fresh value per process (or per test
        # "restart") is what lets rows left by a dead worker be recognised as lost.
        self.process_id = process_id or uuid4().hex
        self._memory: dict[str, JobState] = {}
        self._stores: dict[str, AccountStore] = {}
        self._finalizers: dict[str, Finalizer] = {}
        self._inventory: dict[str, tuple[TravelInventorySummary | None, str | None]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _now() -> datetime:
        from api.auth import now_utc

        return now_utc()

    # -- creation ------------------------------------------------------------ #

    def create_job(
        self,
        job_id: str | None = None,
        *,
        owner_id: str | None = None,
        session_id: str | None = None,
        store: AccountStore | None = None,
        kind: str = "confirmed",
        trip_id: str | None = None,
        finalizer: Finalizer | None = None,
    ) -> str:
        """Create a job. Owned (store + owner) jobs are committed before this returns."""
        job_id = job_id or uuid4().hex
        if store is not None and owner_id is not None and session_id is not None:
            self.start_job(
                job_id,
                owner_id=owner_id,
                session_id=session_id,
                store=store,
                kind=kind,
                trip_id=trip_id,
                finalizer=finalizer,
            )
            return job_id
        with self._lock:
            if job_id not in self._memory:
                self._memory[job_id] = JobState(owner_id=owner_id, session_id=session_id)
        return job_id

    def start_job(
        self,
        job_id: str,
        *,
        owner_id: str,
        session_id: str,
        store: AccountStore,
        kind: str = "confirmed",
        trip_id: str | None = None,
        start_event_id: str | None = None,
        start_fingerprint: str | None = None,
        one_live_per_trip: bool = False,
        finalizer: Finalizer | None = None,
    ) -> tuple[str, bool]:
        """Commit a queued owned job. ``(job_id, created)``; ``created=False`` is a replay.

        On a replay the original job id is returned and nothing may be dispatched.
        """
        # The worker handle is registered *before* the row is committed, so a live job of this
        # process always has one (an active row without one is an orphan; see ``get_job``).
        with self._lock:
            self._stores[job_id] = store
            if finalizer is not None:
                self._finalizers[job_id] = finalizer
        now = self._now()
        record = PlanningJob(
            job_id=job_id,
            user_id=owner_id,
            session_id=session_id,
            kind=kind,
            trip_id=trip_id,
            process_id=self.process_id,
            start_event_id=start_event_id,
            start_fingerprint=start_fingerprint,
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            live_ids = frozenset(self._stores) - {job_id}
        try:
            stored, created = store.start_planning_job(
                record, one_live_per_trip=one_live_per_trip, live_job_ids=live_ids
            )
        except BaseException:
            self._forget(job_id)
            raise
        if not created:  # a replay: the original job's own handle (if any) is not ours to replace
            self._forget(job_id)
        return stored.job_id, created

    def _forget(self, job_id: str) -> None:
        with self._lock:
            self._stores.pop(job_id, None)
            self._finalizers.pop(job_id, None)
            self._inventory.pop(job_id, None)

    # -- reading ------------------------------------------------------------- #

    def get_job(self, job_id: str, store: AccountStore | None = None) -> JobState | None:
        with self._lock:
            memory = self._memory.get(job_id)
        if memory is not None:
            return memory
        if store is None:
            return None
        with self._lock:
            worker_alive = job_id in self._stores
        record = store.get_planning_job(
            job_id, process_id=self.process_id, now=self._now(), worker_alive=worker_alive
        )
        return None if record is None else JobState.from_record(record)

    # -- worker-side updates -------------------------------------------------- #

    def _durable_store(self, job_id: str) -> AccountStore | None:
        with self._lock:
            return self._stores.get(job_id)

    @staticmethod
    def _retry(job_id: str, action: str, write: Callable[[], bool]) -> bool:
        for attempt in range(_WRITE_ATTEMPTS):
            try:
                return write()
            except OperationalError:
                if attempt + 1 == _WRITE_ATTEMPTS:
                    logger.exception("job %s: %s could not be written", job_id, action)
                    return False
                time.sleep(0.2 * (attempt + 1))
            except Exception:  # never let a failed write kill the worker with the job unrecorded
                logger.exception("job %s: %s could not be written", job_id, action)
                return False
        return False

    def set_stage(self, job_id: str, stage_index: int, stage: str) -> None:
        store = self._durable_store(job_id)
        if store is not None:
            self._retry(
                job_id,
                "stage",
                lambda: store.advance_planning_job(
                    job_id,
                    process_id=self.process_id,
                    stage=stage,
                    stage_index=stage_index,
                    now=self._now(),
                ),
            )
            return
        state = self.get_job(job_id)
        if state is not None:
            with state._lock:
                state.status = "running"
                state.stage = stage
                state.stage_index = stage_index

    def record_inventory(self, job_id: str, result: object) -> None:
        """Hold the admitted-inventory evidence until the job finishes (persisted with it)."""
        summary = getattr(result, "summary", None)
        snapshot = getattr(result, "snapshot", None)
        if self._durable_store(job_id) is not None:
            snapshot_json = snapshot.model_dump_json() if snapshot is not None else None
            with self._lock:
                self._inventory[job_id] = (summary, snapshot_json)
            return
        state = self.get_job(job_id)
        if state is not None:
            with state._lock:
                state.inventory_summary = summary
                if snapshot is not None:
                    state.inventory_snapshot = snapshot.model_copy(deep=True)

    def complete(self, job_id: str, status: str, **kwargs: object) -> None:
        store = self._durable_store(job_id)
        if store is None:
            state = self.get_job(job_id)
            if state is not None:
                with state._lock:
                    state.status = status
                    for key, val in kwargs.items():
                        setattr(state, key, val)
            return
        try:
            self._complete_durable(job_id, store, status, kwargs)
        finally:
            # Whatever happened above, this process no longer has a worker for the job; an
            # active row left behind then reads as interrupted instead of running forever.
            with self._lock:
                self._stores.pop(job_id, None)
                self._finalizers.pop(job_id, None)
                self._inventory.pop(job_id, None)

    def _complete_durable(
        self, job_id: str, store: AccountStore, status: str, kwargs: dict[str, object]
    ) -> None:
        with self._lock:
            finalizer = self._finalizers.pop(job_id, None)
            _summary, snapshot_json = self._inventory.pop(job_id, (None, None))
        report = kwargs.get("report")
        error = kwargs.get("error")
        revision: int | None = None
        if status == "complete" and isinstance(report, FinalReport) and finalizer is not None:
            try:
                revision = finalizer(report).get("revision")
            except JobFinalizeError as exc:
                trace_id = report.trace_id
                status, report = "failed", None
                error = {"code": exc.code, "message": exc.message, "trace_id": trace_id}
        outcome: str = status
        written = self._retry(
            job_id,
            "completion",
            lambda: store.finish_planning_job(
                job_id,
                process_id=self.process_id,
                status=outcome,  # type: ignore[arg-type]
                now=self._now(),
                report_json=report.model_dump_json() if isinstance(report, FinalReport) else None,
                unresolved=kwargs.get("unresolved"),  # type: ignore[arg-type]
                error=_error_dict(error),
                inventory_snapshot_json=snapshot_json if outcome == "complete" else None,
                revision=revision,
            ),
        )
        if not written:
            logger.warning(
                "job %s: completion discarded (interrupted, already finished or deleted)", job_id
            )

    def replace_report(
        self,
        job_id: str,
        *,
        store: AccountStore,
        owner_id: str,
        report: FinalReport,
        expected_inventory_revision: int,
    ) -> bool:
        """Persist a traveler's edit of a finished job's report; ``False`` if it did not apply."""
        return store.replace_planning_job_report(
            job_id,
            user_id=owner_id,
            report_json=report.model_dump_json(),
            expected_inventory_revision=expected_inventory_revision,
            now=self._now(),
        )

    # -- restart reconciliation ------------------------------------------------ #

    def reconcile(self, store: AccountStore) -> list[str]:
        """Mark every job a previous process left queued or running as interrupted."""
        return store.interrupt_orphaned_planning_jobs(process_id=self.process_id, now=self._now())


def _error_dict(error: object) -> dict[str, str] | None:
    if error is None:
        return None
    typed = JobError.model_validate(error)
    return {"code": typed.code, "message": typed.message, "trace_id": typed.trace_id}


job_manager = JobManager()

__all__ = [
    "JOB_INTERRUPTED_CODE",
    "Finalizer",
    "JobFinalizeError",
    "JobManager",
    "JobState",
    "job_manager",
]
