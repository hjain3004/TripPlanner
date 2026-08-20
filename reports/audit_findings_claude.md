# Audit Findings — Claude (2026-08-16)

**Do not read this file until you have written your own independent findings.** It exists to be
reconciled against a second auditor's list, and reading it first turns an audit into a
confirmation exercise.

Method used: run the product and compare what it does against what it claims. Every finding below
was reproduced by executing code, not by reading it.

---

## Open findings

### 1. The core value proposition works in one region out of six

Same trip, three destinations, via `estimate_costed_trip`:

```
DEL->SIN:  4 spend lines, 19,403,200 minor (Rs 194,032)
DEL->PAR:  0 spend lines, 0
DEL->NYC:  0 spend lines, 0
```

I7 expanded destination coverage 6x. The money side never moved: `core/seeds/` holds 3 sample
flights, 3 sample hotels and 3 FX rates, all for the Singapore corridor. So five of six regions
produce a full itinerary attached to an empty budget.

It degrades honestly — assumptions explain the gap and `RegionCapability.budget_supported` is
`false` — which is exactly why no gate caught it. Honest degradation made a strategic hole
invisible.

**Class:** claim/reality mismatch. Strategic, not a code defect.

### 2. User interests have no effect on results

```
interests=[food]             -> Astons Specialties, Thomson Plaza, Pizza Hut, Red Bowl
interests=[museums, history] -> Astons Specialties, Thomson Plaza, Pizza Hut, Red Bowl
IDENTICAL? True
```

`agents/retrieval.py::_overlap` intersects user interests with `poi.tags`. Catalog POIs carry one
tag — their category (`restaurant`, `cafe`, `park`). So `"food"` never matches `"restaurant"`, and
`"museums"` does not match `"museum"` (plural). Every catalog POI scores 0, interests drop out of
the sort, and order falls through to provenance and id.

Plan written: `docs/superpowers/plans/2026-08-16-r1-interest-aware-retrieval.md`.

**Class:** scaffolding outliving its purpose. The tag vocabulary was built when 4 hand-tagged POIs
were the entire database.

### 3. Placeholder POIs outrank 28,540 real ones

Top four Singapore candidates: Maxwell Food Centre, Gardens by the Bay, Skyline Luge (all
hand-written M1 seeds), then one real venue. 3 of the top 10 are seeds.

Same root cause as #2 — seeds are the only records whose tags can match an interest, so they win
by construction. `retrieve_candidates` merges `kb.pois(city)` into catalog results rather than
treating it as a fallback.

### 4. Dead scaffolding

- `backend/accounts/` — contains only `__pycache__`. Stub for unimplemented spec 17.
- `backend/ingestion/` — contains only `__init__.py`. Stub for unimplemented spec 05.
- 35 plan documents, at least 8 superseded or marked "DO NOT EXECUTE" — including
  `2026-07-28-figma-template-reconciliation.md`, which `DEVIATIONS.md` says must never be run.
  A live trap for any agent told to "execute the plans."
- 4 Singapore-era design refs from the abandoned celadon direction, still tracked.
- Route architecture: `/plan` is 872 lines holding a 5-step wizard, a polling view and the entire
  results dashboard, switched by `useState`. No addressable trip resource, so nothing is
  shareable, bookmarkable or refresh-safe. `job_id` already exists and `GET /plan/{job_id}` already
  works, so `/trip/{job_id}` needs zero backend work.

---

## Known-open, previously reported (not re-litigating)

- End-to-end pipeline latency ~8 minutes on 70B; never observed completing in-browser. Unexplained.
- Explainer unverified on `llama-3.3-70b-versatile` (0 of 14 scenarios) — Groq daily cap.
- Planner falls back to the deterministic composer on `llama-3.1-8b-instant` for every scenario.
- G0 tiles implemented (`gateway/catalog/tiles.py`, `build_catalog_tiles`) but **not applied** —
  `catalogs/` still holds 6 whole-city artifacts. The 307MB->131MB win came from compaction, not
  bounding.
- `CLAUDE.md` checkpoint dated 2026-07-28, claims 133-test baseline; actual is 493.
- ~45 commits unpushed; nothing deployed.

---

## Findings already fixed this session (listed to show the pattern, not for re-audit)

Each was found by running the product, never by a failing test:

- Overture category mapping discarded ~96,000 restaurants and ~17,000 temples across six cities
  while keeping 4,851 Mumbai condos as "attractions". All gates green throughout.
- No CORS middleware on FastAPI — the browser could never reach the backend. Invisible because MSW
  intercepts in-browser and Playwright ran against mocks.
- urllib's default User-Agent rejected by Groq (HTTP 403, Cloudflare 1010).
- JSON mode returned `{"trip_spec": {...}}`, defeating even the repair retry.
- `TrustChip` at 4.35:1 contrast (AA small text needs 4.5:1).
- `aria-hidden` on the map container left MapLibre's controls keyboard-reachable but
  screen-reader-invisible.
- `_AUTHORITY` hardcoded `overture_sg`, silently dropping all 38,700 Mumbai claims.
- Manifest checksums matching no file on disk; a real rebuild would have failed quarantine.

**The pattern:** every one of these passed the gate. The tests were never wrong — they were never
looking at the thing that mattered.
