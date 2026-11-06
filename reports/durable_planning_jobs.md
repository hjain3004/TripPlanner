# Durable planning jobs

Branch `codex/durable-planning-jobs`, based on `main` @ `a7412e5`. Decisions: `DEVIATIONS.md`, section
"Durable planning jobs". Scope: the existing planning jobs only. No queue, scheduler, second database,
provider, gateway, Gondola, weather, financial-arithmetic, seed or golden change.

**Status: implemented, demonstrated with real process kills, independently reviewed.** The gate result
and CI status for the exact committed tree are recorded in the pull request.

## 1. What a traveler sees now

| Situation | Before | Now |
|---|---|---|
| Plan finished, backend restarted, traveler reopens the plan | `404`/`queued` forever; report lost; "save trip" refused (`PLAN_RESULT_UNAVAILABLE`) | the **same report, byte for byte**, through the same endpoints; saving it works |
| Plan was mid-flight when the backend died | stuck `queued`/`running`, or 404 | `failed` with `error.code = "JOB_INTERRUPTED"` and a message that says what is known; the session moves to `failed`, which the existing "confirm again" accepts |
| Traveler polls, reloads, or re-sends the confirmation / re-run start after a restart | n/a (state was gone) | answered from the stored job; **no model or provider call is dispatched** |
| Traveler edited the finished report (typed edit, prose refresh), then restart | edit lost | the edit is the stored report (compare-and-swap on the report's inventory revision) |
| Re-run started, backend restarted | `404 RERUN_NOT_FOUND`, in-memory registries gone | same job id, status and revision survive; a replayed start returns the original job |
| Someone else's job id | `404 Job not found` | unchanged: **identical** to a nonexistent id (same status and body), including after a restart |
| Account deleted while a plan is running | n/a | the late completion finds no row and recreates nothing |

Newly visible: error code **`JOB_INTERRUPTED`** (no schema change; `error.code` is already a free string,
public `status` stays `failed`). The messages:

* planning had begun: "Planning was interrupted during the *stage* stage (the service restarted or its worker
  stopped). Model or provider calls may already have been made and cannot be confirmed. Nothing was repeated
  automatically; start planning again."
* planning had not begun: "... before any planning stage had begun, so no model or provider call was started. ..."
* a confirmed session with no job record at all, past a 120 s start window: "Planning could not be found after the
  service restarted. Whether it started cannot be established ..."

## 2. Which jobs are durable, and why not all

| Job | Stored? | Reason |
|---|---|---|
| Confirmed-brief job (`POST /planning/sessions/{id}/confirm`) | **yes** | owned by an authenticated user |
| Saved-trip re-run (`POST /account/trips/{id}/reruns`) | **yes** | owned; shares the same lifecycle and table (`kind = rerun`) |
| Anonymous `POST /plan` | **no**, still in memory | no owner: nothing to authorize, export or delete. A stored copy would be ownerless personal data. After a restart it is `404`, as before (the D1 smoke asserts this and still holds). |
| CP4 post-plan operations | already durable (CP4); **untouched** | their own reservations/CAS stay as they were |

## 3. Persisted states and interruption semantics

`planning_jobs` (accounts database; additive `create_all`, no `ALTER` of existing tables). One row per job, payload =
`accounts.models.PlanningJob`:

```
queued --> running --> complete | needs_clarification | failed
   |          |
   +----------+--> interrupted      (worker lost; terminal; never resumed)
```

* Stored: ids, owner, session, kind, trip, status, stage/stage_index, the report JSON as the traveler saw it, the
  admitted-inventory snapshot (needed by CP4 initialisation), unresolved list, typed error (code/message/trace id),
  re-run revision, `process_id`, start event id + fingerprint, `calls_may_have_started`, timestamps. **Not stored:**
  credentials, prompts, raw provider or model bodies.
* `process_id` names the process executing the job. A queued/running row of **another** process has lost its worker;
  so has a row of **this** process with no registered worker handle (its worker died or its final write was lost).
  Both read `interrupted`, lazily on read and for every row at startup (lifespan).
