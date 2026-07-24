# 08 — Product Vision: Unified Travel Rewards Planner

**Status:** Canonical target product. This document defines the destination; specs 00–07 define the current Kernel MVP used to reach it. When an MVP scope statement sounds permanent, this document decides product scope while specs 01/02/04/07 continue to decide deterministic numeric behavior.

## 0. Operating profile

This is a **non-commercial student/portfolio project**, not a travel startup or production booking business. The active goals are technical depth, a compelling end-to-end demonstration, correct reward math, and thoughtful UX under a near-zero provider budget.

Current decisions:

- active profile: `student_noncommercial`;
- expected usage: one developer, evaluators, and low-volume demo users;
- prefer free/open/personal-use APIs and MCP servers;
- accept quota limits, experimental adapters, and occasional provider downtime;
- keep recorded/sample fallbacks so the demonstration remains reliable;
- never execute a booking, payment, or points transfer;
- do not build commercial scale, SLAs, affiliate economics, or licensed inventory procurement now.

If the project is ever monetized or operated for real customers, that is a separate `commercial_production` scope change. Every provider, retention rule, disclaimer, privacy flow, and operational assumption must be re-reviewed then; student-profile approval never carries forward automatically.

## 1. Product promise

Build one place where a traveler can describe a trip, share the cards and points they own, and receive the best practical itinerary and payment/redemption strategy without manually reconciling itinerary planners, cash metasearch, hotel sites, award-search tools, transfer charts, and card-offer guides.

The product combines **capabilities**, not copies of third-party databases. During the student prototype, external evidence may come from a free/open API, a provider or community MCP explicitly permitted for non-commercial experimentation, licensed/open data, approved offline curation, or a clearly labeled verification/deep link. Every source remains replaceable behind the gateway.

Initial corridor: India → Singapore. The architecture must generalize by adding data and provider configuration rather than changing reward math.

## 2. User problem

Travel rewards planning is fragmented across questions that affect one another:

- Which dates, flights, hotels, and neighborhoods make the trip practical?
- Is a cash fare or award redemption better after taxes, surcharges, transfer ratios, and opportunity cost?
- Are award seats actually visible now, and could they disappear during a transfer?
- Which card, portal, coupon, or bank offer should pay for each expense?
- Are caps, exclusions, forex fees, or expiring bonuses changing the answer?
- How trustworthy and current is every recommendation?

Existing products usually answer one slice. The product must produce one coherent answer and preserve alternatives so the user understands the trade-offs.

## 3. Primary user journey

1. User enters origin, destination, dates/flexibility, travelers, budget, style, interests, pace, and constraints.
2. User selects owned cards and optionally enters card-points and airline/hotel balances. Manual balance entry is the initial mode; bank/loyalty passwords are never requested.
3. The orchestrator runs available flight, hotel, award, card/offer, and itinerary workflows.
4. When the user supplies flexible dates, the stay workflow searches a bounded set of date bands and surfaces the cheapest valid stay window before comparing specific properties.
5. External candidates are normalized, time-stamped, de-duplicated, and labeled by trust state. Same-property comparisons align dates, occupancy, room/rate conditions, currency, and tax/fee completeness.
6. The deterministic kernel computes trip costs, card allocation, discounts, rewards, forex fees, effective cost, transfer paths, and cash-versus-points comparisons.
7. The critic checks feasibility, unsupported claims, quote freshness, incomplete pricing, and inconsistent provider evidence.
8. The user receives a single plan with recommended and runner-up choices, provenance, verification steps, and direct/booking deep links.
9. The user independently verifies and executes any booking or transfer. The platform never performs an irreversible action.

## 4. Product-facing capabilities

