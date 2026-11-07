# Definitive Backend Completion Checklist

**Date:** 2026-11-06  
**Project:** TripWise — "A travel planner that knows your credit cards"  
**Profile:** `student_noncommercial` (Zero out-of-pocket spend ceiling)  
**Authoritative Specifications:** Specs `00`–`09`, `16`–`18`, and `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md`  

---

## 1. Operating Framing & Completion Rules

Per `AGENTS.md` and `docs/DEVELOPMENT_WORKFLOW.md`:
- **Progress means demonstrated, verifiable behavior** through the API, kernel, or operator CLI, not lines of code or test-case volume.
- **Adapter existence is not provider activation.** Disabled offline stubs and fixture harnesses are not live integrations.
- **Frontend, mobile, and deployment scaffolding are excluded** from this backend checklist.
- **Parallel active deliverables are marked IN PROGRESS** and not claimed as complete:
  - Flight selection budgeting (`codex/flight-selection-budgeting`)
  - Financial data readiness (`codex/financial-data-readiness`)
  - Card acquisition Case B (`codex/card-acquisition-case-b`)

---

## 2. Definitive Feature-Level Status Matrix

```
┌──────────────────────────────────────┬──────────────────────────────┬────────────────────────────────────────────────────────┐
│ Capability / Workstream              │ Status                       │ Evidence & Implementation Reference                    │
├──────────────────────────────────────┼──────────────────────────────┼────────────────────────────────────────────────────────┤
│ 1. Core Deterministic Optimizer      │ Demonstrated & Landed        │ `backend/core/optimizer/`, evals/golden/               │
│ 2. Transfer Pathfinder               │ Demonstrated & Landed        │ `backend/core/transfer/`, reports/milestone_1b.md      │
│ 3. Orchestration & FastAPI           │ Demonstrated & Landed        │ `backend/agents/pipeline.py`, `backend/api/`           │
│ 4. Critic, Evals & Provenance        │ Demonstrated & Landed        │ `backend/evals/`, reports/milestone_3.md               │
│ 5. Conversational Domain (CP1–CP3)   │ Demonstrated & Landed        │ `backend/planning/`, reports/cp1_conversational_domain │
│ 6. Durable Planning Jobs             │ Demonstrated & Landed        │ `backend/api/job_manager.py`, `backend/accounts/store.py`│
│ 7. Accounts, Wallets & Auth (A1–A3)  │ Demonstrated & Landed        │ `backend/accounts/`, reports/milestone_a1/a2.md        │
│ 8. Saved Trips & Revisions (A4)      │ Demonstrated & Landed        │ `backend/api/saved_trips.py`, `backend/accounts/store.py`│
│ 9. Privacy / GDPR Export & Deletion  │ Demonstrated & Landed        │ `backend/accounts/store.py` (`export_user`, `delete_user`)│
│ 10. Travel Gateway Contracts (G1)    │ Demonstrated & Landed        │ `backend/gateway/travel/contracts.py`                  │
│ 11. Reference Importers (FX, Air) G2 │ Demonstrated & Landed        │ `backend/gateway/reference/`, reports/g2_open_importers│
│ 12. Weather Context (G4 Open-Meteo)  │ Demonstrated & Landed        │ `backend/gateway/weather/`, reports/g4_open_meteo.md   │
│ 13. Financial Ingestion Core (FI0–3) │ Demonstrated & Landed        │ `backend/ingestion/`, reports/fi0_foundation.md        │
│ 14. Card-Bank Pilot (HDFC Page)      │ Demonstrated & Landed        │ `backend/ingestion/`, reports/card_bank_real_issuer    │
│ 15. Welcome Window Case A (Held)     │ Demonstrated & Landed        │ `backend/welcome/`, reports/held_card_welcome_status   │
│ 16. Hotel Selection Budgeting        │ Awaiting Landing (PR #31)    │ `backend/api/post_plan.py`, PR #31 (CI 4/4 passing)    │
│ 17. Gondola Planning Integration     │ Awaiting Landing (PR #29/30) │ `backend/gateway/travel/adapters/gondola/`, PR #29/30  │
│ 18. OpenBnB Rental Stay Adapter      │ Implemented Offline (Gated)  │ `backend/gateway/travel/adapters/openbnb/`, G3b report │
│ 19. TripAdvisor Place Adapter        │ Implemented Offline (Gated)  │ `backend/gateway/places/adapters/tripadvisor/`, I8A rep│
│ 20. Flight Selection Budgeting       │ IN PROGRESS (Other Agent)    │ Branch `codex/flight-selection-budgeting`              │
│ 21. Financial Data Readiness         │ IN PROGRESS (Other Agent)    │ Branch `codex/financial-data-readiness`                │
│ 22. Card Acquisition Case B (New)    │ IN PROGRESS (Other Agent)    │ Branch `codex/card-acquisition-case-b`                 │
│ 23. Live Flight Quoting to Budget    │ Required & Missing           │ Gap between Gondola observation and costable quote     │
│ 24. Live Award Seat Availability     │ Required & Missing           │ Real-time seat discovery missing (uses static advice)  │
│ 25. Welcome Offers Catalog Content   │ Required & Missing           │ `card_acquisition_offers.yaml` currently 0 rows        │
│ 26. Multi-Airport Expansion          │ Explicitly Deferred          │ Bounded single-airport search only (Spec 16)           │
│ 27. Automated Crawler Monitors (FI4) │ Explicitly Deferred          │ Scheduled crawling / Firecrawl deferred to FI4         │
│ 28. Autonomous KB Promotion          │ Non-Negotiable Exclusion     │ Strictly forbidden; human curator review required      │
│ 29. Live Bookings & Point Transfers  │ Non-Negotiable Exclusion     │ Strictly forbidden; non-commercial informational MVP   │
│ 30. Payment Instrument Storage       │ Non-Negotiable Exclusion     │ Strictly forbidden; PAN/CVV/PIN never stored           │
└──────────────────────────────────────┴──────────────────────────────┴────────────────────────────────────────────────────────┘
```

