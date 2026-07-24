# `Beat the Booking Sites` — project assessment

**Reviewed:** 2026-07-24
**Source:** `Beat_the_Booking_Sites.pdf` (7 pages, undated in PDF metadata)
**Project profile:** `student_noncommercial`
**Decision:** adopt the workflow; evaluate Gondola first; treat OpenBnB as experimental; defer phone negotiation

## Why this matters

The PDF demonstrates a compact travel-shopping loop:

1. scan a flexible date window for the cheapest stay period;
2. compare the same accommodation across available channels;
3. shortlist practical listings and provide a direct link;
4. optionally call the property to negotiate.

That loop complements this project’s existing differentiator. The PDF optimizes *where and when to book*; our kernel adds *cash versus points, transfer paths, card rewards, offers, forex fees, caps, and explainability*. Together they describe a much stronger demo than either system alone.

The PDF is not an implementation specification. Its shared `trip-plan.md` state, prompt-driven calculations, browser ranking, provider claims, and phone workflow are intentionally translated into typed, deterministic components.

## Operating assumption

This repository is a non-commercial student/portfolio project. It is acceptable to use free, personal-use, or experimental read-only services for low-volume demonstrations when:

- the source is explicitly allowlisted;
- its source method and uncertainty are visible;
- the integration does not execute bookings, payments, or transfers;
- the application does not bypass robots rules, access controls, CAPTCHAs, or blocks;
- provider output is normalized and all financial math is recomputed locally;
- recorded/sample evidence keeps the demo usable when the provider is unavailable.

A future commercial version would re-review and replace/license providers. Commercial readiness is not a gate for the current project.

## Provider findings

### Gondola MCP — preferred first live adapter

Current official material describes:

- anonymous, no-key search tools;
- structured hotel cash and points rates;
- hotel detail, review, direct-link, price-context, and multi-night-rate tools;
- cash flight and rental-car search;
- optional OAuth 2.1/PKCE for loyalty accounts, balances, certificates, trips, alerts, and booking permissions;
- separate read and booking scopes.

Sources:

- [Gondola MCP capabilities](https://www.gondola.ai/mcp)
- [Custom-client/OAuth guide](https://www.gondola.ai/help/mcp-oauth-integration)
- [Gondola terms](https://www.gondola.ai/terms-of-service)

Project decision:

- implement as `GondolaAdapter` behind the Data Gateway;
- begin with anonymous/read-only search tools;
- never request `mcp:book`;
- do not transmit payment methods or traveler identity;
- use raw cash totals, points totals, taxes/fees, room/rate terms, and source links;
- ignore provider-calculated cents-per-point, card strategy, and portfolio ranking when producing our recommendation;
- recompute all value through the deterministic kernel;
- keep `SampleAdapter` as the fallback.

The official developer page invites custom-client embedding, while the general terms contain personal/non-commercial restrictions. That tension does not block the current student profile, but the adapter would require written clarification or replacement before commercialization.

### OpenBnB — experimental rental adapter

The hosted service currently advertises:

- a free hosted MCP endpoint;
- rental listing/date/guest/budget search;
- listing details, amenities, locations, prices, and deep links;
- free signup with no card.

The hosted terms describe personal/non-commercial/internal use, allow programmatic MCP access, reserve the ability to limit or remove the free tier, and place third-party authorization responsibility on the user. The related open-source implementation accesses Airbnb listing/search content and includes an option to ignore robots rules.

Sources:

- [OpenBnB hosted service](https://openbnb.ai/)
- [OpenBnB terms](https://openbnb.ai/terms)
- [Open-source MCP implementation](https://github.com/openbnb-org/mcp-server-airbnb)
- [Airbnb terms](https://www.airbnb.com/help/article/2857)

Project decision:

- evaluate only as `OpenBnBAdapter` under `student_noncommercial`;
- local/portfolio-demo visibility only;
- low-volume, user-initiated, read-only requests;
- never enable a robots override or use proxy/block circumvention;
- feature flag off by default;
- mark normalized evidence `experimental` and `verify_required`;
- do not persist raw responses when retention rights are unclear;
- never make it the only stay source.

This is useful prototype evidence, not a stable or commercially reusable data foundation.

### Phone negotiation services — not current scope

The PDF’s final step suggests an AI voice agent calling a property for a direct quote. It could be a compelling future experiment, but it introduces:

- bot disclosure;
- call-recording and consent rules that differ by jurisdiction;
- phone-number sourcing and personal-data handling;
- regional provider coverage;
- variable per-minute costs;
- prompt injection/social-engineering risk during a live call;
- ambiguity over whether a quoted rate is complete, cancellable, or bookable.

Project decision: no automated calls in the current build. A future rate-inquiry experiment needs its own consent/compliance and typed quote-capture specification. It still must not commit to or execute a booking.

## Workflow translation

| PDF concept | Project implementation |
|---|---|
| Four prompts/skills | Fixed typed workflows coordinated by the orchestrator |
| Shared `trip-plan.md` | `PlanContext`, domain results, normalized quotes, and trace events |
| Scan every possible start day | Deterministic `FlexibleStaySearchRequest` expanded within `max_start_dates` and call budgets |
| Cheapest week | Cheapest comparable stay window, with completeness/freshness requirements |
| Cheapest neighborhoods | Deterministic aggregates with a minimum sample count |
| Same hotel across sites | Conservative entity matching plus identical dates, occupancy, room/rate, currency, and mandatory-fee scope |
| Review score divided by price | Optional deterministic ranking only after review scales are normalized; never LLM arithmetic |
| Skip sponsored results | `placement` metadata; sponsored placement is never a positive signal |
| Plain booking link | Allowlisted deep/verification URL; user completes the action |
| Provider points math | Raw evidence only; our kernel recomputes every financial comparison |
| Direct negotiation call | Deferred separate experiment |

## Proposed student-project sequence

1. Finish the existing Kernel MVP and F4 test-data application.
2. Implement G1 normalized evidence models, provider registry, flexible-stay request expansion, and `SampleAdapter`.
3. Run a manual read-only Gondola schema/search spike for India → Singapore.
4. Capture minimal sanitized normalized fixtures and build `GondolaAdapter`.
5. Demonstrate:
   - flexible-date hotel price bands;
   - hotel cash versus points evidence;
   - cash flight evidence;
   - direct verification links;
   - our own card/points/transfer optimizer over those quotes.
6. Run an isolated OpenBnB experiment for Singapore rentals. Enable it in the portfolio demo only if stability and source warnings are acceptable.
7. Add award-flight evidence separately; Gondola’s documented flight capability does not replace a dedicated award-seat source.

The complete cash/trend/sandbox/award sourcing decision is maintained in `reports/flight_data_strategy.md`.

## Cost expectation

Provider spend can remain **$0 for the required student prototype** if Gondola’s anonymous/free access remains available and OpenBnB is used only within its free tier. The system must not promise permanent free availability. A provider outage or quota change falls back to sample/recorded evidence.

LLM inference and optional hosting may still cost money depending on the selected model/platform. Paid award sources, voice calls, and credentialed services remain opt-in and require explicit human approval.

## Documentation impact

This assessment is reflected in:

- `docs/ARCHITECTURE.md`;
- specs 00, 01, 03, 05, 06, 07, 08, 09, 12, 14, and 16;
- `AGENTS.md` / `CLAUDE.md`;
- `DEVIATIONS.md`;
- the dated addendum in `reports/free_apis.md`.

No deterministic kernel code or golden value changes as a result of this report.

## Validation

- `AGENTS.md` and `CLAUDE.md` are byte-identical.
- All 17 specification files remain present.
- Local Markdown links resolve across the canonical documents and provider reports.
- Backend tests: **20 passed**.
- Strict type check: **passed for 13 source files**.
- No production code or test fixture was modified.
