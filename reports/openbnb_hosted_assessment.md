# OpenBnB hosted MCP — decision packet

**Status:** documentation-only assessment. No sign-up, sign-in, OAuth, terms acceptance, credential,
credit, `tools/list` or tool call was made. No TripWise activation guard or provider code changed.
This is not a legal opinion and not an activation approval.

**Accessed:** 2026-11-06 (US Pacific) / 2026-11-07 UTC. Pages were read with ordinary HTTPS GETs.
**Base:** `origin/main` @ `21f959a`.

## Recommendation

**Written embedding permission needed.**

- OpenBnB's published terms license the hosted service for *personal, non-commercial use or
  internal business purpose* and forbid redistributing the service **or data obtained through it**
  "as a product or service of your own without our written permission" (Terms §2, §6). Showing
  rental results to other TripWise users and storing them in their saved trips is not clearly
  covered by either personal use or internal business use. TripWise being a noncommercial student
  project does not appear anywhere in the terms as an exemption.
- Cost and access are **not** the blocker: the free USD 2 credit covers a bounded evaluation, no
  card is required, and nothing is charged automatically (details and one caveat below).
- OpenBnB permission alone would not settle the underlying-listing-data question (§5). That is a
  separate, still-open human decision.

A bounded *personal* evaluation by the developer only — results seen only by that person, nothing
shown to other users — reads as within OpenBnB's personal-use licence, but it still requires the
human to create an account and accept the terms, and it does not authorize any TripWise product
display. I do not recommend running it before OpenBnB answers, because its only product value is
proving the search→detail→TripWise path, which is exactly the use the reply must permit.

## 1. Three things that must not be conflated

| Item | Operator / licence | What it is | Bearing on TripWise |
|---|---|---|---|
| Local GitHub server `openbnb-org/mcp-server-airbnb` | MIT, npm `@openbnb/mcp-server-airbnb` 0.3.0; latest commit `d5a8f18`, 2026-08-06 | Self-run Node server that fetches airbnb.com pages; tools `airbnb_search`, `airbnb_listing_details`; robots.txt honoured by default with documented overrides (`--ignore-robots-txt`, `ignoreRobotsText`) | The code licence (MIT) covers the software only. It is what `reports/g3b_openbnb_offline.md` assessed. |
| Hosted service `https://mcp.openbnb.ai/mcp` | Altmatter LLC (Washington, US), own Terms + Privacy (both "Last updated October 17, 2026") | Separately operated, paid-per-call MCP service. The GitHub README calls it "a separate, fully-hosted alternative" with richer filters and MCP UI | Governed by Altmatter's terms, not MIT. Tool names and schemas are **not** assumed to equal the local server's. |
| Permission to use OpenBnB | Altmatter terms | Licence to access the service and its Content | Answerable by contact@openbnb.org. |
| Rights in the underlying listing data | Airbnb / hosts | Listing text, photos, prices originate from Airbnb | Not answered by OpenBnB's terms (§5). |

G3b's local-scraper findings (fail-open robots check, child-process egress to Photon/Nominatim,
etc.) describe the local server. They are **not** evidence about how the hosted service fetches
data, and are not repeated here as hosted facts.

## 2. Verified facts (primary sources)

