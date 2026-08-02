# Itinerary Intelligence & Venue Discovery — design

**Date:** 2026-08-02  
**Status:** DESIGN — approved direction from brainstorming; awaiting review of this written form  
**Scope:** Target-prototype itinerary intelligence after the Kernel MVP/frontend foundations  
**Depends on:** specs 06, 08, 09 and 16; the evidence-graph design; the existing itinerary-accuracy plan  
**Does not change:** Kernel money math, the four named LLM call sites, booking/transfer prohibitions, or provider activation rules

This document resolves the itinerary-planner data problem without pretending that a single
third-party MCP server is the product. It describes a phased, testable system that can discover
venues beyond local seed data, prove where its facts came from, construct feasible days, and
degrade honestly when live evidence is missing.

The first corridor remains India to Singapore. The active user markets are India, the UAE and
the USA. Supported destination families are India, the UAE, the USA, Europe, the UK and
Singapore. Worldwide coverage is a later expansion, not a reason to build worldwide-scale
infrastructure now.

---

## 1. Decision summary

The itinerary feature is a **layered subsystem**, not an MCP integration:

1. An offline place-evidence pipeline builds a useful, attributable candidate catalog from
   Overture Maps, Wikivoyage/Wikidata and selective OpenStreetMap enrichment.
2. The gateway exposes one stable, typed place-search interface regardless of whether the
   backing source is a local snapshot, an HTTP API or an MCP transport.
3. The existing itinerary LLM call may express user intent, generate search queries, shortlist
   evidence-backed candidates and explain trade-offs.
4. Deterministic code validates identity, provenance, freshness, opening-hours feasibility,
   route feasibility and schedule constraints.
5. OR-Tools may optimize a day only after the basic deterministic composer and its fallback are
   correct. It is an implementation detail, not the source of truth.
6. MapLibre renders the resulting route and evidence. The frontend renders fields; it does not
   infer feasibility, trust or prices.
7. MCP is an optional transport behind a reviewed adapter. The LLM never discovers arbitrary
   MCP servers or selects a provider by name.

The product therefore remains useful with **zero external itinerary MCP servers connected**.
An MCP can improve coverage later, but cannot own the itinerary contract or bypass validation.

---

## 2. Goals and non-goals

### Goals

- Discover attractions, activities, neighborhoods, restaurants, cafes and shopping venues that
  are not in the current seed database.
- Produce realistic days that respect travel time, opening hours, arrival/departure constraints,
  pace, meal/rest windows and user preferences.
- Let the LLM contribute taste and query formulation without inventing usable facts.
- Preserve field-level provenance and visible uncertainty through the evidence graph and UI.
- Work offline in CI and in a no-credential student demo using pinned snapshots and fixtures.
- Allow better live sources to be added later without changing the planner or frontend contract.
- Establish a repeatable regional rollout process rather than hard-coding Singapore forever.

### Non-goals for this program

- Booking, purchasing, calling venues or executing points transfers.
- Live events, nightlife inventories, ticket availability or reservation completion in the first
  itinerary release.
- Unapproved automated request-time scraping of Google Maps, Tripadvisor, Booking.com,
  Skyscanner, Google Flights or other consumer booking/search **web pages** as if they were
  stable application APIs.
- Treating an LLM's remembered venue details as evidence.
- Worldwide ingestion, public routing infrastructure, high-volume SLAs or commercial licensing.
- Dynamic provider/MCP discovery, arbitrary URL fetching or provider-specific tools exposed
  directly to the model.
- Using an LLM to compute money, points, route durations, opening-hours validity or the final
  schedule feasibility verdict.

This does **not** prohibit using those companies. Official APIs, official MCP servers, approved
partner feeds, sandbox access, compliant deep links and explicit user-facing verification are in
scope when their adapter passes spec 16. The distinction is between authorized structured access
and an unreviewed scraper that breaks whenever a consumer page or anti-bot control changes.

Spec 05's offline, source-reviewed acquisition of financial rules also remains in scope. It is a
batch proposal pipeline with human approval, not request-time scraping of live booking inventory.

