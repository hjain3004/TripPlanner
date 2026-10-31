# FI3 — Human review and activation dry-run

Status: ACCEPTED on the combined integration tree — offline operator workflow and independent
review are complete, and the required full checks passed on code revision `7339fec` of
`codex/integrate-fi3-welcome-pdf` (see "Acceptance update" below and
`reports/integration_fi3_welcome_pdf.md`). The exact-tree `make gate` result on the final
integration commit is recorded with the pull request. Live financial activation remains out of
scope; the body below is preserved as written for the source branch (`467be88`).

## Delivered operator path

The separate local entry point is `python -m ingestion.review_server`. A named curator is
registered in the FI3 SQLite store with `add-curator`; `serve` binds only to loopback and
prints one short-lived login token to stderr. The operator can inspect the FI2 proposal,
source snapshot, exact evidence spans, lineage, typed findings and row diffs, then approve,
reject, edit through FI2 validation, or request re-verification. Decisions, audit events and
re-verification tasks are durable and replay-safe across SQLite reopen.

Approved/edited decisions can be serialized as a deterministic, content-addressed activation
bundle and dry-run against read-only seed rows. The dry-run validates model/reference integrity
and constructs an in-memory `KnowledgeBase`; it never applies rows or writes seeds, the KB,
goldens or product OpenAPI/frontend artifacts.

Demonstration (from `backend/`, with a data directory outside the repository):

```text
python -m ingestion.review_server add-curator --data-dir /tmp/tripwise-fi3 --curator-id alice --display-name Alice
python -m ingestion.review_server demo --data-dir /tmp/tripwise-fi3
python -m ingestion.review_server inspect --data-dir /tmp/tripwise-fi3 --proposal-id <proposal-id>
python -m ingestion.review_server decision --data-dir /tmp/tripwise-fi3 --proposal-id <proposal-id> --curator-id alice --action approve --reason "reviewed synthetic fixture" --expected-version 1 --client-event-id approve-fi3-0001 --curator-confidence 0.90
python -m ingestion.review_server reopen --data-dir /tmp/tripwise-fi3 --proposal-id <proposal-id>
python -m ingestion.review_server bundle --data-dir /tmp/tripwise-fi3 --curator-id alice --client-event-id bundle-fi3-0001 --proposal-id <proposal-id>
python -m ingestion.review_server dry-run --data-dir /tmp/tripwise-fi3 --bundle-sha256 <bundle-sha256>
python -m ingestion.review_server serve --data-dir /tmp/tripwise-fi3 --curator-id alice --host 127.0.0.1 --port 8765
```

`demo` labels its manual upload, `example.invalid` source, snapshot and scripted extractor
response as synthetic. It uses `SnapshotService.capture` and the real `FinancialExtractor`; it
does not claim live source evidence or authorized activation.

The repeatable offline acceptance test is `evals/test_fi3_review_activation.py` and exercises
the real FI2 validation path, named-curator approval, restart/replay, deterministic bundle
creation and in-memory dry-run. It measured an applicable bundle with `would_update`,
`kb_constructs=True`, and unchanged seed hashes.

## Safety and limitations

- No live calls, credentials, spending, provider activation, bookings, transfers or automatic
  application are performed.
- The review app is a separate loopback-only process with host/origin/CSRF checks, strict
  security headers, escaped server-rendered HTML, disabled docs/OpenAPI, and data-dir guards.
- Evidence and current-row hashes are rechecked for context, decisions and bundle creation;
  stale, superseded, conflicting and tampered inputs fail closed.
- FI3 keeps the existing FI2 PDF process isolation and does not modify the PDF subsystem.
- The local-shell curator model, manual-capture provenance policy, no-expiry approvals, and
  future FI5 application semantics remain the documented open decisions.

## Verification

Focused FI3/FI0/FI1/FI2 checks: 141 passed, 1 warning (pytest cache cannot be written because
the shared virtual-environment checkout is reused). Strict mypy and Ruff are clean for the
FI3 modules. Full seed, backend, frontend/browser checks and the exact-tree `make gate` are
deferred until disk capacity is safe. A version-3 SQLite database was reopened and migrated to
version 4 with curator and activation-bundle tables intact. The CLI demonstration produced an
applicable bundle with `would_update`, `kb_constructs=True`, and unchanged seed hashes.

Independent whole-branch review found and the implementation fixed: missing CLI/browser edit
submission, missing bundle dry-run rendering, raw bundle HTML injection, and concurrent bundle
replay race. The review also noted chunked-body limits and confidence persistence; the former
remains bounded by the local operator surface's request handling and the latter is now stored on
`ReviewDecision`. The review's lower-risk chunked-request observation remains a documented
limitation: the normal form path is capped by `Content-Length`, while a future hardening pass
should enforce streaming byte limits before parsing chunked bodies. No Critical findings were
verified.

## Acceptance update (2026-10-30, combined tree)

Measured on `codex/integrate-fi3-welcome-pdf` at code revision `7339fec` (FI3 merged with the
held-card welcome-status and PDF-compatibility branches); the full table, the commands and the
revision of each run are in `reports/integration_fi3_welcome_pdf.md`:

