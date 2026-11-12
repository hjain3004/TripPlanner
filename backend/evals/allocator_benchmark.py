"""Allocator benchmark oracle and naive baseline (Stream F — F-core).

Measures the heuristic allocator in ``core/optimizer/allocate.py`` (regret-ordered
greedy commit followed by a pairwise improvement sweep) against:

1. **Naive independent-line baseline** (`naive_allocate`, `naive_optimize`):
   Selects the best `(card_id, channel, offer_subset)` choice for each line
   independently as if all cap pools and `uses_per_card` offer counters were full
   and unshared, then commits those chosen options sequentially in trip line order
   (`trip.lines`) against the true shared cap pools and `uses_per_card` limits. If a
   selected `uses_per_card` offer is already exhausted by an earlier line when
   applied in line order, that exhausted offer is dropped from the line's applied
   subset while keeping the naive card, channel, and any still-available chosen
   offers.

2. **Exhaustive oracle** (`exhaustive_oracle`):
   Enumerates the feasible search space of per-line `(card_id, channel, offer_subset)`
   decisions and sequential commit permutations for bounded small cases, using
   fresh isolated copies of cap-pool balances and `uses_per_card` counters along
   every explored branch, and calling the kernel's own `compute_option`, `_commit`,
   `obj_scalar`, `rank_key`, and `build_result` functions so arithmetic is
   identical.

Feasible search space and objective
-----------------------------------
- **Decision variables:** For each spend line `line_i` in `trip.lines`:
  - Either a wallet card `card_id in wallet.card_ids` (present in `kb`), a channel
    `channel in line_i.available_channels`, and a stacking-legal subset of instant-
    discount offers `subset in offer_subsets(eligible_offers(...))` (at most one offer
    per stacking class in `("coupon", "bank_offer", "card_linked")`);
  - Or the kernel's `_cash_only_option(line_i)` fallback when no valid card/channel
    options exist for that line.
- **Sequential resource coupling:** Because `earn_schedule` consumes discrete point
  blocks from shared `RewardCap` pools and `uses_per_card` limits gate offer
  availability across lines, the order in which lines draw from a shared capped pool
  can change total earned points when two rules with different earn rates or point
  valuations share a `shared_cap_group`. The oracle therefore explores line commit
  orderings when multiple lines touch constrained resources, while pruning orderings
  when no constrained resources are touched or when the line count is 1. Every
  explored step uses an isolated copy of `(pool_balances, uses_map)` and enforces
  `_offer_available` before committing.
- **Simplicity constraint:** When `prefs.objective == "simplicity"`, any feasible
  assignment across the trip may use at most 2 distinct wallet cards (`card_id !=
  "cash_only"`), matching spec 02 §9.9.
- **Objective ranking:** Maximizes total trip scalar objective
  `sum(obj_scalar(opt_i, prefs) for line_i in trip.lines)`:
  - `max_savings` and `simplicity`: `sum(benefit_minor)` where
    `benefit_minor = discount_minor + points_value_minor - forex_fee_minor`
    (equivalently minimizing `effective_cost_minor = gross_minor - sum(benefit_minor)`).
  - `min_cash_outlay`: `sum(discount_minor - forex_fee_minor)`, breaking ties by higher
    `sum(benefit_minor)`.
  - `min_forex`: `sum(-forex_fee_minor)`, breaking ties by higher `sum(benefit_minor)`.
  Remaining ties are broken deterministically by total applied offer count ascending,
  distinct non-cash card count ascending, and the per-line `rank_key` tuple in
  `trip.lines` order.
- **Explicit resource bounds:** Enumeration is bounded by `max_lines` (default 8)
  and `max_states` (default 250,000 leaf/node evaluations). If a case exceeds either
  bound before enumeration finishes, `exhaustive_oracle` stops and returns
  `status="not_proven"` (never claiming that the best-so-far assignment is a proven
  optimum).

Handoff seams for F-build (Luna)
--------------------------------
`generate_benchmark_cases` and `write_benchmark_report` are typed seams left for
Luna's F-build generator and report work.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from itertools import permutations
from pathlib import Path
from typing import Literal

import yaml

from core.db import KnowledgeBase
from core.models import (
    Channel,
    CostedTrip,
    Offer,
    OptimizationPrefs,
    OptimizerResult,
    SpendLineItem,
    UserWallet,
)
from core.optimizer.allocate import (
    AllocationResult,
    OnDateFn,
    Option,
    _cash_only_option,
    _commit,
    _line_options,
    _offer_available,
    _on_date_fn,
    _pool_sizes,
    allocate,
    compute_option,
    obj_scalar,
    rank_key,
)
from core.optimizer.offers import eligible_offers, offer_subsets
from core.optimizer.report import build_result
from core.optimizer.rules import matching_rules
from evals._harness import build_kb, golden_files

DEFAULT_MAX_ORACLE_LINES = 8
DEFAULT_MAX_ORACLE_STATES = 250_000

OracleStatus = Literal["proven_optimal", "not_proven"]


@dataclass(frozen=True)
class ChoiceTemplate:
    """A stateless per-line choice `(card_id, channel, offer_subset)` before live pool commit."""

    card_id: str
    channel: Channel
    offers: tuple[Offer, ...]
    is_cash_only: bool = False


@dataclass(frozen=True)
class TripObjectiveScore:
    """Exact trip-level objective score and deterministic tie-break key.

    Smaller `sort_key` is better, matching `core.optimizer.allocate.rank_key`.
    """

    primary_scalar: int
    total_benefit_minor: int
    effective_cost_minor: int
    total_offers_applied: int
    distinct_cards_used: int
    line_rank_keys: tuple[tuple[object, ...], ...]

    @property
    def objective_comparison_key(self) -> tuple[int, int]:
        """Primary objective + secondary total benefit (higher is better for both)."""
        return (self.primary_scalar, self.total_benefit_minor)

    @property
    def sort_key(self) -> tuple[object, ...]:
        """Full deterministic minimization key (smaller is better)."""
        return (
            -self.primary_scalar,
            -self.total_benefit_minor,
            self.total_offers_applied,
            self.line_rank_keys,
        )


@dataclass(frozen=True)
class OracleRunResult:
    """Outcome of running the bounded exhaustive oracle on one trip."""

    status: OracleStatus
    allocation: AllocationResult | None
    result: OptimizerResult | None
    score: TripObjectiveScore | None
    explored_states: int
    max_lines: int
    max_states: int
    stop_reason: str | None = None


@dataclass(frozen=True)
class BenchmarkCase:
    """One benchmark input case (golden or seeded synthetic case for F-build)."""

    name: str
    kb: KnowledgeBase
    trip: CostedTrip
    wallet: UserWallet
    prefs: OptimizationPrefs
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseComparison:
    """Comparison of naive baseline, kernel allocator, and exhaustive oracle on one case."""

    case_name: str
    line_count: int
    objective: str
    oracle_status: OracleStatus
    oracle_explored_states: int
    oracle_stop_reason: str | None
    naive_result: OptimizerResult
    allocator_result: OptimizerResult
    oracle_result: OptimizerResult | None
    naive_score: TripObjectiveScore
    allocator_score: TripObjectiveScore
    oracle_score: TripObjectiveScore | None
    allocator_matches_oracle_objective: bool | None
    allocator_gap_minor: int | None
    allocator_gap_bp: int | None
    allocator_gain_over_naive_minor: int
    allocator_gain_over_naive_bp: int


def score_allocation(
    trip: CostedTrip,
    alloc: AllocationResult,
    prefs: OptimizationPrefs,
) -> TripObjectiveScore:
    """Compute the trip-level objective score for a completed `AllocationResult`."""
    gross = sum(line.amount_minor for line in trip.lines)
    total_primary = sum(obj_scalar(alloc.chosen[line.id], prefs) for line in trip.lines)
    total_benefit = sum(alloc.chosen[line.id].benefit_minor for line in trip.lines)
    effective_cost = gross - total_benefit
    total_offers = sum(len(alloc.chosen[line.id].applied) for line in trip.lines)
    distinct_cards = len(
        {
            alloc.chosen[line.id].card_id
            for line in trip.lines
            if alloc.chosen[line.id].card_id != "cash_only"
        }
    )
    line_keys = tuple(rank_key(alloc.chosen[line.id], prefs) for line in trip.lines)
    return TripObjectiveScore(
        primary_scalar=total_primary,
        total_benefit_minor=total_benefit,
        effective_cost_minor=effective_cost,
        total_offers_applied=total_offers,
        distinct_cards_used=distinct_cards,
        line_rank_keys=line_keys,
    )


def _runner_ups_against_final_state(
    kb: KnowledgeBase,
    trip: CostedTrip,
    wallet: UserWallet,
    prefs: OptimizationPrefs,
    chosen: dict[str, Option],
    pool_balances: dict[str, int],
    uses_map: dict[tuple[str, str], int],
    on_date_fn: OnDateFn,
) -> dict[str, Option | None]:
    """Compute per-line runner-up options holding the other lines' commitments fixed."""
    runner_ups: dict[str, Option | None] = {}
    for line in trip.lines:
        picked = chosen[line.id]
        pb = dict(pool_balances)
        um = dict(uses_map)
        for key, pts in picked.pool_draws.items():
            pb[key] = pb.get(key, 0) + pts
        for offer_id, limit in picked.uses_offers:
            k = (picked.card_id, offer_id)
            um[k] = um.get(k, limit) + 1
        opts = sorted(
            _line_options(kb, line, wallet, pb, um, on_date_fn),
            key=lambda o: rank_key(o, prefs),
        )
        alt = [
            o
            for o in opts
            if (
                o.card_id != picked.card_id
                or o.channel != picked.channel
                or [a.offer_id for a in o.applied] != [a.offer_id for a in picked.applied]
            )
        ]
        runner_ups[line.id] = alt[0] if alt else None
    return runner_ups


