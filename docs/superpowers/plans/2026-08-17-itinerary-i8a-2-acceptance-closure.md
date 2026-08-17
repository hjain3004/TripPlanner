# Implementation Plan: Phase I8A.2 — Tripadvisor Adapter Acceptance Closure

**Milestone:** Phase I8A.2 — Tripadvisor Adapter Acceptance Closure
**Target Date:** 2026-08-17
**Branch:** `feat/i8a-tripadvisor-offline-adapter`
**Current Status:** OFFLINE DEVELOPMENT COMPLETE — LIVE ACTIVATION PENDING

---

## 1. Executive Summary & Acceptance Blockers

This plan addresses the final acceptance findings identified during code review of Phase I8A.1:
1. **Live Transport Ledger Requirement**: Prohibit in-memory ledgers when `transport.is_live=True`. `TripadvisorTerraAdapter` must require an explicit, persistent, on-disk SQLite path in verified billable mode (`is_billable=True`). Reject omitted, in-memory, non-billable, or unverified ledgers.
2. **True Exposure Accounting & Conservative Post-Dispatch Policy**:
   - Store full actual consumption even when it exceeds 900 (e.g. 895 + 10 = 905). Never clamp `new_consumed` to 900.
   - Set `remaining = max(0, limit - consumed - reserved)`.
   - Add persistent exhausted/overage state where future reservations fail closed.
   - Record overage amount and actual consumption in audit log.
   - Define conservative post-dispatch failure accounting: post-dispatch failures (timeout, malformed payload) do not silently restore quota; they conservatively settle reserved entities to prevent financial undercounting.
3. **Complete Exception Secret Scrubbing**:
   - Scrub `BaseException.args`, `str(exc)`, `repr(exc)`, and suppressed exception chains across all client errors and RFC 7807 problem payloads so credentials never leak.
4. **Dynamic Ledger-Backed Registry Quota**:
   - Remove arbitrary integer `remaining_quota` argument from `get_default_place_registry()`.
   - Bind quota dynamically to configured `TripadvisorEntityLedger`. When no ledger is configured, Tripadvisor reports 0 remaining and remains ineligible.
5. **Preserve Provider Diagnostics in Search**:
   - In `search_catalog_places()`, catch typed provider failures (`PlaceGatewayError`, `PartialPlaceResult`) and attach safe, non-sensitive diagnostic records to response/context without leaking secrets or crashing.
6. **Separate Synthetic Fixture Metadata from Wire Schema**:
   - Remove `last_updated_time` from native `TripadvisorLocation` wire model.
   - Introduce internal fixture envelope (`FixtureEvidenceEnvelope`) carrying capture timestamp, status (`stale`, `cached`, `estimated`), and verification metadata outside the provider wire model.
7. **Complete Milestone Documentation & Acceptance Closure**:
   - Reconcile I8A.1 plan checklist and write full documentation in `reports/itinerary_i8a_tripadvisor_offline_adapter.md`.

---

## 2. Test-First Implementation Tasks

### Task 1: Enforce Persistent Billable Ledger for Live Transports
- [x] In `backend/gateway/places/adapters/tripadvisor/adapter.py`:
  - When `self.transport.is_live is True`:
    - Require `ledger` argument to be explicitly supplied (cannot be None).
    - Require `ledger.is_billable is True`.
    - Require `ledger.is_in_memory is False` and `ledger.db_path` is a verified on-disk file.
    - If any condition fails, raise `ValueError("Live Tripadvisor transport requires an explicitly supplied, verified persistent billable ledger on disk")`.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test live transport + omitted ledger is rejected with `ValueError`.
  - Test live transport + in-memory ledger is rejected with `ValueError`.
  - Test live transport + persistent non-billable ledger is rejected with `ValueError`.
  - Test live transport + persistent billable ledger + fake client succeeds offline.
  - Test fixture transport + in-memory non-billable ledger succeeds.

