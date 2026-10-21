# Deployment (D1): single-instance, sample-mode, production-like local stack

**Status:** implemented and locally verified (see `reports/d1_deployment_foundation.md`).
**Not** a public deployment: no cloud account, domain, TLS, or paid service is involved, and
nothing here publishes the application anywhere.

This page is the operating manual for the D1 deployment profile. It is deliberately explicit
about what the profile is *not*: **it is single-instance by design.** The databases are SQLite
files and planning jobs live in one process's memory, so the backend must run as exactly one
replica. Section 11 lists what has to change before that can be true.

## 1. Architecture and ports

```text
 browser ──► proxy (nginx-unprivileged) ── 127.0.0.1:8080 (the only published port)
                │  /api/*  (prefix stripped) ──► backend  (FastAPI, 1 uvicorn worker, :8000)
                └  everything else            ──► frontend (Next.js standalone server, :3000)

 networks:  edge     = proxy only (published, has outbound access)
            internal = backend + frontend + proxy  (internal: true  => NO outbound network)
 volume:    tripwise-data  ->  /data  (the only writable path of the backend)
```

* The browser only ever talks to one origin. The session cookie (`HttpOnly; Secure;
  SameSite=Lax`) and the double-submit CSRF cookie therefore work exactly as designed with
  **no CORS relaxation**. The `/api` prefix exists because backend routes (`/plan`,
  `/plan/{job_id}`) would otherwise collide with the UI's own `/plan` pages.
* The backend and frontend containers have **no route to the internet**. That is a mechanical
  guarantee that no live provider can be reached from this profile, whatever the environment says.
* All three containers run non-root, read-only, with all Linux capabilities dropped and
  `no-new-privileges`. The backend's only writable paths are `/data` and a tmpfs `/tmp`.

## 2. Clean-clone startup

Prerequisites: Docker with Compose **>= 2.24** (the optional `env_file` form needs it). Node and Python are *not* needed to run the stack.

```bash
git clone <this repository> && cd TripPlanner
make compose-up           # builds both images, starts the stack, waits until healthy
# open http://localhost:8080
make d1-smoke             # optional: genuine end-to-end verification (about 20 s once built)
make compose-down         # stop; the data volume is kept
```

`make compose-up` is `docker compose -p tripwise-d1 -f deploy/compose.yaml up -d --build --wait`.
No `.env` file is required; with none, every live provider is disabled.

Developer bootstrap (running tests/linters locally, not required to run the stack):

```bash
make setup                # backend/.venv from the HASHED lockfile + frontend `npm ci` (needs Python 3.14, Node 22)
make seed                 # builds the local reference database (uses backend/.venv automatically)
make gate                 # the authoritative local gate (needs the regional catalogs - section 13)
```

The old friction (`make seed` failing with `python: command not found`) is fixed: `PY` now
defaults to `backend/.venv/bin/python` when it exists and `python3` otherwise, never bare `python`.
Override with `make seed PY=/abs/path/to/python`.

## 3. Environment variables

The template is `deploy/.env.example` (**names and explanations only**; copy to the gitignored
`deploy/.env`). It separates required production configuration, compose-level settings,
optional application settings, local-development-only variables, live-provider variables and
kill switches. Summary:

| Variable | Purpose | Required? |
|---|---|---|
| `TRIPWISE_ENV=production` | enables strict startup validation | set by compose |
| `TRIPWISE_DATA_DIR=/data` | the one directory for all mutable state | set by compose; required in production |
| `TRIPWISE_CORS_ORIGINS` | cross-origin allowlist | **leave unset** (production then allows none) |
| `TRIPWISE_HTTP_PORT` | host loopback port of the proxy | optional (8080) |
| `TRIPWISE_FRONTEND_API_MODE` | `live` (default) or `mock` build of the UI | optional, **build-time** |
| `TRIPWISE_LLM_*`, `TRIPWISE_OLLAMA_*` | hosted/local LLM endpoint (`TRIPWISE_LLM_MAX_CALLS` is a ceiling per LLM client instance, i.e. per request) | optional; without them LLM planning fails honestly |
| live-provider switches | `TRIPWISE_GONDOLA_LIVE_ENABLED`, `TRIPWISE_OPEN_METEO_ENABLED`, `TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED=1`, `TRIPWISE_TRIPADVISOR_API_KEY` | **each refused at startup in production** (a Gondola/Open-Meteo/Tripadvisor kill switch makes its flag moot); kill switches always win |

