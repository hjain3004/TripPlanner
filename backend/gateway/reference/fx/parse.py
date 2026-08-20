"""Frankfurter v2 flat-array response parser -- raw bytes to Decimal quotes.

Uses json.loads(..., parse_float=Decimal) so no rate is ever materialized as
a binary float, even transiently.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from gateway.reference.fx.errors import FxImportError

MAX_BYTES_DEFAULT = 262_144


@dataclass(frozen=True)
class RawFxQuote:
    date: str
    base: str
    quote: str
    rate: Decimal


def parse_frankfurter_v2(raw: bytes, *, max_bytes: int = MAX_BYTES_DEFAULT) -> list[RawFxQuote]:
    if len(raw) > max_bytes:
        raise FxImportError("invalid_response", f"payload exceeds {max_bytes} byte bound")
    try:
        data = json.loads(raw, parse_float=Decimal)
    except json.JSONDecodeError as exc:
        raise FxImportError("invalid_response", f"malformed JSON: {exc}") from exc
    if not isinstance(data, list):
        raise FxImportError("invalid_response", "expected a top-level JSON array")

    quotes: list[RawFxQuote] = []
    for row in data:
        if not isinstance(row, dict):
            raise FxImportError("invalid_response", "each row must be a JSON object")
        try:
            base = str(row["base"]).strip().upper()
            quote = str(row["quote"]).strip().upper()
            date_str = str(row["date"])
            rate_raw = row["rate"]
        except KeyError as exc:
            raise FxImportError("invalid_response", f"missing field: {exc}") from exc

        if len(base) != 3 or not base.isalpha() or len(quote) != 3 or not quote.isalpha():
            raise FxImportError("invalid_response", f"unsupported currency code: {base}/{quote}")

        try:
            rate = rate_raw if isinstance(rate_raw, Decimal) else Decimal(str(rate_raw))
        except (InvalidOperation, ValueError) as exc:
            raise FxImportError(
                "invalid_response", f"malformed decimal rate: {rate_raw!r}"
            ) from exc

        if not rate.is_finite() or rate <= 0:
            raise FxImportError("invalid_response", f"non-positive or non-finite rate: {rate}")

        quotes.append(RawFxQuote(date=date_str, base=base, quote=quote, rate=rate))
    return quotes
