# Implementation Plan: Phase I8A.1 — Tripadvisor Offline Adapter Hardening

**Milestone:** Phase I8A.1 — Tripadvisor Offline Adapter Hardening
**Target Date:** 2026-08-17
**Branch:** `feat/i8a-tripadvisor-offline-adapter`
**Current Status:** OFFLINE DEVELOPMENT COMPLETE — LIVE ACTIVATION PENDING

---

## 1. Executive Summary & Review Findings

This plan addresses all 8 findings from the architectural code review of Phase I8A:
1. **Unsafe Entity Ledger**: Replace naive count-based in-memory default with a persistent, unique-call-identity (`call_id`), atomic SQLite two-phase reservation/reconciliation ledger (`reserve`, `reconcile`, `release`). Require persistent SQLite path for live/billable transports, prevent in-memory defaults on live paths, fail closed on conflicting reconciliations and unexpected actual-count overages.
2. **Evidence Status Transport-Derived**: Eliminate caller-controlled `is_live` boolean on `TripadvisorTerraAdapter`. Transport class itself dictates whether results are `cached`/`estimated` with `needs_verification=True` or `live`. Fixture transports can never produce `live`.
3. **Send Actual Venue Query to Provider**: Pass validated free-text query, city/destination constraint, category filters, and bounded limits from `search_catalog_places` to the gateway place search request and transport.
4. **Preserve Missing Coordinates and Provenance End-to-End**: Ensure missing coordinates remain `None` (never `0.0, 0.0` or synthetic coords); propagate `needs_verification`, `last_verified`, `licence_id`, and `attribution_requirements` honestly from claims.
5. **Complete Offline Security Envelope**: Enforce `MAX_RESPONSE_BYTES` before parsing, bounded timeouts, max result counts, secret redactions (`redact_secret()`), kill switch check before invocation, and typed RFC 7807 error mappings via an offline fake MCP client boundary without sockets.
6. **Exercise Every Advertised Fixture**: Implement test cases covering all 16 fixtures in `gateway/places/fixtures/tripadvisor/` (success, details, exact lookup, empty, partial, missing coords, missing optional, malformed, unknown category, duplicate IDs, stale timestamps, 401, 403, 429, 500, hostile prompt injection, large paginated responses).
7. **Repair Orchestration and Fallback Honesty**: Connect provider registry quota dynamically to the ledger, ensure disabled provider is never selected by default, verify fail-soft fallback with observable diagnostics when provider fails/exhausts budget.
8. **Complete Milestone Documentation**: Update `reports/itinerary_i8a_tripadvisor_offline_adapter.md`, `DEVIATIONS.md`, and synchronize byte-identical `AGENTS.md` and `CLAUDE.md`.

---

## 2. Test-First Implementation Tasks

### Task 1: Persistent, Reservation-Identity-Based Safety Ledger
- [x] Define `TripadvisorEntityLedger` in `backend/gateway/places/adapters/tripadvisor/budget.py`:
  - `__init__(db_path: Path | str | None = None, is_billable: bool = False)`: Enforces that if `is_billable=True`, `db_path` MUST NOT be `None` or `":memory:"`.
  - Schema:
    - `entity_budget_state(id=1, consumed_entities, reserved_entities, last_updated)`
    - `call_reservations(call_id PRIMARY KEY, expected_max INTEGER, actual_consumed INTEGER, status TEXT, created_at TEXT, updated_at TEXT)`
    - `entity_audit_log(id, timestamp, action, call_id, count, new_consumed, new_reserved)`
  - Methods:
    - `reserve(expected_max_entities: int, call_id: str) -> bool`: Idempotent for same `call_id` and count; raises on conflicting count. Uses `BEGIN IMMEDIATE`.
    - `reconcile(call_id: str, actual_entities: int) -> None`: Idempotent for same `call_id` and actual count; raises on conflicting count or unknown `call_id`. If `actual_entities > expected_max`, records actual consumption conservatively and fails closed with `TripadvisorBudgetExhaustedError`.
    - `release(call_id: str) -> None`: Releases reservation if pending.
    - `get_status() -> dict[str, int]`: Returns consumed, reserved, remaining.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test persistence across instances on disk.
  - Test separate SQLite connections / instances sharing one DB file.
  - Test multi-threaded atomic concurrency across separate connections.
  - Test unique call settlement and release.
  - Test idempotent reconcile and release.
  - Test conflicting reconcile raises error.
  - Test one call cannot release another call.
  - Test restart with pending reservation remains reserved.
  - Test exact 900 boundary and 901 rejection.
  - Test unexpected actual > reservation fails closed and records exposure.
  - Test default billable constructor rejects in-memory DB.

