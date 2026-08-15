# I7 — Catalog Relevance Repair → Regional Rollout

Plan: `docs/superpowers/plans/2026-08-15-itinerary-i7-catalog-relevance-and-regional-rollout.md`
Branch: `feat/i7-regional-rollout`

## 1. Per-task status

| Task | Status |
|---|---|
| 0 — Preflight | done |
| 1 — Refuse to build a catalog from zero claims | done |
| 2 — Filter to relevant, in-scope places | done |
| 3 — Retrieval asks for what it needs (category filter, distance rank) | done |
| 4 — Per-region catalog addressing | done |
| 5 — Region resolution replaces Singapore constants | done |
| 6 — Honest capability reporting (RegionCapability, contract, MSW, UI) | done, with one scoped deferral (see §5) |
| 7 — Mumbai catalog | done |
| 8 — Dubai, NYC, London, Paris catalogs | done |
| 9 — Coverage report and Gate I7 | done |

All nine tasks are complete and committed on `feat/i7-regional-rollout`. Not pushed, no PR opened.

## 2. `make gate` — full output

```
455 passed, 4 warnings in 5.29s
--- mypy --strict (every source package) ---
cd backend && .venv/bin/mypy --strict core/ agents/ api/ gateway/
Success: no issues found in 78 source files
--- ruff (zero-tolerance scope) ---
cd backend && .venv/bin/ruff check agents/ gateway/ evals/
All checks passed!
--- ruff (core/ + api/: legacy debt, ratcheted, must not grow) ---
core/ + api/ ruff findings: 0 (ceiling 12)
--- frozen artifacts ---
GOLDENS_OK
CONTRACT_OK (unchanged, or changed with codegen and fixtures)
BRIEFS_IDENTICAL
--- working tree ---
TREE_CLEAN

================ GATE PASSED ================
```

