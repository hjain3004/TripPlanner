"""Approved card products, read from the seeded knowledge base (spec 17 §3).

The wallet stores a ``card_id`` that is a knowledge-base slug, because the
optimizer resolves earn rules *by product*. This module is the single place that
answers "which products may a user attach, and is this slug real?" — and it
answers from the same ``KnowledgeBase`` the optimizer uses, never from a
hardcoded list, so the two can never drift.

Deliberately **not** exposed: annual fee, forex markup, earn rates, reward rules,
valuations, and provenance. Those are optimizer inputs; a card picker needs a
name and an issuer. Surfacing earn arithmetic here would also invite a frontend
to do reward math, which the project forbids.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from core.db import KnowledgeBase


class UnknownCardProductError(ValueError):
    """Raised when a card slug is not a product in the seeded knowledge base."""


class CardProductOut(BaseModel):
    """Display-safe view of one attachable card product."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    card_id: str
    display_name: str
    issuer: str
    is_eligible: bool


def _is_costable(kb: KnowledgeBase, card_id: str) -> bool:
    """Whether the optimizer can actually price this product.

    A product with neither a reward rule nor a positive base earn rate would be
    selectable but uncostable, which is worse than absent. Currently true for
    every seeded card; it exists so a malformed seed row surfaces as ineligible
    instead of silently producing a zero-reward plan.
    """
    card = kb.card(card_id)
    return bool(kb.rules_for_card(card_id)) or card.base_earn.points > 0


def list_card_products(kb: KnowledgeBase) -> list[CardProductOut]:
    """Every attachable card product, ordered by ``card_id``.

    ``KnowledgeBase.cards()`` already sorts by id; the order is part of the
    contract so repeat calls and the generated client stay stable.
    """
    return [
        CardProductOut(
            card_id=card.id,
            display_name=card.name,
            issuer=card.issuer,
            is_eligible=_is_costable(kb, card.id),
        )
        for card in kb.cards()
    ]


def assert_known_card_id(kb: KnowledgeBase, card_id: str) -> None:
    """Raise ``UnknownCardProductError`` unless ``card_id`` is a real product.

    Validating against the KB rather than a local allowlist is what stops the
    API accepting a card the optimizer cannot resolve earn rules for.
    """
    if not card_id or not kb.has_card(card_id):
        raise UnknownCardProductError(f"unknown card product: {card_id!r}")
