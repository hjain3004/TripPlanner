# Tripadvisor Terra API — Developer Reference

> Source: docs.terra.tripadvisor.com (all guide pages, all API reference pages, changelog, and release notes reviewed).
> Legal/policy sections below are paraphrased summaries — always confirm against your signed agreement for anything contractual.

## Table of Contents
1. Platform Overview
2. Authentication & Security
3. Versioning & Compatibility
4. Rate Limits, Quotas & Endpoint Authorization
5. Core Concepts
6. Locale vs. Language
7. Enumerations
8. API Reference
9. Error Handling Reference
10. Commercial Policies
11. Release Notes Summary

---

## 1. Platform Overview

Terra is Tripadvisor's partner content-delivery platform. It exposes Tripadvisor's travel data — Locations (hotels, restaurants, attractions), Reviews, Photos, and Geos (destinations from country down to neighborhood level) — through both a REST API and downloadable batch data feeds. It also exposes an AI-driven "Agentic Search" capability that returns recommended locations/experiences with supporting review citations, intended for agentic/LLM use cases.

Access is tiered by commercial package: **Discover** (self-service, lowest throughput, limited UGC access, API-only), **Growth**, **Scale**, **Innovate**, and **Transform** (highest tiers, add feed access and higher quotas). Your package determines which endpoints you're authorized to call, your QPS, and your daily quota. Package management happens in the Terra Dashboard.

---

## 2. Authentication & Security

Every API call requires an `X-API-Key` header; there is no OAuth/session-based auth model. Requests without a valid key return `401 Unauthorized`.

| Scenario | HTTP Status | Message |
|---|---|---|
| Key missing from request | 401 | API key is not provided |
| Key not recognized | 401 | API key has not been found |
| Key disabled / account inactive | 401 | API key is not enabled |
| Key valid but endpoint outside subscription | 403 | API Key does not have access to endpoint |

All traffic is served over HTTPS/TLS 1.2+ only; plaintext HTTP is rejected. Keys can be rotated instantly from the Dashboard's "My API Key" card if compromised — rotation immediately invalidates the old key, so all consuming services must be updated in the same change window to avoid an outage. Never hardcode the key client-side or commit it to source control; use environment variables or a secrets manager. An AWS WAF filters malicious traffic ahead of the application layer as an additional protection.

---

## 3. Versioning & Compatibility

Tripadvisor uses parameter-based versioning: append `?version=N` (or the beta channel `?version=beta`) to a request; versioning applies per-API, not per-endpoint. Omitting the parameter returns the latest version.

Within a major version, Tripadvisor guarantees it will not remove/rename fields or endpoints, change data types/nullability in breaking ways, or alter validation rules — but it may add new optional parameters, new fields/objects to responses, or new enum values, none of which are treated as breaking on Tripadvisor's side. Consuming code should therefore ignore unrecognized fields and tolerate unfamiliar enum values rather than using strict schema validation.

`version=beta` always tracks latest-stable-plus-in-progress-changes and can break compatibility at any time — testing only, never production.

Deprecation is signaled via HTTP response headers, following RFC 9745 (`Deprecation` header, Unix timestamp) and RFC 8594 (`Sunset` header, HTTP date). Integrations should monitor for these headers and migrate before the `Sunset` date, after which the endpoint returns `410`/`404`.

Feed versions behave differently: they do not auto-upgrade and stay pinned until changed via the Management Portal or your Account/Partner Support contact.

---

## 4. Rate Limits, Quotas & Endpoint Authorization

Limits are enforced at the account level on a rolling 24-hour window (starts at first call, resets 24h after that call — no fixed daily reset clock), plus a per-second cap.

| Package | QPS | Daily quota |
|---|---|---|
| Discover | 10 | 10,000 calls/day per API (further capped optionally in Dashboard) |
| Growth | 25 | Per contract |
| Scale / Innovate / Transform | 50 | Per contract |

Exceeding either limit returns `429 Too Many Requests`. Implement exponential backoff with jitter — tight-loop retries only prolong throttling. Ways to reduce call volume: cache per the Caching Policy, use multi-GET endpoints to batch IDs into one request (billing is still per-entity, not per-call), and set a daily budget cap in the Dashboard.

Separately, your package/add-ons determine **endpoint authorization**. Calling an endpoint outside your package returns `403 Forbidden` ("API Key does not have access to endpoint") — fixed by upgrading the package or enabling the add-on, not by retrying.

Agentic Search (Recommendations) has its own limits: 10 req/s on standard plans, custom limits on enterprise; access is currently provisioned manually per partner (self-service planned for 2026 Q1).

