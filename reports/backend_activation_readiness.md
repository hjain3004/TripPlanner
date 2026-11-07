# Backend Provider Activation Readiness Report

**Date:** 2026-11-06  
**Status:** FACTUAL AUDIT COMPLETE — PROVIDER ACTIVATION REMAINS DISABLED  
**Operating Profile:** `student_noncommercial` (ceiling: USD 0 out-of-pocket spend)  
**Authoritative Specs:** `docs/specs/08_product_vision.md`, `09_target_platform_architecture.md`, `16_data_gateway_and_adapters.md`  

---

## 1. Purpose and Policy Boundaries

This document records the exact factual readiness, implementation status, evidence classification, default safety states, and prerequisites for each external provider adapter in the TripWise backend.

Per project delivery directives and non-negotiables:
- **No live activation is performed in this milestone.**
- **No provider calls, OAuth browser interactions, crawling, or spending are initiated.**
- **Working Gondola OAuth is preserved without modification.**
- **OpenBnB is not activated despite its offline adapter existing.**
- **No replacement providers, speculative infrastructure, or weakened security guards are introduced.**

---

## 2. Provider-by-Provider Readiness

```
┌─────────────────┬─────────────────────┬──────────────────┬──────────────────────┬─────────────────────────┐
│ Provider        │ Application Path    │ Evidence Status  │ Default State        │ Activation Blockers     │
├─────────────────┼─────────────────────┼──────────────────┼──────────────────────┼─────────────────────────┤
│ Gondola         │ Hotel search/rates  │ Real observed    │ Disabled             │ 2-call budget ceiling;  │
│                 │ Flight observations │ captures in demo;│ TRIPWISE_GONDOLA_    │ Markdown-only schemas;  │
│                 │ in saved revisions  │ fixtures in tests│ LIVE_ENABLED=0       │ expired token refresh   │
├─────────────────┼─────────────────────┼──────────────────┼──────────────────────┼─────────────────────────┤
│ Open-Meteo      │ Weather context in  │ 1 live forecast  │ Disabled fail-soft   │ Node runtime + audited  │
│                 │ /plan and revisions │ probe captured;  │ TRIPWISE_OPEN_METEO_ │ package installation    │
│                 │ (non-financial)     │ fixtures for rest│ ENABLED=0            │ required on host        │
├─────────────────┼─────────────────────┼──────────────────┼──────────────────────┼─────────────────────────┤
│ OpenBnB         │ Isolated offline    │ 100% synthetic   │ Mechanically         │ Airbnb ToS §11.1 scrape │
│                 │ adapter only; not   │ fixtures;        │ locked; refuses      │ ban; unreviewed robots; │
│                 │ wired to registry   │ 0 live calls     │ without human grant  │ missing schema capture  │
├─────────────────┼─────────────────────┼──────────────────┼──────────────────────┼─────────────────────────┤
│ TripAdvisor     │ Isolated offline    │ 100% synthetic   │ Disabled             │ API key needed; 900 cap │
│                 │ place adapter only; │ fixtures;        │ TRIPWISE_TRIPADVISOR_│ lifetime allowance;     │
│                 │ not in registry     │ 0 live calls     │ API_KEY not set      │ 24h caching restriction │
├─────────────────┼─────────────────────┼──────────────────┼──────────────────────┼─────────────────────────┤
│ Financial       │ Manual upload active│ 1 manual HDFC    │ Crawl4AI optional;   │ Bank ToS / robots.txt;  │
│ Ingestion       │ Curator CLI/server; │ capture staged;  │ Firecrawl unbuilt;   │ headless Chromium;      │
│ (Crawl4AI /     │ PDF worker isolated;│ zero automated   │ auto-apply forbidden │ human approval mandate; │
│ Firecrawl)      │ in-memory dry-run   │ web crawling     │ by non-negotiable #4 │ Firecrawl FI4 unbuilt   │
└─────────────────┴─────────────────────┴──────────────────┴──────────────────────┴─────────────────────────┘
```

---

### 2.1 Gondola (Travel Inventory MCP)

- **What works through the application:**
  - **Hotel Search & Rates:** Real hotel discovery and dated-rate retrieval implemented in `backend/gateway/travel/adapters/gondola/`. Rates surface in planning reports and saved trip revisions as `verify_required` options.
  - **Flight Price Observations:** Real Google Flights search results returned by Gondola are parsed via `GondolaFlightDiscoveryAdapter` into typed `FlightPriceObservation` records (carrier, outbound local departure/arrival, round-trip USD price in minor units, stop count). These are carried through `TravelInventoryService` and persisted in planning reports and saved revisions with `is_bookable=false` and `return_itinerary_confirmed=false`.
  - **Budgeting Isolation:** Final payable flight and hotel costing in the deterministic optimizer remains strictly sample-backed (`SampleHotel`, `SampleFlight`); Gondola observations provide contextual price alternatives but do not enter financial allocation directly.
