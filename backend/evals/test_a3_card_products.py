"""A3 Task 4 — the approved card-product listing comes from the seeded KB.

The listing must be the same source the optimizer resolves earn rules from. A
hardcoded slug list would drift, and would let the API accept a card the
optimizer cannot cost.

Note on fields: the committed plan sketched a ``points_currency_id``, but the
seeded knowledge base has no card -> loyalty-currency link.
``Card.base_earn.currency`` is the *spend* currency (``INR`` for all four seeded
cards), ``PointValuation.currency`` is the currency a valuation is denominated
in, and loyalty currencies are ``LoyaltyProgram`` ids referenced by
``TransferEdge`` (e.g. ``voyager-prime`` -> ``lionmiles``) which no ``Card`` row
points at. Exposing a derived points currency would therefore assert a fact the
data does not carry, so the field is omitted rather than shipped permanently
null. Recorded in DEVIATIONS.md.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from accounts.cards import (
    CardProductOut,
    UnknownCardProductError,
    assert_known_card_id,
    list_card_products,
)
from accounts.store import AccountStore
from core.db import DB_PATH, load_kb

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def test_listing_comes_from_the_kb_not_a_hardcoded_list() -> None:
    kb = load_kb(DB_PATH)
    products = list_card_products(kb)
    assert [p.card_id for p in products] == [c.id for c in kb.cards()]
    assert products, "the seeded KB must expose at least one card product"


def test_ordering_is_deterministic_by_card_id() -> None:
    kb = load_kb(DB_PATH)
    ids = [p.card_id for p in list_card_products(kb)]
    assert ids == sorted(ids)
    # Repeat calls are identical, so a generated client and the optimizer never
    # disagree about order.
    assert list_card_products(kb) == list_card_products(kb)


def test_display_fields_come_from_the_card_record() -> None:
    kb = load_kb(DB_PATH)
    by_id = {c.id: c for c in kb.cards()}
    for product in list_card_products(kb):
        card = by_id[product.card_id]
        assert product.display_name == card.name
        assert product.issuer == card.issuer


def test_unknown_card_id_is_rejected() -> None:
    kb = load_kb(DB_PATH)
    with pytest.raises(UnknownCardProductError):
        assert_known_card_id(kb, "not-a-real-card")
    with pytest.raises(UnknownCardProductError):
        assert_known_card_id(kb, "")


def test_known_card_id_passes() -> None:
    kb = load_kb(DB_PATH)
    for card in kb.cards():
        assert_known_card_id(kb, card.id)  # must not raise


def test_exposes_only_display_safe_fields() -> None:
    """Pin the contract: no reward arithmetic, fees, or provenance internals."""
    assert set(CardProductOut.model_fields) == {
        "card_id",
        "display_name",
        "issuer",
        "is_eligible",
    }


def test_no_reward_arithmetic_or_private_internals_leak() -> None:
    kb = load_kb(DB_PATH)
    forbidden = {
        "annual_fee_minor",
        "fee_currency",
        "forex_markup_bp",
        "forex_markup_tax_bp",
        "base_earn",
        "provenance",
        "lounge_intl_visits_per_year",
        "network",
        "country",
    }
    for product in list_card_products(kb):
        dumped = product.model_dump()
        assert forbidden.isdisjoint(dumped.keys())
        # And no raw ORM/KB object smuggled through a field value.
        for value in dumped.values():
            assert isinstance(value, str | bool)


def test_eligibility_reflects_whether_the_optimizer_can_cost_the_product() -> None:
    kb = load_kb(DB_PATH)
    for product in list_card_products(kb):
        card = kb.card(product.card_id)
        costable = bool(kb.rules_for_card(card.id)) or card.base_earn.points > 0
        assert product.is_eligible is costable


def test_listing_does_not_mutate_account_data(tmp_path: Path) -> None:
    """Reading the card catalogue is read-only with respect to accounts."""
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    entry = store.add_wallet_entry(
        user_id="u-alice", card_id="hdfc-infinia", nickname="Primary", now=NOW
    )
    before = store.wallet_entries("u-alice")

    list_card_products(load_kb(DB_PATH))

    after = store.wallet_entries("u-alice")
    assert after == before
    assert [e.id for e in after] == [entry.id]
    assert after[0].version == 1
