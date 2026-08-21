from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from gateway.travel.adapters.gondola.budget import (
    CALLS_PER_PLAN,
    GondolaBudgetExhaustedError,
    GondolaCallBudget,
)


def test_reserve_call_succeeds_up_to_the_per_plan_ceiling() -> None:
    budget = GondolaCallBudget()
    for _ in range(CALLS_PER_PLAN):
        assert budget.reserve_call("plan-1") is True


def test_reserve_call_rejects_beyond_the_per_plan_ceiling() -> None:
    budget = GondolaCallBudget()
    for _ in range(CALLS_PER_PLAN):
        budget.reserve_call("plan-1")
    assert budget.reserve_call("plan-1") is False


def test_calls_used_reports_the_running_count() -> None:
    budget = GondolaCallBudget()
    budget.reserve_call("plan-1")
    assert budget.calls_used("plan-1") == 1


def test_ceiling_is_two_calls_per_plan() -> None:
    assert CALLS_PER_PLAN == 2


def test_different_plans_have_independent_budgets() -> None:
    budget = GondolaCallBudget()
    for _ in range(CALLS_PER_PLAN):
        budget.reserve_call("plan-a")
    assert budget.reserve_call("plan-a") is False
    assert budget.reserve_call("plan-b") is True


def test_file_backed_lock_contention_raises_typed_error_not_a_raw_sqlite_exception(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "gondola_budget.sqlite"
    budget = GondolaCallBudget(db_path, busy_timeout_s=0.05)

    # Hold an exclusive lock on the same file from a second, independent
    # connection to force genuine SQLite lock contention.
    blocker = sqlite3.connect(str(db_path), timeout=5.0)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(GondolaBudgetExhaustedError):
            budget.reserve_call("plan-contended")
    finally:
        blocker.rollback()
        blocker.close()


def test_file_backed_ledger_works_normally_once_contention_clears(tmp_path: Path) -> None:
    db_path = tmp_path / "gondola_budget2.sqlite"
    budget = GondolaCallBudget(db_path, busy_timeout_s=1.0)
    assert budget.reserve_call("plan-x") is True
    assert budget.calls_used("plan-x") == 1


def test_reserve_call_is_thread_safe_under_real_concurrency(tmp_path: Path) -> None:
    db_path = tmp_path / "gondola_budget3.sqlite"
    budget = GondolaCallBudget(db_path, busy_timeout_s=2.0)
    results: list[bool] = []
    lock = threading.Lock()

    def _attempt() -> None:
        outcome = budget.reserve_call("plan-concurrent")
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=_attempt) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == CALLS_PER_PLAN
    assert results.count(False) == len(threads) - CALLS_PER_PLAN
