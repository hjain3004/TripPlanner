# Catalog Build → Retrieval Wiring → I6 Vertical Slice

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Steps use checkbox
> (`- [ ]`) syntax. Also required: `superpowers:test-driven-development`,
> `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.

**Goal:** Make the app actually work end to end — a real Singapore catalog feeding the planner,
and the existing frontend rendering a real backend response instead of fixtures.

**Why these three together:** I6 renders whatever retrieval supplies. Today retrieval serves the
4 seeded POIs, so I6 alone would build a polished UI over the same four venues the project has had
since M1. Everything I3/I4/I5 built sits behind a seam nothing crosses. Parts A and B cross it.

**Architecture:** Part A runs the existing I3 ingestion for real (manual, offline, network — the
only networked step in this plan). Part B adds a mapping layer in `agents/` that turns
`SnapshotPlaceAdapter` output into `RetrievalContext`; `core/` never learns the catalog exists.
Part C ships schema + codegen + MSW + UI in one change set per spec 12 §8.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, mypy --strict, ruff · Next.js, TypeScript,
MSW, Playwright, MapLibre GL JS. No new backend dependencies.

---

## Global Constraints

1. **Money goldens are frozen.** `backend/evals/golden/` must not change. POI data does not touch
   card/points math — those run on `core/seeds/sample_flights.yaml` and `sample_hotels.yaml`. If a
   money golden moves, stop and report: something coupled the composer to the optimizer.
2. **`backend/core/` imports nothing from `agents/`, `api/` or `gateway/`.** The catalog mapping
   lives in `agents/retrieval.py`, which may import `gateway/`. Boundary tests enforce this.
3. **Raw catalog data is not committed.** Spec §6: "Raw data and generated catalogs are not
   committed unless their licence and size policy explicitly permits it." Commit the manifest,
   the SHA256 checksums and the quality report — never the Overture extract or `active.json`.
4. **Never compute money, points, travel or trust in the browser.** Render fields. Spec §14 I6.
5. **No localStorage/sessionStorage.** `CLAUDE.md` repo boundaries.
6. **Attribution renders.** ODbL for OSM-derived data, CC BY-SA for Wikivoyage, Overture's own
   notice. Spec §11: "Attribution is data, not footer prose added at the end."
7. **`make gate` is the backend gate.** One command. Do not substitute narrower ones.
8. **Report numbers you measured.**

---

## Measured Baseline

Verify in Task 0. Measured on `feat/i5-agentic-discovery` @ `c6b455d`, 2026-08-14.

| Metric | Value |
|---|---|
| `make gate` | **GATE PASSED** |
| `pytest -q` | 396+ passed |
| `mypy --strict core/ agents/ api/ gateway/` | clean, 77 files |
| `ruff agents/ gateway/ evals/` | zero |
| `ruff core/ api/` | 12, ratcheted |
| Seeded POIs | **4** |
| Active catalog | **none** |
| `agents/retrieval.py` catalog references | **none** |

---

## Known-Bad Patterns

Full table in `2026-08-11-itinerary-i3-open-data-catalog.md`. The recurring three:

- **A narrower command reported under the gate's name.** Five phases. `make gate` now exists
  precisely so there is nothing to narrow. Run it. Paste all of it.
- **A test named for a property it does not test.** I4's invariance file had zero permutations;
  I3's shuffle test never merged. Prove the interesting branch runs.
- **An announced stub.** `evals/test_no_stubs.py` now fails the build on placeholder prose, and
  `KNOWN_GAPS` is empty. Keep it empty.

**Red-then-green is mandatory.** Write the test, run it, **paste the failure**, then implement.

---

## Task 0: Preflight

- [ ] **Step 1: Confirm the baseline**

```bash
cd /Users/himanshu_jain/TripPlanner
git status --short          # empty
make gate                   # GATE PASSED
```

If the gate is red, stop and report — do not build on it.

- [ ] **Step 2: Merge I5 and branch**

```bash
git checkout main && git merge feat/i5-agentic-discovery
make gate                   # still GATE PASSED
git checkout -b feat/catalog-retrieval-i6
```

Report the merge result. Do not push.

---

# PART A — Build the real catalog

## Task 1: Fetch and activate a Singapore catalog

**This is the only networked step in the plan.** It is manual, offline, and outside the test
suite — nothing here runs in CI or in `make gate`.

**Files:** run `scripts/fetch_overture_sg.py`; update
`backend/gateway/catalog/fixtures/manifest_sg.yaml`; create `reports/catalog_sg_build.md`

- [ ] **Step 1: Check the prerequisite**

```bash
duckdb --version || echo "DuckDB not installed — see scripts/fetch_overture_sg.py header"
```

DuckDB is deliberately **not** a project dependency (spec §10 extension attack surface stays out
of the tested pipeline). If it is absent, install it system-wide or report that you cannot proceed
— do not add it to `pyproject.toml`.

- [ ] **Step 2: Fetch a pinned Singapore slice**

Run the script. Bound it to a Singapore bbox (roughly `lon 103.6–104.1`, `lat 1.15–1.48`) and the
Overture `places` theme. Record the exact release you pulled — the catalog is only reproducible if
the release is pinned.

**Zero-spend check:** Overture is on a free public bucket. If anything prompts for credentials or
payment, stop and report. Positive external spend fails closed.

- [ ] **Step 3: Checksum and pin**

```bash
cd backend/gateway/catalog/fixtures
shasum -a 256 <the fetched files>
```

Update `manifest_sg.yaml` with the real checksums, the real `source_release`, and the real
`source_url`. Every spec §11 field must be filled: licence, geographic scope, allowed purpose,
attribution text.

- [ ] **Step 4: Build and activate**

```bash
cd /Users/himanshu_jain/TripPlanner/backend
.venv/bin/python -c "
from pathlib import Path
from gateway.catalog.build import build_catalog
from gateway.catalog.activate import activate, active_catalog_path
a = build_catalog(Path('gateway/catalog/fixtures/manifest_sg.yaml'), Path('<raw dir>'), Path('.work'))
print('places:', len(a.places), 'claims:', len(a.claims), 'quality passed:', a.quality.passed)
print('failures:', a.quality.failures)
activate(a, Path('catalogs'))
print('active:', active_catalog_path(Path('catalogs')))
"
```

**Paste that output.** If `quality.passed` is False, paste `failures` and report — do not lower
the thresholds to make it pass. Per-category minimums exist so the itinerary can actually be
composed.

- [ ] **Step 5: Prove reproducibility on real data**

Build twice into different work directories and compare `canonical_json`. Gate I3 asserted this on
12 synthetic rows; real data is where it counts.

- [ ] **Step 6: Commit the manifest, not the data**

Add `backend/catalogs/` and the raw extract directory to `.gitignore`. Commit only
`manifest_sg.yaml` and `reports/catalog_sg_build.md` (place count by category, licence coverage,
the two build hashes, the Overture release).

```bash
git commit -m "feat(catalog): pin and build the real Singapore catalog"
```

---

# PART B — Wire the catalog into retrieval

## Task 2: Map catalog places into RetrievalContext

**Files:** Modify `backend/agents/retrieval.py`; Test `backend/evals/test_retrieval_catalog.py`

`agents/retrieval.py` currently reads `core.db.KnowledgeBase` and formats POI rows as strings via
`_poi_row`. It gains a second source. **`core/` must not learn the catalog exists** — the mapping
lives here, in `agents/`.

- [ ] **Step 1: Write the failing tests**

```python
def test_catalog_places_reach_the_retrieval_context(active_catalog) -> None:
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    assert len(ctx.poi_rows) > 4, "still serving only the seeded POIs"