---

## 3. System boundary

```text
TripSpec + wallet + preferences
             |
             v
Target orchestrator (fixed state machine + PlanBudget)
             |
             +--> Itinerary workflow / existing itinerary LLM call site
             |       - proposes search intent
             |       - calls one typed search_places tool in a bounded loop
             |       - ranks/explains only returned candidate IDs
             |
             +--> Data Gateway -----------------------------------+
             |       - fixed provider registry                    |
             |       - normalization and validation               |
             |       - no provider choice by the LLM              |
             |                                                    |
             |       +--> snapshot adapters: Overture/Wiki/OSM    |
             |       +--> optional HTTP/MCP adapters later         |
             |                                                    |
             +--> Evidence graph <--------------------------------+
             |       claims, sources, runs, artifacts, evaluations
             |
             +--> RouteMatrix provider
             |
             +--> Deterministic itinerary composer
                     - constraints and feasibility
                     - OR-Tools optimizer when enabled
                     - deterministic fallback always available
                             |
                             v
                 ItineraryDraft + ValidationReport
                             |
                             v
               existing critic / grounded explainer / UI
```

The itinerary workflow receives only normalized contracts and stable IDs. Raw provider payloads,
credentials, SQL, URLs and MCP protocol details stop at the gateway.

`backend/core/` remains pure and does not import the gateway. New provider and ingestion code
lives under `backend/gateway/` and `backend/ingestion/`. Orchestration marshals validated
gateway output into deterministic itinerary inputs.

---

## 4. The LLM may discover new venues

The constraint is **not** “the LLM may only repeat venues already in local seed data.” The
constraint is “the LLM may not turn an unsupported memory into a final itinerary fact.”

The allowed flow is:

1. The LLM translates the trip into typed search intents such as “quiet hawker centre near
   Chinatown, open for an early dinner” or “rain-safe design museum within 25 minutes of the
   hotel.”
2. It calls the single first-party `search_places` tool. The gateway, not the LLM, selects from
   the fixed active adapters.
3. The gateway returns normalized, evidence-backed candidates with stable IDs, claim-level
   provenance and completeness flags.
4. The LLM can broaden/narrow the query, shortlist candidates and state qualitative reasons.
5. Deterministic code checks feasibility and constructs the schedule.
6. Only candidate IDs returned by the gateway may enter a committed itinerary.

If the LLM mentions a venue from memory, that name is only an unverified `DiscoveryCandidate`.
The system performs an exact or alias-aware gateway lookup. If identity and minimum evidence
cannot be established, the venue is excluded from the committed schedule and may appear only as
an explicitly unverified suggestion outside the plan.

### Initial student-profile loop budget

- At most 3 discovery rounds.
- At most 6 total `search_places` calls.
- At most 40 normalized candidates retained across the run.
- At most 12 candidates sent to the schedule composer per destination day.
- No arbitrary URLs and no provider-specific tool names in the model context.
- Exhaustion returns a typed partial result with unresolved needs; it never silently fabricates
  a complete itinerary.

These are Tier-C configuration defaults. They can be tuned after measured evaluations without
changing the contract or adding autonomy.

---

## 5. Normalized place evidence

### 5.1 Stable identity

Every place has an internal `PlaceId` and a set of namespaced external identifiers. Examples:

- `overture:...`
- `osm:node/...`, `osm:way/...` or `osm:relation/...`
- `wikidata:Q...`
- `tomtom:...` only when that adapter is explicitly activated

Names are never primary keys. Identity resolution is deterministic and reversible. An automatic
merge requires an exact shared external identifier or a named rule that combines normalized name,
category and distance within a category-specific threshold. Ambiguous matches remain separate and
surface for review; the LLM does not arbitrate them.

### 5.2 Claim-level provenance

A place is an entity assembled from claims, not one mutable provider blob. Each material field
is a claim carrying:

- `source_id` and `source_url` where one exists
- `retrieved_at` and `source_release`
- `last_verified`
- `verified_by`
- `confidence`
- `needs_verification`
- `licence_id` and attribution requirements
- lifecycle state: active, stale or superseded