Startup validation (`python -m api.runtime_config`, run by the entrypoint and again by the API
lifespan) rejects an unwritable/missing data directory, an unknown `TRIPWISE_ENV`, malformed or
wildcard CORS origins (a trailing slash is also rejected: Starlette matches origins exactly), a
non-positive-integer `TRIPWISE_LLM_MAX_CALLS`, and in production any of the four live-capable
switches listed above. Validation never crashes on malformed input and never echoes it. **Errors name the variable and a fixed problem only, never a value.** A
missing provider credential is never an error: sample mode starts with none.

## 4. Persistent paths

| Path in the backend container | Contents | Backed up? |
|---|---|---|
| `/data/accounts.sqlite` | users, credentials (Argon2id), sessions, wallets, travel preferences, planning sessions, CP3 interview-call ledger, audit events | **yes - irreplaceable** |
| `/data/tripwise.sqlite` | the seeded reference knowledge base (cards, rules, sample flights/hotels) | no - rebuilt from the image's seeds on every start |
| `/data/traces/` | pipeline traces | no - disposable diagnostics |
| `/app/catalogs/` (optional, read-only mount) | regional place catalogs | no - untracked inputs, see section 13 |
| process memory | **planning jobs**, confirmation locks | **lost on every restart** |

Outside containers, with `TRIPWISE_DATA_DIR` unset, state stays where it always was (next to
the code), so development and the test suite are unchanged.

## 5. Migrations and seed behaviour

The entrypoint does exactly three things, all through the application's existing code paths
(there is deliberately no second schema initialiser):

1. `python -m api.runtime_config` - validate configuration.
2. `python -m core.db seed` - rebuild the reference knowledge base from the seeds baked into
   the image, so reference data always matches the deployed code. This drops and recreates
   **only** `tripwise.sqlite`; accounts live in their own database file and are never touched.
3. `uvicorn api.main:app --workers 1` - on startup the API lifespan calls
   `create_accounts_engine`, which creates missing tables and applies additive migrations
   (`wallet_entries.version`) and **never drops anything**.

## 6. Mock versus live frontend modes

`NEXT_PUBLIC_*` values are compiled into the browser bundle at build time, so the mode is a
**build** choice, not a runtime flag. Rebuild to change it.

* `live` (default in this stack): the UI calls the real backend at the same-origin `/api` prefix.
* `mock`: MSW fixtures, no backend network. Build with
  `TRIPWISE_FRONTEND_API_MODE=mock docker compose -p tripwise-d1 -f deploy/compose.yaml build frontend`.

Nothing secret may be passed as a `NEXT_PUBLIC_*` value; the Dockerfile accepts only the two
public build args and a test fails if a secret-shaped name appears.

## 7. Cookies, CSRF, CORS, same origin

* `tp_session` is `HttpOnly; Secure; SameSite=Lax`; `tp_csrf` is readable by the SPA (by design),
  `Secure; SameSite=Lax`. State-changing requests need the matching `X-CSRF-Token` header.
  Verified in a real browser by the smoke (cookie attributes, missing/wrong token refused).
* Nothing was weakened for convenience. Because the cookies are `Secure`, Chromium and Firefox accept
  them over plain HTTP **only for `http://localhost`**; Safari does not, so use a Chromium/Firefox
  browser for this local profile (the smoke runs Chromium). This local profile therefore binds the proxy to
  loopback. **Any real hostname must be served over HTTPS** (TLS termination is not part of D1).
* The proxy hides FastAPI's interactive docs (`/api/docs`, `/api/redoc`): they assume the site root and
  are broken under the `/api` prefix. The machine-readable schema stays at `/api/openapi.json`.
* `TRIPWISE_CORS_ORIGINS` is unnecessary in the supported same-origin arrangement. In production
  mode it defaults to an empty allowlist (the development default of `localhost:3000` no longer applies).

## 8. Health checks