* `calls_may_have_started` becomes true when the first pipeline stage begins. It is the only distinction recorded about
  external calls: if false, the message states that none were started; if true, it states that they may have been and
  cannot be confirmed. **Exactly-once external calls are not promised.**
* Every worker write is a guarded `UPDATE` inside `BEGIN IMMEDIATE`: status still queued/running **and** `process_id`
  equal to the writer's. A stale execution (interrupted job, replaced process, duplicate completion) therefore writes
  nothing, a terminal job cannot be replaced, and nothing is ever upserted, so deletion cannot be undone by a late
  worker. No transaction is held while the pipeline runs: one short transaction per stage and one at the end, with three
  bounded retries on a locked database.
* Re-run specifics: `(user_id, start_event_id)` is unique; "one live re-run per trip" is checked inside the start
  transaction; the revision is appended by a finalizer (idempotent on `rerun:<job_id>`) **before** the job is
  published `complete`, so `complete` always means the revision exists; a finalizer failure publishes a typed failure
  (`TRIP_NOT_FOUND`, `REVISION_LIMIT_REACHED`, `REPORT_TOO_LARGE`, `RERUN_NOT_SAVED`).

## 4. What is deliberately not resumed

A job that was queued or running when its process died is **never** resumed, re-queued or re-dispatched, by startup,
polling, reopening, or a replayed request. Its model and provider consumption cannot be established and the pipeline
has side effects (call budgets, scripted/provider calls). The traveler's remedy is the existing explicit action:
confirm again, or start a re-run with a new `client_event_id`. That creates a **new** job. The old job stays
`interrupted` as the honest record. CP4 workspace operations keep their own rule (reserved operations that outlive their
worker become `interrupted`; the traveler retries with a new action).

## 5. Migration and privacy

* Existing databases: the new table is created additively on open (`create_all`); no existing table is rewritten.
  `test_a_database_from_before_this_feature_opens_without_losing_anything` drops the table from a populated database,
  reopens it, and checks users are intact.
* Existing saved reports/revisions are untouched and still read verbatim (job reports are new records in the
  current report shape; one that a future build can no longer parse reads as a typed `REPORT_UNREADABLE` failure,
  never reshaped).
