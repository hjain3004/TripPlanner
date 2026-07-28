"""Pure projections from stored account rows into kernel request inputs.

``UserWallet`` (``core.models``) is the shape the optimizer already consumes. It
is **not** duplicated as a stored model — it is derived here from ``WalletEntry``
rows at request time.
"""

from __future__ import annotations

from collections.abc import Sequence

from accounts.models import WalletEntry
from core.models import UserWallet


def build_user_wallet(entries: Sequence[WalletEntry]) -> UserWallet:
    """Fold stored wallet rows into the kernel's request-time ``UserWallet``.

    Deterministic: ``card_ids`` and ``points_balances`` come out sorted regardless
    of input order, so the optimizer's output stays byte-reproducible.

    Duplicate points currencies collapse by **max, not sum**. Cards from one issuer
    typically share a single pooled balance, so summing user-entered pool figures
    would overstate available points and could produce an unfundable transfer plan.
    Max never overstates.
    """
    card_ids: set[str] = set()
    balances: dict[str, int] = {}
    for entry in entries:
        card_ids.add(entry.card_id)
        for currency_id, balance in entry.points_balances.items():
            current = balances.get(currency_id)
            if current is None or balance > current:
                balances[currency_id] = balance
    return UserWallet(
        card_ids=sorted(card_ids),
        points_balances={key: balances[key] for key in sorted(balances)},
    )