---

## 5. Core Concepts

### 5.1 Location IDs and Geo IDs
Every hotel, restaurant, attraction, and geographic place on Tripadvisor has a unique numeric ID (Location ID or Geo ID) — the single identifier used across the allowlist, content endpoints, and feeds.

### 5.2 Catalog endpoints vs. Location endpoints

| | Catalog endpoints (`/catalog/locations/...`) | Location endpoints (`/locations/...`) |
|---|---|---|
| Scope | Entire Tripadvisor catalog (8M+ POIs), ignores allowlist/geofencing | Restricted to locations on your allowlist |
| Payload | Lightweight: id, name, address, coordinates, description, overall_rating, urls (+ distance/bearing for nearby) | Full: everything above plus categories, attributes, opening hours, rankings, awards, review count, optional photos |
| Intended use | Discovery/research, populating allowlist, admin tooling, debugging | Live, consumer-facing traffic — "near me," in-app search, map/list views |
| Traffic pattern | Not meant for high-volume end-user traffic | Designed for production throughput |

Typical workflow: search the Catalog to discover Location IDs → add relevant ones to your allowlist → query the full Location endpoints for production traffic.

### 5.3 The Allowlist
Your allowlist is the set of Location IDs your API key may return via content endpoints (`/locations/*`, feeds) — it does **not** restrict Catalog search, which always covers the full catalog. Depending on your contract, allowlists may not apply at all (blanket geography/category access) — check with your account team.

| Operation | Method | Effect |
|---|---|---|
| Retrieve | GET | Returns current allowlist, paginated (default page size 1000) |
| Append | POST, `operation_type=APPEND` | Adds new IDs, leaves existing untouched |
| Delete | POST, `operation_type=DELETE` | Removes specified IDs only |
| Overwrite | POST, `operation_type=OVERWRITE` | Replaces the entire allowlist — anything omitted is removed |

Use APPEND/DELETE for incremental changes; reserve OVERWRITE for when your own system is the source of truth.

---

## 6. Locale (factual content) vs. Language (reviews/UGC)

| | `locale` (factual content) | `language` (reviews only) |
|---|---|---|
| Granularity | Full locale + region (`es-MX`, `fr-CA`) | Canonical language only (`es`, `fr`) |
| Fallback | Yes — walks a parent-locale chain to `en-US`/`en` | No — empty result if no match |
| Multiple values | Yes, repeat the query param | No, single value only |
| Applies to | Names, descriptions, addresses, GenAI text, geo names, enum labels | Review titles/text, owner responses |
| Default | `en-US` | `en` |

**Locale fallback example:** `es-AR → es-MX → es → en-US → en`. The `language` field on the returned translation object shows which locale actually resolved. Array fields (names, descriptions) resolve independently per requested locale; single-value enum labels (category `display_name`, award names, subrating labels) resolve using only the first requested locale's chain. Invalid locale → `400` with supported codes listed.

Supported locales: English (11 variants), Spanish (7), French (4), German (3), Portuguese (2), Dutch (2), Italian (2), Chinese (3), Arabic (2), plus 15 single-locale languages (Danish, Greek, Finnish, Hebrew, Hungarian, Indonesian, Japanese, Korean, Norwegian, Polish, Russian, Swedish, Thai, Turkish, Vietnamese).

**Review language:** reviews are drawn from a fixed "review pool" (your most recent N reviews, or reviews within a configured time window) and only then filtered by language — never expanded to find matches, so an unmatched language returns an empty `data` array. 27 codes supported (ar, cs, da, de, el, en, es, fi, fr, hu, id, it, iw, ja, ko, nl, no, pl, pt, ru, sk, sr, sv, th, tr, vi, zh-CN, zh-TW), plus special value `primary` (originally-authored language only, no machine translation). Default `en`. Invalid code → `400`.

---

## 7. Enumerations

A daily-refreshed enumerations feed provides translated display labels for coded values: `category`, `amenities`, `restaurant_dining_options`, `rules-based` (hotel style), `rating`, `sub_ratings`, `restaurant_styles`, `dining_restrictions`, `priority_1_attributes` ("good for" tags), `award_names`, `restaurant_meal_types`, `attribute_type` (section headers), `other` (misc. templates). 50+ languages supported. Recommended: cache locally, refresh daily/weekly, fall back to the raw enum ID if a translation is missing, and handle placeholder tokens in `award_names`/`other`.

---

## 8. API Reference

Base URL: `https://terra.tripadvisor.com/api`. All endpoints accept `Accept: application/json` (default) or `application/problem+json`. Query params marked "array" can be repeated for multiple values.