(455 includes this report's two supporting files, `coverage_report.py` and `test_i7_gate.py`, committed alongside it.)

`make gate-f4` result: see §6 — three pre-existing frontend failures, isolated and confirmed unrelated to I7 (git-stash verified against a clean tree), logged in `DEVIATIONS.md` under the 2026-08-15 I7 Task 6 entry. No new failures from this rollout.

## 3. Part A: before / after (Singapore)

**Before** (147,145 places, 8.1% categorized, retrieval sorted by place_id hash with no category filter and a null-island origin):

> Mandai Crematorium Service Hall 4 · HDB Bedok Branch · Jurong Logistics Hub · Little Sunshine Baby Photography (JB) · STAR.LABS Macbook Screen Repair · Singapore Post · Boyz Pub

**After** (11,785 places, category-filtered, distance-ranked from the region centroid):

> Isp Cafe · Syonan Jinja Site · Windsor Park Estate · HSBC Treetop Walk · Singapore Windsor Nature Park · Patisserie G · Astons Specialties · Red Bowl

## 4. Per-city table

| Region | Places | Claims | Size | Category mix | Quality | SHA256 |
|---|---|---|---|---|---|---|
| Singapore (`sg-core`) | 11,785 | 35,355 | 18.6 MB | attraction 4765 · restaurant 3717 · cafe 2157 · park 1000 · food_court 81 · museum 65 | pass | `8bc46012...4a97` |
| Mumbai (`bom-core`) | 12,898 | 38,694 | 20.5 MB | attraction 6787 · restaurant 4227 · cafe 1122 · park 725 · museum 35 · food_court 2 | pass | `52678495...05aa4` |
| Dubai (`dxb-core`) | 7,176 | 21,528 | 11.4 MB | restaurant 3082 · attraction 2306 · cafe 1302 · park 420 · museum 60 · food_court 6 | pass | `82f259b4...034c` |
| New York City (`nyc-core`) | 17,201 | 51,603 | 27.3 MB | restaurant 8777 · attraction 4081 · park 2125 · cafe 1872 · museum 292 · food_court 54 | pass | `b94bc75c...5c1c` |
| London (`lon-core`) | 15,202 | 45,606 | 24.1 MB | cafe 4385 · restaurant 4260 · park 2822 · attraction 3261 · museum 447 · food_court 27 | pass | `d9c34786...ccaa7` |
| Paris (`par-core`) | 9,579 | 28,737 | 15.2 MB | restaurant 4478 · attraction 2033 · park 1048 · cafe 1631 · museum 382 · food_court 7 | pass | `80d6b4c1...798322` |

All six activated independently (`backend/catalogs/active_<id>.json` + `.summary.json` sidecar), all verified disjoint (`test_i7_gate.py::test_all_activated_regions_have_disjoint_place_ids`, `test_region_isolation.py`). All raw extracts and built catalogs are gitignored - not committed, per spec §6.

Full coverage table: `reports/i7_coverage.md`.

## 5. Every threshold or judgment call changed, with justification

All logged in `DEVIATIONS.md` under 2026-08-15, I7 Task 1 through Task 7. Summary:

1. **Manifest checksum repair (Task 1-3 commit).** An earlier commit (`da0640d`, before this session) rewrote `manifest_sg.yaml`'s checksums to values matching no file on disk. Recomputed against the real staged sources.
2. **`catalog_id` required, no deprecated Singapore-default fallback** (`active_catalog_path`).
3. **`SUPPORTED_ROUTES` derives from registered regions, not live catalog-file existence** - the plan's literal text would have broken most of the test suite (autouse mock makes catalog lookups raise by default). Region *support* is a static/product question; region *capability* (is the catalog actually built) is answered separately and dynamically.
4. **Budget-section omission deferred (Task 6).** `FinalReport`'s cost fields stayed required rather than architecturally skipping the four frozen Tier-F pipeline call sites on a speculative basis, before a real unsupported region existed. `RegionCapability` shipped as tested, additive metadata instead.
5. **`_AUTHORITY` in `claims.py` generalized from literal source_ids to provider-family prefixes** (Task 7) - a real bug: Mumbai's correctly-named `overture_bom` source lost all 38,700 claims silently under the old hardcoded `("overture_sg", "osm_sg")` tuple.
6. **`_per_diem_lines` degrades gracefully instead of crashing** (Task 7) - registering Mumbai exposed a real `ValueError` on any actual trip request; fixed to match `_pick_flight`/`_pick_hotel`'s existing graceful-degradation pattern rather than force a currency conversion I7 explicitly forbids adding an FX rate for.
7. **No `_MIN_PER_CATEGORY` per-catalog override needed.** The plan anticipated Mumbai might need loosened category minimums; in practice all six cities passed the shared minimums on their first real build. Not changed.
8. **`max_places`/`max_bytes` raised preemptively for NYC/London/Paris** (80,000 / 200MB vs Singapore's 25,000 / 50MB) given denser metros; real counts came in well under both, no further adjustment needed.

## 6. Everything not done, and why

- **All six catalogs have zero real opening-hours coverage.** `reports/i7_coverage.md` shows 0.0% "hours known" across every region, including Singapore. Singapore's manifest nominally has three sources (Overture + OSM + Wikivoyage), but the OSM/Wikivoyage sources are small synthetic fixtures pointed at a `https://example.invalid/...` URL, not real extracts - they contribute negligible real-world overlap by name/coordinate identity resolution. Mumbai/Dubai/NYC/London/Paris are Overture-only by manifest design (no real OSM/Wikivoyage extract exists in this session; fabricating fixture data pretending to be real would violate the no-fabricated-data principle). Every place in every catalog is `needs_verification` for hours. This is an honest, structural gap, not a shortcut - logged, not hidden.
- **The `attraction` category is over-inclusive in every city**, not just Singapore. Overture's `landmark_and_historical_building` -> `attraction` mapping catches ordinary buildings and housing developments across all six catalogs (e.g. Mumbai's "Lotus Cooperation Society", NYC's "25 Park Row Condos", "49 Chambers"). Visible in every city's retrieval sample gathered during this session. Not fixed - a tuning task, not a structural one, better done with all six catalogs in hand than guessed at per-city.
- **The budget-section-omission mechanism is implemented as metadata only, not as an architectural skip of the estimator/optimizer.** See §5 item 4. `RegionCapability.budget_supported=False` and `known_gaps` are real and tested; the frontend renders them; but a Mumbai/Dubai/NYC/London/Paris trip still runs the full costing pipeline and simply omits the per-diem line (fixed in Task 7) rather than skipping costing outright. This is deliberately conservative around the Tier-F-frozen pipeline graph.
- **`make gate-f4` carries three pre-existing failures**, confirmed unrelated to I7 via git-stash isolation, logged in `DEVIATIONS.md`: a mobile-viewport Playwright timing failure on `/kitchen-sink` (unrelated route), a `TrustChip` contrast ratio (4.35:1 vs required 4.5:1, present since before this session via `assumptions-footer.tsx`/`itinerary-timeline.tsx`), and `maplibre-gl` appearing in the wizard's initial JS chunk. None touched or introduced by this rollout.
- **`worldwide` remains labeled future work**, per the itinerary design doc §14 gate for I7: "coverage scores and known gaps are published; no city silently falls back to Singapore assumptions." Six cities is six cities.

## Self-review (per the plan's checklist)

- `make gate` was run whole, output pasted whole above; no narrower command substituted or reported under its name.
- Every test named for a property executes that property's interesting branch: the authority-fix test uses a real non-`_sg` source_id and asserts the previously-empty result is now non-empty; the per-diem test asserts the previously-crashing call now returns cleanly with the expected assumption; the disjointness test asserts on real counts, not just non-crashing.
- No test started passing because a fixture got smaller or emptier - `test_i7_gate.py`'s anti-vacuity test asserts at least one real catalog was found before any per-catalog assertion runs.
- No synthetic-data path was added to production code; Task 1 removed one instead.
- Every number in this report comes from a command run in this session against artifacts built in this session.
- No currency, FX rate, or per-diem constant was added for any new city (constraint 2) - confirmed by the `_per_diem_lines` fix, which explicitly declines to convert rather than inventing a rate.
- `backend/catalogs/` remains untracked (`git check-ignore` confirmed at each activation).
