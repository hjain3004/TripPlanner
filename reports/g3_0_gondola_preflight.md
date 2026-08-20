# G3.0 — Gondola Live-Provider Feasibility, Security and Activation Preflight

**Milestone type:** Research, architecture, and planning only. No code was written, modified, or executed. No live search, credential, provider quota, or paid service was consumed.

**Branch:** `docs/g3-gondola-preflight` (worktree at `.worktrees/docs-g3-gondola-preflight`), based on `main` @ `43c4191` (G1+G2 merged).

---

## 1. Executive decision

**Decision: B — Eligible only for offline fixture-backed adapter development.**

Gondola's hotel-search contract is real, currently live, genuinely free for anonymous read-only search, and worth building an offline, fixture-backed adapter against now. However, **live activation is not approved** because of three unresolved, evidence-backed problems, none of which this preflight can close without a human/Gondola-side action:

1. **An unresolved, direct contradiction between Gondola's own product and its own legal terms.** Gondola's general Terms of Service (last revised January 30, 2024 — before the MCP product existed) explicitly prohibit "any robot, spider, scraper or other automated means" of accessing the Service. Gondola's MCP documentation (last updated June 20, 2026) offers exactly that: automated, agentic access. No MCP-specific terms, developer terms, or API terms exist anywhere that carve out an exception. This is not an inference — it is two live, official Gondola pages saying incompatible things, cited in full below (§6).
2. **The project's primary use case — India→Singapore flight evidence — is the one domain that requires sign-in**, and independent evidence suggests Gondola's flight coverage may be US-carrier-centric. Hotel search (the domain that *is* anonymous and free) is not the corridor's most load-bearing need.
3. **No rate limit, quota, or programmatic-access pricing policy is documented anywhere** for the MCP specifically. "Free" language is scoped to the consumer-facing product; there is no developer/API pricing page, which means zero-spend cannot be mechanically proven — it can only be self-imposed by our own adapter, not guaranteed by Gondola.

Per spec 16 §7 and this milestone's own rule ("no unresolved FAIL and no cost/permission UNKNOWN" for an A rating), items 3–4 and 8–9 of the ten-point checklist land at CONDITIONAL/UNKNOWN (§12), which forecloses decision A. The hotel-search contract shape, tool schemas, and product legitimacy are well-evidenced enough that outright ineligibility (C) would discard real, reusable design value; the evidence is also not so thin as to justify "not enough evidence" (D) — it is specific, sourced, and points to a clear, bounded set of open questions a human can resolve (contact Gondola for MCP-specific terms clarification; re-verify flight coverage before ever wiring `search_flights`).

---

## 2. Evidence methodology

Research was conducted live during this session via web search and direct page fetches against Gondola's own domains (`gondola.ai`, `mcp.gondola.ai`, `help.gondola.ai`) and independent third-party sources (travel-industry blogs). The pre-existing `reports/free_apis.md` entry on Gondola (written 2026-07-24) was treated as a lead only, per this milestone's explicit instruction, and **several of its claims did not survive re-verification** — most importantly, its claim of anonymous "cash flights" access (§7). No MCP tool was invoked; no search was run; no account was created; no credential was obtained. Tool schemas were read from Gondola's own public documentation page, not from a live-connected, locally-installed MCP client (no such client was installed or connected in this session).

**Depth:** ~10 targeted search/fetch operations across primary (Gondola-owned) and independent third-party sources — proportionate to a "Thorough" research pass under the `firecrawl-deep-research` skill's depth tiers, given the scope of the 20-section report and decision-gate stakes required by this milestone.

