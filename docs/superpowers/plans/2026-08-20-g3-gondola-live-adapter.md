# G3 — Gondola Live Adapter Implementation Plan (CONDITIONAL — decision B)

> **Status of this plan: NOT YET AUTHORIZED FOR FULL EXECUTION.** This plan was produced by
> `reports/g3_0_gondola_preflight.md`'s decision **B — eligible only for offline
> fixture-backed adapter development**. Phases G3.1–G3.4 build offline, fixture-backed work
> that is safe to execute today under the same zero-network, zero-credential rules already
> governing this codebase. **Phase G3.5 (the only phase that makes a real network call) is
> explicitly blocked** until a human resolves the unknowns listed in the preflight report's
> §17, specifically: (1) written confirmation from Gondola that MCP access does not violate
> the general Terms of Service's anti-automation clause, and (2) independent confirmation
> that Gondola's hotel search meaningfully covers at least one of this project's actual
> corridors (India, UAE, Singapore, Europe, UK). Do not begin G3.5 without both.

**Goal:** Build a disabled-by-default `GondolaAdapter` implementing the G1
`TravelProviderAdapter` protocol (`backend/gateway/travel/protocol.py`), following the exact
architectural shape already proven safe for Tripadvisor
(`backend/gateway/places/adapters/tripadvisor/`) — transport-derived evidence status,
disabled-by-default live transport, injected-client security envelope, ledgered budget
enforcement — and for `SampleAdapter` (`backend/gateway/travel/adapters/sample.py`) —
fetch/parse/build separation, deterministic identity, zero-network normal tests.

