"""Price labels become money only when scope, currency and precision are unambiguous.

Label strings in these tests are synthetic: upstream's source shows prices travel only as
accessibility-label strings (``structuredDisplayPrice.*.accessibilityLabel``), but the
exact wording a live listing produces has not been captured.
"""

from __future__ import annotations

import pytest

from gateway.travel.adapters.openbnb.price import (
    Money,
    classify_price_label,
    reconcile_breakdown,
)


def _classify(label: str | None, nights: int = 3, bare: str | None = None):  # type: ignore[no-untyped-def]
    return classify_price_label(label, nights=nights, bare_dollar_currency=bare)


@pytest.mark.parametrize(
    ("label", "minor", "currency"),
    [
        ("US$1,029 total", 102_900, "USD"),
        ("S$ 450 total", 45_000, "SGD"),
        ("€450.50 total", 45_050, "EUR"),
        ("£1,200.05 total", 120_005, "GBP"),
        ("₹45,000 total", 4_500_000, "INR"),
        ("JPY 120,000 total", 120_000, "JPY"),  # zero-exponent currency
        ("450 EUR total", 45_000, "EUR"),
        ("A$900 total", 90_000, "AUD"),
        ("$450 for 3 nights", 45_000, "USD"),
    ],
)
def test_a_total_label_becomes_integer_minor_units(label: str, minor: int, currency: str) -> None:
    result = _classify(label, bare="USD")
    assert result.kind == "stay_total", label
    assert result.money == Money(minor=minor, currency=currency)
    assert result.before_taxes is False


def test_a_bare_dollar_sign_is_ambiguous_without_an_explicit_assumption() -> None:
    result = _classify("$1,029 total")
    assert result.kind == "currency_ambiguous"
    assert result.money is None
    assert _classify("$1,029 total", bare="USD").money == Money(minor=102_900, currency="USD")


@pytest.mark.parametrize("label", ["¥12,000 total", "kr 900 total"])
def test_ambiguous_or_unsupported_currency_is_never_guessed(label: str) -> None:
    assert _classify(label, bare="USD").kind in {"currency_ambiguous", "unknown"}
    assert _classify(label, bare="USD").money is None


@pytest.mark.parametrize(
    "label", ["$150 per night", "$150 night", "US$150 / night", "US$150 nightly"]
)
def test_a_nightly_rate_is_never_a_stay_total(label: str) -> None:
    result = _classify(label, bare="USD")
    assert result.kind == "nightly"
    assert result.money is not None  # kept as discovery-only evidence, labelled nightly


def test_a_total_that_names_a_different_night_count_is_a_mismatch() -> None:
    assert _classify("US$750 for 5 nights", nights=5).kind == "stay_total"
    assert _classify("US$750 for 5 nights", nights=3).kind == "nights_mismatch"


def test_before_taxes_is_carried_not_dropped() -> None:
    result = _classify("US$900 total before taxes")
    assert result.kind == "stay_total"
    assert result.before_taxes is True


@pytest.mark.parametrize(
    "label",
    [
        "US$1,200 US$1,029 total",  # struck-through original and discounted price
        "US$150 per night, US$450 total",  # two scopes in one label
        "US$450 total or US$150 per night",
        "US$150 per night total",  # contradictory scope words
    ],
)
def test_a_label_with_more_than_one_price_or_scope_is_ambiguous(label: str) -> None:
    assert _classify(label).kind == "ambiguous"
    assert _classify(label).money is None


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        (None, "missing"),
        ("", "missing"),
        ("   ", "missing"),
        ("Price unavailable", "unknown"),
        ("from US$90", "unknown"),  # no scope word
        ("US$0 total", "zero_price"),
        ("US$0.00 total", "zero_price"),
        ("US$150.123 total", "invalid"),  # more decimals than the currency allows
        ("JPY 150.5 total", "invalid"),
        ("US$99,999,999,999 total", "invalid"),  # beyond the sanity bound
        ("US$12,34 total", "invalid"),  # malformed grouping
    ],
)
def test_unusable_labels_are_typed_never_defaulted(label: str | None, kind: str) -> None:
    result = _classify(label)
    assert result.kind == kind, label
    assert result.money is None or kind == "nightly"


# --------------------------------------------------------------------------- #
# Breakdown reconciliation (the flattened ``priceDetails.items`` string)
# --------------------------------------------------------------------------- #

TOTAL = Money(minor=94_000, currency="USD")
ITEMIZED = "5 nights x US$150: US$750, Cleaning fee: US$60, Service fee: US$90, Taxes: US$40"


def test_a_reconciling_itemization_yields_components() -> None:
    breakdown, reason = reconcile_breakdown(ITEMIZED, total=TOTAL, nights=5)
    assert reason is None
    assert breakdown is not None
    assert (breakdown.base_minor, breakdown.fees_minor, breakdown.taxes_minor) == (
        75_000,
        15_000,
        4_000,
    )


def test_thousands_separators_do_not_split_an_item() -> None:
    text = "5 nights x US$1,000: US$5,000, Cleaning fee: US$1,200, Taxes: US$300"
    breakdown, reason = reconcile_breakdown(text, total=Money(650_000, "USD"), nights=5)
    assert reason is None and breakdown is not None
    assert breakdown.fees_minor == 120_000


def test_itemization_without_taxes_leaves_taxes_unknown_not_zero() -> None:
    text = "5 nights x US$150: US$750, Cleaning fee: US$60"
    breakdown, reason = reconcile_breakdown(text, total=Money(81_000, "USD"), nights=5)
    assert reason is None and breakdown is not None
    assert breakdown.taxes_minor is None


def test_a_list_form_of_items_is_accepted() -> None:
    items = [
        {"description": "5 nights x US$150", "priceString": "US$750"},
        {"description": "Taxes", "priceString": "US$40"},
    ]
    breakdown, _ = reconcile_breakdown(items, total=Money(79_000, "USD"), nights=5)
    assert breakdown is not None and breakdown.taxes_minor == 4_000


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        (ITEMIZED.replace("US$90", "US$91"), "breakdown_mismatch"),  # does not sum to total
        ("5 nights x US$150: US$750, Mystery: US$190", "breakdown_unusable"),  # unclassified
        ("3 nights x US$250: US$750, Taxes: US$190", "nights_mismatch"),
        ("5 nights x US$150: €750, Taxes: US$190", "breakdown_unusable"),  # mixed currency
        ("Cleaning fee: US$60, Taxes: US$880", "breakdown_unusable"),  # no nightly base line
        ("5 nights x US$150: US$750, 5 nights x US$150: US$750", "breakdown_unusable"),
        ("garbled text without any structure", "breakdown_unusable"),
        ("", "breakdown_unusable"),
        (None, "breakdown_unusable"),
        (12345, "breakdown_unusable"),
        ("5 nights x US$150: US$750, Total: US$900", "breakdown_mismatch"),
    ],
)
def test_an_itemization_that_cannot_be_trusted_is_dropped_with_a_reason(
    value: object, reason: str
) -> None:
    breakdown, why = reconcile_breakdown(value, total=TOTAL, nights=5)
    assert breakdown is None
    assert why == reason


def test_itemization_size_is_bounded() -> None:
    huge = ", ".join(f"Fee {i}: US$1" for i in range(500))
    breakdown, why = reconcile_breakdown(huge, total=TOTAL, nights=5)
    assert breakdown is None and why == "breakdown_unusable"
