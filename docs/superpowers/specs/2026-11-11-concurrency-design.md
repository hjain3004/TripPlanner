# Planning concurrency: bounded admission and catalog memory

**Status:** design ready; implement after stream A's API/pipeline handoff. No capacity claim.
**Reviewed:** `origin/main` `a9efea09325a7446e9fa38c10d3d7d6bb0a1ecc0`, 2026-11-11.
The unpublished load-test README reports a 4-vCPU/4-GB Linux baseline with a delayed fake model;
its figures were not reproduced here and do not establish 2-GB AWS capacity. Scope is one process,
one replica, existing endpoints and frozen arithmetic. No external queue/service is introduced.

## Decisions

1. **Admission before work.** One application-lifespan `JobManager` owns a
`ThreadPoolExecutor(max_workers=2)` plus a nonblocking bounded semaphore for ten accepted jobs
(two running, eight waiting). ThreadPoolExecutor alone has an unbounded queue; only this wrapper
may submit. Configuration may lower capacity; increasing it requires the same-hardware check below.
Capacity counts input preparation and finalization, not just model time. No request waits for a
slot. Return 503 `PLANNING_CAPACITY_EXCEEDED`, `Retry-After: 5` before a new job/session/start event
is written. Separate HTTP input, auth, ownership and validation failures retain existing behavior.
All three dispatch sites use this path; no direct new job threads. Preparing the KB, provider/client
or itinerary happens only after admission. Model concurrency/spend still uses A's separate shared
limiter, covering non-plan roles too; obtaining a job slot does not authorize a model call.

2. **Durable start and replay.** Under the existing confirmation guard, validate the request and
look for an existing result **before** acquiring capacity. Exact confirmation/re-run replay returns
the stored job even when full; conflicts retain typed refusal. For a new start, reserve a slot,
register its worker handle, commit the queued job, then submit while holding the manager's admission
lock. Release the slot on every exception, duplicate race and terminal future callback, exactly
once. Queued handles count as alive, so polling must not mark them interrupted.

Confirmation currently saves a session before creating its job (`api/conversation.py`), leaving a
real restart gap. Add a narrow `AccountStore` transaction method that CAS-saves the opaque confirmed
session and inserts its `PlanningJob` together, including the confirmation event fingerprint.
Use the repository's existing serialized session shape; accounts must not import planning/agents.
The API checks replay/brief/version inside the existing session guard; the database rechecks owner,
expected version and event uniqueness. Session and job commit together, or neither does. Re-run
continues to use `start_planning_job` and its transactional one-live-per-trip and replay checks.
No account lock or SQLite transaction spans model work.

If executor submission fails after commit, persist the existing typed start failure and restore
the session to an explicit retryable failed state; the slot/handle is released. This is an accepted
start that failed, not a capacity refusal and not permission to erase its event/history. Hard death
after commit is handled by the existing restart reconciliation. Ownership/deletion/CAS fencing and
`JOB_INTERRUPTED` remain unchanged; queued jobs from a dead process are never automatically resumed.

3. **Terminal retention and shutdown.** Anonymous reports stay memory-only. Record terminal time;
evict after 15 minutes or when retaining more than 64 terminal reports, oldest first. Never evict a
queued/running job to admit another. Access after eviction is existing 404; saved revisions are
unaffected. Run bounded periodic housekeeping every minute in the lifespan maintenance task, plus
cheap admission/read checks. Keep owned job retention/export/delete under `AccountStore` as today.
On shutdown close admission, cancel queued futures and publish their interrupted outcome without
starting them; let running workers drain within the existing grace, then rely on process shutdown
and restart reconciliation. A Python thread cannot be force-killed or called safely cancelled.

4. **One catalog load, one resident region.** Current `_SNAPSHOT_CACHE` is unlocked and adapters
retain lists in `self._cache`; changing only the global entry count does not bound memory. Replace
this with a process-owned catalog cache keyed by resolved path/mtime/size, single-flight per key
and one loader globally. Default maximum is one resident region. A lease pins the shared immutable
candidate set while a request uses it; no adapter holds an independent long-lived list. Evict only
unleased entries. Different-region or replacement-version loads refuse with typed 503
`CATALOG_BUSY`, `Retry-After: 2` while the sole resident entry is pinned. Do not load another region
and hope to evict later. Same-key waiters share the load result/error and wait at most two seconds,
then fail soft; failure must remove the in-flight marker so a later explicit request can retry.

Bound file size before JSON parsing and candidate/claim counts during validation. Start with
64 MiB, 75,000 places and 225,000 claims. Inspected sidecars report Singapore 28,540 places and
New York 56,172; their files are about 19/38 MB, with 85,620/168,516 claim-field markers, respectively.
These are disk-shape observations, not decoded-memory measurements. Refuse
an over-limit region honestly rather than truncate or bypass provenance. Keep one read/parse at a
time to prevent temporary raw JSON/model copies multiplying. Recheck file identity before publishing
the cache entry. Idle cache TTL is ten minutes, followed by lease-aware eviction. This bounds copies
and concurrency, not arbitrary Python object memory; the 2-GB fit still needs measurement.

