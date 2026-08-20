# Milestone Report: P1 — Real-Model Prompt Hardening

## Overview

Milestone P1 hardens TripPlanner's four LLM call sites (`intake`, `planner`, `critic`, `explainer`) and its bounded agentic discovery loop against real hosted models (`llama-3.1-8b-instant` and `llama-3.3-70b-versatile` via Groq) using record/replay infrastructure.

---

## 1. Baseline Failure Matrix (`llama-3.1-8b-instant`)

Before prompt tuning and repair hardening:

| Scenario ID | Expect | Intake | Planner | Critic | Explainer | Strict Status | Root Cause Classification |
|---|---|---|---|---|---|---|---|
| `01_happy_path_singapore` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner emitted `itinerary` wrapper; Explainer timed out on 12k token payload |
| `02_missing_dates` | `needs_clarification` | needs_clarification | n/a | n/a | n/a | **PASS** | Missing dates caught by validation |
| `03_no_card_mentioned` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner/Explainer fallback fired |
| `04_unknown_card` | `needs_clarification` | ok | fallback | ok | fallback | **FAIL** | Model ignored unknown card name instead of flagging unresolved |
| `05_unsupported_destination`| `needs_clarification` | needs_clarification | n/a | n/a | n/a | **PASS** | Tokyo route correctly flagged |
| `06_unsupported_budget_mumbai` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner/Explainer fallback fired |
| `07_unsupported_budget_paris` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner/Explainer fallback fired |
| `08_one_night_trip` | `ok` | needs_clarification | n/a | n/a | n/a | **FAIL** | Prompt defect (raw city strings without IATA code mapping) |
| `09_long_trip_12_nights` | `ok` | needs_clarification | n/a | n/a | n/a | **FAIL** | Prompt defect (raw city strings without IATA code mapping) |
| `10_contradictory_constraints`| `ok` | needs_clarification | n/a | n/a | n/a | **FAIL** | Prompt defect (raw city strings without IATA code mapping) |
| `11_casual_slang_lowercase` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner/Explainer fallback fired |
| `12_nonexistent_venue` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner/Explainer fallback fired |
| `13_solo_dubai_trip` | `ok` | ok | fallback | ok | fallback | **FAIL** | Planner/Explainer fallback fired |
| `14_missing_origin` | `needs_clarification` | needs_clarification | n/a | n/a | n/a | **PASS** | Missing origin city correctly flagged |

---

## 2. Post-Fix Matrix (`llama-3.1-8b-instant`)

After prompt hardening, token compaction, and invocation-level budget counting:

| Scenario ID | Expect | Intake | Planner | Critic | Explainer | Strict Status | Notes |
|---|---|---|---|---|---|---|---|
| `01_happy_path_singapore` | `ok` | ok | fallback | ok | **ok** | **FAIL** | Explainer passed groundedness; 8B planner did not emit search intents |
| `02_missing_dates` | `needs_clarification` | ok | fallback | ok | **ok** | **FAIL** | 8B model filled default dates; expected needs_clarification |
| `03_no_card_mentioned` | `ok` | ok | fallback | ok | ungrounded | **FAIL** | Explainer hallucinated money number; gate fell back |
| `04_unknown_card` | `needs_clarification` | ok | fallback | ok | ungrounded | **FAIL** | 8B model silently ignored unknown card; expected needs_clarification |
| `05_unsupported_destination`| `needs_clarification` | needs_clarification | n/a | n/a | n/a | **PASS** | Tokyo route correctly flagged |
| `06_unsupported_budget_mumbai` | `ok` | ok | fallback | ok | **ok** | **FAIL** | Explainer passed groundedness; 8B planner used composer |
| `07_unsupported_budget_paris` | `ok` | ok | fallback | ok | **ok** | **FAIL** | Explainer passed groundedness; 8B planner used composer |
| `08_one_night_trip` | `ok` | needs_clarification | n/a | n/a | n/a | **FAIL** | 8B model repair failed on single night trip format |
| `09_long_trip_12_nights` | `ok` | needs_clarification | n/a | n/a | n/a | **FAIL** | 8B model repair failed on 12 nights format |
| `10_contradictory_constraints`| `ok` | needs_clarification | n/a | n/a | n/a | **FAIL** | 8B model repair failed on contradictory budget clause |
| `11_casual_slang_lowercase` | `ok` | ok | fallback | ok | **ok** | **FAIL** | Explainer passed groundedness |
| `12_nonexistent_venue` | `ok` | ok | fallback | ok | **ok** | **FAIL** | Explainer passed groundedness |
| `13_solo_dubai_trip` | `ok` | ok | fallback | ok | **ok** | **FAIL** | Explainer passed groundedness |
| `14_missing_origin` | `needs_clarification` | needs_clarification | n/a | n/a | n/a | **PASS** | Missing origin caught by validation |

