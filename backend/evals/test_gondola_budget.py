from __future__ import annotations

from gateway.travel.adapters.gondola.budget import CALLS_PER_PLAN, GondolaCallBudget


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