# --------------------------------------------------------------------------- #
# 1. Naive independent-line baseline                                          #
# --------------------------------------------------------------------------- #


def naive_allocate(
    kb: KnowledgeBase,
    trip: CostedTrip,
    wallet: UserWallet,
    prefs: OptimizationPrefs | None = None,
) -> AllocationResult:
    """Naive independent-line baseline.

    1. Evaluates each line in `trip.lines` independently against full/unshared
       cap pools (`{}`) and unused offer counters (`{}`), picking the best option
       for that line on its own under `rank_key(opt, prefs)`.
    2. For `prefs.objective == "simplicity"`, if the independent picks use more
       than 2 distinct cards, restricts the wallet to the 2 cards that appear on
       the highest-benefit independent picks (ties broken lexicographically by
       card id) and re-picks each line independently on those 2 cards.
    3. Applies the resulting per-line choices sequentially in `trip.lines` order
       against live shared `pool_balances` and `uses_map` via `compute_option`
       and `_commit`. If an offer with `uses_per_card` was selected by multiple
       lines and is already exhausted when a later line commits, that exhausted
       offer is filtered out of the later line's subset while keeping the naive
       card and channel.
    """
    resolved = prefs or OptimizationPrefs()
    on_date_fn = _on_date_fn(trip)
    pool_sizes = _pool_sizes(kb, wallet)

    active_wallet = wallet
    if resolved.objective == "simplicity":
        initial_picks: dict[str, Option] = {}
        for line in trip.lines:
            full_opts = _line_options(kb, line, wallet, {}, {}, on_date_fn)
            initial_picks[line.id] = min(full_opts, key=lambda o: rank_key(o, resolved))
        used_cards = sorted(
            {opt.card_id for opt in initial_picks.values() if opt.card_id != "cash_only"}
        )
        if len(used_cards) > 2:
            card_totals = {
                cid: sum(
                    opt.benefit_minor
                    for opt in initial_picks.values()
                    if opt.card_id == cid
                )
                for cid in used_cards
            }
            top_two = sorted(used_cards, key=lambda cid: (-card_totals[cid], cid))[:2]
            active_wallet = UserWallet(
                card_ids=top_two,
                points_balances=wallet.points_balances,
            )

    # Step 1: independent per-line selection ignoring cross-line pool/offer coupling.
    independent_choices: dict[str, tuple[str, Channel, list[Offer]]] = {}
    for line in trip.lines:
        full_opts = _line_options(kb, line, active_wallet, {}, {}, on_date_fn)
        best_ind = min(full_opts, key=lambda o: rank_key(o, resolved))
        if best_ind.card_id == "cash_only":
            independent_choices[line.id] = ("cash_only", best_ind.channel, [])
        else:
            on_date = on_date_fn(best_ind.channel)
            elig_by_id = {
                o.id: o
                for o in eligible_offers(
                    kb, line, kb.card(best_ind.card_id), best_ind.channel, on_date
                )
            }
            chosen_subset = [
                elig_by_id[a.offer_id]
                for a in best_ind.applied
                if a.offer_id in elig_by_id
            ]
            independent_choices[line.id] = (
                best_ind.card_id,
                best_ind.channel,
                chosen_subset,
            )

    # Step 2: commit sequentially in trip.lines order against live cap/offer state.
    pool_balances = dict(pool_sizes)
    uses_map: dict[tuple[str, str], int] = {}
    chosen: dict[str, Option] = {}

    for line in trip.lines:
        card_id, channel, subset = independent_choices[line.id]
        if card_id == "cash_only":
            opt = _cash_only_option(line)
        else:
            on_date = on_date_fn(channel)
            avail_subset = [
                o for o in subset if _offer_available(o, card_id, uses_map)
            ]
            opt = compute_option(
                kb, line, card_id, channel, avail_subset, pool_balances, on_date
            )
        chosen[line.id] = opt
        _commit(opt, pool_balances, uses_map)

    runner_ups = _runner_ups_against_final_state(
        kb, trip, active_wallet, resolved, chosen, pool_balances, uses_map, on_date_fn
    )
    return AllocationResult(
        lines=list(trip.lines),
        chosen=chosen,
        runner_ups=runner_ups,
        pool_balances=pool_balances,
        pool_keys=sorted(pool_sizes),
    )


