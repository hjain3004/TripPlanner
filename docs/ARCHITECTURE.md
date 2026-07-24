# Architecture — Unified Travel Rewards Student Prototype

*One-page orientation. Product intent lives in spec 08, target boundaries in spec 09, and provider contracts in spec 16. Numeric kernel behavior remains governed by specs 01, 02, 04, and 07.*

## Thesis

"A travel planner that knows your credit cards." Given one trip and the user's cards, points, preferences, and constraints, produce one coherent answer: a practical itinerary, cash and award travel options, a costed budget, the best card/offer/payment strategy, and a points-transfer plan. Every number is deterministic, every external claim is sourced and time-stamped, and every irreversible action remains with the user. Initial corridor: India → Singapore.

The **target prototype** combines the useful outcomes of itinerary planners, cash metasearch, award-search tools, and credit-card optimizers without pretending that one unrestricted data source exists. The **current build** is the test-data Kernel MVP: the trusted optimizer and user experience are completed before free/read-only live providers are activated.

## Operating profile

This repository is a **non-commercial student/portfolio project**. Its goal is to demonstrate sophisticated agentic orchestration, deterministic travel-rewards optimization, live evidence integration, and excellent UX at little or no provider cost. It is not being designed for paying customers, booking volume, uptime SLAs, or commercial redistribution of provider data.

The active provider profile is `student_noncommercial`: free/open or personal-use services are acceptable when they are explicitly allowlisted, read-only, low-volume, source-labeled, and backed by sample/recorded fallbacks. If the project is ever monetized or operated as a real travel service, switch to `commercial_production` and re-review every provider, licence, cache rule, privacy flow, and irreversible action. That future review is not a prerequisite for this student build.

## System shape

```text
User trip + wallet
        │
        ▼
Bounded Orchestrator
        ├── Flight workflow ─────┐
        ├── Hotel workflow ──────┤
        ├── Award workflow ──────┤
        ├── Card/offer workflow ─┼──▶ normalized evidence
        └── Itinerary workflow ──┘
                                  │
                    Allowlisted Data Gateway
                    (sample adapter first; free/read-only
                     MCP/API adapters added after F4)
                                  │
                                  ▼
                   Deterministic Kernel
              cost estimator · rewards optimizer
                    transfer pathfinder
                                  │
                                  ▼
                    Critic + grounded explainer
                                  │
                                  ▼
                   One traceable trip recommendation
```

"Agent" is a product-facing capability, not a requirement that every box be an LLM. Provider calls, normalization, deduplication, rewards arithmetic, transfer search, freshness decisions, and ranking are deterministic code. LLMs are used only where language or qualitative judgment adds value, through fixed typed contracts and deterministic fallbacks.

## Four data classes

1. **Financial rules** — card earn rules, caps, offers, transfer edges, bonuses, and award charts. These enter through offline collection or manual curation, require provenance, and never update the approved KB without human action.
2. **Reference data** — airports, POIs, areas, currencies, and destination metadata from licensed/open sources. These are imported offline with source licence, snapshot date, and attribution retained.
3. **Live inventory evidence** — flight, hotel, rental-stay, and award quotes. These are requested at runtime only through spec 16's allowlisted gateway, are never treated as durable financial facts, and carry provider, retrieval time, expiry, completeness, and verification status.
4. **User-supplied data** — trip constraints, owned cards, and optional balances. The platform does not collect bank or loyalty passwords. A future provider-authorized OAuth flow may be added only through an explicit spec and human approval.

## Two runtime boundaries

**Kernel MVP runtime (current build).** A Level 1–2 governed pipeline over local sample data. Four LLM call sites handle Intake, Itinerary Planning, Critique, and Explanation. Cost Estimator, Rewards Optimizer, and Transfer Pathfinder are pure code. Apart from the configured LLM, there is no request-time network access. This preserves deterministic gates while the full UX is built.

**Target-prototype runtime (post-F4).** The orchestrator may invoke a fixed set of typed domain workflows. Provider I/O is permitted only through `backend/gateway/`, against the active profile's reviewed allowlist with terms snapshot, data-source classification, rate limits, budgets, timeouts, and circuit breakers. The application does not directly crawl booking sites at runtime. It does not bypass robots rules, access controls, CAPTCHAs, or blocks, and it never performs arbitrary URL fetches, dynamic MCP discovery, or free-form tool delegation.

The kernel never imports the gateway. Orchestration maps normalized external quotes into kernel inputs, so provider churn cannot change Tier-F money behavior.

## Offline freshness

Financial and rules data follows spec 05:

