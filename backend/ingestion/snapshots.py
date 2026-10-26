"""Snapshot capture, immutable manifests, and lineage-aware diff helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime

from ingestion.artifacts import ContentAddressedStore
from ingestion.contracts import FetchAttempt, FetchResult, SnapshotBundle
from ingestion.diff import SnapshotDiff, diff_text
from ingestion.storage import FinancialIngestionStore


class SnapshotService:
    def __init__(
        self,
        *,
        store: FinancialIngestionStore,
        artifacts: ContentAddressedStore,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.artifacts = artifacts
        self.now = now or (lambda: datetime.now(UTC))

    def capture(
        self,
        *,
        target_id: str,
        result: FetchResult,
        attempt: FetchAttempt,
    ) -> SnapshotBundle | None:
        self.store.put_fetch_attempt(attempt)
        if (
            result.failure is not None
            or result.raw_artifact is None
            or result.normalized_artifact is None
        ):
            return None
        self.artifacts.read(result.raw_artifact)
        normalized_bytes = self.artifacts.read(result.normalized_artifact)
        if normalized_bytes != result.normalized_text.encode("utf-8"):
            raise ValueError("normalized artifact does not match the fetch result text")
        normalized_hash = hashlib.sha256(result.normalized_text.encode("utf-8")).hexdigest()
        snapshot_id = f"snapshot:{target_id}:{normalized_hash}"
        existing = self.store.get_snapshot(snapshot_id)
        if existing is not None:
            return existing
        snapshot = SnapshotBundle(
            snapshot_id=snapshot_id,
            target_id=target_id,
            captured_at=self.now(),
            raw_artifact=result.raw_artifact,
            normalized_artifact=result.normalized_artifact,
            raw_sha256=result.raw_artifact.sha256,
            normalized_sha256=normalized_hash,
            canonical_markdown=result.normalized_text,
            extraction_engine=result.engine,
            extraction_engine_version=result.engine_version,
            attempts=(attempt,),
            supersedes_snapshot_id=self.store.latest_snapshot_id(target_id),
        )
        return self.store.put_snapshot(snapshot)

    def compare(self, *, target_id: str, current: FetchResult) -> SnapshotDiff:
        previous = self.store.latest_snapshot(target_id)
        return diff_text(
            None if previous is None else previous.canonical_markdown, current.normalized_text
        )
