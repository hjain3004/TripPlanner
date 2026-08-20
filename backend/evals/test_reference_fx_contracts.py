from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from gateway.reference.contracts import SourceProvenance
from gateway.reference.fx.contracts import FxRateRecord, FxSnapshot


def _provenance() -> SourceProvenance:
    return SourceProvenance(
        source_id="frankfurter",
        source_owner="Frankfurter (frankfurter.dev)",
        source_url="https://api.frankfurter.dev/v2/rates",
        release_id="2026-08-20",
        retrieved_at=date(2026, 8, 20),
        licence_id="frankfurter-api-blended-central-bank-sources",
        attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
        terms_reference="https://frankfurter.dev/docs",
        content_hash="a" * 64,
        record_count=1,
        warnings=[],
    )


def test_fx_rate_record_rejects_base_equal_to_quote() -> None:
    with pytest.raises(ValidationError):
        FxRateRecord(base="USD", quote="USD", rate_micro=1_000_000, source_date=date(2026, 8, 20))


def test_fx_rate_record_normalizes_uppercase() -> None:
    r = FxRateRecord(base="usd", quote="inr", rate_micro=1, source_date=date(2026, 8, 20))
    assert r.base == "USD"
    assert r.quote == "INR"


def test_fx_rate_record_requires_positive_rate_micro() -> None:
    with pytest.raises(ValidationError):
        FxRateRecord(base="USD", quote="INR", rate_micro=0, source_date=date(2026, 8, 20))


def test_fx_rate_record_derived_requires_derivation() -> None:
    with pytest.raises(ValidationError):
        FxRateRecord(
            base="USD", quote="INR", rate_micro=1, source_date=date(2026, 8, 20), derived=True
        )


def test_fx_snapshot_accepts_valid_shape() -> None:
    snapshot = FxSnapshot(
        provenance=_provenance(),
        rates=[FxRateRecord(base="USD", quote="INR", rate_micro=1, source_date=date(2026, 8, 20))],
    )
    assert snapshot.rates[0].base == "USD"
