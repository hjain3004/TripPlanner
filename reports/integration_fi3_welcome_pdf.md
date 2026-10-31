# Integration: FI3 review dry-run, held-card welcome status, PDF compatibility

**Branch:** `codex/integrate-fi3-welcome-pdf`, based on `origin/main` `6f0859b`.
**Status:** combined tree accepted for the checks listed under "Measured verification". The
exact-tree `make gate` result on the final integration commit is recorded in the pull request and
the hand-off, not here: this file cannot state the outcome of a run that happens after it is written.

## Working now

| Capability | Who / entry point | Boundary |
|---|---|---|
| **FI3 review + activation dry-run** | A named local operator: `python -m ingestion.review_server` (`add-curator`, `demo`, `inspect`, `decision`, `reopen`, `bundle`, `dry-run`, `serve`). `serve` is a loopback-only browser app (one-time login token on stderr). | Offline operator tool. **No KB apply.** Dry-run builds an in-memory `KnowledgeBase` and reports `would_update`; seeds, KB, goldens, OpenAPI and frontend are untouched. Not traveler-facing. |
| **Held-card welcome-window status (spec 18 Case A)** | An authenticated owner: `POST /account/wallet/{entry_id}/welcome-status` for an owned wallet entry + saved trip revision. | **Backend API only; no traveler UI.** The shipped offer catalog is **empty**, so production answers `unknown` / `NO_APPROVED_OFFER`. A points bonus is **not valued** (`bonus_value_minor: null`, `POINTS_PROGRAM_NOT_ESTABLISHED`) because no verified card-to-points-program mapping exists. Case B untouched. |
| **PDF compatibility** | Existing FI1/FI2 PDF isolation path (`get_default_runner()`, `canonicalize_content`, `verify_evidence_span`). | Compatibility with the real `pdfplumber` for benign generated PDFs. **Not a security-sandbox result**: same user, filesystem and network, no rlimits. |

## What was merged

Three real `--no-ff` merge commits; no squash, rebase, cherry-pick or discarded side. Sources were
verified at their recorded heads with clean worktrees and are preserved unmodified.

| Source branch | Source head | Merge commit |
|---|---|---|
| `codex/fi3-review-dry-run` | `467be88` | `1e73263` |
| `codex/held-card-welcome-status` | `31b9823` | `4cc60c6` |
| `codex/pdf-compatibility-closure` | `2cf34f1` | `ba2d8fe` |

**Conflicts:** one, `DEVIATIONS.md` (FI3 and spec 18 each appended a section at the same place).
Resolved by keeping both sections verbatim; no existing line was removed.

**Semantic checks on the merged tree:** FI3 `SCHEMA_VERSION = 4` and its v3-to-v4 migration test
are intact; `Makefile` and `.github/workflows/ci.yml` keep the original `mypy --strict ingestion/`
and `ruff check ingestion/` lines **and** the separate `welcome/` lines; `backend/pyproject.toml`
lists both `ingestion` and `welcome` (with `welcome` package data); the backend `Dockerfile` copies
`welcome` (it does not copy the offline `ingestion` package, which is unchanged). A wheel built from the committed
tree ships all five `welcome/` files including the empty offers YAML, every FI3 module
(`review*.py`, `activation.py`) and no synthetic welcome fixture.

## Real-browser finding (the one defect integration found)

The suite had **no HTTP-level test** of the FI3 review app; the source report's host/origin/CSRF
and security-header claims were not covered by any test (the existing tests exercise the review
service, bundles and bind/data-dir guards only). Driving the loopback app in a real browser, login failed with
`403 invalid_origin`. A header-capture probe showed why: with `Referrer-Policy: no-referrer` the
browser sends `Origin: null` on its own same-origin form POSTs (Fetch standard), which the strict
origin allowlist correctly refuses, so no operator could sign in or decide. The probe with
`Referrer-Policy: same-origin` sent `Origin: http://127.0.0.1:<port>`.

**Fix** (`7339fec`, separate behavior commit): the policy is now `same-origin`; the allowlist is
unchanged and still refuses `null`, missing and cross-site origins. `evals/test_fi3_review_http.py`
adds three TestClient tests (login, inspect, approve, idempotent replay with durable storage;
origin/host/CSRF refusals; a pin on the policy header, verified to fail against `no-referrer`).
Logged in `DEVIATIONS.md`.

**Browser execution vs TestClient.** The three new tests set `Origin` by hand, so they cannot
reproduce what a browser sends; only the header pin covers that. The actual browser run was manual,
in the Claude desktop app's built-in Chromium-based browser pane against a throwaway data
directory: sign-in with the one-time token, queue, proposal page (summary, typed `manual_capture`
finding, exact evidence quote), approve through the form. A separate CLI process then read back
`status: approved`, reviewer `alice`, the reason typed in the browser and a server-issued event id,
with audit events `created`, `decision`. That browser run is **not** an automated test and was not
repeated for edit, reject, re-verify, bundle pages or logout.

## Demonstrations (execution mode in the second column)

