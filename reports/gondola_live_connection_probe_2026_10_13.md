# Gondola live connection probe

**Date:** 2026-10-13 (America/Los_Angeles)
**Status:** LIVE AUTHENTICATION AND SEARCH TRANSPORT VERIFIED; PRODUCT INTEGRATION ACCEPTANCE PENDING
**Source checkout:** `codex/g3-4-confirmed-brief-gateway` at
`5ffbbe85c0349b48098887b79e165139f08fe480`.
**Human authority:** explicit permission to use existing read-only Gondola keychain credentials
and request sign-in if necessary. Zero out-of-pocket cost remains mandatory; open-source hosted
execution is no longer a selection blocker.

## Result

Real OAuth refresh and both read-only search calls succeeded. Neither search returned the typed
hotel/flight record list required by our current native contracts. Both returned an object with
a `result` string that was not a JSON-encoded object/list. This does not establish cash-quote
accuracy, price scope, completeness, availability, taxes, coverage or successful normalization.
No model or parser guessed missing financial fields. Product live-provider defaults remain off.

## Credential and endpoint verification

- The initial sandboxed keychain read failed with `KeyringError`. Authorized host-level access
  found the existing token and registration; only presence, scope, expiry and refresh availability
  were printed, never token/client-secret values.
- Stored scope was exactly `mcp:read`. Its access token was locally expired; a refresh token and
  stored client registration were available.
- Read public protected-resource and authorization-server metadata at the fixed official HTTPS
  endpoints. Accepted the token endpoint only on `gondola.ai`/`www.gondola.ai`, with no redirects.
- Used the installed official MCP SDK's refresh request builder and response handler. The refresh
  succeeded, retained exactly `mcp:read`, rotated the refresh token and persisted the replacement
  exclusively in the OS keychain. No interactive reauthorization or new registration occurred.
- The existing SDK initialization loads tokens without restoring local expiry. This probe built
  and performed refresh explicitly rather than rerunning the old refresh script's already-known
  expiry-seeding workaround. This proves a real refresh, not a successful no-refresh decision.
- Anonymous MCP discovery used `https://mcp.gondola.ai/mcp`; authenticated search used the
  currently documented interactive endpoint `https://mcp.gondola.ai/mcp/auth`. No runtime source
  or configuration was changed to these endpoints.

## Tool discovery and bounded search ledger

One anonymous `tools/list` returned **46 tools**. **Correction, 2026-10-14:** this probe inspected
camelCase `inputSchema` instead of the installed SDK's `input_schema`; its apparent empty schemas
were a diagnostic bug, not a server finding. The follow-up report captures the actual schemas.
Booking,
payment and account tools were visible; our code-owned default-deny tool policy remained enforced
and none of these tools was invoked. Observed availability never widened the allowlist.

Both search dispatches checked `assert_tool_allowed` and reserved a durable slot before dispatch
through the existing `LiveGondolaTransport`. No automatic retry was added. The same plan identifier
was used for both calls; no fresh identifier was minted to evade the two-call ceiling.

| Probe | Exact request | Observed return |
|---|---|---|
| Hotel search | `location=Singapore`, `checkin=2027-01-11`, `checkout=2027-01-14`, `adults=1`, `rooms=1` | Transport returned successfully; `result` was a non-JSON string of 10,117 characters |
| Flight search | `origin=DEL`, `destination=SIN`, `departure_date=2027-01-11`, `adults=1`, `cabin=economy` | Transport returned successfully; `result` was a non-JSON string of 6,643 characters, 59 lines; no code fence/markdown table detected |

**Correction, 2026-10-14:** the actual schemas use `num_adults` for hotels and `num_passengers` /
`cabin_class` for flights, and advertise no room-count input for this hotel search. The earlier
calls did not prove the requested occupancy/cabin was honored; unknown parameters might have
been ignored. Do not treat their transport success as dimension-matching acceptance.

The temporary SQLite budget lives at
`/private/tmp/tripplanner-gondola-probe.Gn5DW7/budget.sqlite`, plan
`live-acceptance-2026-10-13`. **2 of 2 search slots were consumed.** No further search/detail/rate
tool call was attempted. This is a request-count ledger, not a claim to have measured provider-side
supplier units or account billing. No raw response, actual fare or private account data was saved;
recorded response evidence is structural metadata only. Do not call it a replay corpus or a
verified provider-data fixture.

## Fresh offline verification

Executed from this source checkout's `backend/`:

```text
PYTHONDONTWRITEBYTECODE=1 \
HYPOTHESIS_STORAGE_DIRECTORY=/private/tmp/tripplanner-gondola-probe.Gn5DW7/hypothesis \
.venv/bin/pytest -q -p no:cacheprovider \
evals/test_gondola_*.py evals/test_smoke_gondola_script.py

178 passed in 0.78s
```

These are the existing offline suites, not new regression tests for the live text shape or the
one-off refresh probe. No full backend/frontend suite or `make gate` was rerun; G3.4's previous
catalog-dependent acceptance failure is not closed by this result.

## Cost and privacy posture

The official [MCP page](https://www.gondola.ai/mcp) advertises a free MCP/free account; the
[traveler help page](https://www.gondola.ai/help/what-is-gondola) says there are no subscription,
extra booking or hidden charges for travelers. The [current integration guide](https://www.gondola.ai/help/mcp-oauth-integration)
documents sign-in and bounded search budgets. This supports the authorized low-volume personal
read-only test; no payment instrument, subscription, paid upgrade or billing configuration was
created/changed. No account billing dashboard was accessed, so this report does not claim an
independent billing audit or indefinite third-party embedding entitlement.

No `mcp:write`/`mcp:book` scope, booking/payment/transfer, account-history, loyalty-account or
credential-disclosure tool was used. Scope checks preceded credential persistence. No secret
entered source, report, terminal output, logs or fixtures.

## Next acceptance slice

The blocker is the live response contract, not connectivity. Design a narrow, test-first capture
and normalization slice that inspects the native response safely and identifies a machine-readable,
source-supported route to complete prices/segments. Any newly required rate/detail tool must receive
explicit code-owned allowlist review; do not bypass `assert_tool_allowed` in a diagnostic script.
Do not use LLM prose extraction or provider-written financial advice as authoritative price math.

Until field semantics, freshness, dimensions and failures are proved, leave product defaults off
and describe provider results as unverified search evidence, not admitted optimizer inputs.
Additional provider calls require a newly agreed probe budget; this probe's exhausted budget is
not reopened. API/frontend wiring requires the synchronized contract and complete applicable gates.

## Preserved state

The reference worktree remained clean at the same HEAD, with no product/source changes. The primary
checkout received only this new report; existing modified/untracked files, all other worktrees,
branches, authoritative specs, seeds/goldens and Tier-F arithmetic were preserved. No commit/push
was made. The intended credential side effect was refresh-token rotation in the OS keychain.
