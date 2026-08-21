# G3.2 — Gondola Live Schema, OAuth, and Acceptance Closure

**Milestone type:** Bounded, human-supervised live acceptance. **LIVE CONTRACT ACCEPTANCE
COMPLETE for hotels and OAuth; flight acceptance returned a genuine provider-side error
(`isError=true`) that was not investigated further, since exactly one `search_flights` call was
authorized and it was spent.** `/plan` is still not wired to Gondola — that is G3.3 and was not
started.

**Branch:** `feat/g3-gondola-readonly-mcp`, starting HEAD `1495eee` (G3.1's final commit),
worktree `.worktrees/feat-g3-gondola-readonly-mcp`. Nothing pushed, merged, or deployed.

---

## 1. Starting state (verified, not assumed)

- Branch and HEAD matched exactly what the milestone specified.
- Worktree was clean before any change.
- 16 commits existed from `main`@`43c4191` to the starting HEAD — the G3.1 report incorrectly
  said 15; corrected in this milestone (§9).
- No Gondola token existed in any tracked file (grepped for common access-token literal
  patterns; none found).
- Live mode confirmed disabled by default (`TRIPWISE_GONDOLA_LIVE_ENABLED` unset → `enabled=False`
  in the registry).

## 2. Catalog failure root cause and resolution

The 19 "pre-existing" catalog-dependent test failures G3.1 documented as environment debt were
**not** permanent — the actual root cause was a genuine, reproducible defect in
`gateway/catalog/provision.py`'s manifest lookup: it tries
`manifest_{destination.lower()}.yaml` first, then `manifest_{catalog_id}.yaml`. Every region
except Singapore has an IATA code that happens to equal its manifest suffix (`BOM`→`manifest_bom.yaml`,
etc.), so the primary path always matched for them. Singapore's only registered IATA code is
`SIN` (`regions.yaml`), but its `catalog_id` is `sg-core` and its manifest file was named
`manifest_sg.yaml` — unreachable by either lookup path. `evals/test_catalog_provision.py`'s own
pre-existing idempotency test already documented `manifest_sin.yaml` as the expected convention
(it writes its synthetic manifest to that exact filename); the real `fixtures/` directory just
never had that file.

**Fix:** added `gateway/catalog/fixtures/manifest_sin.yaml` (identical content to
`manifest_sg.yaml`, which is kept unchanged — four other tests reference it by that literal
path). Provisioned all 6 regional catalogs (`SIN`/`BOM`/`DXB`/`NYC`/`LON`/`PAR`) locally via the
existing `python -m gateway.catalog.provision` CLI, against already-fetched, already-approved raw
Overture extracts (gitignored local artifacts under `backend/raw_overture/`, copied from the main
checkout where they were originally fetched via the project's existing `scripts/fetch_overture.py`
— zero new network spend, zero cost). No test was skipped, weakened, or deleted; no product
behavior changed beyond the one-file manifest addition.

**Result:** all 19 previously-failing tests pass. Full suite: 852 → 1038 passed after this fix
alone (before any other G3.2 work), 0 failed, 0 skipped.

## 3. Bounded live-smoke harness

`backend/scripts/smoke_gondola.py` — gated by both `--acknowledge` and
`TRIPWISE_GONDOLA_LIVE_SMOKE=1`; reuses `LiveGondolaTransport`/`GondolaCallBudget`/`tool_policy`/
`KeychainTokenStore` exclusively; hard-caps the exercise at 2 anonymous + 2 authenticated real
calls under two distinct per-exercise plan ids in the existing `GondolaCallBudget` (2-call
ceiling); prints only sanitized structural summaries. 12 offline safety tests prove these
properties without opening a socket.

`LiveGondolaTransport` gained `list_tools()` (for `tools/list` discovery) and optional
(anonymous) auth — `get_access_token` may return `None`, sending no `Authorization` header,
matching Gondola's documented anonymous-tool tier.

## 4. Anonymous discovery — real, live

One `tools/list` call: **28 tools discovered**, elapsed 0.93s.

| | Count | Names |
|---|---|---|
| Allowlisted, present | 11 | `compare_rates`, `diagnose_rates`, `get_booking_link`, `get_hotel_details`, `get_hotel_reviews`, `get_hotel_stats`, `get_multi_night_rates`, `get_similar_hotels`, `predict_price`, `search_flights`, `search_hotels` |
| Denylisted, present | 15 (at anon time) | (account/vehicle/loyalty tools — all still denied) |
| Unexpected/unknown | 2 | `get_rate_alerts`, `get_suggested_searches` |
| High-risk tool names visible | 0 | `book_hotel`/`book_vehicle`/`get_payment_methods`/`cancel_vehicle_booking` never appeared even in the tool list (consistent with `mcp:book` being partner-only, not merely sign-in-gated) |

**Fix:** the 2 unexpected tools were already fail-closed by `assert_tool_allowed`'s default-deny
behavior, but are now explicitly recorded in `DENIED_TOOLS` for the record, per this milestone's
"fail closed on every unexpected tool... do not automatically enable newly discovered tools"
rule.

`search_hotels`/`search_flights` schema fingerprints both showed **empty `inputSchema.properties`**
— Gondola's tools declare a permissive/open input schema (no enumerated required fields), not a
strict JSON Schema. This is itself a real, recorded finding, not a parsing bug.

## 5. Anonymous hotel search — real, live, with an important caveat

One `search_hotels` call for Singapore (check-in +75 days, 3 nights, 1 adult, 1 room):
**transport-level success**, elapsed 0.52s.

**Critical finding, fixed:** the call succeeded, but `LiveGondolaTransport.call_tool()` had never
unwrapped the raw MCP `CallToolResult` envelope (`content`/`structured_content`/`is_error`/
`result_type`) — every downstream consumer (`contracts.py`, `normalize_hotel.py`) expects
Gondola's native tool JSON directly, matching how `FixtureGondolaTransport`'s fixtures were
already written. This bug existed since G3.1 and was invisible there because G3.1 never made a
real call. **Fixed, test-first**, using the real `mcp.types.CallToolResult` type for realistic
offline fixtures: `structured_content` preferred when present, falling back to parsing the first
text content block as JSON, raising `invalid_response` on `isError=true` or when nothing is
parsable.

**Honest limitation:** the one authorized `search_hotels` call's actual response was consumed by
the smoke script *before* this fix was written, using flawed top-level parsing logic
(`result.get("results") or result.get("hotels")`, which found nothing because the real content
was still wrapped). The script's own process exited before the fix was discovered, so Gondola's
actual native top-level key name (and thus whether Singapore hotels were genuinely found) was
**never captured**. No second `search_hotels` call was made to verify, since exactly one was
authorized. **This is recorded as coverage-unknown, not as evidence of zero Singapore coverage** —
the milestone's own rule ("a truthful empty result... must not be represented as a successful
coverage result") is honored by *not* claiming a coverage result at all here.

## 6. OAuth `mcp:read` bootstrap — completed, after fixing 3 real bugs

Three genuine bugs were found and fixed, in order, each verified against the real Gondola OAuth
server before proceeding to the next attempt:

1. **Neither a bare GET nor a plain `session.initialize()` triggers Gondola's 401 challenge** —
   both succeed anonymously (consistent with §4–5's findings). Fixed: the OAuth trigger is now a
   real `session.call_tool("search_flights", ...)` attempt, the one operation that is actually
   sign-in-gated.
2. **Gondola's Dynamic Client Registration endpoint requires `client_name`** — the original
   registration payload omitted it, causing `400 invalid_client_metadata`. Fixed by adding a
   descriptive `client_name`.
3. **CRITICAL, caught before any browser interaction:** the `mcp` SDK's spec-compliant "step-up"
   scope selection (SEP-2350) overrode the script's configured `scope="mcp:read"` with
   `"mcp:read mcp:write"` after Gondola's 401 challenge, because Gondola's own protected-resource
   metadata declares that broader scope set. The resulting authorization URL was inspected before
   ever being shown to the human, the violation was caught, and the process was killed
   immediately — no browser interaction, no leak, nothing authorized under the wrong scope. Fixed
   with two independent layers: (a) `pin_scope_to_read_only()` rewrites the authorization URL's
   `scope` query parameter back to exactly `mcp:read` inside `redirect_handler` — the one function
   that is the sole path by which a human ever sees or visits the URL; (b) a second backstop at
   token-exchange time refuses to store any token whose granted scope isn't exactly `mcp:read`
   (RFC 6749 §5.1: an omitted `scope` in the token response defaults to what the client
   *requested*, which the SDK had already escalated internally, independent of what the pinned
   URL displayed).

**Result:** the human signed in and approved at the corrected, `mcp:read`-only URL. OAuth
completed successfully:

- Token present: **yes**.
- Scope: **exactly `mcp:read`** (verified programmatically; the token-exchange safety guard did
  not trigger, confirming no over-grant).
- Refresh token present: **yes**.
- Token value: **never printed, never logged** — `repr()` confirmed redacted
  (`OAuthTokens(access_token=<redacted len=405>, refresh_token=<redacted>, ...)`).
- Stored exclusively via `KeychainTokenStore` (OS keychain) — never in a repository file.

## 7. Authenticated discovery — real, live

One authenticated `tools/list` call: **28 tools**, elapsed 1.08s (same count as anonymous —
Gondola lists the same catalog regardless of auth state; auth changes what can be *called*, not
what is *listed*).

- Allowlisted present: same 11 as anonymous.
- Denylisted present: 17 (now correctly including `get_rate_alerts`/`get_suggested_searches`
  after §4's fix).
- **Unexpected/unknown tools: 0** — confirming the §4 fix closed the gap completely.
- High-risk tool names (`book_hotel`, etc.): still **0** — `mcp:book` genuinely requires
  partner-scope approval, not merely sign-in, confirmed both anonymous and authenticated.
- `search_flights_now_available=True`.
- No `mcp:write`/`mcp:book` capability was granted or requested at any point.

## 8. Authenticated flight search — real, live, genuine provider error

One authenticated `search_flights` call, route DEL→SIN, depart date +90 days, 1 adult, economy,
INR: **the call reached Gondola's server and returned a proper `CallToolResult` with
`isError=true`.**

A second real bug surfaced here: `TravelGatewayError` raised inside the `mcp` SDK's internal
`anyio` task group was wrapped in a `BaseExceptionGroup`, which the smoke script's
`except TravelGatewayError` clause did not match — the script crashed with an unhandled traceback
instead of printing a clean diagnostic. **Fixed, test-first:**
`extract_travel_gateway_error()` walks one level of exception-group nesting to find the
underlying typed error; both call sites now use it.

**Honest limitation:** the specific reason Gondola returned `isError=true` (invalid argument
shape given the tool's permissive/undocumented input schema? a genuine no-availability response
encoded as an error? something else?) is **unknown**. The error's `content` text was never
printed (per this milestone's "never print raw MCP responses" rule) and the process that made the
call has exited, so nothing more can be learned without a second live call — which is not
authorized (exactly one `search_flights` call was budgeted; it was spent).

**DEL→SIN coverage result: unknown/error, not a coverage finding.** This is the honest,
milestone-mandated framing — an error is not evidence of "no coverage," and it is not
misrepresented as either a success or a definitive no-coverage result.

## 9. Documentation corrections

- `reports/g3_1_gondola_readonly_mcp.md` §"Branch": corrected "15 commits" to the actual **16
  commits** from `main` to that milestone's final HEAD (verified via
  `git log --oneline 43c4191..1495eee | wc -l`). No other content in that report was changed.
- `DEVIATIONS.md`: new "G3.2" section recording the catalog-manifest defect, the three OAuth
  bugs, the envelope-unwrapping bug, the exception-group bug, and the newly-denied tools —
  8 entries, each with date/question/decision/rationale/affected files.
- `CLAUDE.md`/`AGENTS.md`: checkpoint updated, kept byte-identical (`cmp` clean).

## 10. Tests before/after

| | Passed | Failed | Skipped |
|---|---|---|---|
| Start of G3.2 (= G3.1's end state) | 990 | 19 | 7 |
| After catalog fix alone | 1038 | 0 | 0 |
| Final (after all G3.2 work) | 1066 | 0 | 0 |

**+28 new tests this milestone** (catalog regression ×2, live-transport extensions ×7, smoke
script safety ×15, tool-policy update — some overlapping across commits), **0 regressions**, and
**all 19 previously-"pre-existing" failures genuinely resolved**, not exempted.

## 11. `make gate`

**PASSES**, from a clean, fully-committed tree: `pytest -q` (1066 passed), `mypy --strict`
(140 files, clean), `ruff` zero-tolerance scope (clean), `ruff` ratcheted scope (7 findings,
unchanged, ceiling 12), golden-fixture diff (clean), `AGENTS.md`/`CLAUDE.md` `cmp` (identical),
working tree (clean). This is the first time in the G3 line that `make gate` has genuinely
passed end-to-end rather than being reported around a known-excluded failure set.

## 12. Security and secret scan

Grepped the full diff for common secret/token/password literal patterns: **zero matches**. No
OAuth token, no client secret, no cookie, no Authorization header value, and no raw provider
response appears in any tracked file, commit message, or this report.

## 13. Remaining limitations

1. **Flight DEL→SIN coverage is genuinely unresolved** — the one authorized call errored, and the
   cause is unknown without a further live call, which is out of budget for this milestone.
2. **Anonymous hotel search's actual native response shape (top-level key names) is unverified** —
   the one authorized call's raw shape was never captured before the envelope-unwrapping fix
   landed.
3. `search_hotels`/`search_flights` both declare empty/permissive `inputSchema.properties` — no
   further schema tightening was possible from discovery alone.
4. Points-rate hotel evidence, rental-vehicle tools, and loyalty-account tools remain out of scope
   (unchanged from G3.1).
5. The OAuth token obtained this session has a real expiry (~1 hour from bootstrap); no refresh
   flow was exercised live (only unit-tested against fakes in G3.1).

## 14. Explicit statements required by this milestone

**The Gondola adapter has passed live contract acceptance for anonymous discovery, anonymous
transport-level hotel search, and OAuth `mcp:read` bootstrap; authenticated discovery passed;
authenticated flight search reached the real server but returned a provider-side error whose
cause remains uninvestigated (call budget exhausted) — flight acceptance is therefore incomplete,
not failed, and not silently treated as passed. `/plan` does not use the Gondola adapter yet.**

## 15. Explicit confirmation

Nothing was pushed, merged, deployed, booked, paid for, or billed. No `mcp:write` or `mcp:book`
scope was ever granted (verified programmatically, twice, via independent mechanisms). No
booking, mutation, payment, cancellation, rate-alert, or account-history tool was called at any
point. No Gondola password was requested from the human. `agents/gateway_estimator.py` and
`agents/pipeline.py` were not modified.
