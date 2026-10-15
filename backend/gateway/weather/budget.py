"""Persistent per-plan call ledger for the weather adapter (G4).

Open-Meteo's free tier is generous (< 10,000 calls/day) but non-commercial and
shared; this project enforces its own small, explicit per-plan ceiling so a
planning run can never fan out. Same atomic-SQLite-reservation pattern as the
other gateway ledgers: ``BEGIN IMMEDIATE`` makes check-and-increment atomic
across threads *and* processes. Every retry attempt reserves its own slot.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

MAX_CALLS_PER_PLAN = 4  # at most one call each for forecast, history and climate, plus 1 retry


class WeatherBudgetContentionError(Exception):
    """The ledger could not be consulted (e.g. SQLite lock contention)."""


class WeatherCallBudget:
    def __init__(self, db_path: Path | str | None = None, *, busy_timeout_s: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._db_path = ":memory:" if db_path is None else str(db_path)
        self._busy_timeout_s = busy_timeout_s
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
                        "CREATE TABLE IF NOT EXISTS weather_call_counts ("
                        "plan_id TEXT PRIMARY KEY, calls_used INTEGER NOT NULL DEFAULT 0)"
                    )
            finally:
                self._close(conn)

    def reserve_call(self, plan_id: str) -> bool:
        """Atomically reserve one call slot; False (nothing reserved) at the ceiling."""
        with self._lock:
            conn = self._conn()
            try:
                try:
                    with conn:
                        conn.execute("BEGIN IMMEDIATE")
                        row = conn.execute(
                            "SELECT calls_used FROM weather_call_counts WHERE plan_id = ?",
                            (plan_id,),
                        ).fetchone()
                        if (row[0] if row else 0) >= MAX_CALLS_PER_PLAN:
                            return False
                        conn.execute(
                            "INSERT INTO weather_call_counts (plan_id, calls_used) VALUES (?, 1) "
                            "ON CONFLICT(plan_id) DO UPDATE SET calls_used = calls_used + 1",
                            (plan_id,),
                        )
                        return True
                except sqlite3.OperationalError as exc:
                    raise WeatherBudgetContentionError(
                        "weather call ledger is contended or unavailable"
                    ) from exc
            finally:
                self._close(conn)

    def calls_used(self, plan_id: str) -> int:
        with self._lock:
            conn = self._conn()
            try:
                row = conn.execute(
                    "SELECT calls_used FROM weather_call_counts WHERE plan_id = ?", (plan_id,)
                ).fetchone()
                used: int = row[0] if row else 0
                return used
            finally:
                self._close(conn)