| Workflow | Mode | Observed |
|---|---|---|
| FI3 CLI: manual upload, snapshot, scripted FI2 extraction, inspect, validated approval, reopen in a new process, bundle, dry-run | Synthetic fixture (`example.invalid`), real `SnapshotService`, real `FinancialExtractor`, real SQLite | Evidence span `exact`; provenance stays `UNVERIFIED`/`needs_verification`; bundle `applicable`; replay of the same event id is byte-identical; dry-run `would_update`, `kb_constructs: true`, `seed_files_unchanged: true`, and seed hashes plus tree status identical before and after. The demo's proposal equals the current row, so `field_changes` is empty: it demonstrates the path, not a real change. |
| FI3 browser workflow | Manual real-browser run (above) | Works after the fix; 403 before it. |
| Welcome status (`evals.demo_welcome_status`) | Real in-process app, real SQLite, scripted LLM, **synthetic** offers | Empty catalog: `unknown`, `NO_APPROVED_OFFER`. Synthetic offer: `active`, closes 2026-12-30, 67 days left, shortfall 3,800,000 of 5,000,000 after 1,200,000 prior spend, 22,403,200 conditional trip spend, bonus 10,000 points with `bonus_value_minor: null`. Omitted prior spend leaves the shortfall `null`; no `opened_on` gives `unknown`. A foreign and a nonexistent wallet entry return identical `404 WALLET_ENTRY_NOT_FOUND`. |
| PDF canonicalization + evidence verification | Real-library local execution (`pdfplumber` 0.11.10, `pdfminer.six` 20260107, CPython 3.14.6, macOS arm64) | 134 passed (51 compatibility + 83 isolation); no worker process left behind. Missing-dependency behavior is simulated inside the worker and passes with and without the library installed. |

## Measured verification

Each row states the revision it ran on. `7339fec` is the last code revision; the documentation
commit that follows changes no code.

| Check | Revision | Result |
|---|---|---|
| `make seed` | `ba2d8fe` | exit 0 |
| Complete backend suite (`TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`) | `ba2d8fe`, first run | 2752 passed, 52 skipped, **11 errors** (see below) |
| Same | `ba2d8fe`, second run | 2763 passed, 52 skipped, 0 errors |
| Same | `7339fec` | **2766 passed, 52 skipped, 3 warnings** (adds the 3 new HTTP tests) |
| `mypy --strict` | `7339fec` | clean: 200 files (core/accounts/planning/agents/api/gateway), 26 (ingestion), 4 (welcome) |
| `ruff check` zero-tolerance scopes | `7339fec` | clean (accounts/planning/agents/gateway/evals, ingestion, welcome) |
| `ruff` legacy ratchet (`core/` + `api/`) | `7339fec` | 8 (ceiling 12) |
| Real-library PDF modules, explicit run | `7339fec` | 134 passed; FI0/FI1/FI2 suites 53 passed |
| Same compatibility module on the gate interpreter | `7339fec` | 51 skipped, each reporting that the real library is absent (ordinary gate runs do not establish compatibility) |
| `scripts/check-contract-drift.sh` | `7339fec` | `CONTRACT_DRIFT_OK` |
| `tsc --noEmit`, Vitest | `7339fec` | exit 0; 229 passed (13 files) |
| ESLint, token-lint | `7339fec` | 0 errors (14 existing warnings); 0 violations across 15 rules |
| Normal production build (`npm run build`, default bundler) | `7339fec` | passes, with this worktree's own real `node_modules` (an APFS clone of an identical-lockfile install, not a symlink) |
| `no-dead-classes` | `7339fec` | 0 |
| Playwright `f1-gate.spec.ts` (4 projects + axe) | `7339fec` | 107 passed, 13 skipped (the spec's own project-conditional skips; axe runs on the desktop project) |
| Playwright `f1-5-landing.spec.ts` (product shots + axe) | `7339fec` | 54 passed, 6 skipped (same condition) on the second run; see below |

Only the welcome branch changes frontend files (contract, generated client, facade, mocks), so the
frontend results verify that change on the combined tree.

### Anomalies investigated

- **11 setup errors in the first complete run** (a contiguous block in `test_fi1_pdf_isolation.py`).
  They did not reproduce: that module alone passed (83), and a second complete run passed with 0
  errors. The error text was not captured (only the summary was tailed), so the cause is
  **unproven**. The only coincident observation was free disk falling from about 677 to 313 MiB
  during the run, which fits a transient environmental fault but is not established. No code
  defect was found.
- **One Playwright `webServer` build failure** (Turbopack could not resolve a `next/font/google`
  import). It did not reproduce in three plain builds or on re-running the same spec. Cause
  unknown; the build fetches Google Fonts, so it depends on that fetch working.
- Running the product-shots spec rewrites tracked reference PNGs under `design/refs/f1_5/` and
  creates untracked `plan-*.png`; both were restored/removed afterwards and the tree is clean.

## Limitations and not claimed

- FI3 is an offline, local-shell operator tool: no KB apply (FI5), no live source, no
  authorization to activate anything; approvals have no expiry; manual-capture provenance stays
  `UNVERIFIED`. The chunked-request body limit is still enforced only for `Content-Length` bodies.
- Welcome status has no traveler UI or report placement, no approved offer data, no valued points
  bonus, and does not change the optimizer or any total. Prior spend is user-entered and
  unverifiable. Case B is not started.
- PDF checks use benign generated PDFs, Latin/WinAnsi Helvetica only, on macOS arm64; no
  encrypted, scanned, CJK/RTL or real issuer PDFs; versions float within the declared range. Not
  exploit resistance and not an OS sandbox.
- Not done and not authorized: FI4/FI5, verified financial data, spec edits, provider/crawler/model
  activation, credentials, spend, deployment, bookings or transfers.

## Environment and disk

Disk was the constraint (about 0.3 to 0.7 GiB free throughout). Reused, not recreated: the primary
checkout's backend venv (symlinked, the gate interpreter), the task-owned `pdf-real-venv` (read-only,
for the real-library run), and the welcome worktree's ignored regional catalogs (APFS clones of
12 files, byte-compared). `node_modules` is an APFS clone, so no other worktree's install was
modified. To recover space I removed only my own regenerable output: the welcome worktree's 254 MB
ignored `frontend/.next` and two pytest temp directories; no worktree, branch or shared cache was
deleted.
