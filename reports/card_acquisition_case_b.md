# Card Acquisition Assessment — Spec 18 Case B

**Milestone:** Spec 18 Case B (Card Acquisition Assessment & Conditional Welcome Offer Valuation)  
**Branch:** `codex/card-acquisition-case-b`  
**Base:** `origin/main` (clean isolated worktree at `.worktrees/card-acquisition-case-b`)  
**Status:** Complete, independently reviewed, full gates and contract checks passing.

---

## 1. Demonstrated Workflow: What a Traveler / Operator Can Do

A signed-in traveler who has saved a planned trip can request a deterministic, authenticated assessment of candidate unheld credit card welcome offers against their saved trip revision:

```http
POST /account/acquisition/trips/{trip_id}/revisions/{revision}
Content-Type: application/json
X-CSRF-Token: <token>
Cookie: tripwise_session=<session>

{
  "candidate_card_id": "axis-atlas",
  "payment_timing": {
    "booking_date": "2026-10-24",
    "first_bookable_spend_date": "2026-11-20"
  }
}
```

### Response Highlights
1. **Held-Card Strategy Untouched:** The held-card strategy (gross spend, discounts, rewards, forex fees, effective cost, net benefit) is computed solely from cards already in the user's wallet and returned in full alongside any candidate assessment.
2. **Qualifying Offer Suggestion:** When a candidate card offer satisfies all 5 gates from spec 18 §4, a conditional suggestion is returned with:
   - Verbatim informational framing: `"This card's current welcome bonus would be worth ₹22,256 on this trip if you held it"`. Never "you should apply".
   - Verbatim eligibility exclusions directly from the offer terms (e.g. new customer rules).
   - Deterministic integer breakdown of `net_first_year_minor`, `bonus_value_minor`, `trip_earn_delta_minor`, `annual_fee_minor`, and `trip_eligible_spend_minor`.
   - Complete timing assessment (`expected_lead_time_days`, `earliest_usable_date`, `first_bookable_spend_date`, `window_closes_on`).
3. **Fail-Closed Refusals:** If any gate fails, the suggestion is refused with typed codes and explanations:
   - `TIMING_GATE_FAILED`: Card expected in hand after first bookable spend date.
   - `PAYMENT_TIMING_UNKNOWN`: Explicit payment timing was omitted.
   - `MINIMUM_SPEND_NOT_MET`: Eligible trip spend allocated to the candidate is less than required minimum spend.
   - `SPEND_WINDOW_EXCEEDED`: Planned trip spend extends past the offer spend window close.
   - `NONPOSITIVE_NET_VALUE`: Fee exceeds bonus value + incremental trip rewards.
   - `OFFER_EXPIRED`: Planned booking date is past offer's `valid_to`.
   - `ALREADY_HELD_CARD`: The traveler already holds the card in their wallet.
   - `POINTS_PROGRAM_NOT_ESTABLISHED`: Offer bonus is points-denominated but lacks an established valuation link.
4. **Honest Default State:** With the shipped empty offer catalog (`[]`), the route honestly returns empty suggestions and an explicit `NO_APPROVED_OFFER` limitation.
5. **Ownership & Access Security:**
   - Stolen / foreign-owner trip requests are refused with HTTP 404 (`TRIP_NOT_FOUND`), byte-identical to nonexistent trip IDs.
   - Unknown revisions return HTTP 404 (`REVISION_NOT_FOUND`).
   - Unauthenticated requests return HTTP 401; missing CSRF returns HTTP 403.

---

## 2. Limitations & Boundaries Enforced

