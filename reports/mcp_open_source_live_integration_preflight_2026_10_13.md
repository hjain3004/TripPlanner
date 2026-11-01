# Open-source MCP live integration preflight

**Date:** 2026-10-13 (America/Los_Angeles)
**Status:** RESEARCH COMPLETE FOR INITIAL SHORTLIST — NO LIVE ACTIVATION; DESIGN PENDING
**Requested outcome:** integrate live travel MCPs and research useful additions. The human
subsequently clarified that accurate information at zero out-of-pocket cost takes precedence
over the original open-source requirement; hosted-provider execution is not a licensing blocker.
**Runtime reference inspected:** `codex/g3-4-confirmed-brief-gateway` at
`5ffbbe85c0349b48098887b79e165139f08fe480`.

## Clarified priority and initial licensing assessment

Open-source protocol, open-source connector, open-source executing server, and open travel data
are separate properties. A public GitHub repository is not enough. The initial assessment below
used the stricter executing-server criterion. The human has now removed that selection blocker:
hosted Gondola can be evaluated, without claiming its backend is open source.

Gondola and Tripadvisor remain disabled pending their access/data/cost gates, not solely licensing.
Do not replace existing adapters or activate
new providers merely to satisfy this research request. The existing student profile retains a
USD 0 out-of-pocket ceiling, read-only tools, no booking/payment/transfer execution, no access-control
bypass, and mandatory provider-specific activation review.

## Previously discussed providers

### Gondola: catalogue is open source; hosted execution is not established as open source

The public repository identifies an MIT license. However, its actual `server.js` implements
`tools/list` and returns an error pointing to the hosted endpoint for `tools/call`. It is not
the executable travel-search backend. This is direct source evidence, not a directory label.

The official integration guide, updated September 28, 2026, says all tool calls require a bearer
token, identifies `/mcp/auth` for interactive clients, and limits anonymous `/mcp` access to
discovery. This conflicts with the repository README's anonymous-search description and with
historical assumptions in our adapter. Treat authentication, endpoint and tool shapes as needing
fresh verification. Do not silently widen our fixed endpoint or OAuth scope allowlists.

Our prior structured hotel/flight normalization proof is still open; no fresh tool call,
credential lookup or OAuth flow was performed in this preflight. Hosted execution may become
eligible under the clarified requirement if the zero-spend/access review passes.

Sources:

