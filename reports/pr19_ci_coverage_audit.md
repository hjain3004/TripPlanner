# PR #19 — backend CI vs local test-count discrepancy audit

Read-only investigation. No application, CI, spec, seed, golden, OpenAPI, or
frontend code was changed. The only repository write is this report.

## Question

Explain why PR #19's backend suite reports different numbers locally and in CI:

- **Local gate:** `2615 passed, 1 skipped, 3 warnings`
- **CI backend:** `2569 passed, 27 skipped`

…and determine, with collection and execution evidence, whether the difference
is intentional optional coverage or a meaningful coverage gap — without assuming
it is harmless or catalog-caused.

## Short answer

The difference is **entirely and exactly** accounted for by whether the
untracked **regional place catalogs** (`backend/catalogs/active_*-core.json`,
~140 MB, Overture-derived, deliberately git-ignored) are provisioned on the
machine running the suite. It is **intentional, documented, env-gated optional
coverage**, not a gap in PR #19's own coverage:

- CI (no catalogs) **skips** 26 catalog-dependent tests and **1** unrelated
  guard, honestly and visibly, and fails the job if any *non*-catalog skip
  beyond that single known one appears.
- The local `make gate` runs on a **provisioned** machine
  (`TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1`), so those 26 tests **run and pass**
  instead of skipping, which is the 46-test passed-count delta.
- **Every test that PR #19 actually adds** (FI2 ingestion/extraction/parsing/
  validation and the G3b/OpenBnB offline adapter) is hermetic and offline, was
  **collected and passed in CI**, and appears nowhere in the skip list.

The two runs are the same code at effectively the same tree; only the data
environment differs. No required ingestion, parser, or G3b check was missing in
CI.

## 1. Exact revisions

| Role | Commit | Note |
|---|---|---|
| **Target / PR #19 merge commit** | `3471747457968b3d1b3ceb392576d010ec9caed7` | `Merge pull request #19 …`; the commit this audit is pinned to |
| Base (parent¹, prior `main`) | `6428b78d173e8b191889c0d6cd3c8bd7ea9df21f` | PR #18 (`fi1-snapshot-core`) merge |
| PR branch tip (parent², `codex/integrate-fi2-g3b-instagram`) | `6c348af89a236ca800d022e1932c1cc558790d7c` | `docs: finalize integration evidence` |

Evidence: `git log -1 3471747` (parents `6428b78 6c348af`); `gh pr view 19`
(`headRefOid=6c348af`, `mergeCommit.oid=3471747`, `state=MERGED`).

- **CI tested revision:** the `pull_request` event checked out GitHub's merge
  ref for head `6c348af` onto base `main`. The resulting tree is the PR #19
  merge — i.e. the target `3471747`. CI run `40409454628`, backend job
  `121875903527`, `event=pull_request`, `headSha=6c348af`,
  `conclusion=success`.
- **Local tested revision:** the integration report
  (`reports/integration_fi2_g3b_instagram.md`, present at the target, absent on
  `main`) records the `make gate` figure as measured in the integration
  worktree on the committed clean tree, i.e. the same integrated content.

> Evidence gap (stated, not reconstructed): I did **not** perform a present-day
> local full-suite run. This worktree is checked out `--no-checkout` because the
> host disk was full (≤ ~2 GiB free) and the regional catalogs are not
> provisioned here. The `2615 / 1` local figure is quoted from the committed
> integration report, **not** independently reproduced in this session. A
> present-day reproduction would in any case not prove the historical
> environment. The CI figure, by contrast, is read directly from the archived
> job log and is authoritative.

## 2. Commands, Python, dependencies, markers, paths

### CI (`.github/workflows/ci.yml`, job `backend`, at `3471747`)

- Runner: `ubuntu-24.04`. Python **3.14** → resolved to **CPython 3.14.8**
  (log: "Successfully set up CPython (3.14.8)").
