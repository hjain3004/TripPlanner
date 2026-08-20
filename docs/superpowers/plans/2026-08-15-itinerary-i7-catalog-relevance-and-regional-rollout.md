# Catalog Relevance Repair → Regional Rollout (I7)

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Steps use checkbox
> (`- [ ]`) syntax. Also required: `superpowers:test-driven-development`,
> `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.

**Goal:** Make the Singapore catalog serve actual venues, then prove the same pipeline produces
honest catalogs for five more cities without any of them silently inheriting Singapore's
assumptions.

**Why Part A exists.** Gate I6 passed and the catalog is real, but retrieval is handing the
planner a crematorium service hall, an HDB branch office and a logistics hub. The gate tests
structure, provenance and determinism — never relevance. Rolling five cities onto that pipeline
would multiply the defect by six and dress it in a passing gate. Part A is corrective work on
Singapore only. **It is independently valuable and independently committable: if this plan runs
out of time after Part A, stop there and report — that is a real result, not a partial one.**

**Architecture:** Part A changes the build filter, the adapter query and the retrieval request.
Part B makes the catalog store per-region rather than one global slot, and adds honest capability
reporting. Part C adds the five cities and per-city evaluation. `backend/core/` learns nothing
about any of it.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, mypy --strict, ruff. DuckDB stays a
system-level manual tool, never a project dependency (spec §10). No new backend dependencies.

---

## Global Constraints

1. **Money goldens are frozen.** `backend/evals/golden/` must not change. If one moves, stop and
   report — something coupled the catalog to the optimizer.
2. **Do not add currencies or FX rates.** Five new cities imply five new currencies, and currency
   conversion is Tier-F money math. This plan adds **no** entry to
   `DESTINATION_CURRENCY_BY_IATA` and **no** FX rate. A region without a verified rate and
   per-diem constants reports capability `partial` — itinerary yes, budget no. See Task 6.
3. **`backend/core/` imports nothing from `agents/`, `api/` or `gateway/`.** Boundary tests
   enforce this.
4. **Raw catalog data and built catalogs are never committed.** Spec §6. Commit manifests,
   SHA256 checksums and quality reports only. `backend/catalogs/` stays gitignored.
5. **Every place in a catalog carries a licence and attribution.** Dropping a record for
   irrelevance is fine; dropping its provenance is not.
6. **`make gate` is the backend gate.** One command, run whole, pasted whole. Do not substitute
   `pytest -q`, `mypy` on a subdirectory, or any narrower target.
7. **Report numbers you measured.** Every count in your final report must come from a command you
   actually ran in this session.

---

## Measured Baseline

Verify every line in Task 0. Measured on `feat/catalog-retrieval-i6` @ `279cd75`, 2026-08-15.

| Metric | Value |
|---|---|
| `make gate` | PASSED |
| backend tests | 411 passed |
| `mypy --strict core/ agents/ api/ gateway/` | clean |
| `ruff agents/ gateway/ evals/` | 0 findings |
| `ruff core/ api/` | 12 (ratcheted ceiling, must not grow) |
| `backend/catalogs/active.json` | 161 MB, 147,145 places, 306,261 claims |
| places carrying a `category` claim | 11,971 (8.1%) |
| places outside a tight SG bbox | 1,894 (1.3%) |
| categorized **and** in Singapore | 11,785 |
| category mix | attraction 4,809 · restaurant 3,812 · cafe 2,192 · park 1,011 · food_court 81 · museum 66 |

The I6 report records "places: 6022 claims: 30110". The activated artifact does not match that.
Do not try to reconcile the two — rebuild in Task 2 and report the new numbers.

---

## Known-Bad Patterns

These are drawn from I3–I6 post-mortems. Each one shipped at least once.

| # | Pattern | What it looked like | Rule |
|---|---|---|---|
| 1 | Verification substitution | ran `mypy --strict agents/discovery/`, reported it as the gate | Run `make gate`. Paste all of it. |
| 2 | Named but not tested | `test_i4_invariance.py` containing zero permutations | A test named for a property must execute the interesting branch. Prove it. |
| 3 | Scope truncation with confident closure | Tasks 7–8 undone, "Phase I5 complete" | Report per-task status. Unfinished is a fine answer; "complete" when it isn't, is not. |
| 4 | Stub-and-declare | `hasattr(llm, "execute_planner")` guarding a method defined nowhere | `evals/test_no_stubs.py` guards prose. It cannot see a synthetic-data branch. Do not add one. |
| 5 | Gate passes, product broken | I6: 411 green tests over a catalog of crematoria | A structural gate is not a quality gate. Task 3 adds the quality assertion. |
| 6 | Reported numbers that don't match the artifact | "6022 places" vs 147,145 on disk | Print the number from the artifact you actually built, in the same command run. |
| 7 | Blanket suppressions | 14 `# ruff: noqa` in one I4 commit | No blanket suppressions. A `per-file-ignores` entry with a written justification is the only accepted form. |

