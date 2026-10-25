"""Orchestration-side post-plan state (CP4).

``accounts`` stores a workspace, its accepted results and its operations as opaque JSON.
These models are what that JSON means. They live here, not in ``accounts``, because only
orchestration understands reports, briefs and normalized inventory; the account layer
must stay independent of all three.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agents.models import FinalReport
from planning.contracts import TripBrief
from planning.post_plan import DayOverride


def report_schema_fingerprint() -> str:
    """Identity of the report shape this code understands.

    Stored on every workspace. If the report model later changes shape, a workspace
    built under the old one is recognised as needing a rebuild instead of being edited
    through a model that would silently coerce, default or drop its fields.
    """
    canonical = json.dumps(
        FinalReport.model_json_schema(), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class WorkspaceSource(BaseModel):
    """Where the workspace's first result came from."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["job", "saved_revision"]
    job_id: str | None = None
    trip_id: str | None = None
    revision: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def source_is_complete(self) -> WorkspaceSource:
        if self.kind == "job" and (self.job_id is None or self.trip_id or self.revision):
            raise ValueError("a job source names exactly a job id")
        if self.kind == "saved_revision" and (
            self.trip_id is None or self.revision is None or self.job_id
        ):
            raise ValueError("a saved-revision source names a trip and a revision")
        return self


class RetainedInventory(BaseModel):
    """The admitted evidence a workspace may reuse, and the searches it answered.

    ``snapshot_json`` is the sanitized normalized snapshot the completed job actually
    admitted (filled in by the inventory-reuse milestone task); it is ``None`` whenever
    retention is not permitted or the evidence is unavailable, in which case nothing can
    be reused without an explicit review. Fingerprints identify the searches it answered.
    """

    model_config = ConfigDict(extra="forbid")
    flight_fingerprint: str | None = None
    hotel_fingerprint: str | None = None
    retained_hotel_area_id: str | None = None
    captured_at: datetime | None = None
    snapshot_json: str | None = None


class PostPlanWorkspace(BaseModel):
    """What the account layer's opaque ``payload_json`` holds for one session."""

    model_config = ConfigDict(extra="forbid")
    session_id: str
    user_id: str
    confirmed_brief_revision: Annotated[int, Field(ge=1)]
    source: WorkspaceSource
    brief: TripBrief
    day_overrides: list[DayOverride] = Field(default_factory=list)
    inventory: RetainedInventory | None = None
    report_schema_fingerprint: str
    created_at: datetime
    updated_at: datetime