5. **Limits at both boundaries.** App capacity admission is mandatory even behind no proxy. Use a
second nonblocking single-worker admission guard for synchronous CPU-heavy recompute and place
search; excess returns typed 503 with Retry-After, leaving status/health/auth reads responsive.
Proxy limits apply to POST `/api/plan` (six/minute/IP, burst three) and `/api/places/search`
(60/minute/IP, burst ten), returning 429; do not rate-limit polling with the plan-start bucket.
Other owner-scoped plan starts still share the global job capacity. Use nginx's socket peer address,
not caller-supplied X-Forwarded-For or a session-cookie-presence shortcut. Preserve the current
proxy's header overwrite and internal-only backend port. A future CDN needs an explicitly trusted
proxy configuration; do not introduce `forwarded-allow-ips=*`. Shared-IP limits are prototype abuse
protection, not per-person fairness. Limits/configuration and new errors ship with API artifacts
where schema-visible; no unrelated nginx/TLS edits owned by G.

6. **Avoid repeated retrieval work without changing ranking.** Build a `place_id` lookup and
precomputed category/coordinate metadata once inside the same leased catalog entry, accounted in
its memory. `get_catalog_poi` uses that lookup rather than rescanning every candidate per itinerary
item. Replace retrieval's full first-stage sort with `heapq.nsmallest` using the exact current key
and limit, then preserve its final ranking, tie-breaks and provenance. Do not add approximate spatial
ranking, cache traveler results, change taxonomies or create an independently retained global index.
Apply only after parity on representative current fixtures; keep a scan if top-k changes behavior.

7. **Bound metadata, not money rules.** Trace files contain hashed artifacts and stage metadata;
retain the configured task-owned trace directory only. Use atomic replacement on flush; delete
finished traces older than seven days, then oldest finished traces above 64 MiB. Exclude active
trace IDs and symlinks; never traverse arbitrary paths or delete account reports/source captures.
Pass a worker-registration callback into `TraceRecorder` through a defaulted pipeline keyword so
the manager can distinguish active traces without guessing from mtime. Inspect disk usage rather
than applying a broad directory cleanup. No raw prompts/provider bodies added to traces.

## Interface and file handoff

These are proposed signatures, not implemented functions:

```python
JobManager.reserve() -> AdmissionLease  # nonblocking; typed capacity exception
JobManager.submit_reserved(lease: AdmissionLease, job_id: str,
                           run: Callable[[], None]) -> None
AccountStore.commit_confirmed_job(snapshot: PlanningSessionSnapshot, job: PlanningJob,
    *, expected_version: int, client_event_id: str,
    request_fingerprint: str) -> ConfirmedStartReceipt
CatalogCache.acquire(path: Path, *, timeout_s: float = 2.0) -> CatalogLease
JobManager.prune(*, now: datetime) -> None
```

Sonnet owns B: `api/job_manager.py`, all dispatch integration including confirmation in
`api/conversation.py`, the narrow `accounts/store.py` transaction, cache/lease callers in
`gateway/places/adapters/snapshot.py`, `agents/retrieval.py` and `agents/search.py`, trace lifecycle,
proxy rate-limit lines, and required API/error/packaging artifacts. These are necessary additions
to the plan's incomplete path list. A retains factory/input semantics; land A first and add only
the trace callback to its pipeline signature. G must preserve B's proxy lines. No core/golden,
provider-adapter, ingestion or second-replica changes.

## Acceptance and remaining risk

Builder supplies one bounded command, `python -m evals.demo_bounded_planning --data-dir <scratch>`,
using real uvicorn/SQLite and scripted model latency: fill running/waiting slots, get a quick typed
503 for a new start, replay an existing owned start despite saturation, reject conflicting replay,
kill/restart queued and running work without redispatch, and ensure deletion/late completion cannot
recreate a result. Demonstrate submission failure releases the slot and does not strand the session.
The command is a **future deliverable**, not an existing or executed check today.

Use the same Linux hardware/catalog/fake-model latency as a fresh safe baseline. The supplied driver
assumes every POST returns `job_id`; update it to classify expected 429/503 separately from transport
failures and bound polling by a deadline. Attempt 25 cold starts, then a 300-start burst with the
bounded pool: target no transport drops, warm poll p95 under one second, and capacity refusals p95
under one second. These are acceptance targets, not demonstrated figures. Stop an increasing trial
if it nears the host memory budget; do not reproduce the old OOM just for a before table.

Show one cold load for a shared key, no more than one resident region/loader, bounded workers and
terminal report eviction. After expiry, references/counts must fall and repeated cycles must not
grow retained memory; RSS need not return exactly to startup because Python retains arenas. For a
2-GB deployment require measured backend peak below 1 GiB and complete-stack peak below 1.6 GiB
under the agreed workload, with no swap/OOM. If these targets fail, the instance shape is unaccepted;
do not claim more threads or fictitious catalog estimates fix it. Run existing gates on final code.
