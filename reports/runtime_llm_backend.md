# Runtime LLM Backend Implementation Report (A-build-1 Continuation)

**Branch:** `codex/runtime-llm-continuation`  
**Base commit:** `9ae8d8fc19ede80dad605951025367605ceffda1` (on top of `origin/codex/runtime-llm`)  
**Design Reference:** PR #39, `origin/codex/runtime-llm-design` @ `bda1d27cf5a1692917f60c8365c9659880a8eb30`, `docs/superpowers/specs/2026-11-11-runtime-llm-design.md`  
**Mode & Boundaries:** Mode A maintained. Four kernel call sites preserved. $0 out-of-pocket ceiling respected: zero live Claude API calls, zero paid spend, all tests run with mock transports.

---

## 1. Demonstrated Capability & What a Traveler/Operator Can Do

- **Operator Configuration & Validation:** An operator can configure Anthropic Claude (`TRIPWISE_LLM_PROVIDER=anthropic`) with positive integer spend caps (`TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD`, `TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD`, `TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD`, `TRIPWISE_LLM_CAP_LIFETIME_MICRO_USD`, `TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY`). The process performs strict startup validation (`python -m api.runtime_config`), ensuring credentials, caps, and price tables are consistent.
- **Offline Preflight Verification:** An operator can run `python backend/scripts/anthropic_preflight.py --mock` completely offline (zero network). It verifies runtime configuration, budget caps, schema complexity on all runtime models, token upper bounds, and budget-exceeded failure modes before deployment.
- **Fail-Safe Unconfigured Startup:** With no model provider configured in the environment, the stack starts up safely; plan jobs fail fast with typed `JobError.code = "LLM_NOT_CONFIGURED"` and message `"No model provider is configured; planning is unavailable."` without leaking secrets or echoing environment variable names.
- **Deterministic Spend Accounting:** The durable SQLite ledger (`TRIPWISE_DATA_DIR/llm_spend.sqlite3`) records reservations, settlements, releases, and uncertain states with integer micro-USD precision. Schema version 2 seamlessly migrates older version 1 databases, preserving all historical rows and adding shared `role` and `run_id` accounting alongside `plan_id`.
- **Process-Wide Dispatch Limiter:** A shared `ThreadingDispatchGate` bounds concurrent model dispatches across all roles (pipeline, interview, post-plan, and free tier) to `TRIPWISE_LLM_MAX_CONCURRENT_DISPATCH` (default 2).

---

## 2. Reconciled Design Decisions

1. **Lifetime Cap in SpendCaps & Durable Ledger:**
   - Added `lifetime_micro_usd` to `SpendCaps` and env mapping `TRIPWISE_LLM_CAP_LIFETIME_MICRO_USD`.
   - Bumped `SCHEMA_VERSION` to 2.
   - Enforced all-time committed spend cap (`committed("1=1") + amount <= lifetime_micro_usd`) in `LLMSpendLedger.reserve`.
   - Added migration from v1 to v2: preserves all historical rows, populating `run_id = plan_id` and `role = 'pipeline'`.

2. **Capacity Acquisition vs. Reservation Ordering:**
   - Resolved the contradiction between design §7.2 and §7.3.
   - Gate capacity (`self.gate.acquire`) is acquired **first**, followed by deadline re-verification.
   - Ledger reservation (`self.ledger.reserve`) is performed **immediately before HTTP dispatch**.
   - If gate acquisition times out or preflight checks fail, zero reservation is made.
   - On refusal or error, funds are released immediately; on timeout/drop after dispatch, marked uncertain. No unspent reservation is left behind.

3. **Shared Role & Run Accounting:**
   - Reservations track `role` (`pipeline`, `refresh-prose`, etc.) and `run_id` (supporting non-plan workflows like feed runs).
   - Added query methods: `run_committed_micro_usd`, `role_committed_micro_usd`, `lifetime_committed_micro_usd`.

4. **Wire Schema Flattening for Anthropic Structured Outputs:**
   - Measured finding from Sonnet: raw `DraftItinerary` has 22 `anyOf` branches (exceeding Anthropic's limit of 16) due to optional post-enrichment fields.
   - Flattened into `WireDraftItinerary` and `WirePlannerTurn` in `backend/agents/llm_wire.py`.
   - Verified that all 6 runtime models (`TripSpec`, `PlannerTurn`, `DraftItinerary`, `CriticVerdict`, `ExplainerOutput`, `SearchIntent`) have **zero wire problems**.
   - Client-side Pydantic validation round-trips raw output back to domain models seamlessly.

5. **REST Client Architecture vs. SDK:**
   - Used standard HTTP client (`httpx.Client`) targeting Anthropic Messages REST API (`POST /v1/messages`), avoiding adding unpinned `anthropic` SDK to `requirements.lock`.
   - Supports injected `httpx.MockTransport` for zero-spend unit and end-to-end testing.

---

## 3. Verification & Gate Results

- **Unit & Component Suites:**
  - `backend/evals/test_llm_budget.py`: 21 passed (includes lifetime cap, schema v1->v2 migration, role/run accounting).
  - `backend/evals/test_llm_wire.py`: 5 passed (wire problem checks, round-trips, validation).
  - `backend/evals/test_claude_client.py`: 9 passed (mock transport tests for all §8.1 outcomes, gate ordering, breakers).
  - `backend/evals/test_llm_factory.py`: 4 passed (kill switch, role gating, anonymous user handling, dispatch gate).
  - `backend/evals/test_runtime_e2e.py`: 2 passed (full pipeline run with mock client, unconfigured error mapping).
  - `backend/evals/test_runtime_authority.py`: 19 passed.
- **Type Checking (`mypy --strict`):**
  - Clean across all 213 source files in `core/ accounts/ planning/ agents/ api/ gateway/`.
  - Clean across all 36 source files in `ingestion/`.
  - Clean across all 5 source files in `welcome/`.
- **Linting (`ruff check`):**
  - Zero-tolerance scope (`accounts/ planning/ agents/ gateway/ evals/`): 0 findings.
  - Ratcheted debt scope (`core/ api/`): 7 findings (well below the 12-finding ceiling; 0 new findings introduced).
- **Preflight Script:**
  - `python backend/scripts/anthropic_preflight.py --mock`: passes all simulated preflight assertions.

---

## 4. Remaining Blockers & Handoff

- **Owner Action (P1–P7):** Real Claude API keys and paid deployment-day check (`anthropic_preflight.py` without mock) remain owner actions for deployment day after PR merge.
- **Stream A Finish (Luna):** Luna owns the frontend/wizard phase: `TripIntakeRequest.trip` wiring, MSW fixtures, and rendering the new typed `LLM_*` error states and critic caveats.
- **Review (Sol):** Independent branch code review by Sol before final merge.