def naive_optimize(
    trip: CostedTrip,
    user: UserWallet,
    kb: KnowledgeBase,
    prefs: OptimizationPrefs | None = None,
) -> OptimizerResult:
    """Build a full `OptimizerResult` from `naive_allocate` using kernel `build_result`."""
    resolved = prefs or OptimizationPrefs()
    alloc = naive_allocate(kb, trip, user, resolved)
    return build_result(kb, trip, user, alloc, resolved)


# --------------------------------------------------------------------------- #
# 2. Exhaustive oracle for bounded small cases                                #
# --------------------------------------------------------------------------- #


def _line_choice_templates(
    kb: KnowledgeBase,
    line: SpendLineItem,
    wallet: UserWallet,
    on_date_fn: OnDateFn,
) -> list[ChoiceTemplate]:
    """All static `(card_id, channel, offer_subset)` templates for `line`."""
    templates: list[ChoiceTemplate] = []
    for card_id in wallet.card_ids:
        if not kb.has_card(card_id):
            continue
        card = kb.card(card_id)
        for channel in line.available_channels:
            on_date = on_date_fn(channel)
            elig = eligible_offers(kb, line, card, channel, on_date)
            for subset in offer_subsets(elig):
                templates.append(
                    ChoiceTemplate(
                        card_id=card_id,
                        channel=channel,
                        offers=tuple(subset),
                        is_cash_only=False,
                    )
                )
    if not templates:
        fallback = _cash_only_option(line)
        templates.append(
            ChoiceTemplate(
                card_id=fallback.card_id,
                channel=fallback.channel,
                offers=(),
                is_cash_only=True,
            )
        )
    return templates