Coordinates, category, opening hours, description, accessibility and admission are separate
claims because the best source and freshness policy differ by meaning.

### 5.3 Source authority by meaning

| Meaning | Preferred source order | Important limitation |
|---|---|---|
| Existence, coordinates, broad category | Overture source record, then OSM | Coverage and upstream licensing vary per record |
| Editorial context and neighborhood narrative | Wikivoyage/Wikidata | Text is untrusted input and may be stale |
| Opening hours and accessibility | Official venue source when available, then current OSM claim | Missing/complex hours must remain unknown |
| Route duration | Approved route-matrix adapter, then deterministic geodesic estimate | An estimate is never labeled routed travel time |
| Admission/reservation requirement | Official venue source only for a trusted claim | Aggregator or LLM text is discovery-only |
| Live closure/crowding/ticket inventory | No default source in the first release | Render verification guidance instead |

Contradictions are retained as graph edges. The selected claim is the result of a deterministic,
field-specific authority and freshness rule; losing claims remain addressable.

### 5.4 Freshness classes

| Claim class | Policy |
|---|---|
| Identity/coordinates | Snapshot-versioned; revalidate on source refresh |
| Category/basic tags | Snapshot-versioned; warn on stale source release |
| Editorial description | Long-lived but always attributed |
| Opening hours/accessibility | Time-sensitive; stale or absent becomes `verify_required` |
| Admission/reservation | Time-sensitive and official-source-only for trusted status |
| Route matrix | Request-scoped with mode, timestamp and provider/estimate status |

Known closed means infeasible. Known open means eligible. Unknown hours do not magically become
open: non-time-critical candidates may be scheduled with a prominent verification task, while
reservation-dependent or timing-critical candidates are excluded until verified.

---

## 6. Offline ingestion and regional packaging

The ingestion path is deliberately separate from request-time planning:

```text
pinned release/source manifest
        -> quarantine directory
        -> checksum and size verification
        -> licence/source partition validation
        -> schema validation
        -> text/URL sanitization
        -> normalization
        -> deterministic identity resolution
        -> claim + contradiction emission
        -> quality report
        -> atomic dataset activation
```

The active catalog is replaced atomically only after its gate passes. A failed refresh leaves the
last good catalog active. Raw data and generated catalogs are not committed unless their licence
and size policy explicitly permits it; tests use small sanitized fixtures.

### Source roles

- **Overture Maps:** base discovery catalog, queried in batch with DuckDB Spatial or
  `overturemaps-py`; never an unbounded request-time download.
- **Wikivoyage/Wikidata:** destination and neighborhood context plus selected entity links.
  Imported text is untrusted data, stripped of active markup and isolated from model
  instructions.
- **OpenStreetMap:** selective enrichment for tags such as hours, accessibility and category,
  using downloaded extracts or reviewed services. The public Nominatim/Overpass/OSRM endpoints
  are not assumed to be free application backends.

Singapore is the first full catalog because it matches the existing corridor and fixtures.
Regional rollout then uses the same manifest and quality pipeline for Mumbai, Dubai, New York
City, London and Paris as representatives of the declared destination families. These cities are
coverage probes, not a claim that the whole country/region is complete.

---

## 7. Deterministic itinerary composition

### Inputs

The composer accepts typed, already-normalized inputs:

- trip timezone, dates, arrival/departure windows and hotel/base location
- traveler count, interests, must-do/avoid lists and accessibility requirements
- pace, start/end preferences, meal/rest windows and maximum daily travel budget
- candidate places with stable IDs, coordinates, suggested duration, evidence state and
  structured opening-hours intervals
- route matrix by mode, including whether each duration is routed or estimated
- optional reservation windows and immovable activities

### Hard constraints

- no overlap
- arrival/departure buffers
- a place must be open for the visit interval when trusted hours exist
- travel time must fit between adjacent stops
- fixed/reserved activities stay within their window
- accessibility exclusions are honored
- daily travel and activity limits are respected
- every scheduled stop resolves to an evidence-backed `PlaceId`

