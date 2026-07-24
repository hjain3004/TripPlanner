# 07 — Transfer Graph & Pathfinder (Points Transfer Advisor)

**Scope statement.** This module answers: *"Given the points/miles the user already has, is there a smarter way to pay for a flight or hotel in this trip by transferring points — and exactly how?"* It is a deterministic graph-search calculator over curated data, in the same architectural class as the rewards optimizer (doc 02). The Kernel MVP does not search award availability. In the target prototype, a profile-eligible Award workflow may supply normalized `AwardQuote` evidence through 09/16; this module still performs the transfer math and never crawls providers. It **never executes transfers** (transfers are irreversible; executing them is permanently out of scope).

Cash-flight evidence is not award evidence. A Gondola cash `FlightQuote`, Travelpayouts price observation, Duffel sandbox offer, or Google Flights verification link cannot prove that an award seat exists. Until a profile-eligible award adapter is available, the student prototype uses recorded fixtures, curated award/transfer facts, and optional manual award input; every resulting redemption path remains `verify_required`.

Design consequences, frozen alongside doc 06 Tier F (see §9):
1. No new Kernel MVP LLM call sites. The kernel keeps exactly four (03 §1); the pathfinder is pure code, and its output is rendered by the existing explainer.
2. Every transfer plan ends with a mandatory **verify-before-transfer checkpoint** rendered in the booking checklist: the user must confirm live award availability on the airline's own site (or a tool like seats.aero) *before* initiating any transfer, because card→program transfers cannot be undone.
3. All facts (edges, bonuses, award charts) carry doc 01 provenance and staleness rules. Award-chart entries get `STALENESS_DAYS = 180`; transfer bonuses use their own `valid_to`.

---

## 1. Data model additions (extends doc 01)

```python
class LoyaltyProgram(BaseModel):
    id: str                            # "lionmiles"
    kind: Literal["airline", "hotel", "card_currency"]
    name: str
    alliance: str | None               # informational
    booking_url: str | None            # where the user checks availability & books
    provenance: Provenance

class TransferEdge(BaseModel):
    id: str
    from_id: str                       # card_id (its points currency) or program id
    to_id: str                         # LoyaltyProgram id
    ratio_from: int                    # e.g. 3
    ratio_to: int                      # e.g. 1  → "3:1" (3 source points → 1 dest mile)
    min_transfer: int                  # in source points
    increment: int                     # transfer must be a multiple of this (source points)
    transfer_time_hours_typical: int   # 0 = instant
    transfer_time_hours_max: int
    provenance: Provenance
    # NOTE: there is deliberately no "reversible" flag. All transfers are treated
    # as irreversible; a reversible edge does not exist in this schema by design.

class TransferBonus(BaseModel):
    id: str
    edge_id: str
    bonus_bp: int                      # 2000 = +20% destination miles
    valid_from: date; valid_to: date
    provenance: Provenance

class AwardChartEntry(BaseModel):
    id: str
    program_id: str
    origin: str; destination: str      # airport pair in MVP (zone tables are Phase 2)
    cabin: Literal["economy", "premium", "business", "first"]
    trip_type: Literal["one_way", "round_trip"]
    miles_cost: int                    # per person
    fees_minor: int; fees_currency: str  # per person, taxes/surcharges
    operating_airline_hint: str | None  # "own metal" vs partner, for the explanation
    availability_note: str | None      # e.g. "waitlist common in peak season" — rendered verbatim
    provenance: Provenance
```

`UserWallet` (03 §2) already carries `points_balances: dict[str, int]`; extend its key space to accept **program ids** as well as card ids, so a user can declare existing airline miles (e.g. `{"voyager-prime": 140000, "lionmiles": 5000}`).

KB facade additions: `programs()`, `edges_from(currency_ids)`, `bonuses_active(edge_ids, on_date)`, `award_entries(origin, dest, cabin, trip_type)`.

## 2. Interface