**Architecture:** `backend/gateway/travel/adapters/gondola/` holds `contracts.py` (Gondola's
native response shapes, kept separate from the project's normalized `HotelQuote`),
`normalize.py` (native shapes → `HotelQuote`), `transport.py` (a `Protocol` for
fixture-vs-live transport, matching Tripadvisor's `TripadvisorClientProtocol` pattern),
`fixture_transport.py` (the only transport wired up in G3.1–G3.4), `live_transport.py`
(written in G3.2 but never instantiated by default; only reachable via an explicit,
human-set environment flag checked at registry-construction time), `budget.py` (a
persistent call-ledger, matching `TripadvisorEntityLedger`), `errors.py` (reusing
`gateway.travel.errors.TravelGatewayError`'s codes), and `adapter.py` (the
`GondolaAdapter` class itself, implementing only `search_hotels` — `search_flights` is not
implemented in this plan at all, per the preflight's finding that it requires sign-in this
project does not plan to obtain; calling it raises `unsupported_domain`, matching
`SampleAdapter`'s pattern for domains it does not serve).

**Tech Stack:** No new third-party dependency. Uses stdlib `urllib`/`json` for the live
transport (G3.2, written but disabled), matching the `gateway/reference/*/fetch.py` pattern
already established in G2 for isolating real network code from tested code paths.

## Global Constraints (apply to every phase below)

- `backend/core/` never imports `backend/gateway/`.
- No new LLM call site. Gondola-returned free text never reaches an LLM call without
  sanitization first (G3.1).
- `agents/pipeline.py` is not modified in G3.1–G3.4. Any change to production wiring is a
  separate, later, explicitly-authorized decision — not implied by this plan's existence.
- The static tool allowlist from `reports/g3_0_gondola_preflight.md` §10 is a hardcoded
  constant, never runtime-configurable, never LLM-selected.
- `GondolaAdapter` is registered in `gateway/travel/registry.py` with `enabled=False` by
  default in every phase through G3.4. Only a human, after G3.5's prerequisites are met, sets
  it to `enabled=True` in a reviewed, committed change — this plan does not do that for them.
- Every new test in G3.1–G3.4 either uses local fixtures or is a boundary/guard test; the
  full G3.1–G3.4 diff must add **zero** network calls to the normal test suite.
- `evals/golden/` and all existing test counts stay green throughout; behavior changes and
  refactors ship in separate commits, matching this project's established anti-drift rule.

---

## G3.1 — Offline adapter

### Task 1.1: Native contracts + fixtures

**Files:**
- Create: `backend/gateway/travel/adapters/gondola/__init__.py`,
  `backend/gateway/travel/adapters/gondola/contracts.py`
- Create fixtures: `backend/gateway/travel/adapters/gondola/fixtures/search_hotels_success.json`,
  `search_hotels_empty.json`, `search_hotels_partial_price.json`, `search_hotels_stale.json`,
  `search_hotels_malformed.json`, `search_hotels_rate_limited.json`, `search_hotels_timeout.json`
- Test: `backend/evals/test_gondola_contracts.py`

**Note on fixture provenance:** per the preflight's §9/§17 finding, Gondola's exact wire
schema was never captured (no live call was made). These fixtures are **synthetic,
conservative placeholders** shaped from Gondola's own documented field categories (hotel
name, rate, points value, cancellation, review score) and must carry an explicit
`"_fixture_provenance": "synthetic, not captured from a live Gondola response — see
reports/g3_0_gondola_preflight.md §17 item 4"` field at the top level, and every test that
uses them must assert that field is present, so nobody mistakes them for verified real
payloads later.

`GondolaHotelSearchResult` (native shape, deliberately NOT the project's `HotelQuote` — kept
separate so a real schema correction later touches only this file and `normalize.py`):
`hotel_id: str`, `name: str`, `cash_rate_minor: int | None`, `cash_currency: str | None`,
`points_rate: int | None`, `points_program: str | None`, `cancellation_text: str | None`,
`review_score: float | None`, `review_count: int | None`, `booking_link: str | None`,
`raw_notes: list[str]` (free text preserved for audit, never fed to an LLM directly).

- [ ] Write failing tests in `test_gondola_contracts.py` asserting: `GondolaHotelSearchResult`
  round-trips from the `search_hotels_success.json` fixture; `cash_rate_minor` and
  `points_rate` are `int`, never `float`; the fixture's `_fixture_provenance` field is
  asserted non-empty and containing "synthetic".
- [ ] Implement `contracts.py` (Pydantic `BaseModel`), run tests green, `mypy --strict`,
  `ruff check`, commit: `feat(gateway): add native Gondola hotel contracts and fixtures`.

### Task 1.2: Fixture transport

**Files:**
- Create: `backend/gateway/travel/adapters/gondola/transport.py` (a `Protocol`:
  `class GondolaTransport(Protocol): async def search_hotels(self, request: dict) ->
  dict: ...`), `backend/gateway/travel/adapters/gondola/fixture_transport.py`
  (`FixtureGondolaTransport`, reusing the exact envelope/error-mapping pattern already
  proven in `backend/gateway/travel/fixtures/transport.py`'s `FixtureTravelTransport` from
  G1 — same 512KB payload bound, same "cannot claim live" rejection, same 8 scenario names)
- Test: `backend/evals/test_gondola_fixture_transport.py`

- [ ] Write failing tests mirroring `evals/test_travel_fixtures_harness.py`'s exact structure
  (success/empty/malformed/partial-price/stale/rate-limited/auth-failed/timeout, plus the
  "cannot claim live" rejection test and the "no network" `socket.socket.connect`
  monkeypatch guard).
- [ ] Implement `FixtureGondolaTransport` as a thin specialization of the existing generic
  harness (reuse `FixtureTravelTransport` directly by pointing it at the
  `gondola/fixtures/` directory rather than reimplementing the envelope logic — this is the
  "materially reduces duplication" case the G1/G2 plans already established the pattern for).
  Run, mypy, ruff, commit: `feat(gateway): add Gondola fixture transport`.

### Task 1.3: Normalization into `HotelQuote`

**Files:**
- Create: `backend/gateway/travel/adapters/gondola/normalize.py`
  (`normalize_gondola_hotel(raw: GondolaHotelSearchResult, request: HotelSearchRequest, *,
  now: datetime) -> HotelQuote`)
- Test: `backend/evals/test_gondola_normalize.py`

- [ ] Write failing tests: a successful fixture normalizes to a `HotelQuote` with
  `evidence.status="verify_required"` (not `"live"` — per the preflight's §7 finding that
  independent evidence shows staleness/relevance bugs, this adapter's normalization layer
  hard-codes `verify_required` regardless of what Gondola's own response claims, until a
  human overrides this after real-world validation); `evidence.needs_verification=True`
  always; `evidence.completeness` reflects whether `cancellation_text`/tax breakdown are
  present (`"taxes_uncertain"` when Gondola's fixture doesn't show a tax-inclusive total,
  matching the honest-gap pattern from G1's `SampleAdapter`); `points_rate` is preserved as
  raw evidence on the quote but **never** converted to a cents-per-point value by this
  normalization function — that conversion is exclusively the kernel's job, and a test
  asserts `normalize_gondola_hotel` performs no such arithmetic (grep the function body in a
  test, or assert the output type has no such field); prompt-injection sanitization strips
  any text resembling an instruction (e.g. containing "ignore previous", "system:", or
  similar markers) from `raw_notes` before it is copied into `HotelQuote.evidence.notes`.
- [ ] Implement, run, mypy, ruff, commit:
  `feat(gateway): normalize Gondola hotel results into HotelQuote`.

### Task 1.4: Typed errors + static tool allowlist constant

**Files:**
- Create: `backend/gateway/travel/adapters/gondola/errors.py` (thin re-export/wrapper of
  `gateway.travel.errors.TravelGatewayError`, not a new error taxonomy — Gondola's typed
  errors are the same 11 spec-16 codes already established)
- Create: `backend/gateway/travel/adapters/gondola/tool_allowlist.py` — a frozen constant:
  `ALLOWED_TOOLS: frozenset[str] = frozenset({"search_hotels", "get_hotel_details",
  "compare_rates", "get_booking_link", "get_multi_night_rates", "get_hotel_reviews",
  "get_hotel_stats"})` and `DENIED_TOOLS: frozenset[str]` containing every tool listed in
  the preflight report's §10 denylist, verbatim.
- Test: `backend/evals/test_gondola_tool_allowlist.py`

- [ ] Write failing tests: `ALLOWED_TOOLS` and `DENIED_TOOLS` are disjoint sets;
  `DENIED_TOOLS` contains exactly the 22 tool names from the preflight report §10 (hardcode
  the expected list in the test, not derived from the same source file, so a future edit to
  the allowlist can't silently shrink the denylist without the test failing);
  `"book_hotel" in DENIED_TOOLS`, `"search_flights" in DENIED_TOOLS`,
  `"get_payment_methods" in DENIED_TOOLS` are each asserted individually (not just via set
  membership in a loop) since these are the highest-stakes entries.
- [ ] Implement, run, mypy, ruff, commit: `feat(gateway): add Gondola static tool allowlist`.

### Task 1.5: Zero-network end-to-end offline test

**Files:**
- Test: `backend/evals/test_gondola_offline_e2e.py`

- [ ] Write a test that monkeypatches `socket.socket.connect` to raise, then runs
  `FixtureGondolaTransport` → `normalize_gondola_hotel` end-to-end from the success fixture,
  asserting a non-empty, well-formed `HotelQuote` list — mirroring G1's
  `test_travel_boundary.py::test_travel_gateway_search_flights_makes_no_socket_call`
  pattern exactly.
- [ ] Run, mypy, ruff, commit: `test(gateway): prove Gondola offline path is zero-network`.

---

## G3.2 — Runtime safety envelope

### Task 2.1: Disabled-by-default live transport (written, never instantiated by default)

**Files:**
- Create: `backend/gateway/travel/adapters/gondola/live_transport.py`
  (`LiveGondolaTransport`, constructor requires an explicit `base_url` matching a hardcoded
  `ALLOWED_HOST = "mcp.gondola.ai"` constant — connection refused if it doesn't match,
  mirroring the `fetch.py` pattern's `ALLOWED_HOST not in URL` check from G2, now backed by
  the G2 code-review finding that this check should be a genuine assertion, not vacuous:
  `assert urllib.parse.urlparse(base_url).hostname == ALLOWED_HOST`)
- Test: `backend/evals/test_gondola_live_transport_boundary.py`

- [ ] Write failing tests: `LiveGondolaTransport.__init__` raises if `base_url`'s hostname
  isn't exactly `mcp.gondola.ai`; the class is never imported by `core/`, `agents/`, `api/`,
  or any FastAPI route (AST-walk test, matching `test_travel_boundary.py`'s pattern); the
  class's `search_hotels` method only ever calls tools in `ALLOWED_TOOLS` (assert by
  inspecting the tool-name literal passed to the underlying request-construction helper);
  response payload size is capped (512KB, matching Tripadvisor's bound) and oversized
  responses raise `invalid_response` before JSON parsing.
- [ ] Implement using stdlib `urllib.request` only (no new dependency), secret redaction
  reusing `gateway.places.registry.redact_secret` (there are no secrets for anonymous
  hotel search, but the helper is reused for consistency and for the day sign-in-gated
  domains are revisited). Run, mypy, ruff, commit:
  `feat(gateway): add disabled-by-default Gondola live transport`.

### Task 2.2: Budget ledger, timeout, retry, circuit breaker

**Files:**
- Create: `backend/gateway/travel/adapters/gondola/budget.py` (a persistent SQLite-backed
  call ledger, structurally identical to `TripadvisorEntityLedger`
  (`backend/gateway/places/adapters/tripadvisor/budget.py`) but enforcing the ceilings from
  `reports/g3_0_gondola_preflight.md` §14: 2 calls/plan, 1 concurrent, 10s connect/20s total
  timeout, zero retries on 4xx, at most 1 bounded jittered retry on transient 5xx,
  `max_cost_minor=0`)
- Test: `backend/evals/test_gondola_budget.py`

- [ ] Write failing tests mirroring `evals/test_tripadvisor_adapter.py`'s ledger tests:
  reservation/reconciliation via `BEGIN IMMEDIATE`, rejection when
  `calls_per_plan` would be exceeded, rejection of a non-persistent (in-memory) ledger for
  any path that would be wired to a live transport (defense in depth, even though the live
  transport itself is disabled by default in this phase).
- [ ] Implement, run, mypy, ruff, commit: `feat(gateway): add Gondola call budget ledger`.

### Task 2.3: Circuit breaker + kill switch

**Files:**
- Modify: `backend/gateway/travel/adapters/gondola/adapter.py` (created here, not before —
  this is the first task that assembles `GondolaAdapter` itself)
- Test: `backend/evals/test_gondola_circuit_breaker.py`

- [ ] Write failing tests: after N consecutive transport failures within a window (constant,
  e.g. 3), `GondolaAdapter.search_hotels` stops attempting the live transport for the
  remainder of the process/plan and raises `provider_unavailable` immediately (fast-fail,
  no further attempts) so the caller falls back to `SampleAdapter`; the kill switch is a
  single injected boolean (`live_enabled: bool`, defaulting to `False` in the constructor)
  — not an environment variable read inside the adapter itself, so the *registry* (Task 3.2)
  is the only place that decides activation, keeping the adapter class itself dumb and
  testable.
- [ ] Implement `GondolaAdapter(kb=None, *, transport: GondolaTransport, live_enabled:
  bool = False)` implementing `TravelProviderAdapter`'s `search_hotels`; `search_flights`
  raises `TravelGatewayError("unsupported_domain", "Gondola flight search requires
  sign-in and is out of scope per reports/g3_0_gondola_preflight.md")`. Run, mypy, ruff,
  commit: `feat(gateway): assemble GondolaAdapter with circuit breaker and kill switch`.

---

## G3.3 — Orchestration and fallback

### Task 3.1: Deterministic provider selection

**Files:**
- Modify: `backend/gateway/travel/registry.py` (add a `TravelProviderRegistryEntry` for
  `gondola`, `enabled=False`, `priority` lower-numbered than `sample_travel_adapter`'s `999`
  so Gondola would be preferred *if* enabled — matching spec 16 §15's selection order — but
  `enabled=False` means `SampleAdapter` is selected in all normal operation)
- Test: `backend/evals/test_gondola_registry.py`

- [ ] Write failing tests: `get_default_travel_registry()` includes a `gondola` entry with
  `enabled=False`; `select_providers(domain="hotel", ...)` returns `sample_travel_adapter`
  first (or only) when Gondola is disabled, matching G1's existing deterministic-selection
  test pattern exactly; a test that explicitly constructs a registry with Gondola
  `enabled=True` (test-only, not the default factory) proves the ordering logic itself
  works, without ever making the *default* registry live.
- [ ] Implement, run, mypy, ruff, commit: `feat(gateway): register disabled Gondola provider`.

### Task 3.2: Partial-domain diagnostics + freshness/completeness checks

**Files:**
- Modify: `backend/agents/gateway_estimator.py` is **NOT** modified in this phase — Gondola
  is not wired into the estimator in G3.1–G3.4, matching this plan's own scope boundary
  (production wiring is a separate, later, explicitly-authorized decision). Instead:
- Create: `backend/evals/test_gondola_standalone_orchestration.py` — a test-only harness
  proving the *pattern* (adapter → freshness check → completeness check → fallback) works
  in isolation, without touching `gateway_estimator.py`.

- [ ] Write failing tests: a `HotelQuote` from Gondola with `completeness="partial"` cannot
  win against a `SampleAdapter` quote with `completeness="complete"` on price alone
  (reusing `gateway.travel.flexible.stay_windows_comparable` and the existing completeness
  rule from spec 16 §9 — no new ranking logic is written, this test proves the *existing*
  rule already handles a second provider correctly); a quote past its `expires_at` is
  re-classified `stale` by the existing `gateway.travel.freshness.compute_status` function
  (again: proving reuse, not writing new freshness logic); at most one re-query attempt
  is modeled (a test double transport that fails once then succeeds, asserting exactly 2
  calls total, never 3+).
- [ ] Implement only the test harness (no new production ranking/freshness code — this task
  is a reuse-proof, per the "materially reduces duplication" principle). Run, mypy, ruff,
  commit: `test(gateway): prove Gondola quotes obey existing freshness and completeness rules`.

---

## G3.4 — Contract and product integration

**This phase is design-only in this plan and is NOT executed as part of G3.1–G3.3's commits.**
Per this project's own rule (spec 12 §8: schema change, snapshot, generated code, MSW
fixtures, and UI updates ship in ONE PR), and because G3.1–G3.3 do not touch
`agents/pipeline.py` or any FastAPI route, **no public contract change is needed or proposed
in this plan.** If a future milestone decides to surface Gondola-sourced quotes in the
`/plan` response, that decision requires:

- A new `DEVIATIONS.md` entry explaining why the public contract must change.
- `contract/openapi.json`, generated frontend types, Zod/manual schemas, MSW handlers, and
  UI trust-state rendering (live/cached/estimated/stale/verify_required badges, safe deep
  link via `get_booking_link`'s host-validated output, material-limitations text) updated
  in the same commit, per this project's existing, non-negotiable rule.
- Explicit display of `needs_verification=True` and the `verify_required` status this plan's
  normalization layer hard-codes (Task 1.3) — never softened to look more confident than the
  evidence supports.

No files are created or modified for G3.4 in this plan's authorized scope. It is documented
here only so a future implementer knows what "done" looks like when that decision is made.

---

## G3.5 — Manual live acceptance (BLOCKED — do not execute without human sign-off)

**Explicit precondition, restated:** this phase may not begin until a human has (a) obtained
written clarification from Gondola that MCP access does not violate the ToS's automation
prohibition, and (b) confirmed — by manually testing the consumer site or by direct
correspondence with Gondola — that hotel search meaningfully covers at least one of this
project's actual corridors. Neither of these can be satisfied by code.

**Once both preconditions are met**, this phase is:

- A single, separate, manually-triggered script (not part of `pytest`, not part of `make
  gate`), e.g. `backend/gateway/travel/adapters/gondola/scripts/live_acceptance_check.py`.
  **The gate must not be a self-attestation CLI flag** — a flag like
  `--i-have-read-the-preflight-report` can be typed by any future agent session and provides
  no actual evidence the two preconditions above were met (this was flagged as a Critical
  gap by this milestone's own required code review: "a self-attestation flag ... nothing
  checks that Gondola's written clarification or corridor-coverage confirmation actually
  happened"). Instead, the script must require a **human-supplied artifact an agent cannot
  self-generate**: e.g. refuse to run unless a file
  `backend/gateway/travel/adapters/gondola/G3_5_APPROVED.txt` exists, is committed by a human
  (not written by an agent session), and contains a sha256 hash of a value only communicated
  out-of-band by the human at approval time (e.g. a short passphrase the human chooses and
  states directly in chat when granting approval, never generated or guessed by the agent).
  The script verifies the hash before proceeding and refuses to run — or to accept an
  agent-authored version of that file — otherwise.
- Read-only: calls only `search_hotels` for one hardcoded, low-stakes query (e.g. a single
  well-known hotel in the corridor confirmed viable by the human precondition above), once.
- Enforces the `max_cost_minor=0` ceiling from Task 2.2's ledger — the script itself
  constructs a `PlanBudget` and refuses to proceed if the ledger reports any non-zero
  reserved cost.
- Produces a sanitized report (no raw response body committed to the repo, no secret,
  matching this project's existing pattern from the P1 live-LLM-smoke and Tripadvisor
  preflight precedents) documenting: whether the call succeeded, the response shape observed
  (field names only, values redacted or reduced to type/format), latency, and whether the
  observed shape matches or contradicts this plan's Task 1.1 synthetic fixtures — feeding
  directly into a fixture-correction follow-up task if it doesn't match.
- Requires the human's explicit, immediate approval before execution — this script is never
  invoked by an agent autonomously, matching this project's human-in-the-loop precedent for
  every other live-provider smoke test in this codebase.

No files for G3.5 are created by this plan's own execution. They are specified here so a
future, explicitly-authorized session has an implementation-ready starting point once the
preconditions are met.

---

## Verification commands (for G3.1–G3.3, the phases actually authorized to run)

```bash
cd backend
.venv/bin/pytest evals/test_gondola_contracts.py evals/test_gondola_fixture_transport.py \
  evals/test_gondola_normalize.py evals/test_gondola_tool_allowlist.py \
  evals/test_gondola_offline_e2e.py evals/test_gondola_live_transport_boundary.py \
  evals/test_gondola_budget.py evals/test_gondola_circuit_breaker.py \
  evals/test_gondola_registry.py evals/test_gondola_standalone_orchestration.py -v
.venv/bin/pytest -q
.venv/bin/mypy --strict core/ accounts/ agents/ api/ gateway/
.venv/bin/ruff check accounts/ agents/ gateway/ evals/
git diff --exit-code -- evals/golden/
cd .. && make gate
```

## Commit boundaries

1. `feat(gateway): add native Gondola hotel contracts and fixtures`
2. `feat(gateway): add Gondola fixture transport`
3. `feat(gateway): normalize Gondola hotel results into HotelQuote`
4. `feat(gateway): add Gondola static tool allowlist`
5. `test(gateway): prove Gondola offline path is zero-network`
6. `feat(gateway): add disabled-by-default Gondola live transport`
7. `feat(gateway): add Gondola call budget ledger`
8. `feat(gateway): assemble GondolaAdapter with circuit breaker and kill switch`
9. `feat(gateway): register disabled Gondola provider`
10. `test(gateway): prove Gondola quotes obey existing freshness and completeness rules`

Each commit is independently gated: run its own focused test, then the full suite, before
moving to the next. `agents/pipeline.py` is untouched throughout — `/plan` remains on the
legacy estimator path exactly as it was after G1/G2, and `GondolaAdapter` remains
`enabled=False` in the default registry after every commit in this list.
