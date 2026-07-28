from __future__ import annotations

import threading
from uuid import uuid4

from agents.models import PIPELINE_STAGES, FinalReport, JobError, PlanJobStatus


class JobState:
    def __init__(self) -> None:
        self.status: str = "queued"
        self.stage: str | None = None
        self.stage_index: int | None = None
        self.stages_total: int = len(PIPELINE_STAGES)
        self.unresolved: list[str] | None = None
        self.report: FinalReport | None = None
        self.error: JobError | None = None
        self._lock = threading.Lock()

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
                error=self.error,
            )


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = threading.Lock()

    def create_job(self) -> str:
        job_id = uuid4().hex
        with self._lock:
            self._jobs[job_id] = JobState()
        return job_id

    def get_job(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def set_stage(self, job_id: str, stage_index: int, stage: str) -> None:
        state = self.get_job(job_id)
        if state is not None:
            with state._lock:
                state.status = "running"
                state.stage = stage
                state.stage_index = stage_index

    def complete(
        self,
        job_id: str,
        status: str,
        **kwargs: object,
    ) -> None:
        state = self.get_job(job_id)
        if state is not None:
            with state._lock:
                state.status = status
                for key, val in kwargs.items():
                    setattr(state, key, val)


job_manager = JobManager()
