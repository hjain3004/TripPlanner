from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from gateway.reference.contracts import SourceProvenance


def _provenance(**overrides: object) -> SourceProvenance:
    base: dict[str, object] = dict(
        source_id="frankfurter",
        source_owner="Frankfurter (frankfurter.dev)",
        source_url="https://api.frankfurter.dev/v2/rates",
        release_id="2026-08-20",
        retrieved_at=date(2026, 8, 20),
        licence_id="frankfurter-api-blended-central-bank-sources",
        attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
        terms_reference="https://frankfurter.dev/docs",
        content_hash="a" * 64,
        record_count=3,
        warnings=[],
    )
    base.update(overrides)
    return SourceProvenance(**base)  # type: ignore[arg-type]


def test_provenance_requires_nonempty_source_id() -> None:
    with pytest.raises(ValidationError):
        _provenance(source_id="")


def test_provenance_requires_full_length_sha256_hash() -> None:
    with pytest.raises(ValidationError):
        _provenance(content_hash="short")


def test_provenance_rejects_negative_record_count() -> None:
    with pytest.raises(ValidationError):
        _provenance(record_count=-1)


def test_provenance_accepts_valid_shape() -> None:
    p = _provenance()
    assert p.source_id == "frankfurter"
    assert p.warnings == []
