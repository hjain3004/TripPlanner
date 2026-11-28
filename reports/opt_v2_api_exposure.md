# Milestone Report: Optimization Engine v2 API Exposure (`OPT-1` – `OPT-4`)

**Branch:** `codex/opt-v2-api-exposure`  
**Base:** `origin/main` (`7c8806f`)  
**Date:** 2026-11-27  

---

## 1. Working Now (Exposed API Capabilities)

All four merged Optimization Engine v2 modules are now callable over deterministic, LLM-free FastAPI routes and reflected in the synchronized OpenAPI contract and generated TypeScript SDK:

1. **OPT-1 — Zero-Bias Top-`m` Acquisition Retrieval:**
   - **Endpoint:** `POST /account/acquisition/trips/{trip_id}/revisions/{revision}` ([`backend/api/acquisition.py`](../backend/api/acquisition.py))
   - **Capability:** Accepts optional `top_m` (`1..50`), `home_country`, `closed_card_ids`, and `open_card_ids` on `AcquisitionAssessmentIn`, forwarding them to `compute_acquisition_assessment(...)` while leaving omitted calls 100% unchanged.
2. **OPT-2 — Multi-Currency Pooled Transfer Planning:**
   - **Endpoint:** `POST /opt/transfers/pooled` ([`backend/api/opt_v2.py`](../backend/api/opt_v2.py))
   - **Capability:** Accepts `AwardTarget`, `UserWallet` or `points_balances`, `baseline_valuations`, `cash_price_minor`, `on_date`, and optional `PoolingConfig` (`deadline_hours`, `max_transfers`, grouped caps, Sun–Zhang expiry discounts). Returns `TransferAdvice` preserving `"VERIFY (blocking):"` as checklist step 1.
3. **OPT-3 — Spend Milestones, $\Gamma$-Robustness & Shared-Cap Execution Order:**
   - **Endpoint:** `POST /opt/optimize-v2` ([`backend/api/opt_v2.py`](../backend/api/opt_v2.py))
   - **Capability:** Accepts `CostedTrip`, `UserWallet`, optional `OptimizationPrefs`, `milestones`, `gamma`, and provenance-backed `valuation_floors_micro`. Fails closed with HTTP `422` if `gamma > 0` without explicit downside floors (never invents floors). Returns normalized `OptimizeV2Response` with `execution_order`, optimal assignments, milestone attainment, and integer-scaled objective.
4. **OPT-4 — Always-On Explanations, XAIOR Audit & QUICKXPLAIN Diagnosis:**
   - **Endpoints:** `POST /opt/explain-audit` and `POST /opt/diagnose-infeasibility` ([`backend/api/opt_v2.py`](../backend/api/opt_v2.py))
   - **Capability:** `/opt/explain-audit` runs deterministic optimization alongside `build_plan_explain_and_audit(...)`, returning `{optimizer_result, explanation, audit_certificate}` with SHA-256 snapshot/trip/result hashes, cap/MCC/group-cap ledgers, RHS milestone deltas, Forel breakevens, transactor APR warning, and zero-affiliate-weight attestation. `/opt/diagnose-infeasibility` handles discriminated `kind: "transfer" | "milestone"` requests using CP-SAT QUICKXPLAIN (`num_search_workers=1`, `random_seed=1`) to return subset-minimal conflict cores and discrete relaxations.

---

## 2. Demonstrated Behavior & Execution Mode

- **Execution mode:** FastAPI `TestClient` against real routers, Pydantic validation, seeded/fixture `KnowledgeBase` instances, real OR-Tools CP-SAT `9.15.6755`, and offline SQLite/CSRF auth session fixtures for OPT-1 Case B (`evals/test_opt_v2_api.py`, `evals/test_acquisition_api.py`). Zero network calls and zero LLM inference.
- **Contract synchronization:** Exported deterministic `contract/openapi.json`, regenerated TypeScript client + types in `frontend/src/lib/api/generated/`, re-exported new client symbols in `frontend/src/lib/api/index.ts`, added typed MSW handlers in `frontend/src/mocks/handlers.ts`, and verified `scripts/check-contract-drift.sh`.

---

## 3. Unavailable / Deferred

- **Interactive UI pages** consuming `/opt/*` and rendering OPT-1 `top_m` controls are deferred to future frontend work; existing MSW fixtures preserve UI green state in this PR.
- **`agents/pipeline.py` (`/plan`) integration** remains untouched and frozen per scope boundaries.

---

## 4. Verification Summary

- `make seed && make gate` (clean tree on final commit): **PASSED** (`GATE PASSED`, `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`).
- `scripts/check-contract-drift.sh`: **PASSED** (`CONTRACT_DRIFT_OK`).
- Frontend `npx tsc --noEmit`, `npx vitest run`, and ESLint: **PASSED** (`0` errors).
- `mypy --strict` across all backend packages and `ruff check`: **PASSED** (legacy `core/ + api/` debt ceiling unraised; zero findings added).