- **Fixture/replay versus observed live:**
  - **Observed Live:**
    - Live tool discovery completed anonymously (28 tools inspected, high-risk tools denylisted).
    - Authenticated tool discovery via OAuth `mcp:read` (0 unexpected tools).
    - Real argument shapes verified: `search_hotels` requires (`location`, `checkin`, `checkout`); `search_flights` requires (`departure_date`, without currency).
    - Live hotel rates captured for Singapore (Four Seasons Hotel Singapore, SGD 1,970.94).
    - Live flight search executed for DEL–SIN (10–13 Feb 2027), capturing 8 Google Flights round-trip fare options (e.g. Singapore Airlines USD 466).
  - **Fixture/Replay:**
    - Test suites run offline against synthetic fixtures matching the observed grammar.
    - Integration demo scripts (`evals.demo_gondola_hotel_plan`) replay sanitized real captures from temporary directories without network dispatch (`provider_calls: 0`).
- **Default state and actual activation mechanism:**
  - **Default State:** Disabled (`enabled=False`). Default environment: `TRIPWISE_GONDOLA_LIVE_ENABLED=0`. Dominant kill switch `TRIPWISE_GONDOLA_KILL_SWITCH=1` unconditionally forces disabled state.
  - **Activation Mechanism:**
    1. Interactive browser OAuth bootstrap via `backend/gateway/travel/adapters/gondola/scripts/bootstrap_oauth.py` using Dynamic Client Registration (DCR) and PKCE. Requests strictly `mcp:read`. Tokens are saved to the OS keychain via `keyring` (never in repository files).
    2. Environment flag `TRIPWISE_GONDOLA_LIVE_ENABLED=1`.
    3. Mode selection via `TRIPWISE_GONDOLA_SEARCH_MODE=hotels` (default, 2 calls: search + dated rates) or `flights` (1 call).
    4. Guardrails: Atomic SQLite call ledger limits plans to 2 calls total; circuit breaker trips after 3 consecutive failures.
- **Outstanding source permission, credentials, cost, or technical requirements:**
  - **Permission / Terms:** Acceptable under `student_noncommercial` profile for read-only experimentation.
  - **Credentials / Cost:** Free Gondola account; zero out-of-pocket spend.
  - **Technical Requirements:**
    - *Unstructured output:* Both hotel and flight tools emit free-form Markdown rather than structured JSON, requiring brittle text parsing.
    - *Per-plan call budget:* Running both live hotel and live flight workflows in one plan requires 3 calls, exceeding the hard 2-call budget. Simultaneous live hotel + flight in one plan is disabled.
    - *SDK token refresh:* The installed MCP SDK local check treats missing expiry as valid, causing authentication failures if tokens expire before refresh triggers.
- **Smallest explicitly authorized future acceptance run:**
  - Single read-only query (either 1 flight search for DEL–SIN or 1 hotel rate lookup) with existing valid OS keychain token, verified to consume <=1 provider call in the SQLite ledger, returning sanitized output without writing secrets.

---

### 2.2 Open-Meteo (Weather Context MCP)

- **What works through the application:**
  - Pinned stdio client connecting to `@cyanheads/open-meteo-mcp-server` 0.4.1 in `backend/gateway/weather/`.
  - Allowlist strictly limits access to 3 tools: `get_forecast`, `get_historical_weather`, and `get_climate`. All geocoding, marine, air-quality, and SQL tools are denied.
  - Normalizes observations into `WeatherContext` (current temperature, weather code, near-term forecast, historical range, and climate summaries with the mandatory caveat `Climate summary - not a forecast`).
  - Integrated into `/plan` and confirmed-brief jobs: attaches optional `weather_context` to `FinalReport`, surviving backend restarts and revision loads.
  - Non-financial boundary: Fail-soft behavior returns `Weather context unavailable`; weather data never alters itinerary routing, cost lines, or reward calculations.
- **Fixture/replay versus observed live:**
  - **Observed Live:** 1 live forecast probe for Singapore coordinates `(1.3521, 103.8198)` executed via `probe_live.py`, resulting in the committed reference capture `backend/gateway/weather/fixtures/singapore_live_capture.forecast.json`.
  - **Fixture/Replay:** Historical and climate responses are tested offline against synthetic fixtures matching reviewed upstream contracts; no live historical/climate calls have been made.
