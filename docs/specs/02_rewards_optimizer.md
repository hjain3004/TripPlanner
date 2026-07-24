# 02 — Deterministic Rewards Optimizer

Pure Python, zero LLM, zero I/O except reads through the `KnowledgeBase` facade. Input: a costed trip + user's cards. Output: card/channel/offer assignment per spend line, all money math, and a machine-readable explanation trace. This module is the product's credibility; it must be exhaustively unit-tested (see `04`).

```python
def optimize(trip: CostedTrip, user: UserWallet, kb: KnowledgeBase,
             prefs: OptimizationPrefs) -> OptimizerResult: ...
```

## 1. Definitions

- **Benefit** of paying line item L with card C via channel H (+ optional offers O):
  `benefit = instant_discounts + points_value − forex_fees − explicit_surcharges`
- **Points value** = points earned × the card's max `PointValuation` (report must state the assumed redemption path; if the user's `points_balances` make that path implausible — e.g. min redemption block unmet even after this trip — fall back to next path).
- **Effective trip cost** = Σ sticker prices − Σ instant discounts − Σ points value + Σ forex fees. Deferred value (points, `CASHBACK_LATER`) is reported both blended into effective cost **and** separated ("cash outlay now" vs "value returned later") — users distrust a single blended number.
- Annual fees are sunk for owned cards: excluded from optimization, mentioned once in the report if a card's fee renewal is near (out of MVP if renewal dates unknown).

## 2. Preferences (`OptimizationPrefs`)

`objective: Literal["max_savings", "min_cash_outlay", "min_forex", "simplicity"]`.
- `max_savings` (default): maximize Σ benefit.
- `min_cash_outlay`: count only instant discounts and forex fees; ignore points value in the objective (still report it).
- `min_forex`: lexicographic — minimize forex fees first, then max savings.
- `simplicity`: max savings subject to using ≤ 2 distinct cards (solve unrestricted; if >2 cards used, re-solve restricted to each 2-card subset of cards that appeared, pick best).

## 3. Spend normalization (`normalize.py`)

Convert `CostedTrip` (from the estimator, 03 §4) into `SpendLineItem`s:

```python
class SpendLineItem(BaseModel):
    id: str
    label: str                       # "Round-trip flights DEL→SIN ×2"
    category: SpendCategory
    amount_minor: int; currency: str # sticker price in billing terms (see below)
    available_channels: list[Channel]  # from SampleFlight/SampleHotel/POI.booking_channel
    merchant_hint: str | None
    splittable: bool = False         # MVP: False (one card per line item)
```

Currency handling: foreign-currency lines (POS_ABROAD) keep destination currency; benefit math converts to the user's home currency using `FxRate` (mid-market) and then applies the card's forex cost `markup_bp × (1 + tax_bp/10_000)` on the converted amount. **Do not** apply forex fees to INR-billed OTA purchases even for foreign services; DCC (paying in home currency abroad) is out of MVP scope — add a report tip: "always choose local currency at POS."

Aggregation: destination POS spend is aggregated into at most two lines (DINING, FOREX_GENERAL) — per-meal granularity is false precision. Flights, hotel, and each prepaid attractions basket (per merchant) are individual lines.

## 4. Rule matching (`rules.py`)

For a candidate `(line_item, card, channel)`, the applicable earn is decided by:

1. Collect card's `RewardRule`s where: `line.category ∈ rule.categories` AND `line.category ∉ rule.excluded_categories` AND (`rule.channels is None or channel ∈ rule.channels`) AND (`rule.currencies is None or line.currency ∈ rule.currencies`) AND rule is date-valid for the trip's booking date (use "today" for prepaid, trip start for POS lines).
2. Sort matching rules by marginal value per unit spend, descending. The **effective earn schedule** is: best rule until its cap pool is exhausted, then next rule, then `base_earn`. (Cap fall-through is mandatory; see §5.)
3. If no rule matches → `base_earn` (which has no cap in MVP).

Points per transaction: `floor(amount / earn.per_amount) * earn.points`, computed on the **post-instant-discount** amount.

