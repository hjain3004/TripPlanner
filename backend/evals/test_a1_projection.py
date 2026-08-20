from __future__ import annotations

from datetime import UTC, datetime

from accounts.models import WalletEntry
from accounts.projection import build_user_wallet
from core.models import UserWallet

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _entry(
    entry_id: str, card_id: str, balances: dict[str, int] | None = None
) -> WalletEntry:
    return WalletEntry(
        id=entry_id,
        user_id="u1",
        card_id=card_id,
        nickname=entry_id,
        points_balances=balances or {},
        added_at=NOW,
    )


def test_empty_wallet_projects_to_an_empty_user_wallet() -> None:
    wallet = build_user_wallet([])

    assert wallet == UserWallet(card_ids=[], points_balances={})


def test_projection_collects_card_ids_and_balances() -> None:
    wallet = build_user_wallet(
        [
            _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 140000}),
            _entry("w2", "amex-platinum", {"membership-rewards": 50000}),
        ]
    )

    assert wallet.card_ids == ["amex-platinum", "hdfc-infinia"]
    assert wallet.points_balances == {
        "hdfc-reward-points": 140000,
        "membership-rewards": 50000,
    }


def test_projection_is_order_independent() -> None:
    a = _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 100})
    b = _entry("w2", "amex-platinum", {"membership-rewards": 200})

    assert build_user_wallet([a, b]) == build_user_wallet([b, a])


def test_duplicate_card_ids_appear_once() -> None:
    wallet = build_user_wallet(
        [_entry("w1", "hdfc-infinia"), _entry("w2", "hdfc-infinia")]
    )

    assert wallet.card_ids == ["hdfc-infinia"]


def test_a_shared_points_pool_is_not_double_counted() -> None:
    """Two cards on one pooled currency collapse by max, never by sum."""
    wallet = build_user_wallet(
        [
            _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 140000}),
            _entry("w2", "hdfc-diners-black", {"hdfc-reward-points": 140000}),
        ]
    )

    assert wallet.points_balances == {"hdfc-reward-points": 140000}


def test_the_larger_recorded_balance_wins() -> None:
    wallet = build_user_wallet(
        [
            _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 90000}),
            _entry("w2", "hdfc-diners-black", {"hdfc-reward-points": 140000}),
        ]
    )

    assert wallet.points_balances == {"hdfc-reward-points": 140000}
