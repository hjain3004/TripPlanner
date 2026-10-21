# D1 — Deployment foundation and production-mode vertical slice

**Status:** COMPLETE (local). **Not** a public deployment: no cloud account, resource, domain, DNS,
TLS, credential or paid service was created or used.

**Branch:** `codex/d1-deployment-foundation` · **Base:** `11355602d220b09c276c46718c5b2a22b3351975`
(`origin/main`, verified exact before the worktree was created) · **Manual:** [`docs/DEPLOYMENT.md`](../docs/DEPLOYMENT.md)

The product now builds reproducibly and runs from a clean clone as a production-like, **single-instance,
sample-mode** stack, with automated CI and one genuine frontend-to-backend smoke journey that includes a
backend restart. It remains explicitly **not horizontally scalable**.

## 1. Production-runtime gaps found before implementing (reproduced, not assumed)

| Area | Finding at the start of D1 | What D1 did |
|---|---|---|
| Backend process | no documented start command; `uvicorn` was never declared (only a transitive dependency of `mcp`) | declared `uvicorn`, entrypoint runs exactly **one** worker |
| Frontend build/start | only `npm run build && npm run start` (Playwright's webServer); no standalone output | multi-stage Next.js standalone image |
| Mock vs live | `NEXT_PUBLIC_API_MODE` unset ⇒ **MSW mock**; base URL defaults to `http://localhost:8000`; values are compiled in at build time | explicit validated build arg (`live` default in the stack), same-origin `/api` base |
| SQLite paths | state lived **inside the source tree**: `core/tripwise.sqlite`, `accounts/accounts.sqlite`, `backend/.traces`; the KB was lazily created on the first request | single `TRIPWISE_DATA_DIR`; code stays read-only |
| Process-local jobs | `api/job_manager.py` is an in-memory dict; plus process-local confirmation/preference locks in `api/conversation.py` | **unchanged by design**; measured and documented (404 after restart) |
| Cookie / CSRF / CORS | cookies are always `Secure` (browsers accept them over http only on `localhost`); backend routes `/plan`, `/plan/{job_id}` **collide with the UI's `/plan` pages**; CORS default allowed `localhost:3000` | nginx same-origin proxy with an `/api` prefix; production CORS defaults to none; nothing weakened |
| Catalogs / seed | `backend/catalogs/` is untracked (~140 MB); on a fresh worktree **19 tests fail and 8 skip**; `make seed` fails (`python: command not found`) | explicit marker + strict gate mode; `PY` defaults to the venv; optional read-only catalog mount |
| Gondola OAuth | tokens in the **OS keychain** after an interactive browser sign-in — impossible in a container | documented; live Gondola is structurally unavailable |
| Provider ledgers | per-plan budgets are SQLite files at caller-supplied paths (Gondola, Tripadvisor) or in memory (weather); none wired into the runtime | documented; would need shared storage before any live use |
| MCP runtime | Open-Meteo needs a separately provisioned, lockfile-verified Node ≥ 24 server tree | deliberately **not** in the image; startup refuses the flag in production |
| Health | only a constant `GET /health` | `/health/live`, `/health/ready` |
| CI | **no `.github/` at all** | `ci.yml` (required) + `full-browser-suite.yml` |
| After restart | accounts persist; jobs vanish | measured by the smoke |
| Multiple replicas | jobs invisible across replicas; process-local locks; SQLite on a shared volume unsupported | documented as not supported; section 11 of the manual lists the prerequisites |
| Sign-in UI | **none exists** (accounts can only be created through the API) | recorded as a gap; smoke authenticates through the real API |
| `/plan` exposure | legacy unauthenticated `/plan` writes a trace file per request with no retention | recorded under "before public hosting" |

## 2. Implemented behaviour

* **Backend image** (`backend/Dockerfile`): Python 3.14-slim-trixie pinned by digest; `pip install --require-hashes`
  from `backend/requirements.lock` (universal, regenerated with `make lock`); non-root uid 10001; code root-owned
  and read-only; no secrets, databases, `.env` or catalogs in the image; readiness `HEALTHCHECK`; entrypoint =
  validate configuration → `python -m core.db seed` (the real path) → `uvicorn --workers 1`.
* **Frontend image** (`frontend/Dockerfile`): multi-stage; only the standalone server, its traced dependencies,
  static assets and `public/` ship; non-root `node`; `NEXT_PUBLIC_API_MODE` (live|mock, validated) and
  `NEXT_PUBLIC_API_BASE_URL` are the only build args.
* **Compose** (`deploy/compose.yaml`): nginx-unprivileged same-origin proxy is the only published port (loopback);
  backend and frontend sit on an `internal: true` network (**no outbound access**); read-only containers, all
  capabilities dropped, `no-new-privileges`, pid and tmpfs limits; health-gated startup; a named data volume;
  optional read-only catalog overlay (`deploy/compose.catalogs.yaml`).
* **Configuration**: `deploy/.env.example` (names and explanations only, six sections); `api/runtime_config.py`
  validates required configuration at startup and refuses live-capable switches in production (errors carry
  variable names only). A test pins that every `TRIPWISE_*` variable the backend reads is documented — it found
  six that were not.
* **Runtime**: `TRIPWISE_DATA_DIR` (stdlib-only `core/runtime_paths.py`); `/health/live`, `/health/ready` (read-only
  probes, out of the OpenAPI contract); the API lifespan opens the accounts database through its real schema/migration path.
* **Catalog handling**: the 19 catalog-asserting tests carry `requires_regional_catalogs` (skipped with a visible
  reason when absent; session abort when `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`, which `make gate` sets).
* **Tooling**: `make setup | lock | contract-check | docker-build | compose-up | compose-down | d1-smoke`;
  `scripts/d1-smoke.sh`, `scripts/d1-backup.sh`, `scripts/check-contract-drift.sh`.
* **CI**: `ci.yml` on PRs and `main` — backend (seed, complete pytest with accounted skips, strict mypy, Ruff + ceiling,
  frozen artifacts), frontend (tsc, Vitest, ESLint, token lint, build, dead classes), contract drift, container builds
  + the genuine smoke. `full-browser-suite.yml` (manual + weekly) runs the complete ~570-case Playwright suite.
  Actions pinned to full SHAs, `contents: read`, no secrets, no write-back, `shell: bash` (pipefail).

## 3. Locally verified (measured on the final code, not copied)

| Check | Result |
|---|---|
| Documented clean-clone startup (`git clone` → `make compose-up`) | stack healthy from nothing; `/api/health/ready` → `sample`, no live provider |
| Clean-clone developer path (`make setup && make seed`) + complete backend suite, **no catalogs** | 1820 passed, 27 skipped (26 catalog-related), 0 failed (before review fixes; re-run on the final HEAD in the handoff) |
| Both production images | built: backend 656 MB, frontend 433 MB |
| Genuine smoke (`make d1-smoke`) | **D1_SMOKE_OK** — see section 4 |
| Complete backend suite **with** catalogs | **1881 passed, 1 skipped** (baseline 1778/1 + 103 new D1 tests) |
| Strict mypy | clean, 177 files + 5 in `ingestion/` (182) |
| Ruff | zero-tolerance scopes clean; legacy `core/`+`api/` ratchet **6** (was 7; `api/main.py` import sort cleared one), ceiling 12 |
| Frontend `tsc`, Vitest, ESLint, token lint, build, dead classes | clean; **177** Vitest passed; ESLint 0 errors (14 pre-existing warnings); 0 token violations; 0 dead classes |
| Contract drift (`scripts/check-contract-drift.sh`) | OpenAPI export ×2 byte-identical and equal to the committed contract (export + one trailing newline); client regenerated ×2 byte-identical and equal to the committed client |
| Complete browser suite (4 projects, live tests disabled) | **492 passed, 76 skipped, 0 failed**, run twice (before and after the review fixes); identical to the accepted baseline, because the live-stack spec is excluded from the default config and runs only against the Compose stack |
| Backup / restore | backup digest-verified, mode 600; restored onto a **fresh** volume and re-verified through phase 2 |
| `make gate` on the exact final committed clean tree | recorded in the handoff for the final HEAD (a commit cannot contain its own SHA) |

## 4. The genuine smoke — what it proves

A real Chromium, the real built bundle in live mode, the real nginx proxy and the real FastAPI backend with real
SQLite. No MSW, no `page.route`. Phase 1: frontend loads in live mode with **no registered MSW worker**; `/health/ready`
says sample mode with no live provider; unauthenticated calls are refused; registration and login; cookie attributes
(`tp_session` HttpOnly+Secure+Lax, `tp_csrf` readable+Secure+Lax); CSRF missing/wrong token → 403, right token → 201;
durable idempotency replay; profile read; the **app itself** requests `/api/account/wallet` and renders the entry; a
planning session starts (wallet reflected, `interview_llm_calls == 0`, no LLM role ran); a typed answer is accepted and
re-read; `/plan/conversation` makes its own `/api/planning/*` call and shows the first question; a legacy job without an
LLM fails honestly ("not configured"). Then the **backend container is restarted** and phase 2 shows: the pre-restart
session cookie is still valid; the wallet entry (same id and version), the planning session and its answer persist; a fresh
sign-in works; the in-memory planning job is gone and the API answers **404**. Outside the browser, the script asserts the
backend runs as uid 10001, cannot reach the internet, and that no database, `.env` or catalog is in either image.

**Teeth** (each verified red): wallet entry removed behind the app's back; backend stopped; frontend built in **mock** mode
("no mock service worker in live mode").

## 5. Independent whole-branch review — findings and dispositions

One Critical, four Important, nine Minor. All Critical/Important fixed with tests (commit `7e6e2b9`):

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Critical | CI `pytest \| tee` under GitHub's default `bash -e` (no pipefail) — a red suite would pass | **Fixed**: `shell: bash` everywhere; test pins every job/step |
| 2 | Important | restore used `cp` as uid 10001 from a read-only mount (fails on Linux hosts); copy-out never verified | **Fixed**: root one-off copy + chown; umask 077; SHA-256 compare; re-tested |
| 3 | Important | smoke could pass against a mock build (service workers were blocked; raw fetches bypass the app) | **Fixed**: SW allowed, MSW asserted absent, app-initiated `/api` calls required; verified red on a mock image |
| 4 | Important | "live providers refused in production" covered only two of four documented switches | **Fixed**: CP3 flag and Tripadvisor credential also refused; tests |
| 5 | Important | skip accounting matched file *paths* containing "catalog" | **Fixed**: classify on the reason; tests run the workflow's own script |
| 6 | Minor | validation could crash / echo (`²`, bad IPv6/port); trailing-slash origins never match | **Fixed** |
| 7 | Minor | `TRIPWISE_PORT` documented but unwired | **Removed** |
| 8 | Minor | nginx froze upstream addresses at start | **Fixed**: per-request resolution (restart path re-tested) |
| 9 | Minor | readiness recreated a deleted accounts DB; `provider_mode` is a constant | **Fixed**: read-only probes + tests; docs say it is a static label |
| 10 | Minor | egress check passed on any error; smoke not hermetic; image scan gaps | **Fixed** |
| 11 | Minor | dockerignore patterns matched only the context root | **Fixed** |
| 12 | Minor | trace growth, grace period, limits | **Fixed/documented** |
| 13 | Minor | doc inaccuracies (Compose ≥ 2.24, Safari, per-instance LLM ceiling, Swagger under prefix) | **Fixed** |
| 14 | Minor | test polish | **Fixed** (exact headings); lifespan-created `accounts.sqlite` in dev is pre-existing behaviour (git-ignored) |

## 6. Assumptions

* Docker Desktop's bind-mount permission translation was used for local verification; the restore procedure was
  written to also work on Linux hosts but only the Docker Desktop path was executed.
* Chromium treats `http://localhost` as a secure context for `Secure` cookies (verified); Safari does not (documented).
* GitHub Actions behaviour is as documented; **the workflows have not run on GitHub** (nothing was pushed) — every command
  in them was executed locally, and the YAML was parsed and statically tested.
* The six regional catalogs cannot be regenerated inside a build (raw inputs and provisioning data are not in the repo).

## 7. Deferred (explicitly out of D1)

Public hosting, TLS and DNS; any cloud account or resource; a secret store; a sign-in/registration UI; authentication
or rate limiting of the legacy unauthenticated `/plan` and `/places/search`; CSP; logging/metrics/alerting; scheduled
and off-site backups; image scanning and patch cadence; and all horizontal-scaling work (networked database with real
migrations, durable job queue, distributed locks, shared budgets). Also unstarted: CP4, FI1–FI6, card acquisition,
live Gondola/Tripadvisor/Open-Meteo activation, booking/payment/transfers.

## 8. Known limitations

* **Single instance only.** Never run more than one backend replica.
* **Planning jobs do not survive a restart** (404); there is no queue.
* **No sign-in UI**; the smoke creates accounts through the API.
* Image builds need network (npm, PyPI, Google Fonts via `next/font`); only the *runtime* is network-isolated.
* `evals/test_contract_one_pr.py` only inspects uncommitted changes, so it is vacuous in CI; the new drift script is the real guard.
* CI skips 26 catalog-asserting tests (counted and printed); they are verified by `make gate` on a provisioned machine.
* A few unrelated checks remain environment-gated (e.g. `CP1_MERGE_BASE` skip).

## 9. Environment incident (disclosed)

The machine's data volume was at ~100% (220 MB free) when Docker first ran; a build pushed it over, Docker's VM
filesystem hit I/O errors and remounted read-only. Recovery was non-destructive: I freed space by purging **only
regenerable package-manager download caches** outside the repository (pip cache 3.4 GB; uv's unreferenced entries
~5.7 GB) and restarted Docker with `docker desktop restart`. No Docker image, volume or project belonging to anything
else was touched (the user's other images and a `sentry-local` volume were preserved). A `docker volume`/factory reset
was deliberately not used.

## 10. Files

See `git diff --stat 11355602d220b09c276c46718c5b2a22b3351975..HEAD`: backend runtime (`core/runtime_paths.py`,
`api/health.py`, `api/runtime_config.py`, small edits to `core/db.py`, `accounts/db.py`, `api/main.py`), tests
(`evals/test_d1_*.py`, `evals/catalog_guard.py`, marker-only edits to three test modules), images and lockfiles,
`deploy/`, `.github/workflows/`, `scripts/`, smoke spec/config, `Makefile`, `docs/DEPLOYMENT.md`, `DEVIATIONS.md`
(section D1), this report. Untouched: `contract/openapi.json`, the generated client, `backend/evals/golden/`,
`docs/specs/`, Tier-F arithmetic, and every provider/gateway package.
