"""Integer-only money primitives (spec 02 §1, §3; Tier-F: no floats, ever).

- points value: ``value_micro_major_per_point`` is millionths of a major unit;
  1 minor unit = 10^4 micro-major, so ``points * value // 10_000`` gives minor units.
- forex fee: ``amount * markup_bp/10^4 * (1 + tax_bp/10^4)`` = ``amount * markup_bp *
  (10^4 + tax_bp) // 10^8`` (floor).
"""

from __future__ import annotations


def points_value_minor(points: int, value_micro_major_per_point: int) -> int:
    return points * value_micro_major_per_point // 10_000


def forex_fee_minor(amount_minor: int, markup_bp: int, tax_bp: int) -> int:
    return amount_minor * markup_bp * (10_000 + tax_bp) // 100_000_000


def savings_pct_bp(savings_minor: int, gross_minor: int) -> int:
    if gross_minor <= 0:
        return 0
    return savings_minor * 10_000 // gross_minor