| Capability | User-facing responsibility | Primary implementation |
|---|---|---|
| Orchestrator | Coordinate searches and assemble one decision | Typed state machine; bounded reasoning only where necessary |
| Flight Agent | Find and compare suitable cash itineraries | Provider adapters, normalization, deterministic filters/ranking |
| Hotel & Stay Agent | Find the cheapest practical date band, neighborhoods, properties, and comparable rates | Provider adapters, bounded flexible-date search, entity/rate matching, deterministic filters/ranking |
| Award Agent | Find award evidence and evaluate transfer paths | Award adapters + deterministic Transfer Pathfinder |
| Card & Offer Agent | Select payment channel, card, and offers | Deterministic Rewards Optimizer |
| Itinerary Curator | Build realistic days around location, time, and interests | Grounded LLM planner over approved POIs/reference data |
| Critic | Reject or warn on infeasibility and weak evidence | Deterministic checks + bounded LLM critique |
| Explainer | Turn computed artifacts into useful prose | Grounded LLM; copies numbers only |

"Agent" means a bounded capability with a typed contract. It does not imply an autonomous LLM, free-form tool use, or agent-to-agent conversation.

### 4.1 Flight-data responsibilities

The Flight Agent combines four evidence classes without conflating them:

| Evidence | Prototype source | Product meaning |
|---|---|---|
| Current cash itinerary | Gondola MCP first | Candidate `FlightQuote`; verify price/availability before booking |
| Flexible-date price trend | Travelpayouts Data API when enabled | Cached observation used to suggest dates, never a live quote |
| Adapter/test behavior | Duffel test mode + recorded fixtures | `estimated`; validates segments, fare conditions, expiry, and failure handling |
| Award-seat availability | Future free/personal award adapter | Separate `AwardQuote`; always verify before transfer |

Google Flights is a user verification/deep-link destination, not a runtime data API. Recorded award fixtures, curated rules, and optional manual award input keep the zero-budget demo complete until a profile-eligible award adapter exists.

## 5. Required output

Every completed plan should be able to contain:

- day-by-day itinerary and map;
- recommended flight and hotel, plus meaningful alternatives;
- cheapest observed flight-date band when flexibility evidence exists, clearly labeled cached versus current;
- cheapest practical stay window and price range when dates are flexible;
- comparable same-property rates only when occupancy, room/rate conditions, and taxes/fees align;
- cash price, points price, taxes/fees, and effective cost;
- cash-versus-points recommendation with opportunity cost;
- points-transfer steps, timing, bonus, shortfall, and leftover miles;
- best card/payment channel/offer per spend line;
- forex and cap effects;
- total cash outlay now and deferred points value;
- booking and verification links;
- assumptions and unresolved constraints;
- source, retrieval/verification time, confidence, and trust state;
- explicit warnings for stale, estimated, incomplete, or unverified evidence.

No displayed financial number may originate in LLM prose or frontend arithmetic.

## 6. Evidence states

The product distinguishes:

- `live` — provider describes the quote as current and it is inside its expiry window;
- `cached` — real provider data from a declared cache/window;
- `estimated` — sample, sandbox, historical range, or modeled amount;
- `stale` — previously valid evidence outside its accepted freshness window;
- `verify_required` — provider or licence does not support a reliable final claim, or an irreversible action requires first-party confirmation.

These states are visible product information, not internal metadata. A plan may use non-live evidence only when the UI explains the limitation and the recommendation remains safe.

## 7. Product phases

### Phase K — Kernel MVP and full test-data UX

- Complete backend M1/M1b/M2/M3 and frontend F1–F4.
- Use curated sample flights/hotels/POIs and recorded award charts.
- Deliver the complete user journey and premium results UI.
- Label sample inventory `estimated` and seed financial facts `needs_verification`.
- No external inventory dependency.

### Phase G — Gateway foundation

- Add normalized `FlightQuote`, non-bookable `FlightPriceObservation`, `HotelQuote`, and `AwardQuote` contracts.
- Add provider registry, quote freshness, recorded fixtures, and `SampleAdapter`.
- Preserve the Kernel MVP as the default/fallback adapter.

### Phase O — Open/reference data

- Add isolated offline importers for approved FX, airport, and POI sources.
- Preserve licence and attribution metadata.
- Do not put external downloads into kernel golden-test execution.

### Phase P — Student live-provider integrations