- Dependencies: `python -m venv backend/.venv` then
  `pip install --require-hashes -r backend/requirements-dev.lock` (hash-pinned).
- Seed: `make seed` (`python -m core.db seed`).
- Test command (working dir `backend/`):
  `.venv/bin/pytest -q -rs -p no:cacheprovider`.
  - **No `-m` marker filter**, **no path arguments** → the default
    `testpaths = ["evals"]` (from `backend/pyproject.toml`) is collected whole.
  - `-rs` is what makes every skip reason print in the summary (the evidence
    used below). `-q` suppresses the explicit "collected N items" line.
- A dedicated step then parses the skip lines and classifies each on its
  **reason text only** (never the file path), failing the job if more than one
  *non*-catalog skip is present.

### Local gate (`Makefile` → `make gate`, at `3471747`)

- `cd backend && TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1 .venv/bin/pytest -q`
  (same `testpaths`, no marker filter, no path args), plus strict mypy, ruff,
  frozen-artifact and clean-tree checks.
- The `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1` environment variable is the hinge:
  `backend/evals/conftest.py::pytest_sessionstart` **aborts the session** if the
  variable is set and the catalogs are missing. So a passing local gate *proves*
  the catalogs were present, which in turn means the catalog-dependent tests
  **ran** rather than skipped.

Both environments run the identical suite with identical selection; the only
difference is the presence of the catalog data files and the one env var that
turns their absence from "skip" into "hard stop".

## 3. The mechanism (code-level)

Three pieces in the target tree produce the behavior:

1. **`backend/pyproject.toml`** defines the marker
   `requires_regional_catalogs: … skipped with an explicit reason when they are
   absent, and a hard session failure when TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1
   (set by make gate)`.
2. **`backend/evals/catalog_guard.py`** lists the six required corridors
   (`SIN, BOM, DXB, NYC, LON, PAR` → `active_<catalog_id>.json`),
   `missing_catalogs()`, and the exact `SKIP_REASON` string.
3. **`backend/evals/conftest.py`**:
   - `pytest_sessionstart` → `pytest.exit(..., returncode=2)` when
     `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1` **and** catalogs missing.
   - `pytest_collection_modifyitems` → if `missing_catalogs()`, add
     `pytest.mark.skip(reason=SKIP_REASON)` to every item carrying the
     `requires_regional_catalogs` marker. The items are still **collected**;
     they are skipped at run time.

A separate, subtler effect lives in **`backend/evals/test_i7_gate.py`**:
`_ACTIVATED = _activated_regions()` scans `backend/catalogs/active_*.json` **at
import/collection time**, and four tests are
`@pytest.mark.parametrize("catalog_id,data", _ACTIVATED, …)`.

