"""Shared, provider-neutral acquisition workflow contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, Sequence

from agents.llm import LLMClient
from ingestion.contracts import FetchRequest, FetchResult, WatchTarget


class AcquisitionClaim(Protocol):
    state: Literal["dispatch", "replay", "blocked", "pending", "conflict"]
    safe_diagnostic: str
    replay_result: FetchResult | None


class AcquisitionControl(Protocol):
    """Durable reservation/replay boundary for paid document acquisition."""

    def claim(
        self, request: FetchRequest, *, policy_hash: str, estimated_credits: int, now: datetime
    ) -> AcquisitionClaim: ...

    def complete(
        self, request_id: str, *, result: FetchResult, charged_credits: int | None, now: datetime
    ) -> None: ...

    def mark_dispatch_started(self, request_id: str, *, now: datetime) -> None: ...

    def due_targets(
        self, targets: Sequence[WatchTarget], *, now: datetime, limit: int
    ) -> list[str]: ...


class AcquisitionOutcome(Protocol):
    state: Literal[
        "completed", "unchanged", "blocked", "failed", "pending", "needs_reconciliation"
    ]
    request_id: str
    attempt_id: str | None
    snapshot_id: str | None
    proposal_ids: tuple[str, ...]
    safe_diagnostic: str


class AcquisitionService(Protocol):
    """The sole public orchestration seam for target-to-review acquisition."""

    def run_target(
        self, target_id: str, *, client_event_id: str, extractor_client: LLMClient
    ) -> AcquisitionOutcome: ...