---

## 3. Detailed Inspection of Specific Acceptance Areas

### 3.1 Flight Selection, Pricing, and Costing
- **Current Landed State:**
  - Estimator uses deterministic sample flights (`SampleFlight` from `core/seeds/sample_flights.yaml`) to build costed trip line items and allocate payment strategies.
  - Gondola MCP adapter live flight search returns `FlightPriceObservation` records from Google Flights (carrier, local departure, round-trip USD price in minor units, stop count). These are attached to `TravelInventoryService` and persisted in planning reports and saved revisions as non-bookable, `verify_required` observations (`reports/gondola_planning_integration.md`).
- **In Progress:**
  - `codex/flight-selection-budgeting` is implementing explicit traveler flight selection budgeting (parallel to PR #31's hotel selection), allowing travelers to choose specific flight options and recompute deterministic budgets.
- **Remaining Gap:**
  - Gondola emits Google Flights Markdown without specific return leg segments or exact booking classes. Converting an unconfirmed price observation into an automated, fully costable `FlightQuote` without human segment selection remains unsupported by the provider interface.

### 3.2 Award Discovery versus Transfer-Path Calculations
- **Current Landed State:**
  - Transfer Pathfinder (`backend/core/transfer/`, Spec 07, `reports/milestone_1b.md`) is complete and deterministic. It evaluates optimal transfer ratios, point valuations, opportunity costs, and fee conversions (e.g. Voyager Prime -> KrisFlyer).
  - Produces typed `TransferAdvice` with `RecommendationKind` (`REDEEM`, `PAY_CASH`, `NO_DATA`) and the mandatory "verify-before-transfer" checklist step.
- **Remaining Gap:**
  - Real-time *award seat inventory discovery* (e.g. checking whether Singapore Airlines Saver award space actually exists on flight SQ403 on 2027-02-10) is missing. Free/open award discovery APIs do not exist under `student_noncommercial`. The system relies on static award chart baselines with explicit verify-required trust badges.

### 3.3 Flexible Dates and Airport Functionality
- **Current Landed State:**
  - Pure date window generation is implemented in `backend/gateway/travel/flexible.py` (Spec 16 §4): `generate_flight_date_pairs` and `generate_stay_windows` produce bounded date candidates from declared ranges without LLM guessing.
  - Same-property rate comparability (`stay_windows_comparable`) deterministically matches property, room type, occupancy, dates, and mandatory fee scope.
- **Remaining Gap / Deferred:**
  - Nearby airport expansion (e.g. searching BOM when DEL is requested) is explicitly deferred. Supported discovery remains strictly origin-airport to destination-airport without multi-airport combinatorial fan-out.

### 3.4 Financial Data Coverage and Update Operations
- **Current Landed State:**
  - Baseline financial facts are seeded in `core/seeds/` (`cards.yaml`, `reward_rules.yaml`, `point_valuations.yaml`, `offers.yaml`, `fx_rates.yaml`).
  - Offline ingestion foundation (FI0–FI3, `backend/ingestion/`) is complete: typed proposal contracts, PDF worker isolation, extraction validation, and curator review CLI/web app (`python -m ingestion.review_server`).
  - Real-issuer pilot (`reports/card_bank_real_issuer_pilot.md`) demonstrated 1 real HDFC product page staging, validation, bundling, dry-run, and rollback.
- **In Progress:**
  - `codex/financial-data-readiness` is actively working on financial data coverage, verified issuers, and staging validation.
- **Remaining Gap / Deferred:**
  - Shipped baseline seeds remain the original fixture values; fresh proposals from the pilot await final human approval before insertion into active seeds.
  - Automated weekly monitoring and Firecrawl integration (FI4) are deferred. All updates remain batch, local, and curator-driven.

### 3.5 Card Acquisition & Welcome Offers (Spec 18)
- **Current Landed State (Case A):**
  - Held-card welcome window status is implemented in `backend/welcome/` (`reports/held_card_welcome_status.md`).
  - Endpoint `POST /account/wallet/{entry_id}/welcome-status` computes window deadlines, remaining minimum spend, and conditional contribution from planned trip spend.
- **In Progress (Case B):**
  - `codex/card-acquisition-case-b` is actively implementing gated acquisition recommendations for unheld cards.
- **Remaining Gap:**
  - The shipped welcome offers database (`backend/welcome/data/card_acquisition_offers.yaml`) has 0 approved rows. Case A queries mechanically return `status: "unknown"` and `NO_APPROVED_OFFER` until human-curated welcome offers are populated.

### 3.6 Persistence, Concurrency, and Restart Behavior
- **Current Landed State:**
  - Planning Sessions: Backed by SQLite `AccountStore` with optimistic version checks (`expected_version`), idempotent `client_event_id` handling, and TTL expiration.
  - Durable Jobs: SQLite job runner via `AccountStore` and `backend/api/job_manager.py` (PR #28) ensures `/plan` background processing survives server restarts; polling recovers progress.
  - Saved Trips & Revisions: Immutable `SavedTrip` and append-only `TripRevision` persisted in `accounts.db` via `backend/api/saved_trips.py` and `backend/accounts/store.py` (A1/A4).
  - Hotel & Flight Selection State: Stored across revisions, idempotent, and protected against stale parent revisions.
  - Ingestion Decisions: Replay-safe SQLite persistence for proposals, audit logs, and activation bundles.

### 3.7 Account, Security, and Privacy Flows
- **Current Landed State:**
  - Authentication: Argon2id password hashing, server-side hashed session tokens, HTTP-only cookies, and CSRF protection on mutation routes (A2).
  - Security Invariants: Model-level `extra="forbid"` and forbidden field AST checks guarantee PAN, CVV, PIN, and net-banking credentials can never be accepted or stored.
  - Privacy / GDPR: Fully implemented in `backend/accounts/store.py`:
    - `export_user(user_id, now=...)` returns a complete, user-scoped JSON archive (`UserExport`) of profile, wallet entries, saved trips, revisions, and planning sessions.
    - `delete_user(user_id)` performs a cascading hard-delete across all user tables.

---

## 4. Workstreams Awaiting Landing / Integration

1. **PR #31 — Explicit Hotel Selection Budgeting (`codex/hotel-selection-budgeting`):**
   - Head: `ce9acafd68a3f3cca53197831db2844e0fa71922`
   - Checks: **4/4 passing (Backend, Frontend, Contract Drift, Containers/Smoke)**.
   - Status: Complete and verified offline; awaiting human review and merge.
2. **PR #29 / PR #30 — Gondola Planning Integration:**
   - Retains live hotel rates and flight observations in authenticated planning and saved revisions.
   - Status: Reconciled and demonstrated; awaiting final branch landing.

---

## 5. Workstreams In Progress (Other Agents)

1. **Flight Selection Budgeting (`codex/flight-selection-budgeting`):**
   - Extending CP4 actions to support explicit traveler flight selection, retained options, traveler-asserted totals, and deterministic payment strategy recomputation.
2. **Financial Data Readiness (`codex/financial-data-readiness`):**
   - Expanding issuer coverage, validating live bank terms, and preparing curated financial fact bundles for insertion into the Knowledge Base.
3. **Card Acquisition Case B (`codex/card-acquisition-case-b`):**
   - Spec 18 Case B implementation: conservative, eligibility-checked suggestions for new credit cards when trip spend justifies a high-value welcome bonus.

---

## 6. Externally Blocked or Non-Activated Items

1. **OpenBnB Live Adapter:**
   - Blocked by Airbnb Terms of Service §11.1 (scraping prohibition). Requires human legal waiver (`LiveActivationApproval`). Stays disabled.
2. **TripAdvisor Live Adapter:**
   - Blocked by credential requirement (API key) and strict 24-hour caching/attribution constraints. Stays disabled.
3. **Automated Live Financial Crawling:**
   - Blocked by issuer website terms and need for headless browser orchestration. Stays disabled in favor of curator manual capture.

---

## 7. Explicitly Deferred / Non-Negotiable Non-Goals

1. **Live Booking & Checkout:** Informational prototype only; system never executes transactions.
2. **Points Transfer Execution:** Transfers remain manual traveler checklists; system never logs into loyalty programs.
3. **Payment Instrument Storage:** Strict architecture forbids storing real card numbers or credentials.
4. **Autonomous KB Writes:** System never writes financial rules without human curator sign-off.
5. **Commercial-Scale Infrastructure:** Caching clusters, multi-region failover, commercial API subscriptions, and monetization are out of scope.