```python
def find_transfer_plans(target: AwardTarget, wallet: UserWallet, kb: KnowledgeBase,
                        baseline_valuations: dict[str, int],   # micro-major/pt per currency, from doc 01 §5
                        cash_price_minor: int,                 # the CostedTrip price for the same line
                        on_date: date) -> TransferAdvice: ...

class AwardTarget(BaseModel):
    origin: str; destination: str; cabin: str; trip_type: str; travelers: int

class TransferAdvice(BaseModel):
    plans: list[TransferPlan]          # feasible plans, best first
    infeasible: list[InfeasiblePlan]   # near-misses with shortfall explained
    recommendation: Recommendation     # REDEEM(plan_id) | PAY_CASH | NO_DATA, with reason
```

## 3. Algorithm (deterministic; graph is tiny — enumerate exhaustively)

```
1. CANDIDATE AWARDS: all AwardChartEntry matching the target (origin, dest, cabin,
   trip_type). No entries → recommendation = NO_DATA (report says transfer advice
   unavailable for this route; never guess a miles price).
2. For each candidate award A (program P, need = miles_cost × travelers):
   a. Credit existing balance: need_net = max(0, need − wallet.balances.get(P, 0)).
      If need_net == 0 → zero-transfer plan (still gets the verify checkpoint).
   b. PATHS: enumerate transfer paths from every currency the user holds to P,
      max 2 hops (card→P, or card→intermediate→P). Reject paths revisiting a node.
   c. For each path, compute effective ratio per hop with any active bonus:
      dest_units(src) = floor(src × ratio_to × (1 + bonus_bp/10⁴) / ratio_from)
      Then solve for the MINIMUM source amount S such that:
        S ≥ min_transfer, S ≡ 0 (mod increment), and chained dest_units ≥ need_net.
      (Closed form + round up to increment; verify by evaluating forward. For 2-hop,
      solve inner hop first, then outer hop to produce the inner requirement.)
   d. Feasibility: S ≤ wallet balance of the source currency (minus any points already
      committed by another selected plan — MVP: one award target per trip line, no
      cross-plan interaction; document as assumption).
   e. Compute per feasible plan:
      total_fees = fees_minor × travelers
      points_consumed = S (in source currency)
      value_per_point_micro = (cash_price_minor − total_fees) × 1_000_000 // points_consumed
      opportunity_cost = points_consumed × baseline_valuations[source] // 1_000_000
      effective_redemption_cost = total_fees + opportunity_cost
      savings_vs_cash = cash_price_minor − effective_redemption_cost
      transfer_time = Σ hop typical/max hours; leftover_miles = chained_dest − need_net
3. RANK plans: savings_vs_cash desc, then fewer hops, then faster transfer,
   then lexicographic plan id. Deterministic; no randomness.
4. RECOMMENDATION: top plan is recommended iff
   value_per_point_micro ≥ baseline_valuation × REDEEM_MARGIN (default 1.15 — a
   config constant, Tier C: transfers add irreversibility risk and effort, so
   redemption must beat the flexible baseline by a clear margin, not a hair)
   AND savings_vs_cash > 0. Otherwise PAY_CASH with the numeric reason.
5. DOMINANCE PRUNE: drop any plan strictly worse than another on (savings, hops,
   time) — but keep the best 2-hop plan in `plans` even if dominated, flagged
   `dominated: true`, so the explainer can say "going via {hotel program} would
   waste N points" (users ask; pre-compute the answer).
```

Rounding conventions (Tier F): destination-units floor per hop; source amount rounds **up** to increment; all money integer minor units; per-point values micro-major (01 §5).

## 4. Output structures

