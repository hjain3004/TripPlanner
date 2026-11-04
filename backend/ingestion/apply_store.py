"""Durable ledger for controlled application: origin confirmations, applies, field evidence.

A separate SQLite file from the ingestion queue, in the operator's data directory. It records
what was *applied* (and rolled back), the field-level evidence each apply rested on (D1), and
the curator confirmations of manual-capture origins (D2). Writers take ``BEGIN IMMEDIATE`` so two
processes cannot both claim the same first write; every history row is append-only and every
state change leaves an audit event.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from ingestion.verification import LedgerEvidence, OriginConfirmation

ApplyStatus = Literal["planned", "committed", "failed", "rolled_back", "aborted"]
_SCHEMA = """
CREATE TABLE IF NOT EXISTS confirmations(
    id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS applications(
    apply_id TEXT PRIMARY KEY, client_event_id TEXT NOT NULL UNIQUE,
    fingerprint TEXT NOT NULL, status TEXT NOT NULL, bundle_sha256 TEXT NOT NULL,
    payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS field_evidence(
    apply_id TEXT NOT NULL, table_name TEXT NOT NULL, row_id TEXT NOT NULL,
    field_path TEXT NOT NULL, payload TEXT NOT NULL,
    PRIMARY KEY(apply_id, table_name, row_id, field_path));
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
    event TEXT NOT NULL, payload TEXT NOT NULL, at TEXT NOT NULL);
"""


class ApplyLedgerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApplicationRecord(BaseModel):
    apply_id: str
    bundle_sha256: str
    seeds_dir: str
    curator_id: str
    reason: str
    client_event_id: str
    status: ApplyStatus
    plan: dict[str, Any]
    report: dict[str, Any] | None = None


class ApplyStore:
    def __init__(self, path: Path, *, now: Callable[[], datetime] | None = None) -> None:
        self.path = path
        self._now = now or (lambda: datetime.now(UTC))
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _event(
        self, connection: sqlite3.Connection, entity: str, entity_id: str, event: str, payload: Any
    ) -> None:
        connection.execute(
            "INSERT INTO events(entity, entity_id, event, payload, at) VALUES (?, ?, ?, ?, ?)",
            (
                entity,
                entity_id,
                event,
                json.dumps(payload, sort_keys=True, default=str),
                self._now().isoformat(),
            ),
        )

    # ------------------------------------------------------------------ D2 confirmations

    def put_confirmation(self, confirmation: OriginConfirmation) -> tuple[OriginConfirmation, bool]:
        """Insert-only. Re-confirming the same capture and class returns the first record."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM confirmations WHERE id = ?", (confirmation.confirmation_id,)
            ).fetchone()
            if row is not None:
                stored = OriginConfirmation.model_validate_json(row[0])
                if stored.model_dump(exclude={"confirmed_at"}) != confirmation.model_dump(
                    exclude={"confirmed_at"}
                ):
                    raise ApplyLedgerError(
                        "confirmation_conflict",
                        "this capture already has a different origin confirmation; confirmations "
                        "are immutable",
                    )
                return stored, False
            connection.execute(
                "INSERT INTO confirmations(id, snapshot_id, payload) VALUES (?, ?, ?)",
                (
                    confirmation.confirmation_id,
                    confirmation.snapshot_id,
                    confirmation.model_dump_json(),
                ),
            )
            self._event(
                connection,
                "confirmation",
                confirmation.confirmation_id,
                "created",
                confirmation.model_dump(mode="json"),
            )
        return confirmation, True

    def confirmations_for(self, snapshot_id: str) -> list[OriginConfirmation]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM confirmations WHERE snapshot_id = ? ORDER BY id",
                (snapshot_id,),
            ).fetchall()
        return [OriginConfirmation.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------------ applications

    def begin_application(
        self, record: ApplicationRecord, *, fingerprint: str
    ) -> tuple[ApplicationRecord, bool]:
        """Idempotent on ``client_event_id``; a different request under one id is a conflict."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload, fingerprint FROM applications WHERE client_event_id = ?",
                (record.client_event_id,),
            ).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise ApplyLedgerError(
                        "idempotency_conflict",
                        "this client event id was already used for a different apply request",
                    )
                return ApplicationRecord.model_validate_json(row["payload"]), False
            connection.execute(
                "INSERT INTO applications(apply_id, client_event_id, fingerprint, status, "
                "bundle_sha256, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    record.apply_id,
                    record.client_event_id,
                    fingerprint,
                    record.status,
                    record.bundle_sha256,
                    record.model_dump_json(),
                ),
            )
            self._event(
                connection,
                "application",
                record.apply_id,
                "planned",
                {"bundle_sha256": record.bundle_sha256, "curator_id": record.curator_id},
            )
        return record, True

    def get_application(self, apply_id: str) -> ApplicationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM applications WHERE apply_id = ?", (apply_id,)
            ).fetchone()
        return None if row is None else ApplicationRecord.model_validate_json(row[0])

    def application_for_event(self, client_event_id: str) -> ApplicationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM applications WHERE client_event_id = ?", (client_event_id,)
            ).fetchone()
        return None if row is None else ApplicationRecord.model_validate_json(row[0])

    def set_status(
        self,
        apply_id: str,
        status: ApplyStatus,
        *,
        report: dict[str, Any] | None = None,
        evidence: Sequence[LedgerEvidence] = (),
        detail: str | None = None,
    ) -> ApplicationRecord:
        """Change an application's status, optionally recording its evidence, in one transaction."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT payload FROM applications WHERE apply_id = ?", (apply_id,)
            ).fetchone()
            if row is None:
                raise ApplyLedgerError("unknown_apply", f"no apply {apply_id!r}")
            record = ApplicationRecord.model_validate_json(row[0])
            update: dict[str, Any] = {"status": status}
            if report is not None:
                update["report"] = report
            record = record.model_copy(update=update)
            connection.execute(
                "UPDATE applications SET status = ?, payload = ? WHERE apply_id = ?",
                (status, record.model_dump_json(), apply_id),
            )
            for item in evidence:
                connection.execute(
                    "INSERT OR IGNORE INTO field_evidence(apply_id, table_name, row_id, "
                    "field_path, payload) VALUES (?, ?, ?, ?, ?)",
                    (
                        item.apply_id,
                        item.table_name,
                        item.row_id,
                        item.field_path,
                        item.model_dump_json(),
                    ),
                )
            self._event(connection, "application", apply_id, status, {"detail": detail})
        return record

    def active_evidence(self, table_name: str, row_id: str) -> list[LedgerEvidence]:
        """Evidence from applies that are currently committed (rolled-back applies drop out)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.payload FROM field_evidence e JOIN applications a "
                "ON a.apply_id = e.apply_id WHERE a.status = 'committed' "
                "AND e.table_name = ? AND e.row_id = ? ORDER BY e.apply_id, e.field_path",
                (table_name, row_id),
            ).fetchall()
        return [LedgerEvidence.model_validate_json(r[0]) for r in rows]

    def events(self, entity_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as connection:
            query = "SELECT entity, entity_id, event, payload, at FROM events"
            args: tuple[Any, ...] = ()
            if entity_id is not None:
                query += " WHERE entity_id = ?"
                args = (entity_id,)
            rows = connection.execute(query + " ORDER BY id", args).fetchall()
        return [dict(r) for r in rows]