---

## Task 0: Preflight

- [ ] `git status --porcelain` — must be empty. If not, stop and report.
- [ ] `git log --oneline -1` — confirm `279cd75`.
- [ ] Run `make gate` from the repo root. Confirm `GATE PASSED` and 411 tests.
- [ ] Re-measure every row of the baseline table above. If any differs, **stop and report the
      difference before changing anything.**
- [ ] `ls -la backend/catalogs/` and confirm `active.json` is untracked
      (`git check-ignore -v backend/catalogs/active.json`).
- [ ] Create branch `feat/i7-regional-rollout` from the current HEAD.

---

# PART A — Make Singapore actually work

## Task 1: Remove the synthetic-catalog branch from `build.py`

`backend/gateway/catalog/build.py` contains, in production code:

```python
source_is_mock = False
# Mocking for tests
if not raw_claims:
    source_is_mock = True
    ...fabricates places pl_1..pl_N with coordinates {"lat": 1, "lon": 1}
       until _MIN_PER_CATEGORY is satisfied...
```

A manifest whose sources yield zero claims — wrong release, empty extract, changed schema, failed
download — produces a catalog of invented places at latitude 1 that **passes the quality gate**.
Part C points five new manifests at this function.

- [ ] Write the failing test first, in `backend/evals/test_catalog_build_integrity.py`:
      `test_a_manifest_yielding_no_claims_refuses_to_build` — build from a manifest whose staged
      sources contain no usable records; assert it raises, and assert the exception message names
      the source that produced nothing.
- [ ] Add `test_no_place_is_fabricated`: build from the small fixture manifest and assert every
      resulting `place_id` traces to an `external_id` present in the staged input. Include the
      anti-vacuity assertion — assert the fixture produced more than zero places, so the test
      cannot pass by checking an empty list.
- [ ] Delete the `source_is_mock` branch and the `fail_quality` parameter's synthetic path. Raise
      `CatalogBuildError` (new, in `build.py`) when `raw_claims` is empty.
- [ ] The tests that relied on the mock branch must now construct their fixtures explicitly.
      Find them with `grep -rn "fail_quality\|source_is_mock" backend/evals/`. Fixing a test by
      re-adding a synthetic path to production code is the failure this task exists to prevent.
- [ ] Extend `STUB_MARKERS` in `backend/evals/test_no_stubs.py` with `r"mocking for tests"` and
      `r"^\s*#\s*mock\b"`. Confirm the guard would have caught this branch by running it against
      the pre-fix file (temporarily, then revert).
- [ ] `make gate`. Commit: `fix(catalog): refuse to build a catalog from zero claims`.

## Task 2: Filter the catalog to relevant, in-scope places

11,971 of 147,145 places carry a category. The rest are shops, offices, ATMs and bus stops that no
itinerary will ever schedule. They are 92% of the file and 100% of the relevance problem.

- [ ] Add to `CatalogManifest` (`gateway/catalog/manifest.py`) an optional per-catalog
      `bbox: BoundingBox | None` (`min_lon`, `min_lat`, `max_lon`, `max_lat`) and
      `max_places: int`. Populate them for `manifest_sg.yaml` with the tight Singapore bbox
      (103.6, 1.20, 104.09, 1.48) and a cap of 25,000.