```python
class TransferStep(BaseModel):
    from_id: str; to_id: str
    amount_source: int; amount_dest: int
    bonus_applied: str | None          # bonus id; explanation includes valid_to
    transfer_time_hours_typical: int; transfer_time_hours_max: int

class TransferPlan(BaseModel):
    id: str
    award: AwardChartEntry; travelers: int
    steps: list[TransferStep]          # ordered
    points_consumed: int; source_currency: str
    existing_miles_used: int
    leftover_miles: int                # stranded in destination program — must be surfaced
    total_fees_minor: int
    value_per_point_micro: int
    effective_redemption_cost_minor: int
    savings_vs_cash_minor: int
    dominated: bool = False
    checklist_steps: list[str]         # deterministic template, §5
    provenance_flags: list[str]
    explanation: list[str]             # ordered atoms, same style as 02 §7

class InfeasiblePlan(BaseModel):
    award_id: str; best_path: list[str]
    shortfall_points: int; shortfall_currency: str
    note: str                          # "Need 225,000 voyager points via SkyOrchid; you have 140,000"
```

## 5. Checklist template (deterministic; explainer may polish wording only)

For every recommended plan, in this exact order:
1. **VERIFY (blocking):** "Confirm {cabin} award space for {travelers} on {origin}→{destination}, {dates}, at {program.booking_url}. Do NOT transfer until you can see the seats. Transfers are irreversible."
2. One step per TransferStep: "Transfer {amount_source} {from} → {amount_dest} {to} (typically {h}h, up to {max}h{, includes bonus B expiring {date}})."
3. "Book on {program} for {miles_cost}×{travelers} miles + {fees} fees."
4. "Leftover: {leftover_miles} miles will remain in {program}." (omit if 0)
5. Provenance footer: chart last verified {date}; bonus valid to {date}; award availability is never guaranteed by this tool.

If `transfer_time_hours_max > 0`, the checklist inserts a warning between 1 and 2: award space can disappear during a non-instant transfer; prefer instant paths when the value gap is small (the ranker already prefers them on ties — this warning covers non-ties, and the explainer must state the trade-off using the computed numbers).

## 6. Pipeline integration (amends 03 §1)

New node **4b — Transfer Pathfinder (code)**, after the optimizer, before the critic:
- Runs only when `wallet.points_balances` is non-empty. Otherwise the report contains a one-line note that transfer advice is available if the user shares balances.
- MVP targets: the flights line only (hotel awards are Phase 2 — add `AwardChartEntry.kind` then).
- `cash_price_minor` = the flights line's sticker price from CostedTrip; if the recommendation is REDEEM, the optimizer's payment strategy for that line is **replaced** by the transfer plan in the final report, and totals are recomputed by the report assembler (code, not LLM): the flights line contributes `effective_redemption_cost` instead of its cash math. Both variants are kept in the artifact so the explainer renders "vs. paying cash" from real numbers.
- Critic gains one check: transfer-plan claims in prose must match TransferAdvice fields (extends the existing groundedness gate regex to cover miles quantities, not just currency amounts).
- FinalReport gains `transfer_advice: TransferAdvice | None`.

Target-prototype amendment: the Award workflow may provide fresh/cached award evidence before this node, but it cannot change pathfinder rounding, valuation, ranking, or checklist semantics. `NO_DATA` remains valid when no profile-eligible adapter/evidence exists. Recorded/manual evidence may demonstrate the workflow but cannot be presented as live availability. Availability evidence and chart/transfer-rule provenance are distinct and both propagate to the report.

## 7. Worked example (canonical golden test: `evals/golden/transfer_demo.yaml`)

Fictional data, self-contained. **Programs:** `lionmiles` (airline), `skyorchid` (airline), `grandstay` (hotel). **Edges from `voyager-prime` points:** E1 → lionmiles 1:1, instant→24h max, min 1,000, inc 500. E2 → skyorchid 3:1, instant. E3 → grandstay 1:2 instant; E4 grandstay → lionmiles 3:1, 72h. **Bonus B1:** +20% on E2, valid on `on_date`. **Award chart:** lionmiles DEL→SIN business round-trip 62,000 miles + ₹9,000 fees pp; skyorchid same flight (partner) 45,000 miles + ₹12,000 fees pp. **Wallet:** 140,000 voyager points, 0 elsewhere. **Baseline valuation** (voyager, from 02 §8): ₹1.00/pt = 1,000,000 micro. **Cash price** (luxury CostedTrip, 2 pax business): ₹190,000. REDEEM_MARGIN 1.15.

