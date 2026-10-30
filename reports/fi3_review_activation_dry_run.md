# FI3 — Human review and activation dry-run

Status: ACCEPTANCE PENDING — offline operator workflow and independent review are complete;
the required full checks and exact clean-tree gate remain outstanding. Live financial
activation remains out of scope.

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
