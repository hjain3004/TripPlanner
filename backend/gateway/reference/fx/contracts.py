"""Normalized FX reference-rate contracts (offline import, spec 09 §13 G2a).

Values here are never activated in the optimizer/transfer-pathfinder path;
they exist for human review before any decision to update a seed.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

from gateway.reference.contracts import SourceProvenance


def _normalize_currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValueError("must be a 3-letter currency code")
    return normalized


class FxRateRecord(BaseModel):
    base: str
    quote: str
    rate_micro: int = Field(gt=0)
    source_date: date
    derived: bool = False
    derivation: str | None = None

    _norm_base = field_validator("base")(classmethod(lambda cls, v: _normalize_currency(v)))
    _norm_quote = field_validator("quote")(classmethod(lambda cls, v: _normalize_currency(v)))

    @model_validator(mode="after")
    def _base_and_quote_differ(self) -> FxRateRecord:
        if self.base == self.quote:
            raise ValueError("base and quote currency must differ")
        if self.derived and not self.derivation:
            raise ValueError("a derived cross-rate must record its derivation")
        return self


class FxSnapshot(BaseModel):
    provenance: SourceProvenance
    rates: list[FxRateRecord]
