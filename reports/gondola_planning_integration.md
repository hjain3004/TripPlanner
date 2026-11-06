# Gondola planning integration

Status: live hotel search and dated-rate retrieval demonstrated; real reported
rates reach authenticated planning and saved revisions as verify-required
alternatives. Final payable costing and live flight acceptance remain incomplete.

## Current delivered workflow (2026-11-05)

The approved Singapore search and dated-rate sequence now runs without losing
the explicit hotel identifier between calls. The live tool schema requires an
integer property ID. Authentication reused the existing current read-only
credential; no extra authentication tool call was needed.

The final explicitly approved pair completed: one search, immediately followed
by one `get_hotel_rates` call, with no retries or other supplier calls. The
returned Markdown explicitly states the stay (2027-02-10 to 2027-02-13, one
adult), room descriptions, nightly amounts, stay totals, and cancellation
conditions. For the first room the reported stay total was SGD 1970.94. It was
parsed to integer minor units without multiplying the nightly price or
calculating any missing taxes. Raw signed rate tokens are discarded by the
normalizer; none enters a public quote, report, fixture or commit.

The preceding diagnostic pair also succeeded, but its output filter omitted
rate rows along with booking tokens. Automatic approval review refused a
duplicate pair under the prior call limit. The human then explicitly approved
the additional two calls above. This was a local capture/diagnostic mistake,
not evidence that Gondola could not return prices. No further calls were made.

### What a traveler/API consumer can now receive

- Normal confirmed planning retains its sample-backed budget and returns
  Gondola room-price alternatives, including typed property and room names,
  source currency, stated stay total, provenance and explicit limitations.
- Incomplete provider alternatives no longer suppress a cost-eligible sample
  fallback or disappear from the final evidence summary.
- SGD prices remain in SGD when the requested display currency is INR. The
  adapter explicitly declares source-currency alternative support; this never
  authorizes that mismatched currency as a selected payable cost.
- Existing startup validation, default-off enablement and kill-switch precedence
  remain. An enabled local/demo factory now constructs the dated-hotel adapter
  using a shared file-backed reservation ledger. It does not auto-launch OAuth.
- One search plus one dated-rate request exhausts this adapter's per-plan budget.
  Flights remain on the sample path; no live flight response was captured.

The report does **not** claim a final tax-inclusive price: the observed response
did not explicitly establish tax/fee coverage or an admitted purchase channel.
Cancellation text includes estimates and provider verification caveats. Those
fields remain unknown/verify-required, and these rates are excluded from final
payable budgeting and card recommendations. Area/style/currency filtering is not
claimed for this city-scoped discovery path; that limitation is returned visibly.

### Actual application demonstration

The live response was kept in memory through normalization. Its normalized
public quote was replayed through sign-in, the typed interview, confirmation,
the actual planning pipeline, trip save, and revision retrieval after opening a
new SQLite store. The report retained the stated SGD amount and unchanged
evidence timestamps; the selected budget hotel remained the sample adapter.
The model was scripted. The application replay made no additional provider calls.
This demonstrates live retrieval followed by application replay, not a second
networked planning run or continuing live activation.

The local normalized quote (not raw Markdown, credentials or a signed rate
token) is outside Git at
`/private/tmp/tripwise-gondola-finish/normalized-hotel-quote.json`. Reproduce the
offline application demonstration while that file exists:

```sh
cd backend
PYTHONPATH="$PWD" .venv/bin/python -m evals.demo_gondola_hotel_plan \
  /private/tmp/tripwise-gondola-finish/normalized-hotel-quote.json
```

The normalization demonstration conservatively uses the capture-session start
as its evidence time; replay/save/reopen do not stamp it as freshly fetched.
The temporary process holding raw responses was closed after normalization.
The new regression inputs use synthetic names, IDs and prices with the
observed wire grammar; they make no live-data claim.

For a future separately authorized operator run, the reusable entry point is
`python -m gateway.travel.adapters.gondola.scripts.hotel_rates --help`.
It requires explicit read-only/zero-spend flags and current keychain credentials,
prints normalized public fields only, honors the kill switch and shares the
per-plan ledger. No further live invocation of that command was made here.

OpenAPI, generated types, frontend validation and MSW fixtures ship together
for the optional property/room names. No frontend redesign was undertaken.
Focused workflow checks and strict typing/lint pass. A focused independent
static review found no material defects in the rate parsing, budget, trust and
sample-fallback changes. Final exact-commit gate and CI evidence are recorded
on PR #29 after execution; older results below are historical.

## Historical implementation and diagnostic record

The remaining sections describe earlier revisions and are superseded by the
current delivered workflow above where they say rates were not obtained.

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
- hotel search: the corrected retry completed within the revised deadline and
  returned a Markdown envelope containing 20 explicitly formatted heading
  identifiers, but no identifier value was retained for safe rate selection;
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
  45-second deadline, and Gondola returned the observed
  `{"result": "..."}` Markdown envelope. The remaining
  `get_hotel_rates` call was not dispatched because identifier values were
  not retained beyond the bounded capture.
- A later bounded raw-envelope inspection confirmed `is_error=false`,
  `structured_content` present, one text content block of 10,033 UTF-8 bytes,
  and 20 identifiers matching the strict `### ... (ID: <identifier>)` heading
  form. Identifier values were deliberately not retained. The response still
  does not establish dated rate scope, currency, taxes/fees, room identity or
  cancellation terms, and no costable quote reached planning.
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
