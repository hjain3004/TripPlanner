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
The SDK then required a fresh interactive authorization. The diagnostic
stopped at that boundary; no inbox connection, payment, broader access,
additional scope, booking, mutation, or ongoing application traffic was
attempted. No `tools/call` response was retained or used as a fixture, and no
provider quote was promoted.

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

- A valid refreshed credential or interactive reauthorization is required
  before any future human-supervised diagnostic. The current stored OAuth
  registration cannot refresh (HTTP 404), so live activation remains disabled.
- Gondola's previously observed Markdown response still lacks a typed,
  independently verified quote contract. No `SampleFlight`/`SampleHotel`
  record was manufactured from it.
- The existing application request dimensions that Gondola does not advertise
  (hotel style/currency and flight currency/nonstop/nearby-airport) continue to
  fail closed in the request builders; they are never silently dropped.
- No `agents/pipeline.py`, Kernel arithmetic, seed, OpenAPI, frontend, OpenBnB,
  or weather code was changed.
## Verification

The final functional gate phases passed on the seeded tree: 3076 backend tests
passed, 53 skipped, and 3 warnings; strict mypy passed for 201 core/runtime
files, 34 ingestion files, and 4 welcome files; zero-tolerance Ruff passed;
the legacy core/api ceiling was 8 findings against a ceiling of 12; goldens,
contract drift and brief identity checks passed. The first exact gate stopped
only because the tree was intentionally uncommitted. After the normal commit,
  the exact clean-tree gate is rerun and recorded with the final commit.

End of report.
