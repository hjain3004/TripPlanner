"""Price-label parsing for OpenBnB.

Upstream (v0.3.0, source-verified) exposes prices only as accessibility-label strings and
a flattened ``priceDetails.items`` string; there is no numeric amount, currency field or
explicit scope. This module therefore refuses to guess:

* a nightly rate is never a stay total, and carries a ``nightly`` kind instead;
* a bare ``$`` is not a currency (USD, SGD, AUD, ...) unless the caller supplies an
  explicit, recorded assumption;
* a label with more than one price or more than one scope is ``ambiguous``;
* money is parsed with ``Decimal`` straight to integer minor units; more precision than
  the currency allows is ``invalid`` (never rounded), and zero is ``zero_price``.

Nothing here invents a number: every outcome is either exact or a typed refusal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

# Currencies this adapter will name. Minor-unit exponent per ISO 4217.
_EXPONENT: dict[str, int] = {
    "USD": 2, "EUR": 2, "GBP": 2, "INR": 2, "SGD": 2, "AED": 2, "AUD": 2, "CAD": 2,
    "CHF": 2, "THB": 2, "MYR": 2, "IDR": 2, "HKD": 2, "NZD": 2, "JPY": 0, "KRW": 0,
    "VND": 0,
}  # fmt: skip
_SYMBOLS: dict[str, str | None] = {
    "US$": "USD", "S$": "SGD", "A$": "AUD", "C$": "CAD", "HK$": "HKD", "NZ$": "NZD",
    "€": "EUR", "£": "GBP", "₹": "INR",
    "$": None,  # bare dollar: ambiguous unless the caller records an assumption
    "¥": None,  # JPY or CNY
}  # fmt: skip
MAX_MINOR = 1_000_000_000
MAX_BREAKDOWN_CHARS = 2000
MAX_BREAKDOWN_ITEMS = 12

_CODES = "|".join(sorted(_EXPONENT))
_SYMBOL_ALT = "|".join(re.escape(s) for s in sorted(_SYMBOLS, key=len, reverse=True))
# ASCII digits only (``\d`` would accept other scripts' digits). A symbol or code must not be
# the tail of a longer one ("CA$", "MX$", "R$" are not "A$"/"$"), hence the left boundary.
_PREFIX_TOKEN = re.compile(
    rf"(?<![A-Za-z])(?P<neg>-)?(?P<cur>{_SYMBOL_ALT}|(?:{_CODES})\s?)\s?(?P<num>[0-9][0-9,.]*)"
)
_SUFFIX_TOKEN = re.compile(rf"(?<![\w$€£₹¥,.])(?P<num>[0-9][0-9,.]*)\s?(?P<cur>{_CODES})\b")
_NUMBER = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?")
# What may not follow a number: more digits after a group separator or space (a truncated
# "1 234"), a range ("500-600", "500 to 600") or an exponent ("1e3").
_BAD_TAIL = re.compile(
    r"[\s\u00a0\u202f’'‘.,\-\u2013\u2014/]*[0-9]|[eE][+-]?[0-9]|\s+to\s+[0-9]", re.IGNORECASE
)
MAX_NUMBER_CHARS = 20

PriceKind = Literal[
    "stay_total",
    "nightly",
    "unknown",
    "ambiguous",
    "currency_ambiguous",
    "nights_mismatch",
    "zero_price",
    "invalid",
    "missing",
]


@dataclass(frozen=True)
class Money:
    minor: int
    currency: str


@dataclass(frozen=True)
class PriceLabel:
    kind: PriceKind
    money: Money | None = None
    before_taxes: bool = False
    assumed_currency: bool = False  # a bare "$" was read as the caller's recorded assumption


@dataclass(frozen=True)
class Breakdown:
    base_minor: int
    fees_minor: int
    taxes_minor: int | None


class _Invalid(Exception):
    """A token that looks like money but is not exact (precision, grouping, size)."""


@dataclass(frozen=True)
class _Token:
    start: int
    end: int
    minor: int
    currency: str | None  # None => the symbol alone does not identify a currency
    assumed: bool = False


def _to_minor(number: str, currency: str | None) -> int:
    cleaned = number.rstrip(",.")
    if len(cleaned) > MAX_NUMBER_CHARS or _NUMBER.fullmatch(cleaned) is None:
        raise _Invalid("malformed number")
    exponent = _EXPONENT.get(currency, 2) if currency else 2
    if "." in cleaned and len(cleaned.split(".", 1)[1]) > exponent:
        raise _Invalid("more precision than the currency allows")
    try:
        scaled = Decimal(cleaned.replace(",", "")) * (Decimal(10) ** exponent)
    except InvalidOperation:  # pragma: no cover - guarded by the regex above
        raise _Invalid("malformed number") from None
    if scaled != scaled.to_integral_value():
        raise _Invalid("more precision than the currency allows")
    minor = int(scaled)
    if minor > MAX_MINOR:
        raise _Invalid("amount outside the sanity bound")
    return minor


def _scan(text: str, bare_dollar_currency: str | None) -> list[_Token]:
    tokens: list[_Token] = []
    for match in _PREFIX_TOKEN.finditer(text):
        if match.group("neg"):
            raise _Invalid("negative amount")
        if _BAD_TAIL.match(text, match.end()):
            raise _Invalid("number is truncated or part of a range")
        symbol = match.group("cur")
        currency = _SYMBOLS[symbol] if symbol in _SYMBOLS else symbol.strip()
        if symbol == "$":
            currency = bare_dollar_currency
        tokens.append(
            _Token(
                match.start(),
                match.end(),
                _to_minor(match.group("num"), currency),
                currency,
                assumed=symbol == "$" and bare_dollar_currency is not None,
            )
        )
    for match in _SUFFIX_TOKEN.finditer(text):
        if any(t.start <= match.start() < t.end for t in tokens):
            continue
        currency = match.group("cur")
        if _BAD_TAIL.match(text, match.end()):
            raise _Invalid("number is truncated or part of a range")
        tokens.append(
            _Token(
                match.start(),
                match.end(),
                _to_minor(match.group("num"), currency),
                currency,
            )
        )
    return sorted(tokens, key=lambda t: t.start)


_NIGHTLY = re.compile(r"\bper night\b|\ba night\b|/\s?night\b|\bnightly\b|\bnight\b")
_TOTAL = re.compile(r"\btotal\b")
_FOR_NIGHTS = re.compile(r"\bfor (\d+) nights?\b")
_BEFORE_TAXES = re.compile(r"\b(?:before|excluding|plus|\+) ?taxes\b|\bexcl\.? taxes\b")


def classify_price_label(
    label: str | None, *, nights: int, bare_dollar_currency: str | None = None
) -> PriceLabel:
    if label is None or not label.strip():
        return PriceLabel("missing")
    try:
        tokens = _scan(label, bare_dollar_currency)
    except _Invalid:
        return PriceLabel("invalid")
    # Digits glued to a currency marker that did not form a token are still malformed.
    if not tokens:
        if _PREFIX_TOKEN.search(label) or _SUFFIX_TOKEN.search(label):
            return PriceLabel("invalid")
        return PriceLabel("unknown")
    if len(tokens) > 1:
        return PriceLabel("ambiguous")
    token = tokens[0]
    lowered = label.casefold()
    nights_match = _FOR_NIGHTS.search(lowered)
    is_total = _TOTAL.search(lowered) is not None or nights_match is not None
    is_nightly = _NIGHTLY.search(lowered) is not None
    if is_total and is_nightly:
        return PriceLabel("ambiguous")
    if not is_total and not is_nightly:
        return PriceLabel("unknown")
    if token.currency is None:
        return PriceLabel("currency_ambiguous")
    if token.minor == 0:
        return PriceLabel("zero_price")
    money = Money(token.minor, token.currency)
    if is_nightly:
        return PriceLabel("nightly", money)
    if nights_match is not None and int(nights_match.group(1)) != nights:
        return PriceLabel("nights_mismatch")
    return PriceLabel(
        "stay_total",
        money,
        before_taxes=_BEFORE_TAXES.search(lowered) is not None,
        assumed_currency=token.assumed,
    )


_ITEM_SPLIT = re.compile(r",\s+(?=[^:,]{1,80}:\s)")
_BASE_DESC = re.compile(r"(\d+) nights?\b")
_TAX_DESC = re.compile(r"\b(?:tax|taxes|vat|gst)\b")
_FEE_DESC = re.compile(r"\bfees?\b")


def _item_pairs(value: object) -> list[tuple[str, str]] | None:
    if isinstance(value, str):
        if not value.strip() or len(value) > MAX_BREAKDOWN_CHARS:
            return None
        pairs: list[tuple[str, str]] = []
        for part in _ITEM_SPLIT.split(value.strip()):
            description, colon, price = part.partition(":")
            if not colon or not description.strip() or not price.strip():
                return None
            pairs.append((description.strip(), price.strip()))
    elif isinstance(value, list):
        pairs = []
        for item in value:
            if not isinstance(item, dict):
                return None
            description, price = item.get("description"), item.get("priceString")
            if not isinstance(description, str) or not isinstance(price, str):
                return None
            pairs.append((description.strip(), price.strip()))
    else:
        return None
    if not pairs or len(pairs) > MAX_BREAKDOWN_ITEMS:
        return None
    if any(len(description) > 80 or len(price) > 40 for description, price in pairs):
        return None
    return pairs


def _single_money(price: str, bare_dollar_currency: str | None) -> Money | None:
    try:
        tokens = _scan(price, bare_dollar_currency)
    except _Invalid:
        return None
    if len(tokens) != 1:
        return None
    token = tokens[0]
    if token.currency is None or token.start != 0 or token.end != len(price):
        return None
    return Money(token.minor, token.currency)


def reconcile_breakdown(
    value: object,
    *,
    total: Money,
    nights: int,
    bare_dollar_currency: str | None = None,
) -> tuple[Breakdown | None, str | None]:
    """Components of ``total`` iff the itemization is well-formed and sums exactly to it.

    Returns ``(breakdown, None)`` or ``(None, reason)``. A missing taxes line leaves
    ``taxes_minor`` as ``None`` (unknown), never zero.
    """
    pairs = _item_pairs(value)
    if pairs is None:
        return None, "breakdown_unusable"
    base: int | None = None
    fees = 0
    taxes: int | None = None
    stated_total: int | None = None
    for description, price in pairs:
        money = _single_money(price, bare_dollar_currency)
        if money is None or money.currency != total.currency:
            return None, "breakdown_unusable"
        lowered = description.casefold()
        base_match = _BASE_DESC.match(lowered)
        if lowered.startswith("total"):
            if stated_total is not None:
                return None, "breakdown_unusable"
            stated_total = money.minor
        elif base_match is not None:
            if base is not None:
                return None, "breakdown_unusable"
            if int(base_match.group(1)) != nights:
                return None, "nights_mismatch"
            base = money.minor
        elif _FEE_DESC.search(lowered):
            fees += money.minor
        elif _TAX_DESC.search(lowered):
            taxes = (taxes or 0) + money.minor
        else:
            return None, "breakdown_unusable"
    if base is None:
        return None, "breakdown_unusable"
    if stated_total is not None and stated_total != total.minor:
        return None, "breakdown_mismatch"
    if base + fees + (taxes or 0) != total.minor:
        return None, "breakdown_mismatch"
    return Breakdown(base_minor=base, fees_minor=fees, taxes_minor=taxes), None