### Task 2: Transport-Derived Evidence Status
- [x] In `backend/gateway/places/adapters/tripadvisor/transport.py`:
  - Add `is_live: bool` property to `TripadvisorTransport` protocol.
- [x] In `backend/gateway/places/adapters/tripadvisor/fixture_transport.py`:
  - `is_live = False` (strictly cached/estimated).
- [x] In `backend/gateway/places/adapters/tripadvisor/live_transport.py`:
  - `is_live = True` (when active).
- [x] In `backend/gateway/places/adapters/tripadvisor/adapter.py`:
  - Remove `is_live` from `TripadvisorTerraAdapter.__init__`. Derive status from `self.transport.is_live`.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test that fixture evidence cannot be labelled live through constructor args.

### Task 3: Typed Venue Query and Geographic Constraints
- [x] In `backend/gateway/places/contracts.py`:
  - Add `query: str | None = None` to `PlaceSearchRequest`.
- [x] In `backend/gateway/places/adapters/tripadvisor/transport.py`:
  - Update `search_locations(query: str, destination: str | None = None, category: str | None = None, limit: int = 10)`.
- [x] In `backend/gateway/places/adapters/tripadvisor/adapter.py`:
  - Pass `query=request.query or request.destination_area_id or "places"`, `destination=request.destination_area_id`, `category=...`, `limit=...`.
- [x] In `backend/agents/search.py`:
  - Pass `query=request.query` to `GatewayPlaceSearchRequest`.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test venue query propagation (e.g. `Lau Pa Sat`).
  - Test geographic scoping.
  - Test empty query behavior.
  - Test category bounds propagation.

### Task 4: Missing Coordinates and Provenance Preservation
- [x] In `backend/core/models.py`:
  - Update `POI.lat: float | None = None` and `POI.lon: float | None = None`.
- [x] In `backend/agents/retrieval.py` and `backend/agents/search.py`:
  - Ensure missing coordinates remain `None`.
  - Preserve `needs_verification=True` when candidate is `cached` or claims require verification.
  - Propagate `last_verified`, `licence_id`, and `attribution_requirements` from normalized claims.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py` and `backend/evals/test_places_search.py`:
  - Test missing coordinates remain `None` through API and mapping.
  - Test no `0.0, 0.0` coords.
  - Test `needs_verification=True` preservation on cached items.

### Task 5: Security Envelope & Fake MCP Client Boundary
- [x] In `backend/gateway/places/adapters/tripadvisor/live_transport.py`:
  - Injected client protocol (`TripadvisorClientProtocol` / `FakeMcpClient`).
  - Enforce `MAX_RESPONSE_BYTES` (512 KB), timeouts, max result counts (50).
  - Enforce kill-switch and disabled checks.
  - Enforce secret redaction in all exceptions and logs.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`:
  - Test disabled activation invokes client 0 times.
  - Test kill-switch invokes client 0 times.
  - Test unallowlisted tool rejection.
  - Test payload size limit enforcement.
  - Test timeout and RFC 7807 error codes.
  - Test secret redaction.

### Task 6: Fixture Suite Full Coverage
- [x] Review and test all 16 fixtures in `backend/gateway/places/fixtures/tripadvisor/`.
- [x] Ensure `stale_evidence.json` has realistic timestamps and is verified.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py` for each fixture.

### Task 7: Orchestration, Dynamic Quota & Fail-Soft Fallback
- [x] In `backend/gateway/places/registry.py`:
  - Dynamic `remaining_quota` derived from ledger state if ledger is provided.
- [x] In `backend/agents/search.py`:
  - Fail-soft fallback returns local snapshot/KB candidates on provider failure with diagnostic metadata.
- [x] Tests in `backend/evals/test_tripadvisor_adapter.py`.

### Task 8: Verification Gate & Milestone Documentation
- [x] Run full test suite, strict mypy, ruff, golden checks, and socket isolation checks.
- [x] Update `reports/itinerary_i8a_tripadvisor_offline_adapter.md`.
- [x] Update `DEVIATIONS.md`.
- [x] Update `AGENTS.md` and `CLAUDE.md` (keep byte-identical).