### Soft objectives

- interest fit
- geographic coherence
- preference for stronger/fresher evidence
- variety without needless category repetition
- meal/rest alignment
- avoiding excessive backtracking and rushed transitions
- honoring must-dos before optional fillers

The objective contains no money or points arithmetic. Any admission cost is a normalized costed
line evaluated later by deterministic financial code.

### Solver behavior

The first implementation is a deterministic greedy/insertion composer with stable tie-breaking
and geodesic travel estimates. OR-Tools is introduced only behind the same interface after that
baseline passes. OR-Tools runs with a fixed seed, deterministic ordering, a single worker and a
bounded time limit. Timeout or infeasibility falls back to the deterministic composer and emits a
reason; it never returns a solver's half-valid assignment as complete.

Every draft is followed by a separate deterministic validator. The LLM critic can propose a
revision, but cannot override a failed constraint.

---

## 8. Routing and map choices

### Route-matrix contract

The planner depends on `RouteMatrix`, not on Valhalla, Google Maps or any other vendor. Each cell
carries origin/destination IDs, mode, duration, distance, retrieval time, source and confidence.

Fallback order for the student profile:

1. A reviewed and enabled regional route adapter.
2. A private, patched and restricted Valhalla deployment when its security gate passes.
3. A deterministic geodesic estimate with an explicit `estimated` status and conservative mode
   multiplier.

The route implementation can therefore be deferred without blocking place discovery or the
basic itinerary composer.

### Map rendering

MapLibre GL JS is the preferred frontend renderer. It consumes only normalized coordinates,
routes and attribution metadata. Tile/style providers remain separately configured and reviewed;
choosing MapLibre does not grant a free map-tile service. Popups use React-rendered/sanitized
content and never inject provider HTML.

### Valhalla restriction

Valhalla is not internet-exposed in this project. Until the relevant upstream advisories are
resolved or locally mitigated and verified, it is an optional isolated component only. The
gateway rejects JSONP and user-controlled exclusion polygons, runs the service non-root with
CPU/memory/request limits, and permits calls only from the backend network.

---

## 9. MCP and provider policy

MCP is useful when it offers a maintainable transport to a legitimate source. It is not useful
as a substitute for source rights, normalized contracts, validation or deterministic planning.

### Binding rules

- The provider registry is static configuration reviewed in source control.
- Installation never activates an adapter.
- A runtime MCP server is wrapped by a gateway adapter and must pass the active
  `student_noncommercial` activation profile in spec 16.
- The model sees the first-party `search_places` schema, never raw MCP tools or provider names.
- Read-only methods only; no booking, reservation, transfer or purchase methods.
- Credentials live in environment/secret storage, never prompts, traces, fixtures or Git.
- Every call has strict schema validation, timeout, response-size limit, rate limit and audit
  metadata.
- Normal CI uses recorded, sanitized fixtures and makes no network calls.

### Current decisions

| Candidate | Decision |
|---|---|
| Custom TripPlanner place-search MCP | Later convenience boundary only, after the internal gateway contract is stable |
| TomTom official MCP | Optional credentialed experiment; requires human approval before obtaining/using a key |
| Tripadvisor Terra API/MCP | Strong optional itinerary enrichment candidate; official, authenticated and tiered/usage-based. Evaluate factual location/search access first, with reviews/photos excluded until their display, caching and attribution rules are implemented |
| Skyscanner Travel APIs/MCP | Strong flight/hotel candidate, but API keys and the MCP are partner access; the official MCP is currently granted case-by-case. Apply as a student project, but retain Gondola/sample fallbacks |
| Booking.com Demand API | Eligible only with official partner/affiliate credentials. Useful if accepted; never scrape the booking website as a substitute |
| Google Places/Routes APIs | Optional exact-place verification or routing adapter. Do not persist disallowed Places content or put Google Places results on MapLibre; Google requires Places results shown on a map to use a Google map. Store permitted IDs and provenance only |
| Google Flights | User verification/deep-link surface only. Its published Flights Search integration is for airlines/OTAs supplying data to Google, not a public consumer-fare search API |
| Google Travel Impact Model API/MCP | Optional free emissions evidence for known flights; it does not provide fares or availability |
| Community OSM MCPs that hard-code public Nominatim/Overpass/OSRM | Reject for runtime; useful only as code-reading prototypes |
| `gosom/google-maps-scraper` | Reject from product architecture and data pipeline |
| Gondola MCP | Separate flight-provider spike under spec 16; unrelated to itinerary-place readiness |

