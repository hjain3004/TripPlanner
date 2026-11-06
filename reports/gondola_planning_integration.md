# Gondola planning integration

Status: offline development complete; live priced integration blocked pending valid authenticated provider evidence.

## What shipped

- Added `backend/gateway/travel/adapters/gondola/live_adapter.py`, an explicit
  transport-to-gateway seam for typed hotel and flight result envelopes.
- The seam reuses the existing request builders, native contracts, sanitizers,
  normalizers, budget ledger, circuit breaker and `GondolaAdapter`; it rejects
  the observed `{result: string}` Markdown response before a quote can be
  admitted.
- Added an allowlisted `get_hotel_rates` request shape. It remains a reviewed
  diagnostic capability only: no rate response was obtained, so no guessed
  rate contract or priced integration was added.
- Updated human-supervised diagnostic scripts to use the official authenticated
  `/mcp/auth` endpoint while retaining the strict `https://mcp.gondola.ai`
  host restriction.
- Added offline adapter regressions proving typed fixture normalization,
  Markdown rejection, malformed-row typing, reviewed endpoint paths, and the
  disabled boundary without network access.

## Bounded diagnostic evidence

The official registry endpoint and authenticated call endpoint were verified
from Gondola's current documentation. `tools/list` inspection reported the
reviewed fields for `search_hotels`, `get_hotel_rates`, and `search_flights`.
The persisted OS-keychain token was checked to have exactly `mcp:read` scope.

The existing OAuth client registration's refresh request returned HTTP 404.
The bootstrap callback initially failed to forward the RFC 9207 `iss` value;
that was a local callback-parser defect, not evidence of a non-conforming
Gondola response. The corrected handler forwarded the decoded value unchanged,
and the installed SDK accepted the authorization response with `iss` present
and matching. The bootstrap's single authenticated `search_flights` request
then timed out before a token was persisted. That invocation counts against
the bounded diagnostic budget and was not retried. No inbox connection,
payment, broader access, additional scope, booking, mutation, or ongoing
application traffic was attempted. No provider quote was promoted.

The installed MCP SDK was also inspected for an auth-only public route. Its
standard `ping`, `resources/list`, and `resource-templates/list` requests are
ordinary MCP requests; the SDK exposes no public authorization-only method.
The bootstrap therefore retains the provider's existing authenticated-tool
challenge as the only observed trigger, but no second flight invocation was
made. The lifecycle fix now persists validated credentials from the SDK's
`set_tokens()` callback before any downstream request can time out, including
rotated refresh tokens; client registration remains OS-keychain-only.

Consequently, the following remain separate and explicit:

- current cash evidence: not captured in this diagnostic;
- cached award information: not captured and never promoted to availability;
- incomplete discovery: prior sanitized Markdown captures remain
  `verify_required`, non-costable discovery evidence;
- supported capability: read-only provider discovery and a dated-rate request
  shape are known, but a current authenticated typed rate/quote response is
  not established.

## Runtime boundary and demonstration

The confirmed-planning factory remains sample-only by default. Gondola live
construction requires explicit injection of the adapter and `live_enabled=True`;
the registry's existing environment kill switch and profile/cost checks remain
unchanged. Routine tests use only fixture transport. The offline demonstration
is:

```text
cd backend
.venv/bin/pytest -q evals/test_gondola_planning_integration.py
```

This exercises fixture transport → native Gondola contracts → normalized
gateway quotes, plus Markdown fail-closed behavior and zero dispatch while
disabled. It does not claim live provider coverage.

## Limitations and deviations

- The stored OAuth credential remains expired because the authenticated flight
  request timed out before the bootstrap could persist its newly obtained
  token. One of the three authorized diagnostic calls was consumed by that
  flight attempt; it will not be repeated. Live activation remains disabled.
- The OAuth callback fix is covered by focused tests against the installed MCP
  SDK: decoded `iss` is forwarded unchanged, absent/mismatched issuers remain
  subject to SDK rejection, state is preserved, duplicate security parameters
  fail closed, and callback secrets are not logged.
- The authentication lifecycle regressions cover persistence before a
  downstream timeout, omitted-scope handling, unexpected-scope rejection,
  refresh-token rotation, and secure-storage failure propagation. The two
  remaining hotel calls were not dispatched because no valid persisted token
  is available and the authorized flight call cannot be repeated.
- Gondola's previously observed Markdown response still lacks a typed,
  independently verified quote contract. No `SampleFlight`/`SampleHotel`
  record was manufactured from it.
- The existing application request dimensions that Gondola does not advertise
  (hotel style/currency and flight currency/nonstop/nearby-airport) continue to
  fail closed in the request builders; they are never silently dropped.
- No `agents/pipeline.py`, Kernel arithmetic, seed, OpenAPI, frontend, OpenBnB,
  or weather code was changed.
## Verification

The prior final functional gate phases passed on the seeded tree: 3076 backend tests
passed, 53 skipped, and 3 warnings; strict mypy passed for 201 core/runtime
files, 34 ingestion files, and 4 welcome files; zero-tolerance Ruff passed;
the legacy core/api ceiling was 8 findings against a ceiling of 12; goldens,
contract drift and brief identity checks passed. The exact clean-tree gate
passed on the committed implementation tree: `TREE_CLEAN` and
`================ GATE PASSED ================`.

End of report.
