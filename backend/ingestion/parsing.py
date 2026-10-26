"""Deterministic parsers for financial notation found in source material."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


class UnresolvedValueError(ValueError):
    """The source notation is unsupported or ambiguous."""


def _text(raw: Any) -> str:
    if isinstance(raw, bool) or raw is None:
        raise UnresolvedValueError("value is missing or boolean")
    return unicodedata.normalize("NFKC", str(raw)).replace("\u00a0", " ").strip()


def _decimal(raw: Any, *, suffix: str = "") -> Decimal:
    text = _text(raw)
    if suffix and text.lower().endswith(suffix):
        text = text[: -len(suffix)].strip()
    text = text.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        raise UnresolvedValueError(f"unsupported numeric notation: {raw!r}")
    try:
        return Decimal(text)
    except InvalidOperation as error:
        raise UnresolvedValueError(f"invalid number: {raw!r}") from error


def _scaled(value: Decimal, scale: int) -> int:
    result = (value * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if result < 0:
        raise UnresolvedValueError("financial values cannot be negative")
    return int(result)


def parse_money_minor(raw: Any) -> int:
    """Parse a major-unit money amount into integer minor units."""
    text = _text(raw)
    text = re.sub(r"^(?:₹|Rs\.?|INR|USD|AED|SGD)\s*", "", text, flags=re.I)
    if not text:
        raise UnresolvedValueError("money amount is empty")
    return _scaled(_decimal(text), 100)


def parse_basis_points(raw: Any) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    text = _text(raw).lower()
    if text.endswith("bp"):
        return _scaled(_decimal(text[:-2].strip()), 1)
    if text.endswith("%"):
        return _scaled(_decimal(text[:-1].strip()), 100)
    raise UnresolvedValueError("percentage must include % or bp")


def parse_points(raw: Any) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    text = _text(raw).lower()
    text = re.sub(r"\s*(?:points?|pts?)\s*$", "", text)
    value = _decimal(text)
    if value != value.to_integral_value() or value < 0:
        raise UnresolvedValueError("points must be a non-negative integer")
    return int(value)


def parse_ratio(raw: Any) -> tuple[int, int]:
    text = _text(raw)
    match = re.fullmatch(r"(\d+)\s*[:/]\s*(\d+)", text)
    if match is None or int(match.group(1)) <= 0 or int(match.group(2)) <= 0:
        raise UnresolvedValueError("ratio must be two positive integers")
    return int(match.group(1)), int(match.group(2))


def parse_date_value(raw: Any) -> date:
    if isinstance(raw, date):
        return raw
    text = _text(raw)
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise UnresolvedValueError("dates must use ISO YYYY-MM-DD notation") from error


def parse_rate_micro(raw: Any) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    text = _text(raw)
    text = re.sub(r"^(?:₹|Rs\.?|INR|USD|AED|SGD)\s*", "", text, flags=re.I)
    return _scaled(_decimal(text), 1_000_000)


def parse_field_value(field_path: str, raw: Any, *, expected: Any) -> Any:
    """Parse one raw source value according to the existing field type/name."""
    leaf = field_path.rsplit(".", 1)[-1]
    if leaf.endswith("_minor") or leaf in {"price_minor", "fees_minor"}:
        return parse_money_minor(raw)
    if leaf.endswith("_bp") or leaf == "discount_bp":
        return parse_basis_points(raw)
    if leaf == "rate_micro" or leaf == "value_micro_major_per_point":
        return parse_rate_micro(raw)
    if leaf in {"ratio_from", "ratio_to"}:
        ratio_from, ratio_to = parse_ratio(raw)
        return ratio_from if leaf == "ratio_from" else ratio_to
    if leaf in {"points", "max_points", "min_points", "miles_cost", "min_transfer", "increment"}:
        return parse_points(raw)
    if leaf in {"valid_from", "valid_to", "as_of"} or getattr(expected, "__class__", None) is date:
        return parse_date_value(raw)
    if isinstance(expected, bool):
        if isinstance(raw, bool):
            return raw
        raise UnresolvedValueError("boolean fields require a boolean value")
    if isinstance(expected, int):
        value = _decimal(raw)
        if value != value.to_integral_value() or value < 0:
            raise UnresolvedValueError("integer field requires a non-negative integer")
        return int(value)
    if isinstance(expected, str):
        return _text(raw)
    if isinstance(expected, list):
        if not isinstance(raw, list):
            raise UnresolvedValueError("list field requires a list")
        return raw
    return raw