- **Default state and actual activation mechanism:**
  - **Default State:** Disabled fail-soft (`enabled=False`). Default environment: `TRIPWISE_OPEN_METEO_ENABLED=0`. Dominant kill switch `TRIPWISE_OPEN_METEO_KILL_SWITCH=1` unconditionally forces disabled state. Public contract returns `Weather context unavailable`.
  - **Activation Mechanism:**
    1. Operator installs pinned npm package `@cyanheads/open-meteo-mcp-server@0.4.1` with lockfile verification against `backend/gateway/weather/upstream/package-lock.audited.json`.
    2. Set environment variables: `TRIPWISE_OPEN_METEO_ENABLED=1`, `TRIPWISE_OPEN_METEO_INSTALL_ROOT=/path/to/server`, and optionally `TRIPWISE_OPEN_METEO_NODE=/path/to/node`.
    3. MCP child process is spawned with an ephemeral, empty `$HOME` and sanitized environment.
- **Outstanding source permission, credentials, cost, or technical requirements:**
  - **Permission / Terms:** Open-Meteo is free for non-commercial use with CC BY 4.0 attribution. Attribution string is embedded in normalized models. Upstream package is Apache-2.0.
  - **Credentials / Cost:** Zero credentials; zero cost (USD 0).
  - **Technical Requirements:** Requires Node.js (>=20) runtime on host/container and pre-installed pinned package matching the exact lockfile hash.
- **Smallest explicitly authorized future acceptance run:**
  - Execute `python -m gateway.weather.scripts.probe_live` on a host with the pinned package installed, verifying a 3-day forecast for Singapore with CC BY 4.0 provenance.

---

### 2.3 OpenBnB (Rental Stay Scraper MCP)

- **What works through the application:**
  - Isolated adapter in `backend/gateway/travel/adapters/openbnb/` with strict request filtering (vacation rentals, 1 room, <=28 nights, 1–16 adults).
  - Allowlist permits only `airbnb_search` and `airbnb_listing_details`.
  - Normalizes listings into `HotelQuote` with `verify_required`, scraper warnings, NFKC-normalized text, stripped injection markers, and strict total price parsing (refuses nightly rates as totals).
  - **Not wired to the application:** Not in the default provider registry, not imported in `/plan`, not included in deployable packages in `pyproject.toml`.
- **Fixture/replay versus observed live:**
  - **Observed Live:** 0 live calls.
  - **Fixture/Replay:** 100% offline synthetic fixtures (14 fixtures with verified key paths and invented leaf values).
- **Default state and actual activation mechanism:**
  - **Default State:** Disabled. Default registry omits `openbnb`.
  - **Activation Mechanism:** Mechanically unconstructible. `StdioOpenBnBTransport` explicitly requires a `LiveActivationApproval` parameter, which no code in the repository instantiates.
- **Outstanding source permission, credentials, cost, or technical requirements:**
  - **Permission / Legal Blocker:** OpenBnB is an unofficial scraper of Airbnb. Airbnb Terms of Service (§11.1) explicitly prohibits automated crawling/scraping. Spec 16 §7 forbids self-approving unclear source permissions.
  - **Technical / Operational Blockers:**
    - Upstream `robots.txt` compliance check fails open when unreadable.
    - Default geocoding egresses traveler location strings to third-party Photon/Nominatim servers.
    - No live schema capture has ever been conducted.
    - Pinned `@openbnb/mcp-server-airbnb@0.3.0` installation is unverified.
- **Smallest explicitly authorized future acceptance run:**
  - **DO NOT ACTIVATE.** Requires a human legal determination and explicit written `LiveActivationApproval`. If ever authorized for a bounded personal demo: 1 single search call for a specific destination window under the 2-call budget.

---

### 2.4 TripAdvisor (Places / POI Adapter)

- **What works through the application:**
  - Offline place adapter in `backend/gateway/places/adapters/tripadvisor/`.
  - Normalizes place search and location details into `PlaceCandidate` with `tripadvisor-discover` licence ID and trust metadata.
  - Entity ledger tracks billable entity counts in SQLite to enforce the free-tier quota.
  - **Not wired to the application:** Not registered in the active planning pipeline; places enrichment remains sample/catalog-backed.
- **Fixture/replay versus observed live:**
  - **Observed Live:** 0 live calls.
  - **Fixture/Replay:** 100% synthetic/recorded fixtures.
- **Default state and actual activation mechanism:**
  - **Default State:** Disabled.
  - **Activation Mechanism:** Requires environment variable `TRIPWISE_TRIPADVISOR_API_KEY` (or MCP endpoint), explicit registry wiring, and human activation approval.
- **Outstanding source permission, credentials, cost, or technical requirements:**
  - **Credentials / Cost:** Requires developer account registration on the TripAdvisor Content API / Terra portal.
  - **Quota / Zero-Spend Constraint:** TripAdvisor free allowance is a one-time lifetime tier of 1,000 entities (not a monthly reset). TripWise enforces an internal safety ceiling of 900 entities to guarantee USD 0 spend.
  - **Terms / Caching Restrictions:** TripAdvisor Content API terms impose strict caching rules (max 24 hours, no review text caching, mandatory display of TripAdvisor logos and deep links).
  - **Architecture:** Direct REST implementation is preferred over MCP due to lack of stable, non-LLM MCP schemas.
