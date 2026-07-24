# Flight data strategy — zero-budget student prototype

**Reviewed:** 2026-07-24
**Profile:** `student_noncommercial`
**Decision:** Gondola for live-demo cash fares; Travelpayouts for cached trends; Duffel for contract fixtures; recorded/manual evidence until an award adapter exists

## The essential separation

“Flight data” is not one interchangeable dataset:

| Question | Required evidence |
|---|---|
| What cash itinerary can I consider now? | Concrete segments, fare, price scope, retrieval/expiry, and verification link |
| Which dates tend to be cheaper? | Cached route/date price observations |
| Does the adapter handle segments, expiry, baggage, and errors? | Sandbox/recorded contract fixtures |
| Can I redeem miles for seats now? | Program-specific award availability plus miles, fees, cabin, and seat count |

The application must never fill one gap with another evidence class. In particular:

- a cached price trend is not a current fare;
- a sandbox offer is not real inventory;
- a cash fare does not prove award availability;
- an award chart does not prove a seat exists;
- a verification link is not extracted data.

## 1. Current cash-flight quotes — Gondola

Gondola’s current official MCP page advertises anonymous/no-key `search_flights` access for real-time cash fares and booking links.

Source: [Gondola MCP](https://www.gondola.ai/mcp)

Prototype use:

- implement `GondolaAdapter.search_flights`;
- use anonymous/read-only tools only;
- normalize ordered segments, carriers, times, cabin/fare brand, baggage, refund/change conditions, total price, currency, retrieval/expiry, and deep link when supplied;
- mark missing taxes/fees or fare conditions through completeness metadata;
- run the India–Singapore spike on DEL–SIN, BOM–SIN, and BLR–SIN;
- measure exact-date/round-trip coverage, latency, rate limits, and result completeness;
- re-check the selected quote once if it expires before final assembly;
- feed the quote into our kernel for card, offer, forex, points-value, and effective-cost calculations.

Gondola’s own ranking or value calculations are not authoritative for this project.

## 2. Flexible-date flight trends — Travelpayouts

Travelpayouts’ Aviasales Data API provides cached date/route prices from recent user searches, including week/month matrices. Its documentation describes cache ages of roughly two to seven days depending on endpoint.

Sources:

- [Aviasales Data API](https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API)
- [Data API access requirements](https://support.travelpayouts.com/hc/en-us/articles/203956083-Requirements-for-Aviasales-data-API-access)

Prototype use:

- optional `TravelpayoutsTrendAdapter`;
- requires a free affiliate token, so connection needs human approval before implementation;
- returns `FlightPriceObservation`, never `FlightQuote`;
- status is `cached` or `stale`, never `live`;
- use observations to prioritize a bounded set of dates for Gondola/current searches;
- show language such as “lowest recently observed date” rather than “current cheapest flight”;
- do not infer complete itineraries, baggage, taxes, or fare conditions from a trend.

If the token is not obtained, generate deterministic date candidates and query Gondola within the configured zero-cost call budget.

## 3. Flight contract and failure testing — Duffel sandbox

Duffel’s test mode is valuable because it exposes structured offers, segments, fare behavior, expiry, price-change, no-result, and error scenarios. Duffel explicitly states that test-mode schedules and prices are not realistic/live.

Sources:

- [Duffel test mode](https://duffel.com/docs/api/overview/test-mode/duffel-airways)
- [Duffel integration test scenarios](https://duffel.com/docs/api/overview/test-your-integration)
- [Duffel offer/expiry schema](https://duffel.com/docs/api/offers/schema)

Prototype use:

- `DuffelSandboxAdapter` is development/test support, not a live-demo provider;
- every normalized result is `estimated`;
- capture sanitized normalized fixtures for multi-segment, no result, expiry, and price change;
- never show a Duffel test price as a real India–Singapore fare;
- never implement order/payment endpoints.

The existing `SampleAdapter` remains the fully deterministic offline fallback.

## 4. Award-flight availability

Gondola’s documented flight tool covers cash fares. Hotel points capability does not imply airline award-seat capability.

The strongest structured personal-use candidate found so far is the seats.aero Pro API. Its official documentation says eligible Pro users can receive up to 1,000 API calls per day for personal non-commercial use, subject to geography and account eligibility. It is not a zero-cost dependency.

Source: [seats.aero Pro API access](https://docs.seats.aero/article/68-do-you-have-an-api)

Zero-budget mode:

- recorded `AwardQuote` fixtures demonstrate orchestration;
- curated transfer ratios, bonuses, award rules/charts, and valuations drive deterministic math;
- optional manual input captures a user-observed program, miles, fees, cabin, date, and seat count;
- airline/award-tool verification links let the user check current availability;
- output remains `estimated` or `verify_required`;
- checklist step 1 remains verify availability before transferring.

If the human later approves the seats.aero cost and access is available, it becomes a separately reviewed `AwardAdapter`. It does not alter Transfer Pathfinder arithmetic.

## 5. Google Flights

Google’s public developer material for Google Flights Search is an airline/OTA partner integration, not an open consumer airfare-search API. The separate public Travel Impact Model API provides emissions, not fares.

Sources:

- [Google Flights Search partner documentation](https://developers.google.com/travel/flights)
- [Google Travel Impact Model API](https://developers.google.com/travel/impact-model)

Prototype decision:

- no Google Flights fare adapter;
- no scraping or browser automation as a data dependency;
- an allowlisted route/date verification link is acceptable;
- emissions could be added later from the free Travel Impact Model API, but it is not needed for pricing.

## 6. End-to-end flight flow

```text
validated trip + flexibility
  → optional cached trend observations
  → deterministic bounded date/date-pair candidates
  → Gondola exact-date current cash searches
  → normalize FlightQuote + expiry/completeness
  → retrieve recorded/manual/live AwardQuote evidence independently
  → deterministic cash/card/offer/forex + transfer comparison
  → critic checks freshness and unsupported availability claims
  → UI shows winner, alternatives, evidence class, and verification links
```

Failure behavior:

- Gondola unavailable → recorded/sample cash itinerary;
- cached trends unavailable → deterministic date generation;
- no award source → `NO_DATA` or recorded/manual `verify_required`, never fabricated availability;
- quote expired → one bounded refresh, otherwise stale/runner-up;
- taxes or itinerary incomplete → cannot win solely on apparent price.

## 7. Implementation gates

### Cash flight spike

- real DEL/BOM/BLR → SIN read-only searches attempted;
- payload schema and omissions documented;
- normalized fixture retained safely;
- no booking scope or payment data;
- zero provider spend;
- fallback visibly works.

### Flexible dates

- `FlightPriceObservation` cannot validate as `FlightQuote`;
- `max_date_pairs` enforced;
- cached wording and UI treatment tested;
- current quote required before bookable winner.

### Awards

- cash and award evidence cannot be mixed by type;
- recorded/manual/live availability states tested separately;
- verify-before-transfer always first;
- missing live availability yields honest partial output.

## Cost conclusion

The required flight demonstration can remain at **$0 provider spend** with Gondola plus recorded/sample fixtures. Travelpayouts requires a free token but no planned spend. Duffel test mode is for fixtures. Live structured award availability remains optional; any paid seats.aero account requires explicit human approval.

No deterministic kernel code or golden values change because of this strategy.

## Documentation and validation

Reflected in:

- `AGENTS.md` / `CLAUDE.md`;
- `docs/ARCHITECTURE.md`;
- specs 00, 01, 06, 07, 08, 09, 12, and 16;
- `DEVIATIONS.md`;
- `reports/free_apis.md` and `reports/beat_the_booking_sites_assessment.md`.

Checks:

- canonical agent briefs are byte-identical;
- all 17 specifications remain present;
- local Markdown links resolve across 25 canonical/report files;
- backend tests: **20 passed**;
- strict type check: **passed for 13 source files**;
- no production code, golden value, or test fixture changed.