No itinerary phase is gated on finding a public open-source MCP server.

### GitHub Student Developer Pack

The pack materially improves the cost envelope for development and deployment, but it does not
grant rights to Google Maps, Tripadvisor, Skyscanner, Booking.com or other travel data.

Useful current benefits, verified on 2026-08-02:

- **GitHub Pro and Codespaces:** primary repository/development benefits.
- **Heroku:** USD 13/month credit for 24 months; the simplest candidate for a small public
  FastAPI/Next.js prototype if its current resource limits fit.
- **Microsoft Azure:** access to 25+ services plus USD 100 credit for students aged 18+; a better
  candidate for time-bounded container, database or private routing experiments than a permanent
  zero-cost dependency.
- **Appwrite Education:** two Pro-equivalent projects while student eligibility remains active.
  Do not introduce it merely because it is free; the project's account/persistence contracts
  remain authoritative.
- **MongoDB Atlas:** USD 50 credit. The project is relational/evidence-graph oriented, so this is
  not a reason to replace SQLite/PostgreSQL with MongoDB.
- **Datadog:** Pro for up to 10 servers for two years; potentially useful for a later deployed
  observability phase, not local MVP development.
- **1Password:** one year including developer tools; useful for local/deployment secret hygiene.
- **Name.com/Namecheap:** a student domain and/or certificate offer for a portfolio URL.
- **GitHub Pages:** suitable for static documentation or a landing page, not the stateful
  Next.js + FastAPI application.

The listed DigitalOcean USD 200 offer ended on 2026-07-31, so this design does not count it as
available unless the human confirms it was already redeemed and remains active. Pack offers are
time-limited and rechecked immediately before deployment.

Public deployment, paid overages and travel-provider credentials still require explicit human
approval. Every cloud account gets budget alerts/quotas, restricted secrets and a documented
shutdown path before the first deployment.

---

## 10. Security and supply-chain gate

External geographic text and data are hostile inputs even when the source is reputable.

### Required controls

- Pin direct and transitive Python/npm/container dependencies; record hashes where supported.
- Run dependency and container scans in CI and fail on unreviewed high/critical findings.
- Maintain an allowlist of DuckDB extensions. Use signed official extensions only, disable
  automatic/community extension installation, prohibit user-authored SQL and restrict readable
  and writable directories plus memory/thread limits.
- Treat Wikivoyage/Wikidata/OSM/provider text as data, never instructions. Strip scripts, event
  handlers, active markup, unsupported URLs and prompt-like control text before storage/model use.
- Keep raw payloads out of normal model context. Pass bounded normalized fields and stable IDs.
- Run ingestion in a low-privilege process with network, file, CPU, memory, archive-size and row
  limits. Protect against zip bombs and path traversal.
- Keep Valhalla private and apply the restrictions in section 8 before any use.
- Apply CSP, sanitize map content, allowlist tile/style origins and preserve attribution.
- Redact credentials and sensitive traveler data from traces and fixtures.
- Generate a source/licence manifest and software bill of materials for every activated catalog
  build.

Known advisories are not waved away because this is a student project. The student profile
reduces scale and cost expectations; it does not reduce the security bar for running untrusted
data or network services.

---

## 11. Licensing and attribution

Attribution is data, not footer prose added at the end.

- Preserve the original source partition and licence metadata of each Overture record.
- Preserve OpenStreetMap attribution and ODbL obligations for OSM-derived data.
- Preserve Wikimedia page/revision attribution and the applicable CC BY-SA/GFDL requirements.
- Do not merge differently licensed source payloads into an opaque export that makes attribution
  impossible.