- **Smallest explicitly authorized future acceptance run:**
  - Provision 1 developer API key with dashboard billing alerts at $0, execute 1 location search for a known Singapore landmark ("Gardens by the Bay"), verify normalized `PlaceCandidate`, and verify entity ledger increments to 1.

---

### 2.5 Financial-Source Fetching (Crawl4AI & Firecrawl)

- **What works through the application:**
  - Offline financial ingestion architecture (FI0–FI3) is complete in `backend/ingestion/`.
  - `ManualUploadBackend` is active for curator-supplied files.
  - `Crawl4AIBackend` implemented in `backend/ingestion/fetch.py` as an optional backend, enforcing public DNS validation, `robots.txt` crawl delays, and content limits.
  - PDF parsing runs in an isolated subprocess (`pdf_worker.py`) with memory limits and killable deadlines.
  - Human review CLI and web server (`python -m ingestion.review_server`): inspect proposals, record durable decisions, generate content-addressed activation bundles, and run in-memory dry-runs against `KnowledgeBase`.
  - Real issuer pilot demonstrated the complete operator loop on one manually captured HDFC Infinia product page.
- **Fixture/replay versus observed live:**
  - **Observed Live:** Zero automated live web crawling. One real HDFC product page was manually saved in a browser by the human owner (`manual_capture`, 10,280 bytes plain text) and staged offline.
  - **Fixture/Replay:** All tests and CI run against synthetic HTML and PDF fixtures.
- **Default state and actual activation mechanism:**
  - **Default State:** Automated network crawling is disabled. `ManualUploadBackend` is default.
  - **Activation Mechanism (Crawl4AI):** Requires installing the `ingestion-local` extra (`crawl4ai`, Playwright headless Chromium) and injecting a public DNS resolver.
  - **Firecrawl State:** Completely unbuilt. Outlined as optional phase FI4 in `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md`. No SDK, adapter, or configuration exists in the codebase.
- **Outstanding source permission, credentials, cost, or technical requirements:**
  - **Permission / Terms:** Bank websites (HDFC, SBI, Axis, ICICI, etc.) frequently prohibit scraping in website terms. Automated crawling requires per-issuer ToS review and robots.txt clearance.
  - **Technical Requirements (Crawl4AI):** Headless Chromium binaries, system libraries, and DNS resolver setup.
  - **Firecrawl Requirements:** Implementation of FI4, cloud API key (`FIRECRAWL_API_KEY`), and monthly budget controls.
  - **Architectural Non-Negotiable #4:** "Agents propose, humans approve. No autonomous writes of financial facts to the knowledge base. Ever." Regardless of crawler used, facts only reach the knowledge base through human curator approval and bundle application.
- **Smallest explicitly authorized future acceptance run:**
  - For Crawl4AI: 1 single preflight-checked, robots-permitted public card page fetched in a local environment with `ingestion-local` installed, verifying content-addressed storage and text canonicalization without autonomous KB promotion.

---

## 3. Human Action Checklist Before Any Provider Activation

1. **Gondola:**
   - [ ] No action needed for existing OAuth tokens (working tokens preserved in OS keychain).
   - [ ] If renewing: run `backend/gateway/travel/adapters/gondola/scripts/bootstrap_oauth.py` and approve in browser.
   - [ ] Review 2-call per-plan budget constraint if simultaneous hotel + flight discovery is desired.
2. **Open-Meteo:**
   - [ ] Ensure Node.js runtime is installed in the target execution environment.
   - [ ] Install `@cyanheads/open-meteo-mcp-server@0.4.1` verifying against audited lockfile.
   - [ ] Export `TRIPWISE_OPEN_METEO_ENABLED=1` and `TRIPWISE_OPEN_METEO_INSTALL_ROOT`.
3. **OpenBnB:**
   - [ ] **DO NOT ACTIVATE** without written human legal exception to Airbnb ToS §11.1.
4. **TripAdvisor:**
   - [ ] Create developer account on TripAdvisor Terra / Content API.
   - [ ] Confirm $0 billing tier and configure hard alerts.
   - [ ] Set `TRIPWISE_TRIPADVISOR_API_KEY` and verify 900-entity safety cap.
5. **Financial Ingestion:**
   - [ ] Continue with manual capture workflow for bank product pages (`stage-capture`).
   - [ ] Human curator reviews pending proposals via `python -m ingestion.review_server`.
   - [ ] Do not implement automated crawling without explicit issuer terms review.
