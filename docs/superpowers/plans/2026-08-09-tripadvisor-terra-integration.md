# Tripadvisor Terra Integration (Itinerary Phase I8) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## DO NOT EXECUTE — precondition gate

**This plan is not runnable today (2026-08-09).** Tripadvisor Terra is Phase I8 of
`docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md` §14. Per that design's
dependency chain (§15), I8 sits behind I0 → I1 → I2 → (I3, I4) → I5 → I6 → I7. The task that
authorized writing this plan set a reduced floor of **I0 and I2 at minimum**; this plan follows
that floor, not the full chain, but `reports/tripadvisor_terra_preflight.md` records the
full-chain caveat for whoever picks this up.

Before starting Task 1, an implementing agent **must** re-run this exact check and confirm both
pass, because state may have changed since this plan was written:

```bash
# Gate I0 — must all be true
ls reports/itinerary_i0_evidence_hardening.md                    # must exist
ls backend/gateway/evidence/identity.py                          # must exist (I0 Task 3)
grep -q "class SqliteEvidenceStore" backend/gateway/evidence/store.py  # I0 Task 5 landed
cd backend && .venv/bin/pytest evals/test_evidence_boundary.py -q     # I0 Task 7 boundary tests exist and pass
cd backend && .venv/bin/pytest -q                                # floor >= 133, must not regress
cd backend && .venv/bin/mypy --strict gateway/ agents/ api/ core/

# Gate I2 — must all be true
grep -rl "class SamplePlaceAdapter" backend --include="*.py"
grep -rl "class PlaceSearchRequest" backend --include="*.py"
grep -rl "ProviderRegistry\|provider_registry" backend --include="*.py"
```

As of this writing: **none of these pass.** `reports/itinerary_i0_evidence_hardening.md` does not
exist, `backend/gateway/evidence/identity.py` does not exist, and no `Place`, `PlaceSearchRequest`,
`SamplePlaceAdapter`, or provider registry code exists anywhere under `backend/`. Do not begin
Task 1 until the check above is re-run and passes clean. If it fails, stop and update
`reports/tripadvisor_terra_preflight.md` instead of proceeding.

This plan may be read, reviewed, and revised now. It authorizes nothing at read time — per the
itinerary design's closing line: "Approval of this design authorizes writing plans; it does not
activate a provider, use a credential, or begin a public deployment."

**Goal:** Add a disabled-by-default, REST-transport Tripadvisor Terra adapter behind the I2 place
gateway that enriches a bounded shortlist of itinerary stops with factual location data, inside a
hard USD 0 out-of-pocket ceiling enforced by a persistent lifetime entity ledger.