* Privacy export includes `planning_jobs`. Deletion: account (`delete_user`), trip (its re-run jobs and attached
  sessions' jobs), and the expired-session sweep all delete job rows. A job cannot be created for a missing user.
* Retention: finished jobs are swept 30 days after their last update (`PLANNING_JOB_RETENTION_DAYS`), at startup;
  live jobs are never swept. This is not an archive: a saved trip's revisions are the long-term record.

## 6. Actual restart demonstration

`python -m evals.durable_jobs_demo run --data-dir <empty dir>` (also `evals/test_durable_jobs_process_restart.py`, 12 s):
real `uvicorn` processes over shared on-disk SQLite, a scripted offline model that appends every call to
`llm-calls.log` (so "nothing was redispatched" is a count, not an assumption), `SIGKILL` for crashes, `SIGSTOP`/`SIGCONT`
for a frozen process. Measured output: **24/24 checks held**.

1. Plan completes; `SIGKILL`; new process: report identical (`/planning/sessions/{id}/job` and `/plan/{job_id}`); 0 model calls.
2. `SIGKILL` while the plan is inside its first model call; new process: status `running` before, `failed`/`JOB_INTERRUPTED`
   after, no report; replaying the confirmation returns the same job id; model calls after restart, replay and repeated
   polling equal the calls before (no redispatch).
3. Explicit retry through the normal confirmation creates a different job that completes.
4. The pre-restart plan is saved, re-run (revision 2), `SIGKILL`; new process: re-run status `complete`/revision 2, replayed
   start returns the same job, trip holds exactly revisions `[1, 2]`, 0 model calls.
5. Stale completion across processes: a server is frozen mid-plan, a second server starts and reports the job interrupted,
   the first is thawed and runs its pipeline to the end (the log shows its remaining model calls). Its result is **refused**
   (report stays null, status stays failed).
6. Another account's request for the job equals its request for a nonexistent id (status and body).
7. The owner is deleted while the plan is in flight; the plan runs to completion and no user, session or job row reappears.

Faster in-process equivalents (`simulate_restart`) cover the same cases and more edge cases in `evals/test_durable_jobs.py`.

## 7. Compatibility and contract

* No new endpoint. One `rerun_status` description string changed (it no longer says "unknown (404) after a restart"):
  `contract/openapi.json` and `frontend/src/lib/api/generated/sdk.gen.ts` were regenerated together;
  `scripts/check-contract-drift.sh` passes; MSW fixtures and facade types needed no change (no type changed).
  Frontend `tsc --noEmit` and `tests/contract.test.ts` (27) pass. The traveler UI treats `failed` as terminal and shows
  `error.message`, so the interrupted message appears without a UI change.
* Tests that asserted the old behaviour were rewritten, not deleted: "plan lost to a restart is never reconstructed"
  became "finished plan survives; interrupted plan is never reconstructed"; the CP4 initialisation tests now cover a
  finished job after a restart. Three tests of the in-memory re-run pruning were removed with the registries.
* Shared files: none of the other agent's (gateway adapters, provider registry, activation flags, Gondola, weather).
  `docs/DEPLOYMENT.md`, `docs/INFRASTRUCTURE.md` and `CLAUDE.md`/`AGENTS.md` (identical) got corrections of the
  old "jobs do not survive a restart" claims.

## 8. Remaining limitations

* **Single process.** `process_id` is the only liveness signal (the shipped profile is `--workers 1`). A second live
  replica would see the first one's running jobs as orphans and mark them interrupted. A lease/heartbeat would fix that
  and was not built.
* A hard-killed worker is noticed when the job is next read or at the next startup; there is no background watchdog.
* An interrupted job's partial work is discarded; there is no checkpoint, and none is claimed.
* Anonymous `POST /plan` jobs remain process-local.
* A confirmed session's job row is committed *after* the session's CAS save; the 120 s window and the
  `JOB_INTERRUPTED`-after-grace rule cover a crash between the two, but the traveler then retries rather than resuming.
* Report and snapshot are stored as JSON text in SQLite (bounded by `MAX_REPORT_BYTES`); the privacy-export and
  SQLite file-level erasure caveats recorded for A4 apply unchanged.

## 9. Verification

Execution mode: real SQLite, real FastAPI app, real `uvicorn` processes for the restart demonstration, scripted offline
model; no network beyond loopback, credentials, live provider or spend. The required `make seed` / unchanged
`make gate` result and test counts for the exact committed tree are in the pull request description.

**Independent review** (one read-only reviewer; flakiness check: `test_durable_jobs.py` three runs, no variation):
no Critical or Important findings. It confirmed: identical 404 for foreign, unauthenticated and missing job ids on every
route; no path that starts model/provider work from polling, replaying a confirmation or re-run start, or reopening;
stale and duplicate writers refused; deletion vs late completion; the edit compare-and-swap. Four Minor findings, all
fixed with tests: (1) a failed thread start left a permanent `queued` row and a leaked worker handle, so the confirm path now
closes the job `failed` (`PLANNING_START_FAILED`); (2) a job of this process whose final write was lost blocked re-runs of the
trip until someone polled it, so the live-re-run check now interrupts own rows without a worker; (3) a finished plan whose job
row had been swept (30 days) on a saved-trip session was described as a restart interruption, so it now reads
`JOB_EXPIRED` ("the saved trip keeps its revisions") and the session is not failed; (4) `complete()` now releases the worker
handle in a `finally` and `_retry` records any write failure instead of killing the worker. Accepted and recorded, not
changed: if a re-run's revision was appended and only then the final job write failed, the job reads `interrupted` although the
revision exists (the trip is correct; the job status is conservative); two concurrent prose refreshes are last-writer-wins
(prose only, no figures change); nothing enforces `--workers 1` (documented).