### 8.1 Catalog Endpoints (discovery — not allowlist-restricted)

#### `GET /catalog/locations/search` — Search Locations Catalog
Free-text search by name or address against the full catalog.

| Param | Type | Notes |
|---|---|---|
| `query` | string, required | 1–500 chars |
| `search_type` | string | default `NAME` |
| `country_code` | string | 2-letter ISO code |
| `geo_name` | string | city/town/country |
| `postal_code` | string | takes precedence over `geo_name` if both given |
| `category` | enum | `RESTAURANT`, `ATTRACTION`, `HOTEL` |
| `locale` | array of string | priority order |
| `page` | integer ≥1 | 1-based |
| `size` | integer ≤20 | default 20 |

Response: `data[]` of `{ location, matched_value }` + `pagination` (`page`, `size`, `total_elements`, `total_pages`). Errors: 400, 429, 500.

#### `GET /catalog/locations/nearby` — Search Nearby Locations Catalog
Same catalog projection, ordered by proximity or rating within a radius or bounding box.

| Param | Type | Notes |
|---|---|---|
| `location_id` | string | reference point; required if `lat`/`lon` absent |
| `lat`, `lon` | number | -90..90 / -180..180 |
| `radius` | double >0 | required unless bounding box given |
| `unit` | string | default `MI` |
| `sw_lat`, `sw_lon`, `ne_lat`, `ne_lon` | string | bounding-box alternative |
| `category` | enum | `RESTAURANT`/`ATTRACTION`/`HOTEL` |
| `min_rating` | string 1–5 | |
| `locale` | array of string | |
| `page` | integer ≥1 | |
| `size` | integer ≤20, default 20 | |
| `sort` | array, default `rating,desc` | supports `distance` (radius only) and `rating` |

Response: `data[]` of `{ bearing, distance_kilometers, distance_miles, location }` + `pagination`. Errors: 400, 429, 500.

#### `GET /catalog/locations/{id}` — Get Catalog Location *(added July 2026)*
Resolves one known Location ID to the abbreviated catalog projection. Not allowlist-restricted. Path param `id` (int32, required); query param `locale` (array). Errors: 400, 404, 429, 500. Use `GET /locations/{id}` for the fuller record.

**Catalog Location object:** `id`, `geo`, `geo_id`, `names[]` (`language`, `primary`, `value`), `descriptions[]`, `addresses[]` (`city`, `country_code`, `country_name`, `formatted`, `language`, `postal_code`, `state`, `street_address`, `street_address2`), `coordinates` (`latitude`, `longitude`), `overall_rating` (`count`, `icon_url`, `rating`), `urls` (`android_intent`, `menu`, `official`, `tripadvisor`).

### 8.2 Geo Endpoints

#### `GET /geos/{id}` — Geo Details
Full detail for one geographic entity: `id`, `abbreviation`, `names[]`, `descriptions[]`, `coordinates`, `hierarchy.ancestors[]` (`geo_id`, `name`, `rank`), `type` (`id`, `name`), `urls` (`flights`, `geo_page`, `hotels`, `restaurants`, `things_to_do`), `awards[]`, `forum_faqs[]` (`question`, `language`, `answers[]`), `suggested_itineraries[]` (day-by-day `itinerary[]` with `location_ids[]`), deprecated `collections[]`. Query param `locale` (array); path param `id` (int32, required). Errors: 400, 404, 429, 500.

#### `GET /geos` — Multiple Geos Details (multi-GET)
Query params `id` (array of int32, required, unique), `locale` (array). Unresolvable IDs are silently omitted. Response wraps the Geo object in `data[]`. Errors: 400, 429, 500.

### 8.3 Location Endpoints (full detail — allowlist-restricted)

#### `GET /locations/{id}` — Location Details
Full record: `id`, `geo`, `geo_id`, `names[]`, `descriptions[]`, `addresses[]`, `coordinates`, `categories[]` (`id`, `display_name`, `hierarchy`, `parent_category`, `top_level_category` enum: Accommodation/Experience/Attraction/Eat & Drink), `attributes[]`, `accommodation` (`brand`, `chain`, `star_rating`, `room_count`, `prices[]`), `opening_hours` (`formatted[]`, `periods[]`), `phone_numbers[]`, `official_email`, `photos.total_count`, `price_level`, `rankings[]`, `awards[]`, `recommended_visit_length` (coded 0–4), `status` (`value`: OPEN/CLOSED/TEMPORARILY_CLOSED + dates), `traveler_ratings` (`overall`, `breakdowns[]`, `subratings[]`, `language_counts[]`), `neighborhoods[]`, `urls`. Path param `id` (int32, required); query param `locale` (array). Errors: 400, 404, 429, 500. Optional fields are omitted (not null) when no data exists.