def test_seeded_pois_and_catalog_places_coexist_without_duplicates(active_catalog) -> None:
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    ids = [r.split("|")[0].strip() for r in ctx.poi_rows]
    assert len(ids) == len(set(ids))


def test_a_catalog_place_without_hours_is_marked_verify_required(active_catalog) -> None:
    """Spec 5.4 survives the mapping — unknown hours never become open."""
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    rows = [r for r in ctx.poi_rows if "verify" in r.lower()]
    assert rows


def test_provenance_survives_the_mapping(active_catalog) -> None:
    ctx = retrieve_candidates(spec, kb, catalog=active_catalog)
    assert all(r.licence_id for r in ctx.poi_provenance)


def test_retrieval_falls_back_to_seeds_when_no_catalog_is_active(tmp_path) -> None:
    """Spec 12: a missing catalog degrades, it does not crash."""
    ctx = retrieve_candidates(spec, kb, catalog=tmp_path / "absent.json")
    assert len(ctx.poi_rows) == 4


def test_core_still_does_not_import_gateway() -> None:
    """The mapping belongs in agents/. Existing boundary tests must stay green."""
    from pathlib import Path

    from evals.test_catalog_boundary import _imports
    assert _imports(Path(__file__).parent.parent / "core", {"gateway", "agents", "api"}) == []