### 2.1 Hosted tools and fields
Source: [openbnb.ai/pricing](https://openbnb.ai/pricing), [openbnb.ai](https://openbnb.ai/).

| Tool (as named on pricing page) | Stated purpose | Price |
|---|---|---|
| `airbnb_search` | Search Airbnb listings | 2¢ |
| `airbnb_listing` | Full details for one listing | 2¢ |
| `maps_geocode`, `maps_reverse_geocode` | Address ↔ coordinates | 1¢ |
| `maps_directions` | Directions between two places | 1¢ |
| `maps_elevation` | Elevation | 1¢ |
| `maps_place_details` | Hours, phone, reviews for a place | 3¢ |
| `maps_search_places` | Places near a listing | 4¢ |
| `maps_distance_matrix` | Listing→place distances | 1¢ per pair, max 25 pairs |
| `account_balance` | Balance, prices, top-up link | Free |

- Marketing text says search filters cover "place, dates, budget, beds, amenities, and type" and
  listing details include "Amenities, house rules, and exact prices for your dates."
- **No public request/response schema was found.** Argument names, price scope (nightly vs stay
  total, taxes/fees), currency, links, identifiers and timestamps are undocumented publicly.
- Note: hosted `airbnb_listing` ≠ local `airbnb_listing_details`. TripWise's existing offline
  adapter (stdio, local tool names) cannot be pointed at the hosted service as-is.
- Privacy policy: maps queries go to Google Maps Platform; Airbnb searches/listing lookups
  "to Airbnb, to retrieve publicly available listing information"; name/email/account details are
  not sent to Google or Airbnb.

### 2.2 Authentication and developer integration
Sources: [openbnb.ai/connect](https://openbnb.ai/connect), unauthenticated GETs to
`https://mcp.openbnb.ai/mcp` and `https://mcp.openbnb.ai/.well-known/oauth-authorization-server`,
Terms §3–§4, Privacy §1.

- `GET /mcp` without a token → `401`, `WWW-Authenticate: Bearer realm="OAuth", error="invalid_token"`.
  This is normal for an OAuth-protected MCP endpoint, not evidence that it is broken.
- Published OAuth metadata: issuer `https://mcp.openbnb.ai`; `/authorize`, `/token`, `/register`
  (dynamic client registration); grants `authorization_code`, `refresh_token`; PKCE `S256`
  (and `plain`); token endpoint auth includes `none` (public clients). `/.well-known/oauth-protected-resource`
  returned 404.
- Account sign-in: Google or emailed link/code. No API-key flow is documented.
- Connect page: ChatGPT, Claude, OpenClaw; "Using another MCP client? Paste the URL above."
  No developer docs, SDK, or third-party-application integration guide were found
  (`/docs` → 404).
- Terms §3(6) expressly permits "authenticated programmatic access to our MCP server endpoints
  using your own credentials".
- **Tool discovery is not public.** `/mcp` requires a bearer token, so `tools/list` needs a
  separately approved sign-in. It was not attempted.

### 2.3 Pricing, credit and charging
Sources: [openbnb.ai/pricing](https://openbnb.ai/pricing), Terms §5.

- USD 2 free credit on new accounts, "No card needed"; "may limit Free Credit to one grant per
  person"; no cash value; never refunded.
- Only successful tool calls are charged; failed calls and balance checks are free.
- Warning below USD 0.50; at USD 0 tool calls (other than balance) pause and a top-up link is shown.
- "We never charge your payment method automatically." Top-ups are voluntary, ≥ USD 5, card via
  Stripe, taxes may apply, non-refundable.
- **Negative balance:** "Calls already in progress when your balance runs out may take it slightly
  below zero, and that amount is deducted from your next top-up."
- Credit may later be given an expiry, and prices may change, with advance notice.
- Rate/usage limits may be imposed; none are published.

Against TripWise's USD 0 rule ("eligible only when overage is mechanically impossible"): with no
card on file, no out-of-pocket charge can occur without a human choosing to top up. A small
negative balance can still accrue and would be owed from any future top-up. Whether that satisfies
the rule is a human call; TripWise can additionally stop itself well above zero (checking the free
`account_balance` before each paid call and enforcing its own small call ceiling).

A search plus one detail lookup costs 4¢; USD 2 ≈ 100 paid calls.

### 2.4 Personal use versus embedding in TripWise
Source: [openbnb.ai/terms](https://openbnb.ai/terms) §2, §6.

- §2: Content and Marks provided "for your personal, non-commercial use or internal business
  purpose only"; no Content may be "copied, reproduced, aggregated, republished, … publicly
  displayed, … distributed … for any commercial purpose whatsoever, without our express prior
  written permission." Other uses: "please address your request to: contact@openbnb.org."
- §6: personal and internal-business use is allowed, "such as researching comparable listings,
  studying markets, or advising your own clients, including sharing results with those clients.
  You may not resell, sublicense, or redistribute the Services, or data obtained through them, as
  a product or service of your own without our written permission."
- §6 also forbids systematically compiling a collection/database made available to others, using
  the service to build a competing service, and AI training without consent.

Reading: the "commercial purpose" qualifier in §2 does not appear in the §6 redistribution clause.
TripWise displaying results to its users is plausibly "a product or service of your own". The
terms do not address noncommercial student projects. Hence written permission.

### 2.5 Display, attribution, retention, caching, deletion
- **Attribution/display:** no attribution or branding requirement is published. Site footer:
  "OpenBnB is not affiliated with, associated with, or endorsed by Airbnb, Vrbo, Booking.com, or any
  other booking platform." §6 forbids removing proprietary notices from Content.
- **Caching / saved-trip retention / expiry of results:** not addressed in the terms or pricing.
- **Redistribution:** see §2.4.
- **Deletion:** applies to OpenBnB's own records about the account holder. OpenBnB logs each tool
  call (location, dates, guests, filters, listings looked up, results returned, time, cost) and keeps
  tool-call records "for as long as we need them to operate, secure, and improve the Services";
  account termination requests go to contact@openbnb.org, with some retention for fraud/legal/tax.
  Nothing is said about deletion obligations for data a client application stores.

### 2.6 Underlying data — what public documents do and do not say
- OpenBnB states it uses "publicly available data", is not affiliated with or endorsed by Airbnb,
  and (privacy policy) sends searches "to Airbnb, to retrieve publicly available listing
  information." It does not publicly state the retrieval method or any licence from Airbnb.
- Terms §9: users are responsible for third-party terms and authorizations when connecting third
  parties, and "must not use the Services to process content you do not have the right to process."
- [Airbnb Terms of Service](https://www.airbnb.com/help/article/2908) (Last Updated February 5,
  2026, non-EEA/UK/AU version): "Do not use bots, crawlers, scrapers, or other automated means to
  access or collect data or other content from or otherwise interact with the Airbnb Platform."
- **No published OpenBnB–Airbnb agreement was found.** That absence does not prove none exists, and
  "not affiliated/endorsed" does not by itself settle licensing. It means TripWise has no public
  basis today for its own right to display or retain Airbnb-originated listing content.

### 2.7 Users connecting their own OpenBnB accounts
- The terms permit programmatic access "using your own credentials" and make each account holder
  responsible for their credentials and downstream use. They do not say whether a third-party
  application may act as the OAuth client for many users, display results in its own interface, or
  store them.
- Per-user accounts would move cost to each user (and the free grant is per person) but would not,
  on the published text, convert TripWise's display/retention into personal use. This is treated as
  **unconfirmed**, not as a workaround.

## 3. Confirmed versus assumed

| Topic | Confirmed (published) | Assumed / unknown |
|---|---|---|
| Endpoint & auth | OAuth 2 + DCR + PKCE; bearer required for `/mcp` | Scopes, token lifetimes, whether `tools/list` is free |
| Tools | Names and prices above | Arguments, response fields, price scope, currency, IDs, links |
| Cost | $2 free, no card, no auto-charge, pause at $0, small negative possible | Rate limits; credit expiry date |
| Personal use | Allowed | — |
| Embedding/display to other users | Not granted; written permission route stated | Whether OpenBnB will grant it for a noncommercial prototype |
| Attribution, caching, retention, expiry | Not specified | OpenBnB's requirements |
| Underlying data rights | OpenBnB claims public data; Airbnb ToS forbids automated collection | Any arrangement with Airbnb; TripWise's right to display/retain |
| User-owned accounts | Own-credential access allowed | Third-party app acting for users |

## 4. Unresolved questions (external)
1. Is TripWise's intended use (below) permitted, and in what form (email, partner terms, licence)?
2. Required attribution/branding text and links.
3. Maximum retention for quoted prices and listing references in a private saved trip; expiry
   semantics for prices.
4. Whether a third-party app may be the OAuth client for its users.
5. Whether OpenBnB holds or relies on any arrangement covering Airbnb-originated data that extends
   to downstream display, and what obligations pass to TripWise.
6. Published request/response schema; price scope (nightly vs total, taxes/fees) and currency.
7. Rate limits; whether `tools/list`/`initialize` is billed.

Separate human decision (not OpenBnB's to make): whether TripWise displays Airbnb-originated
listing data at all given Airbnb's published terms, even with OpenBnB's permission.

## 5. Ready-to-send request (NOT SENT — requires explicit user authorization)

> **To:** contact@openbnb.org
> **Subject:** Permission request — noncommercial student prototype using the OpenBnB hosted MCP
>
> Hello,
>
> I am a student building TripWise, a noncommercial portfolio prototype that plans a trip and
> works out how to pay for it with the traveler's own credit cards and points. It has no revenue,
> advertising, affiliate links or paid users, and is used by me, evaluators and a small number of
> demo users. I understand your Terms (§2, §6) license personal and internal-business use and
> require written permission to redistribute the Services or data obtained through them as part of
> another product, so I am asking before connecting.
>
> Intended use:
> - An authenticated MCP integration with https://mcp.openbnb.ai/mcp (OAuth, my own account),
>   calling only `airbnb_search` and `airbnb_listing` (plus the free `account_balance`).
> - A traveler's trip request triggers at most a couple of calls; a small number of rental results
>   (roughly 3–5) are shown to that signed-in user alongside hotels, clearly labelled as
>   "verify before booking" with a link to the listing.
> - If the user saves the trip, we store privately, for that user only: listing identifier/link,
>   title, quoted price and currency, dates/guests, and the retrieval time. Nothing is public.
> - No bulk or systematic catalogue replication, no database offered to others, no AI training,
>   no booking, and no resale.
>
> Questions:
> 1. Is this use permitted? If so, what form of permission or partner arrangement is required?
> 2. What attribution or display requirements apply (to OpenBnB and to the listing source)?
> 3. How long may quoted prices and listing references be retained in a private saved trip, and
>    should they be treated as expiring after a set time?
> 4. May an application act as the OAuth client on behalf of its users with their own OpenBnB
>    accounts, or should all calls run under one developer account?
> 5. Do any terms from the underlying listing source pass through to applications displaying your
>    results, and is there anything we must or must not do as a result?
> 6. Is there a published request/response schema for these tools (including whether prices are
>    nightly or stay totals, and tax/fee coverage), and are there rate limits?
>
> I am happy to share more detail or adjust the scope. Thank you.
>
> [Name], [university/programme], [contact]

Fill the bracketed fields truthfully before sending. Do not describe the project as exempt because
of student status.

## 6. Proposed bounded demonstration (future, requires approval)

Preconditions, all explicit and recorded: (a) written OpenBnB reply permitting the use, or a human
decision to run a developer-only personal evaluation; (b) human decision on the underlying-data
question (§4, last item); (c) human creates the account, accepts terms, completes OAuth; no card
added; (d) a reviewed hosted-adapter change replacing the stdio transport (separate task — the
existing `LiveActivationApproval` guard stays in force until then).

Run (one session, no retries):
1. `initialize` + `tools/list` — record exact hosted tool names and input schemas.
2. `account_balance` (free) — record starting balance.
3. One `airbnb_search`: Singapore, exact check-in/out dates of the demo trip, 2 adults, ≤ 28 nights. Retain the response privately outside Git, hash recorded.
4. One `airbnb_listing` for one returned listing.
5. `account_balance` — confirm a 4¢ deduction and no negative balance.
6. Normalize only observed fields into `HotelQuote` (`status="verify_required"`, no invented
   coordinates/taxes; nightly-only prices never become totals), run through `TravelInventoryService`
   with `SampleAdapter` fallback into a plan, save the trip, reopen SQLite, read the revision.

Ceilings: ≤ 2 paid calls (≤ 4¢ of free credit), zero top-ups. Success = real fields carried
end-to-end with provenance; any schema mismatch is recorded, not patched with invented fixtures.

## 7. Sources
- https://openbnb.ai/ · https://openbnb.ai/connect · https://openbnb.ai/pricing
- https://openbnb.ai/terms (Terms of Service, last updated October 17, 2026)
- https://openbnb.ai/privacy (Privacy Policy, last updated October 17, 2026)
- https://mcp.openbnb.ai/mcp (unauthenticated GET → 401 Bearer) ·
  https://mcp.openbnb.ai/.well-known/oauth-authorization-server
- https://github.com/openbnb-org/mcp-server-airbnb (README, package.json 0.3.0, MIT)
- https://www.openbnb.org/ (browser-extension site, same Altmatter footer)
- https://www.airbnb.com/help/article/2908 (Airbnb Terms of Service, Last Updated February 5, 2026)
- Internal: `reports/g3b_openbnb_offline.md`, `docs/specs/16_data_gateway_and_adapters.md` §7