- [Repository](https://github.com/gondola-ai/gondola-mcp)
- [Actual catalogue implementation](https://raw.githubusercontent.com/gondola-ai/gondola-mcp/main/server.js)
- [Current official integration guide](https://www.gondola.ai/help/mcp-oauth-integration)

### Tripadvisor Terra: hosted platform; open-source execution not verified

Official documentation exposes a hosted developer MCP and describes account/API/documentation
access. It does not establish a licensed, self-hostable source release for that server. Terra
access depends on subscription packages; rate quotas are not evidence of a zero-billing cap.
An existing Tripadvisor connector in the coding environment is not runtime activation permission.

Our fixture adapter and structural injected-client transport remain useful, but neither proves
the official live schema or data entitlement. Keep disabled pending source/access/billing review.

Sources:

- [Official MCP documentation](https://docs.terra.tripadvisor.com/reference/mcp)
- [Platform and package access](https://docs.terra.tripadvisor.com/docs/overview)
- [Rate limits and per-entity billing](https://docs.terra.tripadvisor.com/docs/rate-limits)

### OpenBnB: actual MIT server, not safe to activate unchanged

The repository contains an executable Airbnb search/listing server and identifies MIT licensing.
Its source implements runtime HTML fetching. It exposes global and per-call robots overrides,
uses a browser-shaped User-Agent for Airbnb, and treats robots fetch/parse errors as permission
to proceed. These require review against our no-circumvention and runtime crawling boundaries;
turning the override off alone does not resolve fail-open behavior.

No upstream code was installed or executed. Do not infer that the separate hosted openbnb.ai
service has the same source, license, terms or data behavior as this repository. OpenBnB is not
an initial production-path integration candidate under the current constraints.

Sources:

- [Repository and licensing](https://github.com/openbnb-org/mcp-server-airbnb)
- [Source: robots handling and outbound requests](https://raw.githubusercontent.com/openbnb-org/mcp-server-airbnb/main/index.ts)

## Additional candidates

These are research candidates, not audited/activated dependencies. Pin exact commits/releases and
review executable source, dependencies, endpoint policies, tool schemas and tests before adoption.

| Candidate | Published code license | Useful capability | Initial posture |
|---|---|---|---|
| `cyanheads/open-meteo-mcp-server` | Apache-2.0 | Weather, air quality and seasonal context | Strong first-spike candidate; locally run, narrow read-only allowlist, no optional storage/cloud/SQL tools |
| `weather-mcp/weather-mcp` | MIT | Alternative weather implementation using public APIs | Compare against the Open-Meteo candidate; choose one, not both by default |
| `ni-c/osm-mcp` | MIT | Walking/driving/cycling routes, matrices and POI lookup | Strong candidate, conditional on each upstream service's policy and appropriate endpoints |
| `wmde/WikidataMCP` | BSD-3-Clause | Destination/landmark identities and structured cultural facts | Reference enrichment only, never current price/availability evidence |
| `anirbanbasu/frankfurtermcp` | MIT (repository declaration) | Currency reference data | Lower priority: our existing G2 Frankfurter importer already owns this need |
| `fiqcodes/amadeus-mcp-server` | MIT (repository declaration) | Flight/hotel search connector | Not selected: defaults to test API, requires credentials; production billing/coverage unverified; provider-side FX conversion needs exclusion |

Sources:

- [Open-Meteo MCP](https://github.com/cyanheads/open-meteo-mcp-server)
- [Open-Meteo MCP license](https://github.com/cyanheads/open-meteo-mcp-server/blob/main/LICENSE)
- [Weather MCP](https://github.com/weather-mcp/weather-mcp)
- [Weather MCP license](https://github.com/weather-mcp/weather-mcp/blob/main/LICENSE)
- [OSM MCP](https://github.com/ni-c/osm-mcp)
- [Wikidata MCP](https://github.com/wmde/WikidataMCP)
- [Wikidata MCP license](https://raw.githubusercontent.com/wmde/WikidataMCP/main/LICENSE)
- [Official Wikidata MCP documentation](https://www.wikidata.org/wiki/Wikidata:MCP)
- [Frankfurter MCP](https://github.com/anirbanbasu/frankfurtermcp)
- [Amadeus community connector](https://github.com/fiqcodes/amadeus-mcp-server)

## Service-policy caveats

Open-Meteo's free API permits non-commercial use with attribution and published request limits.
Weather forecasts, historical observations and climate projections must be separate evidence
types: no distant-trip day-by-day forecast invented from seasonal averages. The reviewed
Open-Meteo MCP documents ordinary forecast requests for 1–16 days. Its current package also has
runtime/dependency requirements to review; this report does not certify supply-chain safety.

Nominatim's public service has a maximum of one request/second across the whole application,
requires identification/attribution/caching, forbids autocomplete and systematic extraction, and
requires a deliberate informed developer decision for use in LLM-built applications. Its policy
does not apply identically to self-hosted or other organisations' instances. Do not automatically
adopt the public endpoint, or treat the wrapper's compliance claim as proof. OSM routing is not
public-transit routing; returned paths/modes and service coverage must be checked independently.

Wikidata enrichment needs source/qualifier preservation and bounded queries. The documented
`get_statements` tool omits references/qualifiers; use a reference-preserving path when evidence
requires them. Restrict arbitrary SPARQL/remote service clauses rather than allowing free-form
model network queries.

Sources:

- [Open-Meteo terms](https://open-meteo.com/en/terms)
- [Nominatim public-service policy](https://operations.osmfoundation.org/policies/nominatim/)
- [Wikidata tool semantics](https://www.wikidata.org/wiki/Wikidata:MCP)

## Additional flight candidate excluded from the open-source shortlist

Kiwi.com's official public repository contains installation instructions and a hosted MCP URL,
but the inspected file tree contains only a README; an executable licensed server implementation
was not established. Do not label it open source because installation instructions are public.

Source: [Official Kiwi installation repository](https://github.com/alpic-ai/kiwi-mcp-server-public).

## Proposed delivery order, not approved implementation

1. The human has clarified that accurate zero-cost data matters more than provider implementation
   licensing. Prioritize the existing Gondola integration's live proof. No verified complete
   open-source live fare/hotel backend was established by this initial shortlist.
2. Restore and verify the G3.4 baseline using the existing approved local catalog artifacts. This
   is an outstanding acceptance prerequisite, not an exemption or changed golden expectation.
3. Design one narrow integration slice. Weather has the clearest anonymous, zero-spend path;
   OSM routing/POI is next after service-policy checks. Proprietary hosted execution is now
   permitted by the human's clarified selection criterion; prioritize Gondola's missing live
   search proof rather than claiming
   weather completes live travel inventory.
4. For each slice: fixed endpoints/tools, immutable version pinning, bounded inputs/results,
   timeouts, durable budgets where applicable, kill switch, source/freshness metadata, no secrets
   in logs, no financial math delegated to MCP, and deterministic fixture/failure coverage.
5. After design approval and offline gates, run a small explicitly bounded real MCP probe;
   capture sanitized native responses and prove normalization without inventing missing fields.
6. Wire accepted evidence through `backend/gateway/` and the synchronized API/frontend contract.
   Installing a desktop MCP is not application integration. No browser-to-provider credentials,
   no core network imports, no dynamic production provider discovery, and no booking tools.

## Verification and preserved state

### Follow-up: zero-cost Gondola verification

The official [MCP page](https://www.gondola.ai/mcp) labels the MCP server free and offers a free
account; the [traveler help page](https://www.gondola.ai/help/what-is-gondola) says there are no
subscription, extra booking or hidden charges for travelers. This supports a free personal
read-only evaluation, not an unverified claim about third-party embedding rights or unlimited use.
The current integration guide requires sign-in, defines search quotas and supports `mcp:read`.
The proposed first slice is bounded hotel/flight response capture and normalization proof,
without booking/account-history tools, write scopes, billing setup or default product activation.
Existing credentials were not read. Human permission for read-only credential use/re-authentication
is still needed before authenticated execution. The existing bootstrap invokes a flight tool and
uses historical endpoint/auth assumptions, so it must not be run unchanged as a supposedly
credential-only operation without reviewing those behaviors.

- Research read public official documentation, repositories and selected source/license files.
- No claim of exhaustive source audit, working transport, live coverage or successful MCP handshake.
- No provider tool invocation, package install, OAuth, keychain access, billing, booking, transfer
  or backend/frontend implementation occurred.
- Firecrawl status could not fetch account information; built-in web research was used instead,
  without consuming Firecrawl credits.
- No application test or gate was run for this research-only artifact. G3.4 remains acceptance pending.
- The primary checkout's existing modified `DEVIATIONS.md`, untracked reports/tools/examples/plans,
  and all other worktrees/branches were preserved. Only this new report was added; no commit/push.
- Authoritative specifications, financial seeds/goldens, core arithmetic, API contract and runtime
  configuration remain unchanged by this preflight.
