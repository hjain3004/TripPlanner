# FI0 — Robust financial ingestion foundation

## Status

FI0 acceptance is complete. The implementation is offline-only and stops at typed contracts, policy-controlled targets, immutable snapshot references, draft proposals, review decisions, re-verification tasks, and SQLite audit storage in `backend/ingestion/`. Persistence conflict semantics, canonical decision idempotency, genuine two-connection concurrency, and complete negative coverage are implemented and verified. The branch has been reconciled with current `origin/main` (`eccb19885557001fec7a87d5b459998dda646e57`) via a real merge commit. With approved regional catalog artifacts copied into ignored `backend/catalogs/` and the trusted virtualenv linked at `backend/.venv`, the full backend suite passes cleanly with zero regressions.

## Delivered

- `backend/ingestion/contracts.py` defines the financial-only discovery candidate, source policy, watch target, fetch request/result/failure, fetch attempt, immutable artifact, snapshot, evidence span, field proposal, change proposal, validation finding, review decision, and re-verification task contracts.
- `backend/ingestion/policy.py` promotes a candidate only through a curator decision and the selected issuer URL. Discovery hints and claim text cannot enter a proposed row.
- `backend/ingestion/storage.py` persists the ingestion queue in a separate SQLite database with optimistic version checks, idempotent client events, immutable snapshot manifests, typed audit events, and fail-closed lineage checks. It never opens the approved knowledge-base store.
- `backend/ingestion/migrations.py` provides the versioned schema migration seam (schema version 1).
- Draft evidence is represented through the existing evidence graph using `ReferenceFactIdentity(namespace="financial_draft", ...)`, `VERIFY_REQUIRED`, and `needs_verification=True`; no duplicate graph was introduced.
- `Makefile` and `backend/pyproject.toml` include the new package in the strict FI0 gate scope.
- Immutable queue writes are insert-only with typed conflicting-payload errors; proposal decisions use a canonical request fingerprint, version/CAS checks, durable audit events, and SQLite transaction serialization.

## Explicit non-scope

No crawler, Firecrawl/Crawl4AI adapter, PDF parser, browser automation, scheduler, live network call, credential, extraction LLM, review UI, KB activation, `/plan` change, OpenAPI change, frontend change, seed change, or golden-test change was made. FI1 has not been started.

## Verification

- Focused FI0 tests: **17 passed** (`backend/evals/test_fi0_ingestion.py`).
- Full backend pytest suite: **1,283 passed, 1 skipped** (1,266 baseline from main + 17 FI0).
- Strict mypy: **passed across 154 source files** (`core/ accounts/ planning/ agents/ api/ gateway/ ingestion/`).
- Ruff (zero-tolerance scope): **passed** (`accounts/ planning/ agents/ gateway/ evals/ ingestion/`).
- Ruff (core/ + api/ legacy debt): **6 findings (ceiling 12)**.
- Frozen artifacts: **GOLDENS_OK, CONTRACT_OK, BRIEFS_IDENTICAL**.
- Clean working tree: **TREE_CLEAN**.
- Reconciled with `origin/main` (`eccb19885557001fec7a87d5b459998dda646e57`) via merge commit `a1e7e7a`.
- Acceptance criteria verified:
  - Conflicting duplicate source/watch/fetch/snapshot writes: typed `ConflictingWriteError`, insert-only evidence.
  - Audit history cannot be replaced: append-only events, verified via reopen and inspection.
  - Malformed timestamp ordering: validated and rejected.
  - Unsafe URL schemes and redirect/final-URL validation: rejected in contracts.
  - Reverify-task reference and idempotency behavior: validated and tested.
  - Package boundaries: AST tests verify `core/`, `agents/`, `api/` do not import `ingestion/`.
  - Offline-only / no crawler: AST tests verify no network/crawler packages imported, socket connect monkeypatched to fail.
  - Two-connection reviewer race: barrier-synchronized concurrency test confirms exactly one decision succeeds with version/CAS checks.
  - Canonical request identity: `client_event_id` request fingerprinting validated.
- Full `make gate` executed from a clean tree and passed.

## Commits

- `1547589` — `feat(fi0): harden financial ingestion persistence`
- `51dd1b6` — `docs(fi0): record acceptance verification`
- `9ac4818` — `fix(fi0): preserve existing gate command contracts`
- `dc0e968` — `docs(fi0): record final gate outcome`
- `a1e7e7a` — `merge: reconcile FI0 with current origin/main`

## Review notes

The ingestion database is intentionally separate from the core KB database. The contracts carry evidence references and lineage, but no fetch result can contain a proposed row and no storage method writes approved financial facts. Human review is the only transition from a pending proposal to a terminal decision.