### Task 2: True Exposure Accounting & Conservative Post-Dispatch Policy
- [x] In `backend/gateway/places/adapters/tripadvisor/budget.py`:
  - Update `reconcile()`: `new_consumed = consumed + actual_entities` (no clamping to 900).
  - Update `get_status()`: `remaining = max(0, self.LIFETIME_LIMIT - (consumed + reserved))`.
  - Check in `reserve()`: if `consumed >= self.LIFETIME_LIMIT`, return `False` (exhausted state).
  - Store `overage_amount = max(0, actual_entities - expected_max)` in `call_reservations` and `entity_audit_log`.
  - Commit transaction before raising `TripadvisorBudgetExhaustedError` so overage state persists across restarts.
  - Implement conservative post-dispatch failure policy: define `settle_ambiguous_failure(call_id: str)` to settle the reservation as consumed when provider state is unknown.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test reproduction: 895 consumed + 5 reserved + 10 reconciled -> records 905 consumed, 0 remaining.
  - Test future reservations fail when consumed >= 900.
  - Test restart preserves 905 consumed count and exhausted state.
  - Test audit log captures exact overage amount.
  - Test ambiguous post-dispatch failure conservatively settles reservation.

### Task 3: Exception Secret Scrubbing Across `args`, `str()`, `repr()`
- [x] In `backend/gateway/places/adapters/tripadvisor/live_transport.py`:
  - Create safe exception factory / custom `PlaceGatewayError` subclass that scrubs `self.args` as well as `.message`.
  - Suppress exception chaining with `from None` or sanitized inner cause to prevent leaking raw auth in `__cause__` or traceback.
  - Map RFC 7807 detail fields to generic error messages without echoing untrusted provider detail.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test API key in RFC 7807 detail is scrubbed from `exc.message`, `str(exc)`, `repr(exc)`, and `exc.args`.
  - Test Bearer token in client failure is scrubbed from `str(exc)` and `exc.args`.
  - Test Authorization header in traceback/cause is suppressed.

### Task 4: Dynamic Ledger-Backed Registry Quota
- [x] In `backend/gateway/places/registry.py`:
  - Remove arbitrary `remaining_quota` integer from `get_default_place_registry()`.
  - Support `get_default_place_registry(ledger: TripadvisorEntityLedger | None = None)`.
  - If `ledger is None`, set `remaining_quota=0`, `enabled=False`.
  - If `ledger` is provided, evaluate `ledger.get_status()["remaining"]` dynamically.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test registry without ledger reports 0 quota and is ineligible.
  - Test registry with ledger reports true dynamic remaining quota.
  - Test registry quota updates after reservations and reconciliations.

### Task 5: Preserve Provider Diagnostics in Place Search
- [x] In `backend/gateway/places/contracts.py` & `backend/agents/search.py`:
  - Add optional `diagnostics: list[ProviderDiagnostic]` to `PlaceSearchResponse` or capture in retrieval context.
  - Catch `PlaceGatewayError` and `PartialPlaceResult` explicitly in `search_catalog_places()` and record safe diagnostic record (provider_id, error_code, stop_reason, fallback_used=True).
  - Unexpected exceptions captured as safe internal diagnostic without leaking trace details or secrets.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py` & `backend/evals/test_places_search.py`:
  - Test search fallback returns local results plus safe diagnostic on timeout, 429, 500, budget exhaustion.
  - Test diagnostic contains zero secrets or raw headers.

### Task 6: Separate Synthetic Fixture Metadata from Wire Schema
- [x] In `backend/gateway/places/adapters/tripadvisor/contracts.py`:
  - Remove `last_updated_time` from `TripadvisorLocation`.
- [x] In `backend/gateway/places/adapters/tripadvisor/fixture_transport.py`:
  - Introduce `FixtureEvidenceEnvelope` handling capture timestamp, fixture status (`stale`, `cached`, `estimated`), and verification dates.
  - Parse `_metadata` or fixture-specific envelope headers outside the provider wire model.
- [x] In `backend/gateway/places/adapters/tripadvisor/normalize.py`:
  - Accept optional `evidence_status: str | None` and `capture_dt: datetime | None` in `normalize_tripadvisor_location()`.
- [x] Update `backend/gateway/places/fixtures/tripadvisor/stale_evidence.json` to store freshness metadata in envelope `_metadata`.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test `TripadvisorLocation` rejects/ignores wire timestamp fields.
  - Test stale fixture resolves to `status="stale"` via envelope metadata.
  - Test missing coordinates remain `None`.

### Task 7: Complete Milestone Documentation & Gate Verification
- [x] Update `DEVIATIONS.md` with I8A.2 decisions (conservative post-dispatch failure accounting, envelope separation).
- [x] Update `reports/itinerary_i8a_tripadvisor_offline_adapter.md` with all required report sections.
- [x] Update `AGENTS.md` and `CLAUDE.md` (keep byte-identical).
- [x] Run full gate: `pytest -q`, strict mypy across 92 files, ruff zero-tolerance, socket guard, and contract checks.