```text
watchlist → polite Crawl4AI snapshot → diff → typed proposal
          → deterministic validation → human review → approved KB fact
```

Only approved facts enter the KB. Crawlers do not collect login-walled pages, bypass access controls, rotate proxies, solve CAPTCHAs, or scrape live booking inventory. Live prices and availability come from profile-eligible adapters, not the ingestion crawler.

## Stay-shopping loop

The PDF `Beat_the_Booking_Sites.pdf` contributes a useful workflow pattern:

```text
flexible window → cheapest valid stay/date band
                → comparable rates for the same property/rate conditions
                → itinerary-fit shortlist
                → user-controlled direct/verification link
```

The implementation improves on the PDF by using typed state instead of a shared Markdown file, bounding flexible-date fan-out, matching the same room/rate/tax scope before comparing prices, and passing raw price evidence into our deterministic kernel. Sponsored placement or provider commission never controls the winner. Automated phone negotiation is not part of the current build; it would require a separate consent and compliance design.

## Flight evidence ladder

Flight data is deliberately split by what it can honestly prove:

```text
Gondola MCP ───────────────▶ current cash FlightQuote + verification link
Travelpayouts Data API ───▶ cached date/route price observations
Duffel test mode ─────────▶ estimated schema/error fixtures, not real prices
recorded/sample evidence ─▶ deterministic offline fallback
future award adapter ─────▶ AwardQuote availability evidence
```

Cash fare evidence and award-seat evidence are separate domains. Gondola is the first cash-flight spike, but its documented flight search does not replace a dedicated award source. Cached Travelpayouts observations may suggest cheaper dates but cannot masquerade as a current bookable itinerary. Duffel test offers validate adapter behavior only. Google Flights has no open consumer fare-search API for this project; the UI may provide a verification/deep link but the application does not scrape it.

Until a free/personal award adapter is available, the prototype uses recorded award fixtures, curated transfer/award rules, optional manual award input, and first-party verification links. It never tells the user to transfer points as though a seat were confirmed.

## Trust model

- LLMs never calculate money, points, ratios, discounts, or fees.
- Every rule/reference fact carries provenance and staleness.
- Every live quote carries source, retrieval time, expiry, and a UI trust state: `live`, `cached`, `estimated`, `stale`, or `verify_required`.
- Conflicting providers are preserved as separate evidence until deterministic normalization/ranking resolves them; disagreement is surfaced when material.
- Award availability is evidence, not a guarantee. Verify-before-transfer remains checklist step 1 even for a fresh provider quote.
- The platform never executes bookings or points transfers and never recommends hiding uncertainty.

## Build order

1. **Kernel backend:** M1 → M1b → M2 → M3 using existing sample data and golden tests.
2. **Kernel frontend:** F1 → F2 → F3 → F4 using MSW, then one end-to-end run against the sample-data backend.
3. **Platform gateway:** normalized quote contracts + `SampleAdapter`; no paid provider required.
4. **Open/reference ingestion:** FX, airports, and licensed POIs as isolated importers.
5. **Student live evidence:** add read-only Gondola MCP for hotel/cash-flight evidence; optionally add Travelpayouts cached flight trends; evaluate OpenBnB as an experimental, low-volume rental adapter; add award evidence when a free/personal source is available.
6. **Optional experiments:** rate alerts, user-authorized loyalty OAuth, and any browser extension are separately gated. Automated booking and phone negotiation remain outside the current project.

Provider access is never a prerequisite for completing the Kernel MVP. A free provider disappearing must degrade to recorded/sample evidence, not derail the project.

## Extensibility

A new corridor still adds data packs, theme assets, and golden evals without changing optimizer behavior. A new provider implements spec 16's adapter contract and passes recorded-fixture conformance tests. It does not add fields directly to `SampleFlight` or `SampleHotel`; those remain Kernel MVP fixtures.

## Permanently absent

LLM money math. Autonomous writes of financial facts. Unreviewed or dynamically discovered providers/MCP servers. Direct runtime scraping by this application. Access-control, robots, CAPTCHA, or block circumvention. Bank/loyalty password handling. Autonomous bookings. Autonomous points transfers. Runtime self-modification of prompts, rules, or code.

## Spec index (`docs/specs/`)

**Kernel backend:** 00 build plan · 01 data model · 02 rewards optimizer · 03 kernel orchestration · 04 evals · 05 offline ingestion · 06 implementation protocol · 07 transfer pathfinder.

**Target platform:** 08 product vision · 09 target architecture · 16 data gateway and adapters.

**Frontend:** 10 build plan/tooling · 11 design system · 12 integration contract · 13 pages/motion · 14 components · 15 wit pack.