- Render required map/data attribution in the UI and include the activated catalog manifest in
  the build report.
- Do not ingest consumer website content merely because a scraper can technically fetch it.
- Re-run provider, licence and compliance review before any commercial use.

The source manifest records URL, licence, release/revision, checksum, retrieval date, geographic
scope, allowed purpose and attribution text for every input.

---

## 12. Failure and partial-result behavior

| Failure | Required behavior |
|---|---|
| Catalog refresh fails | Keep the previous catalog active; publish failed quality report |
| No candidate meets evidence minimum | Return the unmet need; do not invent a venue |
| Hours absent/stale | Exclude if timing-critical; otherwise mark verify-required visibly |
| Routing unavailable | Use conservative geodesic estimate and label it estimated |
| Solver times out/is infeasible | Use deterministic fallback or return partial day with reasons |
| LLM/tool loop fails | Compose from deterministic retrieval results; no extra hidden call site |
| Tool-call budget exhausted | Return best partial artifact plus unresolved needs and stop reason |
| Providers disagree | Preserve contradiction; deterministic field rule chooses or withholds claim |
| Optional live adapter fails | Fall back per-adapter policy without changing evidence type |
| Required destination evidence missing | Stop finalization for that day; return actionable verification guidance |

Partial results remain structured. Fluent prose must never disguise missing evidence.

---

## 13. Observability and evaluation

Every itinerary run records:

- search intents and normalized tool arguments
- adapter selected by the registry, calls attempted, latency and stop reason
- candidate IDs returned, rejected and shortlisted with deterministic reason codes
- graph claim/source/evaluation IDs read and artifact IDs written
- route source/estimate status
- composer and solver configuration, seed, result and fallback reason
- validation failures and verification tasks
- token and tool-call budget consumption

Evaluation has separate dimensions:

- provenance completeness
- entity-resolution precision
- opening-hours feasibility
- route/travel-time feasibility
- schedule validity
- interest fit and variety
- geographic coherence
- graceful degradation
- grounded narrative quality

The first six are deterministic assertions. Qualitative LLM judging may supplement the final
three but never replace deterministic failures.

---

## 14. Phased delivery plan

Each phase is a separately gated change set. A later phase cannot repair an earlier gate after
the fact.

### Phase I0 — Evidence-graph correctness repair

**Purpose:** make the graph safe enough to support place identity and lineage.

Repair the known review findings before adding new node volume:

- make SQLite persistence complete and idempotent for runs, artifacts, evaluations,
  resolutions and edges
- enforce edge endpoint/direction contracts and eliminate duplicate/stale edges
- make identity-resolution rules explicit, reversible and unable to merge arbitrary claims
- replace flight-specific contradiction logic with per-kind comparators
- type timestamps and define exact freshness-boundary behavior
- keep stale and superseded as distinct states in backend and UI contracts
- reconcile stale design fields/tests and remove accidental test artifacts

**Gate I0:** round-trip persistence of every graph object; idempotency; invalid-edge rejection;
reversible-resolution tests; per-kind contradiction tests; clock-boundary tests; backend baseline
does not fall below 133 passing tests; strict typing and lint are clean.

### Phase I1 — Closed-world itinerary safety

**Purpose:** make the current seeded itinerary honest and mechanically feasible before adding
new data.

This absorbs the intent of the uncommitted `2026-07-29-itinerary-accuracy.md` plan after its
assumptions are reconciled with the current code:

- make POI provenance load-bearing in retrieval, planner and output
- replace prose-only hours with structured timezone-aware intervals and exceptions
- move final schedule construction out of the LLM and into deterministic code
- implement geodesic travel estimates and a per-day travel budget
- add the separate itinerary validator and explicit verification tasks

**Gate I1:** seeded Singapore schedules have no overlap, known-closed visits or impossible
transitions; every stop resolves to provenance; missing hours visibly propagate; two runs are
byte-identical; all existing money/transfer goldens remain unchanged.

