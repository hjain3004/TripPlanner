"""Deterministic FX snapshot builder -- pure function, no I/O.

Rounding rule: banker's rounding (ROUND_HALF_EVEN) at the rate_micro integer
boundary -- the standard deterministic tie-break with no directional bias.
Cross-rates are computed only when both legs against a common pivot base
exist in the source data; an unresolvable cross pair is recorded as a
provenance warning, never invented.
"""

from __future__ import annotations

import decimal
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal

from gateway.reference.contracts import SourceProvenance
from gateway.reference.fx.contracts import FxRateRecord, FxSnapshot
from gateway.reference.fx.errors import FxImportError
from gateway.reference.fx.parse import RawFxQuote

MICRO = Decimal(1_000_000)


def decimal_to_rate_micro(rate: Decimal) -> int:
    return int((rate * MICRO).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))


def build_fx_snapshot(
    raw_quotes: list[RawFxQuote],
    *,
    source: dict[str, object],
    now: date,
    cross_pairs: list[tuple[str, str]],
) -> FxSnapshot:
    seen: dict[tuple[str, str], RawFxQuote] = {}
    for q in raw_quotes:
        key = (q.base, q.quote)
        if key in seen and seen[key].rate != q.rate:
            raise FxImportError(
                "invalid_response",
                f"duplicate {key} with conflicting rates {seen[key].rate} vs {q.rate}",
            )
        seen[key] = q

    direct_by_pair = {k: v.rate for k, v in seen.items()}
    source_warnings = source.get("warnings", [])
    warnings: list[str] = list(source_warnings) if isinstance(source_warnings, list) else []

    records: list[FxRateRecord] = [
        FxRateRecord(
            base=q.base,
            quote=q.quote,
            rate_micro=decimal_to_rate_micro(q.rate),
            source_date=date.fromisoformat(q.date),
            derived=False,
            derivation=None,
        )
        for q in sorted(seen.values(), key=lambda x: (x.base, x.quote))
    ]

    for a, b in sorted(cross_pairs):
        pivot_bases = {base for (base, _quote) in direct_by_pair}
        found = False
        for pivot in sorted(pivot_bases):
            if (pivot, a) in direct_by_pair and (pivot, b) in direct_by_pair:
                with decimal.localcontext() as ctx:
                    ctx.prec = 50
                    cross = direct_by_pair[(pivot, b)] / direct_by_pair[(pivot, a)]
                records.append(
                    FxRateRecord(
                        base=a,
                        quote=b,
                        rate_micro=decimal_to_rate_micro(cross),
                        source_date=now,
                        derived=True,
                        derivation=f"{pivot}/{b} ÷ {pivot}/{a}",
                    )
                )
                found = True
                break
        if not found:
            warnings.append(f"cannot derive {a}->{b}: missing a common pivot leg in source data")

    provenance = SourceProvenance(
        **{**source, "record_count": len(records), "warnings": warnings}
    )
    records.sort(key=lambda r: (r.base, r.quote))
    return FxSnapshot(provenance=provenance, rates=records)
