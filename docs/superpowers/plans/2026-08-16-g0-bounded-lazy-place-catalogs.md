# G0 — Bounded, Lazily-Provisioned Place Catalogs

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Steps use checkbox
> (`- [ ]`) syntax. Also required: `superpowers:test-driven-development`,
> `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.

**Goal:** Make catalog storage bounded and destination coverage lazy, so adding a destination
costs a bounded amount of disk and no code change — replacing the current model where every
supported city is pre-built in full and kept forever.

**Why now.** I7 built six cities and measured the wall: **307MB on disk for six destinations**,
at ~1,582 bytes per place. That is the honest cost of correctness — the I7 category fix roughly
tripled the catalogs by stopping them discarding real restaurants and temples. Correctness and
pre-building pull against each other on size, and the pre-build model does not survive its own
success. The human raised this directly: *"you do understand that i need to make this website for
all over the globe at some point. are we seriously going to store each and every tourist spot on
earth?"* No. This plan is the answer.

**Prerequisite met:** `make gate-f4` passes as of 2026-08-16. `CLAUDE.md` gates provider/gateway
work behind F4, so this work is now formally unblocked.

---

## The constraint that shapes the design — read this before designing anything

The obvious design is "fetch places from the web at request time." **That is forbidden**, and
three separate rules say so. Do not design around them; design within them.

1. **`CLAUDE.md`, non-negotiable #2:** *"The deterministic kernel never touches the web. During
   the Kernel MVP, the only request-time external call is the LLM API. In the target prototype,
   allowlisted live evidence is accessed only through the Data Gateway (specs 09/16)."*
2. **Itinerary design §6:** Overture is *"queried in batch with DuckDB Spatial or
   `overturemaps-py`; **never an unbounded request-time download**."*
3. **`DEVIATIONS.md` 2026-08-11 (spec 10):** DuckDB is deliberately **not** a project dependency,
   to keep its extension attack surface out of the tested pipeline. A request-time DuckDB query
   would drag it back in.

**Therefore the architecture is lazy *provisioning*, not lazy *fetching*.** The request path never
touches the network. When a destination has no catalog, the request returns an honest partial
result — `RegionCapability` already models exactly this — and a **separate, offline, bounded
provisioning job** builds that destination's tiles. The next request finds them.

This is not a workaround. It is better: provisioning stays reviewable and deterministic, request
latency stays independent of Overture, and the zero-spend ceiling stays trivially provable.

---

## Global Constraints

1. **The request path makes no network call other than the LLM.** A test must prove it.
2. **Money goldens are frozen.** `backend/evals/golden/` must not change.
3. **`backend/core/` imports nothing from `agents/`, `api/` or `gateway/`.**
4. **DuckDB stays out of `pyproject.toml`** and out of anything pytest imports.
5. **No new runtime dependency** without a `DEVIATIONS.md` entry justifying it.
6. **Raw extracts and built catalogs stay gitignored.** Commit manifests, checksums, reports.
7. **`make gate` is the backend gate.** Run it whole, paste it whole. `make gate-f4` for anything
   touching `frontend/` or `contract/`.
8. **Report numbers you measured**, from commands run in your session.

---

## Measured Baseline

Verify in Task 0. Measured on `feat/i7-regional-rollout` @ `3c7812a`+, 2026-08-16.

| Metric | Value |
|---|---|
| `make gate` | PASSED, 475 tests |
| `make gate-f4` | All checks passed |
| catalogs on disk | **307 MB**, six regions |
| largest single catalog | `active_nyc-core.json`, 85 MB, 56,172 places |
| bytes per place | ~1,582 |
| fields duplicated on **every** claim | `source_url`, `attribution_requirements`, `licence_id`, `source_release`, `verified_by`, `retrieved_at`, `last_verified` |
| claims per place | ~3 |
| adapter seam | `gateway/places/protocol.py::PlaceProviderAdapter.search_places()` |
| existing implementation | `gateway/places/adapters/snapshot.py::SnapshotPlaceAdapter` |
| capability model | `agents/pipeline.py::build_region_capability()` → `RegionCapability` |

---

## Known-Bad Patterns

Each of these shipped at least once in this project. They are why the gate is what it is.

| # | Pattern | Rule |
|---|---|---|
| 1 | Verification substitution — running a narrower command, reporting it as the gate | Run `make gate`. Paste all of it. |
| 2 | Named but not tested — a test whose fixture never reaches the interesting branch | Prove the branch executes. Assert the fixture is non-trivial. |
| 3 | Scope truncation with confident closure | Report per-task status. "Partial" is a fine answer. |
| 4 | Stub-and-declare — a mock-shaped hole in production code | `evals/test_no_stubs.py` guards prose. Do not add a synthetic-data path. |
| 5 | Gate passes, product broken | I6 shipped 411 green tests over a catalog of crematoria. Structural gates are not quality gates. |
| 6 | Singapore-shaped assumptions | I7 found `_AUTHORITY` hardcoding `overture_sg`, silently dropping all 38,700 Mumbai claims. Assume every constant is region-shaped until proven otherwise. |
| 7 | Fixing the test instead of the bug | Legitimate sometimes — three F4 tests were genuinely wrong. But prove it empirically first, and write down the evidence. |

---

## Task 0: Preflight

- [ ] `git status --porcelain` — must be empty.
- [ ] Run `make gate` and `make gate-f4`. Both must pass before you change anything.
- [ ] Re-measure every row of the baseline table. Report any row that differs, and stop if the
      catalogs are missing (they are gitignored; you may need to rebuild via
      `scripts/fetch_overture.py` + `build_catalog`).
- [ ] Create branch `feat/g0-bounded-catalogs`.

---

# PART A — Make storage bounded

## Task 1: Stop duplicating source metadata on every claim

Seven fields repeat on every claim, ~3 claims per place. This is pure duplication: the values are
per-*source*, and the artifact already carries a `sources` list.

- [ ] Failing test first, `evals/test_catalog_compaction.py`: build a fixture catalog and assert
      the serialized artifact stores each source's `source_url`/`attribution_requirements`/
      `licence_id`/`source_release`/`verified_by` **once**, not once per claim.
- [ ] Add a second test asserting a **round-trip**: `SnapshotPlaceAdapter` loading the compacted
      artifact yields `PlaceCandidate`s whose claims still expose every provenance field with the
      same values as before. Provenance must survive compaction — it is Tier-F
      (`CLAUDE.md` non-negotiable #3). Losing a licence to save bytes fails this task.
- [ ] Implement: claims reference a source by id; the adapter rehydrates on load.
- [ ] Rebuild all six catalogs. Record before/after bytes-per-place and total MB.
- [ ] Target: well under 800 bytes/place. If you cannot get there, report the number you got and
      why — do not drop provenance fields to hit a target.
- [ ] `make gate`. Commit: `perf(catalog): store source provenance once per source`.

## Task 2: Tiles, not whole cities

A city is the wrong unit: it is unbounded in size and forces all-or-nothing provisioning.

- [ ] Introduce a deterministic tile scheme — fixed-degree bbox tiles (suggested 0.1° × 0.1°),
      addressed `tile_{lat}_{lon}` at a pinned precision. Document the choice; it must be
      reproducible from coordinates alone, with no floating-point ambiguity at boundaries.
- [ ] Failing test first: a place's tile id is a pure function of its coordinates, stable across
      runs, and boundary coordinates land in exactly one tile (assert the boundary case
      explicitly — off-by-one at a tile edge is the obvious bug here).
- [ ] `build_catalog` emits one artifact per tile instead of one per city. A city manifest becomes
      a set of tiles covering its bbox.
- [ ] `SnapshotPlaceAdapter` gains a sibling `TiledPlaceAdapter` implementing the **same**
      `PlaceProviderAdapter` protocol: given a request origin and radius, it loads only the tiles
      that intersect, not the whole city.
- [ ] Failing test first: a search near a city edge loads a bounded number of tiles, and a search
      in the middle of a large city loads **fewer bytes** than the whole-city artifact. Assert on
      bytes or tile count, not just correctness — the point of this task is the bound.
- [ ] `make gate`. Commit: `feat(catalog): address places by deterministic tile`.

## Task 3: A disk budget with eviction

- [ ] Add a cache index (SQLite is already a dependency — do not add another) recording per tile:
      tile id, catalog release, byte size, build time, last-access time.
- [ ] Enforce a configurable total disk budget (suggest 2 GB default) with LRU eviction. Evicting
      a tile must never corrupt an in-flight read.
- [ ] Failing test first: provision more tiles than the budget allows; assert total on-disk bytes
      stay under budget and that the **least recently used** tiles are the ones gone. Anti-vacuity:
      assert at least one tile actually survived and at least one was actually evicted.
- [ ] `make gate`. Commit: `feat(catalog): bound total catalog disk with LRU eviction`.

---

# PART B — Make provisioning lazy

## Task 4: A provisioning state machine

- [ ] Model states explicitly: `absent` → `provisioning` → `active` → `stale`. `RegionCapability`
      already has `catalog_status` with `active`/`absent`/`stale`; extend it with `provisioning`
      and keep the contract honest.
- [ ] The request path **reads** this state and never advances it, never fetches, never blocks.
- [ ] Failing test first, and this is the one that matters most:
      `test_the_request_path_makes_no_network_call`. Patch the socket layer (or
      `urllib.request.urlopen` plus any HTTP client in use) to raise on any call, run a full
      `run_pipeline` against an **unprovisioned** destination, and assert it returns a normal
      response with `catalog_status="absent"` — no exception, no network, no Singapore fallback.
      This encodes `CLAUDE.md` non-negotiable #2 as an executable test for the first time.
- [ ] `make gate`. Commit: `feat(agents): report provisioning state without touching the network`.

## Task 5: The offline provisioning job

- [ ] A CLI entry point (`python -m gateway.catalog.provision --destination BOM`) that: resolves
      the region, computes its tile set, fetches only tiles not already cached, builds, quality-
      gates and activates them, and updates the cache index.
- [ ] It reuses `scripts/fetch_overture.py`'s DuckDB path. **DuckDB stays a system tool invoked by
      subprocess**, never imported, never added to `pyproject.toml`.
- [ ] Idempotent: running it twice provisions nothing the second time. Assert that.
- [ ] Failing test first: the provisioning job is **not importable from the request path**. Add a
      boundary test asserting `agents/` does not import `gateway.catalog.provision`.
- [ ] `make gate`. Commit: `feat(catalog): lazy per-destination provisioning job`.

## Task 6: Frontend honesty for a cold destination

- [ ] The UI must say something true and calm when a destination is `absent`/`provisioning` —
      reuse the existing `RegionCapability.known_gaps` rendering and the `TrustChip`
      `needs-verification` variant. Do **not** invent a new visual language.
- [ ] Contract change ships as ONE commit: schema + `contract/openapi.json` + regenerated client +
      MSW fixtures + UI (spec 12 §8, enforced by `make gate`'s `CONTRACT_OK`).
- [ ] Note for whoever does this: `frontend/src/lib/api/schemas.ts` and `client-config.ts` are
      **hand-written**, not generated. `npm run gen:api` overwrites the output directory and will
      delete them. Restore them after regenerating.
- [ ] `make gate` **and** `make gate-f4`. Commit: `feat(contract): surface provisioning state`.

---

# PART C — Prove the bound

## Task 7: The scale test

- [ ] Write `evals/test_catalog_scale.py`: provision N synthetic destinations (N ≥ 20, using
      fixture data — **do not hit the network in a test**), and assert:
      total disk stays under budget; every provisioned destination answers a search; unprovisioned
      ones report `absent` rather than failing or borrowing another region's data.
- [ ] Anti-vacuity: assert the fixture actually produced ≥ 20 distinct destinations and that at
      least one eviction occurred — otherwise the test proves nothing about bounding.
- [ ] Report: disk used for 20 destinations vs the 307 MB that six cost before this plan.

## Task 8: Report and gate

- [ ] `make gate && make gate-f4`, both pasted whole.
- [ ] Write `reports/g0_bounded_catalogs.md`: baseline vs after (bytes/place, total MB, tiles per
      city), the tile scheme and why that size, the eviction policy, the network-isolation test,
      and everything you did not do.
- [ ] Update `docs/ARCHITECTURE.md` if the storage model description is now wrong.

---

## Explicitly out of scope

Say so in your report if you were tempted; do not silently expand.

- Request-time fetching of any kind. See the constraint section.
- Adding DuckDB, or any HTTP client, as a runtime dependency.
- Global coverage. This plan makes coverage *bounded and lazy*; it does not claim worldwide
  support, and `worldwide` stays labeled future work per itinerary design §14.
- Real opening-hours data. Every catalog is still 0% hours because the OSM/Wikivoyage manifest
  sources are `example.invalid` placeholders. That is a separate, known task.
- Flights/hotels providers (G1+). This is places only.

---

## Final Response Requirements

1. **Per-task status** — `done` / `partial` / `not started`, one line each.
2. **Full `make gate` and `make gate-f4` output**, pasted whole.
3. **Before/after table**: bytes per place, total MB, tiles per city, disk for 20 destinations.
4. **The network-isolation test result** — this is the headline; it is the first executable proof
   of `CLAUDE.md` non-negotiable #2.
5. **Every threshold you chose** (tile size, disk budget, eviction policy) and why.
6. **Everything you did not do**, and why.

Do not push. Do not open a PR. Report and stop.

---

## Self-Review Notes

- Did I run `make gate` whole, or substitute something narrower and report it under its name?
- Does the network-isolation test actually fail if I remove the isolation? Verify by breaking it
  on purpose once.
- Did any test start passing because a fixture got smaller or emptier?
- Did compaction drop any provenance field? (Tier-F. The round-trip test must prove it did not.)
- Is DuckDB still absent from `pyproject.toml` and from every import pytest reaches?
- Are `backend/catalogs/` and `backend/raw_overture/` still untracked?