- **Shipped Catalog is Empty:** The committed welcome offer catalog contains no real financial facts (`[]`). Agent 2 prepares financial evidence under human review. The feature is proven end-to-end using clearly marked `SYNTHETIC_TEST_FIXTURE` offers.
- **No Money Math in LLMs:** All calculations are pure Python deterministic integer arithmetic (minor currency units).
- **No Parallel Reward Calculator:** The candidate incremental benefit is computed by invoking the existing `core.optimizer.optimize` with `UserWallet([*stored_cards, candidate_card])` and subtracting the held-wallet benefit.
- **Explicit Payment Timing Mandatory:** Travel dates are not payment dates. Omitting `payment_timing` refuses the suggestion immediately (`PAYMENT_TIMING_UNKNOWN`).
- **No Underwriting or Recommendation:** No inference of income, credit score, approval odds, or application guidance. Informational framing only.
- **No Cross-Program Valuation Guessing:** Unestablished points programs are withheld fail-closed with typed limitation `POINTS_PROGRAM_NOT_ESTABLISHED`.

---

## 3. Architecture & Ownership

- `backend/welcome/acquisition.py`: Core pure-functional assessment engine (`compute_acquisition_assessment`).
- `backend/welcome/models.py`: Pydantic models for request timing, suggestion details, timing evaluation, refusals, and summary.
- `backend/welcome/catalog.py`: Offer catalog retrieval with filtering and selection.
- `backend/welcome/status.py`: Enhanced `StoredPlan` extraction retaining full `costed_trip`, `optimizer_result`, `planned_wallet`, and `optimization_prefs`.
- `backend/api/acquisition.py`: Dedicated API module mounting `POST /account/acquisition/trips/{trip_id}/revisions/{revision}`.
- `backend/evals/demo_card_acquisition.py`: Runnable script demonstrating all five scenes in-process with real SQLite and real session cookies.
- Contract synchronization:
  - `contract/openapi.json` exported from FastAPI.
  - `frontend/src/lib/api/generated/` updated via `@hey-api/openapi-ts`.
  - `frontend/src/lib/api/index.ts` facade exports.
  - `frontend/src/mocks/handlers.ts` MSW handlers and error fixtures.
  - `frontend/tests/acquisition-assessment-mocks.test.ts` MSW test suite.

---

## 4. Independent Review

An independent review was performed focusing on four critical review criteria:
1. **Arithmetic Reuse:** Verified that `compute_acquisition_assessment` directly calls `core.optimizer.optimize` with `candidate_wallet` and differences against the existing `plan.optimizer_result`. No parallel rule engine or hardcoded reward rates exist. All values remain integer minor units.
2. **Timing & Lead Time Gate:** Verified that lead time is calculated as `expected_approval_days + expected_card_in_hand_days`, earliest usable date is `booking_date + lead_time`, and spend window closes at `earliest_usable_date + spend_window_days`. All 3 timing checks fail closed.
3. **Unknown Inputs Fail-Closed:** Verified that missing payment timing, missing open dates, missing valuation mappings, and empty catalogs never produce a speculative suggestion.
4. **Framing & Claim Safety:** Verified exact phrasing: `"This card's current welcome bonus would be worth {val} on this trip if you held it"`. Verified that eligibility exclusions are passed verbatim without modification.

---

## 5. Verification & Acceptance Record

- **Focused Unit & Property Tests:**
  - `evals/test_acquisition_core.py`: 12 passed.
  - `evals/test_acquisition_api.py`: 11 passed.
  - `evals/test_welcome_status_core.py` + `evals/test_welcome_api.py`: 41 passed (0 regressions).
- **Contract & Drift Checks:**
  - `./scripts/check-contract-drift.sh`: `CONTRACT_DRIFT_OK`.
  - `evals/test_contract_one_pr.py`: passed.
- **Frontend Checks:**
  - `npx tsc --noEmit`: 0 errors.
  - `npx vitest run`: 14 test files, 233 tests passed.
- **Ruff & Typecheck:**
  - `mypy --strict` across 247 source files: clean (0 errors).
  - Ruff zero-tolerance scope (`welcome/`, `evals/`, `accounts/`, `planning/`, `agents/`, `gateway/`, `ingestion/`): passed.
  - Ruff legacy debt ratchet (`core/` + `api/`): 8 findings (within ceiling 12).
- **In-Process Demonstration:**
  - `python -m evals.demo_card_acquisition`: all 5 scenes executed and verified.
