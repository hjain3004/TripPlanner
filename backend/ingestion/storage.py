from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from ingestion.contracts import (
    ChangeProposal,
    CuratorRecord,
    DiscoveryCandidate,
    FetchAttempt,
    ProposalStatus,
    ReverifyTask,
    ReviewAttestation,
    ReviewDecision,
    ReviewDecisionStatus,
    SnapshotBundle,
    SourcePolicyRecord,
    WatchTarget,
)
from ingestion.migrations import migrate


class IngestionStoreError(Exception):
    pass


class StaleVersionError(IngestionStoreError):
    pass


class AlreadyDecidedError(IngestionStoreError):
    pass


class IdempotencyConflictError(IngestionStoreError):
    pass


class InvalidDecisionError(IngestionStoreError):
    pass


class ConflictingWriteError(IngestionStoreError):
    pass


_SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS source_policies (
    id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discovery_candidates (
    id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watch_targets (
    id TEXT PRIMARY KEY, source_policy_id TEXT NOT NULL REFERENCES source_policies(id),
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fetch_attempts (
    id TEXT PRIMARY KEY, request_id TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_manifests (
    id TEXT PRIMARY KEY, target_id TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS change_proposals (
    id TEXT PRIMARY KEY, status TEXT NOT NULL, version INTEGER NOT NULL,
    client_event_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    request_fingerprint TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS review_decisions (
    id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE REFERENCES change_proposals(id),
    client_event_id TEXT NOT NULL UNIQUE, request_fingerprint TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reverify_tasks (
    id TEXT PRIMARY KEY, target_id TEXT NOT NULL, client_event_id TEXT NOT NULL UNIQUE,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    event_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
    event_type TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON change_proposals(status);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_events(entity_type, entity_id);
CREATE TABLE IF NOT EXISTS curators (
    id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activation_bundles (
    id TEXT PRIMARY KEY, client_event_id TEXT NOT NULL UNIQUE,
    request_fingerprint TEXT NOT NULL, payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class FinancialIngestionStore:
    """Small SQLite queue store; it never opens or writes the approved KB."""

    def __init__(
        self,
        path: Path,
        *,
        now: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(UTC))
        self._id = id_factory or self._next_id
        self._ensure_schema()

    def _next_id(self) -> str:
        return f"evt-{uuid.uuid4().hex}"

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as connection:
            try:
                migrate(connection, _SCHEMA)
            except RuntimeError as error:
                raise IngestionStoreError(str(error)) from error

    @staticmethod
    def _payload(model: BaseModel) -> str:
        return model.model_dump_json()

    @staticmethod
    def proposal_payload_sha256(payload_json: str) -> str:
        return hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _fingerprint_request(
        *,
        proposal_id: str,
        reviewer_id: str,
        status: ReviewDecisionStatus,
        reason: str,
        expected_version: int,
        edits: dict[str, object] | None,
        curator_confidence: float | None = None,
    ) -> str:
        request: dict[str, object] = {
            "proposal_id": proposal_id,
            "reviewer_id": reviewer_id,
            "status": status.value,
            "reason": reason,
            "expected_version": expected_version,
            "edits": edits or {},
        }
        if curator_confidence is not None:
            request["curator_confidence"] = curator_confidence
        canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _insert_immutable(
        self,
        connection: sqlite3.Connection,
        *,
        table: str,
        key_column: str,
        entity_id: str,
        payload: str,
        insert_sql: str,
        audit_type: str,
    ) -> bool:
        existing = connection.execute(
            f"SELECT payload FROM {table} WHERE {key_column} = ?", (entity_id,)
        ).fetchone()
        if existing is not None:
            if existing[0] == payload:
                return False
            raise ConflictingWriteError(f"conflicting payload for immutable {table} {entity_id}")
        connection.execute(insert_sql, (entity_id, payload))
        self._audit(
            connection,
            entity_type=audit_type,
            entity_id=entity_id,
            event_type="created",
            payload=payload,
        )
        return True

    def _audit(
        self,
        connection: sqlite3.Connection,
        *,
        entity_type: str,
        entity_id: str,
        event_type: str,
        payload: str,
    ) -> None:
        for _attempt in range(3):
            event_id = self._id()
            try:
                connection.execute(
                    "INSERT INTO audit_events(event_id, entity_type, entity_id, event_type, "
                    "payload, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        entity_type,
                        entity_id,
                        event_type,
                        payload,
                        self._now().isoformat(),
                    ),
                )
                return
            except sqlite3.IntegrityError:
                # The default per-process sequence restarts after reopen; skip existing IDs.
                continue
        raise IngestionStoreError("unable to allocate a unique audit event id")

    def put_curator(self, curator: CuratorRecord) -> CuratorRecord:
        payload = self._payload(curator)
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT payload FROM curators WHERE id = ?", (curator.curator_id,)
            ).fetchone()
            if prior is not None and prior[0] != payload:
                raise ConflictingWriteError(f"conflicting curator {curator.curator_id}")
            if prior is None:
                connection.execute(
                    "INSERT INTO curators(id, payload) VALUES (?, ?)", (curator.curator_id, payload)
                )
                self._audit(
                    connection,
                    entity_type="curator",
                    entity_id=curator.curator_id,
                    event_type="created",
                    payload=payload,
                )
        return curator

    def get_curator(self, curator_id: str) -> CuratorRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM curators WHERE id = ?", (curator_id,)
            ).fetchone()
        return None if row is None else CuratorRecord.model_validate_json(row[0])

    def get_watch_target(self, target_id: str) -> WatchTarget | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM watch_targets WHERE id = ?", (target_id,)
            ).fetchone()
        return None if row is None else WatchTarget.model_validate_json(row[0])

    def get_source_policy(self, policy_id: str) -> SourcePolicyRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM source_policies WHERE id = ?", (policy_id,)
            ).fetchone()
        return None if row is None else SourcePolicyRecord.model_validate_json(row[0])

    def list_proposals(self, status: ProposalStatus | None = None) -> list[ChangeProposal]:
        with self._connect() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT payload FROM change_proposals ORDER BY rowid"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT payload FROM change_proposals WHERE status = ? ORDER BY rowid",
                    (status.value,),
                ).fetchall()
        return [ChangeProposal.model_validate_json(row[0]) for row in rows]

    def get_reverify_task(self, task_id: str) -> ReverifyTask | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM reverify_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return None if row is None else ReverifyTask.model_validate_json(row[0])

    def put_activation_bundle(
        self,
        record_json: str,
        *,
        bundle_sha256: str,
        client_event_id: str,
        request_fingerprint: str,
        created_by: str,
    ) -> str:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT payload, request_fingerprint FROM activation_bundles "
                "WHERE client_event_id = ?",
                (client_event_id,),
            ).fetchone()
            if prior is not None:
                if prior[1] != request_fingerprint:
                    raise IdempotencyConflictError(
                        "client event was already used for another bundle"
                    )
                return str(prior[0])
            existing = connection.execute(
                "SELECT payload FROM activation_bundles WHERE id = ?", (bundle_sha256,)
            ).fetchone()
            if existing is not None:
                return str(existing[0])
            connection.execute(
                "INSERT INTO activation_bundles(id, client_event_id, request_fingerprint, "
                "payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    bundle_sha256,
                    client_event_id,
                    request_fingerprint,
                    record_json,
                    self._now().isoformat(),
                ),
            )
            self._audit(
                connection,
                entity_type="activation_bundle",
                entity_id=bundle_sha256,
                event_type="created",
                payload=record_json,
            )
        return record_json

    def get_activation_bundle(self, bundle_sha256: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM activation_bundles WHERE id = ?", (bundle_sha256,)
            ).fetchone()
        return None if row is None else str(row[0])

    def put_source_policy(self, record: SourcePolicyRecord) -> SourcePolicyRecord:
        with self._connect() as connection:
            self._insert_immutable(
                connection,
                table="source_policies",
                key_column="id",
                entity_id=record.policy_id,
                payload=self._payload(record),
                insert_sql="INSERT INTO source_policies(id, payload) VALUES (?, ?)",
                audit_type="source_policy",
            )
        return record

    def put_discovery_candidate(self, candidate: DiscoveryCandidate) -> DiscoveryCandidate:
        with self._connect() as connection:
            self._insert_immutable(
                connection,
                table="discovery_candidates",
                key_column="id",
                entity_id=candidate.id,
                payload=self._payload(candidate),
                insert_sql="INSERT INTO discovery_candidates(id, payload) VALUES (?, ?)",
                audit_type="discovery_candidate",
            )
        return candidate

    def put_watch_target(self, target: WatchTarget) -> WatchTarget:
        with self._connect() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM source_policies WHERE id = ?", (target.source_policy_id,)
                ).fetchone()
                is None
            ):
                raise ValueError(f"missing source policy: {target.source_policy_id}")
            existing = connection.execute(
                "SELECT payload FROM watch_targets WHERE id = ?", (target.target_id,)
            ).fetchone()
            payload = self._payload(target)
            if existing is not None:
                if existing[0] != payload:
                    raise ConflictingWriteError(
                        f"conflicting payload for immutable watch_targets {target.target_id}"
                    )
                return target
            connection.execute(
                "INSERT INTO watch_targets(id, source_policy_id, payload) VALUES (?, ?, ?)",
                (target.target_id, target.source_policy_id, payload),
            )
            self._audit(
                connection,
                entity_type="watch_target",
                entity_id=target.target_id,
                event_type="created",
                payload=payload,
            )
        return target

    def put_fetch_attempt(self, attempt: FetchAttempt) -> FetchAttempt:
        with self._connect() as connection:
            payload = self._payload(attempt)
            existing = connection.execute(
                "SELECT payload FROM fetch_attempts WHERE id = ?", (attempt.attempt_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise ConflictingWriteError(
                        f"conflicting payload for immutable fetch_attempts {attempt.attempt_id}"
                    )
                return attempt
            connection.execute(
                "INSERT INTO fetch_attempts(id, request_id, payload) VALUES (?, ?, ?)",
                (attempt.attempt_id, attempt.request_id, payload),
            )
            self._audit(
                connection,
                entity_type="fetch_attempt",
                entity_id=attempt.attempt_id,
                event_type="created",
                payload=payload,
            )
        return attempt

    def put_snapshot(self, snapshot: SnapshotBundle) -> SnapshotBundle:
        with self._connect() as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM watch_targets WHERE id = ?", (snapshot.target_id,)
                ).fetchone()
                is None
            ):
                raise ValueError(f"missing watch target: {snapshot.target_id}")
            existing = connection.execute(
                "SELECT payload FROM snapshot_manifests WHERE id = ?", (snapshot.snapshot_id,)
            ).fetchone()
            payload = self._payload(snapshot)
            if existing is not None:
                if existing[0] != payload:
                    raise ConflictingWriteError(
                        f"conflicting payload for immutable snapshot {snapshot.snapshot_id}"
                    )
                return snapshot
            connection.execute(
                "INSERT INTO snapshot_manifests(id, target_id, payload) VALUES (?, ?, ?)",
                (snapshot.snapshot_id, snapshot.target_id, payload),
            )
            self._audit(
                connection,
                entity_type="snapshot",
                entity_id=snapshot.snapshot_id,
                event_type="created",
                payload=payload,
            )
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> SnapshotBundle | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM snapshot_manifests WHERE id = ?", (snapshot_id,)
            ).fetchone()
        return None if row is None else SnapshotBundle.model_validate_json(row[0])

    def latest_snapshot(self, target_id: str) -> SnapshotBundle | None:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM snapshot_manifests WHERE target_id = ? "
                "ORDER BY rowid DESC LIMIT 1",
                (target_id,),
            ).fetchone()
        return None if rows is None else SnapshotBundle.model_validate_json(rows[0])

    def latest_snapshot_id(self, target_id: str) -> str | None:
        snapshot = self.latest_snapshot(target_id)
        return None if snapshot is None else snapshot.snapshot_id

    def create_proposal(self, proposal: ChangeProposal, *, client_event_id: str) -> ChangeProposal:
        return self.create_proposal_with_fingerprint(
            proposal, client_event_id=client_event_id, request_fingerprint=""
        )

    def get_proposal_by_client_event(
        self, client_event_id: str
    ) -> tuple[ChangeProposal, str] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload, request_fingerprint FROM change_proposals "
                "WHERE client_event_id = ?",
                (client_event_id,),
            ).fetchone()
        if row is None:
            return None
        return ChangeProposal.model_validate_json(row[0]), str(row[1])

    def create_proposal_with_fingerprint(
        self,
        proposal: ChangeProposal,
        *,
        client_event_id: str,
        request_fingerprint: str,
    ) -> ChangeProposal:
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT payload, request_fingerprint FROM change_proposals "
                "WHERE client_event_id = ?",
                (client_event_id,),
            ).fetchone()
            payload = self._payload(proposal)
            if prior is not None:
                if prior[0] != payload or (
                    prior[1] and request_fingerprint and prior[1] != request_fingerprint
                ):
                    raise IdempotencyConflictError(
                        "client event was already used for another proposal"
                    )
                return ChangeProposal.model_validate_json(prior[0])
            existing = connection.execute(
                "SELECT payload FROM change_proposals WHERE id = ?", (proposal.proposal_id,)
            ).fetchone()
            if existing is not None:
                if existing[0] != payload:
                    raise ConflictingWriteError(
                        f"conflicting payload for immutable proposal {proposal.proposal_id}"
                    )
                return ChangeProposal.model_validate_json(existing[0])
            for lineage_id in proposal.lineage_ids:
                if (
                    connection.execute(
                        "SELECT 1 FROM snapshot_manifests WHERE id = ?", (lineage_id,)
                    ).fetchone()
                    is None
                ):
                    raise ValueError(f"missing snapshot manifest: {lineage_id}")
            now = proposal.created_at.isoformat()
            connection.execute(
                "INSERT INTO change_proposals(id, status, version, client_event_id, "
                "payload, created_at, updated_at, request_fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal.proposal_id,
                    proposal.status.value,
                    proposal.version,
                    client_event_id,
                    payload,
                    now,
                    proposal.updated_at.isoformat(),
                    request_fingerprint,
                ),
            )
            self._audit(
                connection,
                entity_type="proposal",
                entity_id=proposal.proposal_id,
                event_type="created",
                payload=payload,
            )
        return proposal

    def get_proposal(self, proposal_id: str) -> ChangeProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM change_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        return None if row is None else ChangeProposal.model_validate_json(row[0])

    def decide_proposal(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        status: ReviewDecisionStatus,
        reason: str,
        expected_version: int,
        client_event_id: str,
        edits: dict[str, object] | None = None,
        attestation: ReviewAttestation | None = None,
        curator_confidence: float | None = None,
        reverify_task: ReverifyTask | None = None,
    ) -> ReviewDecision:
        try:
            return self._decide_proposal(
                proposal_id,
                reviewer_id=reviewer_id,
                status=status,
                reason=reason,
                expected_version=expected_version,
                client_event_id=client_event_id,
                edits=edits,
                attestation=attestation,
                curator_confidence=curator_confidence,
                reverify_task=reverify_task,
            )
        except sqlite3.OperationalError as error:
            if "locked" in str(error).lower():
                raise StaleVersionError("proposal decision lost the SQLite write lock") from error
            raise

    def _decide_proposal(
        self,
        proposal_id: str,
        *,
        reviewer_id: str,
        status: ReviewDecisionStatus,
        reason: str,
        expected_version: int,
        client_event_id: str,
        edits: dict[str, object] | None = None,
        attestation: ReviewAttestation | None = None,
        curator_confidence: float | None = None,
        reverify_task: ReverifyTask | None = None,
    ) -> ReviewDecision:
        request_fingerprint = self._fingerprint_request(
            proposal_id=proposal_id,
            reviewer_id=reviewer_id,
            status=status,
            reason=reason,
            expected_version=expected_version,
            edits=edits,
            curator_confidence=curator_confidence,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            prior = connection.execute(
                "SELECT request_fingerprint, payload FROM review_decisions "
                "WHERE client_event_id = ?",
                (client_event_id,),
            ).fetchone()
            if prior is not None:
                if prior[0] != request_fingerprint:
                    raise IdempotencyConflictError(
                        "client event was already used for a different decision request"
                    )
                return ReviewDecision.model_validate_json(prior[1])
            row = connection.execute(
                "SELECT status, version, payload FROM change_proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"missing proposal: {proposal_id}")
            if int(row[1]) != expected_version:
                raise StaleVersionError(
                    f"proposal {proposal_id} is at version {row[1]}, expected {expected_version}"
                )
            if row[0] != "pending":
                raise AlreadyDecidedError(f"proposal {proposal_id} already has a terminal decision")
            proposal = ChangeProposal.model_validate_json(row[2])
            if status is ReviewDecisionStatus.EDITED and not edits:
                raise InvalidDecisionError("edited decisions require non-empty edits")
            if status is not ReviewDecisionStatus.EDITED and edits:
                raise InvalidDecisionError("only edited decisions may carry edits")
            if (status is ReviewDecisionStatus.REVERIFY) != (reverify_task is not None):
                raise InvalidDecisionError("reverify decisions require exactly one reverify task")
            if status in {ReviewDecisionStatus.APPROVED, ReviewDecisionStatus.EDITED} and any(
                finding.severity == "blocking" for finding in proposal.validation_findings
            ):
                raise ValueError("proposal has blocking validation findings")
            for lineage_id in proposal.lineage_ids:
                if (
                    connection.execute(
                        "SELECT 1 FROM snapshot_manifests WHERE id = ?", (lineage_id,)
                    ).fetchone()
                    is None
                ):
                    raise ValueError(f"missing snapshot manifest: {lineage_id}")
            if attestation is not None:
                payload_hash = hashlib.sha256(row[2].encode("utf-8")).hexdigest()
                if payload_hash != attestation.proposal_payload_sha256:
                    raise StaleVersionError("proposal payload changed before decision")
            decision = ReviewDecision(
                decision_id=self._id(),
                proposal_id=proposal_id,
                proposal_version=expected_version,
                reviewer_id=reviewer_id,
                status=status,
                edits=edits or {},
                reason=reason,
                decided_at=self._now(),
                client_event_id=client_event_id,
                curator_confidence=curator_confidence,
                attestation=attestation,
            )
            decision_payload = decision.model_dump_json()
            connection.execute(
                "INSERT INTO review_decisions(id, proposal_id, client_event_id, "
                "request_fingerprint, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    decision.decision_id,
                    proposal_id,
                    client_event_id,
                    request_fingerprint,
                    decision_payload,
                ),
            )
            updated = proposal.model_copy(
                update={
                    "status": ProposalStatus(status.value),
                    "version": proposal.version + 1,
                    "updated_at": decision.decided_at,
                }
            )
            connection.execute(
                "UPDATE change_proposals SET status = ?, version = ?, payload = ?, "
                "updated_at = ? WHERE id = ?",
                (
                    updated.status.value,
                    updated.version,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    proposal_id,
                ),
            )
            self._audit(
                connection,
                entity_type="proposal",
                entity_id=proposal_id,
                event_type="decision",
                payload=decision_payload,
            )
            if reverify_task is not None:
                self._insert_reverify_task(connection, reverify_task, client_event_id + ":task")
            return decision

    def _insert_reverify_task(
        self, connection: sqlite3.Connection, task: ReverifyTask, client_event_id: str
    ) -> None:
        payload = self._payload(task)
        if (
            connection.execute(
                "SELECT 1 FROM watch_targets WHERE id = ?", (task.target_id,)
            ).fetchone()
            is None
        ):
            raise ValueError(f"missing watch target: {task.target_id}")
        for evidence_id in task.prior_evidence_ids:
            if (
                connection.execute(
                    "SELECT 1 FROM snapshot_manifests WHERE id = ?", (evidence_id,)
                ).fetchone()
                is None
            ):
                raise ValueError(f"missing snapshot manifest: {evidence_id}")
        prior = connection.execute(
            "SELECT payload FROM reverify_tasks WHERE client_event_id = ?", (client_event_id,)
        ).fetchone()
        if prior is not None:
            if prior[0] != payload:
                raise IdempotencyConflictError("client event was already used for another task")
            return
        connection.execute(
            "INSERT INTO reverify_tasks(id, target_id, client_event_id, payload) "
            "VALUES (?, ?, ?, ?)",
            (task.task_id, task.target_id, client_event_id, payload),
        )
        self._audit(
            connection,
            entity_type="reverify_task",
            entity_id=task.task_id,
            event_type="created",
            payload=payload,
        )

    def list_decisions(self, proposal_id: str) -> list[ReviewDecision]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM review_decisions WHERE proposal_id = ? ORDER BY rowid",
                (proposal_id,),
            ).fetchall()
        return [ReviewDecision.model_validate_json(row[0]) for row in rows]

    def put_reverify_task(self, task: ReverifyTask, *, client_event_id: str) -> ReverifyTask:
        with self._connect() as connection:
            prior = connection.execute(
                "SELECT payload FROM reverify_tasks WHERE client_event_id = ?", (client_event_id,)
            ).fetchone()
            if prior is not None:
                if prior[0] != self._payload(task):
                    raise IdempotencyConflictError("client event was already used for another task")
                return ReverifyTask.model_validate_json(prior[0])
            if (
                connection.execute(
                    "SELECT 1 FROM watch_targets WHERE id = ?", (task.target_id,)
                ).fetchone()
                is None
            ):
                raise ValueError(f"missing watch target: {task.target_id}")
            for evidence_id in task.prior_evidence_ids:
                if (
                    connection.execute(
                        "SELECT 1 FROM snapshot_manifests WHERE id = ?", (evidence_id,)
                    ).fetchone()
                    is None
                ):
                    raise ValueError(f"missing snapshot manifest: {evidence_id}")
            existing_id = connection.execute(
                "SELECT payload, client_event_id FROM reverify_tasks WHERE id = ?", (task.task_id,)
            ).fetchone()
            if existing_id is not None:
                if existing_id[0] != self._payload(task):
                    raise ConflictingWriteError(f"conflicting reverify task {task.task_id}")
                return ReverifyTask.model_validate_json(existing_id[0])
            connection.execute(
                "INSERT INTO reverify_tasks(id, target_id, client_event_id, "
                "payload) VALUES (?, ?, ?, ?)",
                (task.task_id, task.target_id, client_event_id, self._payload(task)),
            )
            self._audit(
                connection,
                entity_type="reverify_task",
                entity_id=task.task_id,
                event_type="created",
                payload=self._payload(task),
            )
        return task

    def list_audit_events(self, *, entity_id: str | None = None) -> list[dict[str, str]]:
        with self._connect() as connection:
            if entity_id is None:
                rows = connection.execute(
                    "SELECT event_id, entity_type, entity_id, event_type, payload, created_at "
                    "FROM audit_events ORDER BY rowid"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT event_id, entity_type, entity_id, event_type, payload, created_at "
                    "FROM audit_events WHERE entity_id = ? ORDER BY rowid",
                    (entity_id,),
                ).fetchall()
        return [
            {
                "event_id": row[0],
                "entity_type": row[1],
                "entity_id": row[2],
                "event_type": row[3],
                "payload": row[4],
                "created_at": row[5],
            }
            for row in rows
        ]
