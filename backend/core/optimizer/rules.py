"""Reward-rule matching and the cap-aware earn schedule (spec 02 §4-§5).

Points per transaction are floored per block on the **post-instant-discount**
amount. Cap fall-through is mandatory: the best matching rule earns until its
pool is exhausted, then the next rule, then ``base_earn`` (uncapped in MVP).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from functools import cmp_to_key

from core.db import KnowledgeBase
from core.models import Card, Channel, EarnRate, RewardRule, SpendLineItem

# POS channels use the trip-start date for rule validity; others use booking date.
POS_CHANNELS: frozenset[Channel] = frozenset({Channel.POS_ABROAD, Channel.POS_DOMESTIC})


def pool_key(rule: RewardRule) -> str | None:
    """Cap-pool identity: shared group if set, else the rule's own pool. None = uncapped."""
    if rule.cap is None:
        return None
    if rule.cap.shared_cap_group:
        return f"{rule.card_id}:{rule.cap.shared_cap_group}"
    return f"{rule.card_id}:{rule.id}"


def _date_valid(rule: RewardRule, on_date: date) -> bool:
    if rule.valid_from is not None and on_date < rule.valid_from:
        return False
    if rule.valid_to is not None and on_date > rule.valid_to:
        return False
    return True


def _category_channel_currency_match(
    rule: RewardRule, line: SpendLineItem, channel: Channel
) -> bool:
    if line.category not in rule.categories:
        return False
    if line.category in rule.excluded_categories:
        return False
    if rule.channels is not None and channel not in rule.channels:
        return False
    if rule.currencies is not None and line.currency not in rule.currencies:
        return False
    return True


def _cmp_rules(a: RewardRule, b: RewardRule) -> int:
    # Higher marginal earn rate (points / per_amount) first; integer cross-multiply.
    lhs = a.earn.points * b.earn.per_amount_minor
    rhs = b.earn.points * a.earn.per_amount_minor
    if lhs != rhs:
        return -1 if lhs > rhs else 1
    if a.id != b.id:  # deterministic tie-break: rule id ascending
        return -1 if a.id < b.id else 1
    return 0


def matching_rules(
    kb: KnowledgeBase, line: SpendLineItem, card: Card, channel: Channel, on_date: date
) -> list[RewardRule]:
    """Date-valid rules matching (line, channel), sorted best marginal rate first."""
    out = [
        r
        for r in kb.rules_for_card(card.id)
        if _category_channel_currency_match(r, line, channel) and _date_valid(r, on_date)
    ]
    return sorted(out, key=cmp_to_key(_cmp_rules))


def expired_candidates(
    kb: KnowledgeBase, line: SpendLineItem, card: Card, channel: Channel, on_date: date
) -> list[RewardRule]:
    """Rules that match on category/channel/currency but fail date validity (for notes)."""
    return [
        r
        for r in kb.rules_for_card(card.id)
        if _category_channel_currency_match(r, line, channel) and not _date_valid(r, on_date)
    ]


@dataclass
class EarnSegment:
    """One tier of the earn schedule for a single line (drives explanations)."""

    source: str  # rule id, or "base"
    description: str
    points: int
    amount_minor: int  # spend covered by this tier
    pool_key: str | None = None


@dataclass
class EarnResult:
    total_points: int
    segments: list[EarnSegment] = field(default_factory=list)
    pool_draws: dict[str, int] = field(default_factory=dict)


def earn_schedule(
    amount_minor: int,
    sorted_rules: list[RewardRule],
    base_earn: EarnRate,
    pool_balances: dict[str, int],
) -> EarnResult:
    """Cap-aware earn over one line's post-discount amount.

    ``pool_balances`` holds *remaining* pool capacity keyed by ``pool_key``; pass
    an empty dict to evaluate as if every pool were full. This function does not
    mutate ``pool_balances`` — it returns the draws for the caller to commit.
    """
    remaining = amount_minor
    result = EarnResult(total_points=0)

    for rule in sorted_rules:
        if remaining <= 0:
            break
        per = rule.earn.per_amount_minor
        blocks = remaining // per
        if blocks == 0:
            continue  # cannot fill even one block at this rule's granularity
        uncapped_pts = blocks * rule.earn.points

        if rule.cap is None:
            result.total_points += uncapped_pts
            result.segments.append(
                EarnSegment(
                    source=rule.id,
                    description=_rule_desc(rule),
                    points=uncapped_pts,
                    amount_minor=remaining,
                )
            )
            remaining = 0
            break

        key = pool_key(rule)
        assert key is not None
        pool_left = pool_balances.get(key, rule.cap.max_points)

        if uncapped_pts <= pool_left:
            result.total_points += uncapped_pts
            result.pool_draws[key] = result.pool_draws.get(key, 0) + uncapped_pts
            result.segments.append(
                EarnSegment(
                    source=rule.id,
                    description=_rule_desc(rule),
                    points=uncapped_pts,
                    amount_minor=remaining,
                    pool_key=key,
                )
            )
            remaining = 0
            break

        # Cap binds: earn as many whole blocks as the remaining pool allows.
        blocks_by_pool = pool_left // rule.earn.points
        pts = blocks_by_pool * rule.earn.points
        consumed = blocks_by_pool * per
        result.total_points += pts
        if pts > 0:
            result.pool_draws[key] = result.pool_draws.get(key, 0) + pts
        result.segments.append(
            EarnSegment(
                source=rule.id,
                description=(
                    f"{_rule_desc(rule)}; cap pool '{key}' exhausted after "
                    f"{_rupees(consumed)}, remainder falls through"
                ),
                points=pts,
                amount_minor=consumed,
                pool_key=key,
            )
        )
        remaining -= consumed

    if remaining > 0:
        blocks = remaining // base_earn.per_amount_minor
        pts = blocks * base_earn.points
        result.total_points += pts
        result.segments.append(
            EarnSegment(
                source="base",
                description=(
                    f"Base earn {base_earn.points} pts per {_rupees(base_earn.per_amount_minor)}"
                ),
                points=pts,
                amount_minor=remaining,
            )
        )

    return result


def _rule_desc(rule: RewardRule) -> str:
    return (
        f"Matched rule {rule.id} ({rule.earn.points} pts per {_rupees(rule.earn.per_amount_minor)})"
    )


def _rupees(minor: int) -> str:
    # Display helper only (never used in money math): ₹ major with thousands sep.
    return f"₹{minor // 100:,}"