| Endpoint (via proxy) | Meaning |
|---|---|
| `GET /api/health/live` | the process is up; touches nothing |
| `GET /api/health/ready` | data dir writable; the accounts database and the knowledge base exist and are readable (cheap **read-only** probes: a probe never creates, migrates or recreates a database, so it cannot mask a deleted one; the schema is created once by the API lifespan at startup). **Provider state is reported but can never make the sample app unready.** Returns 503 with check names only (no paths, no exception text) when not ready |
| `GET /api/health` | legacy constant `{"status":"ok"}` (unchanged) |
| `GET /healthz` | the proxy itself |

`/health/ready` also reports `"provider_mode": "sample"` (a fixed label of this profile) and
`"live_providers_enabled": []` (computed from the real registries and flags - this is the field that
carries information; the network isolation in section 1 is the stronger guarantee). These endpoints are excluded from
the OpenAPI contract. Container health checks use readiness, so `docker compose up --wait` and
the `depends_on: service_healthy` ordering mean "actually able to serve".

## 9. Restart behaviour (measured by the smoke, not assumed)

| After the backend container restarts | Result |
|---|---|
| accounts, passwords, the pre-restart browser session cookie | **survive** (sessions are stored server-side) |
| wallet entries (same id and version), planning sessions and their typed answers | **survive** |
| reference knowledge base | rebuilt from the image seeds |
| **planning jobs** (`POST /plan`, confirmed-plan jobs) | **lost**: `GET /plan/{job_id}` returns `404 Job not found`; the UI must restart the job. Durable session state and the confirmation event are the recovery boundary - there is no job queue |
| in-flight requests | fail; graceful shutdown allows 10 s |

A legacy planning job in a deployment with no LLM configured fails *honestly* (`failed`,
"HostedFreeTier is not configured ...") instead of hanging or fabricating a plan.

## 10. Provider kill switches and live providers

All live providers are disabled by default and the four live-capable switches (section 3) are
**refused at startup in production**. Per
provider: Gondola (`TRIPWISE_GONDOLA_LIVE_ENABLED` / `_KILL_SWITCH`), Open-Meteo
(`TRIPWISE_OPEN_METEO_ENABLED` / `_KILL_SWITCH`), Tripadvisor (`TRIPWISE_TRIPADVISOR_KILL_SWITCH`,
live transport not wired), CP3 interview LLM (needs `TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED=1`).
Kill switches always win. Why live activation is *structurally* impossible in this profile, not
merely discouraged:

* **Gondola** stores OAuth tokens in the **OS keychain** (`keyring`) after an interactive browser
  sign-in. A container has no keychain and no browser; there is no non-interactive path.
* **Open-Meteo** needs a separately provisioned, lockfile-verified Node >= 24 MCP server tree that
  is deliberately not in the image (see `reports/g4_open_meteo_weather_context.md`).
* The `internal` network has no outbound route at all.
* File-backed provider budget ledgers (Gondola, Tripadvisor, Open-Meteo) take caller-supplied paths;
  none is wired into the runtime, and the weather ledger defaults to memory. They would need the
  shared durable storage of section 11 before any live use.

## 11. Single-instance limitations, and what must change before horizontal scaling

Do **not** run more than one backend replica. Specifically:

* **Planning jobs are per-process memory.** With two replicas a job created on one is invisible to
  the other (`404`).
* **Confirmation and preference locks are process-local** (`api/conversation.py`), as the CP2.1
  report already records. SQL compare-and-swap protects data, but the in-process serialisation does not span replicas.
* **SQLite on a shared volume** across containers is unsupported: default rollback-journal mode,
  no WAL, no busy-timeout tuning, advisory locking that is unreliable on network filesystems.
* Provider ledgers/budgets are per-file or per-process.

Required before scaling out: a networked database (e.g. PostgreSQL) with real migrations instead of
`create_all` plus ad-hoc ALTERs; a durable job queue (or sticky routing as a stopgap) and
re-hydration of confirmed sessions into jobs; distributed locks or removal of the process-local ones;
shared rate-limit/budget storage; and revisiting every `threading.Lock`. This is **not** done in D1
because the single-instance profile does not require any of it.

## 12. Backups