def _has_order_sensitive_cap_pool(kb: KnowledgeBase, wallet: UserWallet) -> bool:
    """Return True if any wallet card has a capped reward rule.

    Whenever two or more lines match a capped reward rule, the order in which they
    draw from the cap pool can change total points earned — either because two rules
    share a `shared_cap_group`, because a line has a secondary fall-through rule on
    the same card, or because `rule.earn.per_amount_minor != card.base_earn.per_amount_minor`
    makes the per-line floor on post-cap remainder blocks depend on which line took
    the capped blocks.
    """
    for card_id in wallet.card_ids:
        if not kb.has_card(card_id):
            continue
        if any(r.cap is not None for r in kb.rules_for_card(card_id)):
            return True
    return False


def exhaustive_oracle(
    kb: KnowledgeBase,
    trip: CostedTrip,
    wallet: UserWallet,
    prefs: OptimizationPrefs | None = None,
    *,
    max_lines: int = DEFAULT_MAX_ORACLE_LINES,
    max_states: int = DEFAULT_MAX_ORACLE_STATES,
) -> OracleRunResult:
    """Exhaustively search feasible assignments for a bounded small trip.

    Every explored step evaluates `compute_option` against an isolated copy of
    `pool_balances` and `uses_map`, enforces `_offer_available` for `uses_per_card`
    offers, and enforces `distinct_cards <= 2` when `prefs.objective == "simplicity"`.

    In the outer branch-and-bound over per-line `(card_id, channel, offer_subset)`
    choices, whenever the chosen assignment has `>= 2` lines drawing from a capped
    pool on a card with multiple rules (`_has_order_sensitive_cap_pool`), all
    relative commit orderings of those cap-touching lines are evaluated.

    If `len(trip.lines) > max_lines` or the number of explored states exceeds
    `max_states`, immediately stops and returns `status="not_proven"` with
    `allocation=None` and `result=None`.
    """
    resolved = prefs or OptimizationPrefs()
    n_lines = len(trip.lines)
    if n_lines > max_lines:
        return OracleRunResult(
            status="not_proven",
            allocation=None,
            result=None,
            score=None,
            explored_states=0,
            max_lines=max_lines,
            max_states=max_states,
            stop_reason=(
                f"line count {n_lines} exceeds max_lines={max_lines}; "
                "exhaustive optimality not proven"
            ),
        )

    on_date_fn = _on_date_fn(trip)
    pool_sizes = _pool_sizes(kb, wallet)

    if n_lines == 0:
        empty_alloc = AllocationResult(
            lines=[],
            chosen={},
            runner_ups={},
            pool_balances=dict(pool_sizes),
            pool_keys=sorted(pool_sizes),
        )
        empty_res = build_result(kb, trip, wallet, empty_alloc, resolved)
        empty_score = score_allocation(trip, empty_alloc, resolved)
        return OracleRunResult(
            status="proven_optimal",
            allocation=empty_alloc,
            result=empty_res,
            score=empty_score,
            explored_states=1,
            max_lines=max_lines,
            max_states=max_states,
        )

    templates_by_line: dict[str, list[ChoiceTemplate]] = {
        line.id: _line_choice_templates(kb, line, wallet, on_date_fn)
        for line in trip.lines
    }
    order_sensitive_caps = _has_order_sensitive_cap_pool(kb, wallet)

    explored_states = 0
    limit_exceeded = False
    stop_reason: str | None = None

    best_score: TripObjectiveScore | None = None
    best_chosen: dict[str, Option] | None = None
    best_pools: dict[str, int] | None = None
    best_uses: dict[tuple[str, str], int] | None = None

    def _record_candidate(
        chosen_map: dict[str, Option],
        pb: dict[str, int],
        um: dict[tuple[str, str], int],
    ) -> None:
        nonlocal best_score, best_chosen, best_pools, best_uses
        candidate_alloc = AllocationResult(
            lines=list(trip.lines),
            chosen=dict(chosen_map),
            runner_ups={},
            pool_balances=dict(pb),
            pool_keys=sorted(pool_sizes),
        )
        cand_score = score_allocation(trip, candidate_alloc, resolved)
        if best_score is None or cand_score.sort_key < best_score.sort_key:
            best_score = cand_score
            best_chosen = dict(chosen_map)
            best_pools = dict(pb)
            best_uses = dict(um)

    def _line_matches_capped_rule(
        line: SpendLineItem, tmpl: ChoiceTemplate
    ) -> bool:
        if tmpl.is_cash_only:
            return False
        on_date = on_date_fn(tmpl.channel)
        card = kb.card(tmpl.card_id)
        return any(
            r.cap is not None
            for r in matching_rules(kb, line, card, tmpl.channel, on_date)
        )

    def _evaluate_cap_permutations(
        picked_templates: dict[str, ChoiceTemplate],
    ) -> None:
        """Re-evaluate non-default commit orderings for lines that match any capped rule."""
        nonlocal explored_states, limit_exceeded, stop_reason
        capped_lines = [
            line
            for line in trip.lines
            if _line_matches_capped_rule(line, picked_templates[line.id])
        ]
        if len(capped_lines) <= 1:
            return
        uncapped_lines = [
            line
            for line in trip.lines
            if not _line_matches_capped_rule(line, picked_templates[line.id])
        ]
        for perm in permutations(capped_lines):
            if list(perm) == capped_lines:
                continue  # default order already evaluated
            explored_states += 1
            if explored_states > max_states:
                limit_exceeded = True
                stop_reason = (
                    f"explored state count exceeded max_states={max_states}; "
                    "exhaustive optimality not proven"
                )
                return
            pb = dict(pool_sizes)
            um: dict[tuple[str, str], int] = {}
            chosen_perm: dict[str, Option] = {}
            for line in (*perm, *uncapped_lines):
                tmpl = picked_templates[line.id]
                if tmpl.is_cash_only:
                    opt = _cash_only_option(line)
                else:
                    on_date = on_date_fn(tmpl.channel)
                    opt = compute_option(
                        kb,
                        line,
                        tmpl.card_id,
                        tmpl.channel,
                        list(tmpl.offers),
                        pb,
                        on_date,
                    )
                chosen_perm[line.id] = opt
                _commit(opt, pb, um)
            _record_candidate(chosen_perm, pb, um)

    def _dfs(
        idx: int,
        pool_balances: dict[str, int],
        uses_map: dict[tuple[str, str], int],
        chosen: dict[str, Option],
        picked_templates: dict[str, ChoiceTemplate],
        distinct_cards: frozenset[str],
    ) -> None:
        nonlocal explored_states, limit_exceeded, stop_reason

        if limit_exceeded:
            return

        if idx == n_lines:
            explored_states += 1
            if explored_states > max_states:
                limit_exceeded = True
                stop_reason = (
                    f"explored state count exceeded max_states={max_states}; "
                    "exhaustive optimality not proven"
                )
                return
            _record_candidate(chosen, pool_balances, uses_map)
            if order_sensitive_caps and not limit_exceeded:
                _evaluate_cap_permutations(picked_templates)
            return

        line = trip.lines[idx]
        for tmpl in templates_by_line[line.id]:
            if limit_exceeded:
                return
            if tmpl.is_cash_only:
                next_cards = distinct_cards
                opt = _cash_only_option(line)
                next_pb = dict(pool_balances)
                next_um = dict(uses_map)
            else:
                next_cards = distinct_cards | {tmpl.card_id}
                if resolved.objective == "simplicity" and len(next_cards) > 2:
                    continue
                if not all(
                    _offer_available(o, tmpl.card_id, uses_map) for o in tmpl.offers
                ):
                    continue
                explored_states += 1
                if explored_states > max_states:
                    limit_exceeded = True
                    stop_reason = (
                        f"explored state count exceeded max_states={max_states}; "
                        "exhaustive optimality not proven"
                    )
                    return
                next_pb = dict(pool_balances)
                next_um = dict(uses_map)
                on_date = on_date_fn(tmpl.channel)
                opt = compute_option(
                    kb,
                    line,
                    tmpl.card_id,
                    tmpl.channel,
                    list(tmpl.offers),
                    next_pb,
                    on_date,
                )
                _commit(opt, next_pb, next_um)

            chosen[line.id] = opt
            picked_templates[line.id] = tmpl
            _dfs(idx + 1, next_pb, next_um, chosen, picked_templates, next_cards)
            del chosen[line.id]
            del picked_templates[line.id]

    _dfs(0, dict(pool_sizes), {}, {}, {}, frozenset())

    if limit_exceeded or best_chosen is None or best_pools is None or best_uses is None:
        return OracleRunResult(
            status="not_proven",
            allocation=None,
            result=None,
            score=None,
            explored_states=explored_states,
            max_lines=max_lines,
            max_states=max_states,
            stop_reason=stop_reason or "no feasible assignment found",
        )

    runner_ups = _runner_ups_against_final_state(
        kb, trip, wallet, resolved, best_chosen, best_pools, best_uses, on_date_fn
    )
    final_alloc = AllocationResult(
        lines=list(trip.lines),
        chosen=best_chosen,
        runner_ups=runner_ups,
        pool_balances=best_pools,
        pool_keys=sorted(pool_sizes),
    )
    final_result = build_result(kb, trip, wallet, final_alloc, resolved)
    assert best_score is not None
    return OracleRunResult(
        status="proven_optimal",
        allocation=final_alloc,
        result=final_result,
        score=best_score,
        explored_states=explored_states,
        max_lines=max_lines,
        max_states=max_states,
    )


