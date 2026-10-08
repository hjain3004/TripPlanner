# FI0 — Robust financial ingestion foundation

## Status

FI0 acceptance is pending. The implementation is offline-only and stops at typed contracts, policy-controlled targets, immutable snapshot references, draft proposals, review decisions, re-verification tasks, and SQLite audit storage. Persistence conflict semantics, canonical decision idempotency, genuine two-connection concurrency, and complete negative coverage are implemented; final acceptance is blocked by the seeded repository-wide catalog fixture state described below.

## Delivered

- `backend/ingestion/contracts.py` defines the financial-only discovery candidate, source policy, watch target, fetch request/result/failure, fetch attempt, immutable artifact, snapshot, evidence span, field proposal, change proposal, validation finding, review decision, and re-verification task contracts.
- `backend/ingestion/policy.py` promotes a candidate only through a curator decision and the selected issuer URL. Discovery hints and claim text cannot enter a proposed row.
- `backend/ingestion/storage.py` persists the ingestion queue in a separate SQLite database with optimistic version checks, idempotent client events, immutable snapshot manifests, typed audit events, and fail-closed lineage checks. It never opens the approved knowledge-base store.
- `backend/ingestion/migrations.py` provides the versioned schema migration seam (schema version 1).
- Draft evidence is represented through the existing evidence graph using `ReferenceFactIdentity(namespace="financial_draft", ...)`, `VERIFY_REQUIRED`, and `needs_verification=True`; no duplicate graph was introduced.
- `Makefile` and `backend/pyproject.toml` include the new package in the strict FI0 gate scope.
- Immutable queue writes are insert-only with typed conflicting-payload errors; proposal decisions use a canonical request fingerprint, version/CAS checks, durable audit events, and SQLite transaction serialization.

## Explicit non-scope

No crawler, Firecrawl/Crawl4AI adapter, PDF parser, browser automation, scheduler, live network call, credential, extraction LLM, review UI, KB activation, `/plan` change, OpenAPI change, frontend change, seed change, or golden-test change was made.

## Verification

- Focused FI0 tests: **17 passed**.
- FI0 ruff: **passed**.
- FI0 strict mypy: **passed**.
- `git diff --check`: **passed**.
- `make seed` succeeded when the existing backend virtualenv was placed on `PATH`; the unmodified Makefile command first failed because this shell has no `python` executable on `PATH`.
- The seeded full backend suite collected **1,251 tests** and completed with **1,224 passed, 19 failed, 8 skipped**. All 19 failures are catalog-fixture failures: regional retrieval/search tests see no BOM/DXB/NYC/LON/PAR active artifacts, SIN has only the four seed POIs where the test requires at least eight, and recompute tests cannot open `catalogs/active_lon-core.json`. Root cause is confirmed: `make seed` creates the 42-row kernel database, while these acceptance tests require active catalog artifacts that are neither tracked nor provisioned by `make seed` in this worktree. No FI0 code is on those stacks.
- Exact committed-tree `make gate` result: **exit 1** at the full pytest phase with the same **1,224 passed, 19 failed, 8 skipped** result; mypy, ruff, frozen-artifact checks, contract checks, and clean-tree checks were not reached because the gate stops on pytest failure. Acceptance remains pending until the pre-existing catalog fixture/provisioning issue is resolved by its owning milestone.

## Commits

- `1547589` — `feat(fi0): harden financial ingestion persistence`
- `51dd1b6` — `docs(fi0): record acceptance verification`
- `9ac4818` — `fix(fi0): preserve existing gate command contracts`

## Review notes

The ingestion database is intentionally separate from the core KB database. The contracts carry evidence references and lineage, but no fetch result can contain a proposed row and no storage method writes approved financial facts. Human review is the only transition from a pending proposal to a terminal decision.
