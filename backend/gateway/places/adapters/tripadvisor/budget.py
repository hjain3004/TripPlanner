from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path


class TripadvisorBudgetExhaustedError(Exception):
    """Raised when an operation exceeds or would exceed the lifetime 900-entity safety budget."""


class TripadvisorEntityLedger:
    """Thread-safe, persistent ledger enforcing a strict lifetime ceiling of 900 entities.

    Uses unique call-level reservation IDs (`call_id`) and atomic SQLite transactions
    to guarantee that multiple processes or connections sharing a database cannot
    over-allocate, double-release, or undercount provider entities.
    """

    LIFETIME_LIMIT: int = 900

    def __init__(
        self,
        db_path: Path | str | None = None,
        is_billable: bool = False,
    ) -> None:
        self._lock = threading.Lock()
        self._is_billable = is_billable

        if is_billable and (db_path is None or str(db_path) == ":memory:"):
            raise ValueError(
                "Billable Tripadvisor transport requires an explicit persistent SQLite path on disk"
            )

        if db_path is None:
            self._db_path = ":memory:"
            # Keep open connection for in-memory database to persist across method calls
            self._mem_conn: sqlite3.Connection | None = sqlite3.connect(
                ":memory:", timeout=30.0, check_same_thread=False
            )
            self._mem_conn.row_factory = sqlite3.Row
        else:
            self._db_path = str(db_path)
            self._mem_conn = None

        self._init_db()

    @property
    def is_billable(self) -> bool:
        return self._is_billable

    @property
    def is_in_memory(self) -> bool:
        return self._db_path == ":memory:"

    @property
    def db_path(self) -> str:
        return self._db_path

    def _get_connection(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        conn = sqlite3.connect(self._db_path, timeout=30.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _close_connection(self, conn: sqlite3.Connection) -> None:
        if self._mem_conn is None:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS entity_budget_state (
                            id INTEGER PRIMARY KEY CHECK (id = 1),
                            consumed_entities INTEGER NOT NULL DEFAULT 0,
                            reserved_entities INTEGER NOT NULL DEFAULT 0,
                            last_updated TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO entity_budget_state
                        (id, consumed_entities, reserved_entities, last_updated)
                        VALUES (1, 0, 0, ?)
                        """,
                        (datetime.now(UTC).isoformat(),),
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS call_reservations (
                            call_id TEXT PRIMARY KEY,
                            expected_max INTEGER NOT NULL,
                            actual_consumed INTEGER,
                            overage_amount INTEGER NOT NULL DEFAULT 0,
                            status TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL
                        )
                        """
                    )
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS entity_audit_log (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            timestamp TEXT NOT NULL,
                            action TEXT NOT NULL,
                            call_id TEXT NOT NULL,
                            count INTEGER NOT NULL,
                            overage INTEGER NOT NULL DEFAULT 0,
                            new_consumed INTEGER NOT NULL,
                            new_reserved INTEGER NOT NULL
                        )
                        """
                    )
            finally:
                self._close_connection(conn)

    def get_status(self) -> dict[str, int]:
        """Return current ledger status: consumed, reserved, remaining, is_exhausted."""
        with self._lock:
            conn = self._get_connection()
            try:
                cur = conn.execute(
                    "SELECT consumed_entities, reserved_entities "
                    "FROM entity_budget_state WHERE id = 1"
                )
                row = cur.fetchone()
                if not row:
                    return {
                        "consumed": 0,
                        "reserved": 0,
                        "remaining": self.LIFETIME_LIMIT,
                        "is_exhausted": 0,
                    }
                consumed = int(row["consumed_entities"])
                reserved = int(row["reserved_entities"])
                remaining = max(0, self.LIFETIME_LIMIT - (consumed + reserved))
                is_exhausted = 1 if (consumed >= self.LIFETIME_LIMIT or remaining == 0) else 0
                return {
                    "consumed": consumed,
                    "reserved": reserved,
                    "remaining": remaining,
                    "is_exhausted": is_exhausted,
                }
            finally:
                self._close_connection(conn)

    def reserve(self, expected_max_entities: int, call_id: str) -> bool:
        """Atomically reserve `expected_max_entities` under `call_id`.

        Idempotent for the exact same `call_id` and count.
        Returns True if reservation succeeded within the 900 ceiling; False otherwise.
        """
        if expected_max_entities < 0:
            raise ValueError("expected_max_entities cannot be negative")
        if not call_id:
            raise ValueError("call_id must be a non-empty string")
        if expected_max_entities == 0:
            return True

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")

                    # Check if reservation already exists
                    cur = conn.execute(
                        "SELECT expected_max, status FROM call_reservations WHERE call_id = ?",
                        (call_id,),
                    )
                    existing = cur.fetchone()
                    if existing:
                        if existing["status"] == "pending":
                            if existing["expected_max"] == expected_max_entities:
                                return True
                            prev_max = existing["expected_max"]
                            msg = (
                                f"Conflicting reservation count for call_id '{call_id}': "
                                f"previously {prev_max}, requested {expected_max_entities}"
                            )
                            raise ValueError(msg)
                        msg = (
                            f"Reservation '{call_id}' already settled "
                            f"with status '{existing['status']}'"
                        )
                        raise ValueError(msg)

                    # Check overall budget limits
                    cur = conn.execute(
                        "SELECT consumed_entities, reserved_entities "
                        "FROM entity_budget_state WHERE id = 1"
                    )
                    row = cur.fetchone()
                    consumed = int(row["consumed_entities"])
                    reserved = int(row["reserved_entities"])

                    if consumed >= self.LIFETIME_LIMIT:
                        return False

                    if consumed + reserved + expected_max_entities > self.LIFETIME_LIMIT:
                        return False

                    new_reserved = reserved + expected_max_entities
                    now_str = datetime.now(UTC).isoformat()

                    conn.execute(
                        "UPDATE entity_budget_state "
                        "SET reserved_entities = ?, last_updated = ? WHERE id = 1",
                        (new_reserved, now_str),
                    )
                    conn.execute(
                        "INSERT INTO call_reservations "
                        "(call_id, expected_max, status, created_at, updated_at) "
                        "VALUES (?, ?, 'pending', ?, ?)",
                        (call_id, expected_max_entities, now_str, now_str),
                    )
                    conn.execute(
                        "INSERT INTO entity_audit_log "
                        "(timestamp, action, call_id, count, overage, new_consumed, new_reserved) "
                        "VALUES (?, 'reserve', ?, ?, 0, ?, ?)",
                        (now_str, call_id, expected_max_entities, consumed, new_reserved),
                    )
                    return True
            finally:
                self._close_connection(conn)

    def reconcile(self, call_id: str, actual_entities: int) -> None:
        """Reconcile a completed call under `call_id` with `actual_entities` consumed.

        Idempotent for the exact same `call_id` and `actual_entities`.
        If `actual_entities > expected_max`, records actual consumption conservatively
        WITHOUT clamping to 900, persists the full exposure, and raises
        `TripadvisorBudgetExhaustedError` to prevent further operations.
        """
        if actual_entities < 0:
            raise ValueError("actual_entities cannot be negative")
        if not call_id:
            raise ValueError("call_id must be a non-empty string")

        overage_error: TripadvisorBudgetExhaustedError | None = None
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")

                    cur = conn.execute(
                        "SELECT expected_max, actual_consumed, status "
                        "FROM call_reservations WHERE call_id = ?",
                        (call_id,),
                    )
                    res = cur.fetchone()
                    if not res:
                        raise ValueError(f"Unknown reservation call_id: '{call_id}'")

                    if res["status"] in ("reconciled", "settled_ambiguous_failure"):
                        if res["actual_consumed"] == actual_entities:
                            return
                        msg = (
                            f"Conflicting reconcile count for call_id '{call_id}': "
                            f"previously {res['actual_consumed']}, requested {actual_entities}"
                        )
                        raise ValueError(msg)
                    if res["status"] == "released":
                        msg = f"Cannot reconcile previously released call_id '{call_id}'"
                        raise ValueError(msg)

                    expected_max = int(res["expected_max"])

                    cur = conn.execute(
                        "SELECT consumed_entities, reserved_entities "
                        "FROM entity_budget_state WHERE id = 1"
                    )
                    row = cur.fetchone()
                    consumed = int(row["consumed_entities"])
                    reserved = int(row["reserved_entities"])

                    overage = max(0, actual_entities - expected_max)
                    new_reserved = max(0, reserved - expected_max)
                    new_consumed = consumed + actual_entities  # NEVER clamp to 900
                    now_str = datetime.now(UTC).isoformat()

                    conn.execute(
                        "UPDATE entity_budget_state "
                        "SET consumed_entities = ?, reserved_entities = ?, last_updated = ? "
                        "WHERE id = 1",
                        (new_consumed, new_reserved, now_str),
                    )
                    conn.execute(
                        "UPDATE call_reservations "
                        "SET status = 'reconciled', actual_consumed = ?, overage_amount = ?, "
                        "updated_at = ? WHERE call_id = ?",
                        (actual_entities, overage, now_str, call_id),
                    )
                    conn.execute(
                        "INSERT INTO entity_audit_log "
                        "(timestamp, action, call_id, count, overage, new_consumed, new_reserved) "
                        "VALUES (?, 'reconcile', ?, ?, ?, ?, ?)",
                        (now_str, call_id, actual_entities, overage, new_consumed, new_reserved),
                    )

                    if actual_entities > expected_max:
                        overage_error = TripadvisorBudgetExhaustedError(
                            f"Unexpected provider response count ({actual_entities}) "
                            f"exceeded reserved ceiling ({expected_max}) for call '{call_id}'"
                        )
            finally:
                self._close_connection(conn)

        if overage_error is not None:
            raise overage_error

    def settle_ambiguous_failure(self, call_id: str) -> None:
        """Conservatively settle a reservation as fully consumed after a post-dispatch failure.

        If a network/client call fails after dispatch (e.g. timeout, malformed payload),
        we cannot verify the provider did not bill for the request.
        Conservatively assumes `expected_max` was consumed rather than restoring quota.
        """
        if not call_id:
            return

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")

                    cur = conn.execute(
                        "SELECT expected_max, status FROM call_reservations WHERE call_id = ?",
                        (call_id,),
                    )
                    res = cur.fetchone()
                    if not res:
                        return
                    if res["status"] != "pending":
                        return

                    expected_max = int(res["expected_max"])

                    cur = conn.execute(
                        "SELECT consumed_entities, reserved_entities "
                        "FROM entity_budget_state WHERE id = 1"
                    )
                    row = cur.fetchone()
                    consumed = int(row["consumed_entities"])
                    reserved = int(row["reserved_entities"])

                    new_reserved = max(0, reserved - expected_max)
                    new_consumed = consumed + expected_max
                    now_str = datetime.now(UTC).isoformat()

                    conn.execute(
                        "UPDATE entity_budget_state "
                        "SET consumed_entities = ?, reserved_entities = ?, last_updated = ? "
                        "WHERE id = 1",
                        (new_consumed, new_reserved, now_str),
                    )
                    conn.execute(
                        "UPDATE call_reservations "
                        "SET status = 'settled_ambiguous_failure', actual_consumed = ?, "
                        "updated_at = ? WHERE call_id = ?",
                        (expected_max, now_str, call_id),
                    )
                    conn.execute(
                        "INSERT INTO entity_audit_log "
                        "(timestamp, action, call_id, count, overage, new_consumed, new_reserved) "
                        "VALUES (?, 'ambiguous_failure_settlement', ?, ?, 0, ?, ?)",
                        (now_str, call_id, expected_max, new_consumed, new_reserved),
                    )
            finally:
                self._close_connection(conn)

    def release(self, call_id: str) -> None:
        """Release reservation for `call_id` if pending, restoring budget to pool."""
        if not call_id:
            return

        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")

                    cur = conn.execute(
                        "SELECT expected_max, status FROM call_reservations WHERE call_id = ?",
                        (call_id,),
                    )
                    res = cur.fetchone()
                    if not res:
                        return
                    if res["status"] == "released":
                        return
                    if res["status"] in ("reconciled", "settled_ambiguous_failure"):
                        msg = f"Cannot release already settled call_id '{call_id}'"
                        raise ValueError(msg)

                    expected_max = int(res["expected_max"])

                    cur = conn.execute(
                        "SELECT consumed_entities, reserved_entities "
                        "FROM entity_budget_state WHERE id = 1"
                    )
                    row = cur.fetchone()
                    consumed = int(row["consumed_entities"])
                    reserved = int(row["reserved_entities"])

                    new_reserved = max(0, reserved - expected_max)
                    now_str = datetime.now(UTC).isoformat()

                    conn.execute(
                        "UPDATE entity_budget_state "
                        "SET reserved_entities = ?, last_updated = ? WHERE id = 1",
                        (new_reserved, now_str),
                    )
                    conn.execute(
                        "UPDATE call_reservations "
                        "SET status = 'released', updated_at = ? WHERE call_id = ?",
                        (now_str, call_id),
                    )
                    conn.execute(
                        "INSERT INTO entity_audit_log "
                        "(timestamp, action, call_id, count, overage, new_consumed, new_reserved) "
                        "VALUES (?, 'release', ?, ?, 0, ?, ?)",
                        (now_str, call_id, expected_max, consumed, new_reserved),
                    )
            finally:
                self._close_connection(conn)

    def reset_for_test(self) -> None:
        """Reset budget ledger state (test-only)."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        "UPDATE entity_budget_state "
                        "SET consumed_entities = 0, reserved_entities = 0, last_updated = ? "
                        "WHERE id = 1",
                        (datetime.now(UTC).isoformat(),),
                    )
                    conn.execute("DELETE FROM call_reservations")
                    conn.execute("DELETE FROM entity_audit_log")
            finally:
                self._close_connection(conn)
