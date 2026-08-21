# G3 — Gondola Read-Only MCP Integration Implementation Plan

> Supersedes `docs/superpowers/plans/2026-08-20-g3-gondola-live-adapter.md` per
> `reports/g3_0a_gondola_preflight_reassessment.md`. Two corrections from the old plan: (1) the
> official `mcp` Python SDK replaces the old plan's stdlib-`urllib` transport assumption; (2)
> authenticated `search_flights` (`mcp:read`) is implemented, not declared out of scope. Every
> other safety property of the old plan (static allowlist, disabled-by-default live transport,
> ledger, circuit breaker, `SampleAdapter` fallback, zero-network normal tests, no
> `backend/core/` → `gateway/` import) carries forward unchanged.

**Goal:** A disabled-by-default `GondolaAdapter` implementing G1's `TravelProviderAdapter`
protocol (`backend/gateway/travel/protocol.py`), for anonymous hotel search and authenticated
(`mcp:read`) flight search, fail-soft to `SampleAdapter`, activated only behind an explicit,
human-set environment flag.

**Architecture:** `backend/gateway/travel/adapters/gondola/`:
- `contracts.py` — Gondola-native response shapes (kept separate from `HotelQuote`/`FlightQuote`).
- `transport.py` — `Protocol` for fixture-vs-live transport.
- `fixture_transport.py` — the only transport wired by default; reuses G1's
  `FixtureTravelTransport` envelope pattern.
- `mcp_client.py` — thin wrapper around the official `mcp` package's `ClientSession` +
  Streamable HTTP client, constrained to `ALLOWED_HOST = "mcp.gondola.ai"`.
- `oauth.py` — OAuth bootstrap using `mcp`'s OAuth client support (discovery, DCR, PKCE `S256`,
  refresh); `TokenStore` protocol with a keychain-backed implementation and an in-memory fake for
  tests.
- `tool_policy.py` — frozen `ALLOWED_TOOLS` / `DENIED_TOOLS` constants.
- `budget.py` — persistent call ledger (mirrors `TripadvisorEntityLedger`).
- `normalize_hotel.py`, `normalize_flight.py` — native shapes → `HotelQuote` / `FlightQuote`.
- `errors.py` — reuses `gateway.travel.errors.TravelGatewayError` codes.
- `adapter.py` — `GondolaAdapter`, circuit breaker, kill switch.

**New dependency:** `mcp` (official Model Context Protocol Python SDK), pinned in
`backend/pyproject.toml`. `packages`/`include` discovery updated so installed builds include
`gateway.travel.adapters.gondola`.

## Global constraints (every phase)

- `backend/core/` never imports `backend/gateway/`.
- No new LLM call site; no LLM ever selects which MCP tool to call — `ALLOWED_TOOLS` is a
  hardcoded constant, checked before every `tools/call`.
- Only `mcp:read` is ever requested. `mcp:write` and `mcp:book` are never requested.
- `agents/pipeline.py` is not modified until Phase 7, and even then only behind a feature flag
  that defaults to the legacy path.
- `GondolaAdapter` is registered with `enabled=False` by default through every phase until a
  human explicitly flips `TRIPWISE_GONDOLA_LIVE_ENABLED` in their own environment.
- Every new test uses local fixtures or is a boundary/guard test. The full diff adds **zero**
  network calls to the normal test suite (`make gate` stays offline).
- OAuth tokens, client registration secrets, and raw provider responses never enter the repo, a
  fixture, a log, a trace, or an LLM prompt.
- `evals/golden/` stays green throughout; behavior changes and refactors ship in separate commits.

---

## Phase 2 — MCP client boundary + fixture transport (test-first)

### Task 2.1: Dependency + native contracts
- Add `mcp` to `backend/pyproject.toml` dependencies; confirm `mcp.client.auth`'s actual API
  surface against the installed version's own docs (per reassessment §5) before writing `oauth.py`.
- `contracts.py`: `GondolaHotelResult`, `GondolaFlightSegment`, `GondolaFlightResult` (Pydantic
  models, native field names, kept separate from `HotelQuote`/`FlightQuote`).
- Test: `evals/test_gondola_contracts.py` — round-trip from fixtures; every fixture asserts a
  `_fixture_provenance` field containing "synthetic" or "sanitized" (never silently real).

