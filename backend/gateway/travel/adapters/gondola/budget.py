"""Persistent per-plan call ledger for Gondola — matches
``TripadvisorEntityLedger``'s atomic-SQLite-reservation pattern, simplified
to a flat per-plan call ceiling (Gondola publishes no rate limit of its own,
so this project enforces its own conservative one — an undocumented limit
is a reliability concern, not permission to make unlimited calls).
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

CALLS_PER_PLAN = 2


class GondolaBudgetExhaustedError(Exception):
    pass


class GondolaCallBudget:
    def __init__(self, db_path: Path | str | None = None) -> None:
        self._lock = threading.Lock()
        self._db_path = ":memory:" if db_path is None else str(db_path)
        self._mem_conn: sqlite3.Connection | None = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._mem_conn is not None:
            return self._mem_conn
        return sqlite3.connect(self._db_path, check_same_thread=False)

    def _close(self, conn: sqlite3.Connection) -> None:
        if self._mem_conn is None:
            conn.close()

    def _init_db(self) -> None:
        with self._lock:
            conn = self._conn()
            try:
                with conn:
                    conn.execute(
                        "CREATE TABLE IF NOT EXISTS gondola_call_counts ("
                        "plan_id TEXT PRIMARY KEY, calls_used INTEGER NOT NULL DEFAULT 0)"
                    )
            finally:
                self._close(conn)

    def reserve_call(self, plan_id: str) -> bool:
        """Atomically reserve one call slot for ``plan_id``.

        Returns False without reserving anything if the per-plan ceiling
        would be exceeded.
        """
        with self._lock:
            conn = self._conn()
            try:
                with conn:
                    conn.execute("BEGIN IMMEDIATE")
                    cur = conn.execute(
                        "SELECT calls_used FROM gondola_call_counts WHERE plan_id = ?",
                        (plan_id,),
                    )
                    row = cur.fetchone()
                    used = row[0] if row else 0
                    if used >= CALLS_PER_PLAN:
                        return False
                    conn.execute(
                        "INSERT INTO gondola_call_counts (plan_id, calls_used) VALUES (?, 1) "
                        "ON CONFLICT(plan_id) DO UPDATE SET calls_used = calls_used + 1",
                        (plan_id,),
                    )
                    return True
            finally:
                self._close(conn)

    def calls_used(self, plan_id: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                cur = conn.execute(
                    "SELECT calls_used FROM gondola_call_counts WHERE plan_id = ?", (plan_id,)
                )
                row = cur.fetchone()
                count: int = row[0] if row else 0
                return count
            finally:
                self._close(conn)