#### `GET /locations` — Multiple Locations Details (multi-GET)
Query params `id` (array of int32, required), `locale` (array). IDs not licensed/nonexistent are omitted, not errored. Errors: 400, 429, 500.

#### `GET /locations/{id}/photos` — Location Photos
Fields: `id`, `location_id`, `caption`, `publish_ts`, `photo`, `source`, `user`, `cv_metadata` (eligible partners only). Query params: `locale` (array), `page` (int32 ≥0), `size` (int32 ≥1), `sort` (array). Errors: 400, 404, 429, 500.

#### `GET /locations/{id}/reviews` — Location Reviews
Fields: `id`, `title[]`, `text[]`, `rating`, `subratings[]`, `trip_type` enum (BUSINESS/COUPLES/FAMILY/FRIENDS/SOLO/NONE), `travel_date`, `publish_ts`, `photos[]`, `owner_response`, `user`, `url`.

| Param | Notes |
|---|---|
| `rating_min` | minimum overall rating |
| `trip_type` | filter |
| `published_after_ts` | date `YYYY-MM-DD` |
| `sort_by` | `MOST_RECENT` (default) / `HIGHEST_RATED` |
| `published_after_review_id` | keyset cursor |
| `language` | UGC code or `primary`; default `en` |
| `page`, `size` | pagination |

Errors: 400, 404, 429, 500.

#### `GET /locations/nearby` — Search Nearby Locations
Same radius/bounding-box pattern as Catalog nearby, but allowlist-restricted, full Location object returned. Adds `include_photo` boolean (default `false`). Errors: 400, 429, 500.

#### `GET /locations/search` — Search Locations
Free-text search restricted to your allowlist, full Location payload. Same params as `/catalog/locations/search`. Initial release optimized for non-Asian languages; CJK support planned by demand. Errors: 400, 429, 500.

### 8.4 Agentic Search

#### `POST /recommendations/search` — Recommendations
Natural-language query → AI-ranked Locations/Experiences with review citations.

Query param: `locale` (array). Body:

| Field | Type | Notes |
|---|---|---|
| `query` | string, required | free text; destination inferred if no geo given |
| `geo` | object, required | `{name}` \| `{geo_id}` \| `{search_area: {centroid_latitude, centroid_longitude, search_radius_meters}}` |
| `limit` | int32, default 5 | |
| `top_level_categories` | array of enum | Accommodation/Experience/Attraction/Eat & Drink |
| `exclude_location_ids` | array of int32 | pagination simulation |
| `response_preference` | enum, default `quality` | `quality` \| `speed` |

Response: `search_results[]` (typed `location`/`experience`) + `review_sources[]` (`id`, `snippet`). Errors: 400, 404, 429, 500. Rate limit: 10 req/s standard; access provisioned per-partner today.

### 8.5 Feed File API

Bulk access; Innovate/Transform tiers (or add-on) only. Files regenerate daily, retained 30 days.

| Endpoint | Purpose |
|---|---|
| `GET /feeds/files/list` | List available files; params `page` (≥0), `size` (≥1), `sort`. Returns `data[]` of `{filename, filesize}` + `pagination` |
| `GET /feeds/json/{filename}` | Returns `{url, exp}` — presigned URL + expiry, for deferred/programmatic download |
| `GET /feeds/{filename}` | 302 redirect straight to a presigned URL — simplest for direct/scripted downloads |

Filenames: `{feed_type}.json` (all types except reviews); reviews use `{feed_type}{yyyyMMdd}.json`. Files are gzipped.

### 8.6 Allowlist API

| Endpoint | Purpose |
|---|---|
| `GET /allowlist` | Params `page` (≥0), `size` (≥1), `sort`. Returns `data[]` of int32 IDs + `pagination`. Errors: 400, 500 |
| `POST /allowlist` | Body `{ allowlist: [int32...], operation_type: APPEND \| DELETE \| OVERWRITE }`. Returns `{ added, deleted, no_change }`. Errors: 400, 404, 429, 500 |

Note: for OVERWRITE, `deleted` reflects existing IDs dropped for being absent from the payload; for DELETE, IDs never present aren't counted at all.

### 8.7 MCP (Model Context Protocol) Server

Remote MCP server at `https://docs.terra.tripadvisor.com/mcp` lets AI coding tools (Cursor, Windsurf, Claude Desktop) query Terra's live API/docs directly from the editor.