Expected computation:
- **Plan P1 (E1 → lionmiles):** need 124,000 miles; 1:1 → 124,000 source; increment-ok; ≤ 140,000 ✓. Fees ₹18,000. value/pt = (190,000−18,000)×10⁶/124,000 = **1,387,096 micro (₹1.387/pt)**. Opportunity cost 124,000 → effective redemption cost **₹142,000**; savings vs cash **₹48,000**. Leftover 0. Transfer time typical 0h, max 24h.
- **SkyOrchid via E2+B1:** need 90,000 miles; effective 3 pts → 1.2 miles ⇒ minimum source = 225,000 → **infeasible**, shortfall 85,000 voyager points (goes to `infeasible` with that exact note).
- **P2 (E3+E4 two-hop to lionmiles):** 140,000 → 280,000 grandstay → 93,333 lionmiles < 124,000 → infeasible; recorded with shortfall in source terms; also flagged as the "don't do this" hotel-hop example (effective 1 pt → 0.667 miles).
- **Recommendation: REDEEM(P1)** — 1,387,096 ≥ 1.15 × 1,000,000 ✓ and savings positive. Checklist: verify on lionmiles first; transfer 124,000 (up to 24h warning applies); book 62,000×2 + ₹18,000; chart-verified date rendered.
- Report totals: flights line contributes ₹142,000 effective (fees ₹18,000 cash-now; opportunity ₹124,000 deferred-value terms), cash variant ₹190,000 retained in artifact for the "vs cash" sentence.

## 8. Edge cases (each is a required golden test)

1. Increment rounding: need_net implies 123,700 source, inc 500 → transfer 124,000; leftover computed from the rounded amount.
2. Existing destination balance reduces need (wallet has 5,000 lionmiles → transfer 119,000).
3. Bonus outside validity window → ignored; same input with date inside window → applied (two tests, same fixture, different `on_date`).
4. Zero-transfer plan (balance already covers award) → still emits VERIFY checkpoint and fees math.
5. `min_transfer` gate: tiny top-up below minimum forces transferring the minimum; leftover surfaced.
6. Margin gate: value/pt = ₹1.10 vs baseline ₹1.00 → PAY_CASH with reason string containing both numbers and the margin.
7. NO_DATA route (no chart entries) → recommendation NO_DATA; report renders "no transfer advice for this route", never an invented miles price.
8. Two-hop dominated plan retained with `dominated: true`.
9. Fees denominated in a non-home currency → converted via FxRate before comparison (reuse 02 §3 conversion).
10. Determinism: byte-identical output across two runs.

## 9. Protocol amendments (extends doc 06)

Add to **Tier F-K**: §3 rounding conventions; the four-LLM-call-site invariant covers the Kernel MVP pathfinder (it is code); the VERIFY-before-transfer checkpoint and its position as checklist step 1; never executing transfers; NO_DATA behavior (never estimate an award price). Add to **Tier C**: REDEEM_MARGIN value; checklist wording (structure fixed); `STALENESS_DAYS` for award charts. Milestone: implement as **M1b** (after Gate M1, before M2) — it depends only on `core/`; Gate M1b = golden tests for §7–§8 green + determinism + mypy clean, self-reviewed per 06 §5.

Seed data: real-world edges/charts for the India→Singapore corridor ship with `needs_verification: true`, like everything else — transfer ratios and award prices change without notice, and a wrong ratio here costs the user real, unrecoverable points. This module has the highest per-fact stakes in the product; curation discipline matters most here.
