import pytest

from gateway.evidence.budget import (
    BudgetExhausted,
    BudgetLedger,
    PartialResult,
    PlanBudget,
)


def _budget(**overrides: int) -> PlanBudget:
    base = dict(
        max_provider_calls=2,
        max_fan_out=2,
        max_wall_clock_s=30,
        max_retries=1,
        min_evidence_for_finalization=1,
    )
    base.update(overrides)
    return PlanBudget(**base)


def test_ledger_allows_calls_within_budget() -> None:
    ledger = BudgetLedger(_budget(max_provider_calls=2))
    ledger.record_provider_call()
    ledger.record_provider_call()
    assert ledger.provider_calls == 2


def test_ledger_raises_when_provider_calls_exhausted() -> None:
    ledger = BudgetLedger(_budget(max_provider_calls=1))
    ledger.record_provider_call()
    with pytest.raises(BudgetExhausted) as exc:
        ledger.record_provider_call()
    assert "max_provider_calls" in str(exc.value)


def test_cannot_finalize_below_minimum_evidence_bar() -> None:
    ledger = BudgetLedger(_budget(min_evidence_for_finalization=3))
    assert ledger.can_finalize(evidence_count=2) is False
    assert ledger.can_finalize(evidence_count=3) is True


def test_partial_result_requires_a_stop_reason() -> None:
    with pytest.raises(ValueError):
        PartialResult(best_artifact_id=None, completed=[], unresolved=["flights"], stop_reason="")


# --- I0 Task 1: zero-spend enforcement ------------------------------------ #


def test_plan_budget_defaults_to_zero_external_spend() -> None:
    budget = _budget()  # no max_cost_minor override
    assert budget.max_cost_minor == 0


def test_budget_ledger_accepts_zero_cost() -> None:
    ledger = BudgetLedger(_budget())  # default cap: 0
    ledger.record_external_cost(0)
    assert ledger.external_cost_minor == 0


def test_budget_ledger_rejects_first_positive_cost_without_incrementing() -> None:
    ledger = BudgetLedger(_budget())  # default cap: 0
    with pytest.raises(BudgetExhausted) as exc:
        ledger.record_external_cost(1)
    assert "max_cost_minor" in str(exc.value)
    assert ledger.external_cost_minor == 0  # rejected call left no trace


def test_budget_ledger_rejects_cumulative_cost_above_explicit_cap() -> None:
    ledger = BudgetLedger(_budget(max_cost_minor=100))
    ledger.record_external_cost(60)
    with pytest.raises(BudgetExhausted):
        ledger.record_external_cost(50)  # 60 + 50 = 110 > 100
    assert ledger.external_cost_minor == 60  # rejected call did not partially apply
