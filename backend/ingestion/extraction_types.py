"""Typed, untrusted extractor response contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ingestion.contracts import EvidenceSpan


class ExtractedField(BaseModel):
    field_path: str = Field(min_length=1)
    proposed_raw_value: Any
    evidence_spans: tuple[EvidenceSpan, ...] = Field(min_length=1)


class ExtractionResponse(BaseModel):
    target_table: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    proposed_row: dict[str, Any]
    fields: tuple[ExtractedField, ...] = Field(min_length=1)
    change_summary: str = Field(min_length=1, max_length=2000)
    extractor_confidence: float = Field(ge=0.0, le=1.0)
