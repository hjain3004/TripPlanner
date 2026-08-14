import re
from typing import Literal

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


class LoopState(BaseModel):
    budget: LoopBudget
