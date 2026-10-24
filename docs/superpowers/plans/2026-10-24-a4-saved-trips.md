# A4 — Saved-Trip API and Planning Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in traveler can save a finished plan, list their saved trips, reopen any stored result exactly as it was computed, re-run a trip to get fresh prices as a new revision, and delete a trip. Everything is owner-scoped, idempotent, concurrency-safe, and covered by privacy export and delete.

**Architecture:** Storage already exists (`SavedTrip`, `TripRevision`, `AccountStore.save_trip/add_revision/trips/revisions/latest_revision`) but has no API, no owner scoping on revision access, no idempotency, and no protection against two writers taking the same revision number. A4 hardens the store, then adds an authenticated `/account/trips` route family that (1) snapshots the current in-memory report of a confirmed planning session into a durable revision and (2) re-runs a saved trip through the **unchanged** confirmed-planning path, appending a revision server-side when the job completes. Stored reports are returned verbatim, never re-parsed through today's `FinalReport`.

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2 (SQLite), pytest + Hypothesis, mypy `--strict`, Ruff; OpenAPI → `@hey-api/openapi-ts` generated client; MSW.

**Base:** `origin/main` at `cef3a4d` (PR #15, which already contains A3 and D1). Branch `codex/a4-saved-trips`, worktree `/Users/himanshu_jain/.codex/worktrees/a4-saved-trips/TripPlanner`.

---

## Read first (cold start)

1. `CLAUDE.md` (== `AGENTS.md`) — non-negotiables, tiers, ambiguity protocol.
2. `docs/specs/17_accounts_and_persistence.md` §§ 1, 2, 5, 6 — **§ 5 is the contract for this milestone.**
3. `docs/specs/06_implementation_protocol.md` § 1 (tiers) and § 5 (gates).
4. `reports/a3_wallet_product_wiring.md` — the pattern A4 copies (owner scoping, idempotency ledger, error-ordering traps).
5. `backend/accounts/store.py` (saved-trip section, `export_user`, `delete_user`), `backend/accounts/db.py`, `backend/accounts/models.py` (`SavedTrip`, `TripRevision`).
6. `backend/api/conversation.py` — `confirm_session`, `session_job`, `_owned_job_report`, `recompute_confirmed_session`; `backend/api/confirmed_planning.py` — `start_confirmed_job`; `backend/api/job_manager.py`; `backend/api/wallet.py` (route and error pattern to mirror).

## Settled decisions — do not reopen

| # | Decision | Why |
|---|---|---|
| D1 | **Explicit save only.** No autosave of completed plans. | Saved trips are a travel history (spec 17 § 6); the user decides what is kept. |
| D2 | **Save source is a confirmed planning session** owned by the caller whose job report is still in process memory. If the report is gone (restart), return `409 PLAN_RESULT_UNAVAILABLE`; never reconstruct a report. | Jobs are process-local; a recomputed report would misstate what the user saw. |
| D3 | **The stored report is the session's *current* report**, including typed edits applied through `/sessions/{id}/recompute` and prose refreshes. | That is what the user is looking at when they press save. |
| D4 | **One session ↔ at most one saved trip.** Saving sets `PlanningSession.saved_trip_id` (CAS through the repository). Saving an already-attached session again returns `409 SESSION_ALREADY_SAVED` with the `trip_id`; later edits are appended through the revisions route. | Matches the existing `saved_trip_id` column and its expiry exemption. |
| D5 | **Re-run** recompiles the attached session's **latest confirmed brief** (`compile_confirmed_input`), uses the caller's **current** wallet projection and current reference data, and runs through the existing `_run_job` path. The revision records the exact `trip_spec` used. | Fresh prices are the point of a re-run; the pipeline graph and its four call sites are Tier F and must not change. |
| D6 | **The rerun revision is appended server-side on job completion** by a wrapper around `_run_job`, idempotent on the job id. A failed, clarification-needing, or lost (restart) run appends nothing. | The client may never poll; a half-written revision must be impossible. |
| D7 | **At most one in-flight rerun per trip** (`409 RERUN_IN_PROGRESS`). | Bounds LLM use and revision races without a global scheduler. |
| D8 | **Revisions are returned verbatim**: `report` is the stored JSON object, plus `schema_version`, `computed_at`, and `is_current_schema`. The server never re-validates it through the current `FinalReport`. | Spec 17 § 5: re-reading through a later model silently changes meaning. |
| D9 | **Wrong owner is indistinguishable from missing** (`404`) on every route. | Same rule as A3; prevents id probing. |
| D10 | **Deleting a trip hard-deletes** the trip, all its revisions, its idempotency events, and any planning session attached to it. No tombstone. Revisions themselves have no delete or update. | Spec 17 §§ 5–6. |
| D11 | **Limits:** 50 saved trips per user, 25 revisions per trip, 2 MiB per stored report. Typed `409 TRIP_LIMIT_REACHED`, `409 REVISION_LIMIT_REACHED`, `413 REPORT_TOO_LARGE`. | Bounds storage and export size; Tier C, logged. |
| D12 | **No UI in A4.** Contract, generated client, facade exports, and MSW fixtures ship (one-PR rule); saved-trip screens come later. | Keeps A4 a backend milestone while honouring the one-PR rule. |
| D13 | **Titles** default to `"{ORIGIN} → {DESTINATION} · {start_date}"`, built server-side; an optional caller title (1–80 characters, trimmed) overrides it. | Deterministic; no LLM involvement. |

## Global constraints

- **LLMs never do money math; neither does the frontend.** A4 stores and returns server-computed reports only.
- **Agents propose, humans approve.** Every A4 write is a direct authenticated user action, or the completion of a run the user started.
- **Every fact carries provenance.** Stored provenance and `last_verified` survive byte for byte.
- **Never** store PAN, expiry, CVV/CVC, PIN, banking or loyalty credentials. `extra="forbid"` and `FORBIDDEN_FIELD_NAMES` cover every new model.
- **No account identity in LLM prompts.** Re-runs use the existing path; prove with a recording client that no email, display name, or `last4` reaches the LLM.
- **`backend/core/` imports nothing from `accounts/`, `gateway/`, `ingestion/`, or `api/`.** AST-checked.
- **One-PR rule (spec 12 § 8):** models, routes, `contract/openapi.json`, generated client, facade, and MSW fixtures ship together.
- **Tier F untouchable:** pipeline graph and call sites, optimizer/transfer arithmetic, golden values, provenance columns. `docs/specs/` is read-only.
- **Behaviour changes and refactors are separate commits;** goldens green between them.
- **Ambiguity protocol:** do not stop and ask. Choose the most conservative option that changes no Tier-F behaviour and no golden value, log a `DEVIATIONS.md` row, continue.
- **Out of scope — do not start:** saved-trip UI, opening a saved revision into the editable workspace, sharing links, autosave, saving results from the legacy unauthenticated `/plan`, CP4, FI1+, spec 18, provider activation, the native Claude client, AWS or any deployment work. Do not touch another worktree.

---

## File structure

| Path | Change |
|---|---|
| `backend/accounts/db.py` | Unique index on `trip_revisions (trip_id, revision)`; new `TripMutationEventRow`; additive migration in `_migrate_existing_accounts_schema` |
| `backend/accounts/models.py` | `TripMutationEvent` model; limit constants; `UserExport` field |
| `backend/accounts/store.py` | Owner-scoped trip methods, `delete_trip`, idempotency, limits, typed errors; export and delete cover the new table |
| `backend/api/saved_trips.py` | **New** — router, request/response models, error mapping, save and rerun services |
| `backend/api/main.py` | Include the router (no other change) |
| `backend/evals/test_a4_*.py` | **New** test files (see tasks) |
| `contract/openapi.json`, `frontend/src/lib/api/generated/**`, `frontend/src/lib/api/index.ts`, `frontend/src/mocks/handlers.ts` (+ fixtures) | Contract synchronization |
| `DEVIATIONS.md`, `reports/a4_saved_trips.md` | Decisions and evidence |

---

## Setup

- [ ] **Step 0.1: Confirm the workspace**

```bash
cd /Users/himanshu_jain/.codex/worktrees/a4-saved-trips/TripPlanner
git rev-parse --abbrev-ref HEAD   # codex/a4-saved-trips
git log --oneline -2              # the plan commit on top of cef3a4d
```

- [ ] **Step 0.2: Environment, seed, catalogs**

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' 2>&1 | tail -3 && cd ..
make seed PY=.venv/bin/python     # bare `python` is not on PATH on this machine
cd frontend && npm ci && cd ..
```

The regional catalogs are gitignored. Copy them from an existing worktree instead of re-provisioning, then prove they stayed untracked:

```bash
cp -R /Users/himanshu_jain/.codex/worktrees/d1-deployment-foundation/TripPlanner/backend/catalogs backend/
git status --porcelain | grep -iE "catalog|overture" || echo "no catalog artifact tracked — correct"
```

- [ ] **Step 0.3: Capture the real baseline — never copy a number from a report**

```bash
make gate 2>&1 | tail -25          # record pytest counts, mypy file counts, ruff ratchet
cd frontend && npx tsc --noEmit; echo "tsc: $?"; npx vitest run 2>&1 | tail -3
```

---

### Task 1: Owner-scoped trip storage and safe revision numbering

**Files:** `backend/accounts/db.py`, `backend/accounts/store.py`, `backend/accounts/models.py`; test `backend/evals/test_a4_trip_scoping.py`.

The existing `add_revision(trip_id=…)`, `revisions(trip_id)`, and `latest_revision(trip_id)` resolve a trip by id alone — the same defect A3 found in the wallet mutators. There is also no unique constraint on `(trip_id, revision)`, so two concurrent appends can both compute `max + 1`.

- [ ] **1.1 Failing tests first:** a second user cannot read revisions of, append to, or delete the first user's trip, and each failure is the same typed "not found" as a missing id; `trips(user_id)` never returns another user's rows; two genuinely concurrent `add_revision` calls on separate connections produce revisions 1 and 2, never 1 and 1 (two threads, two `AccountStore.open` instances, as in `test_a3_wallet_concurrency.py`).
- [ ] **1.2 Require `user_id`:** `get_trip(user_id, trip_id)`, `revisions(user_id, trip_id)`, `latest_revision(user_id, trip_id)`, `add_revision(user_id=…, trip_id=…, …)`, and a new `delete_trip(user_id, trip_id) -> bool`. Every query constrains `SavedTripRow.user_id`. Update every caller, including `export_user`; `git grep -n "revisions(\|add_revision(\|latest_revision(" backend` must show no unscoped use.
- [ ] **1.3 Revision numbering:** add a unique index on `(trip_id, revision)` through `_migrate_existing_accounts_schema` (additive, `CREATE UNIQUE INDEX IF NOT EXISTS`). Read `max` and insert inside one `BEGIN IMMEDIATE` transaction; if an `IntegrityError` still occurs, retry once, then raise a typed `TripRevisionConflictError`. No raw `sqlite3` or SQLAlchemy exception may escape the store.
- [ ] **1.4 Migration safety test:** a database created with the pre-A4 schema, holding one trip and one revision, upgrades without rewriting rows, and the old revision reads back byte-identical.
- [ ] **1.5 Commit** `fix(accounts): owner-scope saved-trip access and serialize revision numbers`.

### Task 2: Durable idempotency and limits

**Files:** `backend/accounts/db.py`, `backend/accounts/models.py`, `backend/accounts/store.py`; test `backend/evals/test_a4_trip_idempotency.py`.

Mirror A3's `WalletMutationEventRow`: `TripMutationEventRow` with composite primary key `(user_id, client_event_id)`, `operation` (`save`, `append_revision`, `delete`, `rerun_complete`), `trip_id`, a request fingerprint, and the original result payload.

- [ ] **2.1 Failing tests:** replaying the same `client_event_id` with the same request returns the original result and writes nothing; reusing it with a different request raises a typed conflict (`409 IDEMPOTENCY_KEY_REUSED`); two concurrent identical submissions apply once; two users may reuse the same textual id.
- [ ] **2.2 Ordering trap (from A3):** the replay check runs **before** existence and limit checks, so a retried save that already succeeded is not rejected by the limit it consumed.
- [ ] **2.3 Limits (D11):** enforce trip count, revision count, and report size inside the store transaction, with typed errors.
- [ ] **2.4 Rerun completion key:** `rerun_complete` events use `client_event_id = "rerun:" + job_id`, so a completion callback that fires twice appends once.
- [ ] **2.5 Commit** `feat(accounts): idempotent saved-trip mutations with storage limits`.

### Task 3: Privacy export and delete

**Files:** `backend/accounts/store.py`, `backend/accounts/models.py` (`UserExport`); test `backend/evals/test_a4_trip_privacy.py`.

- [ ] **3.1** `export_user` includes trips, every revision (verbatim `report_json`), and trip mutation events, deterministically ordered and scoped to one user.
- [ ] **3.2** `delete_user` deletes `TripMutationEventRow` rows. It enumerates tables explicitly, so a new table silently survives erasure unless added.
- [ ] **3.3** `delete_trip` hard-deletes the trip, its revisions, its mutation events, and planning sessions whose `saved_trip_id` is that trip (D10). Deleted data does not survive a SQLite reopen.
- [ ] **3.4 Commit** `feat(accounts): saved trips in privacy export and erasure`.

### Task 4: Save from a confirmed session

**Files:** `backend/api/saved_trips.py` (new), `backend/api/main.py`; test `backend/evals/test_a4_save_api.py`.

- [ ] **4.1 Failing tests** with the scripted LLM client: confirm a session, wait for the job, save → `201` with revision 1 whose `report` equals the job's current report JSON; saving after a typed recompute edit stores the edited report (D3); saving a session that is unconfirmed, unfinished, or whose job state is gone returns the typed `409`; saving twice returns `409 SESSION_ALREADY_SAVED` (D4); another user's session id returns `404`.
- [ ] **4.2 Implement** `POST /account/trips` with body `{session_id, title?, client_event_id}`. Read the report through the same ownership check as `_owned_job_report` (owner, session, and job must all match). Build the `SavedTrip` from `report.trip_spec` (origin, destination, dates) and the compiled confirmed input's `raw_request`; store `report.model_dump_json()`; set `saved_trip_id` on the session through an optimistic-concurrency save. If that save loses a race, roll back the trip or return the existing one through the replay path — never two trips for one session.
- [ ] **4.3 Implement** `POST /account/trips/{trip_id}/revisions` with body `{session_id, client_event_id}`: append the attached session's current report. The session must be the one attached to that trip (`409 SESSION_NOT_ATTACHED` otherwise).
- [ ] **4.4** Every mutating handler starts with `require_csrf(request)` and `current_user`, and never reads a user id from the body.
- [ ] **4.5 Commit** `feat(api): save confirmed plans as immutable trip revisions`.

### Task 5: Read routes

**Files:** `backend/api/saved_trips.py`; test `backend/evals/test_a4_read_api.py`.

- [ ] **5.1** `GET /account/trips` → summaries, newest first: `id, title, origin_city, destination_city, start_date, end_date, created_at, revision_count, latest_revision, latest_computed_at`. No report bodies.
- [ ] **5.2** `GET /account/trips/{trip_id}` → the trip plus revision summaries (`revision, computed_at, trace_id, schema_version, is_current_schema`).
- [ ] **5.3** `GET /account/trips/{trip_id}/revisions/{revision}` → `{revision, computed_at, schema_version, is_current_schema, report}`, where `report` is the stored JSON parsed with `json.loads` and **not** validated through `FinalReport` (D8). OpenAPI type for `report`: a free-form object.
- [ ] **5.4 Immutability test:** save revision 1; change a seeded valuation or point value in the knowledge base the app uses and re-run; revision 1's bytes, prices, `last_verified`, and provenance are unchanged, and revision 2 differs where the data changed.
- [ ] **5.5 Commit** `feat(api): list and reopen saved trips verbatim`.

### Task 6: Re-run

**Files:** `backend/api/saved_trips.py`; test `backend/evals/test_a4_rerun.py`.

- [ ] **6.1 Failing tests** (scripted LLM): `POST /account/trips/{trip_id}/reruns` with `{client_event_id}` → `202 {job_id}`; after completion, revision N+1 exists with the current wallet projection in its `trip_spec`; a second rerun while one is running → `409 RERUN_IN_PROGRESS`; a failed or clarification-needing run appends nothing; a completion wrapper that fires twice appends once; another user's trip → `404`.
- [ ] **6.2 Implement** per D5–D7: load the attached session (exempt from expiry while attached), recompile its latest confirmed brief, project the caller's current wallet, create an owner-bound job, and start a thread that runs the existing `_run_job` and then, if the job ended `completed` with a report, calls `add_revision` with `client_event_id = "rerun:" + job_id`. Do not modify `run_pipeline` or the pipeline graph.
- [ ] **6.3** `GET /account/trips/{trip_id}/reruns/{job_id}` → `{status, stage, revision?, error?}`, owner-scoped. After a restart the job is unknown: return `404 RERUN_NOT_FOUND`, and document that a lost rerun leaves the trip unchanged.
- [ ] **6.4 Prompt-privacy test:** with a recording LLM client, a rerun's prompts contain no email, display name, or `last4`.
- [ ] **6.5 Commit** `feat(api): re-run saved trips into new revisions`.

### Task 7: Delete

**Files:** `backend/api/saved_trips.py`; tests in `test_a4_trip_privacy.py`.

- [ ] **7.1** `DELETE /account/trips/{trip_id}?client_event_id=…` → `204`; a replay → `204`; another user's trip → `404`. Follow the A3 wallet DELETE convention for the event id.
- [ ] **7.2 Commit** `feat(api): hard-delete saved trips`.

### Task 8: Error mapping and boundary coverage

**Files:** `backend/api/saved_trips.py`; test `backend/evals/test_a4_boundaries.py`.

- [ ] **8.1** One `_handle` mapper like `api/wallet.py`. **Ordering trap:** typed errors subclass `ValueError`, so the broad `ValueError → 422` arm comes last.
- [ ] **8.2** Response bodies never contain `sqlite`, `sqlalchemy`, `operationalerror`, or `traceback` (assert on 409, 413, 422, and 500 bodies).
- [ ] **8.3** Error codes: `PLAN_RESULT_UNAVAILABLE`, `SESSION_NOT_CONFIRMED`, `SESSION_ALREADY_SAVED`, `SESSION_NOT_ATTACHED`, `TRIP_NOT_FOUND`, `REVISION_NOT_FOUND`, `RERUN_IN_PROGRESS`, `RERUN_NOT_FOUND`, `TRIP_LIMIT_REACHED`, `REVISION_LIMIT_REACHED`, `REPORT_TOO_LARGE`, `IDEMPOTENCY_KEY_REUSED`, `TRIP_REVISION_CONFLICT`.
- [ ] **8.4** The legacy unauthenticated `/plan` contract is unchanged (`TripSpec.wallet` still caller-supplied; no saved-trip side effect).
- [ ] **8.5** The `core/` boundary test still passes; add the new routes to any route-inventory test that exists.
- [ ] **8.6 Commit** `test(api): saved-trip error mapping and boundaries`.

### Task 9: Contract synchronization — one PR

- [ ] **9.1 Export the schema** (deterministic, one trailing newline) and regenerate the client:

```bash
cd backend && .venv/bin/python -m api.main --export-schema /tmp/a4_openapi.json && cd ..
cp /tmp/a4_openapi.json contract/openapi.json && printf '\n' >> contract/openapi.json
cd frontend && npm run gen:api && cd ..
scripts/check-contract-drift.sh     # must pass; run it twice to prove stability
```

- [ ] **9.2** Re-export the new types and operations through `frontend/src/lib/api/index.ts`; components import `@/lib/api`, never `generated/`.
- [ ] **9.3** MSW handlers for every route, with success, empty list, 401, 403 (CSRF), 404, 409 (each code), 413, and 422 fixtures.
- [ ] **9.4** `npx tsc --noEmit` and `npx vitest run` pass.
- [ ] **9.5 Commit** `feat(contract): synchronize saved-trip API contract, client, and mocks`.

### Task 10: Report, deviations, and the exact-tree gate

- [ ] **10.1** `DEVIATIONS.md` section "A4 — saved trips" with a row for each Tier-C call (at least D1, D2, D5, D10, D11, D13, and anything decided during execution).
- [ ] **10.2** `reports/a4_saved_trips.md`: what shipped, commits, routes, measured verification, findings, open limitations, scope confirmations (verified by diff), deviations.
- [ ] **10.3** Commit, then on the **clean committed tree**:

```bash
make gate 2>&1 | tail -25           # must print GATE PASSED
scripts/check-contract-drift.sh
cd frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -3
```

Record the numbers from this run in the report in a follow-up commit, then re-run the gate on that commit.

## Definition of done

- Every route in Tasks 4–7 exists, is owner-scoped, CSRF-protected on mutation, idempotent, and typed on failure.
- Revisions are immutable and verbatim; the immutability test (5.4) passes.
- The concurrency tests (1.1, 2.1) pass with genuinely separate connections.
- Privacy export, account delete, and trip delete cover every new row.
- Contract, client, facade, and MSW fixtures are synchronized; the drift check passes twice.
- `make gate` passes on the final clean commit, with counts recorded from that run.
- No change to Tier-F code, goldens, specs, or other worktrees. Nothing pushed or merged.

## Known limitations to record (not to fix)

- Process-local jobs: a save after a restart, or a rerun interrupted by a restart, cannot complete (typed 409 or 404).
- A saved revision cannot be opened into the editable workspace; editing starts from a rerun (CP4 territory).
- No saved-trip UI yet.
