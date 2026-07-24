# 09 — Target Platform Architecture

**Scope:** Architecture surrounding the frozen deterministic kernel. This spec does not change any golden number or money/points rule in specs 01, 02, 04, or 07. Phase K continues to implement spec 03 unchanged; this architecture becomes executable after F4 through the milestones in §13.

**Active operating profile:** `student_noncommercial`. One developer, low-volume portfolio/demo traffic, near-zero provider budget, no commercial SLA, no autonomous transaction. A hypothetical commercial launch is a separate re-architecture/re-approval trigger, not a current acceptance criterion.

## 1. Architectural goals

1. Add live discovery without letting provider churn contaminate the optimizer.
2. Present specialized flight, hotel, award, card/offer, and itinerary capabilities through one orchestrated flow.
3. Keep autonomy bounded, observable, budgeted, and testable.
4. Preserve product usefulness when credentials, providers, or live inventory are unavailable.
5. Treat provider terms, source method, freshness, and data completeness as visible runtime correctness concerns.
6. Demonstrate live orchestration with free/read-only providers without making the demo depend on their uptime.

## 2. Constraints

- Existing kernel arithmetic, pathfinding, provenance, groundedness, and golden tests are frozen.
- Initial team/operation is small; avoid distributed-system machinery until load justifies it.
- Provider access may be absent, regional, experimental, rate-limited, changed, or revoked.
- The app must build and run end-to-end with only `SampleAdapter`.
- Default provider spend is zero. Paid services or credentials require explicit human approval.
- No provider may require the kernel to import a network client or provider SDK.
- No irreversible action is executed.

## 3. Component view

```text
Frontend
  │  POST /plan · GET /plan/{job_id}
  ▼
Plan API / Job Runner
  ▼
Target Orchestrator (typed state machine)
  ├── Intake workflow
  ├── Flight workflow ─────┐
  ├── Hotel workflow ──────┤
  ├── Award workflow ──────┼── Data Gateway ── reviewed adapters
  ├── Card/offer workflow ─┘         │
  └── Itinerary workflow             ├── quote cache (ephemeral)
                                     └── provider registry/config
  ▼
Evidence Assembler / Normalizer
  ▼
Deterministic Kernel
  ├── Cost Estimator
  ├── Rewards Optimizer
  └── Transfer Pathfinder
  ▼
Critic / Groundedness Gate / Explainer
  ▼
FinalReport + trace
```

## 4. Boundary rules

### Deterministic kernel

- Lives under `backend/core/`.
- Performs no network, filesystem discovery, secret access, or provider selection.
- Accepts typed values and returns typed computed artifacts.
- Knows channels and financial semantics, not provider APIs.
- Retains existing golden tests byte-for-byte unless a separately authorized Tier-F change occurs.

### Data Gateway

- Future home: `backend/gateway/`.
- Owns provider clients, credentials, rate limits, timeouts, caching, normalization, and terms metadata.
- Returns only spec 16 normalized contracts.
- Has no authority to write approved financial facts.
- Cannot execute bookings, transfers, or arbitrary URLs.

### Orchestration

- Calls a fixed registry of domain workflows.
- Selects only adapters enabled in configuration and permitted for the request's country/use case.
- May run independent searches concurrently within a configured fan-out/cost budget.
- Does not permit providers or LLMs to create new tools, delegate to arbitrary agents, or modify the workflow.

### Offline ingestion

- Remains spec 05.
- Writes proposals, never approved facts.
- Does not serve live inventory.

## 5. Domain workflows

Each workflow implements:

```python
class DomainWorkflow(Protocol):
    name: str
    async def run(self, context: PlanContext) -> DomainResult: ...
```

`DomainResult` contains normalized evidence, warnings, trace references, and a declared quality state. A workflow may be deterministic or may contain a separately specified LLM call; no LLM call is implied by the word "agent."

### Flight workflow

- Build `FlightSearchRequest` from validated trip input.
- Ask profile-eligible current-quote adapters through the gateway; Gondola is the first student-profile spike.
- When dates are flexible, deterministically query a bounded date set and/or consult cached `FlightPriceObservation` trends. A trend chooses dates to inspect; it never becomes a current itinerary.
- Normalize, de-duplicate, filter impossible itineraries, and retain material alternatives.
- Preserve quote expiry, price completeness, baggage/fare conditions, and verification links.
- Keep cash `FlightQuote` and award `AwardQuote` evidence separate.
- Treat Duffel test-mode offers as `estimated` fixtures, never live consumer prices.
- Never calculate rewards or effective cost.

### Hotel workflow

- Build search request using destination, dates/flexibility, occupancy, style, and candidate itinerary areas.
- For flexible dates, deterministically generate a bounded set of valid stay windows; never let an LLM invent or expand the fan-out.
- Compute cheapest/most-expensive comparable date bands and neighborhood aggregates from normalized evidence.
- Normalize price completeness, cancellation, room/rate plan, and location evidence.
- Compare the same property across sources only when dates, occupancy, room/rate conditions, currency, and mandatory-price scope align.
- Rank itinerary fit separately from final effective cost.

