from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pytest

from gateway.reference.fx.build import build_fx_snapshot
from gateway.reference.fx.errors import FxImportError
from gateway.reference.fx.parse import parse_frankfurter_v2

FIXTURES = Path(__file__).parent.parent / "gateway" / "reference" / "fx" / "fixtures"


def _raw(name: str) -> bytes:
    return (FIXTURES / f"{name}.json").read_bytes()


def _source(raw: bytes, record_count: int, warnings: list[str] | None = None) -> dict:
    return dict(
        source_id="frankfurter",
        source_owner="Frankfurter (frankfurter.dev)",
        source_url="https://api.frankfurter.dev/v2/rates",
        release_id="2026-08-20",
        retrieved_at=date(2026, 8, 20),
        licence_id="frankfurter-api-blended-central-bank-sources",
        attribution="Exchange rate data from Frankfurter (frankfurter.dev)",
        terms_reference="https://frankfurter.dev/docs",
        content_hash=hashlib.sha256(raw).hexdigest(),
        record_count=record_count,
        warnings=warnings or [],
    )


def test_valid_fixture_produces_direct_rates_with_correct_rate_micro() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
    )
    assert snapshot.rates
    by_pair = {(r.base, r.quote): r for r in snapshot.rates}
    assert by_pair[("USD", "AED")].rate_micro == 3_672_500
    assert by_pair[("USD", "INR")].rate_micro == 95_680_000
    assert by_pair[("USD", "SGD")].rate_micro == 1_274_000
    assert all(r.derived is False for r in snapshot.rates)


def test_missing_currency_is_documented_not_invented() -> None:
    raw = _raw("frankfurter_missing_currency")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes,
        source=_source(raw, len(quotes)),
        now=date(2026, 8, 20),
        cross_pairs=[("SGD", "AED")],
    )
    assert not any(r.quote == "AED" or r.base == "AED" for r in snapshot.rates)
    assert any("AED" in w for w in snapshot.provenance.warnings)


def test_unsupported_currency_code_is_rejected() -> None:
    with pytest.raises(FxImportError) as exc_info:
        parse_frankfurter_v2(_raw("frankfurter_unsupported_code"))
    assert exc_info.value.code == "invalid_response"


def test_malformed_decimal_is_rejected() -> None:
    with pytest.raises(FxImportError) as exc_info:
        parse_frankfurter_v2(_raw("frankfurter_malformed"))
    assert exc_info.value.code == "invalid_response"


def test_duplicate_currency_pair_with_conflicting_rates_is_rejected() -> None:
    raw = _raw("frankfurter_duplicate")
    quotes = parse_frankfurter_v2(raw)
    with pytest.raises(FxImportError) as exc_info:
        build_fx_snapshot(
            quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
        )
    assert exc_info.value.code == "invalid_response"


def test_zero_rate_is_rejected() -> None:
    with pytest.raises(FxImportError):
        parse_frankfurter_v2(_raw("frankfurter_zero_rate"))


def test_negative_rate_is_rejected() -> None:
    with pytest.raises(FxImportError):
        parse_frankfurter_v2(_raw("frankfurter_negative_rate"))


def test_cross_rate_is_computed_only_when_both_legs_present_and_is_deterministic() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot1 = build_fx_snapshot(
        quotes,
        source=_source(raw, len(quotes)),
        now=date(2026, 8, 20),
        cross_pairs=[("SGD", "INR")],
    )
    snapshot2 = build_fx_snapshot(
        quotes,
        source=_source(raw, len(quotes)),
        now=date(2026, 8, 20),
        cross_pairs=[("SGD", "INR")],
    )
    cross1 = next(r for r in snapshot1.rates if (r.base, r.quote) == ("SGD", "INR"))
    cross2 = next(r for r in snapshot2.rates if (r.base, r.quote) == ("SGD", "INR"))
    assert cross1.derived is True
    assert cross1.rate_micro == cross2.rate_micro
    # 95.68 / 1.274 = 75.10204081632653... -> rate_micro rounds to 75_102_041
    assert cross1.rate_micro == 75_102_041


def test_integer_rounding_boundary_uses_banker_rounding() -> None:
    from decimal import Decimal

    from gateway.reference.fx.build import decimal_to_rate_micro

    assert decimal_to_rate_micro(Decimal("63.2000005")) == 63_200_000
    assert decimal_to_rate_micro(Decimal("63.2000015")) == 63_200_002


def test_repeated_build_is_byte_identical() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    s1 = build_fx_snapshot(
        quotes,
        source=_source(raw, len(quotes)),
        now=date(2026, 8, 20),
        cross_pairs=[("SGD", "INR")],
    )
    s2 = build_fx_snapshot(
        quotes,
        source=_source(raw, len(quotes)),
        now=date(2026, 8, 20),
        cross_pairs=[("SGD", "INR")],
    )
    assert s1.model_dump_json() == s2.model_dump_json()


def test_licence_and_provenance_are_retained_on_the_snapshot() -> None:
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
    )
    assert snapshot.provenance.licence_id == "frankfurter-api-blended-central-bank-sources"
    assert "Frankfurter" in snapshot.provenance.attribution
    assert snapshot.provenance.source_url == "https://api.frankfurter.dev/v2/rates"
    assert snapshot.provenance.content_hash == hashlib.sha256(raw).hexdigest()


def test_input_size_bound_is_enforced() -> None:
    oversized = json.dumps(
        [{"date": "2026-08-20", "base": "USD", "quote": "AED", "rate": 1.0}] * 20_000
    ).encode()
    assert len(oversized) > 262_144
    with pytest.raises(FxImportError) as exc_info:
        parse_frankfurter_v2(oversized, max_bytes=262_144)
    assert exc_info.value.code == "invalid_response"


def test_zero_network_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FX build must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    raw = _raw("frankfurter_valid")
    quotes = parse_frankfurter_v2(raw)
    snapshot = build_fx_snapshot(
        quotes, source=_source(raw, len(quotes)), now=date(2026, 8, 20), cross_pairs=[]
    )
    assert snapshot.rates


def test_existing_kernel_fx_seed_and_goldens_are_unchanged() -> None:
    from core.db import SEEDS_DIR

    seed_text = (SEEDS_DIR / "fx_rates.yaml").read_text()
    assert "base: SGD" in seed_text and "rate_micro: 63200000" in seed_text
    assert "base: USD" in seed_text and "rate_micro: 86500000" in seed_text
    assert "quote: USD" in seed_text and "rate_micro: 730000" in seed_text