## 5. Cap-aware allocation (`allocate.py`)

Caps couple line items: assigning the flights to a capped portal rule consumes pool capacity the hotel might have used. MVP algorithm — **regret-based greedy with one improvement sweep** (problem sizes: ≤ 12 lines, ≤ 12 cards, ≤ 4 channels/line):

```
1. Enumerate options: for each line L, every (card, channel, offer-set) combo → benefit(L, opt)
   computed as if all cap pools were full. Also compute benefit_uncapped_alt(L) =
   best option for L that touches NO capped pool.
2. regret(L) = best_capped_option(L) − benefit_uncapped_alt(L)
3. Process lines in descending regret. For each, evaluate its options against CURRENT
   pool balances (partial cap coverage = rule rate up to remaining pool, fall-through
   after), pick max benefit, commit, decrement pools (points drawn = min(pool, earned-under-rule)).
4. Improvement sweep: for every pair of committed lines, test swapping their pool
   consumption / options; accept any swap that strictly increases total benefit.
   Repeat until no swap improves (converges fast at this scale).
5. Deterministic tie-breaking everywhere: (higher benefit, fewer offers used,
   lexicographic card id). Same input ⇒ byte-identical output. No randomness.
```

This is not provably optimal in general, but with the improvement sweep it is exact on all realistic MVP instances; the golden tests in `04` pin expected outputs. Future work (documented, not built): exact MILP via OR-Tools if datasets grow.

Shared pools: `RewardCap.shared_cap_group` pools are keyed `(card_id, group)`; rules without a group get their own pool `(card_id, rule_id)`. Pool size = `max_points` (assume one statement cycle covers the booking window; refinement out of MVP, note the assumption in the report).

## 6. Offer application (`offers.py`)

Candidate offers for `(line, card, channel)`: `merchant matches merchant_hint` (case-insensitive; None matches nothing), `channel ∈ offer.channels`, `category ∈ offer.categories`, card/issuer/network matches, `valid_to ≥ booking date`, `min_txn` satisfied.

Stacking: per line item, at most **one offer per `stacking_class`** (so one `bank_offer` + one `coupon` may combine). Application order: `coupon` first, then `bank_offer`, each computed on the running (already-discounted) amount; `max_discount_minor` caps each. `INSTANT_DISCOUNT` reduces paid amount (and thus points base); `CASHBACK_LATER` and `BONUS_POINTS` do not reduce the points base and are valued in the deferred bucket. `uses_per_card` is enforced across the whole trip. `NO_COST_EMI` is never selected by the optimizer (report-only).

## 7. Output (`report.py`)

```python
class LineAssignment(BaseModel):
    line: SpendLineItem
    card_id: str; channel: Channel
    offers_applied: list[AppliedOffer]          # id, discount_minor
    points_earned: int
    points_value_minor: int; assumed_redemption: RedemptionPath
    forex_fee_minor: int
    benefit_minor: int
    explanation: list[str]      # ordered atoms: "Matched rule R1 (10 pts/₹100 portal flights)",
                                # "Cap pool 'portal' exhausted after ₹40,000; remainder at base 2 pts/₹100", ...
    provenance_flags: list[str] # e.g. "offer O1 needs_verification", "rule R1 last verified 2026-07-07"
    runner_up: RunnerUp | None  # second-best option + delta, for the report's "why not X?" section

class OptimizerResult(BaseModel):
    assignments: list[LineAssignment]
    gross_minor: int; discounts_minor: int; rewards_value_minor: int
    forex_fees_minor: int; effective_cost_minor: int
    cash_outlay_now_minor: int; deferred_value_minor: int
    savings_pct_bp: int
    cap_pools_final: dict[str, int]
    assumptions: list[str]
    confidence: float           # min over used facts' confidences
```

Every number in the final user-facing report must be traceable to a field here. The explainer LLM (03 §6) receives this object and may rephrase, never recompute.

## 8. Worked example (canonical test: `evals/golden/demo_trip.yaml`)

