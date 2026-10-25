# A4 — Saved-Trip API and Planning Integration

**Status:** COMPLETE — independent review remediated; the final committed-tree gate passed (numbers in
"Verification").

**Base commit:** `cef3a4d4acad1b46eb3642efa013510f509fab79` (`origin/main`, PR #15)
**Branch:** `codex/a4-saved-trips`
**Worktree:** `/Users/himanshu_jain/.codex/worktrees/a4-saved-trips/TripPlanner`
**Plan:** `docs/superpowers/plans/2026-10-24-a4-saved-trips.md`
**Pushed / merged:** no. Nothing was pushed, merged, rebased, or opened as a PR.

---

## What shipped

A signed-in traveler can save a finished plan, list their saved trips, reopen any stored result exactly as
it was computed, plan a saved trip again for fresh prices (which becomes a new revision), and delete a
trip. Every route is owner-scoped, CSRF-protected, idempotent where it mutates, concurrency-safe, and
covered by privacy export and erasure.

Backend only, plus the one-PR contract synchronization. **No UI** was built (plan D12).

### Commits, one per plan task

| Task | Commit | Summary |
|---|---|---|
| plan | `fe672d6` | the plan |
| 1 | `f782ed0` | owner-scoped trip access; revision numbers serialised (`BEGIN IMMEDIATE` + unique index) |
| 2 | `ee415fa` | durable `(user_id, client_event_id)` idempotency; atomic `save_trip_with_revision`; limits |
| 3 | `f4eb836` | trips in privacy export/erasure; `delete_trip` cascade |
| 4 | `c340070` | `POST /account/trips`, `POST /account/trips/{id}/revisions` |
| 4 fix | `82ac6dd` | A1 boundary test pins the new `trip_mutation_events` table |
| 5 | `0cf22ae` | list / detail / verbatim revision reads |
| 6 | `e808970` | `POST …/reruns`, `GET …/reruns/{job}` |
| 7 | `771cd88` | `DELETE /account/trips/{id}` |
| 8 | `ff36111` | error mapping + boundary tests (found and fixed an unmapped read route) |
| 9 | `13fe9ed`, `daa444d` | contract, generated client, facade, MSW mocks + fixtures |
| review | `21f5958` | independent-review fixes |

### Route family

| Method | Path | Success |
|---|---|---|
| POST | `/account/trips` | 201 trip + revision 1 (session attached atomically) |
| GET | `/account/trips` | 200 summaries, newest first, no report bodies |
| GET | `/account/trips/{trip_id}` | 200 trip + revision summaries |
| DELETE | `/account/trips/{trip_id}?client_event_id=` | 204 (replay 204) |
| POST | `/account/trips/{trip_id}/revisions` | 201 next revision from the attached session |
| GET | `/account/trips/{trip_id}/revisions/{n}` | 200 stored report, verbatim |
| POST | `/account/trips/{trip_id}/reruns` | 202 `{job_id}` |
| GET | `/account/trips/{trip_id}/reruns/{job_id}` | 200 `{status, stage, revision?, error?}` |

Typed failures: `PLAN_RESULT_UNAVAILABLE`, `SESSION_NOT_CONFIRMED`, `SESSION_ALREADY_SAVED` (with
`trip_id`), `SESSION_NOT_ATTACHED`, `SESSION_NOT_FOUND`, `SESSION_EXPIRED`, `STALE_SESSION`,
`TRIP_NOT_FOUND`, `REVISION_NOT_FOUND`, `RERUN_IN_PROGRESS`, `RERUN_NOT_FOUND`, `TRIP_NOT_RERUNNABLE`,
`TRIP_LIMIT_REACHED`, `REVISION_LIMIT_REACHED`, `REPORT_TOO_LARGE` (413), `IDEMPOTENCY_KEY_REUSED`,
`TRIP_REVISION_CONFLICT`, `SAVED_TRIPS_UNAVAILABLE` (503).

---

## Verification — measured on the final committed clean tree

All figures below were measured in this session, on the committed tree `1542d27` (clean `git status`),
with the regional catalogs copied in (never committed). The report-only commit that records them changes
no code; the gate was re-run on it (see the last row).

| Check | Baseline (own run on `cef3a4d` + plan) | Final tree |
|---|---|---|
| `make gate` | GATE PASSED | **GATE PASSED** (`GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`) |
| Backend pytest | 1883 passed, 1 skipped | **1991 passed, 1 skipped** (+108: 104 A4 tests by the end of Task 9, +4 from the review fixes) |
| mypy `--strict` | 177 + 5 files clean | 178 + 5 files clean |
| Ruff, zero-tolerance scope | clean | clean |
| Ruff `core/` + `api/` legacy ratchet | 6 (ceiling 12) | 6 (ceiling 12) — A4 added none |
| `scripts/check-contract-drift.sh` | — | `CONTRACT_DRIFT_OK`, run twice |
| Frontend `tsc --noEmit` | exit 0 | exit 0 |
| Frontend Vitest | 177 passed (11 files) | **204 passed (12 files)** (+27 saved-trip mock tests) |
| Frontend ESLint | 14 warnings, 0 errors | 14 warnings, 0 errors |

The one skipped backend test is the pre-existing `CP1_MERGE_BASE` guard (a clean worktree has no merge
base to compare), unchanged by A4.

Per-test-file counts at the end of the work: `test_a4_trip_scoping` 15, `test_a4_trip_idempotency` 14,
`test_a4_trip_privacy` 12, `test_a4_save_api` 24, `test_a4_read_api` 10, `test_a4_rerun` 15,
`test_a4_boundaries` 18.

Tests that were mutation-checked (the production change that must make them fail): removing
`BEGIN IMMEDIATE` fails the concurrent-append test and the concurrent-save-cap test (2 of 3 runs each);
the replay-before-limit ordering tests fail if the order is swapped by construction.

---

## Findings worth recording

1. **The pre-A4 store resolved a trip by id alone** (the defect A3 found in the wallet), and nothing
   stopped two writers taking the same `max + 1`. Fixed in Task 1; the concurrency test fails on 2 of 3
   runs when the lock is removed (mutation-checked).
2. **A read route skipped the error mapper.** `GET /account/trips` called the store without `_handle`, so a
   locked database would have been an unmapped 500. Found by the Task 8 leak test (RED first), fixed.
3. **Summaries must not materialise reports.** A revision row's payload embeds the whole report (up to
   2 MiB). List/detail read `trace_id`, `schema_version`, `created_at` with SQLite `json_extract`.