### Award workflow

- Retrieve award evidence when a profile-eligible adapter is enabled.
- Pass miles/fees/program evidence to the existing Transfer Pathfinder.
- Preserve cached/live distinction and provider retrieval time.
- Always emit verify-before-transfer, even for `live` evidence.

### Card/offer workflow

- Retrieve approved financial facts from the KB.
- Invoke the existing Rewards Optimizer.
- Contains no LLM money reasoning.

### Itinerary workflow

- Retrieve approved/reference POIs.
- Use the existing planner contract to compose days.
- When target-platform live hours/travel-time evidence exists, pass it as grounded context; otherwise retain current conservative behavior.

## 6. Orchestration policy

The first target orchestrator is a typed state machine, not a free-form LLM planner:

```text
validate intake
  → start flight/hotel/reference searches allowed by config
  → start award search when balances/preferences make it relevant
  → assemble available evidence
  → curate itinerary
  → estimate costs
  → optimize cards/offers
  → run transfer pathfinder
  → critique
  → explain
```

Conditional branches are explicit code. Examples:

- no award adapter or no balances → skip award search, render unlock/verification note;
- live provider fails → fall back to cached/sample evidence if permitted;
- flexible dates enabled → search only the configured number of date variants;
- only cached flight trend exists → suggest dates, then require a current quote/verification before ranking a bookable winner;
- quote expires during planning → mark `stale` and re-query once if budget remains;
- materially incomplete price → exclude from winner or label `estimated`.

The PDF-inspired stay flow is implemented as typed workflow state:

```text
generate bounded stay windows
  → collect normalized stay quotes
  → aggregate date/neighborhood price bands
  → match comparable property/rate variants
  → shortlist by constraints + itinerary fit
  → send display-ready evidence to the kernel/UI
```

It does not use a shared Markdown file as application state, browser-sponsored placement as a ranking signal, or provider-calculated rewards value.

A future LLM orchestration call requires its own typed contract, deterministic fallback, eval suite, cost budget, and Tier-F protocol amendment. It may choose among predeclared actions only.

## 7. Storage

### Approved knowledge base

SQLite during Kernel MVP; Postgres-portable. Holds financial rules and curated/reference facts with human verification.

### Quote cache

Separate logical store, even if initially another SQLite table/in-memory implementation. Holds ephemeral provider responses and normalized quotes only for the duration/licence permitted. Records expiry and deletion policy. Quote-cache rows are never promoted into approved financial facts.

### Raw/recorded fixtures

Sanitized provider responses used for tests. Stored under a provider fixture directory with capture date, API version, redaction record, source method, and known retention basis. If raw-response retention is unclear, keep a minimal hand-reviewed normalized fixture rather than the raw payload. No secrets or personal data.

### Job state

In-memory/SQLite is acceptable for one-process demo use. Before multi-instance deployment, move jobs to a shared store/queue and define idempotency and retention.

## 8. API evolution

The Kernel MVP keeps spec 12's endpoints. Target-platform additions are contract changes and must follow spec 12 §8:

- plan status may add real search/normalization stages;
- `FinalReport` may carry normalized quote summaries and evidence status;
- partial domain results are explicit, not encoded as generic errors;
- the frontend receives display-ready numbers and trust metadata, never provider secrets/raw payloads.

The backend OpenAPI snapshot remains the frontend source of truth.

## 9. Reliability and graceful degradation

- Provider calls use bounded concurrency, per-adapter timeout, retry classification, and circuit breakers.
- Retry only idempotent reads and only for documented transient errors.
- A provider outage produces `provider_unavailable`, not a pipeline crash.
- Search results are useful partial artifacts; the job runner should expose real progress.
- One revalidation attempt is allowed when a winning quote expires before report assembly.
- If no trustworthy price exists, the plan may still return itinerary and card/transfer guidance with `estimated`/`verify_required` labels.
- Do not merge results when taxes, occupancy, cabin, or trip type cannot be made comparable.

## 10. Provider governance, security, and future compliance

- Provider secrets are server-side environment/secret-manager values and never enter prompts, traces, fixtures, or the browser.
- Adapter requests use a fixed base URL and fixed endpoint set; user input cannot become an arbitrary URL.
- Student-profile activation records the provider/source owner, endpoint, allowed non-commercial use, source method, robots/access-control behavior where relevant, data sent, retention uncertainty, quotas, and shutdown switch. Experimental evidence is visibly labeled and never treated as guaranteed.
- Commercial-profile activation, if ever needed, additionally requires written commercial rights, caching/redistribution permission, privacy review, operational support, and production suitability. It is inactive today.
- User inputs sent to providers are minimized; avoid names/contact details during search.
- No bank or loyalty credentials are accepted. Future OAuth tokens require a separate encrypted-token and revocation design.
- Community MCP servers and scraper wrappers are disabled by default. Under the student profile they may be explicitly feature-flagged for low-volume, read-only experimentation after spec 16 review; the application never disables robots handling, circumvents a block, or treats them as a durable dependency.

