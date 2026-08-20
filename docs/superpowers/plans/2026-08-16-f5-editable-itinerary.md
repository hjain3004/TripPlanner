# F5 — Editable Itinerary, Instant Recompute, Attached Guidance

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Steps use checkbox
> (`- [ ]`) syntax. Also required: `superpowers:test-driven-development`,
> `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.

**Goal:** Turn the product from a one-shot generator into something a person can actually use —
move an activity to another day, drop one they don't want, and see the money update instantly —
without waiting on an LLM.

**Why.** Today the app produces a plan and the plan is read-only. `grep -rln
"dnd|draggable|onDragEnd|reorder" frontend/src` returns nothing. Every planner we benchmarked
(Wanderlog, Stippl, Travefy) is an *editor*; ours is a *generator*. Wanderlog's most-praised paid
feature — "optimize route" — is only meaningful because the itinerary can be rearranged first.

Two mechanics observed on AwardFares are worth taking, and they solve a problem we measured:

1. **Show cached instantly, refresh per-cell on demand.** AwardFares renders cached availability
   immediately, then *"click the Search icon for each date you want to search."* Expensive work
   happens only where the user asks. Our full pipeline takes **~8 minutes**; nobody waits.
2. **Freshness is a visible property, not a footnote.** Their whole product distinguishes cached
   from real-time. We already have the primitive (`TrustChip`, `last_verified`,
   `needs_verification`) but apply it only to provenance, never to recency.

---

## The architectural insight — read this before designing

**An edit does not need the LLM.**

`CLAUDE.md` non-negotiable #1 already guarantees this: *"All reward/fee/discount/points arithmetic
is deterministic Python."* So when a user moves a POI to another day:

- re-validating hours and travel time is deterministic (`check_poi_hours`,
  `validate_day_travel_budget`)
- re-costing is deterministic (`estimate_costed_trip`)
- re-optimising cards/offers is deterministic (`run_kernel`)
- only the **prose** came from an LLM, and prose written for the old itinerary is simply *stale*

So the edit path is: **validate → recost → reoptimise → mark prose stale.** No intake, no planner,
no critic, no explainer. Sub-second instead of eight minutes, and it costs zero tokens.

That is also why mechanic (2) is mandatory rather than decorative: after an edit the numbers are
fresh and the prose is not, and the UI must say so rather than showing stale sentences beside new
figures. Honesty about staleness is the same discipline as provenance, applied to time.

**Do not** add an LLM call to the edit path. **Do not** re-run `compose_itinerary` on an edit —
that would discard the user's change. Validate what they gave you; do not overwrite it.

---

## Global Constraints

1. **The edit path makes zero LLM calls.** A test must prove it.
2. **Exactly four LLM call sites** remain (intake, planner, critic, explainer). Tier-F.
3. **LLMs never do money math.** Recompute is deterministic Python only.
4. **Money goldens are frozen.** `backend/evals/golden/` must not change.
5. **`backend/core/` imports nothing from `agents/`, `api/`, `gateway/`.**
6. **Contract changes ship in ONE commit** — schema + `contract/openapi.json` + regenerated client
   + MSW fixtures + UI (spec 12 §8, enforced by `CONTRACT_OK`).
   Note: `frontend/src/lib/api/schemas.ts` and `client-config.ts` are **hand-written**;
   `npm run gen:api` deletes them. Restore after regenerating.
7. **Keep the approved visual language.** Japan Quiet Blossom, neo-brutalist base, the four
   semantic registers, `TrustChip` for evidence state (DEVIATIONS 2026-08-09). Do **not** import a
   third-party Figma kit or invent a new component vocabulary.
8. **`make gate` and `make gate-f4`**, whole, pasted whole.

---

## Measured Baseline

| Metric | Value |
|---|---|
| `make gate` | PASSED, 493 tests |
| full pipeline latency (live, 70B) | **~8 minutes**, never observed completing in-browser |
| edit capability | none — zero drag/drop/reorder code |
| results layout | already dual-pane (`plan/page.tsx:577`, `lg:grid-cols-2`) |
| existing components | 27 under `components/product/`, incl. `itinerary-timeline`, `trip-map`, `trust-chip`, `payment-strategy-card` |
| POI spend-line id | `poi:{poi_id}` (`estimator.py:152`) — joins optimizer assignments to itinerary items |
| deterministic prose fallback | `_template_explainer` (`explainer.py:140`) |

---

# PART A — A deterministic recompute endpoint

## Task 1: Typed edit operations

- [ ] Add to `agents/models.py`: `ItineraryEdit` as a discriminated union —
      `MoveItem(poi_id, from_day_index, to_day_index, position)`,
      `RemoveItem(poi_id, day_index)`,
      `ReorderDay(day_index, poi_ids)`.
      `AddItem` is **out of scope** for this plan (it needs candidate search; see Out of Scope).
- [ ] Failing test first: applying `MoveItem` to a `DraftItinerary` produces the expected
      arrangement, and applying an edit that references an unknown `poi_id` raises rather than
      silently no-oping. **Referential integrity is Tier-F (I5):** an edit must never introduce a
      `poi_id` that did not come from the gateway.
- [ ] Implement `apply_edit(itinerary, edit) -> DraftItinerary` as a pure function in
      `core/itinerary/` — no I/O, no LLM, `core/` stays pure.
- [ ] `make gate`. Commit: `feat(core): typed itinerary edit operations`.

## Task 2: Stateless recompute

- [ ] Add `POST /plan/recompute` taking `{trip_spec, itinerary, edit}` and returning a
      `FinalReport`. **Stateless on purpose** — no job store, no persistence. Spec 17 (accounts)
      is not implemented, and inventing a plan store here would pre-empt it.
- [ ] The handler: `apply_edit` → re-validate (hours, travel budget) → `estimate_costed_trip` →
      `run_kernel` → `build_final_report` using `_template_explainer` prose, with the previous
      prose carried through and flagged stale (Task 3).
- [ ] **The headline test:** `test_recompute_makes_no_llm_call`. Pass an `LLMClient` whose every
      method raises, run a recompute, assert a normal `FinalReport` comes back. Verify the test has
      teeth by temporarily wiring an LLM call in and watching it fail.
- [ ] Test that a bad edit surfaces honestly: moving a POI into a day where it is closed must
      return the itinerary **with a warning**, not silently drop it or refuse the edit. Users are
      allowed to make infeasible plans; the product's job is to say so.
- [ ] Measure and report recompute latency. Target < 500ms. If it is not, say what it was.
- [ ] `make gate`. Commit: `feat(api): deterministic itinerary recompute without the LLM`.

---

# PART B — Freshness as a first-class property

## Task 3: Per-section staleness

- [ ] Add `SectionFreshness` to the contract: for each of `budget`, `payment_strategy`,
      `itinerary`, `prose`, `critic_verdict` — a state of `fresh` | `stale` | `recomputed`, plus
      the edit count since generation.
- [ ] After a recompute: budget/payment/itinerary are `recomputed`; prose and critic verdict are
      `stale`. Say it in the data; do not infer it in the UI.
- [ ] Failing test first: after one recompute, prose is `stale` and budget is `recomputed`.
      Anti-vacuity: assert the freshly generated report has everything `fresh`, so the test cannot
      pass by marking everything stale always.
- [ ] Contract + codegen + MSW + UI in ONE commit. `make gate` **and** `make gate-f4`.
      Commit: `feat(contract): per-section freshness after edits`.

## Task 4: Explicit, user-triggered prose refresh

This is AwardFares' per-date search icon, applied to our expensive operation.

- [ ] Add `POST /plan/refresh-prose` taking `{trip_spec, itinerary, kernel_result}` and running
      **only** the explainer call site. One LLM call, user-initiated, never automatic.
- [ ] The groundedness gate still applies unchanged — refreshed prose that disagrees with the
      computed artifacts still loses to `_template_explainer`. Tier-F.
- [ ] UI: a refresh affordance on the stale prose block, not a background job. The user chooses to
      spend the wait.
- [ ] `make gate`. Commit: `feat(api): explicit prose refresh as a single explainer call`.

---

# PART C — The frontend

## Task 5: Editable timeline

- [ ] Add drag-and-drop to `itinerary-timeline.tsx` — move items within a day and between days.
      Use a maintained library (`@dnd-kit/core` is the usual choice) rather than hand-rolling
      pointer maths. New dependency ⇒ `DEVIATIONS.md` entry.
- [ ] **Keyboard parity is required, not optional.** Every drag action needs a keyboard path, and
      `f3-results.spec.ts`'s aXe check must stay green. The I6 gate already demands the itinerary
      work without the map; the same standard applies here.
- [ ] Each edit calls `/plan/recompute` and re-renders. Optimistic UI is fine; a failed recompute
      must roll back visibly, not silently.
- [ ] Remove-item affordance on each card. No add-item (out of scope).
- [ ] `make gate-f4`. Commit: `feat(ui): drag to reorder and move itinerary items`.

## Task 6: Attach payment guidance to the item

Currently the results page stacks Itinerary, then Budget, then Payment strategy as separate
sections. The guidance for a restaurant sits ~400px below the restaurant.

- [ ] Join optimizer `LineAssignment`s to itinerary items on `poi:{poi_id}` (the id format already
      exists — no new computation, no new endpoint).
- [ ] Render the assigned card as a compact badge on the item card, reusing `TrustChip` /
      `payment-strategy-card` vocabulary. Keep the Budget section as the full ledger; the badge is
      a pointer, not a replacement.
- [ ] **Render fields, never compute.** No arithmetic in the browser — `CLAUDE.md` non-negotiable
      #1 applies to the frontend too. The badge shows a value the kernel produced.
- [ ] Failing test first: an item whose `poi_id` has an optimizer assignment shows the card badge;
      one without shows nothing. Anti-vacuity: assert the fixture contains both cases.
- [ ] `make gate-f4`. Commit: `feat(ui): show the optimal card on the itinerary item itself`.

## Task 7: Freshness in the UI

- [ ] Stale sections get a visible, calm marker using the existing evidence vocabulary — not a
      modal, not a toast. A `TrustChip` reading "written before your last edit" is enough.
- [ ] The prose refresh control lives on the stale block.
- [ ] Contrast and aXe must stay green (`tests/contrast.test.ts` pins the 11px chip at ≥4.5:1).
- [ ] `make gate-f4`. Commit: `feat(ui): surface per-section staleness after edits`.

---

## Task 8: Report

- [ ] `reports/f5_editable_itinerary.md`: recompute latency measured, the no-LLM proof, what edits
      are supported, what staleness states exist, and everything left undone.
- [ ] `DEVIATIONS.md` for each judgment call (new dependency, edit semantics, staleness policy).

---

## Explicitly out of scope

- **Adding new POIs to a day.** Needs candidate search and a picker; that is its own plan, and it
  reopens the I5 discovery budget. Move/remove/reorder first.
- **Persistence.** Recompute is stateless. Plans still vanish on reload. Spec 17 owns this.
- **Re-running the planner on edit.** The user's arrangement is the source of truth.
- **Auto "optimize route".** Tempting — the composer already does TSP — but it is a *different*
  feature from manual editing and would mask whether editing works. Separate plan.
- **Group travel / expense splitting / multi-currency normalisation.** All validated by Wanderlog
  reviews as real demand, all separate work.
- **Live award search, seat maps, alerts.** Needs the G-track providers. Do not build the UI for
  data that does not exist.

---

## Final Response Requirements

1. **Per-task status** — `done` / `partial` / `not started`.
2. **Full `make gate` and `make gate-f4`**, pasted whole.
3. **Recompute latency**, measured.
4. **The no-LLM proof** — and evidence the test fails when the isolation is removed.
5. **Every judgment call**, with its `DEVIATIONS.md` row.
6. **Everything not done**, and why.

Do not push. Do not open a PR. Report and stop.

---

## Self-Review Notes

- Does the edit path make **zero** LLM calls? Prove it by breaking the test on purpose.
- Did I re-run `compose_itinerary` on an edit and quietly overwrite the user's arrangement?
- Can every drag be done with a keyboard? Is aXe still green?
- Does any number get computed in the browser?
- Can an edit introduce a `poi_id` the gateway never returned? (Tier-F. It must not.)
- Is stale prose visibly marked, or is it sitting next to fresh numbers pretending to be current?