### Phase I2 — Place contracts, registry and sample adapter

**Purpose:** freeze the internal seam before choosing real data transports.

- define `Place`, field-level claims, `PlaceSearchRequest`, `PlaceCandidate`, `RouteMatrix`,
  `ItineraryConstraints`, `ItineraryDraft`, `ItineraryValidation` and partial-result contracts
- implement the fixed provider registry and activation-profile checks
- implement a `SamplePlaceAdapter` and sanitized recorded fixtures
- connect place claims and itinerary artifacts to the evidence graph
- add source/licence manifest schemas and capability reporting

**Gate I2:** contract/schema tests, registry-deny tests, sample end-to-end search, provenance and
lineage invariants, deterministic fixture replay, no live network, and no imports from
`backend/core/` to `backend/gateway/`.

### Phase I3 — Singapore open-data catalog

**Purpose:** prove new-venue discovery at useful depth without a live MCP.

- ingest a pinned Singapore slice from Overture in batch
- enrich selected entities with Wikivoyage/Wikidata and OSM-derived claims
- implement sanitization, deterministic identity resolution, contradiction retention,
  checksums, licence manifest and atomic activation
- expose deterministic geo/category/text retrieval through the sample/snapshot adapter

**Gate I3:** a clean-machine catalog build from pinned inputs; repeat build is hash-identical;
licence and attribution coverage is complete; hostile-text/path/archive fixtures are rejected;
quality thresholds cover each supported venue category; the last good catalog survives a failed
refresh.

### Phase I4 — Composer, route matrix and OR-Tools

**Purpose:** turn a richer candidate set into valid, pleasant days.

- keep the I1 deterministic baseline as the fallback
- add route-matrix abstraction and conservative estimate adapter
- add OR-Tools behind the composer interface with fixed deterministic settings
- implement hard/soft constraints, structured rejection reasons and schedule repair
- add property-based and adversarial feasibility tests

**Gate I4:** all hard constraints are invariant under candidate ordering; solver runs are
deterministic; timeout/infeasible cases use the documented fallback; every scheduled route cell
has provenance/status; benchmark fixtures beat or match the baseline on coherence without any
validity regression.

### Phase I5 — Bounded agentic venue discovery

**Purpose:** let the LLM actively find better candidates without giving it provider or factual
authority.

- expose the one typed `search_places` tool inside the existing itinerary LLM call site
- implement the section-4 budgets and loop state machine
- allow query refinement, exact lookup of remembered names and evidence-backed shortlisting
- force candidate-ID referential integrity and deterministic post-validation
- implement tool failure, exhaustion and prompt-injection tests

**Gate I5:** the model can introduce a venue absent from the original seed fixture only by
retrieving a verified candidate; hallucinated IDs/names are rejected; provider selection stays
outside the prompt; six-call/three-round bounds cannot be exceeded; no fifth named LLM call site
is introduced.

### Phase I6 — API and frontend vertical slice

**Purpose:** expose the capability through the existing calm, trust-forward experience.

- change backend schemas, OpenAPI, generated client, MSW fixtures and UI in one change set
- render itinerary states, provenance, stale/verify-required status and partial-day reasons
- add MapLibre route/venue rendering with attribution and accessible list parity
- preserve the issued-document/boarding-pass visual language rather than adding a generic map UI
- never compute travel, trust, money or points values in the browser

**Gate I6:** contract drift test passes; keyboard/screen-reader itinerary works without the map;
reduced-motion and responsive checks pass; no storage-policy violation; CSP/sanitization tests
pass; frontend typecheck, tests and token lint are clean; backend baseline remains green.

### Phase I7 — Regional coverage and quality rollout

**Purpose:** prove the architecture generalizes before claiming broad destination support.

- add manifest-driven catalogs and test packs for Mumbai, Dubai, New York City, London and Paris
- implement per-region capability reporting and honest unsupported/partial states
- run category, identity, hours, route and itinerary-quality evaluations by city
- tune only Tier-C thresholds with recorded evidence and deviation entries where required

