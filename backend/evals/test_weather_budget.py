"""G4 weather: persistent per-plan call ceiling (SQLite, atomic reservation)."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from gateway.weather.budget import (
    MAX_CALLS_PER_PLAN,
    WeatherBudgetContentionError,
    WeatherCallBudget,
)


def test_ceiling_is_small_and_explicit() -> None:
    assert MAX_CALLS_PER_PLAN == 4


def test_reservations_stop_at_the_ceiling_per_plan() -> None:
    budget = WeatherCallBudget()
    assert [budget.reserve_call("plan-a") for _ in range(MAX_CALLS_PER_PLAN + 2)] == (
        [True] * MAX_CALLS_PER_PLAN + [False, False]
    )
    assert budget.calls_used("plan-a") == MAX_CALLS_PER_PLAN
    assert budget.reserve_call("plan-b") is True  # plans are independent


def test_file_backed_ledger_survives_reopen(tmp_path: Path) -> None:
    db = tmp_path / "weather_budget.sqlite"
    first = WeatherCallBudget(db)
    for _ in range(MAX_CALLS_PER_PLAN):
        assert first.reserve_call("plan-x")
    assert WeatherCallBudget(db).reserve_call("plan-x") is False


def test_concurrent_reservations_never_exceed_ceiling(tmp_path: Path) -> None:
    budget = WeatherCallBudget(tmp_path / "b.sqlite")
    granted: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        ok = budget.reserve_call("plan-c")
        with lock:
            granted.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(granted) == MAX_CALLS_PER_PLAN


def test_lock_contention_raises_typed_error_not_raw_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "locked.sqlite"
    budget = WeatherCallBudget(db, busy_timeout_s=0.05)
    blocker = sqlite3.connect(db, timeout=0.05)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(WeatherBudgetContentionError):
            budget.reserve_call("plan-d")
    finally:
        blocker.rollback()
        blocker.close()
