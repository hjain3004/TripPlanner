"""Spend normalization (spec 02 §3).

In M1 the estimator (M2, spec 03 §4) is bypassed: the ``CostedTrip`` already
carries ready ``SpendLineItem``s (the golden harness supplies them directly).
This module is the seam where M2 will fold richer estimator output, FX
conversion to home currency, and destination-POS aggregation (at most two lines:
DINING + FOREX_GENERAL). For now it validates and passes the line items through.
"""

from __future__ import annotations

from core.models import CostedTrip, SpendLineItem


def normalize(trip: CostedTrip) -> list[SpendLineItem]:
    for line in trip.lines:
        if line.amount_minor < 0:
            raise ValueError(f"line {line.id!r} has negative amount")
        if not line.available_channels:
            raise ValueError(f"line {line.id!r} has no available channels")
    return list(trip.lines)