# --------------------------------------------------------------------------- #
# 3. Case comparison & golden-case loading                                    #
# --------------------------------------------------------------------------- #


def _gap_bp(delta_minor: int, gross_minor: int) -> int:
    if gross_minor <= 0:
        return 0
    return (delta_minor * 10_000) // gross_minor


def compare_case(
    case: BenchmarkCase,
    *,
    max_lines: int = DEFAULT_MAX_ORACLE_LINES,
    max_states: int = DEFAULT_MAX_ORACLE_STATES,
) -> CaseComparison:
    """Run naive baseline, kernel allocator, and exhaustive oracle on `case`."""
    naive_alloc = naive_allocate(case.kb, case.trip, case.wallet, case.prefs)
    naive_res = build_result(case.kb, case.trip, case.wallet, naive_alloc, case.prefs)
    naive_sc = score_allocation(case.trip, naive_alloc, case.prefs)

    alloc_alloc = allocate(case.kb, case.trip, case.wallet, case.prefs)
    alloc_res = build_result(case.kb, case.trip, case.wallet, alloc_alloc, case.prefs)
    alloc_sc = score_allocation(case.trip, alloc_alloc, case.prefs)

    oracle_run = exhaustive_oracle(
        case.kb,
        case.trip,
        case.wallet,
        case.prefs,
        max_lines=max_lines,
        max_states=max_states,
    )

    gross = alloc_res.gross_minor
    gain_over_naive = alloc_sc.primary_scalar - naive_sc.primary_scalar
    gain_over_naive_bp = _gap_bp(gain_over_naive, gross)

    if oracle_run.status == "proven_optimal" and oracle_run.score is not None:
        oracle_sc = oracle_run.score
        matches = (
            alloc_sc.objective_comparison_key == oracle_sc.objective_comparison_key
        )
        gap_minor = oracle_sc.primary_scalar - alloc_sc.primary_scalar
        gap_bp = _gap_bp(gap_minor, gross)
    else:
        oracle_sc = None
        matches = None
        gap_minor = None
        gap_bp = None

    return CaseComparison(
        case_name=case.name,
        line_count=len(case.trip.lines),
        objective=case.prefs.objective,
        oracle_status=oracle_run.status,
        oracle_explored_states=oracle_run.explored_states,
        oracle_stop_reason=oracle_run.stop_reason,
        naive_result=naive_res,
        allocator_result=alloc_res,
        oracle_result=oracle_run.result,
        naive_score=naive_sc,
        allocator_score=alloc_sc,
        oracle_score=oracle_sc,
        allocator_matches_oracle_objective=matches,
        allocator_gap_minor=gap_minor,
        allocator_gap_bp=gap_bp,
        allocator_gain_over_naive_minor=gain_over_naive,
        allocator_gain_over_naive_bp=gain_over_naive_bp,
    )