- [ ] In `build.py`, after claim normalization and before identity resolution, drop any place that
      (a) has no `category` claim, or (b) has coordinates outside the manifest bbox. Record both
      counts in `QualityReport` as `dropped_uncategorized` and `dropped_out_of_bbox`.
- [ ] Failing test first, `test_catalog_build_integrity.py::test_out_of_bbox_places_are_dropped`:
      stage a fixture containing one in-bbox and one out-of-bbox place, assert only the first
      survives and that `dropped_out_of_bbox == 1`.
- [ ] `test_uncategorized_places_are_dropped`, same shape.
- [ ] Add to `evaluate_quality`: fail if `len(places) > manifest.max_places`. A catalog that
      exceeds its declared cap is a manifest bug, not something to activate.
- [ ] Rebuild the real Singapore catalog. **This is the one networked step in the plan** — it
      re-runs the manual DuckDB extract. Record: place count, claim count, category mix, file size
      in MB, and the SHA256 of the artifact.
- [ ] Expected: ~11,785 places, roughly 13 MB. If you get materially different numbers, report
      them rather than tuning the filter until they match.
- [ ] `make gate`. Commit: `feat(catalog): drop uncategorized and out-of-bbox places at build time`.

## Task 3: Make retrieval ask for what it needs

`agents/retrieval.py:132` issues `PlaceSearchRequest(origin_lat=0, origin_lon=0, max_results=limit,
timeout_ms=5000, destination_area_id="")` — no category filter, null-island origin. And
`SnapshotPlaceAdapter.search_places` ignores `origin_lat`/`origin_lon` entirely, returning
`filtered[:max_results]` sorted by `place_id`. The 40 candidates are an arbitrary hash-ordered
slice.

- [ ] Failing test first, `backend/evals/test_retrieval_relevance.py`:
      `test_every_candidate_has_a_supported_category`. Build a catalog fixture containing both
      categorized venues and (via direct construction, not via `build_catalog`) uncategorized
      records; assert retrieval returns only the former. Anti-vacuity: assert the fixture
      contained at least one of each, so the test cannot pass on an all-clean fixture.
- [ ] `test_candidates_are_ordered_by_distance_from_origin`: two venues at known distances,
      assert the nearer one ranks first. Then assert that permuting the input order does not
      change the output order — the I4 invariance property, applied here.
- [ ] Implement geographic filtering in `SnapshotPlaceAdapter.search_places`: when
      `origin_lat`/`origin_lon` are supplied, sort by haversine distance and apply
      `max_results` after sorting, not before. Keep `place_id` as the deterministic tiebreak.
- [ ] In `retrieve_candidates`, pass `category_filters=list(SUPPORTED_CATEGORIES)` and a real
      origin. The origin is the trip's base location; where `TripSpec` has no hotel coordinate
      yet, use the destination city centroid from the catalog manifest (new field
      `centroid_lat`/`centroid_lon`). Do not use `0, 0`.
- [ ] Add the relevance assertion to the quality report so this cannot silently regress: a
      catalog activates only if ≥95% of its places carry a supported category.
- [ ] Print the top 40 candidates retrieval now returns for a Singapore trip. Paste them in your
      report. They should read as venues a person would visit.
- [ ] `make gate`. Commit: `fix(retrieval): filter candidates by category and rank by distance`.

**Part A checkpoint.** Report the before/after candidate lists side by side, catalog size before
and after, and the gate result. If time runs out here, stop — this is a complete, valuable
change set. Part B begins a new concern.

---

# PART B — Make the catalog multi-region

## Task 4: Per-region catalog addressing

`activate()` writes to `catalog_root / "active.json"` — one global slot. `build_catalog` hardcodes
`catalog_id="cat_1"` and `catalog_release="2026-08-01"`, discarding the manifest's real values
(`load_manifest` returns only `.sources`).

- [ ] Change `load_manifest` to return the full `CatalogManifest`, not just its sources. Fix all
      call sites.
- [ ] `build_catalog` uses `manifest.catalog_id` and `manifest.catalog_release`. Delete the
      hardcoded literals.
