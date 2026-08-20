# Phase I8A.2.1 — Tripadvisor Final Acceptance Closure

Status: OFFLINE DEVELOPMENT COMPLETE — LIVE ACTIVATION PENDING.

Scope: surgical closure of verified I8A.2 acceptance defects only. No live Tripadvisor activation, no frontend redesign, no backend contract expansion, no provider/MCP configuration, no raw Tripadvisor data retention.

## Baseline

- [x] Read `AGENTS.md`, `CLAUDE.md`, `DEVIATIONS.md`, newest report, relevant implementation/provider specs, and Tripadvisor reference note.
- [x] Confirmed `AGENTS.md` and `CLAUDE.md` are byte-identical before editing.
- [x] Fresh pre-edit gate:
  - backend pytest: 571 passed
  - strict backend mypy: clean across 92 source files
  - backend ruff: clean
  - frontend TypeScript: clean

## Task 1 — Fixture/live evidence boundary

- [x] Red: prove sanitized fixture metadata cannot set `status: "live"`.
- [x] Red: prove a non-live transport claiming live evidence fails closed before normalized evidence is emitted.
- [x] Green: restrict fixture metadata status to non-live evidence states and reject invalid metadata as `invalid_response`.
- [x] Green: enforce an adapter/normalizer invariant that `"live"` status is only possible for a live transport.
- [x] Verify focused Tripadvisor adapter tests.

## Task 2 — Honest fixture provenance semantics

- [x] Red: prove fixture replay claims use fixture-review provenance, not provider-live verification.
- [x] Green: separate retrieval/capture time from fixture review provenance and keep replayed evidence `needs_verification=True`.
- [x] Verify stale fixture evidence and normal fixture evidence tests.

## Task 3 — Trusted dynamic registry quota

- [x] Red: prove a fake ledger-like object cannot grant Tripadvisor quota.
- [x] Red: prove non-billable or in-memory ledgers cannot grant live Tripadvisor quota.
- [x] Red: prove an on-disk billable `TripadvisorEntityLedger` reports dynamic quota without rebuilding stale state.
- [x] Green: bind Tripadvisor quota to the real persistent billable ledger only and refresh registry entries before selection/reporting.
- [x] Verify provider registry tests.

## Task 4 — `/places/search` provider resolver path

- [x] Red: prove default API search does not invoke Tripadvisor when disabled.
- [x] Red: prove an explicit test resolver invokes fixture Tripadvisor through registry eligibility and returns provider diagnostics on failure.
- [x] Green: add a typed provider resolver dependency while keeping normal runtime provider map empty/disabled.
- [x] Green: preserve provider IDs in diagnostics from the adapter instead of hardcoding Tripadvisor in the search helper.
- [x] Verify place-search API tests.

## Task 5 — Frontend generated API isolation

- [x] Red: document current generator output collides with stable facade/wrapper files.
- [x] Green: move generated client output to `frontend/src/lib/api/generated/`.
- [x] Green: update hand-maintained wrappers and imports to reference generated files through stable boundaries.
- [x] Verify `npm run gen:api` twice is idempotent and preserves hand-maintained wrappers.
- [x] Verify frontend TypeScript/lint/token gate.

## Task 6 — Documentation reconciliation

- [x] Update previous I8A/I8A.1/I8A.2 plan checkboxes to reflect verified completion state.
- [x] Add final report sections for exact verification commands, acceptance findings closed, disabled live state, offline-only status, and remaining live blockers.
- [x] Update `DEVIATIONS.md` for narrow implementation judgments.
- [x] Keep `AGENTS.md` and `CLAUDE.md` byte-identical if the checkpoint text changes.

## Task 7 — Final verification and review

- [x] Run focused Tripadvisor/place-search tests.
- [x] Run full backend pytest, strict mypy, and ruff gates.
- [x] Run frontend generation, TypeScript, lint, and token gates.
- [x] Verify no golden fixture drift.
- [x] Run targeted secret/configuration scan.
- [x] Request read-only code review with exact base/head commits.
- [x] Address critical/important review findings, rerun relevant gates, and prepare branch handoff.
