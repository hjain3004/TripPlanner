"""Pure, closed contracts for user-reviewable CP3 assistance results."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from planning.answers import ANSWER_TYPE_BY_QUESTION, AnswerPayload, QuestionId

AssistanceDiagnostic = Literal["unavailable", "invalid_response", "budget_exhausted", "interrupted"]


class AnswerCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    payload: AnswerPayload

    @model_validator(mode="after")
    def validate_payload(self) -> AnswerCandidate:
        if not isinstance(self.payload, ANSWER_TYPE_BY_QUESTION[self.question_id]):
            raise ValueError("candidate payload does not match its question")
        return self


class InterviewContradiction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_ids: list[QuestionId] = Field(min_length=2, max_length=4)
    clarification: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_references(self) -> InterviewContradiction:
        if len(set(self.answer_ids)) != len(self.answer_ids):
            raise ValueError("contradiction references must be distinct")
        return self


class AssistantReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledgement: str = Field(default="", max_length=500)
    acknowledgement_answer_ids: list[QuestionId] = Field(default_factory=list, max_length=8)
    question_ids: list[QuestionId] = Field(default_factory=list, max_length=4)
    wording: dict[QuestionId, str] = Field(default_factory=dict)
    contradictions: list[InterviewContradiction] = Field(default_factory=list, max_length=4)


class AssistanceRequestRecord(BaseModel):
    """No prompt or user text: a request hash and its validated result only."""

    model_config = ConfigDict(extra="forbid")
    fingerprint: str
    reserved_at: datetime | None = None
    status: Literal["reserved", "complete", "degraded"] = "reserved"
    review: AssistantReview | None = None
    candidate: AnswerCandidate | None = None
    diagnostic: AssistanceDiagnostic | None = None