4. **`get_store()` opens the database on every request** (pre-existing). The new duplicate-index check
   therefore had to be a catalogue lookup, not a scan; the independent review caught the scan.
5. **Process-local jobs shape the product.** A save needs the in-memory report; a restart loses it
   (`409 PLAN_RESULT_UNAVAILABLE`). A re-run in flight during a restart is lost; the trip is unchanged.
6. **The mapper order trap** (typed errors subclass `ValueError`) is pinned by a parametrised test.
7. **CSRF is checked after body validation** (same as A3), so an invalid body without a CSRF header is 422,
   not 403.
8. **The review's expired-session finding** turned out not to allow revival (the attach model validator
   rejected it) — but as a misleading 422. It is now a typed 410.

## Open findings and limitations

- **Jobs and re-run state are process-local.** A save after a restart, or a re-run interrupted by one,
  cannot complete (typed 409/404); the registry of re-runs is also lost, and a retried re-run *start* after
  a restart launches a new job.
- A saved revision cannot be opened into the editable workspace; editing starts from a re-run (CP4).
- No saved-trip UI.
- A re-run of a trip whose confirmed dates are now in the past plans those past dates (UX, CP4).
- Freed SQLite pages are not zeroed on delete (`secure_delete` is not enabled); a hard delete removes rows,
  not file bytes, until the file is vacuumed.
- `STALE_SESSION` and `TRIP_NOT_RERUNNABLE` have no dedicated test.

### Deferred Minor review findings (not fixed, for a human to decide)

> **Update:** items 3 (error contract), 4 (mock drift), 5 (`rerun:` prefix collision), 6 (pruning
> untested) and 7 (lock outside the mapper in `_launch_rerun`) were closed afterwards — see
> `reports/a4_closure.md`. `STALE_SESSION` and `TRIP_NOT_RERUNNABLE` are also covered there.

1. `GET /account/trips` would 500 on a revisionless trip (reachable only through the legacy A1 `save_trip`).
2. The catch-all `ValueError → 422` also covers server-side `ValueError`s.
3. OpenAPI documents no 404/409/413/503 bodies (`ApiErrorBody` is unused), so generated client error types
   are the validation-error shape.
4. MSW mocks drift from the real API: DELETE ignores `client_event_id` replay; append/rerun-start ignore
   idempotency, `SESSION_NOT_ATTACHED`, `RERUN_IN_PROGRESS`; rerun status reports `revisions.length`.
5. A client `client_event_id` starting with `rerun:` can collide with a rerun-completion event.
6. In-memory re-run registry pruning (> 256) is untested and has user-visible effects.
7. A lock timeout inside `_launch_rerun`'s store reads is not mapped (500 instead of 503).
8. Save/append/rerun events store the report a second time (2× disk and export vs the 2 MiB cap).
9. `is_current_schema` compares only `ACCOUNTS_SCHEMA_VERSION`; nothing forces a bump when `FinalReport`
   changes shape (suggest a hash-pin guard test).
10. `job_manager` keeps every re-run's report in memory for the life of the process (pre-existing pattern).

## Scope confirmations (verified by diff)

- `git diff --name-only cef3a4d..HEAD` touches **no** file under `backend/agents/`, `backend/core/`,
  `backend/gateway/`, `backend/ingestion/`, or `docs/specs/`. The pipeline graph, its four call sites, the
  optimizer, transfer math and all golden values are untouched (`GOLDENS_OK` in the gate).
- `api/main.py` only gains the router include; the legacy unauthenticated `/plan` and `/places/search` are
  unchanged (a test proves `/plan` has no saved-trip side effect and still takes a caller wallet).
- The only change outside `accounts/` and `api/` in `backend/` is the additive
  `PlanningSessionRepository.snapshot_of`.
- No provider, MCP, Claude client, deployment, UI, CP4, FI, or spec 18 work. Catalogs were copied from
  another worktree's ignored directory and never committed.
- No secret entered any tracked file.

## Deviations

Fifteen rows are recorded in `DEVIATIONS.md` under "A4 — Saved-trip API and planning integration".

## Review closure

One independent whole-branch review (fresh opus subagent) found 0 Critical, 0 Important, 15 Minor as
labelled. Re-graded by effect, five entered the fix pass and were fixed test-first (commit `21f5958`);
ten remain deferred above.