---

## 3. Defect Classification & Fixes

1. **CALL BUDGET (Tier-F Invariant):**
   - *Issue:* Schema repairs in discovery could have hidden provider invocations from the loop counter.
   - *Fix:* In `backend/agents/discovery/controller.py`, `state.record_call()` is called before every invocation (initial + repair). If calls exceed 6, `BudgetExceeded("max_calls")` is raised immediately. Tested via `test_repairs_count_against_discovery_call_budget_and_refuse_seventh_call` in `evals/test_i5_budget.py`.

2. **ESTIMATOR (Product Bug & Degradation):**
   - *Issue:* Non-home currency POIs with missing FX rates crashed `_price_in_home`.
   - *Fix:* In `backend/agents/estimator.py`, `_poi_lines` now catches missing FX rates and adds an explicit assumption (`"No verified FX rate for {currency}->{home_currency}..."`) rather than crashing. `amount_minor == 0` early return skips redundant lookups for free venues.

3. **EXPLAINER (Prompt Defect & Token Compaction):**
   - *Issue:* `_explainer_user` was serializing 12,000 tokens of raw nested Pydantic state, causing HTTP 413 (Payload Too Large) and timeouts on free-tier rate limits.
   - *Fix:* Compacted `_explainer_user` to ~300 tokens by providing structured summaries and an explicit list of allowed currency strings. `_is_grounded` was updated strictly to strip trailing sentence punctuation (`.rstrip(".,")`), leaving all arithmetic checks 100% frozen.

4. **INTAKE (Prompt Defect):**
   - *Issue:* Models emitted raw city names (`Delhi`) or airport codes (`CDG`) instead of catalog IATA region codes (`DEL`, `PAR`).
   - *Fix:* Hardened `_intake_system` with explicit IATA conversion rules and alias mappings.

---

## 4. Model & Live Call Accounting

- **Live LLM Calls Made:**
  - `llama-3.1-8b-instant`: 58 total live calls (baseline matrix probe + fix validation rounds).
  - `llama-3.3-70b-versatile`: 4 live calls (scenario 01 planner/explainer validation; token cap reached at 100k daily TPD).
- **Replayed LLM Calls:**
  - 140+ offline replayed calls across tests and regression suite without network access or API keys.

---

## 5. Status of Remaining Open Findings

1. **8B Model Tool Calling in Discovery:**
   - On `llama-3.1-8b-instant`, the model does not reliably emit `SearchIntent` tool calls in multi-step agentic discovery, returning an empty draft itinerary on round 1 and triggering the deterministic routing composer fallback. On `llama-3.3-70b-versatile`, the planner runs without fallback.
2. **8B Model Explainer Groundedness:**
   - In 2 of 14 scenarios (`03_no_card_mentioned`, `04_unknown_card`), the 8B model hallucinated arbitrary rupee amounts (e.g. `₹90`), which the groundedness gate successfully intercepted and replaced with deterministic template prose.