Only `accounts.sqlite` is irreplaceable. Use the online-backup API, never `cp` of a live file:

```bash
scripts/d1-backup.sh ./backups          # verified (integrity_check) copy, mode 600
```

The script verifies SQLite integrity inside the container, streams the file out (`docker cp` cannot
read a tmpfs), and compares SHA-256 digests so a truncated copy is deleted rather than kept.

Restore onto a fresh data volume (tested on Docker Desktop): create the stack without starting it,
copy the file in with a one-off **root** container that then hands ownership to the app user (this also
works on Linux hosts whose uid is not 10001), then start:

```bash
docker compose -p tripwise-d1 -f deploy/compose.yaml create
docker run --rm --entrypoint sh -u 0 -v tripwise-d1_tripwise-data:/data \
  -v "$PWD/backups:/backup:ro" tripwise-backend:d1 -c \
  'cp /backup/accounts-<STAMP>.sqlite /data/accounts.sqlite && chown 10001:10001 /data/accounts.sqlite && chmod 600 /data/accounts.sqlite'
docker compose -p tripwise-d1 -f deploy/compose.yaml up -d --wait
```

Restoring over an existing volume additionally requires stopping the backend first and removing any
stale journal file next to the old database; that removal is left to the operator. A backup contains user
data and password hashes: treat it as a credential. There is no scheduled backup in D1.

## 13. Regional catalogs

The regional place catalogs (`backend/catalogs/active_*-core.json`, six corridors, ~140 MB, derived
from Overture Maps) are **deliberately untracked** and cannot be regenerated inside the build (the
raw extracts and the provisioning inputs are not in the repository). Consequences, handled
explicitly rather than hidden:

* **Containers** run without them and honestly report regions lacking catalog coverage as
  unsupported. To provide them: `TRIPWISE_CATALOGS_DIR=/abs/path/to/backend/catalogs docker compose -p tripwise-d1 -f deploy/compose.yaml -f deploy/compose.catalogs.yaml up -d`.
* **Tests:** 19 backend tests (plus 7 that already guarded themselves) assert on real catalog content.
  On a clone without catalogs they carry the `requires_regional_catalogs` marker and are **skipped with
  a visible reason**; CI prints the count. `make gate` sets `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`, which
  aborts the session if any catalog is missing, so the authoritative gate cannot pass on an unprovisioned clone.

## 14. CI

| Workflow | Runs | Covers |
|---|---|---|
| `ci.yml` (required; **has not yet run on GitHub** - verified by running each command locally) | every PR and push to `main` | backend seed, complete pytest (catalog-less, skips accounted), strict mypy, ruff + legacy ceiling, frozen goldens/brief identity; frontend `tsc`, Vitest, ESLint, token lint, production build, dead classes; OpenAPI + generated-client drift; both container builds; the **genuine live-backend smoke** |
| `full-browser-suite.yml` (separate) | manual dispatch + weekly | the complete ~570-case Playwright suite in mock mode (too slow for every PR) |

All steps run under `shell: bash` (which implies `pipefail`; GitHub's default `bash -e` would let
`pytest | tee` hide a red suite - a test pins this). Skips are classified by their *reason* text, so an
unrelated skip in a file merely named `*catalog*` still trips the guard. All actions are pinned to full
commit SHAs, permissions are `contents: read`, no secrets are
referenced, nothing is written back to the branch, and no live provider or paid service is reachable.
Not in CI: `make gate`'s catalog-dependent assertions and its clean-tree check; run `make gate` locally on a provisioned machine.

## 15. What remains before public hosting

Not done and out of scope for D1: TLS and a real hostname/DNS; a cloud account and resources; a
production secret store; a **sign-in/registration UI** (the product has none: accounts are created
through the API only); authentication or rate-limiting on the legacy unauthenticated `/plan` and
`/places/search` endpoints (an LLM key plus a public `/plan` is a cost-abuse risk, and every `/plan` request writes a trace file
to `/data/traces` with no retention, on the same volume as the accounts database - it can fill the disk); a Content-Security-Policy;
log aggregation, metrics and alerting; scheduled backups and a tested off-site restore; abuse and
privacy operations; image scanning and a patch cadence; dependency update automation; and the
horizontal-scaling work in section 11.
