"""Offer eligibility, stacking and application (spec 02 §6).

Per line item, at most one offer per ``stacking_class``. Application order is
``coupon -> bank_offer -> card_linked`` on the running (already-discounted)
amount; ``max_discount_minor`` caps each. Only ``INSTANT_DISCOUNT`` offers are
selected by the optimizer in M1 (``CASHBACK_LATER`` / ``BONUS_POINTS`` deferred
valuation and ``NO_COST_EMI`` are report-only — logged in DEVIATIONS).
"""

from __future__ import annotations

from datetime import date
from itertools import product

from core.db import KnowledgeBase
from core.models import (
    AppliedOffer,
    Card,
    Channel,
    Offer,
    OfferKind,
    SpendLineItem,
)

# Application order (spec 02 §6; card_linked appended — see DEVIATIONS).
STACKING_ORDER: tuple[str, str, str] = ("coupon", "bank_offer", "card_linked")


def card_eligible(offer: Offer, card: Card) -> bool:
    """card / issuer / network eligibility (spec 01 §6, 02 §6)."""
    if offer.card_ids is not None:
        if card.id not in offer.card_ids:
            return False
    elif offer.issuer is not None:
        # card_ids None + issuer set = any card of that issuer
        if card.issuer != offer.issuer:
            return False
    if offer.networks is not None and card.network not in offer.networks:
        return False
    return True


def eligible_offers(
    kb: KnowledgeBase,
    line: SpendLineItem,
    card: Card,
    channel: Channel,
    on_date: date,
) -> list[Offer]:
    """Instant-discount offers valid for (line, card, channel) before use-limits.

    ``min_txn`` is checked against the original (pre-discount) line amount.
    ``uses_per_card`` is *not* enforced here — that is a stateful allocation
    concern handled in ``allocate.py``.
    """
    candidates = kb.offers_matching(line.merchant_hint, channel, line.category, on_date)
    out: list[Offer] = []
    for o in candidates:
        if o.kind != OfferKind.INSTANT_DISCOUNT:
            continue
        if not card_eligible(o, card):
            continue
        if o.min_txn_minor is not None and line.amount_minor < o.min_txn_minor:
            continue
        out.append(o)
    return out


def offer_subsets(eligible: list[Offer]) -> list[list[Offer]]:
    """All stacking-legal subsets (<=1 per class), incl. empty, in application order."""
    by_class: dict[str, list[Offer | None]] = {c: [None] for c in STACKING_ORDER}
    for o in eligible:
        by_class[o.stacking_class].append(o)
    subsets: list[list[Offer]] = []
    for combo in product(*(by_class[c] for c in STACKING_ORDER)):
        subsets.append([o for o in combo if o is not None])
    return subsets


def discount_for(offer: Offer, running_amount: int) -> int:
    """Discount this offer yields on the running amount, capped and non-negative."""
    if offer.discount_flat_minor is not None:
        d = offer.discount_flat_minor
    elif offer.discount_bp is not None:
        d = running_amount * offer.discount_bp // 10_000
    else:
        d = 0
    if offer.max_discount_minor is not None:
        d = min(d, offer.max_discount_minor)
    return max(0, min(d, running_amount))


def apply_offer_subset(amount_minor: int, subset: list[Offer]) -> tuple[int, list[AppliedOffer]]:
    """Apply the subset in coupon->bank_offer->card_linked order on the running amount.

    Returns ``(total_instant_discount, applied)``. Every instant discount reduces
    the running amount (and therefore the downstream points base).
    """
    running = amount_minor
    total = 0
    applied: list[AppliedOffer] = []
    for o in subset:
        d = discount_for(o, running)
        running -= d
        total += d
        applied.append(
            AppliedOffer(offer_id=o.id, discount_minor=d, stacking_class=o.stacking_class)
        )
    return total, applied
