# G2 — Open/Reference Importers

**Milestone status:** complete
**Branch:** `feat/g2-open-reference-importers`
**Base:** `feat/g1-travel-inventory-gateway` @ `67d7d95` (G1's completed HEAD — G2 is stacked on G1 until G1 merges; not based on `main`)
**Authoritative spec:** 09 §13 — "G2 — Open/reference importers... Add one FX, airport, and POI importer at a time. Gate: licence metadata retained, deterministic snapshots, no change to golden optimizer values."

## 1. Scope and non-goals

G2 builds offline, deterministic, licence-aware reference-data importers for FX rates and
airports, and audits the existing POI catalog pipeline against the same gate. This is
reference-data ingestion, not pipeline integration. Explicitly **not done** (per the
milestone's own scope correction): `agents/pipeline.py`/`/plan` was not wired to
`estimate_costed_trip_via_gateway`; no live travel-inventory adapter (Gondola or otherwise)
was added; Tripadvisor live transport was not touched; no runtime provider/MCP calls were
added; no booking/payment/hold/transfer execution exists; the deterministic kernel's
financial behavior is unchanged; `core/seeds/fx_rates.yaml` was not automatically replaced;
no golden value changed; no frontend change; no new LLM call site.

## 2. Source-selection evidence

Both sources were **re-verified live** during this session via web fetch, per the
milestone's explicit instruction not to trust the old `reports/free_apis.md` blindly.

### FX — Frankfurter (`api.frankfurter.dev`)

| Field | Value |
|---|---|
| Source owner | Frankfurter (`frankfurter.dev`), open-source (MIT), free/keyless hosted API |
| Fixed source URL | `https://api.frankfurter.dev/v2/rates?base=USD&quotes=AED,INR,SGD` (base: `https://api.frankfurter.dev/v2/`) |
| Source method | Keyless HTTPS GET, no account |
| Licence identifier | `frankfurter-api-blended-central-bank-sources` (no single well-known SPDX licence found; commercial use permitted per FAQ, "see each provider's terms") |
| Attribution | "Exchange rate data from Frankfurter (frankfurter.dev), aggregating data from 84 central banks/providers." |
| Terms/licence URL | `https://frankfurter.dev/docs` (no dedicated legal page found) |
| Snapshot/release identifier | Injected retrieval date, since Frankfurter has no versioned release |
| Retrieval date | 2026-08-20 |
| Schema/version confirmed | **v2 flat JSON array**: `[{"date","base","quote","rate"}, ...]` — corrects the stale report's assumed v1 nested shape |
| Cache/retention position | Not cached/persisted by this project; a fresh fetch is a manual dev command |
| Geographic coverage | 169 currencies (confirmed live), 84 central banks/providers |
| Known gaps | No per-currency upstream-provider attribution captured; no dedicated licence document beyond the FAQ |
| Credential/payment/overage exposure | **None** — confirmed keyless, no billing page, USD 0 |

**Corrected finding:** the old report described Frankfurter as an ECB-only proxy with
~30 currencies. Live verification of `/v2/currencies` today returned 169 currencies,
explicitly including `AED`, `INR`, `SGD`, `USD` — the v2 API aggregates from 84 central
banks/providers, not ECB alone.

### Airports — OurAirports (`davidmegginson/ourairports-data`)

| Field | Value |
|---|---|
| Source owner | OurAirports (David Megginson); official page `ourairports.com/data/` links to the GitHub mirror |
| Fixed source URL | `https://davidmegginson.github.io/ourairports-data/airports.csv` |
| Source method | Static HTTPS file download, no key |
| Licence identifier | `public-domain` — confirmed: "All data is released to the Public Domain" |
| Attribution | "Airport data courtesy of OurAirports (ourairports.com), released to the Public Domain." |
| Terms/licence URL | `https://ourairports.com/data/` |
| Snapshot/release identifier | `(retrieval date, content hash)` — OurAirports has no formal versioned release, only nightly rolling updates |
| Retrieval date | 2026-08-20 |
| Schema/version confirmed | 19-column CSV (confirmed via the official data dictionary): `id, ident, type, name, latitude_deg, longitude_deg, elevation_ft, continent, iso_country, iso_region, municipality, scheduled_service, gps_code, icao_code, iata_code, local_code, home_link, wikipedia_link, keywords` |
| Cache/retention position | Not cached/persisted by this project |
| Geographic coverage | Global, all airport types |
| Known gaps | No formal release/version identifier; OpenFlights route/connectivity data explicitly excluded (out of scope per instruction) |
| Credential/payment/overage exposure | **None** — confirmed |

### POIs — existing `gateway/catalog/` (audited, not re-sourced)

Overture/OSM/Wikivoyage licensing was already reviewed in prior milestones (I3–I7); this
milestone only audited the existing pipeline against the G2 gate (§6 below).

## 3. Files created and modified

**Created:**
- `backend/gateway/reference/__init__.py`, `contracts.py` (shared `SourceProvenance`)
- `backend/gateway/reference/fx/` — `__init__.py`, `contracts.py`, `errors.py`, `parse.py`,
  `build.py`, `fetch.py`, `fixtures/*.json` (7 fixtures)
- `backend/gateway/reference/airports/` — `__init__.py`, `contracts.py`, `errors.py`,
  `parse.py`, `build.py`, `fetch.py`, `fixtures/*.csv` (5 fixtures)
- `backend/evals/test_reference_contracts.py`, `test_reference_fx_contracts.py`,
  `test_reference_fx_build.py`, `test_reference_fx_fetch_boundary.py`,
  `test_reference_airports_build.py`, `test_reference_airports_fetch_boundary.py`,
  `test_g2_poi_acceptance.py`, `test_reference_boundary.py`
- `docs/superpowers/plans/2026-08-20-g2-open-reference-importers.md`

**Modified:** `DEVIATIONS.md` (7 new entries). No production runtime file
(`agents/pipeline.py`, `agents/estimator.py`, `agents/gateway_estimator.py`,
`core/optimizer/`, `core/transfer/`, `core/seeds/fx_rates.yaml`, `contract/openapi.json`)
was touched.

## 4. FX importer behavior and coverage

`gateway/reference/fx/`: parses the confirmed v2 flat-array JSON via
`json.loads(raw, parse_float=Decimal)` so no rate value is ever materialized as a binary
`float`, even transiently — bare JSON integers are still routed through `Decimal(str(x))`
rather than `Decimal(x)`. Rejects: malformed JSON, non-list top-level shape, non-3-letter
currency codes, malformed/non-finite/zero/negative rates, oversized payload (262,144-byte
bound, enforced before parsing), and duplicate `(base, quote)` pairs with **conflicting**
rates (fails closed). A non-conflicting exact duplicate row is deduplicated but now leaves a
`provenance.warnings` trace (added after code review — see §12). Converts to `rate_micro`
(rate × 1,000,000) using `ROUND_HALF_EVEN` (banker's rounding) — verified at both rounding
boundaries (`63.2000005 → 63_200_000`, `63.2000015 → 63_200_002`). Computes cross-rates only
when both legs share a common pivot base in the source data (high-precision `Decimal`
division, 50-digit context, before quantization); an unresolvable cross pair is recorded as a
warning, never invented. **Coverage gap, honestly preserved:** if a requested currency is
absent from the source snapshot, no rate is fabricated and the gap is documented in
`provenance.warnings` (proven by `test_missing_currency_is_documented_not_invented`). The
importer's output is never written to `core/seeds/fx_rates.yaml` and is never read by the
optimizer or transfer pathfinder.

## 5. Airport importer behavior and coverage

`gateway/reference/airports/`: parses the confirmed 19-column OurAirports CSV via stdlib
`csv.DictReader`, enforcing a 5,000,000-byte / 5,000-record bound before row-level
validation. Uppercase-normalizes `iso_country`/`iata_code`/`icao_code`/`gps_code`/
`local_code`. Duplicate stable `id`s are a structural invariant violation and fail closed.
Duplicate `iata_code`s are handled **conservatively**: every record is preserved (never
dropped), with a `provenance.warnings` entry noting the code is no longer a reliable unique
key — proven with a real-world scenario (an active airport and a `closed_airport` both
claiming `DEL`). Airports without an `iata_code` are always preserved, never excluded. The
sample fixture carries real, well-known, public-domain facts for the seven airports serving
all six existing regional catalog corridors plus the two Kernel MVP corridor cities: DEL
(Indira Gandhi Intl), BOM (Chhatrapati Shivaji Maharaj Intl), SIN (Changi), DXB (Dubai Intl),
LHR (Heathrow, serving LON), CDG (Charles de Gaulle, serving PAR), JFK (serving NYC) — all
present and asserted in `test_valid_fixture_produces_normalized_records_for_all_seven_corridor_airports`.
**Coverage gap, honestly preserved:** OpenFlights route/connectivity data is explicitly out
of scope per the milestone's own instruction; this importer produces airport reference facts
only, no route graph.

## 6. POI importer acceptance results

No new POI ingestion architecture was created. `backend/evals/test_g2_poi_acceptance.py`
audits the existing `gateway/catalog/` pipeline against spec 09 §13's gate:

| G2c requirement | Result |
|---|---|
| Licence metadata survives into normalized claims/artifacts | **Pass** (pre-existing: `test_catalog_compaction.py`) |
| Source release and attribution survive compaction **and tiling** | **Pass, newly proven** — `test_tiling_preserves_real_licence_release_and_attribution` builds a real tiled catalog through the actual `build_catalog_tiles`/`TiledPlaceAdapter` pipeline and asserts real, non-placeholder `licence_id="CDLA-Permissive-2.0"`, `source_release="2026-07-22.0"`, `attribution_requirements="Overture Maps Foundation"` on the loaded claims (the pre-existing tiles test only used a placeholder `"L"`) |
| Repeated fixture builds are byte-identical | **Pass** (pre-existing: `test_catalog_determinism.py`) |
| Runtime request paths do not fetch POI data | **Pass** (pre-existing: `test_network_isolation.py`) |
| All six regional corridors continue to work | **Pass, newly proven** — `test_all_six_regional_corridors_resolve` checks SIN/BOM/DXB/NYC/LON/PAR explicitly (the pre-existing test only compared SIN vs BOM pairwise) |
| No 130 MB active catalog artifact accidentally committed | **Pass, newly proven** — `test_no_active_catalog_artifact_is_tracked_by_git` runs `git ls-files backend/catalogs` and asserts empty output |
| Existing POI identity/provenance model not replaced | **Pass, newly proven** — structural field-set assertions on `Place`/`PlaceClaim`/`CompactClaim` |

**G2c is accepted with evidence**, per the milestone's own instruction not to add useless
production code when the existing pipeline already satisfies the gate.

## 7. Determinism proof (actual hashes)

Both importers: build twice from the same fixture bytes, compare `model_dump_json()` output
byte-for-byte and its sha256.

```
FX:
  bytes equal: True
  output sha256: 3fd61e350cd7e0b4428e77017929bfaccf3b6cfe43b2587f9d3c29c9b49ec8c8
  input  sha256: 3d88f8a0d7df23370bd922981eb6420a658d8e3c92bfabc005aea22373a84c8a

Airports:
  bytes equal: True
  output sha256: 618e56bf960fa86688be045fd38095ca280f6f680793fe8c7e80260946c62733
  input  sha256: df0486705dbd8b61d5eaec0a581c0031749a1aa552152cb67f7ddc2b76fbf364
```

`test_stable_deterministic_ordering` (airports) additionally feeds *reversed* input row order
and asserts identical output order — proving the sort is a real deterministic key, not an
accident of input order.

## 8. Network-isolation proof

`test_reference_boundary.py::test_full_reference_package_zero_network` monkeypatches
`socket.socket.connect` to raise, then runs the real parse+build path for **both** importers
end-to-end from local fixtures and asserts non-empty normalized output — proving the guarded
code path actually executed rather than short-circuiting. Each importer additionally has its
own dedicated zero-network test. `test_reference_fx_fetch_boundary.py` and
`test_reference_airports_fetch_boundary.py` prove via AST walk that `fetch.py` (the only
module in this diff capable of a real network call) is never imported by `core/`, `agents/`,
or `api/`.

## 9. Test counts

| | Before G2 | After G2 |
|---|---|---|
| Backend tests | 847 (G1 baseline) | **898** |
| New tests | — | 51 |
| Strict mypy source files | 113 | 127 |

Test file breakdown: `test_reference_contracts.py` (4), `test_reference_fx_contracts.py`
(5), `test_reference_fx_build.py` (16, incl. the post-review duplicate-warning test),
`test_reference_fx_fetch_boundary.py` (3, incl. post-review rejection test),
`test_reference_airports_build.py` (11), `test_reference_airports_fetch_boundary.py` (3,
incl. post-review rejection test), `test_g2_poi_acceptance.py` (5),
`test_reference_boundary.py` (5) = **51 new tests**, 0 removed, 0 modified existing test.

## 10. Mypy and Ruff results

```
mypy --strict core/ accounts/ agents/ api/ gateway/
  Success: no issues found in 127 source files

ruff check accounts/ agents/ gateway/ evals/
  All checks passed!

ruff check core/ api/ (legacy-debt ceiling)
  7 findings (ceiling 12) — pre-existing, unrelated to G2, unchanged
```

## 11. Golden-drift result

`git diff --exit-code -- backend/evals/golden/` — **clean, no diff.**
`backend/core/seeds/fx_rates.yaml` — untouched (also explicitly asserted by
`test_existing_kernel_fx_seed_and_goldens_are_unchanged`, which checks the three pre-existing
seed pairs and their exact `rate_micro` values are still present byte-for-byte).

## 12. Code-review findings and resolutions

Dispatched `superpowers:requesting-code-review` against the full diff
(`67d7d95..16247e3`), with explicit instructions to hand-verify the cross-rate math, the
banker's-rounding boundaries, licence/attribution propagation end-to-end, and duplicate
handling. The reviewer independently re-derived the cross-rate value
(`95.68/1.274 = 75.10204081632653... → 75_102_041`) and both rounding-boundary cases,
confirming correctness rather than trusting the plan's prose.

- **Important — vacuous host-allowlist check.** `fetch.py`'s `ALLOWED_HOST not in URL` check
  (both FX and airports) can never fire today since nothing varies the hardcoded URL
  constant. **Resolved:** added a test for each fetch module that monkeypatches the URL
  constant to a mismatched host and confirms the check genuinely rejects it — the check logic
  was already correct, it just had no test proving so, and this pattern (`scripts/fetch_overture.py`'s
  shape) is likely to be reused for a future live-provider adapter where the URL could
  genuinely vary.
- **Minor — silent exact-duplicate FX rows.** Two identical `(base, quote, rate)` rows
  collapsed to one record with no trace, contradicting the importer's own
  record-every-anomaly philosophy. **Resolved:** added a `provenance.warnings` entry on the
  exact-duplicate path, test-first (`test_exact_duplicate_row_is_documented_in_warnings`).
- **Minor — unused `unsupported_domain` error code.** `fx/errors.py` declared a literal
  nothing ever raised. **Resolved:** confirmed dead via grep, removed.
- **Minor — `fx/errors.py`/`airports/errors.py` near-duplication** and **`source: dict[str,
  object]` looseness** — reviewed and accepted as-is (the two importers are deliberately
  independent siblings; a `TypedDict` would be marginally stricter but isn't a defect).

No Critical findings. Full gate re-run clean after all fixes (§§9–11 above reflect the
post-fix state).

## 13. Explicit confirmations

- **`/plan` remains on the legacy estimator path.** `agents/pipeline.py` still calls
  `agents.estimator.estimate_costed_trip` directly, unchanged since G1. This milestone added
  zero lines to any of `agents/pipeline.py`, `agents/estimator.py`, or
  `agents/gateway_estimator.py` — confirmed via `git diff --stat 67d7d95..HEAD`.
- **No provider, MCP, credential, paid service, or runtime crawl was activated.** Both new
  `fetch.py` modules are manual, human-run, offline developer commands that are never
  imported by `core/`, `agents/`, `api/`, or any test other than their own boundary tests
  (AST-verified). All 51 new tests run against local, committed, sanitized fixtures only. No
  `.env` change, no new environment variable, no credential reference anywhere in the diff
  (grep-confirmed). `SampleAdapter` (from G1) remains the only enabled travel-inventory
  provider.

## 14. Remaining limitations

- FX importer output is not yet reviewed/promoted into any seed file — that remains a
  separate, explicitly human-gated future action (never automatic, per this milestone's own
  boundary rule).
- Airport importer's sample fixture covers 7 airports (the corridors currently in scope); the
  real OurAirports dataset (~80,000 rows) has not been fetched or committed in this
  milestone — only the manual `fetch.py` command exists for a human to do that later.
- No per-currency upstream-provider verification beyond what Frankfurter's own aggregation
  claims (documented as a known gap, not fabricated).
- The `core/`+`api/` ruff legacy-debt ceiling (7/12) is pre-existing, untouched by this
  milestone.
- G2c added acceptance tests but no new capability to the POI pipeline — by design.

## 15. Recommended next milestone

Per spec 09 §13's build order, **G3 — first student-profile live adapter** is the next
milestone: a read-only `GondolaAdapter` behind the gateway, anonymous-search-only, for
hotel cash/points and cash-flight evidence, gated on the same zero-spend/student-profile
checklist that governed G1's `SampleAdapter`. G3 is **not implemented** in this milestone —
this is a recommendation only, consistent with the instruction to name it without building
it.
