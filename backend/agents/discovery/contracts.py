import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class SearchIntent(BaseModel):
    query_text: str
    round_index: int

    @field_validator("query_text")
    @classmethod
    def prevent_urls(cls, v: str) -> str:
        if "http://" in v or "https://" in v:
            raise ValueError("URLs are not allowed in query_text")
        return v


class DiscoveryCandidate(BaseModel):
    mentioned_name: str
    resolved_place_id: str | None = None
    verification_state: Literal["unverified", "verified", "unresolved"] = "unverified"


class LoopBudget(BaseModel):
    max_rounds: int = Field(default=3, le=3)
    max_calls: int = Field(default=6, le=6)
    max_retained_candidates: int = Field(default=40, le=40)
    max_per_day: int = Field(default=12, le=12)


class BudgetExceeded(Exception):
    pass


class LoopState(BaseModel):
    budget: LoopBudget
    rounds_completed: int = 0
    calls_made: int = 0
    retained: list[Any] = Field(default_factory=list)

    def begin_round(self) -> None:
        if self.rounds_completed >= self.budget.max_rounds:
            raise BudgetExceeded("max_rounds")
        self.rounds_completed += 1

    def record_call(self) -> None:
        if self.calls_made >= self.budget.max_calls:
            raise BudgetExceeded("max_calls")
        self.calls_made += 1

    def retain(self, candidates: list[Any]) -> None:
        self.retained.extend(candidates)
        # Deduplicate deterministically by place_id
        seen = set()
        deduped = []
        for c in self.retained:
            if getattr(c, "place_id", None) not in seen:
                deduped.append(c)
                seen.add(getattr(c, "place_id", None))
        
        self.retained = deduped
        
        # Sort deterministically
        self.retained.sort(key=lambda c: getattr(c, "place_id", ""))
        
        # Truncate to budget
        if len(self.retained) > self.budget.max_retained_candidates:
            self.retained = self.retained[:self.budget.max_retained_candidates]

    def select_for_day(self, day_index: int) -> list[Any]:
        # Currently just returns all up to max_per_day. In real use it might filter.
        return self.retained[:self.budget.max_per_day]
