import pytest

from gateway.evidence.budget import (
    BudgetExhausted, BudgetLedger, PartialResult, PlanBudget,
)


def _budget(**overrides: int) -> PlanBudget:
    base = dict(max_provider_calls=2, max_fan_out=2, max_wall_clock_s=30,
                max_retries=1, min_evidence_for_finalization=1)
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
        PartialResult(best_artifact_id=None, completed=[],
                      unresolved=["flights"], stop_reason="")
