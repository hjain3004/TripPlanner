"""Per-run budgets. Exhaustion returns a PartialResult with an explicit reason —
partial failure is never hidden behind fluent prose (design §6).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetExhausted(RuntimeError):
    """Raised when a declared cap is hit."""


class PlanBudget(BaseModel):
    max_provider_calls: int = Field(ge=1)
    max_fan_out: int = Field(ge=1)
    max_wall_clock_s: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    min_evidence_for_finalization: int = Field(ge=1)
    max_tokens: int | None = None
    max_cost_minor: int | None = None


class PartialResult(BaseModel):
    best_artifact_id: str | None
    completed: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    stop_reason: str = Field(min_length=1)


class BudgetLedger:
    """Mutable counter guarding a PlanBudget."""

    def __init__(self, budget: PlanBudget) -> None:
        self.budget = budget
        self.provider_calls = 0
        self.retries = 0

    def record_provider_call(self) -> None:
        if self.provider_calls + 1 > self.budget.max_provider_calls:
            raise BudgetExhausted(
                f"max_provider_calls={self.budget.max_provider_calls} exhausted"
            )
        self.provider_calls += 1

    def record_retry(self) -> None:
        if self.retries + 1 > self.budget.max_retries:
            raise BudgetExhausted(f"max_retries={self.budget.max_retries} exhausted")
        self.retries += 1

    def can_finalize(self, evidence_count: int) -> bool:
        return evidence_count >= self.budget.min_evidence_for_finalization
