# G3.1 — Gondola Read-Only MCP Integration

**Milestone type:** Offline-development implementation. **OFFLINE DEVELOPMENT COMPLETE — LIVE
ACTIVATION NOT ATTEMPTED.** Every safety boundary (OAuth scope, tool allowlist, host lock,
budget/circuit-breaker, kill switch, fail-soft fallback) is implemented and tested; no real
network call to Gondola was ever made in this session. Live activation — schema discovery
(Phase 3) and bounded live acceptance — is explicitly deferred pending the human, per this
milestone's own instructions ("A human explicitly triggers this — it is never invoked
autonomously by an agent").

**Branch:** `feat/g3-gondola-readonly-mcp`, worktree `.worktrees/feat-g3-gondola-readonly-mcp`,
branched from `main` @ `43c4191`. **15 commits**, nothing pushed, merged, or force-anything.

---

## 1. What was built

`backend/gateway/travel/adapters/gondola/` — a disabled-by-default `GondolaAdapter` implementing
the existing `TravelProviderAdapter` protocol for anonymous hotel search and authenticated
(`mcp:read`-only) flight search:

- `contracts.py` — native Gondola response shapes, kept separate from `HotelQuote`/`FlightQuote`.
- `tool_policy.py` — frozen `ALLOWED_TOOLS`/`DENIED_TOOLS`, fail-closed on every unknown name.
- `fixture_transport.py` — the only transport wired by default; reuses G1's proven
  `FixtureTravelTransport` envelope. 16 fixture scenarios (success ×2, empty, auth-required,
  refresh-failure, rate-limited, timeout, malformed, unknown-tool, oversized, partial-price,
  incomplete-segments, stale, prompt-injection, missing-link, outage).
- `oauth.py` — `OAuthClientBoundary` (requests only `mcp:read`, serializes token refresh under a
  lock, redacts tokens from `repr`), `KeychainTokenStore` (OS keychain via `keyring`),
  `InMemoryTokenStore` (tests only).
- `mcp_client.py` — `LiveGondolaTransport`, hard-locked to `https://mcp.gondola.ai`, using the
  official `mcp` Python SDK (`ClientSession` + `streamable_http_client`) — confirmed against the
  installed package's real API surface, not assumed.
- `sanitize.py` — shared, NFKC-normalized prompt-injection sanitizer applied uniformly to every
  Gondola free-text field reaching `HotelQuote`/`FlightQuote`.
- `normalize_hotel.py` / `normalize_flight.py` — fail-closed normalization: a missing required
  field (price, currency, segment data) raises a typed `invalid_response` error rather than
  fabricating anything; `evidence.status` is hard-coded `"verify_required"`, never `"live"` or
  `"award_availability"`; booking links host-validated before becoming a `deep_link_url`.
- `budget.py` — `GondolaCallBudget`, a persistent SQLite ledger (2 calls/plan), with clean
  fail-soft behavior under real lock contention (not simulated — proven against genuine
  `BEGIN EXCLUSIVE` contention from a second connection).
- `adapter.py` — `GondolaAdapter`: kill switch (`live_enabled: bool`, constructor-only, never an
  env read inside the adapter), `GondolaCircuitBreaker` (opens after 3 consecutive failures),
  bounded retry (exactly one retry on `provider_unavailable`/`timeout`; zero retries on
  `rate_limited` or any other 4xx-shaped failure, which instead count directly toward the
  breaker).
- `scripts/bootstrap_oauth.py` — one-time, human-supervised OAuth bootstrap using the real `mcp`
  SDK's `OAuthClientProvider` with a loopback callback server bound to `127.0.0.1`; never part of
  `pytest`/`make gate`; never invoked automatically.
- `gateway/travel/registry.py` — `gondola` entry registered, `enabled` driven solely by
  `TRIPWISE_GONDOLA_LIVE_ENABLED` / `TRIPWISE_GONDOLA_KILL_SWITCH`, read once at
  registry-construction time; disabled by default.

## 2. What was deliberately not built