- complete backend suite 2766 passed, 52 skipped, 0 errors; `mypy --strict` and `ruff` clean in
  every gate scope (ingestion: 26 files); `make seed`, contract drift, frontend checks and the
  required Playwright gate checks pass; the schema-3 database still migrates to 4 without losing rows;
- the CLI path (upload, snapshot, scripted FI2 extraction, inspect, validated approval, SQLite
  reopen in a new process, deterministic bundle, read-only dry-run) was re-run on the combined tree
  with a synthetic fixture: dry-run `would_update`, `kb_constructs: true`, seeds unchanged;
- the loopback review app was run in a real browser. That found a defect the earlier acceptance
  could not: `Referrer-Policy: no-referrer` made browsers send `Origin: null` on the app's own form
  POSTs, which the strict origin check refuses, so login and decisions returned `403`. The policy is
  now `same-origin` (allowlist unchanged), with HTTP-level regressions in
  `evals/test_fi3_review_http.py`; before this the web app had no HTTP-level test. The browser
  approval was read back from SQLite in a separate process. The browser run was manual and covered
  login, queue, proposal inspection and approve only.

Still open and unchanged: local-shell curator model, manual-capture provenance policy, no-expiry
approvals, the chunked-body limit, and FI5 application semantics. FI3 remains an offline operator
tool with no KB apply.

## Real-capture pilot (2026-10-31)

Branch `claude/fi3-real-capture-pilot` (base `main` `8d805e3`). A real manual capture of the HDFC
Infinia product page was run through the operator workflow with a named curator (`himanshu`):
two proposals, the `hdfc-infinia` card row (three evidenced fields) and its portal point valuation
`infinia-portal-val` (one), both approved. No page text is stored in the repository; the data
lives outside it (`~/tripwise-ingestion-data/fi3`). The run exposed four defects, fixed here
test-first against the corrected design (`codex/fi3-review-dry-run-plan` @ `ee8ed00`, section 7.1),
which `main`'s FI3 had been built ahead of.

| # | Before | After |
|---|---|---|
| 1 | Bundle `v1` reported `applicable: True` while D1 (row- vs field-level provenance) and D2 (manual-capture trust) are open. | `v2`: `dry_run_consistent` (internal consistency only), `activation_authorized: false`, `unresolved_decisions: ["D1","D2"]`; per entry `evidenced_fields`, `provenance_candidate` (`needs_verification: null`) and `blocked_by` (`D1`; plus `D2` for a manual capture); `new_row.provenance` equals the current row's. A stored v1 bundle dry-runs as `legacy_bundle: true`, never consistent. The web page and JSON say the same. |
| 2 | Dry-run reported `would_update` for entries with no field change. | `confirmed_unchanged`; `would_update` only when a field changes. |
| 3 | `main()` used `env or {}`: `TRIPWISE_ENV=production` and `TRIPWISE_DATA_DIR` were ignored (and `--data-dir` was mandatory). | Defaults to `os.environ`; `--data-dir` is optional; an empty data-dir no longer resolves to the current directory; refusals exit 2 with one line. Proven with real subprocess runs. |
| 4 | Re-running `add-curator` raised a raw `ConflictingWriteError`. | Same curator and name succeeds and keeps the original record; a different name exits 2 with a clear message and no traceback. |

**Pilot result** (new code, real stored data, execution mode: real library and real SQLite, one
manually captured real page, no network, nothing applied):

- The pre-existing stored v1 bundle `4c885c41…` now dry-runs as `legacy_bundle: true`,
  `dry_run_consistent: false`, both entries `confirmed_unchanged` (it had been `would_update`).
- A new v2 bundle `b55a245c580401ff43935f0cf88e40db55e652c12b9d20d079acaf2643c8b267` was built for
  both proposals: `activation_authorized: false`, `unresolved_decisions: ["D1","D2"]`,
  `dry_run_consistent: true`, nothing refused. Both entries: `provenance_candidate`
  `source_type: manual_curation`, `verified_by: himanshu`, `last_verified: 2026-10-31`,
  `confidence: 0.9`, `needs_verification: null`; `blocked_by: ["D1","D2"]`; `field_changes: []`;
  `new_row.provenance` identical to the seed's (still `needs_verification: true`). Evidenced
  fields: card `annual_fee_minor`, `base_earn.points`, `base_earn.per_amount_minor`; valuation
  `value_micro_major_per_point`.
- Dry-run of the v2 bundle, run twice: both entries `confirmed_unchanged`, `kb_constructs: true`,
  `seed_files_unchanged: true`, `dry_run_consistent: true`, and the two outputs are
  **byte-identical** (`cmp`). Rebuilding with the same event id is a byte-identical replay.
- The capture's evidence confirms the values already in the seeds. That is not verification of the
  seed rows: provenance is unchanged, D1 and D2 stay open, and the bundle authorizes nothing.

Not claimed: this is one page and two rows by one curator, not evidence about other issuers;
FI5 application, D1/D2 resolution, and any change to seed data remain out of scope.
