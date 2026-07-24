"""Cap-aware allocation: regret-ordered greedy + pairwise improvement sweep (spec 02 §5).

Constrained resources that couple line items are cap pools *and* ``uses_per_card``
offers (the latter generalized in — see DEVIATIONS). Enumeration values each
option as if all resources were full; ``regret`` orders the lines; the greedy
commit re-evaluates against live pool/offer state; a pairwise sweep repairs any
residual sub-optimality. Deterministic tie-breaking throughout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from typing import Callable

from core.db import KnowledgeBase
from core.models import (
    AppliedOffer,
    Channel,
    CostedTrip,
    Offer,
    OptimizationPrefs,
    RedemptionPath,
    SpendLineItem,
    UserWallet,
)
from core.optimizer.money import forex_fee_minor, points_value_minor
from core.optimizer.offers import apply_offer_subset, eligible_offers, offer_subsets
from core.optimizer.rules import (
    POS_CHANNELS,
    EarnSegment,
    earn_schedule,
    expired_candidates,
    matching_rules,
    pool_key,
)

MAX_SWEEP_PASSES = 8


@dataclass
class Option:
    card_id: str
    channel: Channel
    applied: list[AppliedOffer]
    discount_minor: int
    post_amount_minor: int
    points: int
    points_value_minor: int
    assumed_redemption: RedemptionPath
    forex_fee_minor: int
    benefit_minor: int
    pool_draws: dict[str, int]
    uses_offers: list[tuple[str, int]]  # (offer_id, uses_per_card limit)
    segments: list[EarnSegment]
    expired_notes: list[str]
    provenance_flags: list[str]
    min_confidence: float

    @property
    def touches_constrained(self) -> bool:
        return bool(self.pool_draws) or bool(self.uses_offers)


@dataclass
class AllocationResult:
    lines: list[SpendLineItem]
    chosen: dict[str, Option]
    runner_ups: dict[str, Option | None]
    pool_balances: dict[str, int]
    pool_keys: list[str]


OnDateFn = Callable[[Channel], date]


def _on_date_fn(trip: CostedTrip) -> OnDateFn:
    def resolve(channel: Channel) -> date:
        return trip.trip_start_date if channel in POS_CHANNELS else trip.booking_date

    return resolve


# --------------------------------------------------------------------------- #
# Objective helpers                                                           #
# --------------------------------------------------------------------------- #


def obj_scalar(opt: Option, prefs: OptimizationPrefs) -> int:
    if prefs.objective == "min_cash_outlay":
        return opt.discount_minor - opt.forex_fee_minor
    if prefs.objective == "min_forex":
        return -opt.forex_fee_minor
    return opt.benefit_minor  # max_savings, simplicity


def rank_key(opt: Option, prefs: OptimizationPrefs) -> tuple[object, ...]:
    """Sort key where the smallest tuple is the best option (spec 02 §5 tie-breaks)."""
    if prefs.objective == "min_forex":
        primary: tuple[int, ...] = (opt.forex_fee_minor, -opt.benefit_minor)
    elif prefs.objective == "min_cash_outlay":
        primary = (-(opt.discount_minor - opt.forex_fee_minor), -opt.benefit_minor)
    else:  # max_savings, simplicity
        primary = (-opt.benefit_minor,)
    return (
        *primary,
        len(opt.applied),  # fewer offers first
        opt.card_id,  # lexicographic card id
        opt.channel.value,
        tuple(a.offer_id for a in opt.applied),
    )


# --------------------------------------------------------------------------- #
# Option construction                                                         #
# --------------------------------------------------------------------------- #


def _offer_available(offer: Offer, card_id: str, uses_map: dict[tuple[str, str], int]) -> bool:
    if offer.uses_per_card is None:
        return True
    remaining = uses_map.get((card_id, offer.id), offer.uses_per_card)
    return remaining > 0


def compute_option(
    kb: KnowledgeBase,
    line: SpendLineItem,
    card_id: str,
    channel: Channel,
    subset: list[Offer],
    pool_balances: dict[str, int],
    on_date: date,
) -> Option:
    card = kb.card(card_id)
    discount, applied = apply_offer_subset(line.amount_minor, subset)
    post = line.amount_minor - discount

    sorted_rules = matching_rules(kb, line, card, channel, on_date)
    earn = earn_schedule(post, sorted_rules, card.base_earn, pool_balances)

    val = kb.best_valuation(card_id)
    if val is None:
        value_micro, path = 0, RedemptionPath.CASHBACK
    else:
        value_micro, path = val
    pv = points_value_minor(earn.total_points, value_micro)

    fee = (
        forex_fee_minor(post, card.forex_markup_bp, card.forex_markup_tax_bp)
        if channel == Channel.POS_ABROAD
        else 0
    )
    benefit = discount + pv - fee

    expired = expired_candidates(kb, line, card, channel, on_date)
    notes = [f"Rule {r.id} ignored (expired {r.valid_to})" for r in expired if r.valid_to]

    contributing = {seg.source for seg in earn.segments}
    tagged: list[tuple[str, str, object]] = [("card", card.id, card.provenance)]
    for off in subset:
        tagged.append(("offer", off.id, off.provenance))
    for rule in sorted_rules:
        if rule.id in contributing:
            tagged.append(("rule", rule.id, rule.provenance))
    val_obj = kb.best_valuation_obj(card_id)
    if val_obj is not None:
        tagged.append(("valuation", val_obj.id, val_obj.provenance))
    prov_flags = [
        f"{kind} {ident} needs_verification"
        for kind, ident, prov in tagged
        if prov.needs_verification  # type: ignore[attr-defined]
    ]
    min_conf = min(prov.confidence for _, _, prov in tagged)  # type: ignore[attr-defined]

    return Option(
        card_id=card_id,
        channel=channel,
        applied=applied,
        discount_minor=discount,
        post_amount_minor=post,
        points=earn.total_points,
        points_value_minor=pv,
        assumed_redemption=path,
        forex_fee_minor=fee,
        benefit_minor=benefit,
        pool_draws=dict(earn.pool_draws),
        uses_offers=[(o.id, o.uses_per_card) for o in subset if o.uses_per_card is not None],
        segments=earn.segments,
        expired_notes=notes,
        provenance_flags=prov_flags,
        min_confidence=min_conf,
    )


def _line_options(
    kb: KnowledgeBase,
    line: SpendLineItem,
    wallet: UserWallet,
    pool_balances: dict[str, int],
    uses_map: dict[tuple[str, str], int],
    on_date_fn: OnDateFn,
) -> list[Option]:
    opts: list[Option] = []
    for card_id in wallet.card_ids:
        if not kb.has_card(card_id):
            continue
        for channel in line.available_channels:
            on_date = on_date_fn(channel)
            eligible = [
                o
                for o in eligible_offers(kb, line, kb.card(card_id), channel, on_date)
                if _offer_available(o, card_id, uses_map)
            ]
            for subset in offer_subsets(eligible):
                opts.append(
                    compute_option(kb, line, card_id, channel, subset, pool_balances, on_date)
                )
    return opts


# --------------------------------------------------------------------------- #
# Pool / offer state mutation                                                 #
# --------------------------------------------------------------------------- #


def _pool_sizes(kb: KnowledgeBase, wallet: UserWallet) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for card_id in wallet.card_ids:
        if not kb.has_card(card_id):
            continue
        for rule in kb.rules_for_card(card_id):
            if rule.cap is None:
                continue
            key = pool_key(rule)
            assert key is not None
            sizes[key] = min(sizes.get(key, rule.cap.max_points), rule.cap.max_points)
    return sizes


def _commit(opt: Option, pool_balances: dict[str, int], uses_map: dict[tuple[str, str], int]) -> None:
    for key, pts in opt.pool_draws.items():
        pool_balances[key] = pool_balances.get(key, 0) - pts
    for offer_id, limit in opt.uses_offers:
        k = (opt.card_id, offer_id)
        uses_map[k] = uses_map.get(k, limit) - 1


def _rollback(opt: Option, pool_balances: dict[str, int], uses_map: dict[tuple[str, str], int]) -> None:
    for key, pts in opt.pool_draws.items():
        pool_balances[key] = pool_balances.get(key, 0) + pts
    for offer_id, limit in opt.uses_offers:
        k = (opt.card_id, offer_id)
        uses_map[k] = uses_map.get(k, limit) + 1


# --------------------------------------------------------------------------- #
# Core allocation                                                             #
# --------------------------------------------------------------------------- #


def _allocate_core(
    kb: KnowledgeBase, trip: CostedTrip, wallet: UserWallet, prefs: OptimizationPrefs
) -> AllocationResult:
    on_date_fn = _on_date_fn(trip)
    pool_sizes = _pool_sizes(kb, wallet)

    # --- regret ordering (options valued as if all resources were full) ---
    regrets: dict[str, int] = {}
    for line in trip.lines:
        full_opts = _line_options(kb, line, wallet, {}, {}, on_date_fn)
        best_full = min(full_opts, key=lambda o: rank_key(o, prefs))
        unconstrained = [o for o in full_opts if not o.touches_constrained]
        best_unc = min(unconstrained, key=lambda o: rank_key(o, prefs)) if unconstrained else None
        scalar_full = obj_scalar(best_full, prefs)
        scalar_unc = obj_scalar(best_unc, prefs) if best_unc is not None else 0
        regrets[line.id] = scalar_full - scalar_unc

    ordered = sorted(trip.lines, key=lambda line: (-regrets[line.id], line.id))

    # --- greedy commit against live state ---
    pool_balances = dict(pool_sizes)
    uses_map: dict[tuple[str, str], int] = {}
    chosen: dict[str, Option] = {}
    runner_ups: dict[str, Option | None] = {}
    for line in ordered:
        opts = sorted(
            _line_options(kb, line, wallet, pool_balances, uses_map, on_date_fn),
            key=lambda o: rank_key(o, prefs),
        )
        best = opts[0]
        chosen[line.id] = best
        runner_ups[line.id] = opts[1] if len(opts) > 1 else None
        _commit(best, pool_balances, uses_map)

    # --- pairwise improvement sweep ---
    _improvement_sweep(kb, trip, wallet, prefs, on_date_fn, chosen, pool_balances, uses_map)

    return AllocationResult(
        lines=list(trip.lines),
        chosen=chosen,
        runner_ups=runner_ups,
        pool_balances=pool_balances,
        pool_keys=sorted(pool_sizes),
    )


def _improvement_sweep(
    kb: KnowledgeBase,
    trip: CostedTrip,
    wallet: UserWallet,
    prefs: OptimizationPrefs,
    on_date_fn: OnDateFn,
    chosen: dict[str, Option],
    pool_balances: dict[str, int],
    uses_map: dict[tuple[str, str], int],
) -> None:
    lines = sorted(trip.lines, key=lambda line: line.id)
    for _ in range(MAX_SWEEP_PASSES):
        improved = False
        for i in range(len(lines)):
            for j in range(i + 1, len(lines)):
                if _try_pair_swap(
                    kb, trip, wallet, prefs, on_date_fn, lines[i], lines[j],
                    chosen, pool_balances, uses_map,
                ):
                    improved = True
        if not improved:
            break


def _try_pair_swap(
    kb: KnowledgeBase,
    trip: CostedTrip,
    wallet: UserWallet,
    prefs: OptimizationPrefs,
    on_date_fn: OnDateFn,
    line_a: SpendLineItem,
    line_b: SpendLineItem,
    chosen: dict[str, Option],
    pool_balances: dict[str, int],
    uses_map: dict[tuple[str, str], int],
) -> bool:
    oa, ob = chosen[line_a.id], chosen[line_b.id]
    orig_total = obj_scalar(oa, prefs) + obj_scalar(ob, prefs)

    # release both lines' resource consumption
    _rollback(oa, pool_balances, uses_map)
    _rollback(ob, pool_balances, uses_map)

    best_total = orig_total
    best: tuple[Option, Option, dict[str, int], dict[tuple[str, str], int]] | None = None
    for first, second in ((line_a, line_b), (line_b, line_a)):
        pb = dict(pool_balances)
        um = dict(uses_map)
        opt_first = min(
            _line_options(kb, first, wallet, pb, um, on_date_fn),
            key=lambda o: rank_key(o, prefs),
        )
        _commit(opt_first, pb, um)
        opt_second = min(
            _line_options(kb, second, wallet, pb, um, on_date_fn),
            key=lambda o: rank_key(o, prefs),
        )
        _commit(opt_second, pb, um)
        total = obj_scalar(opt_first, prefs) + obj_scalar(opt_second, prefs)
        if total > best_total:  # strict improvement only → determinism preserved
            best_total = total
            if first.id == line_a.id:
                best = (opt_first, opt_second, pb, um)
            else:
                best = (opt_second, opt_first, pb, um)

    if best is not None:
        new_a, new_b, pb, um = best
        chosen[line_a.id] = new_a
        chosen[line_b.id] = new_b
        pool_balances.clear()
        pool_balances.update(pb)
        uses_map.clear()
        uses_map.update(um)
        return True

    # no improvement: restore original commitments
    _commit(oa, pool_balances, uses_map)
    _commit(ob, pool_balances, uses_map)
    return False


# --------------------------------------------------------------------------- #
# Objective dispatch (simplicity re-solve)                                    #
# --------------------------------------------------------------------------- #


def allocate(
    kb: KnowledgeBase, trip: CostedTrip, wallet: UserWallet, prefs: OptimizationPrefs
) -> AllocationResult:
    if prefs.objective != "simplicity":
        return _allocate_core(kb, trip, wallet, prefs)

    base_prefs = OptimizationPrefs(objective="max_savings")
    unrestricted = _allocate_core(kb, trip, wallet, base_prefs)
    used = sorted({opt.card_id for opt in unrestricted.chosen.values()})
    if len(used) <= 2:
        return unrestricted

    best_result = unrestricted
    best_total: int | None = None
    for subset in combinations(used, 2):  # sorted → lexicographic ties favour the first
        sub_wallet = UserWallet(card_ids=list(subset), points_balances=wallet.points_balances)
        r = _allocate_core(kb, trip, sub_wallet, base_prefs)
        total = sum(o.benefit_minor for o in r.chosen.values())
        if best_total is None or total > best_total:
            best_total = total
            best_result = r
    return best_result
