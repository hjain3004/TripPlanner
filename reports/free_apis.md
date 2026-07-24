# Free Travel, Flight, Hotel & Rewards Data Sources for a Zero-Budget Student MVP (2026)

## Update — 2026-07-24: student profile + `Beat the Booking Sites`

The human confirmed this is a **non-commercial student/portfolio project**. Commercial-production licensing, SLAs, and scale are not current acceptance criteria. Free, personal-use, and experimental read-only sources are therefore valid prototype candidates when their limitations are visible and the application has recorded/sample fallbacks. If the project is ever monetized, every provider must be re-reviewed and replaced or licensed as necessary.

The newly supplied `Beat_the_Booking_Sites.pdf` identifies two immediately relevant hosted MCPs:

- **Gondola MCP — preferred first live spike.** Its current official page advertises anonymous/free read-only search, structured responses, hotel cash and points rates, flexible multi-night rates, direct links, cash flights, reviews, price context, and optional OAuth account tools. Use only raw normalized price/points evidence; our deterministic kernel recomputes cents-per-point, card rewards, transfer value, and effective cost. Initial adapter excludes all booking/payment tools. The public developer guide supports custom MCP clients with OAuth 2.1/PKCE, while the general terms still contain personal/non-commercial wording; that is acceptable for this active student profile but would require written clarification before commercialization. Sources: [MCP capabilities](https://www.gondola.ai/mcp), [client integration](https://www.gondola.ai/help/mcp-oauth-integration), [terms](https://www.gondola.ai/terms-of-service).
- **OpenBnB hosted MCP — experimental rental source.** The service advertises a free hosted endpoint for rental search. Its terms permit personal/non-commercial/internal use but reserve the right to change or discontinue the free tier. The related open-source implementation accesses Airbnb listing/search content, so this remains local/demo-only, low-volume, feature-flagged, `verify_required`, and non-persistent by default. Never enable robots overrides or circumvent a block. Sources: [service](https://openbnb.ai/), [terms](https://openbnb.ai/terms), [open-source implementation](https://github.com/openbnb-org/mcp-server-airbnb), [Airbnb terms](https://www.airbnb.com/help/article/2857).

Full workflow and architecture assessment: `reports/beat_the_booking_sites_assessment.md`.

Canonical flight-source decision: `reports/flight_data_strategy.md`. In short: Gondola for current cash-flight quotes; optional Travelpayouts for cached date trends; Duffel test mode for structured fixtures only; recorded/manual award evidence until a free/personal award adapter exists. Google Flights is verification/deep-link only, not a fare API.

This update supersedes older conclusions below where they imply that commercial-production entitlement is required for the student prototype or where they omit Gondola. It does **not** change the permanent no-circumvention, provenance, deterministic-math, or no-autonomous-booking rules.

## TL;DR
- **The "no live site" claim is only half true.** Several strong providers offer genuine, instant, self-serve, personal-email signup with no business verification, no company registration, and no revenue test — notably **Duffel** (sandbox flights), **Tripadvisor Content API** (POI/hotel content; 5,000 free calls/mo but a credit card is required at signup), **Frankfurter** (FX, no key at all), **Foursquare/OpenStreetMap** (POIs), and open datasets (**OpenFlights, OurAirports**). Where the "no site" warning IS correct: real live-fare/inventory affiliate APIs (Travelpayouts Aviasales Search API, Booking.com Demand API, Expedia Rapid, Skyscanner official) all gate access behind approved sites, traffic thresholds, or partner review.
- **A critical 2026 event changes the default advice:** the **Amadeus for Developers Self-Service portal is being decommissioned on July 17, 2026, and new registrations are already paused** — so do NOT build the MVP on Amadeus. Gondola is now the preferred live-demo cash-flight spike; Duffel remains the primary free structured sandbox source and never represents live consumer fares.
- **Comprehensive credit-card reward rules and live award-seat availability essentially do not exist in free, structured, reusable form** — keep hand-curating those. Free FX, airport/route reference data, and POI/destination content CAN and should replace hand-curated data now; live flight/hotel *prices* cannot be obtained free and legitimately at scale.

## Key Findings

### 1. The "student / no live site" reality, provider by provider
The other AI was partially right. The distinction that matters is **developer/test access** (build-and-test data) vs **live affiliate/inventory access** (real consumer prices you could monetize).

- **Instant self-serve, personal email, no site, no business check:** Duffel (test mode), Tripadvisor Content API (needs credit card, not a business), AviationStack (real-time flight *status*, not fares), RapidAPI marketplace flight APIs (Sky-Scrapper etc.), Foursquare, Frankfurter/exchangerate APIs, seats.aero Pro API (needs $9.99/mo Pro, but personal/non-commercial, no business).
- **Gated behind an approved site / traffic / partner review:** Travelpayouts Aviasales flight Search API (requires MAU ≥ 50,000), Booking.com Demand API (Managed Affiliate Partner approval), Expedia Rapid (targets businesses with booking volume), Skyscanner official partner program (commercial agreement, weeks-long review), Hotelbeds APItude (certification process before live keys), Kiwi Tequila (now invitation-only, closed to new self-serve developers).

**Verdict:** A GitHub Pages/Vercel demo is generally NOT enough to pass the live-affiliate gates (they want real traffic/booking intent). But it is completely unnecessary for the test/sandbox and open-data sources — which is where a pre-launch MVP should live.

### 2. Flight data

**Amadeus Self-Service (do not adopt).** Historically the best free-tier option: instant self-serve signup, free monthly quota in test AND production (production only bills above the free quota, roughly $0.003–$0.046/call over quota). Test environment returns a static, cached subset of real production data (10 TPS cap) — good enough to prototype. **BUT** Amadeus is shutting the whole thing down. Per PhocusWire, an Amadeus spokesperson confirmed: *"We are decommissioning only the self‑service section of the Amadeus for Developers portal,"* with the letter to developers stating registration for new users is paused and *"the portal will be fully decommissioned for existing users on July 17. As of that date, API keys will be disabled, and the self-service portal will be inaccessible."* (Only the paid Enterprise portal, via a sales contract, survives.) New students likely cannot even register now, and anything built on it dies July 17, 2026. **Skip it.**

**Duffel (recommended structured sandbox/test source).** Instant signup at app.duffel.com with name/email/password → immediate sandbox access. Test tokens (`duffel_test_`) work with no verification, no credit card, no business. Test mode talks to airlines' sandbox environments; for reliable results Duffel provides its own "Duffel Airways" test airline (search LHR→JFK, one adult). Test schedules/prices are not realistic, so use this only for contract/error fixtures. Live mode requires account activation and is not part of the zero-budget plan.

**Kiwi.com Tequila (closed).** No longer an open self-service program for new developers; existing partners only, new partnerships invitation-only. Treat public Tequila examples as legacy. Do not plan around it.

**Skyscanner.** Official Travel APIs are partner-only (business review + commercial agreement, weeks). The practical independent-developer route is the **Sky-Scrapper API by apiheya on RapidAPI** (unofficial), free tier ~100 requests/month, returning Skyscanner-style flight/hotel/car data. This is a third-party scraper wrapper — data-rights and freshness are uncertain, and it is legally grey for anything beyond prototyping.

**Travelpayouts / Aviasales.** The affiliate *network* is 100% free to join with no fees and instant access to affiliate tools. Two very different APIs:
- **Flight Data API / Travelpayouts Data API** (price trends, popular destinations, cheapest cached prices): accessible once registered in the affiliate network, token from your account. Data is served **from cache** (Travelpayouts explicitly recommends using it to generate static pages) — NOT guaranteed-live but a legitimate, free, cached-price source. This is the most realistic free "real-ish price" source for an Indian resident with just an affiliate signup.
- **Aviasales Flight Search API** (real-time metasearch): heavily gated — requires MAU ≥ 50,000, a Book button on every result, server-side requests, conversion thresholds (≥9% search-to-Book, ≥5% Book-to-purchase), and manual approval. Not attainable pre-launch.

**RapidAPI marketplace flight APIs.** Sky-Scrapper (~100 req/mo free), DataCrawler Google Flights (~150 req/mo free BASIC), "Flight Data", Priceline/Tripadvisor endpoints — free tiers exist but are small, unofficial scrapers with uncertain ToS/freshness. Fine for a handful of prototype pulls; not a production base.

**Flight status / tracking (NOT fares):** AviationStack free plan = 100 requests/month (the project's GitHub page cites a 500/mo free tier — figures vary by source), returning real-time flight *status* data, no credit card. AeroDataBox, FlightAPI.io, OAG, Cirium, Flightradar24 — mostly paid or tiny trials; these return schedules/status/positions, not shoppable fares, so they are largely irrelevant to a rewards *pricing* optimizer.

**Google Flights:** No official public API. QPX Express shut down in 2018; only the Travel Impact Model (emissions) API remains public. "Google Flights API" products on RapidAPI are scrapers. Confirmed dead — do not chase it.

**Open/free datasets (adopt immediately):**
- **OpenFlights** — airports, airlines, planes, routes as CSV/.dat under the Open Database License. Caveat: the **route data has not been updated since June 2014** (historical value only). Airport/airline reference data still useful.
- **OurAirports** — ~78,000 airports plus runways/frequencies/navaids, **public domain**, updated nightly, on GitHub (davidmegginson/ourairports-data). Best free airport reference set.
- **Bureau of Transportation Statistics DB1B / T-100** — real historical US fare and traffic data, free, public domain — but **US domestic only**, so not relevant to the India→Singapore corridor.
- Historical fare data for the MVP corridors is **not** available free anywhere in structured form.

### 3. Hotel data

**Amadeus Hotel Search/List** — same self-service shutdown applies; skip.

**Hotelbeds APItude** — a free evaluation API key gives a generic key (no specific pricing/commission), and a **sandbox limited to 50 requests/day**. Sandbox returns cached results with approximate pricing (real hotel structure, indicative prices). Going live requires a formal **certification process** (submit test cases, confirm a live booking six months out for 2 adults/2 children, then get approval) — not attainable pre-launch, and direct integration is famously heavy (industry estimates put a full APItude build at months and tens of thousands of dollars). Sandbox is usable for prototyping hotel data shape only.

**Booking.com Demand API** — approved **Managed Affiliate Partners only**; requires Partner Centre access (often enabled via an account manager). A sandbox endpoint exists (`demandapi-sandbox.booking.com`) but you need affiliate approval first. **Critical ToS conflict:** partners are **not allowed to cache availability or prices**, and **data forwarding is strictly forbidden** — this directly breaks the project's local-SQLite-KB model. Avoid.

**Expedia Rapid / EPS** — partner program targeting travel sellers with booking volume; applying is free but approval rarely granted to pure data users/pre-launch. Skip.

**RateHawk / Emerging Travel Group, TravelgateX** — B2B, contract/partner-gated; not self-serve free. Impala effectively defunct as a public hotel-connectivity API. Google Hotels — no public developer API.

**Tripadvisor Content API (recommended for hotel/POI CONTENT, not live prices).** Self-serve: register, set a max daily budget, provide billing info. Per the Tripadvisor Content API FAQ: *"We offer the first 5000 API calls for free every month after you sign up. You do need a credit card to sign up as any overage will be charged to the billing account you provided. You are required to select a max daily budget when you sign up."* Search APIs allow up to 10,000 calls/day; the **development phase provides 50 calls/sec and 1,000 calls/day** (the Location Mapper API has a separate 25,000 calls/day allowance). It returns ~7.5M locations with reviews, ratings, and *some* pricing metadata, but it is built for owners displaying their own content and has **no official path to competitor data**. Treat it as a **content/ratings** source (hotel names, ratings, review counts, photos, descriptions), NOT a live-rate source. **Attribution to Tripadvisor is mandatory** (logos, bubble ratings).

**Yelp Fusion / Yelp Places** — Yelp **ended free access**; all accounts were converted to paid (Starter ~$7.99 per 1,000 calls). No longer a free option. Drop it.

**Foursquare Places (recommended for dining/attractions POIs).** The Foursquare official blog states that all developer accounts *"can enjoy $200 a month in free usage credits"* (Sandbox/Pay-as-you-go tiers; *"free credits do not roll over"*), and the pricing page confirms *"up to 10,000 free calls on Pro endpoints"* — while Premium endpoints (photos, tips, hours, ratings) have **no** free tier. Note the **legacy v3 endpoints deprecate May 15, 2026** — build on the new FSQ OS Places API. Genuinely free POI/venue source.

**OpenStreetMap / Overpass API (recommended, fully free/open).** Free POI data (restaurants, attractions, transit) under ODbL — attribution required, no key. Ideal for interests/attractions in the KB. **Wikivoyage/Wikipedia APIs** (CC BY-SA) for destination guides and descriptions — free, no key, attribution/share-alike required.

### 4. Credit-card / rewards / points data — mostly must be hand-curated
This is the project's hardest gap, and the honest finding is: **there is no free, structured, comprehensive, reusable dataset or API for credit-card reward rules — especially for India.**

- **ccreward / ccreward.app (aashishvanand)** — the most relevant project for India+Singapore, covering MCC-based earn rates across HDFC, Axis, ICICI, SBI, Amex India, DBS, UOB, OCBC, and ~20+ other Indian and Singaporean banks. **But the reward-rule data is NOT published as a reusable dataset** — it lives server-side in Firebase/Firestore and is not committed to the public `ccreward-web` repo; cloning the code yields an empty database. There is **no public API**. License is a **custom non-commercial dual license** requiring attribution and open-sourcing of derivatives. Verdict: usable as a reference app and as a template for your own schema, but **not** a data feed.
- **USCreditCardGuide/Wings-of-the-Points** — points-transfer partners and ratios, but **US-only** (Chase UR, Amex MR, Citi TYP, Capital One, Bilt, Marriott), embedded as JS objects inside `index.html`, licensed **CC BY-NC-ND 4.0** (no commercial use, no derivatives). Verdict: can eyeball/reference for personal non-commercial use; cannot legally redistribute a modified/derived dataset. Limited relevance to India.
- **YuanzheSu/AwardChart** — open-source award-redemption logic covering ~26 US bank transfer partners and ~136 carriers, using OurAirports data. Useful as a structural template for an award-charts module; still US-centric.
- **AwardWallet, seats.aero, PointsYeah, Roame, point.me** — no free public developer API for reward rules/valuations. **seats.aero** is the notable exception for one narrow slice: **award-seat availability**. Its developer docs state *"Seats.aero Pro users may be able to access the partner API for up to 1,000 API calls per day at no cost,"* with Pro at *"$9.99 USD per month or $99.99 USD per year."* The partner API can *"perform live searches on any route across 20 different mileage programs"* and *"instantly quote pricing and availability for over 70,000 routes"* (Aeroplan, Alaska, United, Singapore, Emirates, Qatar, etc.). However, the Knowledge Base warns: *"Live Search is not available to Pro users, regardless of use case. Access is limited to approved commercial partners,"* and *"The seats.aero API (personal or commercial) is not available in all countries"* — so India/UAE availability is not guaranteed, and commercial use is prohibited without written permission. Not free (requires Pro), and not commercial-safe, but the cheapest real award-availability source.
- **RBI / Indian bank published feeds** — none. Banks publish reward terms as human-readable web pages/PDFs only.

**Conclusion:** Credit-card earn rules, offers, transfer-partner ratios, award charts, and points valuations should remain **hand-curated in your KB with provenance**. This is a legitimate, defensible design choice — the structured free data simply does not exist.

### 5. Currency / FX — solved, fully free
- **Frankfurter (recommended default).** Free, open-source, **no API key, no signup, no usage limits** (rate-limited only against abuse). ECB reference rates, ~30+ currencies incl. INR, SGD, AED, USD, historical data back to 1999. Terms permit caching. Covers all MVP corridors. Only caveat: daily ECB reference rates, not live intraday quotes — perfectly adequate for budgeting/costing.
- **exchangerate.host / ExchangeRate-API / Open Exchange Rates / Fixer / CurrencyAPI** — free tiers exist but now generally require a free API key and impose monthly caps (and exchangerate.host applies overage billing). ExchangeRate-API's open endpoint is keyless, updates once/24h, and **its terms explicitly permit caching**. ECB publishes raw reference rates directly too.
- **Verdict:** Use Frankfurter as primary (keyless, no limits, cacheable), ExchangeRate-API open endpoint as fallback.

### 6. MCP servers for travel — now useful for this student profile
An MCP server is a transport/tool contract, not automatic entitlement. It may expose its provider's own data, wrap an API key, or wrap public-site access; classify those cases separately.
- **Gondola MCP (recommended first live spike)** — provider-hosted, no key needed for anonymous search, and currently exposes hotel cash/points rates, flexible-night pricing, cash flights, direct links, reviews, and price context. Use read-only tools and recompute all value in our kernel.
- **Airbnb MCP (OpenBnB / openbnb-org)** — hosted/community options with **no API key required**, accessing public Airbnb listings and respecting robots.txt by default. For the active non-commercial student profile, use only as an experimental, low-volume, feature-flagged rental source with visible verification warnings. Never enable its robots override or circumvent blocking.
- **Duffel flights MCP (ravinahp/flights-mcp)** — community MCP wrapping Duffel; needs a Duffel key underneath (free test key works). Read-only search. Reasonable for local experimentation.
- **seats.aero MCP** — wraps the seats.aero Partner API; needs a Pro ($9.99/mo) key underneath.
- **Google Maps MCP** — official-ish; needs a Google Maps Platform key (has a free monthly credit but requires a billing account/credit card).
- **Tripadvisor / Booking.com / Expedia / Skyscanner / Kayak MCPs** — exist in community registries (Smithery, mcp.so, Glama) but each needs the underlying provider key, which for these providers is gated/paid/partner-only, so the MCP does not remove the access barrier.

**Verdict:** Gondola materially improves the zero-budget prototype path and should be the first live adapter. MCPs remain runtime evidence sources behind the gateway, never direct writers to the approved KB. OpenBnB remains an experimental personal-use source rather than a durable dependency.

### 7. Legal / ToS — caching & storage rights (this project stores data in local SQLite)
- **Frankfurter / ExchangeRate-API:** caching explicitly permitted. ✅ Store freely.
- **OurAirports:** public domain — store, modify, redistribute freely (credit appreciated, not required). ✅
- **OpenFlights:** Open Database License (ODbL) — store/use freely **with attribution** and share-alike on derived databases. ✅ with attribution.
- **OpenStreetMap/Overpass:** ODbL — attribution + share-alike. ✅ with attribution.
- **Wikivoyage/Wikipedia:** CC BY-SA — attribution + share-alike. ✅ with attribution.
- **Foursquare:** storing/caching POI data is allowed within plan terms; check display/attribution requirements. ✅ within free credits.
- **Tripadvisor Content API:** display requires **mandatory Tripadvisor attribution**; content is for display, generally not for building a competing database — caching for your own display is constrained. ⚠️ Content/ratings display OK with attribution; do not repurpose as a rate database.
- **Duffel:** test data fine to store while developing; live data governed by Duffel terms (you're not booking, so lower risk). ⚠️ Re-verify before any commercial launch.
- **Booking.com Demand API:** **explicitly forbids caching availability/prices and forbids data forwarding.** ❌ Incompatible with your KB model.
- **Travelpayouts Data API:** data is delivered from cache and Travelpayouts *recommends* using it to generate static pages — so local storage is aligned with intended use. ✅ (affiliate-network signup required).
- **seats.aero:** non-commercial personal use only; commercial use needs written permission. ⚠️ Fine for a non-commercial MVP; must renegotiate before monetizing.
- **RapidAPI scrapers (Sky-Scrapper etc.):** data rights uncertain/grey; fine for throwaway prototyping, risky to store-and-display or commercialize. ⚠️

## Comparison Table

| Source | Data type | Free-tier limit | Signup difficulty (student) | Real vs sandbox | Caching / ToS | Verdict |
|---|---|---|---|---|---|---|
| **Amadeus Self-Service** | Flights + hotels | Free monthly quota (test + prod) | Was instant; **new signup paused** | Test = cached real subset | Portal dies **17 Jul 2026** | ❌ Do not adopt |
| **Duffel (test)** | Flight contract fixtures | Unlimited sandbox | Instant, email only, no card | Airline/Duffel sandbox data | OK for dev | ✅ Primary sandbox source |
| **Kiwi Tequila** | Flights | — | Invitation-only now | — | — | ❌ Closed |
| **Skyscanner official** | Flights | — | Partner review, weeks | Live | Commercial agreement | ❌ Not pre-launch |
| **Sky-Scrapper (RapidAPI)** | Flights/hotels | ~100 req/mo | Instant, email | Scraped Skyscanner data | Grey ToS | ⚠️ Prototype only |
| **Travelpayouts Data API** | Cached flight prices/trends | Affiliate acct req'd | Free network signup, instant | Cached real prices | Storage aligned w/ use | ✅ Best free "real-ish" price |
| **Travelpayouts Aviasales Search** | Live fares | MAU ≥ 50,000 | Manual approval | Live | — | ❌ Not attainable |
| **AviationStack** | Flight *status* | 100 (GitHub cites 500)/mo | Instant, no card | Real status (not fares) | — | ⚠️ Status only |
| **OpenFlights** | Airports/airlines/routes | Full download | None | Real (routes stale since 2014) | ODbL, attribution | ✅ Reference data |
| **OurAirports** | Airports | Full download | None | Real, nightly | Public domain | ✅ Best airport ref |
| **BTS DB1B/T-100** | US historical fares | Full download | None | Real (US only) | Public domain | ✅ but US-only |
| **Hotelbeds APItude** | Hotel rates | 50 req/day sandbox | Free key; live needs certification | Cached approx prices | Live gated | ⚠️ Shape only |
| **Booking.com Demand** | Hotel inventory | Partner only | Affiliate approval | Live | **No caching allowed** | ❌ Conflicts w/ KB |
| **Expedia Rapid** | Hotels | Partner only | Needs booking volume | Live | — | ❌ Not pre-launch |
| **Tripadvisor Content API** | Hotel/POI content, ratings | 5,000/mo (50/s, 1,000/day in dev) | Instant but **card required** | Real content, limited prices | Mandatory attribution | ✅ Content, not rates |
| **Foursquare Places** | POIs/venues | $200/mo credit; up to 10k Pro calls | Instant, no biz check | Real | Cache OK in-plan | ✅ POIs |
| **OpenStreetMap/Overpass** | POIs | Unlimited (fair use) | None | Real | ODbL attribution | ✅ POIs |
| **Wikivoyage/Wikipedia** | Destination content | Unlimited (fair use) | None | Real | CC BY-SA | ✅ Content |
| **Frankfurter** | FX rates | Unlimited, no key | None | Real (ECB daily) | Cache OK | ✅ Primary FX |
| **ExchangeRate-API (open)** | FX rates | Keyless, ~daily | None | Real | Cache OK | ✅ FX fallback |
| **seats.aero Partner API** | Award seat availability | 1,000/day with Pro | **$9.99/mo Pro**, personal | Real cached (Live = partner only) | Non-commercial only; geo-limited | ⚠️ Cheapest award data |
| **ccreward** | India/SG card reward rules | App only | — | Real (locked in Firestore) | Non-commercial license | ❌ Not a feed |
| **Wings-of-the-Points** | US transfer ratios | Full (in HTML) | None | Real (US only) | CC BY-NC-ND | ⚠️ Reference only |
| **Gondola MCP** | Hotel cash/points, flexible nights, cash flights | No key for anonymous search | Instant | Live/provider-hosted | Personal/non-commercial terms tension | ✅ Student live spike |
| **OpenBnB MCP** | Airbnb listings/prices | No key | Instant | Public-site wrapper | Personal experiment; no circumvention | ⚠️ Experiment only |

## Recommendations

**Sign up / adopt in this order:**

1. **Gondola MCP (live hotel/points + cash flights)** — first live-provider spike after G1. Anonymous, read-only, zero provider spend, and directly aligned with the project’s rewards differentiator.
2. **Frankfurter (FX)** — zero friction, no key, cacheable, covers INR/SGD/AED/USD. Replaces hand-curated exchange rates immediately. Fallback: ExchangeRate-API open endpoint.
3. **OurAirports + OpenFlights (reference data)** — download and ingest into SQLite. Replaces hand-curated airport/airline/IATA-code tables and gives route adjacency (accepting OpenFlights' route staleness). Public domain / ODbL.
4. **OpenBnB MCP (experimental rentals)** — evaluate locally at low volume after Gondola; always visibly experimental/verify-required and never the sole stay source.
5. **Duffel (flight offers, test mode)** — structured sandbox offers of the correct shape for recorded contract tests; useful even when Gondola supplies the live-demo cash flight.
6. **Travelpayouts Data API (cached flight trends)** — optional free enrichment for realistic route price ranges; do not expect the gated live Aviasales Search API.
7. **Foursquare + OpenStreetMap/Overpass + Wikivoyage (POIs)** — replaces hand-curated attractions/dining/destination content for Singapore and later corridors.
8. **Tripadvisor Content API** — optional hotel/POI content only if a billing card is acceptable; otherwise use OSM/Wikivoyage plus curated hotel content.

**Each recommendation maps to what it replaces in the current hand-curated dataset:** Frankfurter → FX table; OurAirports/OpenFlights → airport/airline/route reference; Duffel + Travelpayouts → sample flight prices; Foursquare/OSM/Wikivoyage → attractions/dining/destination content; Tripadvisor → hotel content/ratings (not prices).

**Keep hand-curating (no free structured source exists):**
- Credit-card reward earn rates / MCC rules (India + Singapore) — model your own schema (ccreward is a good structural reference).
- Points transfer partners and ratios for Indian/UAE programs.
- Airline and hotel award charts; points valuations.
- Dedicated award-flight availability remains the hardest gap. Gondola can cover live hotel cash/points evidence for the demo; a separate award-flight source is still needed when one is free/personal-use or explicitly approved.

**Benchmarks that would change this advice:**
- If the project ever reaches **real traffic (a live site with meaningful MAU, ~50k+)**, revisit Travelpayouts Aviasales Search API and Booking.com/Expedia affiliate programs for live inventory.
- If you secure **any budget**, the first paid dollar should go to seats.aero Pro (award availability) and/or a Duffel live account (real fares) — both are cheap and self-serve.
- If you **monetize**, you must renegotiate seats.aero (commercial permission), re-check Duffel/Travelpayouts terms, and never adopt Booking.com Demand (its no-caching rule breaks your architecture).
- Watch the **Foursquare v3 → FSQ OS Places migration (v3 deprecates 15 May 2026)** and the **Amadeus self-service shutdown (17 Jul 2026)**.

## Caveats
- **Fast-moving terms:** Amadeus's self-service shutdown (July 17, 2026) and Foursquare's v3 deprecation (May 15, 2026) are both imminent; Yelp already went fully paid. Re-verify any provider's terms at signup.
- **Sandbox ≠ live prices:** Duffel test mode and Hotelbeds sandbox return cached/simulated data, not the exact live consumer fare. For a KB-driven MVP that presents indicative costed budgets (not bookable prices), this is acceptable and should be labeled "indicative" in the UI.
- **The RapidAPI "Skyscanner"/"Google Flights" APIs are unofficial scrapers** — uncertain legality, freshness, and longevity; acceptable for a few prototype pulls, not a foundation.
- **Source-quality note:** Several free-tier figures (e.g., AviationStack 100 vs 500/mo, Foursquare's exact Pro allotment) come from secondary blogs and vary; treat the provider's own dashboard/pricing page at signup as authoritative.
- **India/UAE geo-restrictions:** seats.aero explicitly limits API access by geography; confirm availability from India/UAE before relying on it.
- **GitHub Student Developer Pack:** contains cloud/hosting/domain/dev-tool credits (DigitalOcean, Azure, Namecheap, MongoDB Atlas, Heroku) useful for hosting the MVP, but **no travel-data API offers** — it will not solve the flight/hotel/rewards data problem, only the infrastructure one.
- **Credit-card data is the structural weakness** of any rewards optimizer built for free — accept that this remains manual and invest curation effort there rather than hunting for a nonexistent free API.