- **`agents/gateway_estimator.py` / `agents/pipeline.py` were not modified.** `gateway_estimator.py`
  is not the production path today (G1's own prior, documented decision); its `SampleAdapter`-
  specific `legacy_flight`/`legacy_hotel` reconstruction shim is too tightly coupled to force
  Gondola through safely without its own reviewed redesign. Gondola's registry selectability and
  conformance to the existing freshness/completeness rules are proven in isolation instead
  (`test_gondola_registry.py`, `test_gondola_standalone_orchestration.py`). `/plan` is
  byte-identical to before this milestone.
- **Phase 3 (real schema capture via `tools/list`) was not run.** Fixtures remain explicitly
  labeled synthetic (`_fixture_provenance`).
- **Bounded live acceptance was not run.** No real Gondola call, no OAuth bootstrap, no browser
  sign-in happened this session.

## 3. Claude's development MCP connection / TripPlanner's runtime MCP integration

- **Claude's own MCP tooling was not touched.** No `claude mcp add` or equivalent was run; nothing
  was added to this session's own MCP configuration.
- **TripPlanner's own runtime MCP client integration was implemented** (the `gondola/` package
  above) — this is the actual product integration the milestone asked for, distinct from and
  unrelated to Claude's own MCP tooling.

## 4. OAuth

**Not completed.** The bootstrap script (`scripts/bootstrap_oauth.py`) is written, type-checked
(`mypy --strict` clean), and statically verified (scope-only-`mcp:read`, no raw-token logging,
localhost-only loopback, keychain-only persistence) — but was never executed. No browser sign-in
happened; no token exists anywhere.

## 5. Tools discovered vs. allowlisted

No live `tools/list` call was made (Phase 3 deferred). The allowlist (`tool_policy.py`) was built
directly from the parent task's own explicit "G3 active read-only discovery allowlist" (11 tools)
and denylist (21 tools: 14 explicit + 7 recognized-but-deferred), not from a live discovery
response.

## 6. Hotel live-smoke / flight live-smoke / fallback

- **Hotel live-smoke:** not run (deferred to bounded live acceptance).
- **Flight live-smoke:** not run (deferred to bounded live acceptance).
- **Fallback result:** proven offline. `test_gondola_circuit_breaker.py::test_kill_switch_disabled_by_default_raises_provider_unavailable`
  and the registry's disabled-by-default gating together prove that with no live flag set,
  Gondola is never selected and behavior is unchanged from pre-milestone `main`.

## 7. Tests before and after

| | Collected | Passed | Failed | Skipped |
|---|---|---|---|---|
| Before (fresh worktree, `main` @ `43c4191`, post-`make seed`) | 878 | 852 | 19 | 7 |
| After (this branch, `HEAD`) | 1,016 | 990 | 19 | 7 |

**+138 new tests, 0 regressions.** The 19 failures are identical before and after — confirmed
pre-existing (present before any Gondola code was written) and unrelated to this milestone: they
require a locally-provisioned regional catalog (`gateway.catalog.provision` against real Overture
data), deliberately never git-tracked per the G0/G2 design, and are documented as environment
debt in `DEVIATIONS.md`'s G3.0a section. The stated `CLAUDE.md` checkpoint of "898 tests" does not
match this fresh worktree's baseline either way; see the same DEVIATIONS entry.

## 8. mypy and ruff

- `mypy --strict core/ accounts/ agents/ api/ gateway/` — **clean, 140 source files.**
- `ruff check accounts/ agents/ gateway/ evals/` (zero-tolerance scope) — **clean.**
- `ruff check core/ api/` (ratcheted, ceiling 12) — **7 findings, unchanged from before this
  milestone** (this milestone touched neither `core/` nor `api/`).

## 9. Golden / contract drift

- `git diff --exit-code -- backend/evals/golden/` — **clean, zero diff.**
- `evals/test_contract_one_pr.py` — **passes** (no OpenAPI contract change; none was needed).
- `AGENTS.md` / `CLAUDE.md` — **byte-identical** (`cmp` clean).

## 10. `make gate`

