# Phase I8A: Offline-First Tripadvisor Terra Adapter Development Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

## Overview & Goal

Implement an offline-first, test-replay-backed Tripadvisor Terra place adapter (`TripadvisorTerraAdapter`) and security envelope behind the existing `PlaceProviderAdapter` gateway protocol.

All live access is disabled by default; billing/account activation remains incomplete, so live transport validation is deferred. Development, normalization, entity accounting, threat modeling, and testing proceed entirely against typed, sanitized recorded fixtures.

## Architectural Invariants & Non-Negotiables

1. **USD 0 out-of-pocket ceiling**: Zero credentials required for offline tests; zero network requests in CI.
2. **Deterministic safety budget**: Application-side lifetime ceiling of **900 entities** managed via atomic SQLite ledger.
3. **No LLM money math or raw tool access**: The LLM never sees raw Tripadvisor tools or selects providers. It uses the typed `search_places` workflow only.
4. **Zero runtime scraping**: No arbitrary URL fetching or unverified endpoint querying.
5. **Gateway isolation**: `backend/core/` never imports Tripadvisor or gateway code.
6. **Provenance & honesty**: Fixture evidence is marked `cached` or `estimated` with `needs_verification=True` and is never labelled `live`.
7. **Fail-soft local fallback**: Failure, rate limits, or budget exhaustion fall back to local snapshot/KB catalog seamlessly.

---

## Tasks

### Task 1: Freeze Transport and Adapter Boundaries
- [x] Create `backend/gateway/places/adapters/tripadvisor/` module.
- [x] Define `TripadvisorTransport` protocol in `backend/gateway/places/adapters/tripadvisor/transport.py`.
- [x] Define native typed schemas in `backend/gateway/places/adapters/tripadvisor/contracts.py` based on `TripAdvisorAPI.md`.
- [x] Create `TripadvisorTerraAdapter` in `backend/gateway/places/adapters/tripadvisor/adapter.py` implementing `PlaceProviderAdapter`.
- [x] Commit message: `feat(gateway): define tripadvisor transport protocol and adapter boundary`

### Task 2: Build Sanitized Recorded Fixtures and Fixture Transport
- [x] Create fixtures directory: `backend/gateway/places/fixtures/tripadvisor/`.
- [x] Create sanitized synthetic JSON fixtures:
  - `search_locations_success.json`
  - `location_details_success.json`
  - `location_lookup_exact.json`
  - `empty_search.json`
  - `partial_result.json`
  - `missing_optional_fields.json`
  - `malformed_response.json`
  - `unknown_category.json`
  - `duplicated_entity.json`
  - `stale_evidence.json`
  - `error_401_unauthorized.json`
  - `error_403_forbidden.json`
  - `error_429_rate_limit.json`
  - `error_500_server_error.json`
  - `hostile_prompt_injection.json`
  - `large_response.json`
  - `manifest.yaml` documenting provenance, redaction, and schema sources.
- [x] Implement `FixtureTripadvisorTransport` in `backend/gateway/places/adapters/tripadvisor/fixture_transport.py`.
- [x] Commit message: `feat(gateway): add tripadvisor recorded fixtures and fixture transport`

### Task 3: Normalization and Prompt Sanitization
- [x] Implement pure normalizer in `backend/gateway/places/adapters/tripadvisor/normalize.py`:
  - Maps native responses into `PlaceCandidate`, `PlaceClaim`, `ExternalId(namespace="tripadvisor", ...)`.
  - Category mapping (`RESTAURANT` -> `food`, `ATTRACTION` -> `attractions`, `HOTEL` -> `hotel`, fallback -> `other`).
  - Coordinates mapping (only genuine coordinates; missing remains missing).
  - Ratings & reviews (only if supplied; missing ratings omitted, not 0).
  - Robust prompt-injection sanitization (`_sanitize_text`) to strip instruction injections.
  - Provenance attribution (`licence_id="tripadvisor-discover"`, `needs_verification=True`, `status="cached"`).
- [x] Commit message: `feat(gateway): implement tripadvisor normalization and sanitization`

### Task 4: Static MCP Allowlist and Security Envelope
- [x] Implement `LiveTripadvisorMcpTransport` in `backend/gateway/places/adapters/tripadvisor/live_transport.py` (structural, disabled by default, fails closed without credentials/activation).
- [x] Enforce static tool allowlist: `["search_locations", "get_location_details", "get_catalog_location"]`.
- [x] Add secret redaction utilities and max payload size limits.
- [x] Commit message: `feat(gateway): add tripadvisor live mcp transport stub with security envelope`

### Task 5: Persistent Lifetime Entity Safety Ledger
- [x] Implement `TripadvisorEntityLedger` in `backend/gateway/places/adapters/tripadvisor/budget.py`:
  - Persistent SQLite storage with atomic reservations.
  - Lifetime hard ceiling of 900 entities.
  - Atomic `reserve(count)`, `commit(actual)`, `rollback(reserved)` methods.
  - Audit logging of reservation and usage events without sensitive content.
  - Test-only in-memory reset method.
- [x] Commit message: `feat(gateway): implement tripadvisor persistent entity budget ledger`

### Task 6: Provider Registry Integration
- [x] Update `backend/gateway/places/registry.py` with `tripadvisor_terra` provider entry:
  - `provider_id="tripadvisor_terra"`, `enabled=False` by default, `allowed_profiles=["student_noncommercial"]`.
  - Capability domains `["poi"]`, supported countries `["SG", "IN", "AE", "US", "GB", "FR"]`.
  - Licence manifest reporting with `tripadvisor-discover` licence ID.
- [x] Commit message: `feat(gateway): register tripadvisor adapter in place provider registry`

### Task 7: Orchestration & Fallback Behavior
- [x] Ensure `search_catalog_places` or planner discovery gracefully uses Tripadvisor when enabled, falling back to snapshot catalog on failure or budget exhaustion.
- [x] Commit message: `feat(gateway): wire tripadvisor fallback into place discovery`

### Task 8: Comprehensive Test Suite & Mutation Tests
- [x] Create `backend/evals/test_tripadvisor_adapter.py`:
  - Test fixture search, lookup, details, and missing fields.
  - Test prompt injection defense.
  - Test malformed responses, errors, timeouts, rate limits.
  - Test budget ledger: reservation, exhaustion at 900, atomic concurrency, restart persistence.
  - Test secret redaction.
  - Mutation/teeth tests: unallowlisted tool attempt, budget ceiling bypass, socket layer blocking assertion.
- [x] Commit message: `test(gateway): add tripadvisor adapter and security test suite`

### Task 9: Documentation, Threat Model & Milestone Report
- [x] Author `reports/itinerary_i8a_tripadvisor_offline_adapter.md`.
- [x] Include threat model, licence/terms record, fixture manifest, and activation checklist.
- [x] Status: `OFFLINE DEVELOPMENT COMPLETE — LIVE ACTIVATION PENDING`.
- [x] Commit message: `docs(reports): author itinerary i8a tripadvisor offline adapter report`