```json
{
  "mcpServers": {
    "tripadvisor-content": {
      "url": "https://docs.terra.tripadvisor.com/mcp"
    }
  }
}
```

If your account requires auth, headers are passed however your specific MCP client supports header configuration.

---

## 9. Error Handling Reference

All errors follow an RFC 7807 "problem" JSON body: `type` (URI identifying the error category), `title`, `status`, `detail`, `instance` (request path), `trace_id` (for support escalation).

| Title | Status | Meaning |
|---|---|---|
| Bad Request | 400 | Malformed request generally |
| Constraint Violation | 400 | Field-level validation failure; includes `field_errors[]` |
| Unauthorized | 401 | Missing/invalid API key |
| Forbidden Access | 403 | Key valid but lacks endpoint access |
| Resource Not Found | 404 | Generic not-found |
| Geo Not Found | 404 | Geo-specific; includes `ids[]` unresolved |
| Location Not Found | 404 | Location-specific; includes `ids[]` |
| Too Many Requests | 429 | Rate limit exceeded |
| Internal Server Error | 500 | Unexpected server-side failure |

---

## 10. Commercial Policies (developer-relevant summary)

These are paraphrased summaries of formal policy pages — confirm against your own signed agreement for anything contractual.

**Caching:** Beyond your specific contract terms, general caching/copying/downloading/indexing of Licensed Content is not permitted; the one universal exception is caching the Location ID itself to speed up your application.

**Linking requirements:** UI displaying Tripadvisor content must link back appropriately — photo galleries need "See all photos," property names/review counts link to the Tripadvisor page, truncated reviews need "Read more" linking to the full review, AI-generated summaries need "More on Tripadvisor" attribution plus an inline citation, bookable properties need "Check Rates & Availability."

**Discover usage-based pricing:** Billed per "billable entity." For most location endpoints, each distinct Location ID returned = one entity, whether from a single call or a multi-GET batch. Reviews/photos endpoints bill per API call (one entity per call). Geo endpoints bill per Geo ID returned. 4xx/5xx responses are never billed. Feed File API and Allowlist API calls don't count toward usage. New accounts get a one-time lifetime allowance of 1,000 free billable entities, then a six-tier volume discount applies per billing cycle:

| Tier | Usage (entities/cycle) | Price/entity (USD) |
|---|---|---|
| 1 | 1–1,000 | $0.01500 |
| 2 | 1,001–2,000 | $0.01350 |
| 3 | 2,001–3,000 | $0.01215 |
| 4 | 3,001–4,000 | $0.01094 |
| 5 | 4,001–5,000 | $0.00984 |
| 6 | 5,001+ | $0.00900 |

**Master Terms & Conditions:** Apply specifically to Discover-tier partners; everyone else follows their individually negotiated agreement. The license is limited, non-exclusive, and revocable, and explicitly excludes AI/ML model training or fine-tuning — the one exception is RAG-based "grounding" of an LLM for internal, non-commercial testing only. Also covers attribution/display rules, restrictions on scraping or mixing Tripadvisor data with other UGC, confidentiality, indemnification, and a liability cap tied to fees paid in the preceding 12 months. Recommend legal review of the full text directly on the API Master Terms page.

**Brand/display guidelines:** Separate Logo & Guidelines and Partner Brand Guidelines pages govern trademark usage — relevant for whoever owns the UI layer.

---

## 11. Release Notes Summary (reverse chronological)

| Date | Change |
|---|---|
| Jul 2026 | New `GET /catalog/locations/{id}` endpoint (same schema as other catalog endpoints) |
| Jun 2026 | `locale` query param added across all factual-content endpoints, with fallback-chain resolution |
| May 2026 | `language` query param added to Reviews endpoint; review pool made consistent (filters narrow, never expand, the pool) |
| Feb 2026 | New Catalog Search endpoints (`/catalog/locations/search`, `/catalog/locations/nearby`); internal search performance optimizations |
| Dec 2025 | New `/locations/search` and `/locations/nearby` endpoints; enhanced Reviews filtering/sorting/pagination params |
| Nov 2025 | Multi-GET endpoints introduced for `/locations` and `/geos` |
| Oct 2025 | New `GET /files/list` (beta) feed-listing endpoint; empty objects/nulls removed from all responses; photo ranking improved |

*Document compiled from docs.terra.tripadvisor.com as of August 2026. Endpoint behavior, pricing tiers, and package names should be periodically re-verified against the live docs site, since Tripadvisor may ship changes noted only in the changelog/release notes.*