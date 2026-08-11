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
    # Zero-cost by default (student_noncommercial profile). Any positive
    # external spend must be an explicit, reviewed override — never a
    # provider default. design §9 / CLAUDE.md build order.
    max_cost_minor: int = Field(default=0, ge=0)


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
        self.external_cost_minor = 0

    def record_provider_call(self) -> None:
        if self.provider_calls + 1 > self.budget.max_provider_calls:
            raise BudgetExhausted(
                f"max_provider_calls={self.budget.max_provider_calls} exhausted"
            )
        self.provider_calls += 1

    def record_external_cost(self, amount_minor: int) -> None:
        """Reserve external spend against max_cost_minor. Checks before
        mutating: a rejected call leaves external_cost_minor unchanged."""
        if amount_minor < 0:
            raise ValueError("amount_minor must be >= 0")
        prospective = self.external_cost_minor + amount_minor
        if prospective > self.budget.max_cost_minor:
            raise BudgetExhausted(
                f"max_cost_minor={self.budget.max_cost_minor} exhausted"
            )
        self.external_cost_minor = prospective

    def record_retry(self) -> None:
        if self.retries + 1 > self.budget.max_retries:
            raise BudgetExhausted(f"max_retries={self.budget.max_retries} exhausted")
        self.retries += 1

    def can_finalize(self, evidence_count: int) -> bool:
        return evidence_count >= self.budget.min_evidence_for_finalization
