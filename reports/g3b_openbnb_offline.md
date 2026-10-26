# G3b — OpenBnB rental-stay adapter (offline development)

**Status: OFFLINE DEVELOPMENT COMPLETE — NOT ELIGIBLE FOR LIVE ACTIVATION.**
Branch `codex/g3b-openbnb-offline`, started from `6428b78` (FI1 merge, PR #18). Nothing was
installed, launched or called against OpenBnB, Airbnb or any other provider. No credentials,
spend, crawling, model calls, booking or deployment were involved.

This report separates four things, because they must not be confused:

1. [Implemented and offline-tested behaviour](#1-implemented-and-offline-tested-behaviour)
2. [Upstream interfaces verified from source](#2-upstream-interfaces-verified-from-source)
3. [Unresolved permission and retention questions](#3-unresolved-permission-and-retention-questions)
4. [Live acceptance and production wiring still required](#4-live-acceptance-and-production-wiring-still-required)

## Headline finding

OpenBnB is a **community scraper of airbnb.com**, and Airbnb's current Terms of Service
prohibit exactly that. This is not an ambiguous permission the project could resolve by
reading harder: the primary source says it. Per the task and spec 16 §7 ("do not
self-approve unclear source permissions"), the adapter is built, tested and isolated, and the
live path is **unconstructible** without a `LiveActivationApproval` that only a human can
supply. The recommendation is not to activate it for any use that is not a deliberate,
informed, low-volume personal demo decision by a person.

## 1. Implemented and offline-tested behaviour

Everything lives under `backend/gateway/travel/adapters/openbnb/` (14 modules, 14 synthetic
fixtures). No shared contract, default registry, provider factory, OpenAPI, frontend, spec,
seed, golden, Tier-F or ingestion file was changed.

| Concern | Behaviour | Where |
|---|---|---|
| Tool allowlist | Exactly `airbnb_search` and `airbnb_listing_details`; anything else (booking, messaging, payments, URL fetch, `tools/list`, case/space variants) is `permission_denied` **before** any fixture lookup or process start. | `tool_policy.py` |
| Argument allowlist | Only the verified keys. `ignoreRobotsText` is refused **whatever its value**; so are `placeId`, `cursor`, price filters, `pets`, unknown keys. City text is a typed plain-name check (no `/ ? # % & < > :`, newlines, URLs, `..`, >80 chars). | `tool_policy.py`, `requests.py` |
| Request fidelity | Only `{"vacation_rental"}` requests with `rooms == 1`, no `area_ids`, 1–16 adults, ≤28 nights. Anything else is `unsupported_domain` before dispatch and spends no budget. Nothing is silently narrowed or dropped. | `requests.py` |
| Date/occupancy fidelity | The response's own `searchUrl` must echo requested check-in/out and adults/children/infants. A mismatch rejects the whole payload; an echo that cannot be confirmed yields **no priced quote** (`request_not_verified`). | `normalize.py`, `links.py` |
| Price scope | Only a stated stay **total** becomes `total_minor`. A nightly rate is reported as `IncompleteListing(price_nightly_only)` and is never multiplied, summed or shown as a total. Ambiguous currency (`$`, `¥`), two prices/scopes in one label, a night-count mismatch, zero, malformed or excess precision, and absurd magnitudes are typed refusals. | `price.py` |
| Currency | Taken from the label; never converted and never taken from the request. A bare `$` needs an explicit, recorded caller assumption, which is then written into the evidence notes. | `price.py`, `normalize.py` |
| Fees/taxes | `complete` only if an itemization reconciles exactly to the total **and** has a taxes line; `taxes_uncertain` if taxes are absent or stated excluded (taxes stay `None`, never `0`); `partial` with no itemization. An itemization that does not sum to the total demotes the listing. | `price.py`, `normalize.py` |
| Trust | Every quote is `status="verify_required"`, `needs_verification=True`, `expires_at=None`, with a visible source-method warning ("community MCP that scrapes Airbnb web pages (not an official API)…"), an origin note (`origin=synthetic_fixture` + "not live inventory", or `origin=openbnb_stdio_live`), `terms_version` marked *unreviewed*, and attribution. Fixtures cannot claim live status or origin. | `normalize.py`, `fixture_transport.py` |
| Not invented | `lat/lon`, `area_id`, `room_name`, `rate_plan`, `cancellation_summary`, `refundable`, `placement`, `pay_timing`, channels are left unset unless the provider stated them; coordinates come only from the details tool and never as `0,0`. A rating is scaled only from a label that states an "out of 5" scale. | `normalize.py`, `detail.py` |
| Links | A returned link is used only if it is exactly `https://[www.]airbnb.com/rooms/<digits>` for the result's own id (no userinfo/port/query/fragment/IDN/backslash/control characters); otherwise it is dropped, not repaired. `/rooms/undefined` (upstream issue #54) never becomes a quote. | `links.py` |
| Untrusted text | Host-authored titles/amenities are NFKC-normalized, stripped of invisible/bidi characters (both split and joined readings), checked for injection phrases and role markers, stripped of markup and links, and length-bounded. Provider **error text is classified, never echoed**. | `sanitize.py`, `normalize.py` |
| Transport boundary | Fixture transport (tested) and a stdio transport (never run): fixed `node <abs>/dist/index.js`, no `npx`, no flags, child env pins `IGNORE_ROBOTS_TXT=false` and `DISABLE_GEOCODING=true` by default, pinned server name/version check after `initialize`, no `tools/list`, 25 s total timeout, 512 KB payload bound, generic non-leaking errors. | `fixture_transport.py`, `mcp_client.py` |
| Human gate | `StdioOpenBnBTransport` refuses to construct without a `LiveActivationApproval` (`terms_disabled`). Nothing in the repository creates one. | `mcp_client.py` |
| Disabled by default | `OpenBnBAdapter(enabled=False)` raises `provider_unavailable` before touching budget or transport. Only `registry.py` computes `enabled`, from `TRIPWISE_OPENBNB_ENABLED` and `TRIPWISE_OPENBNB_KILL_SWITCH`; **the kill switch wins**. The default registry has no `openbnb` entry (tested with the flag set). | `adapter.py`, `registry.py` |
| Budgets and failure | 2 calls per plan, 40 lifetime, reserved atomically **before** dispatch and never refunded; **zero retries** (a deliberate tightening of spec 16's one retry — see DEVIATIONS); 30 s adapter timeout; circuit breaker opens after 2 failures and stops dispatching; concurrency 1; ledger contention fails soft. | `budget.py`, `adapter.py` |
| Fallback | Through the real `TravelInventoryService` with the real `SampleAdapter`: an OpenBnB failure leaves sample hotels with a `provider_unavailable` diagnostic; different-currency quotes are rejected as `mismatched_response`; accepted OpenBnB quotes get `scope_verified=False` and basis `unknown` unless `complete`. | `evals/test_g3b_adapter.py` |
| Retention | No raw cache, no file writes anywhere in the package; the only persistence is the call counter (`plan_id` → count). A full offline flow run in an empty directory leaves it empty. | `evals/test_g3b_boundaries.py` |

### Tests (all offline; sockets, `subprocess` and asyncio process creation are patched to raise)

| File | Tests |
|---|---:|
| `test_g3b_policy_requests.py` | 49 |
| `test_g3b_sanitize_links.py` | 53 |
| `test_g3b_price.py` | 49 |
| `test_g3b_normalize.py` | 62 |
| `test_g3b_detail.py` | 27 |
| `test_g3b_transport.py` | 41 |
| `test_g3b_adapter.py` | 33 |
| `test_g3b_boundaries.py` | 28 |
| **G3b total** | **342** |

Baseline before any change (own seeded run, regional catalogs present): **2220 passed, 1 skipped**.
With G3b: **2562 passed, 1 skipped** (2220 + 342). The first full run after the code was
written failed one existing guard — D1's "every `TRIPWISE_*` literal is documented" — because
the two new flags were undocumented; they are now documented in `backend/.env.example` only.

**Test teeth.** Twenty targeted mutations were applied one at a time and every one was killed
by at least one G3b test (nightly promoted to total; robots override accepted; date mismatch
ignored; any-host links accepted; sanitizer disabled; per-plan ceiling off by one; disabled
guard removed; kill switch ignored; approval gate removed; completeness forced to `complete`;
bare `$` guessed as USD; status forced to `live`; `0,0` coordinates accepted; robots env pin
flipped; itemization mismatch tolerated; taxes zero-filled; duplicate listings kept; zero price
accepted; a retry added; reservation moved after dispatch).

**Process note, stated plainly.** Tasks 1–5 followed red→green. For Task 6 (budget, fixture/stdio
transports, adapter, registry) the implementation was written before its tests; the tests were
then written and their strength established by the mutation run above rather than by watching
them fail first.

### Contract gaps (reported, not papered over)

1. **No discovery-only accommodation type.** `HotelQuote.total_minor` is required, and a
   nightly advertised rate or unverifiable price is not a total. The adapter returns these as
   its own `IncompleteListing` rows (`search_rental_stays`) and `search_hotels` returns priced
   quotes only. A shared "discovery listing" contract would need a spec decision.
2. **`EvidenceMeta` has no origin field.** Fixture-versus-live origin is carried as an explicit
   note and by transport type, not by schema.
3. **The registry cannot express "needs a recorded human approval".** It is enforced in the
   live transport constructor instead.
4. **`AdapterCapabilities.live_data` is static,** so it is `False`; truth about origin is in
   each quote's notes.

## 2. Upstream interfaces verified from source

Inspected on **2026-10-26** (no Airbnb page, search, `robots.txt` or listing was requested).

| Item | Finding | Source |
|---|---|---|
| Repository | `openbnb-org/mcp-server-airbnb`, default branch `main`, head `d5a8f18f5978b0a33dea4b3ec130c389bad845cc` (2026-08-06), tag `v0.3.0` = same commit; not archived | `https://github.com/openbnb-org/mcp-server-airbnb`, `api.github.com/repos/openbnb-org/mcp-server-airbnb/{commits,tags}` |
| Package | npm `@openbnb/mcp-server-airbnb@0.3.0`, published 2026-08-06, integrity `sha512-igJNB5RAEb4LyQphl++B3kL8ONCnl/pcF6qVAsE2E75//6vmcwgSoHqmdf+bHNdAXZ4Hma9eetxdkPJd088IdA==` | `https://registry.npmjs.org/@openbnb/mcp-server-airbnb` |
| License | MIT (`LICENSE`: "Copyright (c) 2025 Altmatter"); no attribution requirement beyond keeping the notice | repo `LICENSE`, `package.json` |
| Transport | **stdio only** (Node ≥18, `StdioServerTransport`). No remote/HTTP endpoint exists in v0.3.0 (a Streamable-HTTP PR, issue #62, is open) | `index.ts` |
| Tools | Exactly two: `airbnb_search`, `airbnb_listing_details` | `index.ts` `AIRBNB_TOOLS`, `manifest.json` |
| `airbnb_search` args | `location` (required), `placeId`, `checkin`, `checkout`, `adults`, `children`, `infants`, `pets`, `minPrice`, `maxPrice`, `cursor`, `propertyType` ∈ {`entire_home`,`private_room`,`shared_room`,`hotel_room`}, `ignoreRobotsText` | `index.ts` `AIRBNB_SEARCH_TOOL` |
| `airbnb_listing_details` args | `id` (required), `checkin`, `checkout`, `adults`, `children`, `infants`, `pets`, `ignoreRobotsText` | `index.ts` |
| Method | Fetches `https://www.airbnb.com/s/<slug>/homes?…` and `/rooms/<id>` HTML with a browser `User-Agent`, parses the embedded `#data-deferred-state-0` JSON with cheerio → **scraper wrapper** | `index.ts` `handleAirbnbSearch/ListingDetails` |
| Robots | Fetches and honours `robots.txt` by default. **Override paths:** `ignoreRobotsText` per call, `IGNORE_ROBOTS_TXT=true` env, `--ignore-robots-txt` flag. **If robots.txt cannot be fetched or parsed it assumes everything is allowed (fails open).** | `index.ts` `fetchRobotsTxt`, `isPathAllowed`; `README.md` |
| Third-party egress | Unless `placeId` is given or `DISABLE_GEOCODING=true`, the `location` string is sent to Photon (`photon.komoot.io`) and, as fallback, Nominatim | `index.ts` `geocodeLocation`; `README.md` "External Services" |
| Response shape | One MCP text block holding JSON. Search: `{searchUrl, searchResults[{id,url,demandStayListing{id,description,location},badges,structuredContent{…body},avgRatingA11yLabel,listingParamOverrides,structuredDisplayPrice{primaryLine,secondaryLine{accessibilityLabel},explanationData{title,priceDetails{items{description,priceString}}}}}], paginationInfo}`; arrays are **flattened to `", "`-joined strings** (`flattenArraysInObject`). Details: `{listingUrl, details[{id, …}]}` with `LOCATION_DEFAULT{lat,lng,title,subtitle}`, `AMENITIES_DEFAULT{seeAllAmenitiesGroups}` (struck-through items under `"Not included"`). **No numeric price, currency or scope field** — price exists only inside label strings. | `index.ts` `allowSearchResultSchema`, `allowSectionSchema`; `util.ts`; `README.md` |
| Errors | Failures return `isError:true` with a JSON text `{error: "<message>", …}` (robots block, HTTP status, timeout, "page structure may have changed"); unknown tool raises `McpError` | `index.ts` |
| Known fragility | #54 decoded listing ids are not validated (`/rooms/undefined`); #55 coordinates can be stubbed; #60 non-US IPs get a domain-handoff stub page | open issues on the repository |
| Airbnb terms | Terms of Service, **"Last Updated: February 5, 2026"**, §11.1: "Do not use bots, crawlers, scrapers, or other automated means" to access or collect data from the Airbnb Platform | `https://www.airbnb.com/help/article/2908` |
| Hosted alternative | `https://openbnb.ai/` is a separate hosted commercial service with free credit and pricing. It is **not** this adapter's source, was not evaluated, and is out of scope (paid/credentialed services need human approval). | `https://openbnb.ai/` |

**Not verified (and therefore not claimed):** the exact wording of any live price, rating or
cancellation label; whether `demandStayListing.location` carries coordinates; Airbnb's current
`robots.txt` rules for `/s/` and `/rooms/`; response behaviour under rate limiting. The
fixtures use the verified *key paths* with invented *leaf values* and say so in their
`_fixture_provenance`. `reports/*` from earlier gateway milestones were not treated as proof of
anything about OpenBnB.

## 3. Unresolved permission and retention questions

These need a human decision; none were self-approved.

1. **Airbnb ToS §11.1 vs. any live use.** The terms forbid automated access. Is there a
   defensible personal, low-volume, demo-only reading, or is the answer simply "no"? Until a
   person decides, `LiveActivationApproval` is never created.
2. **Robots.** Upstream fails open when robots.txt is unreadable, and offers three override
   paths. This repository's code never sets them, but it cannot make upstream's own robots
   check fail closed. Is a server whose compliance check fails open acceptable at all?
3. **Third-party egress.** With geocoding on, the traveler's destination text goes to
   Photon/Nominatim (OSM Foundation usage policy applies). The default here is
   `DISABLE_GEOCODING=true`, but upstream then mis-resolves many non-US locations. Which
   trade-off, and does it need a privacy-notice line?
4. **Retention.** Spec 09: "no persistent raw cache without a documented basis." None exists
   (no basis was found, so none was created). Even normalized quotes copy scraped listing
   data; whether storing them in a saved trip is permitted is unanswered.
5. **Attribution/branding.** MIT needs only the notice, but showing Airbnb names, listing text
   and links in a product UI may need Airbnb's brand rules. The evidence attribution string says
   "Listing data from Airbnb via the unaffiliated OpenBnB community MCP".
6. **Property-kind semantics.** `entire_home` ≈ `vacation_rental` is an approximation; a
   reviewed crosswalk is needed before rentals compete with hotels in ranking.
7. **Commercial profile.** Inactive by spec; this adapter's `supports_commercial_use` is `False`
   and `allowed_profiles` is `{"student_noncommercial"}`.

## 4. Live acceptance and production wiring still required

Not done, deliberately:

- A human decision on §3.1–3.3, recorded as a `LiveActivationApproval` and a reviewed
  `terms_version` (the current value is the string `unreviewed: …`).
- A pinned, locally installed copy of `@openbnb/mcp-server-airbnb@0.3.0` (and its lockfile
  review); today `StdioOpenBnBTransport` refuses to start when the entrypoint is absent.
- **Schema capture:** a sanitized, human-supervised live capture of search and details output
  to replace the invented leaf values in the fixtures and to confirm the label grammar in
  `price.py` (the parser refuses anything it does not recognize, so it fails closed until then).
- A bounded live acceptance run (within the 2-calls-per-plan / 40-lifetime ceilings) with a
  recorded outcome, as G3.2 did for Gondola.
- Adding the registry entry to a registry, wiring the adapter into plan assembly, and adding
  `openbnb` to `api/runtime_config.LIVE_PROVIDER_FLAGS` so production startup rejects the flag
  like Gondola's. None of that was touched.
- Packaging: `gateway.travel.adapters.openbnb` is intentionally **not** listed in
  `pyproject.toml`'s package list, so it does not ship in the deployable image.
- A spec decision on the discovery-only gap (contract gap 1).
- UI treatment of `verify_required` rentals with a scraper warning (no frontend was touched).

## Verification evidence

See the final section appended after the review and gate (below).