- [ ] `activate()` writes `catalog_root / catalog_id / "active.json"`; `active_catalog_path`
      takes a `catalog_id`. Preserve atomic replace-within-filesystem semantics.
- [ ] Add `list_active_catalogs(catalog_root) -> list[CatalogSummary]` returning id, release,
      place count and quality status for each activated catalog.
- [ ] Failing test first: two catalogs activate independently, and activating the second does not
      disturb the first. Assert on both files' contents, not just their existence.
- [ ] `make gate`. Commit: `feat(catalog): address catalogs by region id`.

## Task 5: Region resolution replaces the Singapore constants

Every one of these is a Singapore assumption that a second city inherits silently:

| File | Line | Constant |
|---|---|---|
| `agents/retrieval.py` | 11 | `CITY_BY_IATA = {"SIN": "Singapore"}` |
| `agents/retrieval.py` | 48 | `timezone="Asia/Singapore"` on every mapped POI |
| `agents/retrieval.py` | 42 | `currency="INR"` on every mapped POI |
| `agents/retrieval.py` | 115 | `Path("catalogs")` — the global slot |
| `agents/intake.py` | 9 | `SUPPORTED_ROUTES = {("DEL","SIN"), ("BOM","SIN")}` |
| `agents/estimator.py` | 23 | `DESTINATION_CURRENCY_BY_IATA = {"SIN": "SGD"}` |

- [ ] Create `backend/gateway/catalog/regions.py` with a `Region` model: `iata`, `city_name`,
      `country_code`, `timezone`, `catalog_id`, `centroid_lat`, `centroid_lon`, `currency`,
      and `budget_supported: bool`. Load it from `gateway/catalog/fixtures/regions.yaml`:

```yaml
- iata: SIN
  city_name: Singapore
  country_code: SG
  timezone: Asia/Singapore
  catalog_id: sg-core
  centroid_lat: 1.3521
  centroid_lon: 103.8198
  currency: SGD
  budget_supported: true
```

- [ ] `retrieve_candidates` resolves the region from `spec.destination_city` and uses its
      timezone, centroid and catalog id. A destination with no region entry raises a typed
      "unsupported region" result — it does not fall back to Singapore. **Write that test first
      and name it `test_an_unknown_destination_does_not_get_the_singapore_catalog`.**
- [ ] `SUPPORTED_ROUTES` derives from which catalogs are actually activated, not a literal set.
      An origin/destination pair is supported when the destination's region has an active catalog.
- [ ] `budget_supported` is `false` for every region except Singapore. Do not add currencies or
      FX rates — see Global Constraint 2.
- [ ] `make gate`. Commit: `feat(agents): resolve destination region instead of assuming Singapore`.

## Task 6: Honest capability reporting

- [ ] Add `RegionCapability` to the agents contract: `region`, `catalog_status`
      (`active` / `absent` / `stale`), `place_count`, `budget_supported`, `known_gaps: list[str]`.
- [ ] The pipeline attaches the resolved region's capability to its result. When
      `budget_supported` is `false`, the costed-budget section is **absent with a stated reason**,
      not zero-filled and not estimated with Singapore per-diems.
- [ ] Contract change: schema + `contract/openapi.json` + regenerated client + MSW fixtures + UI
      in **one commit** (spec 12 §8). `make gate`'s `CONTRACT_OK` check enforces this.
- [ ] Frontend renders the partial state using the existing evidence/trust language. Do not invent
      a new "unsupported" visual — reuse `verify_required` styling conventions.
- [ ] Failing test first: a Mumbai trip returns an itinerary and **no** budget block, with a
      `known_gaps` entry naming the missing FX rate.
- [ ] `make gate` **and** `make gate-f4`. Commit: `feat(contract): report per-region capability`.

---

# PART C — Roll out the cities

## Task 7: Second city — Mumbai

Mumbai first, alone, because the second city is where every hidden Singapore assumption surfaces.
Cities three through six are then repetition.

- [ ] Write `gateway/catalog/fixtures/manifest_bom.yaml`: pinned Overture release, Mumbai bbox,
      `max_places`, centroid, licence and attribution per source. Same schema as `manifest_sg.yaml`.