**Gate I7:** every representative city passes the same structural/provenance/security gates;
coverage scores and known gaps are published; no city silently falls back to Singapore assumptions;
worldwide is still labeled future work.

### Phase I8 — Optional live routing/MCP experiments

**Purpose:** measure whether a live integration improves the product enough to keep.

- evaluate a reviewed regional route source or restricted Valhalla adapter
- optionally evaluate the official TomTom MCP only after explicit credential approval
- apply for and, if accepted, evaluate the official Tripadvisor Terra and Skyscanner adapters
- evaluate Google Places only as a policy-compliant verification path, not as a persistent
  MapLibre catalog source
- optionally expose the stable first-party place interface as a TripPlanner MCP for developer use
- keep every experiment behind disabled-by-default activation configuration and recorded fixtures

**Gate I8:** threat model, licence/terms record, secret handling, schema normalization, rate and
timeout tests, fixture replay and kill-switch all pass. Failure returns to the I4/I5 fallback.
No experiment is promoted merely because it connects successfully.

---

## 15. Dependencies and sequencing

```text
I0 graph repair
   -> I1 closed-world safety
      -> I2 contracts + sample adapter
         -> I3 Singapore catalog
         -> I4 composer + routing abstraction
             I3 + I4 -> I5 bounded LLM discovery
                         -> I6 API/UI vertical slice
                            -> I7 regional rollout
                               -> I8 optional live/MCP experiments
```

I3 and I4 may be implemented as separate branches after I2, but I5 depends on both. I8 is not on
the critical path and may be skipped entirely.

The detailed work orders should be separate implementation plans rather than one enormous plan:

1. `itinerary-i0-evidence-hardening`
2. `itinerary-i1-safety`
3. `itinerary-i2-contracts`
4. `itinerary-i3-open-data-ingestion`
5. `itinerary-i4-composer-routing`
6. `itinerary-i5-agentic-discovery`
7. `itinerary-i6-frontend-vertical-slice`
8. `itinerary-i7-regional-rollout`
9. `itinerary-i8-optional-integrations`

Each plan must name exact files and interfaces, start behavior changes with failing tests, include
its gate commands, preserve unrelated work and use small commits. The implementation plans must
not contain “wire later,” placeholder components or skipped validation.

---

## 16. Explicitly rejected shortcuts

- “Let the LLM invent a day and then ask it whether the day is valid.”
- “Install a travel MCP and expose all of its tools directly to the model.”
- “Scrape Google Maps/TripAdvisor because the project is non-commercial.”
- “Download the whole world before the Singapore path works.”
- “Use public Nominatim/Overpass/OSRM as an undocumented free production backend.”
- “Treat missing hours as open.”
- “Treat straight-line distance as routed travel time.”
- “Merge place records by fuzzy name alone.”
- “Hide stale or partial evidence to keep the UI clean.”
- “Add live providers and frontend contract changes in different pull requests.”

---

## 17. Relationship to authoritative specs

- **Spec 06:** decision tiers, ambiguity handling and gate discipline remain binding.
- **Spec 08:** this implements the target itinerary-curation experience; it does not expand
  booking, events or commercialization scope.
- **Spec 09:** the star topology, fixed workflows, evidence graph and four named LLM call sites
  remain binding. The bounded search loop is inside the existing itinerary call site and uses one
  first-party tool; it is not dynamic provider discovery.
- **Spec 16:** all sources, including MCP transports, enter through reviewed adapters under the
  active `student_noncommercial` profile.
- **Evidence-graph design:** this document depends on its graph model, but Phase I0 must repair
  the implementation defects found in review before place evidence is added.
- **Existing itinerary-accuracy plan:** its safety goals belong to Phase I1. Its stale branch and
  fixture assumptions must be reconciled when the I1 work order is written; this design does not
  overwrite the untracked file.

If this document conflicts with an authoritative spec, the spec wins and the conflict is logged
before implementation. Approval of this design authorizes writing plans; it does not activate a
provider, use a credential or begin a public deployment.