def load_golden_benchmark_cases() -> list[BenchmarkCase]:
    """Load all existing optimizer golden YAML cases (`backend/evals/golden/*.yaml`)."""
    cases: list[BenchmarkCase] = []
    for path in golden_files():
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        kb = build_kb(spec["kb"])
        lines = [SpendLineItem.model_validate(line) for line in spec["lines"]]
        booking = spec.get("booking_date", "2026-07-24")
        trip_start = spec.get("trip_start_date", booking)
        trip = CostedTrip(
            id=spec["name"],
            booking_date=date.fromisoformat(str(booking)),
            trip_start_date=date.fromisoformat(str(trip_start)),
            lines=lines,
        )
        wallet = UserWallet(**spec["wallet"])
        prefs = OptimizationPrefs(**spec.get("prefs", {}))
        cases.append(
            BenchmarkCase(
                name=spec["name"],
                kb=kb,
                trip=trip,
                wallet=wallet,
                prefs=prefs,
                tags=("golden",),
            )
        )
    return cases


# --------------------------------------------------------------------------- #
# 4. Seams for F-build (Luna): seeded generator and report writer             #
# --------------------------------------------------------------------------- #


def generate_benchmark_cases(seed: int, count: int = 50) -> list[BenchmarkCase]:
    """Seam for F-build (Luna): seeded deterministic case generator."""
    raise NotImplementedError(
        "F-build seam: implement seeded deterministic case generator covering exhausted caps, "
        "shared cap pools, rounding boundaries, min_txn offers, uses_per_card limits, and "
        "negative forex."
    )


