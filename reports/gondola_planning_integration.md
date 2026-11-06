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

The corrected auth-only bootstrap was then exercised live: the callback was
accepted, the token was persisted, and a fresh OS-keychain reload showed
non-expired `mcp:read` credentials. The first remaining hotel call was sent
with `Singapore`, `2027-02-10` through `2027-02-13`, and one adult. Gondola's
MCP response timed out at the existing bounded transport timeout before any
hotel result or identifier arrived. That call counts as consumed; the dated
rate call was not made because there was no returned identifier to use.

The timeout was traced to the HTTP layer: the exception chain was an AnyIO
`BaseExceptionGroup` containing `httpx2.ReadTimeout` while waiting for MCP POST
response headers, with roughly 25 seconds elapsed. It was not a provider
timeout response, an outer application deadline, or an MCP session error.
`httpx2.Timeout(20, connect=10)` supplied a 20-second per-operation read
timeout, not an end-to-end deadline. The transport now uses a 40-second finite
HTTP operation timeout and an explicit 45-second cancellation deadline, within
the 60-second request budget, and maps wrapped timeout chains to the existing
typed timeout fallback. A delayed MCP-response regression exercises
cancellation locally.

Consequently, the following remain separate and explicit:

- authentication: successful on the corrected callback/storage path and
  confirmed by safe metadata reload;
- hotel search: the corrected retry completed within the revised deadline but
  returned only a Markdown envelope and no hotel identifier;
- dated hotel rates: not attempted because no valid identifier was returned;
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

- The fresh OAuth credential persisted successfully and survives safe reload.
  Two of the three authorized diagnostic calls are now consumed: the earlier
  flight timeout and the hotel-search timeout. The final rate call was not
  spent without a provider-returned hotel identifier. Live activation remains
  disabled.
- The OAuth callback fix is covered by focused tests against the installed MCP
  SDK: decoded `iss` is forwarded unchanged, absent/mismatched issuers remain
  subject to SDK rejection, state is preserved, duplicate security parameters
  fail closed, and callback secrets are not logged.
- The authentication lifecycle regressions cover persistence before a
  downstream timeout, omitted-scope handling, unexpected-scope rejection,
  refresh-token rotation, and secure-storage failure propagation. The final
  rate call was not dispatched because the hotel search returned no identifier.
- Gondola's previously observed Markdown response still lacks a typed,
  independently verified quote contract. No `SampleFlight`/`SampleHotel`
  record was manufactured from it.
- The existing application request dimensions that Gondola does not advertise
  (hotel style/currency and flight currency/nonstop/nearby-airport) continue to
  fail closed in the request builders; they are never silently dropped.
- The original three-call authorization had one call reserved for
  `get_hotel_rates`; the prior hotel-search call was consumed by its HTTP
  timeout. A subsequent fresh human-supervised authorization was completed and
  the corrected search retry was dispatched without retrying the flight.
- The corrected transport deadline was exercised live successfully at the HTTP
  boundary, but the response contract remains discovery Markdown rather than
  typed inventory. Existing planning replay proves this envelope remains
  non-costable and the application keeps its sample fallback.
- The subsequent human-authorized run completed authentication and immediately
  retried the corrected hotel search. The token was present, scoped exactly to
  `mcp:read`, and non-expired at dispatch. The search completed within the new
  45-second deadline, but Gondola returned only the observed
  `{"result": "..."}` Markdown envelope; no hotel identifier was available.
  The remaining `get_hotel_rates` call was therefore not dispatched. The live
  response was not retained beyond its bounded structural classification.
- No `agents/pipeline.py`, Kernel arithmetic, seed, OpenAPI, frontend, OpenBnB,
  or weather code was changed.
## Verification

The exact gate on commit `9876e2d41976e26c6ec023b99839804b8677ae82` passed:
3,088 backend tests passed, 53 skipped, and 3 warnings; strict mypy passed for
201 core/runtime files, 34 ingestion files, and 4 welcome files; zero-tolerance
Ruff passed; the legacy core/api ceiling was 8 findings against a ceiling of
12; `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, and `TREE_CLEAN` all
passed. This report-only update records the live result after that gate; no
source behavior changed afterward.

End of report.