```

- [ ] **Step 2-4: red, implement, green, commit**

```bash
git commit -m "feat(agents): serve catalog places through retrieval"
```

## Task 3: Absorb what real data breaks

Twelve synthetic rows did not exercise real-world mess. Expect failures here — that is the point
of this task, not a sign something went wrong.

- [ ] **Step 1: Run the planner against the real catalog and record what breaks**

```bash
cd backend && .venv/bin/python -m core.optimizer demo
.venv/bin/pytest -q
```

Likely: unparseable OSM `opening_hours` strings (`"Mo-Su 05:00-02:00"`, `"24/7"`,
`"sunrise-sunset"`), places with no coordinates, categories outside `SUPPORTED_CATEGORIES`, names
in scripts the row formatter did not anticipate.

- [ ] **Step 2: For each failure, write a test with the real offending value, then fix**

Take the actual string from the catalog. Do not invent a tidy fixture — the value that broke it is
the value the test needs.

**Unknown hours never become open** (carried from I1/I3). A venue whose hours cannot be parsed is
`verify_required`, and excluded if timing-critical.

- [ ] **Step 3: `test_demo_output.py` will change.** The itinerary text now names real venues.
  That is expected. Update the fixture **in this commit only** and quote the before/after diff.
  **Money goldens must not move** — if they do, stop and report.

```bash
git commit -m "fix(core): handle real-world hours, categories and coordinate gaps"
```

---

# PART C — I6 vertical slice

## Task 4: Teach the gate the one-PR rule

`make gate` currently freezes `contract/openapi.json`. Correct for I0–I5, wrong for I6. **Do not
delete the check** — replace the freeze with the invariant spec 12 §8 actually wants.

**Files:** Modify `Makefile`; Test `backend/evals/test_contract_one_pr.py`

- [ ] **Step 1: Write the failing test**

```python
def test_a_contract_change_ships_with_its_generated_client_and_fixtures() -> None:
    """Spec 12 section 8: schema, codegen, MSW fixtures and UI ship in ONE commit.
    Split PRs are the drift vector."""
    changed = git_changed_files_in_head()
    if "contract/openapi.json" not in changed:
        return
    required = ["frontend/src/lib/api/", "frontend/src/mocks/handlers.ts"]
    missing = [r for r in required if not any(c.startswith(r) for c in changed)]
    assert not missing, f"contract changed without {missing} in the same commit"
```

- [ ] **Step 2-4:** red, implement, green. Update the Makefile so `CONTRACT_OK` means "unchanged,
  **or** changed together with codegen and fixtures," and say so in the target's comment.

```bash
git commit -m "build: gate the contract one-PR rule instead of freezing the schema"
```

## Task 5: Extend the contract for itinerary evidence

**Files:** `contract/openapi.json`, `backend/api/main.py`, generated client,
`frontend/src/mocks/handlers.ts`

Everything in this task ships in **one commit**.

- [ ] **Step 1: Write the failing contract test**, then extend the schema so each itinerary item
  carries what the UI must render without computing anything:

```
place_id · name · start/end · category
travel_from_previous { duration_min, status: routed|estimated, source }
evidence { status: live|cached|estimated|stale|verify_required,
           last_verified, licence_id, attribution, needs_verification }
day-level: unmet_needs[], rejections[{ code, place_id, detail }]
```

- [ ] **Step 2: Regenerate the client and update MSW fixtures in the same commit.**

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(contract): carry itinerary evidence and route provenance"
```

## Task 6: Render itinerary, provenance and partial days

**Files:** `frontend/src/app/plan/`, components; Test `frontend/e2e/i6-itinerary.spec.ts`

- [ ] **Step 1: Write the failing e2e tests**

```ts
test("an estimated travel time is never labelled as routed", async ({ page }) => {
  await expect(page.getByTestId("travel-0")).toContainText(/estimated/i);
});

test("a verify-required venue shows its badge, not a silent gap", async ({ page }) => {
  await expect(page.getByTestId("evidence-badge").first()).toBeVisible();
});

test("a partial day states why, in structured terms", async ({ page }) => {
  await expect(page.getByTestId("day-unmet")).toContainText(/travel budget|no candidate/i);
});

test("no storage is written", async ({ page }) => {
  const n = await page.evaluate(() => localStorage.length + sessionStorage.length);
  expect(n).toBe(0);
});
```