## 11. Observability and cost control

Extend `TraceEvent` with:

- workflow and adapter name;
- request/result count;
- start/end/timeout;
- cache outcome;
- evidence states returned;
- normalized error category;
- estimated/actual provider cost where available;
- quote IDs/hashes, never raw secrets.

Each plan has configured ceilings for:

- total provider calls;
- calls per adapter;
- flexible-date fan-out;
- total provider time;
- paid usage;
- retry count.

Exceeding a ceiling degrades gracefully and becomes a trace warning.

## 12. Testing strategy

- Kernel tests never call a live provider.
- Every adapter has recorded-fixture contract tests for success, empty, rate-limit, auth failure, malformed payload, incomplete price, and timeout.
- Normalization/dedup/freshness tests are deterministic and clock-controlled.
- `SampleAdapter` implements the same normalized contract and drives all Phase G end-to-end tests.
- A live smoke test is manual, read-only, budget-capped, and excluded from normal CI. Anonymous/free providers do not require credentials; any provider that does still requires human approval.
- Any provider-caused demo bug becomes a sanitized recorded/normalized fixture in the same fix.

## 13. Implementation milestones

Implementation begins after F4 unless the human explicitly changes the order.

### G1 — Contracts and sample gateway

Implement spec 16 normalized models, provider registry, `SampleAdapter`, and recorded-fixture harness. Gate: identical Kernel MVP recommendations through the gateway versus direct samples; no network in tests.

### G2 — Open/reference importers

Add one FX, airport, and POI importer at a time. Gate: licence metadata retained, deterministic snapshots, no change to golden optimizer values.

### G3 — First student-profile live adapter

Add a read-only `GondolaAdapter` behind the gateway, initially using anonymous search tools only. Prefer hotel cash/points evidence, flexible-night rates, direct links, and exact-date cash-flight evidence. Ignore provider-computed cents-per-point/card optimization; send raw normalized values to the kernel. Gate: India–Singapore coverage and payload completeness measured, student activation checklist complete, failure fixtures green, quote trust states visible, zero spend ceiling enforced, and `SampleAdapter` fallback demonstrated.

### G3a — Flight trends and contract fixtures

- Optional `TravelpayoutsTrendAdapter`: cached week/month/date observations only; cannot emit `status="live"` or a bookable `FlightQuote`.
- `DuffelSandboxAdapter`: development/contract fixtures only; always `estimated`, never shown as real inventory.
- Google Flights: verification/deep-link output only; no scraping or runtime fare adapter.

Gate: current quotes, cached trends, and sandbox fixtures cannot be confused by schema or UI; flexible-date fan-out is bounded; the winner requires a current/verified quote.

### G3b — Experimental rental-stay adapter

Evaluate `OpenBnBAdapter` as local/demo-only, low-volume, read-only, feature-flagged evidence. Never enable any robots override or blocking circumvention. Gate: source-method warning visible, output always `verify_required`, no persistent raw cache without a documented basis, failure fallback green.

### G4 — Award evidence

Add one free/personal-use award adapter when available. Until then, keep recorded fixtures, curated award/transfer rules, optional manual award input, and airline/award-tool verification links as the zero-budget mode. Gate: fresh/cached/estimated/manual/expired cases are distinct, transfer verification is always first, geographic eligibility is confirmed, and provider spend defaults to zero. A paid source such as an eligible seats.aero plan requires explicit human approval.

## 14. Trade-offs

- **Fixed workflows over autonomous agents:** less novelty, much higher testability and financial safety.
- **Gateway over direct tools/MCPs:** more adapter code, but stable contracts and enforceable licensing/security.
- **Sample-first:** delays live wow-factor, but completes the differentiated optimizer and UX without external blockers.
- **Free/experimental providers:** excellent student-project reach at near-zero cost, with lower stability and weaker guarantees; source labels and fallbacks make that trade-off honest.
- **Separate quote cache and KB:** more concepts, but prevents expiring inventory from masquerading as approved facts.
- **Partial results:** more UI states, but better availability and honesty than all-or-nothing planning.

## 15. Revisit triggers

- Shared job store/queue: before multi-instance deployment.
- Postgres: when concurrency or persistence exceeds SQLite's safe operating envelope.
- Streaming/SSE: when polling materially harms latency or load.
- LLM orchestration: only after deterministic branching becomes demonstrably insufficient.
- Multi-provider parallel fan-out: when cost, latency, and duplicate quality are measured.
- User-authorized OAuth: only after privacy/security requirements and provider contracts are approved.
- Commercialization: re-run every provider under `commercial_production`, replace experimental adapters as needed, and revisit privacy, scale, SLAs, and licensed inventory.
- Automated rate-negotiation calls: only after a separate regional disclosure/consent/recording and abuse-prevention design.