### Task 2.2: Tool policy (write first, before any transport)
- `tool_policy.py`: `ALLOWED_TOOLS = frozenset({"search_hotels", "get_hotel_details",
  "compare_rates", "get_booking_link", "predict_price", "get_hotel_stats",
  "get_multi_night_rates", "get_similar_hotels", "get_hotel_reviews", "diagnose_rates",
  "search_flights"})` (exactly the parent task's "G3 active read-only discovery allowlist").
  `DENIED_TOOLS` = the parent task's explicit denylist verbatim, plus `search_vehicles`,
  `get_vehicle_*`, `credit_card_coverage`, `optimize_loyalty_portfolio`, `get_loyalty_accounts`,
  `get_free_night_credits` (deferred domains, not this milestone's contracts).
- Test: `evals/test_gondola_tool_policy.py` — `ALLOWED_TOOLS`/`DENIED_TOOLS` disjoint; individual
  asserts (not just loop membership) for `book_hotel`, `search_vehicles` at
  `mcp:book`/deferred-domain tiers is absent from `ALLOWED_TOOLS`; a `assert_tool_allowed(name)`
  helper raises `TravelGatewayError("tool_denied", ...)` for every name not in `ALLOWED_TOOLS`,
  proven by a parametrized test over the full denylist plus 5 synthetic unknown names (fail-closed
  on unknown, not just on known-denied).

### Task 2.3: Fixture transport — 16 required scenarios
- `fixture_transport.py`: `FixtureGondolaTransport`, reusing G1's `FixtureTravelTransport`
  envelope (512KB bound, "cannot claim live" rejection).
- Fixtures under `gondola/fixtures/`, one JSON per scenario, each carrying
  `"_fixture_provenance"`: successful hotel search; successful flight search; empty results;
  authentication required (`401`); token refresh failure; rate limiting (`429`); timeout;
  malformed MCP result; unknown tool requested; oversized payload (>512KB, rejected pre-parse);
  partial hotel price (rate present, no tax breakdown); incomplete flight segments (missing
  arrival time); stale response (past `expires_at`); hostile prompt-injection text embedded in a
  hotel review/name field; missing booking link; provider outage (transport-level error).
- Test: `evals/test_gondola_fixture_transport.py` — one test per scenario; a `socket.socket.connect`
  monkeypatch-raise guard proving zero network; explicit assertion that auth-required/malformed/
  timeout/rate-limited scenarios raise the correct typed `TravelGatewayError` code, never a bare
  exception.

### Task 2.4: OAuth bootstrap + token storage boundary
- `oauth.py`: `TokenStore` protocol (`load() -> OAuthTokens | None`, `save(tokens) -> None`,
  `clear() -> None`); `KeychainTokenStore` (macOS/Linux OS-backed secure store, e.g. via the
  `keyring` package — add as a pinned dependency alongside `mcp`); `InMemoryTokenStore` for tests.
- `bootstrap_oauth(transport_base_url, token_store)`: generates the authorization URL via the
  `mcp` SDK's OAuth client, opens/prints it for the human, runs a local loopback HTTP server for
  the redirect callback, exchanges the code, persists tokens via `TokenStore`. Never logs the
  authorization code, access token, or refresh token — only redacted markers
  (`"token: <redacted, len=NN>"`).
- Test: `evals/test_gondola_oauth_boundary.py` — `bootstrap_oauth` with `InMemoryTokenStore` and a
  fake local OAuth server fixture (no real network); refresh-token reuse is serialized (a lock
  around token refresh, proven by a concurrent-call test asserting exactly one refresh HTTP call
  is made even when two callers race); requested scope is asserted to be exactly `"mcp:read"` in
  every constructed authorization request, never omitted, never including `write`/`book`; a grep-
  style test asserts no test file, fixture, log format string, or trace-writing code path contains
  a raw token pattern.

### Task 2.5: Zero-network offline end-to-end proof
- `evals/test_gondola_offline_e2e.py`: `socket.socket.connect` monkeypatched to raise; fixture
  transport → normalization end-to-end for both hotel and flight success fixtures.

---

## Phase 3 — Schema discovery + sanitized fixtures

- One-time, human-supervised script (not part of `pytest`/`make gate`):
  `backend/gateway/travel/adapters/gondola/scripts/discover_schema.py`. Connects anonymously,
  calls `tools/list` only (no `tools/call`), writes the returned tool schemas to a scratch file
  outside the repo.
- A human reviews the scratch output and manually authors sanitized fixtures reflecting the real
  field names/shapes, with names, IDs, links, prices, and timestamps redacted or replaced with
  synthetic values, each fixture tagged `"_fixture_provenance": "sanitized from tools/list schema
  capture on <date>"`. No raw response is ever committed.
- Task 2.1's fixtures are corrected in place if the real schema differs from the synthetic
  placeholders; corrections are their own commit (`fix(gateway): correct Gondola fixtures to
  match discovered schema`), never bundled with behavior changes.

---

## Phase 4 — Hotel normalization

- `normalize_hotel.py`: `normalize_gondola_hotel(raw, request, *, now) -> HotelQuote`. Integer
  minor units; correct currency exponent; preserves requested dates/travelers/rooms;
  `evidence.status` hard-coded `"verify_required"` (never `"live"`, regardless of what Gondola's
  response claims — matches the reassessment's "experimental, fail-soft" framing);
  `needs_verification=True` always; `completeness` reflects honest tax/cancellation gaps;
  provider IDs and deep links preserved; `get_booking_link`'s output URL is host-validated against
  `gondola.ai`/documented partner domains before ever being surfaced. Points-rate fields from
  Gondola are preserved on an adapter-internal side channel (documented in a code comment
  referencing this gap), never smuggled into `HotelQuote`'s cash fields, never converted to a
  cents-per-point value by this function — that conversion is the kernel's job alone, proven by a
  test that asserts the function body performs no such arithmetic. Free-text fields are sanitized
  for prompt-injection markers before reaching `evidence.notes`.
- Test: `evals/test_gondola_normalize_hotel.py` covering all of the above plus the injection-
  sanitization and partial-price fixtures from Phase 2.

---

## Phase 5 — Flight normalization (authenticated)

- `normalize_flight.py`: `normalize_gondola_flight(raw, request, *, now) -> FlightQuote |
  PartialProviderResult`. A normalized `FlightQuote` requires: ordered real segments; origin/
  destination; timezone-aware departure/arrival; marketing carrier; operating carrier when
  available; real flight number; cabin; duration; trip type; traveler mix; total integer price;
  currency; completeness; booking/verification link when present; provider quote identity;
  retrieval/expiry metadata. If Gondola's response lacks enough segment or price information, the
  function returns a typed `PartialProviderResult` diagnostic — it never fabricates a missing
  segment, carrier, or price. `evidence.status` is never `"award_availability"` — a cash
  `FlightQuote` from Gondola is typed distinctly from any future `AwardQuote`, matching Tier-F-P
  rule 9.
- Test: `evals/test_gondola_normalize_flight.py` — success, incomplete-segments (asserts
  `PartialProviderResult`, not a fabricated quote), and the malformed/empty fixtures from Phase 2.

---

## Phase 6 — Runtime safety envelope

- `mcp_client.py`: live transport constructor asserts
  `urllib.parse.urlparse(base_url).hostname == "mcp.gondola.ai"` — refuses otherwise. Payload size
  capped at 512KB before parsing. Every `tools/call` passes through `tool_policy.assert_tool_allowed`
  first — proven by a test that the live client cannot be made to call a name outside
  `ALLOWED_TOOLS` even if a caller tries to pass one directly (defense at the client layer, not
  just at the adapter layer).
- Env flags: `TRIPWISE_GONDOLA_LIVE_ENABLED` (default unset/false), `TRIPWISE_GONDOLA_KILL_SWITCH`
  (default unset/false; when true, forces `SampleAdapter` regardless of the live flag) — both read
  only at registry-construction time (Phase 7), never inside the adapter's call path.
- `budget.py`: SQLite ledger, `BEGIN IMMEDIATE` reservation, ceilings: 2 calls/plan, 1 concurrent
  session, 10s connect/20s total timeout, zero retries on 4xx, at most one bounded jittered retry
  on a transient 5xx (429 is treated as a hard stop — the circuit opens, not a retry target, per
  the parent task's explicit instruction), `max_cost_minor=0`.
- `adapter.py`: circuit breaker opens after 3 consecutive transport failures within a window,
  fast-fails `provider_unavailable` for the rest of the plan.
- Test: `evals/test_gondola_runtime_safety.py` — host-mismatch refusal, oversized-payload rejection
  pre-parse, tool-policy enforcement at the client layer, ledger reservation/rejection, circuit
  breaker trip, kill-switch override.

---

## Phase 7 — Gateway registry + product wiring (feature flag)

- `gateway/travel/registry.py`: register `gondola` with `provider_id="gondola"`,
  `source_method="provider_mcp"`, `allowed_profiles={"student_noncommercial"}`,
  `supports_commercial_use=False`, `stability="experimental"`, `enabled=False` by default;
  `enabled=True` only when `TRIPWISE_GONDOLA_LIVE_ENABLED` is set **and**
  `TRIPWISE_GONDOLA_KILL_SWITCH` is not.
- `agents/gateway_estimator.py`: when Gondola is disabled (the default), behavior is byte-
  identical to the existing G1 sample-parity test — proven by rerunning that exact parity test
  with the registry constructed post-Phase-7 code, unmodified expectation. When enabled and
  Gondola succeeds, its normalized evidence is eligible input alongside `SampleAdapter`'s, ranked
  by the existing freshness/completeness rules (no new ranking logic). When Gondola fails/
  times out/is incomplete, a visible diagnostic is attached and `SampleAdapter` evidence is used —
  never silently relabeled as live.
- `agents/pipeline.py` is touched only to read the same feature flag for the default estimator
  path; the flag defaults to legacy behavior.
- No OpenAPI/contract change — Gondola evidence surfaces through the same `HotelQuote`/
  `FlightQuote` shapes `/plan` already renders; if a future milestone wants Gondola-specific UI
  (e.g., a distinct trust badge), that is its own spec-12-§8 single-PR change, not this one.
- Test: `evals/test_gondola_registry.py`, `evals/test_gondola_gateway_estimator_parity.py`
  (disabled-path byte-identical parity), `evals/test_gondola_fallback_diagnostics.py` (failure →
  fallback with visible diagnostic).

---

## Bounded live acceptance (after Phases 2–7 pass, human-supervised, not part of `pytest`)

Exactly as the parent task specifies: at most one anonymous `tools/list`, one anonymous hotel
search for a supported destination, one authenticated `tools/list`, one authenticated
`search_flights` for DEL–SIN, using future valid dates. No booking/alert/account-history/payment
tool, no crawling, no checkout. A human explicitly triggers this — it is never invoked
autonomously by an agent. The OAuth authorization step itself requires the human to complete
sign-in in their own browser; the agent pauses at exactly that step and provides the one
authorization URL/action needed, never asking for or handling the password.

Sanitized results only are recorded in `reports/g3_1_gondola_readonly_mcp.md`: auth success/
failure, tool availability, non-empty/empty result, schema completeness vs. Phase 3's fixtures,
elapsed time, diagnostic category, fallback correctness. No raw response, account identifier,
token, or cookie is recorded.

---

## Verification commands

```bash
cd backend
.venv/bin/pytest evals/ -k gondola -v
.venv/bin/pytest -q
.venv/bin/mypy --strict core/ accounts/ agents/ api/ gateway/
.venv/bin/ruff check accounts/ agents/ gateway/ evals/
git diff --exit-code -- evals/golden/
cd .. && make gate
```

## Commit boundaries

1. `feat(gateway): add mcp dependency and native Gondola contracts`
2. `feat(gateway): add Gondola static tool policy`
3. `feat(gateway): add Gondola fixture transport with 16 scenarios`
4. `feat(gateway): add Gondola OAuth bootstrap and token storage boundary`
5. `test(gateway): prove Gondola offline path is zero-network`
6. `fix(gateway): correct Gondola fixtures to match discovered schema` (Phase 3, if needed)
7. `feat(gateway): normalize Gondola hotel results into HotelQuote`
8. `feat(gateway): normalize Gondola flight results into FlightQuote`
9. `feat(gateway): add Gondola runtime safety envelope`
10. `feat(gateway): register disabled Gondola provider and wire feature-flagged estimator`

Each commit is independently gated (focused test → full suite) before the next. `GondolaAdapter`
remains `enabled=False` in the default registry after every commit above; only a human sets the
env flag in their own shell to activate it for the bounded live-acceptance step.