def write_benchmark_report(
    comparisons: Sequence[CaseComparison],
    output_path: Path,
    *,
    seed: int,
    elapsed_seconds: float,
) -> str:
    """Seam for F-build (Luna): write reports/allocator_benchmark.md from benchmark results."""
    raise NotImplementedError(
        "F-build seam: format and write reports/allocator_benchmark.md with match rate, "
        "gap in minor units/bp, gain over naive baseline, runtime, and smallest losing case."
    )


def _demo_cli(case_name: str | None) -> int:
    cases = load_golden_benchmark_cases()
    if case_name is not None:
        cases = [c for c in cases if c.name == case_name]
        if not cases:
            print(f"Unknown golden case: {case_name}", file=sys.stderr)
            return 2

    rows = []
    for case in cases:
        comp = compare_case(case)
        rows.append(
            {
                "case": comp.case_name,
                "lines": comp.line_count,
                "objective": comp.objective,
                "oracle_status": comp.oracle_status,
                "explored_states": comp.oracle_explored_states,
                "naive_primary_minor": comp.naive_score.primary_scalar,
                "allocator_primary_minor": comp.allocator_score.primary_scalar,
                "oracle_primary_minor": (
                    comp.oracle_score.primary_scalar if comp.oracle_score else None
                ),
                "naive_effective_cost_minor": comp.naive_result.effective_cost_minor,
                "allocator_effective_cost_minor": comp.allocator_result.effective_cost_minor,
                "oracle_effective_cost_minor": (
                    comp.oracle_result.effective_cost_minor if comp.oracle_result else None
                ),
                "allocator_matches_oracle": comp.allocator_matches_oracle_objective,
                "allocator_gap_minor": comp.allocator_gap_minor,
                "allocator_gain_over_naive_minor": comp.allocator_gain_over_naive_minor,
            }
        )
    print(json.dumps(rows, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals.allocator_benchmark",
        description="Run the allocator benchmark oracle and naive baseline on golden fixtures.",
    )
    parser.add_argument(
        "--case",
        default=None,
        help="Optional golden case name (e.g. regret_trap). Omit to run all goldens.",
    )
    args = parser.parse_args(argv)
    return _demo_cli(args.case)


if __name__ == "__main__":
    raise SystemExit(main())