Fictional cards so the math is self-contained. **Cards:** `voyager-prime` (Visa): base 2 pts/₹100; rule **R1** 10 pts/₹100 on FLIGHTS+HOTELS via BANK_PORTAL, shared cap group `portal` max 4,000 pts/cycle; forex 350 bp + 18% tax → 4.13%; best valuation ₹1.00/pt (portal_flights). `globesaver` (Mastercard): base 1 pt/₹100; rule **R2** 5 pts/₹100 on DINING+FOREX_GENERAL, any channel, cap 2,500 pts/month; forex 100 bp + 18% → 1.18%; best valuation ₹0.50/pt (cashback). **Offers:** **O1** 10% instant off Agoda hotels, globesaver only, max ₹3,000, min ₹15,000 (bank_offer). **O2** 5% instant off Klook, any Visa, max ₹500 (bank_offer).

**Lines:** flights ₹56,000 (DIRECT_AIRLINE|OTA|BANK_PORTAL); hotel ₹48,000 (Agoda OTA|BANK_PORTAL|DIRECT); attractions ₹14,000 Klook; dining SGD≈₹20,000 POS_ABROAD; misc forex SGD≈₹15,000 POS_ABROAD. (FX pre-converted for clarity.)

**Expected optimal assignment and math:**

| Line | Card / channel / offer | Points | Pts value | Discount | Forex fee | Benefit |
|---|---|---|---|---|---|---|
| Flights 56,000 | voyager-prime, BANK_PORTAL | 4,000 (R1, pool hits cap at ₹40,000) + 320 base on remaining ₹16,000 = **4,320** | 4,320 | — | — | **+4,320** |
| Hotel 48,000 | globesaver, OTA + O1 | 450 (base on 45,000 post-discount) | 225 | 3,000 (10% capped) | — | **+3,225** |
| Attractions 14,000 | voyager-prime, Klook + O2 | 270 (base on 13,500) | 270 | 500 | — | **+770** |
| Dining 20,000 | globesaver, POS_ABROAD (R2) | 1,000 | 500 | — | 236 | **+264** |
| Misc forex 15,000 | globesaver, POS_ABROAD (R2, pool 1,750→1,000 left) | 750 | 375 | — | 177 | **+198** |

The allocation subtlety this test pins: the `portal` cap must go to **flights**, not the hotel — hotels have a strong uncapped alternative (O1 worth 3,225 ⇒ regret is low), flights don't (alternative ≈ ₹280 ⇒ regret is high). A naive "biggest line first through the portal" or "raw value" ordering can get this wrong depending on tie-breaks; regret ordering gets it right by construction.

**Totals:** gross **153,000**; discounts **3,500**; rewards value **5,690**; forex fees **413**; effective cost **144,223**; savings **8,777** (**5.74%**, `savings_pct_bp = 573` after floor). Cash outlay now = 153,000 − 3,500 + 413 = **149,913**; deferred value = **5,690**. Final pools: `portal: 0`, `(globesaver, R2): 750`.

`python -m core.optimizer demo` must reproduce this table exactly; it is also golden test #1.

## 9. Edge cases the implementation must handle (tests in 04)

1. Cap fall-through mid-line (flights above: one line spans capped + base rates).
2. Shared pool across two rules (portal flights + portal hotels drawing one pool).
3. Offer `max_discount` cap and `min_txn` gate.
4. Offer reduces points base; verify order coupon→bank_offer on running amount.
5. Negative-benefit forex line (a high-markup card must lose to a low-markup card even when its points rate is higher — voyager on dining: 400 pts=₹400 − ₹826 fee = −₹426 < globesaver's +₹264).
6. `uses_per_card` exhausted by an earlier line.
7. Rule expired relative to booking date → ignored, explanation notes it.
8. No cards own a matching rule → base earn everywhere, still produces a full report.
9. `simplicity` objective collapses to ≤2 cards with correct re-solve.
10. Points floor rounding: ₹14,999 at 5 pts/₹100 → floor(14,999/100) = 149 blocks × 5 = 745 pts (not 749.95 rounded). Pin per-transaction floor semantics.
11. Determinism: run twice, byte-identical JSON.
