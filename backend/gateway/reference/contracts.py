"""Shared reference-snapshot provenance contract — spec 09 §13 (G2).

Every offline reference importer (FX, airports, and any future open/licensed
source) attaches one of these to its normalized snapshot. It retains enough
to answer "where did this come from, under what licence, and how fresh is
it" without ever becoming an approved financial fact by itself — activation
into a seed remains a separate, human-reviewed step.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class SourceProvenance(BaseModel):
    source_id: str = Field(min_length=1)
    source_owner: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    retrieved_at: date
    licence_id: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    terms_reference: str = Field(min_length=1)
    content_hash: str = Field(min_length=64, max_length=64)
    record_count: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
