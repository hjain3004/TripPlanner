# G4 — Open-Meteo MCP weather-context adapter

**Status:** ACCEPTANCE PENDING FINAL COMMITTED-TREE GATE — implementation, bounded live forecast
probe, independent review, accepted fixes, reseed, and full regression are complete.

**Branch:** `codex/g4-open-meteo-mcp`

**Base:** `eccb19885557001fec7a87d5b459998dda646e57`

**Implementation commits:** `377745e`, `568115c`, `860f3dc`, `974c39d`

## Scope delivered

- `backend/gateway/weather/` is an application-owned contextual-evidence boundary. It does not
  extend the travel-inventory domain, enter money arithmetic, or import into `core/`, `agents/`,
  request-time `api/`, the OpenAPI contract, or the frontend.
- The adapter talks over a real stdio MCP client to one pinned upstream server:
  `@cyanheads/open-meteo-mcp-server` 0.4.1, Apache-2.0, upstream commit
  `bff522070d90cdf99579a3d23a88e8c0e93324ee`. The audited lockfile contains 48 packages,
  no install scripts, registry integrity hashes, and no vendored `node_modules` tree.
- The server is correctly disclosed as a third-party `community_mcp`, not an Open-Meteo-operated
  provider MCP. The Python dependency is bounded to the exercised MCP 2.x API line.
- Exactly three tools are allowlisted: forecast, historical weather, and climate. Geocoding,
  elevation, marine, air-quality, ensemble, flood, DuckDB/dataframe, storage, and SQL tools are
  denied. The runtime never calls `tools/list`; discovery does not grant authority.
- Coordinates, date windows, forecast days, variables, payload bytes, result rows, timeouts,
  retries, and per-plan calls are bounded. The adapter is disabled by default and the kill switch
  wins over the enable flag.
- Current observation, near-term forecast, historical observation, and climate summary use
  separate typed evidence contracts. Climate summaries are low confidence, require verification,
  omit daily-series output, and carry the fixed caveat `Climate summary - not a forecast`.
- All provider failures become a typed unavailable outcome with the fixed public message
  `Weather context unavailable`; provider exception text does not cross the boundary.
- Evidence carries fixed Open-Meteo attribution and licence, source, retrieval/validity times,
  origin, confidence, verification state, upstream identity, and bounded sanitized notes.

## Activation and upstream execution

The adapter remains disabled by default and is not wired into planning, API, OpenAPI, or the UI.
The upstream server is an operator-provisioned, out-of-repository dependency. Launch refuses an
install tree whose audited lockfile hash, package name/version/licence, or entrypoint differs from
the reviewed pin. The child receives only the code-owned Open-Meteo base URLs and disabled-storage
configuration; no credentials are required or supplied.
Every variable the MCP SDK otherwise inherits is overridden: the child receives an ephemeral
empty HOME plus fixed user, shell, terminal, and executable-path values. The empty HOME is removed
after the call.

One anonymous, read-only Singapore forecast call was run through the production stdio transport
against the pinned server on the already-installed Node 24.19.0 runtime. It required no account,
credential, payment method, credit, or paid tier. The strict normalizer accepted the response on
first contact. A 2.2 KB whitelisted numeric capture is committed with CC BY 4.0 attribution and
explicit `sanitized_capture` provenance. This verifies only forecast and current-condition
response shapes. Historical and climate response shapes were reviewed from source and tested
offline; they were not exercised live and will fail soft if the real server differs.

## Security and policy boundaries

- No arbitrary URL, tool, SQL, path, environment key, model, unit, or provider variable can be
  supplied by a caller.
- Tool arguments are validated before process creation. Server identity is checked after MCP
  initialization and before dispatch.
- Live provenance requires a private factory attestation created only after lockfile, package,
  licence, path, and entrypoint checks. Copying or directly constructing a launch cannot preserve
  `origin="live"`.
