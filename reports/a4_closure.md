# A4 — Correctness and Contract Closure

**Status:** COMPLETE — five bounded fixes, each test-first; the final committed-tree gate passed (numbers
in "Verification").

**Base:** the A4 build, `d3536f561a760881d4c748741db536ed1c53cc31`, on `codex/a4-saved-trips`
(itself on `origin/main` `cef3a4d`).
**Pushed / merged:** no. Nothing was pushed, merged, rebased or opened as a PR.
**Not started:** CP4 (the next task), durable job execution, SQLite file-level erasure.

---

## What was closed

| # | Problem | Fix | Commit |
|---|---|---|---|
| 1 | `rerun:<job_id>` shared an event-id space with caller-supplied ids, so a client could make a finished re-run fail with `RERUN_NOT_SAVED` | Event keys are namespaced (`client:` / `system:`), `TripMutationEvent.source` exposes it, the worker uses `system_event_id`; a mutation names at most one | `0b3c380` |
| 2 | `_launch_rerun` read the database outside the error mapper, so a lock was an untyped 500 | Runs through `_handle` (typed 503, reservation released); a new file holds a genuine `BEGIN EXCLUSIVE` from a second connection against all eight routes | `96d9848` |
| 3 | OpenAPI declared no failure bodies; generated clients described them as the validation-error shape | Per-route `responses`, a closed 19-value `ApiErrorBody.code` union, `AuthErrorResponse` for 401/403, a 422 union; contract, client and facade regenerated together | `8434ea0` |
| 4 | Mocks omitted idempotency and conflict behaviour a UI depends on | Stateful mocks model replay, event reuse, one trip per session, attached-session checks, both caps, delete replay, re-run in-progress and the appended revision number; fixtures typed against the generated code union | `254f1a8` |
| 5 | `STALE_SESSION`, `TRIP_NOT_RERUNNABLE` and rerun-registry pruning were untested | Tests for each, mutation-checked; an unreadable attached session is now `TRIP_NOT_RERUNNABLE` instead of a misleading 422 | `898353a` |

Each fix was written test-first. The tests that guard a production branch were mutation-checked (the
branch removed, the test fails, the branch restored):

- lock wrap around `_launch_rerun` removed → the launch-contention test fails;
- `STALE_SESSION` branch removed → its test fails;
- `TRIP_NOT_RERUNNABLE` guard removed → 3 tests fail;
- pruning disabled → 2 tests fail; pruning that also evicts running reruns → 1 test fails.

## Behaviour worth knowing

- A client may now send `client_event_id: "rerun:<anything>"` freely; it lives in the `client` namespace.
- `422` is declared on the two read routes with path parameters only because FastAPI adds one regardless.
- Past the registry cap (256), an old rerun's status is `404 RERUN_NOT_FOUND` and a retried start with an
  evicted event id launches a **new** run. This is the documented limit, now pinned by a test, and is a
  consequence of process-local jobs.

---

## Verification — measured on the final committed clean tree

VERIFICATION_PLACEHOLDER

---

## Still open (unchanged by this pass)

- Jobs, the rerun registry and confirmation locks are process-local; a restart loses them.
- SQLite file-level erasure: deleted rows leave freed pages until a vacuum; a retention design (including
  backups) is needed rather than an incidental `VACUUM`.
- Deferred Minors from `reports/a4_saved_trips.md` that this pass did **not** touch: a revisionless trip
  would 500 the list (reachable only through the legacy A1 `save_trip`); the catch-all `ValueError → 422`
  also covers server-side `ValueError`s; save/append/rerun events store the report a second time;
  `is_current_schema` compares only `ACCOUNTS_SCHEMA_VERSION` (suggest a hash-pin guard test);
  `job_manager` keeps every re-run's report in memory for the life of the process.
- No saved-trip UI, and a saved revision cannot be opened into the editable workspace (CP4).

## Scope confirmations (verified by diff)

`git diff --name-only d3536f5..HEAD` touches no file under `backend/agents/`, `backend/core/`,
`backend/gateway/`, `backend/ingestion/`, or `docs/specs/`. No provider, Claude client, deployment, UI,
CP4 or spec 18 work; no secret entered a tracked file. Deviations are in `DEVIATIONS.md` under
"A4 — correctness and contract closure".