- Activate one free/read-only provider at a time under spec 16's student profile.
- First candidate: Gondola MCP for hotel cash/points evidence, flexible-night pricing, direct links, and cash-flight evidence. Import raw evidence; recompute points value and card optimization in the kernel.
- Optional cash-flight trend source: Travelpayouts Data API for cached week/month observations. It informs date exploration but cannot produce a `live` winner.
- Duffel test mode is a contract/error fixture source only; its schedules and prices are not presented as real.
- Second candidate: OpenBnB MCP as an experimental, low-volume rental-stay source, feature-flagged and always `verify_required`.
- Add live award-flight evidence only when a free/personal-use source is available or the human explicitly approves a paid credential. Until then, use recorded/manual evidence and verification links.
- Continue to support partial operation when a provider is unavailable.

### Phase X — Optional acquisition channels

- User-authorized loyalty OAuth, rate alerts, and any browser extension are separate scoped projects.
- A browser extension requires its own terms, privacy, store-review, DOM-maintenance, and security decision.
- Automated phone negotiation is not part of the current prototype; it requires a separate disclosure, consent, recording, regional-availability, and abuse-prevention design.

### Phase C — Future commercial hardening (inactive)

- Replace or contractually authorize every provider for commercial use.
- Revisit caching, redistribution, privacy, affiliate disclosure, observability, scale, support, and SLAs.
- Re-run provider activation under the commercial profile; no student approval is grandfathered.

## 8. Zero-budget strategy

Zero provider spend must not block any required student-project phase. The product begins with test data and open/reference sources, then improves discovery through free anonymous, personal-use, or non-commercial provider access where the service permits it. Paid or gated providers are optional experiments and require explicit human approval.

Free does not mean unbounded or permanent: API quotas, hosting, LLM inference, storage, and maintenance are measured. Local inference and recorded fixtures are valid development modes. The demo must fail soft when a free tier changes or disappears.

## 9. Non-functional requirements

- **Correctness:** deterministic integer money/points calculations; existing golden values remain frozen.
- **Traceability:** every recommendation can be traced to input, computed artifact, and external evidence.
- **Graceful degradation:** one provider failure cannot blank the whole plan; unavailable domains render honest partial states.
- **Freshness:** quote expiry and financial-rule staleness are separate mechanisms.
- **Latency:** the UI reports real workflow progress. Provider searches run concurrently only within configured budgets and rate limits.
- **Cost control:** default provider spend is zero; per-provider/per-request ceilings prevent unbounded fan-out.
- **Security:** secrets server-side; no bank/loyalty passwords; no arbitrary URL fetching.
- **Maintainability:** providers are adapters; provider-specific fields do not leak into the kernel.
- **Accessibility/performance:** existing frontend gates remain binding.

## 10. Success measures

Kernel/demo:

- golden optimizer/pathfinder tests pass;
- complete sample trip produces a schema-valid report;
- every displayed number is grounded;
- users can understand why the recommendation wins.

Target prototype:

- percentage of plans with at least one usable flight/hotel/award evidence source;
- quote freshness at display time;
- provider failure and fallback rates;
- user clicks to verify/book;
- recommendation changes after verification;
- unsupported-claim rate;
- percentage of live-demo plans completed with zero provider spend;
- time from request to first useful partial result.

## 11. Permanent non-goals

- Executing bookings or points transfers.
- Holding or moving user funds.
- Collecting bank or loyalty passwords.
- LLM-generated financial arithmetic.
- Autonomous writes of financial facts.
- Bypassing CAPTCHAs, access controls, paywalls, or provider restrictions.
- Presenting experimental/non-commercial evidence as commercially licensed or guaranteed.
- Pretending award availability or a travel quote is guaranteed.

## 12. Definition of target-product done

For one supported corridor, a user can submit a trip and wallet, the orchestrator can obtain at least one profile-eligible cash/stay evidence source plus an award evidence path when available, the deterministic kernel can compare cash/points/card/offer strategies, and the UI can render one coherent plan with freshness, provenance, alternatives, and verify-before-transfer/booking actions. A flexible-date request can show the cheapest practical stay band and comparable same-property rates. The system remains useful with sample or partial evidence when free providers are unavailable.