- Payloads are bounded before JSON normalization. Numeric/date/unit/row invariants are validated
  fail-closed; dated windows must be complete and contiguous, and forecasts must start on the
  exact current local date. Unsupported or contradictory data is never repaired or fabricated.
- Climate metrics remain unavailable when any daily value for that metric is missing; the adapter
  never computes a deceptively complete aggregate over a hidden subset.
- Provider free text is unnecessary for evidence. The sole advisory notice path is NFKC- and
  control-normalized, URL-stripped, marker-filtered, and length-bounded.
- Fixtures cannot claim live status. Authored fixtures, captured fixtures, test-double output, and
  pinned live output retain different origins.
- The live-capture writer deep-whitelists nested fields. A committed capture prevents another
  probe, while a fresh tree atomically records an output-independent attempt before dispatch, so
  changing `--out` or receiving a provider/normalization failure cannot replay the authorization.
- The default call ledger can run in memory for isolated tests, while the implementation supports
  a shared SQLite path with atomic reservation. Product wiring must supply a shared file-backed
  ledger rather than constructing one per adapter.

## Test coverage

The branch adds **344 weather tests** covering contracts, normalization, fixture replay, the real
stdio MCP boundary through a subprocess test double, upstream pin validation, registry activation,
kill-switch precedence, call-budget concurrency, circuit breaking, date semantics, malformed and
oversized responses, unsafe text, wrong server identity, forbidden tools, wrong endpoints,
timeouts, rate limits, unavailable providers, boundary imports, and network-bypass guards.

Fresh post-review verification before the final report commit:

- `make seed PY=.venv/bin/python`: **42 rows** across the unchanged seed tables;
- complete backend suite after seeding: **1610 passed, 1 skipped**, 3 existing OR-Tools
  deprecation warnings;
- focused weather suite: **344 passed**;
- strict mypy: **163 source files**, clean;
- weather/G4 Ruff scope: clean.

The authoritative final `make gate` is not yet claimed. It must be run after independent review,
all accepted review fixes, and the final report commit.

## Review

An independent whole-branch review (`codex review --base origin/main`) reported no Critical
findings and six P2 findings. All six were reproduced and fixed with regressions:

1. MCP 1.x was allowed by packaging despite 2.x-only response fields — dependency is now
   `mcp>=2.3,<3` and the supported/excluded lines are tested.
2. Capture sanitization copied nested dictionaries shallowly — current, daily, and unit objects
   are now independently projected onto explicit field allowlists.
3. A different output path could replay the one-call probe — the committed capture plus an atomic,
   output-independent pre-dispatch marker now enforce the authorization.
4. `ServerLaunch(is_pinned_upstream=True)` could forge live provenance — the constructor boolean
   is gone and factory attestation is not constructor-settable or retained by copies.
5. The community-maintained server was labelled `provider_mcp` — corrected to `community_mcp`.
6. Partial climate rows produced subset aggregates — any missing sample now preserves the metric
   as unavailable.

Review investigation also reproduced and closed three adjacent gaps: incomplete/gapped dated
windows, yesterday/tomorrow-start forecasts, and inherited HOME/user/path/shell/terminal values.
These are included in the 344-test focused slice.

## Known limitations and deferred work

1. Historical and climate tools have not been exercised against the real upstream server.
2. The adapter is not yet product-wired; no API/frontend weather surface is claimed.
3. A real product wiring must inject a durable shared call ledger and preserve fail-soft fallback.
4. Open-Meteo's free, non-commercial path is eligible only for the active student profile. Any
   commercialization requires a new provider/licensing review.

## Non-scope confirmation

No booking, payment, points transfer, financial-rule ingestion, crawler, dynamic MCP discovery,
credential, frontend, OpenAPI, conversational flow, Gondola implementation, authoritative spec,
golden value, seed value, or Tier-F arithmetic was changed. Nothing is pushed, merged, or deployed.