**Architecture:** A typed `TripadvisorTerraAdapter` implements the I2 place-provider adapter
protocol (the POI analogue of spec 16 §6's `TravelProviderAdapter`). It is registered
disabled-by-default in the I2 provider registry. All wire parsing tolerates additive Tripadvisor
schema changes (`extra="ignore"`, unknown enums mapped to `UNKNOWN`); all internal contracts
(`PlaceCandidate` and friends, from I2) stay strict. A `TripadvisorEntityLedger` reserves entities
atomically before every call against a persistent SQLite lifetime cap (default 900) that never
auto-resets, and reconciles after the response. `SamplePlaceAdapter` (I2) is the fallback whenever
the adapter is disabled, the ledger is exhausted, or the call fails.

**Tech stack:** Python 3.11+, Pydantic v2, `httpx` (or the project's existing HTTP client — confirm
against what I2's other adapters use; do not introduce a second HTTP library), stdlib `sqlite3`,
pytest, `respx` or `httpx.MockTransport` for fixture-based HTTP tests, mypy strict, Ruff. No live
network in normal tests.

## Global Constraints

- **USD 0 out of pocket, always.** `PlanBudget.max_cost_minor` stays `0`. Positive external spend
  fails closed. (CLAUDE.md "Build order"; itinerary design §2, §9.)
- **The deterministic kernel never touches the web.** This adapter lives entirely under
  `backend/gateway/`; `backend/core/` must never import it. (CLAUDE.md non-negotiable #2; spec 16
  §18 G1 gate line "`backend/core/` has no gateway/provider imports.")
- **Every fact carries provenance.** Every normalized place claim carries `source_url`,
  `retrieved_at`, `last_verified`, `verified_by`, `needs_verification`, `confidence`. (CLAUDE.md
  non-negotiable #3; itinerary design §5.2.)
- **Agents propose, humans approve.** No autonomous write of Tripadvisor content into the approved
  financial knowledge base, ever. (CLAUDE.md non-negotiable #4.)
- **No LLM sees raw provider tools, the credential, or arbitrary URLs.** The model only ever sees
  the first-party `search_places` tool result already defined by I2/I5; Tripadvisor's own schema
  and endpoints never enter model context. (Itinerary design §4, §9 "Binding rules.")
- **Installation ≠ activation.** Registering the Tripadvisor developer MCP endpoint
  (`https://docs.terra.tripadvisor.com/mcp`) in an editor or connecting to it for documentation
  purposes never enables the runtime adapter. (Task instructions; itinerary design §9.)
- **Read-only only.** No booking, reservation, allowlist-write, or purchase endpoint is ever
  called. (Spec 16 §9 "Binding rules"; task instructions.)
- **`docs/specs/` is read-only during implementation.** This plan touches `docs/superpowers/`,
  `docs/providers/`, `backend/`, `reports/`, and `DEVIATIONS.md` only.
- **Behavior and cleanup are separate commits.** No unrelated refactor rides in this branch.
- **Golden fixtures are immutable.** `git diff --exit-code -- backend/evals/golden/` must stay
  empty through every task.

---

## Task 0 — Confirm preconditions and reserve the branch

**Files:** none (verification only)

- [ ] **Step 1:** Run the precondition gate block at the top of this document. Both Gate I0 and
  Gate I2 checks must pass with the stated evidence (files exist, tests pass, floor holds).
- [ ] **Step 2:** If either gate fails, stop. Update `reports/tripadvisor_terra_preflight.md` with
  the current failure detail and do not proceed to Task 1.
- [ ] **Step 3:** If both gates pass, create an isolated worktree per
  `superpowers:using-git-worktrees` on a fresh branch, e.g.
  `feat/tripadvisor-terra-adapter`, off the `main` commit where Gate I0/I2 were confirmed passing.
  Record that commit hash in the eventual `reports/tripadvisor_terra_adapter.md`.

---

## Task 1 — Provider research and account/dashboard verification (docs-only commit)

**Purpose:** Confirm the facts this plan currently treats as open questions before any code is
written, and relocate the research document per the task's provider-document cleanup requirement.

**Files:**
- Move: `frontend/TripAdvisorAPI.md` → `docs/providers/tripadvisor-terra-reference.md`
- Create: dated preamble at the top of the moved file (see below)
- Modify: `DEVIATIONS.md` (log the relocation and any open verification items)

**Open items a human must verify before Task 3 (the ledger/budget task) can be trusted — do not
guess at these:**

1. **Stable API version.** `frontend/TripAdvisorAPI.md` §3 states versioning is `?version=N`
   per-API, and omitting it returns "latest," which is not deterministic for a pinned integration.
   The task instructions ask to "verify whether `version=2` is correct" — the reference doc as
   currently written does **not** state that `2` is the current stable major version for the
   Catalog/Location endpoints this plan uses. Confirm the actual current version integer against
   the live Terra Dashboard/docs before Task 4, and pin it in the registry entry's config, not as
   a hardcoded literal in adapter code.
2. **Account-level overage prevention.** §4 says Discover-tier daily quota is "further capped
   optionally in Dashboard." §10 describes usage-based billing after a one-time lifetime 1,000
   free entities, then per-entity tiered pricing with **no stated hard `$0` account cap**. A local
   SQLite ledger alone does not satisfy this project's zero-cost requirement if the account can
   still auto-bill past the free allowance. A human must check the Terra Dashboard for a
   mechanically-enforced spend cap (not just a request-count cap) before the adapter is ever
   enabled outside a manually-authorized, budget-tracked smoke test. If no such cap exists,
   the live adapter stays disabled indefinitely and only manually authorized smoke tests within
   the 900-entity ledger ceiling are permitted — never automatic `POST /plan` traffic.
3. **Caching/retention rights beyond the Location ID.** §10 "Commercial Policies" states the
   *only* universal caching exception is the Location ID itself; everything else needs "your own
   signed agreement" review. This project is on the self-service Discover tier with standard
   Master Terms, not a negotiated agreement. Until a human confirms otherwise, this plan treats
   name/coordinate/category claims as **display-only for the current request**, not persistable
   KB facts — see Task 5's retention design.
4. **Dedicated project API key.** A human must create a Tripadvisor Terra Discover-tier account
   and a project-scoped key before any live test. This plan does not request or store one.

**Steps:**

- [ ] **Step 1:** `git mv frontend/TripAdvisorAPI.md docs/providers/tripadvisor-terra-reference.md`.

- [ ] **Step 2:** Prepend a dated preamble stating: this is a research note, not an activation
  record; no adapter is enabled by this document; official docs must be re-checked against the
  live docs/dashboard before implementation; all credential handling is backend-only; installing
  or connecting to the developer MCP endpoint never activates the runtime adapter; raw wire
  parsing is forward-compatible but TripPlanner's normalized models stay strict; rate-limit
  figures must be reconfirmed against the live dashboard; the 1,000 free billable entities are a
  one-time lifetime allowance unless the signed agreement says otherwise; reviews, photos, feeds,
  Agentic Search, and allowlist writes are out of scope for the first runtime slice (cite this
  plan's path).

- [ ] **Step 3:** Log the relocation in `DEVIATIONS.md` under a new "Itinerary I8 — Tripadvisor
  Terra" section: date, doc ref (this plan), question "where does provider research live," decision
  "moved to `docs/providers/`, dated preamble added," rationale "keeps provider research out of
  `frontend/` per repo boundaries; task-mandated relocation," files touched.

- [ ] **Step 4:** Commit:

  ```bash
  git add docs/providers/tripadvisor-terra-reference.md DEVIATIONS.md
  git rm frontend/TripAdvisorAPI.md 2>/dev/null || true
  git commit -m "docs(providers): relocate Tripadvisor Terra reference with dated preamble"
  ```

---

## Task 2 — Registry entry (disabled) and activation record

**Purpose:** Register the adapter per spec 16 §7's format, disabled, before any adapter code
exists. Confirms the I2 registry and activation-profile check accept a new provider without
enabling it.

**Files:**
- Create: `backend/gateway/places/registry_entries/tripadvisor_terra.yaml` (path depends on
  wherever I2 lands its registry storage — confirm the actual location against I2's landed code
  before writing this file; the shape below is fixed regardless of location)
- Create: `docs/providers/tripadvisor-terra-activation-record.md`
- Test: `backend/evals/test_tripadvisor_terra_registry.py`

**Interfaces:**
- Consumes: I2's `ProviderRegistry` load/validate mechanism and `AdapterCapabilities`-shaped model
  (spec 16 §6 defines the flight/hotel/award version; I2 defines the POI-domain equivalent —
  confirm the exact field names against I2's landed module before writing this task's code).
- Produces: a registry row other tasks reference by `provider_id: tripadvisor_terra`.

**Registry entry (values fixed by this plan; adjust only the `terms_version` date and confirmed
API version once Task 1's open items resolve):**

```yaml
provider_id: tripadvisor_terra
enabled: false
active_profile: student_noncommercial
domains: [poi]
transport: direct_api
source_method: official_api
stability: experimental
base_urls: [https://terra.tripadvisor.com/api]
credential_ref: TRIPADVISOR_TERRA_API_KEY
allowed_countries: configured
allowed_use: noncommercial_demo
visibility: local_or_portfolio_demo
terms_version: "reviewed-{{DATE}}"  # set to the date Task 1's dashboard check actually ran
cache_policy:
  allowed: false
  ttl_seconds: 0
retention:
  raw_response_seconds: 0
attribution: "Data provided by Tripadvisor"  # confirm exact required string per Task 1 review
request_budget:
  calls_per_plan: 2
  monthly_cost_minor: 0
  lifetime_entity_ceiling: 900
timeouts:
  connect_seconds: 3
  total_seconds: 12
allowed_endpoints:
  - GET /catalog/locations/search
  - GET /catalog/locations/nearby
  - GET /catalog/locations/{id}
  - GET /locations/{id}
```

`enabled: false` is not a placeholder — it stays `false` through this entire plan. A separate,
explicitly human-approved change flips it, after Task 1's account-level overage question is
answered.

**Activation record (`docs/providers/tripadvisor-terra-activation-record.md`) must walk spec 16
§7's ten-point student-profile checklist explicitly, one heading per point, citing this plan and
`docs/providers/tripadvisor-terra-reference.md` for each answer.** Every one of the ten has a real
answer for this provider (e.g. point 6 "read-only tools/endpoints; booking/payment/transfer tools
disabled" → cite the `allowed_endpoints` list above and Task 4's explicit exclusion list).

- [ ] **Step 1:** Write the registry entry YAML with `enabled: false` as shown above, in whatever
  format/location I2's registry loader expects.
- [ ] **Step 2:** Write failing test `test_registry_rejects_call_when_disabled` — asserts the I2
  registry's adapter-selection function raises/returns a typed "not enabled" result for
  `provider_id="tripadvisor_terra"` given the entry above.
- [ ] **Step 3:** Write `test_registry_active_profile_rejects_commercial_profile` — the entry's
  `active_profile: student_noncommercial` must reject selection under a `commercial_production`
  profile context.
- [ ] **Step 4:** Write the full ten-point activation record.
- [ ] **Step 5:** Run `mypy --strict` over the registry loader and the full backend suite to
  confirm no regression.
- [ ] **Step 6:** Commit:

  ```bash
  git add backend/gateway/places/registry_entries/tripadvisor_terra.yaml \
    docs/providers/tripadvisor-terra-activation-record.md \
    backend/evals/test_tripadvisor_terra_registry.py
  git commit -m "feat(gateway): register disabled Tripadvisor Terra provider entry"
  ```

---

## Task 3 — Persistent zero-cost lifetime entity ledger

**Purpose:** A SQLite-backed ledger that makes it mechanically impossible for this adapter to
exceed a configurable lifetime entity ceiling (default 900, safety margin below the 1,000 lifetime
free allowance), across process restarts, without ever auto-resetting.

**Files:**
- Create: `backend/gateway/places/ledger.py`
- Test: `backend/evals/test_tripadvisor_terra_ledger.py`

**Interfaces:**
- Consumes: nothing from other tasks (self-contained; only stdlib `sqlite3` + Pydantic).
- Produces: `TripadvisorEntityLedger` — consumed by Task 4's adapter.

```python
class LedgerExhausted(Exception):
    """Raised when a reservation would exceed the lifetime ceiling."""

class TripadvisorEntityLedger:
    def __init__(self, db_path: Path, lifetime_ceiling: int = 900) -> None: ...

    def remaining(self) -> int:
        """Lifetime ceiling minus all-time reserved (committed + still-open reservations)."""

    def reserve(self, expected_max_entities: int, *, call_id: str) -> None:
        """
        Atomically check remaining() >= expected_max_entities and record a pending
        reservation of that size under call_id, in one transaction. Raises LedgerExhausted
        if it would exceed the ceiling. Must be safe under concurrent callers (SQLite
        transaction with IMMEDIATE locking, or an equivalent atomic check-and-increment).
        """

    def reconcile(self, call_id: str, actual_entities: int) -> None:
        """
        Converts the pending reservation for call_id into a committed entry of
        actual_entities (which may be less than the reservation — excess reserved headroom
        is released, never carried over as a bonus). Idempotent for the same value;
        reconciling with a different value raises.
        """

    def release(self, call_id: str) -> None:
        """Releases a pending reservation entirely (e.g. the HTTP call failed before any
        response body was read) — full refund, no entities charged."""
```

**Steps:**

- [ ] **Step 1:** Write failing tests: `test_remaining_starts_at_lifetime_ceiling`,
  `test_reserve_below_ceiling_succeeds`,
  `test_reserve_exceeding_remaining_raises_and_does_not_mutate_state`,
  `test_reconcile_lower_than_reserved_releases_excess`,
  `test_reconcile_is_idempotent_for_same_value`, `test_reconcile_different_value_raises`,
  `test_release_refunds_full_reservation`,
  `test_ledger_never_auto_resets_between_instantiations` (open, reserve+reconcile, close, reopen a
  new instance against the same `db_path`, assert `remaining()` reflects prior consumption),
  `test_concurrent_reservations_do_not_exceed_ceiling` (N threads each reserving
  `ceiling // N + 1`; assert the total never exceeds the ceiling — use `BEGIN IMMEDIATE`, not a
  naive read-then-write), `test_persistence_across_simulated_process_restart`.

- [ ] **Step 2:** Run red:

  ```bash
  cd backend && .venv/bin/pytest evals/test_tripadvisor_terra_ledger.py -q
  ```

- [ ] **Step 3:** Implement `TripadvisorEntityLedger` using one SQLite table
  `(call_id TEXT PRIMARY KEY, state TEXT CHECK(state IN ('pending','committed','released')),
  entities INTEGER NOT NULL, created_at TEXT NOT NULL)`, with `remaining()` computed as
  `lifetime_ceiling - SUM(entities) WHERE state IN ('pending','committed')`. Use
  `BEGIN IMMEDIATE` transactions for `reserve()`.

- [ ] **Step 4:** Run green, then `mypy --strict backend/gateway/places/ledger.py`.

- [ ] **Step 5:** Commit:

  ```bash
  git add backend/gateway/places/ledger.py backend/evals/test_tripadvisor_terra_ledger.py
  git commit -m "feat(gateway): add persistent zero-cost Tripadvisor entity ledger"
  ```

---

## Task 4 — Wire-tolerant parsing models and the REST adapter

**Purpose:** Implement `TripadvisorTerraAdapter` against the I2 place-provider adapter protocol,
calling only the four allowlisted endpoints, with tolerant wire parsing and strict internal
output.

**Files:**
- Create: `backend/gateway/places/adapters/tripadvisor_terra_wire.py` (raw response models)
- Create: `backend/gateway/places/adapters/tripadvisor_terra.py` (adapter + normalization)
- Test: `backend/evals/test_tripadvisor_terra_adapter.py`
- Create: `backend/evals/fixtures/tripadvisor_terra/*.json` (sanitized, hand-authored from the
  documented schema — do not record real live traffic without Task 1's retention question
  resolved and explicit human authorization)

**Interfaces:**
- Consumes: `TripadvisorEntityLedger` (Task 3); I2's `PlaceSearchRequest`/`PlaceCandidate`/place
  adapter protocol (confirm exact names against I2's landed module — do not invent parallel
  types).
- Produces: `TripadvisorTerraAdapter.search_places(request) -> list[PlaceCandidate]` conforming to
  whatever Protocol I2 defines for place adapters (the POI analogue of spec 16 §6's
  `TravelProviderAdapter`).

**Allowed endpoints (nothing else is ever called):** `GET /catalog/locations/search`,
`GET /catalog/locations/nearby`, `GET /catalog/locations/{id}`, `GET /locations/{id}` (only where
the allowlist permits) — combined, at most 1–2 calls per plan, at most 5 entities per call, no
automatic pagination.

**Explicitly not implemented in this task or any later one without a new plan:** reviews, photos,
`/recommendations/search` (Agentic Search), `/feeds/*`, `/allowlist` writes, hotel
prices/booking/reservations, arbitrary Tripadvisor URLs, model training/fine-tuning, and
consumer-page scraping. Encode this as a hard-coded allowlist the adapter checks before building
any request — not just a comment.

**Wire-tolerant models (`tripadvisor_terra_wire.py`):**

```python
class TerraWireBase(BaseModel):
    model_config = ConfigDict(extra="ignore")  # tolerate additive provider fields

class TerraCoordinates(TerraWireBase):
    latitude: float | None = None
    longitude: float | None = None

class TerraCatalogLocation(TerraWireBase):
    id: int
    names: list[dict] = Field(default_factory=list)
    addresses: list[dict] = Field(default_factory=list)
    coordinates: TerraCoordinates | None = None
    overall_rating: dict | None = None
    urls: dict | None = None

class TerraCatalogSearchResponse(TerraWireBase):
    data: list[dict]  # each item is {location, matched_value}
    pagination: dict

class TerraProblemDetail(TerraWireBase):
    # RFC 7807 problem+json body
    type: str | None = None
    title: str | None = None
    status: int | None = None
    detail: str | None = None
    instance: str | None = None
    trace_id: str | None = None
```

Model only what the adapter actually normalizes into `PlaceCandidate` fields (id, name, category,
coordinates, address, rating, source URL). Category enum values are treated as untrusted strings
and mapped to an explicit `UNKNOWN` fallback at the normalization boundary, never raised as a
parse error.

**Adapter contract (`tripadvisor_terra.py`):** `TripadvisorTerraAdapter.__init__(api_key, ledger,
http_client, *, max_entities_per_call=5)`; `search_places(request)` must: build a typed query
(never interpolate raw user text into the URL beyond validated param encoding); check
`ledger.remaining() >= max_entities_per_call` and raise a typed `budget_exhausted` error if not
(caller falls back to `SamplePlaceAdapter`, never a paid call); `ledger.reserve(...)`; call the
allowlisted endpoint with the registry's timeouts, redirects disabled, `X-API-Key` header never
logged, `size` capped at `max_entities_per_call`; on success, normalize and
`ledger.reconcile(call_id, actual_entities=len(results))`; on any failure before a full response
body is parsed, `ledger.release(call_id)` then map to a typed error — never leak the raw response
body or headers into an exception message or log.

**Error mapping (from `docs/providers/tripadvisor-terra-reference.md` §9, spec 16 §13's
taxonomy/retry matrix):** 400/Constraint Violation → `invalid_response`, no retry. 401 →
`authentication_failed`, no retry. 403 → `permission_denied`, no retry. 404 → `no_results` (not an
error state for search). 429 → `rate_limited`, one bounded retry honoring `Retry-After` within the
call's own timeout budget. 500 → `provider_unavailable`, one bounded retry with jitter. timeout →
`timeout`, no retry. oversized response / malformed JSON → `invalid_response`, no retry.

- [ ] **Step 1:** Write failing tests covering all of:
  `test_disabled_registry_entry_prevents_adapter_selection`,
  `test_missing_credential_raises_before_any_request`,
  `test_search_places_success_fixture`, `test_search_places_nearby_success_fixture`,
  `test_search_places_empty_result`,
  `test_search_places_tolerates_unknown_additional_fields`,
  `test_search_places_maps_unknown_enum_to_UNKNOWN`,
  `test_search_places_malformed_response_raises_invalid_response`,
  `test_search_places_400_raises_invalid_response_no_retry`,
  `test_search_places_401_raises_authentication_failed_no_retry`,
  `test_search_places_403_raises_permission_denied_no_retry`,
  `test_search_places_429_retries_once_honoring_retry_after`,
  `test_search_places_500_retries_once_then_fails`,
  `test_search_places_timeout_raises_timeout_no_retry`,
  `test_search_places_oversized_response_rejected`,
  `test_search_places_partial_multi_id_response_handled`,
  `test_place_candidate_ids_are_deterministic`,
  `test_normalized_output_carries_full_attribution_and_provenance`,
  `test_no_raw_provider_object_escapes_adapter`,
  `test_api_key_never_appears_in_logs_or_exceptions`,
  `test_no_traveler_pii_in_outbound_request`,
  `test_reviews_photos_agentic_search_allowlist_endpoints_are_rejected`,
  `test_search_places_reserves_and_reconciles_ledger`,
  `test_search_places_releases_ledger_on_http_failure`,
  `test_search_places_skips_call_when_ledger_exhausted_and_falls_back`,
  `test_no_live_network_in_normal_test_run`.

- [ ] **Step 2:** Run red:

  ```bash
  cd backend && .venv/bin/pytest evals/test_tripadvisor_terra_adapter.py -q
  ```

- [ ] **Step 3:** Author sanitized fixtures under `backend/evals/fixtures/tripadvisor_terra/` by
  hand from the documented schema.

- [ ] **Step 4:** Implement the wire models and adapter as specified above.

- [ ] **Step 5:** Run green, then:

  ```bash
  cd backend && .venv/bin/mypy --strict gateway/places/
  cd backend && .venv/bin/ruff check gateway/places/ evals/test_tripadvisor_terra_adapter.py
  ```

- [ ] **Step 6:** Commit:

  ```bash
  git add backend/gateway/places/adapters/ backend/evals/test_tripadvisor_terra_adapter.py \
    backend/evals/fixtures/tripadvisor_terra/
  git commit -m "feat(gateway): implement Tripadvisor Terra REST adapter"
  ```

---

## Task 5 — SamplePlaceAdapter fallback wiring and caching/retention enforcement

**Purpose:** Ensure the disabled/exhausted/failed adapter path always falls through to I2's
`SamplePlaceAdapter`, and that nothing beyond a Location ID and minimal display-only fields is
ever persisted, per Task 1's retention findings.

**Files:**
- Modify: I2's provider-selection orchestration path (exact file depends on I2's landed
  architecture — confirm before editing)
- Test: `backend/evals/test_tripadvisor_terra_fallback.py`

**Steps:**

- [ ] **Step 1:** Write failing tests:
  `test_disabled_adapter_selection_falls_back_to_sample_place_adapter`,
  `test_exhausted_ledger_falls_back_to_sample_place_adapter`,
  `test_adapter_error_falls_back_to_sample_place_adapter_not_a_paid_retry`,
  `test_no_raw_response_persisted_beyond_request_lifetime` (assert nothing under
  `backend/gateway/places/` or the evidence store writes a raw Tripadvisor payload to disk/DB —
  only the normalized `PlaceCandidate` and the Location ID reference persist),
  `test_reviews_and_photos_fields_never_populated_on_normalized_output`.
- [ ] **Step 2:** Run red, wire the fallback into I2's existing selection-order logic (spec 16
  §15, applied to the `poi` domain — no new call site), run green.
- [ ] **Step 3:** `mypy --strict`, commit:

  ```bash
  git commit -m "feat(gateway): wire Tripadvisor fallback and zero-retention enforcement"
  ```

---

## Task 6 — Boundary tests and secret-scan verification

**Files:** Create/extend `backend/evals/test_tripadvisor_terra_boundary.py`

- [ ] **Step 1:** Add an import-scan test asserting `backend/core/**/*.py` never imports anything
  from `backend/gateway/places/`.
- [ ] **Step 2:** Add a test asserting the adapter's `http_client` is always injected, never
  self-constructed with a real transport, across the whole suite (no live network in CI).
- [ ] **Step 3:** Run:

  ```bash
  cd backend && .venv/bin/pytest -q
  cd backend && .venv/bin/mypy --strict core/ agents/ api/ gateway/
  cd backend && .venv/bin/ruff check gateway/places/ evals/test_tripadvisor_terra*.py
  git diff --check
  git diff --exit-code -- backend/evals/golden/
  grep -rn "TRIPADVISOR_TERRA_API_KEY" --include="*.py" backend/ | grep -v "os.environ\|os.getenv\|credential_ref"
  ```

  The last command must return only environment-variable lookup sites, never a literal key value.

- [ ] **Step 4:** Commit.

---

## Task 7 — Manual live smoke test (disabled by default)

**Purpose:** A human-invoked, budget-tracked, read-only script — never part of CI, never
automatic.

**Files:** Create `backend/scripts/tripadvisor_terra_smoke.py`

- [ ] **Step 1:** Write the script requiring an explicit `--i-understand-this-costs-entities` flag
  plus `TRIPADVISOR_TERRA_API_KEY` from the environment. It must call at most one allowlisted
  endpoint returning at most 3 entities; reserve/reconcile against the real
  `TripadvisorEntityLedger`; print only counts and redacted metadata (Location ID, category,
  whether coordinates were present) — never raw content, never the key; exit non-zero and print
  the remaining ledger balance if already exhausted, without attempting the call.
- [ ] **Step 2:** Confirm it is excluded from `pytest` collection (`backend/scripts/`, no `test_`
  prefix).
- [ ] **Step 3:** Do not run it as part of this plan's own execution — running it requires a human
  to have completed Task 1's account setup and to explicitly say go. Document "available, not run"
  in Task 8's report unless a human runs it and reports results back.
- [ ] **Step 4:** Commit.

---

## Task 8 — Final verification report

**Files:**
- Create: `reports/tripadvisor_terra_adapter.md`
- Modify: `DEVIATIONS.md` (any judgment calls from Tasks 1–7)
- Modify: `AGENTS.md` and `CLAUDE.md` (identical checkpoint bullet, proved with `cmp`)

- [ ] **Step 1:** Run the full Task 6 verification block from a clean working tree and quote the
  actual output in the report — not a paraphrase.
- [ ] **Step 2:** Report must state explicitly: what was implemented; MCP vs REST transport
  decision and why (REST, per this plan's Architecture, unless a later re-evaluation proves the
  MCP determinism/budget/no-raw-tool criteria from the task instructions — record which); whether
  the adapter is enabled (**no**, unless a human explicitly flipped it after Task 1's account-cap
  question was answered — record who and when); the exact lifetime entity ceiling (900 unless
  changed); whether account-level overage is mechanically prevented (Task 1's finding); allowed
  vs disabled endpoints; test and typing results; whether the Task 7 live smoke test actually ran;
  remaining prerequisites or blockers.
- [ ] **Step 3:** Invoke `superpowers:requesting-code-review` with the exact base/head commit
  range covering Tasks 1–8. Resolve all Critical/Important findings or record a technically
  justified rejection before declaring completion.
- [ ] **Step 4:** Invoke `superpowers:finishing-a-development-branch` and present merge/PR/local
  options to the human rather than choosing one silently.
- [ ] **Step 5:** Commit the report/checkpoint update separately from any code fix that came out
  of code review.

---

## Self-review notes (per superpowers:writing-plans)

- **Spec coverage:** every requirement in the task's original instructions (endpoints
  allowed/disallowed, ledger semantics, schema tolerance, security controls, caching/retention,
  the full test list, deliverables, separate commits, final-response shape) maps to a task above.
  The one item deliberately not concretized is exact type names from I2 (`PlaceSearchRequest`,
  `PlaceCandidate`, the POI `AdapterCapabilities` shape, the registry loader's exact module path) —
  those don't exist yet, and inventing them here risks silently diverging from whatever I2
  actually lands. Every task that touches them says so explicitly.
- **No placeholders:** every code block above is either complete or explicitly marked "confirm
  against I2's landed types" — never a bare "TODO" or "handle appropriately."
- **Type consistency:** `TripadvisorEntityLedger`'s `reserve`/`reconcile`/`release` signatures are
  used identically in Task 3 (definition) and Task 4/5 (consumption).
