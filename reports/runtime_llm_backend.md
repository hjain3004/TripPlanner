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

## 3. Sol Review Corrections (R1–R8)

1. **R1 (Production runtime dependency):** Promoted `httpx>=0.28` to `[project] dependencies` in `backend/pyproject.toml` and regenerated `backend/requirements.lock` via `make lock` (`uv`). Verified with isolated runtime-only import probe that `agents.llm_factory` and `api.main` import cleanly without any development packages.
2. **R2 (Authenticated job identity binding):** Bound server-resolved authenticated owner (`user_id`) and durable job identity (`plan_id`) at execution boundaries (`start_confirmed_job`, saved-trip `_plan_inputs_from_saved_trip`, `POST /plan`, and `_run_job`). Verified that the durable ledger records `user_id` and `plan_id` for authenticated jobs, enforcing per-user and per-plan caps, while anonymous requests produce explicit typed refusal (`LLMSignInRequired`).
3. **R3 (Usage validation & uncertain settlement):** Added strict response usage validation in `AnthropicMessagesClient` (nonnegative integers for input/output tokens). Responses with missing or invalid usage call `ledger.mark_uncertain(reservation_id)` and raise typed `LLMInvalidResponse`, preserving full committed reservation in the ledger and never settling to zero.
4. **R4 (Mandatory no-overage attestation):** Enforced `TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED=1` at startup in `api/runtime_config.py` and client construction in `agents/llm_factory.py`. Documented as operator attestation in `backend/.env.example` and `deploy/.env.example`.
5. **R5 (Plan-wide call ceiling & deadline):** Added `PlanBudget` shared per plan bounding `TRIPWISE_LLM_MAX_CALLS` across all nodes and repair attempts. Re-verifies deadline after gate acquisition and immediately before dispatch; raises typed `LLMBudgetExceeded` on call ceiling.
6. **R6 (Non-plan roles share process-wide gate):** Routed `get_interview_llm()` and `get_post_plan_llm()` through `build_llm_client`, acquiring the shared `ThreadingDispatchGate` before dispatch.
7. **R7 (Provider error secret redaction):** Implemented `_redact_detail` in `AnthropicMessagesClient` scrubbing configured API keys, bearer tokens, and `sk-...` patterns from exception messages, logs, and durable breaker reasons.
8. **R8 (Truthful deployment preflight):** Added explicit `--offline`, `--mock`, and `--live` (requires `TRIPWISE_ANTHROPIC_LIVE_CHECK_CONFIRMED=1`) modes to `scripts/anthropic_preflight.py`. Zero-flag invocations run offline checks and exit with code 2 (incomplete), never claiming live compatibility when unverified. Labeled cached price row as unverified.

---

## 4. Verification & Gate Results

- **Unit & Component Suites:**
  - `backend/evals/test_llm_budget.py`: 21 passed.
  - `backend/evals/test_llm_wire.py`: 5 passed.
  - `backend/evals/test_claude_client.py`: 12 passed (added usage validation, call ceiling, error redaction regressions).
  - `backend/evals/test_llm_factory.py`: 5 passed (added shared gate on non-plan roles, typed refusal on missing identity/attestation).
  - `backend/evals/test_runtime_e2e.py`: 2 passed.
  - `backend/evals/test_runtime_authority.py`: 19 passed.
  - `backend/evals/test_d1_deployment_files.py`: 49 passed.
  - `backend/evals/test_a4_save_api.py`, `evals/test_a4_rerun.py`, `evals/test_cp2_api.py`: 53 passed.
- **Type Checking (`mypy --strict`):**
  - Clean across all 215 source files in `core/ accounts/ planning/ agents/ api/ gateway/ scripts/`.
  - Clean across all 41 source files in `ingestion/ welcome/`.
- **Linting (`ruff check`):**
  - Zero-tolerance scope (`accounts/ planning/ agents/ gateway/ evals/`): 0 findings.
  - Ratcheted debt scope (`core/ api/`): 7 findings (well below the 12-finding ceiling; 0 new findings introduced).
- **Preflight Script:**
  - `python backend/scripts/anthropic_preflight.py --mock`: passes all simulated preflight assertions (exit 0).
  - `python backend/scripts/anthropic_preflight.py`: exits 2 with explicit incomplete status notice.

---

## 5. Remaining Blockers & Handoff

- **Owner Action (P1–P7):** Real Claude API keys and paid deployment-day check (`anthropic_preflight.py --live` with `TRIPWISE_ANTHROPIC_LIVE_CHECK_CONFIRMED=1`) remain owner actions for deployment day after PR merge.
- **Stream A Finish (Luna):** Luna owns the frontend/wizard phase: `TripIntakeRequest.trip` wiring, MSW fixtures, and rendering the new typed `LLM_*` error states and critic caveats.
- **Review (Sol):** Independent branch code review by Sol before final merge.