- [ ] Extend `scripts/fetch_overture_sg.py` into `scripts/fetch_overture.py`, parameterized by
      manifest. **It must execute the DuckDB query, not print it** — the current script only
      `print()`s, which is why its output was never checksummed against a real run. Keep it manual
      and offline; it stays out of tests and CI.
- [ ] Build, quality-gate and activate the Mumbai catalog. Record place count, category mix, size,
      SHA256, and the top 40 retrieval candidates.
- [ ] Add `evals/test_region_isolation.py`: a Mumbai trip returns zero Singapore places and vice
      versa. Anti-vacuity — assert both catalogs are non-empty first.
- [ ] Report every place the Mumbai build revealed as a Singapore-shaped assumption. Expect at
      least the category minimums: `_MIN_PER_CATEGORY` requires 2 `food_court`, which is a
      Singapore concept. If a minimum blocks Mumbai, move the minimums into the manifest
      per-catalog rather than lowering Singapore's. Log it in `DEVIATIONS.md` as Tier C.
- [ ] `make gate`. Commit: `feat(catalog): add Mumbai region`.

## Task 8: Remaining four — Dubai, New York City, London, Paris

- [ ] One manifest, one build, one commit per city. Do not batch them: a batched failure tells you
      nothing about which city broke.
- [ ] For each: place count, category mix, size, SHA256, quality report, top 40 candidates.
- [ ] Any city that fails its quality gate stays **unactivated** and is reported as
      `catalog_status: absent` with its failures listed. A city that cannot pass is an honest
      result. Lowering a threshold to make it pass is not — and if you do tune a Tier-C threshold,
      it needs a `DEVIATIONS.md` row with the measured evidence that motivated it.
- [ ] Expect Paris and London to stress `max_places`. Raising a cap is fine; record the new size.

## Task 9: Coverage report and Gate I7

- [ ] Write `backend/evals/coverage_report.py` producing `reports/i7_coverage.md`: one row per
      region with place count, category mix, coordinate coverage, hours coverage, contradiction
      count, budget support, and known gaps. Deterministic output — no wall-clock timestamps.
- [ ] Add `evals/test_i7_gate.py` asserting, per activated region: ≥95% categorized, 100% inside
      the declared bbox, 100% of claims carrying a licence, zero places without coordinates, and
      that region isolation holds.
- [ ] Run the full gate:

```bash
make gate && make gate-f4
```

- [ ] Write `reports/itinerary_i7_regional_rollout.md` with: the measured baseline, every task's
      outcome, per-city numbers, the before/after Singapore candidate lists from Part A, every
      Tier-C threshold you tuned and why, and every gap you are leaving open.
- [ ] `worldwide` remains labeled future work. Six cities is six cities.

---

## Final Response Requirements

Your report must contain, in this order:

1. **Per-task status** — one line each, `done` / `partial` / `not started`. Partial is an
   acceptable answer. "Complete" for anything not fully done is not.
2. **Full `make gate` output**, pasted whole, including the `GATE PASSED` line. If you ran any
   narrower command during development, that is fine — but the gate output is what you report.
3. **The Part A before/after candidate lists**, side by side.
4. **Per-city table**: places, claims, size MB, category mix, quality pass/fail, SHA256.
5. **Every threshold you changed**, with the measurement that justified it and its
   `DEVIATIONS.md` row.
6. **Everything you did not do**, and why.

Do not push. Do not open a PR. Report and stop.

---

## Self-Review Notes

Before reporting, check each of these against your own work:

- Did I run `make gate`, whole, or did I run something narrower and report it as the gate?
- Does every test named for a property actually execute that property's interesting branch?
- Did any test start passing because a fixture got smaller or emptier?
- Did I add any synthetic-data path to production code to make a test pass?
- Do the numbers in my report come from commands I ran in this session, against the artifacts I
  actually built?
- Did I add a currency, an FX rate, or a per-diem constant for a new city? (Constraint 2 — the
  answer must be no.)
- Is `backend/catalogs/` still untracked?
