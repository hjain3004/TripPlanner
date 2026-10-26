"""Persistent call ledger for OpenBnB: a per-plan ceiling and a lifetime ceiling.

OpenBnB scrapes a consumer website that forbids automated access, so volume is held far
below what the upstream server could do: at most ``CALLS_PER_PLAN`` calls per plan (one
search plus one details lookup) and ``TOTAL_CALLS_CEILING`` calls ever recorded in this
ledger. A file-backed ledger therefore enforces "low-volume" across processes; the default
in-memory ledger enforces it for the life of one process.

Reservation is atomic (``BEGIN IMMEDIATE``) and happens *before* dispatch, so a crash or
timeout never refunds a call: an interrupted call stays spent.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

CALLS_PER_PLAN = 2
TOTAL_CALLS_CEILING = 40


class OpenBnBBudgetUnavailableError(Exception):
    """The ledger could not be read or written (e.g. lock contention)."""


class OpenBnBCallBudget:
    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        calls_per_plan: int = CALLS_PER_PLAN,
        total_ceiling: int = TOTAL_CALLS_CEILING,
        busy_timeout_s: float = 5.0,
    ) -> None:
        self._lock = threading.Lock()
        self._db_path = ":memory:" if db_path is None else str(db_path)
        self._busy_timeout_s = busy_timeout_s
        self._calls_per_plan = calls_per_plan
        self._total_ceiling = total_ceiling
        self._mem_conn: sqlite3.Connection | None = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        return sqlite3.connect(self._db_path, timeout=self._busy_timeout_s, check_same_thread=False)

    def _close(self, conn: sqlite3.Connection) -> None:
        if self._mem_conn is None:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                with conn:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS openbnb_call_counts ("
                        "plan_id TEXT PRIMARY KEY, calls_used INTEGER NOT NULL DEFAULT 0)"
                    )
            finally:
                self._close(conn)

    def reserve_call(self, plan_id: str) -> bool:
        """Atomically reserve one call for ``plan_id``; ``False`` if a ceiling is reached."""
        with self._lock:
            conn = self._conn()
            try:
                try:
                    with conn:
                        conn.execute("BEGIN IMMEDIATE")
                        row = conn.execute(
                            "SELECT calls_used FROM openbnb_call_counts WHERE plan_id = ?",
                            (plan_id,),
                        ).fetchone()
                        used = row[0] if row else 0
                        total = conn.execute(
                            "SELECT COALESCE(SUM(calls_used), 0) FROM openbnb_call_counts"
                        ).fetchone()[0]
                        if used >= self._calls_per_plan or total >= self._total_ceiling:
                            return False
                        conn.execute(
                            "INSERT INTO openbnb_call_counts (plan_id, calls_used) VALUES (?, 1) "
                            "ON CONFLICT(plan_id) DO UPDATE SET calls_used = calls_used + 1",
                            (plan_id,),
                        )
                        return True
                except sqlite3.OperationalError as exc:
                    raise OpenBnBBudgetUnavailableError(
                        f"OpenBnB call ledger unavailable for plan {plan_id!r}: {exc}"
                    ) from exc
            finally:
                self._close(conn)

    def calls_used(self, plan_id: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT calls_used FROM openbnb_call_counts WHERE plan_id = ?", (plan_id,)
                ).fetchone()
                used: int = row[0] if row else 0
                return used
            finally:
                self._close(conn)

    def total_calls(self) -> int:
        with self._lock:
            conn = self._conn()
            try:
                total: int = conn.execute(
                    "SELECT COALESCE(SUM(calls_used), 0) FROM openbnb_call_counts"
                ).fetchone()[0]
                return total
            finally:
                self._close(conn)