- Catalogs absent → `_ACTIVATED == []` → each parametrized test collects an
  **empty parameter set**, which pytest records as a single *skip* ("got empty
  parameter set for (catalog_id, data)"). This is a **collection-count**
  difference, not merely an execution one.
- Catalogs present → `_ACTIVATED` has 6 entries → each of the four tests expands
  to **6** collected, passing nodes.

## 4. Exact CI skip inventory (authoritative, from the job log)

CI summary line: **`2569 passed, 27 skipped in 149.97s`**. No `failed`, `error`,
`deselected`, `xfailed`, or `xpassed` appears anywhere in the log.

| # | Node (file:line) | Count | Recorded reason | Class |
|---|---|---|---|---|
| 1 | `test_audit_regional_search.py:35` | 5 | regional catalog artifacts … not provisioned | catalog |
| 2 | `test_audit_regional_search.py:48` | 1 | regional catalog artifacts … not provisioned | catalog |
| 3 | `test_audit_regional_search.py:63` | 1 | regional catalog artifacts … not provisioned | catalog |
| 4 | `test_audit_taxonomy_retrieval.py:53` | 6 | regional catalog artifacts … not provisioned | catalog |
| 5 | `test_audit_taxonomy_retrieval.py:68` | 4 | regional catalog artifacts … not provisioned | catalog |
| 6 | `test_cp1_boundaries.py:74` | 1 | `CP1_MERGE_BASE is required for committed-diff assertions` | **other** |
| 7 | `test_i7_gate.py:47` | 1 | requires at least one real catalog built | catalog |
| 8 | `test_i7_gate.py:54` | 1 | got empty parameter set for (catalog_id, data) | catalog |
| 9 | `test_i7_gate.py:62` | 1 | got empty parameter set for (catalog_id, data) | catalog |
| 10 | `test_i7_gate.py:67` | 1 | got empty parameter set for (catalog_id, data) | catalog |
| 11 | `test_i7_gate.py:78` | 1 | got empty parameter set for (catalog_id, data) | catalog |
| 12 | `test_i7_gate.py:102` | 1 | requires at least two real catalogs built | catalog |
| 13 | `test_recompute_endpoint.py:102` | 1 | regional catalog artifacts … not provisioned | catalog |
| 14 | `test_recompute_endpoint.py:129` | 1 | regional catalog artifacts … not provisioned | catalog |
| 15 | `test_region_isolation.py:47` | 1 | requires both real catalogs built | catalog |

**Totals:** 27 skipped = **26 catalog-caused + 1 other**. CI's own
skip-accounting step printed exactly this: `total skipped: 27`,
`untracked regional catalogs: 26`, `other: 1` — and did **not** trip its
`other > 1` failure guard.

Marker-driven skips (items 1–5, 13–14) sum to **19**: five parametrized
destinations + two single tests in `test_audit_regional_search.py`; six
destinations + four picker cases in `test_audit_taxonomy_retrieval.py`; two in
`test_recompute_endpoint.py`. The `test_i7_gate.py` (items 7–12) and
`test_region_isolation.py:47` (item 15) skips are the self-guarding
`skipif`/empty-paramset/runtime-`pytest.skip` cases, for another **7**.
19 + 7 = 26 catalog-caused.

## 5. Were any tests *not collected at all*?

Yes — and this is a genuine **collection-level** difference, distinct from the
run-time skips:

- The four `test_i7_gate.py` parametrized tests collect an **empty parameter
  set** on CI (items 8–11). With catalogs present they collect **4 × 6 = 24**
  nodes. So CI's collected total is **20 lower** than local's purely from this
  parametrization (24 local nodes vs 4 skip-placeholder nodes).
- Everything else (the marker tests, the `skipif` gates) is **collected in both
  environments**; it is only the *outcome* (skip vs pass) that differs.

Because CI runs with `-q`, the explicit "collected N" line is suppressed, so the
collected totals are **inferred** from `passed + skipped`:

- CI collected ≈ 2569 + 27 = **2596**.
- Local collected ≈ 2615 + 1 = **2616**.
- Difference **20** = the `test_i7_gate.py` 4→24 expansion. Consistent.

(Stated evidence gap: the "2596"/"2616" collected totals are sums, not a printed
`collected N` line; and the `2616` side rests on the integration report's
figure, not a fresh local run.)

## 6. Reconciliation table (exact arithmetic)

Starting from the authoritative CI numbers and applying only the catalog effect:

| Transition (CI → provisioned local) | Nodes | Passed Δ | Skipped Δ |
|---|---|---|---|
| CI baseline | — | **2569 passed** | **27 skipped** |
| Marker tests run instead of skip (items 1–5, 13–14) | 19 | +19 | −19 |
| `test_i7_gate.py:47` runs (≥1 catalog) | 1 | +1 | −1 |
| `test_i7_gate.py:102` runs (≥2 catalogs) | 1 | +1 | −1 |
| `test_region_isolation.py:47` runs (SG+BOM) | 1 | +1 | −1 |
| `test_i7_gate.py` 4 empty paramsets → 4×6 real nodes | 4 → 24 | +24 | −4 |
| `test_cp1_boundaries.py:74` (`CP1_MERGE_BASE` still unset locally) | 1 | 0 | 0 (stays skipped) |
| **Resulting local** | — | **2615 passed** | **1 skipped** |

- Passed delta: `2615 − 2569 = 46 = 22 (one-to-one skip→pass) + 24 (parametric
  expansion)`. The one-to-one group is `19 markers + i7:47 + i7:102 +
  region_isolation = 22`.
- Skipped delta: all **26** catalog skips disappear; the **1** `CP1_MERGE_BASE`
  skip remains → local `1 skipped`.

The single remaining local skip and CI's single "other" skip are the **same
test** (`test_cp1_boundaries.py:74`): `make gate` does not set `CP1_MERGE_BASE`,
so that committed-diff guard self-skips locally too. The arithmetic closes
exactly, with no unexplained residual.

## 7. Did the required ingestion / parser / G3b checks actually run in CI?

**Yes — all of them, and they passed.** None appears in the skip list.

PR #19's own payload (diff `6428b78..6c348af`) is:

- `backend/ingestion/` — new `extraction.py`, `extraction_types.py`,
  `parsing.py`, `validation.py`, `evidence.py`; modified `migrations.py`,
  `storage.py`; new `fixtures/fi2_prompt_injection.txt`.
- `backend/gateway/travel/adapters/openbnb/` — the full offline OpenBnB (G3b)
  adapter package + 14 JSON fixtures.
- Tests added: `test_fi2_extraction.py`, `g3b_support.py`, and 10
  `test_g3b_*.py` files.

Evidence that these ran in CI:

- Grep of the CI `SKIPPED` lines for
  `ingest|parser|openbnb|g3b|fi2|instagram|extract|pdf|snapshot` → **no
  matches**. These suites are hermetic/offline (fixture-replay, no catalog, no
  network), so they are collected and executed normally and are counted in the
  2569 passed.
- `mypy --strict ingestion/` and `ruff check ingestion/` both ran as explicit CI
  steps and reported `All checks passed!`.
- The integration report independently records the focused FI0/FI1/FI2 + G3b +
  gateway slice at **456 passed** and FI2 extraction/replay at **15 passed**
  after review fixes.

So the discrepancy touches **only pre-existing regional-catalog integration
tests** (`test_audit_*`, `test_i7_gate`, `test_recompute_endpoint`,
`test_region_isolation`) that PR #19 did **not** modify. It does not touch the
PR's new coverage.

## 8. Classification: intentional optional coverage, not a gap

This is **intentional, documented, optional coverage**, by design:

- `catalog_guard.py`'s module docstring states the three-way contract
  explicitly: artifacts present → tests run; absent → skip with a visible
  reason "so a catalog-less CI run is honest about exactly what it did not
  verify"; absent with `TRIPWISE_REQUIRE_REGIONAL_CATALOGS=1` → session aborts.
- CI deliberately runs the catalog-less path and **surfaces and bounds** it: the
  skip-accounting step prints the counts to the job summary and **fails** if any
  non-catalog skip beyond the single known `CP1_MERGE_BASE` one appears. That
  guard is what converts "silent skips" into an enforced invariant.
- The authoritative verification of the catalog-dependent assertions is
  `make gate` on a provisioned machine, which is exactly the run that produced
  `2615 / 1`.

It is **not** a meaningful gap in PR #19 because none of the skipped tests
exercise PR #19's changed code; all of PR #19's own tests ran and passed in CI.

The one caveat worth flagging honestly (not a CI defect, a design property): on
the catalog-less CI path, the six-corridor **regional retrieval / taxonomy /
region-isolation / i7 structural** assertions are genuinely *not verified by
CI*. The project's stated and accepted compensating control is that `make gate`
must pass on a provisioned machine before a change is considered done. Any
regression that only manifests against real catalog data would therefore be
caught by `make gate`, not by the required PR CI.

## 9. Recommendations (no fixes implemented)

1. **Keep the current design; make the compensating control a named gate.** The
   skip-accounting guard is good. Record, in `docs/DEPLOYMENT.md` or the PR
   template, that a provisioned `make gate` run (with its `2615 / 1` figure) is
   a required pre-merge artifact for any change touching `gateway/catalog/`,
   `agents/retrieval.py`, `agents/search.py`, or the regional corridors — since
   required CI cannot cover them.
2. **Print the collected count in CI.** Add `-ra` or drop `-q` for a
   `--co`-style line (or run `pytest --collect-only -q | tail -1` once) so the
   collected total is logged. Today the collected count is only inferable from
   `passed + skipped`; a printed total would make the collection-level
   difference (the `test_i7_gate` expansion) self-evidencing in the log.
3. **Consider provisioning a minimal catalog fixture in CI**, or a single-city
   catalog, so at least one corridor exercises the `requires_regional_catalogs`
   and `test_i7_gate` paths in required CI. This would shrink the unverified
   surface without the full ~140 MB cost. (Trade-off: CI time and artifact size;
   out of scope to implement here.)
4. **Tighten the `test_i7_gate` empty-paramset ergonomics.** An empty
   `parametrize` silently becoming a skip is easy to misread as "a test ran."
   An explicit `skip_if_empty`/`pytest.param(..., marks=skip)` with a catalog
   reason would make the i7 skips classify like the marker skips and read
   uniformly in the log. (Cosmetic; the current CI classifier already handles
   the "empty parameter set" string correctly.)
5. **Normalize `CP1_MERGE_BASE`.** The single tolerated "other" skip is a
   committed-diff guard that only runs when `CP1_MERGE_BASE` is set. If that
   check is still considered valuable, wire the base SHA in CI (it is available
   as `github.event.pull_request.base.sha`) so the guard actually executes;
   otherwise document it as intentionally local-only. Either way the `other > 1`
   tripwire stays meaningful.

## 10. Unresolved evidence gaps (stated, not reconstructed)

1. **No present-day local full-suite reproduction.** Disk pressure on the host
   (worktree created `--no-checkout`) and unprovisioned catalogs here meant I
   could not independently re-run `make gate`. The `2615 / 1` figure is taken
   from the committed integration report, not re-measured. The CI `2569 / 27`
   figure **is** independently verified from the archived job log.
2. **Collected totals are inferred.** CI's `-q` suppressed the `collected N`
   line; `2596` (CI) and `2616` (local) are `passed + skipped` sums. The 20-node
   collection difference is derived from the `test_i7_gate` parametrization, and
   is consistent, but no literal `collected` line was captured.
3. **Integration report's intermediate `2220 passed` baseline** (its first table
   row) was not independently re-derived; it reflects a different invocation
   context (a plain seeded baseline before later focused/gate runs) and is not
   load-bearing for this reconciliation, which uses only the authoritative CI
   log and the gate figure.

## 11. Bottom line

- **Verified explanation:** the 46-passed / 26-skip difference is 100%
  attributable to regional-catalog provisioning — 22 catalog tests flipping
  skip→pass one-to-one, plus a 4→24 `test_i7_gate` parametrization expansion,
  with the lone surviving skip being the unrelated `CP1_MERGE_BASE` guard that
  is skipped in both environments. The arithmetic closes exactly against the
  authoritative CI log (`2569 passed, 27 skipped`) and the recorded gate figure
  (`2615 passed, 1 skipped`).
- **Required coverage missing?** No. Every test PR #19 introduced
  (FI2 ingestion/extraction/parsing/validation, G3b/OpenBnB offline adapter) was
  collected and passed in CI; strict mypy and ruff ran over `ingestion/`. The
  skips are confined to pre-existing, env-gated, intentionally-optional regional
  catalog integration tests that PR #19 did not touch.
- **Severity:** informational. The discrepancy is an intended, surfaced, and
  bounded property of the test harness, not a defect introduced by PR #19.
