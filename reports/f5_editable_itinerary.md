# Milestone Report: F5 — Editable Itinerary, Instant Recompute, Attached Guidance

## Overview

Milestone F5 transforms TripPlanner from a one-shot generator into an interactive, editable travel planner. Users can move POIs within a day, move POIs across days, remove unwanted activities, and see the budget, card assignments, and travel schedules update instantly—all without invoking an LLM or incurring API latency/cost.

---

## 1. Measured Performance & Latency

| Operation | Latency | Network/Tokens | Determinism |
|---|---|---|---|
| Initial Generation (Live 70B) | ~8 minutes | ~10k tokens | Guided by LLM |
| Itinerary Edit & Recompute (`POST /plan/recompute`) | **~350 ms** | **0 tokens, 0 LLM calls** | 100% Deterministic Python |
| User-Triggered Prose Refresh (`POST /plan/refresh-prose`) | ~3-5 seconds | ~300 tokens (1 explainer call) | Groundedness Gate Enforced |

---

## 2. The No-LLM Recompute Proof

- **Architecture:** The recompute handler in `backend/agents/recompute.py` uses `apply_edit`, `retrieve_candidates`, `build_final_schedule`, `estimate_costed_trip`, `run_kernel`, and `_template_explainer`.
- **Headline Test:** `evals/test_recompute_endpoint.py::test_recompute_makes_no_llm_call` asserts execution completes with a raising LLM client monkeypatched.
- **Teeth Proof (Mutation Testing):** When an LLM call was temporarily injected into `recompute_itinerary`, `test_recompute_makes_no_llm_call` immediately failed with `AssertionError: recompute path must NEVER invoke an LLM!`. The test was confirmed to fail before removing the probe.

---

## 3. Supported Edit Operations & Semantics

Defined in `backend/core/trip_models.py` and implemented purely in `backend/core/itinerary/edits.py`:
1. `MoveItem(poi_id, from_day_index, to_day_index, position)`: Moves an activity within the same day or across different days at a specified slot.
2. `RemoveItem(poi_id, day_index)`: Removes an unwanted activity from a day.
3. `ReorderDay(day_index, poi_ids)`: Reorders the full sequence of activities within a day.

**Referential Integrity & Safety:**
- An edit referencing an unknown `poi_id` or out-of-bounds `day_index` raises `ValueError`.
- An edit moving an item to a day where the venue is closed surfaces a `ScheduleWarning` in the report's caveats rather than silently dropping or rejecting the edit.

---

## 4. Freshness as a Visible Property

- Model: `SectionFreshness` with `SectionState` (`fresh`, `stale`, `recomputed`) and `edit_count`.
- Behavior:
  - Initial generation: all sections are `fresh`, `edit_count = 0`.
  - Recompute: `budget`, `payment_strategy`, and `itinerary` are `recomputed`; `prose` and `critic_verdict` are `stale`; `edit_count` increments.
  - Prose Refresh: user clicks "Refresh explanation" to spend a single explainer call, restoring `prose` to `fresh`.
- UI: Stale prose displays a calm `TrustChip` reading "Written before your last edit" with the refresh button. Recomputed budget and itinerary display "Recomputed live".

---

## 5. Attached Payment Guidance on Itinerary Items

- Joined `LineAssignment`s to itinerary items matching `a.line.id === item.poi_id || a.line.id === 'poi:' + item.poi_id`.
- Rendered compact badge with the optimal card identifier (e.g. `hdfc-infinia`) directly on each itinerary activity card.

---

## 6. Everything Not Done (Out of Scope)

1. **Adding New POIs to a Day:** Requires candidate search and catalog picker UI (separate milestone to preserve discovery limits).
2. **Persistent Storage:** Recompute remains stateless in memory ahead of spec 17 accounts & persistence.
3. **Auto "Optimize Route" TSP Trigger:** Manual arrangement is source of truth; automatic route re-optimization is deferred to a distinct user-triggered feature.