- [ ] **Step 2-4: red, implement, green, commit.** Preserve the issued-document visual language —
  do not introduce a generic map UI. Trust badges are never styled away (non-negotiable #3).
  The browser renders fields; it computes no money, points, travel or trust value.

```bash
git commit -m "feat(frontend): render itinerary evidence and partial-day reasons"
```

## Task 7: MapLibre with accessible list parity

**Files:** `frontend/src/components/map/`; Test `frontend/e2e/i6-a11y.spec.ts`

- [ ] **Step 1: Write the failing tests**

```ts
test("the itinerary is fully usable with the map absent", async ({ page }) => {
  await page.route("**/*.pbf", r => r.abort());
  await expect(page.getByRole("list", { name: /itinerary/i })).toBeVisible();
  await expect(page.getByRole("listitem")).toHaveCount(await expectedStops());
});

test("keyboard reaches every stop without entering the map canvas", async ({ page }) => {
  /* tab through the itinerary list; assert focus never lands inside the canvas */
});

test("map attribution is present and not visually suppressed", async ({ page }) => {
  const a = page.getByTestId("map-attribution");
  await expect(a).toBeVisible();
  await expect(a).toContainText(/OpenStreetMap|Overture/);
});

test("popups render sanitized React content, never provider HTML", async ({ page }) => {
  /* assert no dangerouslySetInnerHTML path and no provider markup in the DOM */
});
```

List parity is **not** a degraded mode — spec §14 I6 requires the itinerary to work by keyboard and
screen reader with the map absent entirely.

- [ ] **Step 2-4: red, implement, green, commit**

```bash
git commit -m "feat(frontend): add MapLibre rendering with accessible list parity"
```

## Task 8: Live run and Gate I6

**Files:** `reports/itinerary_i6_vertical_slice.md`; `DEVIATIONS.md`, `CLAUDE.md`, `AGENTS.md`

- [ ] **Step 1: Run it for real**

```bash
cd backend && .venv/bin/uvicorn api.main:app --port 8000 &
cd frontend && NEXT_PUBLIC_API_MODE=live npm run dev
```

`NEXT_PUBLIC_API_MODE` already gates MSW (`frontend/src/mocks/MSWProvider.tsx:9`) — anything other
than `mock` disables the mocks. Plan a real Singapore trip through the UI against the real backend.

**Paste the venue names that appear.** If they are Gardens by the Bay, Marina Bay Sands SkyPark,
Maxwell Food Centre and Skyline Luge Sentosa, Part B did not land and the phase is not done.

- [ ] **Step 2: Screenshot it.** Attach to the report.

- [ ] **Step 3: Gate I6**

```bash
cd /Users/himanshu_jain/TripPlanner
make gate
make gate-f2
cd frontend && npx playwright test i6-itinerary.spec.ts i6-a11y.spec.ts --config=e2e/playwright.config.ts
node scripts/token-lint.mjs
npx vitest run tests/contrast.test.ts tests/contract.test.ts
```

| Check | Required |
|---|---|
| `make gate` | GATE PASSED |
| Backend tests | > baseline, all passing |
| Money goldens | **unchanged** |
| Contract | changed **with** codegen + MSW in one commit |
| Frontend typecheck / token-lint / contrast | clean |
| i6 e2e (itinerary + a11y) | passing |
| Live run | real catalog venues, screenshotted |
| `AGENTS.md` ≡ `CLAUDE.md` | identical |
| Tree | clean |

- [ ] **Step 4:** DEVIATIONS rows, I6 checkpoint in both briefs, write the report, commit.

**Do not push. Do not open a PR.**

---

## Final Response Requirements

1. Task 0 baseline and merge result, pasted.
2. **Task 1 Step 4 output** — place count, quality pass/fail, and the two build hashes.
3. **Task 3's list of real-data failures** and the actual offending values you turned into tests.
4. The `test_demo_output.py` before/after diff.
5. **Task 8 Step 1's venue names** — the proof Part B landed.
6. Per task: pasted red phase, green phase, test-count delta, commit sha.
7. Full `make gate` output, raw.
8. Anything incomplete, stated plainly.

---

## Self-Review Notes

Spec coverage: §6 ingestion and packaging (Task 1) · §5.4 freshness through the mapping (Task 2) ·
§12 partial results and missing-catalog degradation (Tasks 2, 6) · §11 attribution rendered
(Task 7) · §14 Gate I6 — contract drift (Task 4), keyboard/screen-reader without the map (Task 7),
storage policy and no browser computation (Task 6), frontend gates (Task 8).

**Deferred to I7:** every non-Singapore catalog. This plan proves one city end to end.

**Not in scope:** flight/hotel providers. The kernel keeps using `sample_flights.yaml` and
`sample_hotels.yaml` — that is the separate G-track, and nothing here touches money math.

**Expect Task 3 to be the long one.** Real hours strings, missing coordinates and unmapped
categories are where twelve synthetic fixture rows stop being representative. Budget for it.
