# G3b OpenBnB rental-stay adapter (offline) — task plan

Branch `codex/g3b-openbnb-offline` from `6428b78` (FI1 merge). Specs: 09 §13 G3b, 16 §§5–9, 13–16.
Scope: offline development only. No live call, no activation, no production wiring, no shared-contract change.

## Verified upstream facts that shape the design (details in `reports/g3b_openbnb_offline.md`)
- `openbnb-org/mcp-server-airbnb` v0.3.0 (`d5a8f18`), MIT, **stdio** server (Node), two tools: `airbnb_search`, `airbnb_listing_details`.
- It parses `airbnb.com` HTML (cheerio) → `scraper_wrapper`. Airbnb ToS §11.1 (updated 2026-02-05) forbids bots/scrapers.
- `ignoreRobotsText` tool argument and `--ignore-robots-txt` flag exist; robots fetch/parse failure **fails open**. Geocoding calls Photon/Nominatim unless `placeId`/`DISABLE_GEOCODING`.
- Results are one JSON text block; arrays are flattened to strings; prices appear only as accessibility labels.

## Tasks (each: failing test → code → green → commit)
1. `tool_policy` + `requests`: two-tool allowlist, per-tool argument allowlist (`ignoreRobotsText`, `placeId`, `cursor`, price filters rejected), typed city/date/occupancy validation.
2. `sanitize` + `links`: injection stripping/bounds for host-authored text; strict `https://www.airbnb.com/rooms/<digits>` validation; listing-id validation.
3. `price`: money/label/breakdown parsing — never nightly-as-total, never ambiguous currency, never zero price.
4. `contracts` + `normalize`: bounded native models; payload→`HotelQuote` or typed `IncompleteListing`; date/occupancy verification via `searchUrl`.
5. `detail`: LOCATION_DEFAULT coordinates (no 0,0), amenities kept native, enrichment guard.
6. `budget`, `fixture_transport`, `mcp_client` (stdio, injected opener, human-approval gate, no `npx`, no robots override), `adapter` (disabled default, circuit breaker, no retry, timeout), `registry` (entry builder; kill switch wins; default registry unchanged).
7. Orchestration/fallback + boundary tests (no sockets/subprocess, AST import/forbidden-token checks).
8. Report, DEVIATIONS, review, fixes, full gate.
