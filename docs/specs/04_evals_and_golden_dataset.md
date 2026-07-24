# 04 — Evals, Golden Dataset & Regression Gates

Philosophy (per AgentOps guidance): deterministic components get exact-match unit tests; LLM components get rubric-based LM-judge evals; every human-reported failure becomes a permanent test case. No prompt, rule-engine, or dataset change ships without a green run.

## 1. Optimizer golden tests (exact-match, Milestone 1)

Format — `evals/golden/*.yaml`, self-contained (embeds its own fictional cards/rules/offers so tests don't break when seed data is re-verified):

```yaml
name: demo_trip
kb:            # inline fixture: cards, reward_rules, offers, fx (01 schemas)
  cards: [...]
  reward_rules: [...]
  offers: [...]
wallet: { card_ids: [voyager-prime, globesaver] }
prefs: { objective: max_savings }
lines:         # SpendLineItems directly (bypass estimator)
  - { id: flights, category: flights, amount_minor: 5600000, currency: INR,
      available_channels: [direct_airline, ota_generic, bank_portal] }
  # ...
expect:
  assignments:
    flights:      { card: voyager-prime, channel: bank_portal, points: 4320, benefit_minor: 432000 }
    hotel:        { card: globesaver, channel: ota_generic, offers: [O1], discount_minor: 300000, benefit_minor: 322500 }
    attractions:  { card: voyager-prime, offers: [O2], benefit_minor: 77000 }
    dining:       { card: globesaver, points: 1000, forex_fee_minor: 23600, benefit_minor: 26400 }
    misc_forex:   { card: globesaver, points: 750, forex_fee_minor: 17700, benefit_minor: 19800 }
  totals: { gross: 15300000, discounts: 350000, rewards_value: 569000,
            forex_fees: 41300, effective_cost: 14422300, savings_pct_bp: 573 }
  pools_final: { "voyager-prime:portal": 0, "globesaver:R2": 750 }
```

`evals/test_optimizer.py` parametrizes over all golden files: build in-memory KB → `optimize()` → assert every `expect` field exactly. Required golden set (≥ 12 files): the demo trip above (from 02 §8) plus one per edge case in 02 §9 — cap fall-through, shared pool, regret-ordering trap (a case where raw-value greedy picks wrong), offer caps/min-txn, discount-reduces-points-base, negative-forex-benefit, uses_per_card, expired rule, no-matching-rules, simplicity objective, floor rounding, determinism (run twice, compare serialized bytes).

Property tests (hypothesis, optional but recommended): benefit never exceeds line amount; pools never negative; removing a card never increases total benefit; adding an offer never decreases it.

## 2. Pipeline contract tests (Milestone 2)

- Intake: ~15 fixture inputs (clean form, free text, ambiguous card mention, missing dates, mixed currency budget) → assert TripSpec fields / `unresolved` behavior. These run against a **recorded-response fake LLM** by default (fixtures under `evals/recorded/`); a `--live` flag re-records against the real provider.
- Planner referential integrity: every `poi_id` ∈ candidates; hotel_area ∈ areas — assert on 10 recorded runs.
- Explainer groundedness gate: the §6-doc-03 regex check as a test — no currency amount in prose absent from artifacts.
- End-to-end smoke: demo trip through `POST /plan` returns schema-valid FinalReport in < 60s.

## 3. LM-judge for itinerary quality (Milestone 3)

`evals/judge.py`: judge model (any capable hosted model, temperature 0) scores a DraftItinerary against TripSpec + POI rows on a 1–5 rubric, JSON output `{scores: {...}, rationale}`:

1. **Groundedness** — only supplied POIs/areas used; no invented facts. (Gate: must be 5; anything less is a bug, since the coordinator should have caught it.)
2. **Interest match** — items reflect stated interests/dietary.
3. **Geographic coherence** — days cluster by area; no ping-ponging.
4. **Pacing** — matches requested pace; realistic durations/hours.
5. **Budget respect** — style/budget consistent with picks.

Golden itinerary set: 8 TripSpecs spanning styles/paces/interest mixes (fixed seeds, recorded planner outputs re-generated on change). Gate: mean ≥ 4.0, no dimension < 3, groundedness = 5, across 3 judge runs (report variance). Judge rubric drift is checked by 3 hand-scored anchor itineraries (one good, one geographically scattered, one overpacked) — judge must rank them correctly or the judge prompt, not the planner, is fixed first.

## 4. Regression policy

- CI = ruff + mypy + §1 + §2 on every commit (fakes only, no network). §3 runs on demand pre-merge for prompt/planner changes (`--live`).
- Changing seed data: re-run §1 (should be unaffected — fixtures are inline; if affected, a test wrongly depends on seeds → fix the test).
- Every bug found manually or by users → minimal reproducing golden file added **in the same PR as the fix**.
- Track per-run: pass rate, judge means, p50/p95 latency, tokens per plan (from TraceEvents). A one-page `evals/report.md` is regenerated per run — this is the go/no-go artifact.