**Source confidence key used throughout:** **Explicit** = stated directly in the cited source. **Inferred** = derived from stated facts but not stated verbatim. **High/Medium/Low confidence** reflects source authority (Gondola's own pages > independent industry press > general web search synthesis) and corroboration across sources.

---

## 3. Identity and ownership

| Question | Finding | Confidence |
|---|---|---|
| Product/server evaluated | "Gondola MCP" — a remote-hosted MCP server operated by Gondola AI Inc., exposing the same hotel/vehicle/flight search and loyalty-points engine used by the consumer site `gondola.ai` | High (primary) |
| Legal owner | **Gondola AI Inc.** | High (primary — ToS text) |
| Canonical website | `https://www.gondola.ai/` | High |
| Canonical MCP endpoint | `https://mcp.gondola.ai/mcp` (remote HTTP transport; connect via `claude mcp add --transport http gondola https://mcp.gondola.ai/mcp` or equivalent) — **not** an installable npm/pip package | High (primary — `gondola.ai/mcp` setup instructions) |
| Official vs. community | **Official, first-party, maintainer-hosted.** Gondola AI Inc. operates both the consumer product and the MCP server. This is not a community wrapper around a third-party API. | High |
| Source code repository | **None found.** No GitHub repository, npm package, or PyPI package for a Gondola-authored MCP server implementation was located via targeted search. The MCP is a closed-source, remote-hosted service — there is no server-side code to statically audit (see §11). | Medium-High (absence is harder to prove than presence; search was thorough but not exhaustive) |
| Current version/commit | No version number is published on the MCP documentation page; only a "Date of Last Revision" is shown for the ToS (Jan 30, 2024) and a "last updated" date on the MCP integration guide (June 20, 2026). There is no pinned commit to review because there is no public repository. | High |
| Software licence compatibility | **Not applicable in the traditional sense** — there is no open-source server codebase with its own licence to evaluate. The only governing document is Gondola's Terms of Service (§6), which governs *use of the service*, not *redistribution of code*. | High |
| Company legitimacy | Real, VC-backed startup: founders Skyler Erickson and Xan Tanner (co-founders), with Justin Hnatow (engineering) and Ashna Gupta (growth) named on the team page; backed by Next View Ventures and Maven Ventures. Delaware corporation per ToS governing-law clause. | Medium (single source, `gondola.ai/about`, not independently corroborated by a corporate registry lookup in this preflight) |
| Data rights vs. code rights | Since there is no open-source code, this distinction collapses to a single question: **does the Terms of Service grant rights to programmatically access and use the underlying travel data via the MCP?** The answer is unresolved (§6) — the ToS's own text (personal/non-commercial use permitted; automated access prohibited) contradicts the existence of the MCP product itself. | High (this is the central finding of this preflight) |

**Sources:**
- [Gondola MCP — Hotel Search for AI Agents](https://www.gondola.ai/mcp), Gondola AI Inc., accessed 2026-08-20. Explicit: tool list, endpoint URL, auth model.
- [Gondola Terms of Service](https://www.gondola.ai/terms-of-service), Gondola AI Inc., "Date of Last Revision: January 30, 2024," accessed 2026-08-20. Explicit: entity name, use restrictions, governing law.
- [About - The Hotel Booking Tool for Frequent Travelers](https://www.gondola.ai/about), Gondola AI Inc., accessed 2026-08-20. Explicit: founders, backers.
- [Build your own client with the Gondola MCP](https://www.gondola.ai/help/mcp-oauth-integration), Gondola AI Inc., "Last updated June 20, 2026," accessed 2026-08-20. Explicit: OAuth flow, terms-reference (only the same general ToS).

---

## 4. Pricing and zero-spend proof

**Claim under test:** "Gondola is free, no API key or account required."

**Finding: Explicit and corroborated for anonymous search, but incomplete for programmatic/MCP-specific volume use.**

- Gondola's own MCP page states: *"Completely free. No account, no API key, no credit card"* required for the 19 no-sign-in tools (High confidence, primary source, `gondola.ai/mcp`).
- No pricing page, developer/API pricing tier, or overage policy was found anywhere on `gondola.ai` for programmatic/MCP access specifically. This is a genuine **absence of evidence**, not evidence of a hidden cost — but per this project's own standing rule ("free credits" are insufficient if overage is possible; "unknown financial exposure means disabled"), the absence of a *documented ceiling* is itself disqualifying for live activation, because our adapter cannot mechanically prove a zero-spend guarantee that Gondola itself has not published.
- The consumer-facing monetization model is affiliate/booking-commission based: independent reporting (Frequent Miler, July 24 2026 review) states bookings are made "directly with the hotel" and that the reviewer's own site earns "a commission on paid bookings" through referral links — consistent with Gondola not charging *searchers*, but not evidence one way or the other about whether *high-volume automated MCP callers* could ever be rate-limited into a paid tier or blocked.
- **No rate limit, quota, or fair-use policy is documented** for the MCP anywhere found (`gondola.ai/mcp`, the MCP OAuth integration guide, or the July 2026 "Best Travel MCP Server" blog post all omit this).

**Conclusion:** Cost exposure for *anonymous hotel search specifically* is plausibly USD 0 based on explicit "no account, no API key, no credit card" language, but this cannot be classified as **mechanically proven zero-spend** in the sense this project requires, because (a) no rate-limit/fair-use policy exists to bound abuse-triggered blocking or throttling, and (b) flight search requires sign-in with unknown downstream terms. Per this milestone's own rule, this is classified **UNKNOWN, not PASS**, for the purposes of the spec-16 checklist (§12).

**Sources:**
- [Gondola MCP](https://www.gondola.ai/mcp), Gondola AI Inc., accessed 2026-08-20. Explicit: "Completely free. No account, no API key, no credit card."
- [Gondola: My go-to hotel award search tool...](https://frequentmiler.com/gondola/), Frequent Miler, updated July 24, 2026. Explicit: commission disclosure; "booked directly with the hotel."
- [New Tool for Booking Hotels, Gondola, Is Available to the Public](https://upgradedpoints.com/news/gondola-hotel-booking-tool/), Upgraded Points, July 21, 2025. Explicit: "3% in Gondola Cash" cashback mechanism; email-based signup requirement (at that time).

---

## 5. Authentication requirements

Directly from Gondola's own MCP tool inventory (`gondola.ai/mcp`, accessed 2026-08-20, High confidence):

| Tier | Tool count | Examples | Auth |
|---|---|---|---|
| No sign-in | 19 | `search_hotels`, `get_hotel_details`, `compare_rates`, `get_booking_link`, `predict_price`, `get_multi_night_rates`, `search_vehicles`, `get_hotel_reviews`, `get_booking`, `diagnose_rates` | None — explicitly "Search works with no account" |
| Sign-in required (OAuth 2.1/PKCE) | 9 | `search_flights`, `get_rate_alerts`, `get_upcoming_trips`, `get_past_trips`, `get_loyalty_accounts`, `get_free_night_credits`, `get_travel_profiles`, `get_traveler_context`, `update_traveler_profile` | User OAuth login; server returns `401` to trigger the flow when a gated tool is called |
| Write permission | 2 | `create_rate_alert`, `delete_rate_alert` | Sign-in required |
| Booking-partner only | 4 | `book_hotel`, `get_payment_methods`, `book_vehicle`, `cancel_vehicle_booking` | Requires "`mcp:book` scope, granted only to approved booking partners" — **not available to a general integrator regardless of sign-in** |

**Critical correction to the prior internal report:** `reports/free_apis.md` (2026-07-24) stated Gondola offers "cash flights" via anonymous search. **This is not supported by current evidence.** `search_flights` is in the **sign-in-required** tier, not the anonymous tier. Flight search — the domain most relevant to this project's India→Singapore corridor — requires a per-user OAuth login, which this project's architecture (a stateless, non-account-bound deterministic kernel demo) is not designed to obtain or manage for a backend service call, and which raises its own data-handling questions (whose account, whose loyalty data, what happens to session tokens) not evaluated by this preflight because it was out of scope to attempt.

**Sources:**
- [Gondola MCP](https://www.gondola.ai/mcp), Gondola AI Inc., accessed 2026-08-20. Explicit: full tool-tier breakdown.
- [Build your own client with the Gondola MCP](https://www.gondola.ai/help/mcp-oauth-integration), Gondola AI Inc., last updated June 20, 2026. Explicit: "Search works with no account"; 401-triggered OAuth flow.

---

## 6. Terms and permitted-use analysis (no legal conclusions — evidence only)

Direct extracts from [Gondola's Terms of Service](https://www.gondola.ai/terms-of-service) (Gondola AI Inc., "Date of Last Revision: January 30, 2024," accessed 2026-08-20 — High confidence, primary source):

- **Personal/non-commercial use is explicitly permitted:** *"you will only use the Service for personal and non-commercial purposes."* This aligns with this project's `student_noncommercial` profile.
- **Commercial use is explicitly prohibited:** users may not "display, distribute, license, perform, publish, reproduce...for any commercial purposes any portion of the Service."
- **Automated access is explicitly prohibited:** *"you will not access, monitor or copy any content on our Service using any robot, spider, scraper or other automated means or any manual process."*
- **No MCP-specific, developer, or API terms exist.** The MCP integration guide's only terms link is to this same general ToS page — confirmed by direct inspection of `gondola.ai/help/mcp-oauth-integration`.
- **Data retention (one-directional):** Gondola "retains rights to user data for service improvement and marketing purposes" — this describes Gondola's rights over *user-supplied* data, not our rights over *results we retrieve*. No clause addresses caching, storing, or redistributing search results we obtain.
- **No attribution requirement is stated anywhere found.**
- **No geographic restriction is stated**, beyond a general "comply with all local rules and laws" clause.
- **Governing law:** Delaware; exclusive jurisdiction in Kent County, Delaware courts.
- **Liability/accuracy disclaimer:** Gondola disclaims *"the accuracy, completeness, or reliability of the suggested travel products"* and provides the service "AS IS," "all warranties...disclaimed" — this is standard, but it also means Gondola itself does not warrant the freshness/correctness of the data it returns, which matters for how the future adapter would classify evidence status (§7).

**The central, unresolved tension:** Gondola simultaneously (a) forbids "any robot, spider, scraper or other automated means," and (b) officially publishes and markets an MCP server whose entire purpose is automated, agentic access (its own July 19, 2026 blog post is titled "The Best Travel MCP Server for AI Agents"). No page anywhere — the ToS, the MCP docs, the OAuth integration guide, or the blog posts — resolves this contradiction or states that MCP access is exempted from the anti-automation clause. This preflight does not conclude that MCP use *violates* the ToS (that is a legal conclusion outside this milestone's authority per CLAUDE.md's ambiguity protocol, which reserves "legal/compliance wording" for human judgment) — it concludes that **the evidence is materially ambiguous**, which per this milestone's own explicit instruction is grounds to withhold live-activation approval pending human clarification (e.g., contacting `concierge@gondola.ai`, the support address surfaced during research, for a written statement that MCP access is permitted use).

**Sources:**
- [Gondola Terms of Service](https://www.gondola.ai/terms-of-service), Gondola AI Inc., Jan 30, 2024, accessed 2026-08-20.
- [Build your own client with the Gondola MCP](https://www.gondola.ai/help/mcp-oauth-integration), Gondola AI Inc., June 20, 2026, accessed 2026-08-20.
- [The Best Travel MCP Server for AI Agents](https://www.gondola.ai/blog/best-travel-mcp-server), Gondola AI Inc., July 19, 2026, accessed 2026-08-20.

---

## 7. Data-source and freshness semantics

| Domain | Tool(s) | Classification | Evidence |
|---|---|---|---|
| Hotel cash rates | `search_hotels`, `get_hotel_details`, `compare_rates` | **Marketed as live**, but independent evidence of staleness exists (below) — classify **verify_required**, not `live`, until corroborated | Gondola markets "live rates" (blog); Frequent Miler review reports rooms shown as available that were unavailable at checkout |
| Hotel points/loyalty rates | `search_hotels` (same call returns both cash and points pricing per Gondola's own description) | **estimated/verify_required** — points pricing is provider-computed and must never be trusted as kernel-ready arithmetic per this project's Tier-F rule; only the raw miles/points/cash figures may be evidence | Gondola markets "Same Member rates, points redemptions...a traveler would see logged in" |
| Multi-night/flexible-date hotel rates | `get_multi_night_rates` | **estimated** | Tool exists per schema; no independent freshness evidence found |
| Flight cash quotes | `search_flights` | **unknown / not evaluated** — sign-in gated, not reachable without an account this project does not plan to obtain for a backend service | §5 |
| Award/points availability (flights) | Not offered as a distinct tool — `search_flights` appears to blend cash and rewards pricing, not a dedicated award-availability domain | **unknown** | No distinct award-search tool found in the schema |
| Property metadata | `get_hotel_details`, `get_hotel_reviews`, `get_similar_hotels`, `get_hotel_stats` | Reference-style data, not price-bearing | — |
| Direct booking/verification links | `get_booking_link`, `get_vehicle_booking_link` | Returns a link for the user to complete checkout on Gondola/partner site — **not** itself a booking action | `gondola.ai/mcp` tool list |
| Provider-computed cents-per-point / rewards recommendations | `optimize_loyalty_portfolio`, `predict_price`, `credit_card_coverage` | **Provider-computed financial guidance exists as a tool and must never enter this project's deterministic recommendation as trusted arithmetic** — this project's kernel recomputes all such values independently, per the non-negotiable rule already governing every other provider in this codebase | `gondola.ai/mcp` tool list |
| Sponsored placement / affiliate content | Not disclosed as a field in any available schema excerpt; Gondola's own business model is commission-based (§4), so a ranking-bias risk cannot be ruled out and must be assumed present until proven otherwise | **unknown, treated as present by default** | Inferred from business model, not stated in tool docs |

**Independent reliability signal (Medium confidence, single source but specific and dated):** Frequent Miler's July 24, 2026 review documents user-reported cases where "hotels appeared available for my dates, but when I tried to book...only then did I see that rooms were not available," and a case where a Bali search returned "hotels randomly across the US" — a geographic-relevance bug. Both are directly relevant to this project's non-US corridors (India, UAE, Singapore) and support treating Gondola hotel evidence as `verify_required` rather than `live`, consistent with this project's existing trust-state vocabulary (spec 16 §3).

Field-level completeness (taxes, traveler count, occupancy/room count, cancellation/refundability, flight segments/cabin/baggage, provider quote IDs, expiry) **could not be verified** from marketing/help pages alone — this requires inspecting an actual tool response, which this preflight explicitly did not do (no search was invoked). This is recorded as an open unknown (§17), to be resolved during offline fixture design by requesting (not scraping) a sample response shape from Gondola support, or by constructing conservative synthetic fixtures that assume the worst case (partial completeness) until proven otherwise — consistent with how this project already handles `SampleAdapter` and Tripadvisor evidence.

**Sources:**
- [The Best Travel MCP Server for AI Agents](https://www.gondola.ai/blog/best-travel-mcp-server), Gondola AI Inc., July 19, 2026.
- [Gondola: My go-to hotel award search tool...](https://frequentmiler.com/gondola/), Frequent Miler, updated July 24, 2026.
- [Gondola MCP](https://www.gondola.ai/mcp), Gondola AI Inc., accessed 2026-08-20.

---

## 8. Geographic coverage matrix

| Corridor need | Flights | Hotels | Points rates | Flexible dates | Direct links | Currencies | Known exclusions | Confidence |
|---|---|---|---|---|---|---|---|---|
| India (origin, home market) | Unknown — gated behind sign-in, not evaluated | Unknown — no explicit statement of Indian hotel-market coverage found | Unknown | Unknown | Unknown | Unknown | No positive evidence of India coverage found in any source reviewed | **Low** |
| UAE (home market) | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | No positive evidence found | **Low** |
| USA (home market) | Explicit — independent review names United, Delta, American, Alaska as flight partners | Explicit — major US-heavy chains named (Marriott, Hilton, Hyatt, IHG, Accor, Wyndham) | Explicit — "Member rates, points redemptions" | Explicit — `get_multi_night_rates` tool exists | Explicit — `get_booking_link` tool exists | Not stated; inferred USD | None found for US | **Medium** (independent + primary, but no first-party coverage statement) |
| Singapore (initial-corridor destination) | Not evaluated (sign-in gated) | Unstated — Gondola names "Marriott, Hilton, Hyatt, IHG, Accor" which all operate in Singapore, but this is an inference from brand presence, not a coverage statement | Unstated | Unstated | Unstated | Unstated | No explicit statement either way | **Low** (inferred only) |
| Europe / UK | Not evaluated | Unstated; same brand-presence inference as Singapore | Unstated | Unstated | Unstated | Unstated | No explicit statement | **Low** |
| Worldwide / long-term | Marketing language ("Search Every Hotel Suite in the World") exists on a dedicated `gondola.ai/suites` page, but this is promotional copy, not a documented coverage list | — | — | — | — | — | Reviewer explicitly reported a *failure* of worldwide relevance (Bali search returning US hotels) | **Low** — a marketing claim of "world" coverage was directly contradicted by an independent reviewer's own test |

**Conclusion:** No first-party, structured coverage matrix (supported countries, airport list, hotel-market list, or currency list) exists in any Gondola documentation found. Coverage evidence is strongest for the US market and essentially absent for this project's actual initial corridor (India → Singapore) and home markets (India, UAE). This is a material feasibility gap independent of the terms and cost questions in §§4–6, and independent evidence (the Bali search bug) actively suggests non-US search relevance may currently be unreliable, not merely undocumented.

**Sources:**
- [Gondola: My go-to hotel award search tool...](https://frequentmiler.com/gondola/), Frequent Miler, updated July 24, 2026.
- [Search Every Hotel Suite in the World](https://www.gondola.ai/suites), Gondola AI Inc., accessed 2026-08-20 (marketing page, not a coverage specification).
- [About](https://www.gondola.ai/about), Gondola AI Inc., accessed 2026-08-20.

---

## 9. MCP tool inventory (schema inspection only — no tool was invoked)

All 34 tools below are recorded from Gondola's own public documentation page (`gondola.ai/mcp`, accessed 2026-08-20). **No MCP client was installed or connected in this session; no tool schema field-level detail beyond what the documentation page itself displays was inspected; no tool was called.**

| Tool | Domain | Auth | Read-only? | Can book/hold/pay/mutate? | Accepts arbitrary URL/command? | Billable-activity risk | Allowlist? |
|---|---|---|---|---|---|---|---|
| `search_hotels` | Hotel | None | Yes | No | Not disclosed (no schema field list available); no evidence of accepting a caller-supplied URL | Unknown (§4) | **Allow** |
| `get_hotel_details` | Hotel | None | Yes | No | No | Unknown | **Allow** |
| `compare_rates` | Hotel | None | Yes | No | No | Unknown | **Allow** |
| `get_booking_link` | Hotel | None | Yes (returns a link; does not book) | No | Returns a URL as *output*, does not accept one as input per available docs | Unknown | **Allow**, with output-URL host-allowlist validation before ever surfacing to a user |
| `predict_price` | Hotel | None | Yes | No | No | Unknown | **Allow**, output treated as provider guidance only, never trusted arithmetic |
| `get_hotel_stats` | Hotel | None | Yes | No | No | Unknown | **Allow** |
| `get_multi_night_rates` | Hotel | None | Yes | No | No | Unknown | **Allow** |
| `get_similar_hotels` | Hotel | None | Yes | No | No | Unknown | **Allow** |
| `optimize_loyalty_portfolio` | Rewards | None | Yes | No | No | Unknown | **Allow**, output never trusted as kernel arithmetic |
| `search_vehicles` | Vehicle | None | Yes | No | No | Unknown | Out of current project scope (no rental-car domain) — **Deny (scope)** |
| `get_vehicle_details` | Vehicle | None | Yes | No | No | Unknown | **Deny (scope)** |
| `get_vehicle_booking` | Vehicle | None | Read status, but named "booking" — ambiguous | Unclear from name alone | No | Unknown | **Deny (ambiguous name — verify before ever allowing)** |
| `get_vehicle_booking_link` | Vehicle | None | Yes | No | Returns a URL | Unknown | **Deny (scope)** |
| `credit_card_coverage` | Rewards | None | Yes | No | No | Unknown | **Deny (out of scope — this project's own kernel already owns card-coverage logic)** |
| `get_vehicle_booking_coverage` | Vehicle | None | Yes | No | No | Unknown | **Deny (scope)** |
| `get_hotel_reviews` | Hotel | None | Yes | No | No | Unknown | **Allow** |
| `get_suggested_searches` | Hotel | None | Yes | No | No | Unknown | **Allow**, low priority |
| `get_booking` | Hotel/Vehicle | None (per tier list) | Reads an existing booking's status — ambiguous whether this requires the caller to own a booking | No mutation implied by name | No | Unknown | **Deny (ambiguous; do not allow without a concrete schema showing it cannot be used to probe others' bookings)** |
| `diagnose_rates` | Hotel | None | Yes | No | No | Unknown | **Allow**, low priority |
| `get_rate_alerts` | Hotel | Sign-in | Yes | No | No | Unknown | **Deny (requires account this project does not hold)** |
| `get_upcoming_trips` | Account | Sign-in | Yes | No | No | Unknown | **Deny (requires account)** |
| `get_past_trips` | Account | Sign-in | Yes | No | No | Unknown | **Deny (requires account)** |
| `get_loyalty_accounts` | Account | Sign-in | Yes | No | No | Unknown | **Deny (requires account; also PII-adjacent)** |
| `get_free_night_credits` | Account | Sign-in | Yes | No | No | Unknown | **Deny (requires account)** |
| `search_flights` | Flight | Sign-in | Yes | No | No | Unknown | **Deny (requires account — see §5)** |
| `get_travel_profiles` | Account | Sign-in | Yes | No | No | Unknown | **Deny (requires account; PII)** |
| `get_traveler_context` | Account | Sign-in | Yes | No | No | Unknown | **Deny (requires account; PII)** |
| `update_traveler_profile` | Account | Sign-in | **No — explicit mutation** | Profile mutation | No | Unknown | **Deny (mutation)** |
| `create_rate_alert` | Hotel | Sign-in + write scope | No — mutation | No booking, but a standing account mutation | No | Unknown | **Deny (mutation; requires account)** |
| `delete_rate_alert` | Hotel | Sign-in + write scope | No — mutation | Mutation | No | Unknown | **Deny (mutation; requires account)** |
| `book_hotel` | Hotel | `mcp:book` partner scope | **No** | **Yes — "can charge a saved card"** | No | **Yes — explicit charge** | **Deny (booking/payment — absolute, per project rule)** |
| `get_payment_methods` | Account | `mcp:book` partner scope | Reads stored payment methods | Payment-adjacent | No | Sensitive | **Deny (payment data access — absolute)** |
| `book_vehicle` | Vehicle | `mcp:book` partner scope | **No** | **Yes** | No | Yes | **Deny (booking — absolute)** |
| `cancel_vehicle_booking` | Vehicle | `mcp:book` partner scope | **No** | **Yes — mutates/cancels a reservation** | No | Possible | **Deny (mutation — absolute)** |

**Note on schema depth:** the source page (`gondola.ai/mcp`) presents this list as prose/marketing categorization, not raw JSON Schema. Exact required/optional input fields, output field names, and precise error shapes were **not independently verifiable** without connecting a live MCP client — which this preflight explicitly did not do. Any future offline adapter design (§ implementation plan, if commissioned) must treat these as **placeholder-shaped fixtures pending a genuine schema capture**, not as ground truth, and must not claim a fixture matches Gondola's real wire format until independently confirmed by a human with legitimate access.

---

## 10. Proposed static allowlist and denylist

**Proposed allowlist (read-only, hotel-domain-only, no-sign-in tools):**
```
search_hotels
get_hotel_details
compare_rates
get_booking_link      # output URL only; must be host-validated against gondola.ai before use
get_multi_night_rates
get_hotel_reviews
get_hotel_stats
```
`predict_price`, `optimize_loyalty_portfolio`, `get_similar_hotels`, `get_suggested_searches`, and `diagnose_rates` are **not** included in the initial allowlist — they are lower priority for the flight/hotel evidence use case this project needs and each adds surface area (provider-computed guidance, in particular) that should be reviewed individually before inclusion, not bundled in by default.

**Absolute denylist (never allowlisted under any circumstance, regardless of future scope grants):**
```
book_hotel
book_vehicle
cancel_vehicle_booking
get_payment_methods
update_traveler_profile
create_rate_alert
delete_rate_alert
search_flights            # sign-in required; out of scope until resolved
get_rate_alerts
get_upcoming_trips
get_past_trips
get_loyalty_accounts
get_free_night_credits
get_travel_profiles
get_traveler_context
get_booking                # ambiguous scope; deny until schema-confirmed safe
search_vehicles
get_vehicle_details
get_vehicle_booking
get_vehicle_booking_link
get_vehicle_booking_coverage
credit_card_coverage
```

The application must never perform dynamic tool discovery against the live MCP server and must never let an LLM select which tool to call — the allowlist above is a fixed, code-level constant, matching this project's existing pattern for the Tripadvisor adapter's disabled-by-default resolver (`backend/gateway/places/adapters/tripadvisor/`) and this milestone's own explicit instruction.

---

## 11. Security findings

**Static repository review was not possible** — no source code exists to review (§3). The findings below are instead a **remote-endpoint trust and integration-boundary analysis**, appropriate to a closed-source, hosted MCP.

| Finding | Classification | Adapter-boundary mitigation possible? |
|---|---|---|
| No public source code exists to audit for install scripts, postinstall hooks, transitive dependencies, or backdoors. All trust is placed in Gondola's hosted infrastructure with zero code-level visibility. | **Important** | Partially — the adapter cannot mitigate an untrustworthy *server*, but it can (and must) bound the blast radius: strict response-size limits, timeouts, no credential storage on our side, and treating every field as untrusted input (see below). This is the same posture already used for the disabled-by-default Tripadvisor live transport. |
| The MCP endpoint (`https://mcp.gondola.ai/mcp`) is a fixed HTTPS host — no arbitrary-URL construction risk from *our* side, since the endpoint is a hardcoded constant, not derived from user input. | **Informational** | N/A — already safe by construction if implemented as a fixed constant, matching the `fetch.py` pattern established in G2. |
| `get_booking_link` and `get_vehicle_booking_link` return URLs as *output*. If ever surfaced to a user or followed programmatically, an unvalidated output URL is an SSRF/open-redirect-adjacent risk if Gondola's own link-generation were ever compromised or manipulated. | **Important** | Yes — validate the returned URL's host against an allowlist (`gondola.ai` and known partner-booking domains) before display or any server-side follow; never let the application fetch an arbitrary URL returned by the tool. |
| Free-text fields (hotel names, reviews, descriptions) returned by `get_hotel_reviews`, `get_hotel_details`, etc. are a **prompt-injection vector** if ever passed into an LLM context (e.g., the itinerary planner or explainer). | **Important** | Yes — sanitize/strip any instruction-like content from provider free-text fields before it reaches any LLM call site, and never let provider text alter tool selection or money computation, consistent with this project's existing prompt-hardening posture (P1 milestone). |
| `book_hotel` can "charge a saved card" per Gondola's own documentation. This is an absolute Tier-F violation risk (this project must never execute a financial transaction) if this tool were ever accidentally reachable. | **Critical if reachable; mitigated to Informational if never allowlisted** | Yes, fully — the tool requires `mcp:book` partner scope this project will never hold, AND the static allowlist in §10 excludes it entirely. Both the platform-level scope gate and the application-level allowlist independently prevent invocation. Documented here so a future maintainer understands *why* it is safe, not merely *that* it is excluded. |
| No documented rate limit means the adapter cannot rely on the provider to bound call volume; a bug in our own orchestration (e.g., a retry loop) could generate unbounded call volume against Gondola's infrastructure. | **Important** | Yes — the adapter itself must enforce a hard per-plan call ceiling, bounded retries, and a circuit breaker, exactly as this project's existing `PlanBudget`/`BudgetLedger` (`backend/gateway/evidence/budget.py`) already does for other domains. |
| No documented input/response size limits from Gondola's side. | **Minor** | Yes — the adapter enforces its own response-size ceiling (matching the 512KB pattern already used for Tripadvisor) and rejects oversized responses rather than attempting to parse them. |
| No documented error-response shape; error handling behavior under malformed/rate-limited/timeout conditions is unverified. | **Minor** | Yes — the adapter must fail closed (typed `provider_unavailable`/`timeout`/`invalid_response` errors) on any unexpected shape, never guess. |
| TLS certificate mismatch was observed when this preflight attempted to fetch `help.gondola.ai` (a subdomain, not the MCP endpoint itself) during research. | **Informational** | Recorded for completeness; this was on a documentation subdomain, not the MCP transport host, and may be a transient CDN/Fastly configuration issue rather than a persistent flaw. Not weighted into the overall decision, but worth a spot-check before any future live work begins. |

**No Critical, unmitigated finding exists that cannot be closed by an adapter-boundary control** — the one theoretically Critical item (`book_hotel`'s charge capability) is fully closed by the combination of Gondola's own partner-scope gate and this project's own static allowlist. This means the *security* dimension alone does not force decision C — it is the **terms ambiguity (§6)** and **coverage/cost unknowns (§§4, 8)** that keep this preflight at decision B rather than A.

---

## 12. Spec-16 §7 student-profile activation checklist

| # | Item | Status | Basis |
|---|---|---|---|
| 1 | Owner and fixed endpoint | **PASS** | Gondola AI Inc.; `https://mcp.gondola.ai/mcp` (§3) |
| 2 | Source method | **PASS** | `provider_mcp` — official, first-party, maintainer-hosted (§3) |
| 3 | Non-commercial use and current terms | **CONDITIONAL** | Personal/non-commercial use is explicitly permitted, but the same terms' anti-automation clause is in unresolved, undocumented tension with the MCP product itself (§6) |
| 4 | Anonymous vs. credentialed access | **CONDITIONAL** | Anonymous for the 19 hotel/reference tools (PASS-equivalent); the domain most relevant to this project's corridor (`search_flights`) requires sign-in this project does not plan to obtain (FAIL-equivalent for that specific domain) (§5) |
| 5 | Live/sandbox semantics and geography | **CONDITIONAL/UNKNOWN** | Marketed as live; independent evidence of staleness and geographic-relevance bugs exists; no documented coverage for this project's actual corridor (§§7–8) |
| 6 | Read-only endpoint/tool restriction | **PASS** (achievable) | A strict static allowlist excluding all booking/mutation/account tools is fully specifiable and enforceable (§§9–10) |
| 7 | Access-control/robots behavior | **CONDITIONAL** | Not scraping-based (this is an official MCP, not a page crawler), but the general ToS's automation clause has not been confirmed inapplicable to MCP use (§6) |
| 8 | Data sent, attribution, cache/retention | **UNKNOWN** | No attribution requirement found; no explicit cache/retention permission or prohibition for search results found; ToS's data-retention clause addresses Gondola's rights over *our* submitted data, not our rights over *retrieved* results (§6) |
| 9 | Call/latency/zero-spend ceilings | **UNKNOWN** | No rate limit, quota, or programmatic pricing policy published anywhere found (§4) |
| 10 | Failure fixture and `SampleAdapter` fallback design | **PASS** (design-only, not yet built) | Fully within this project's own control; the existing `SampleAdapter` (G1) and its established fixture-replay pattern (`backend/gateway/travel/fixtures/`) are directly reusable as the fallback design template (§16 of this report; not yet implemented) |

**Per this milestone's own rule** ("a live activation recommendation requires no unresolved FAIL and no cost/permission UNKNOWN"): items 8 and 9 are UNKNOWN, and item 4 is FAIL-equivalent for the flight domain. **This checklist result alone is sufficient to rule out decision A.**

---

## 13. Cache, retention and attribution requirements (as currently understood — incomplete)

- **Attribution:** No requirement found anywhere in Gondola's public documentation. This is unusual for a travel-data provider (compare to Tripadvisor's mandatory attribution, already implemented in this codebase) and should be re-confirmed directly with Gondola before assuming none is required — absence of a found requirement is not proof none exists.
- **Cache/retention of search results:** No explicit permission or prohibition found. Given the ToS's general restrictiveness (no redistribution, personal/non-commercial only), the conservative default this project would apply — consistent with how `SampleAdapter` and the Tripadvisor adapter already treat evidence — is: **ephemeral quote-cache only, never promoted to an approved KB fact, with a short TTL and no long-term raw-response retention**, pending explicit confirmation.
- **Raw response retention:** No stated policy. Conservative default: **do not retain raw Gondola responses beyond the request lifecycle**; only normalized, minimal fields needed for the kernel's cost estimate would be retained, and even that only ephemerally.
- **Normalized-result retention:** Same conservative default as above.

---

## 14. Proposed call/time/result ceilings (design-only, not yet implemented)

If a future offline-then-live adapter is built (per the conditional plan, §"Conditional implementation plan" below), the following are proposed *starting* ceilings — deliberately conservative, matching this project's existing `PlanBudget` pattern:

- Max 2 Gondola calls per plan (mirroring the existing `request_budget.calls_per_plan` pattern already used in the places/travel gateway registries).
- Max 1 concurrent call (no fan-out) until real latency/reliability is observed.
- Timeout: 10s connect / 20s total, matching the conservative end of this project's existing adapter timeout conventions.
- Zero retries on 4xx; at most one bounded retry with jitter on a transient 5xx, matching spec 16 §13's retry matrix.
- Hard monthly/lifetime call ceiling enforced by a persistent ledger (mirroring `TripadvisorEntityLedger`'s pattern), since Gondola publishes no ceiling of its own.
- `max_cost_minor = 0` — this project's `PlanBudget` already defaults to zero-cost, and Gondola would inherit that default unmodified, since no paid tier is being activated.

---

## 15. Kill-switch design (design-only, not yet implemented)

Matching the existing pattern already proven for Tripadvisor (`backend/gateway/places/adapters/tripadvisor/`, a disabled-by-default live transport gated by an explicit resolver dependency with no default adapter map):

- The live Gondola transport would be **disabled by default** in the travel provider registry (`backend/gateway/travel/registry.py`'s pattern), with `enabled=False` until a human explicitly flips it after this preflight's open questions are resolved.
- A single environment-level flag (never a default) would gate activation, checked at registry-construction time, not at call time — so a compromised or buggy runtime code path cannot self-activate it.
- The `SampleAdapter` remains registered at all times as the always-available fallback with lower priority ordering, per spec 16 §13's existing rule that "`SampleAdapter` is never circuit-broken."
- A circuit breaker (per-adapter, not global) would trip after N consecutive failures within a window and fall back to `SampleAdapter` automatically for the remainder of that plan run.

---

## 16. `SampleAdapter` fallback expectations

No new fallback mechanism is required — the existing G1 `SampleAdapter` (`backend/gateway/travel/adapters/sample.py`) already satisfies spec 16 §13's requirement that it "drives all Phase G end-to-end tests" and "is never circuit-broken." Any future Gondola adapter would be strictly additive to the existing registry (`backend/gateway/travel/registry.py`), selected only when explicitly enabled and only after `SampleAdapter` and any higher-priority enabled adapter have been considered per the registry's existing deterministic selection order (spec 16 §15). No change to `SampleAdapter` itself is anticipated or proposed.

---

## 17. Unknowns and human decisions required

1. **Does Gondola's anti-automation ToS clause apply to its own officially-published MCP?** This requires a direct, written answer from Gondola (e.g., via `concierge@gondola.ai`, the support address surfaced during research), not an inference. Until answered, live activation cannot proceed regardless of other findings.
2. **Does Gondola's hotel/flight search meaningfully cover India, UAE, Singapore, Europe, or the UK?** No first-party coverage statement was found; independent evidence (US-only flight-carrier examples, a documented non-US geo-relevance bug) suggests the current product may be US-centric. This requires either a direct question to Gondola support or a human manually testing 1–2 read-only searches on the consumer website (not the MCP, and not by this preflight) for the actual corridor before committing engineering time.
3. **What are Gondola's real rate limits / fair-use thresholds for MCP callers?** Not documented; requires a direct question to Gondola, since guessing and then hitting an undocumented limit risks account/IP blocking with no advance warning.
4. **What does a real `search_hotels`/`get_hotel_details` response actually look like** (field names, completeness, provider quote ID, expiry)? Not verifiable without a live call, which this preflight explicitly did not make. A human would need to authorize exactly one manual, bounded, read-only test call (outside CI, per this project's own G3.5 pattern already used for the Tripadvisor and LLM live-smoke precedents) to capture a sanitized fixture — and only after items 1–2 above are resolved, since making that call before resolving the automation-clause question would itself be premature.
5. **Attribution requirement** — not found; needs direct confirmation rather than an assumption of "none."
6. **Whether `get_booking`/`get_vehicle_booking` could be used to probe another user's booking by ID** — the tool names are ambiguous from documentation alone; this must be resolved by inspecting a real schema (item 4) before ever considering allowlisting them, which is why §10 denies them by default.

---

## 18. Direct source links with access dates

All accessed 2026-08-20 unless a different date is shown from the source itself:

1. [Gondola MCP — Hotel Search for AI Agents](https://www.gondola.ai/mcp) — Gondola AI Inc.
2. [Gondola Terms of Service](https://www.gondola.ai/terms-of-service) — Gondola AI Inc., "Date of Last Revision: January 30, 2024"
3. [Build your own client with the Gondola MCP](https://www.gondola.ai/help/mcp-oauth-integration) — Gondola AI Inc., "Last updated June 20, 2026"
4. [About - The Hotel Booking Tool for Frequent Travelers](https://www.gondola.ai/about) — Gondola AI Inc.
5. [The Best Travel MCP Server for AI Agents](https://www.gondola.ai/blog/best-travel-mcp-server) — Gondola AI Inc., July 19, 2026
6. [Search Every Hotel Suite in the World](https://www.gondola.ai/suites) — Gondola AI Inc.
7. [Gondola: My go-to hotel award search tool now automatically reprices some flights](https://frequentmiler.com/gondola/) — Frequent Miler, updated July 24, 2026
8. [New Tool for Booking Hotels, Gondola, Is Available to the Public](https://upgradedpoints.com/news/gondola-hotel-booking-tool/) — Upgraded Points, July 21, 2025
9. `https://help.gondola.ai/en/articles/9652929` — Gondola AI Inc. help center; **attempted fetch failed with a TLS certificate hostname mismatch** at access time (2026-08-20); recorded in §11 as an informational finding, content not retrievable and therefore not otherwise cited.

---

## 19. Final decision

**B — Eligible only for offline fixture-backed adapter development.**

Gondola is a legitimate, VC-backed, first-party company offering a real, currently-live, officially-documented MCP with genuinely anonymous, genuinely free (as far as documented) read-only hotel search. That contract shape is worth building against offline now, using synthetic/conservative fixtures pending a real schema capture. It is **not** eligible for live activation today because: (1) its own general Terms of Service contain an unresolved, unaddressed contradiction with the existence of its MCP product; (2) the project's primary corridor need (flights) sits behind a sign-in wall this project has no plan to cross, with independent evidence suggesting flight coverage may be US-centric; (3) geographic coverage for India/UAE/Singapore/Europe/UK is undocumented and one independent report actively demonstrates a non-US relevance failure; and (4) no rate-limit or programmatic-cost ceiling is published, so zero-spend cannot be mechanically proven. None of these four issues can be resolved by better engineering — each requires either a direct answer from Gondola or a human manually verifying the consumer product, which is why this preflight stops here rather than proceeding to design a live-activation path.

## 20. Explicit confirmation

No live search was performed. No MCP client was installed, connected, or configured. No credential, account, API key, or OAuth token was created or used. No provider quota was consumed. No paid service was enabled or configured. No runtime code, configuration, or environment flag in this repository was modified, added, or activated. No booking, hold, payment, or transfer tool was invoked or tested. All findings above were obtained via public, unauthenticated web reads of Gondola's own published documentation and independent third-party commentary.