The `gate` target's `pytest -q` step fails on the same 19 pre-existing catalog-provisioning
tests described in §7 — this was true of this worktree before any Gondola code existed, so it is
not a result of this milestone. Every other gate check that the pytest failure prevented `make`
from reaching was run manually and passed: `mypy --strict`, `ruff` (both scopes), the golden-diff
check, `test_contract_one_pr.py`, the `AGENTS.md`/`CLAUDE.md` `cmp`, and a clean `git status
--porcelain` tree (all reported above). `pytest -k gondola` itself is 100% green (138/138).

## 11. Code review

Dispatched a `general-purpose` subagent per `superpowers:requesting-code-review` against the full
diff (`43c4191..`pre-fix HEAD``). Findings and disposition:

- **Critical — rejected (false positive, verified with evidence):** "the code imports `httpx2`,
  which doesn't exist; should be `httpx`." Directly checked: `httpx2` is a real, installed PyPI
  package (`pip show httpx2` → v2.12.0, "the next generation HTTP client") and is exactly what the
  `mcp` SDK's own `mcp/client/streamable_http.py` imports and requires (`import httpx2`,
  `streamable_http_client`'s `http_client` parameter is typed `httpx2.AsyncClient | None`).
  Switching to classic `httpx` would have been the actual bug. No code changed.
- **Critical — fixed, test-first:** `normalize_flight.py` copied `raw.raw_notes` into
  `evidence.notes` with zero sanitization, unlike the hotel path — a real, silent
  prompt-injection gap. Extracted a shared `sanitize.py`, applied uniformly to both paths.
- **Important — fixed, test-first:** the sanitizer's plain lowercase-substring matching was
  bypassable via extra whitespace, embedded newlines, or fullwidth Unicode. Hardened with NFKC
  normalization + whitespace collapsing (still explicitly best-effort, per the parent task's own
  framing — no substring sanitizer is a formal guarantee).
- **Important — fixed, test-first:** the file-backed call budget ledger could raise a raw,
  unhandled `sqlite3.OperationalError` under real lock contention instead of a clean fail-soft
  signal. Added a `busy_timeout_s` knob, caught the contention case, translated it to
  `TravelGatewayError("provider_unavailable", ...)`, and proved it against genuine SQLite lock
  contention (a second connection holding `BEGIN EXCLUSIVE`), not a simulation.
- **Minor — fixed:** removed dead, misleading `_sanitize(raw.name) or raw.name` fallback
  (unreachable given `raw.name`'s `min_length=1` constraint).

Full gate re-run after fixes: see §7–10 above (post-fix numbers).

## 12. Security and secret scan

`git diff 43c4191..HEAD --name-only | xargs grep` for common secret-key/token/password literal
patterns across every file this milestone touched: **zero matches.** No token, API key, or
credential of any kind exists in any tracked file.

## 13. Remaining limitations / follow-up work

1. **Phase 3 (real schema capture)** and **bounded live acceptance** remain the two explicitly
   deferred, human-supervised steps. Neither happened this session.
2. `agents/gateway_estimator.py`/`agents/pipeline.py` wiring is intentionally out of scope (§2) —
   a future milestone that wants Gondola evidence to actually reach `/plan` needs its own reviewed
   redesign of the `SampleAdapter`-coupled legacy reconstruction shim first.
3. Hotel points-rate evidence has no reviewed award-rate contract yet (documented gap, per the
   parent task's own instruction — preserved on the native contract only, never smuggled into
   `HotelQuote`).
4. Rental-vehicle and loyalty-account-import domains are explicitly deferred (parent task's
   "Recognized but deferred" list) — not built, not stubbed.
5. The circuit breaker's 3-failure threshold is, in practice, rarely reachable within a single
   plan's 2-call budget ceiling (documented in `DEVIATIONS.md`) — its real value is cross-plan/
   process-lifetime protection, not intra-plan.

## 14. Explicit confirmation

Nothing was pushed, merged, or deployed. No branch was force-anything. No booking, payment,
cancellation, mutation, or account-data tool was ever called or even referenced outside the
`DENIED_TOOLS` constant and test assertions that it stays denied. No live Gondola call was made.
No OAuth token was created, requested, or stored. No secret exists in any tracked file. The
working tree is clean at every commit boundary.
