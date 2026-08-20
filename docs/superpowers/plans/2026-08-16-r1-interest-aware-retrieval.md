# R1 — Interest-Aware Retrieval

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`. Steps use checkbox
> (`- [ ]`) syntax. Also required: `superpowers:test-driven-development`,
> `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.

**Goal:** Make the interests a user types into the wizard actually change which venues they get,
and stop four hand-written placeholders from outranking 28,540 real ones.

Named R1 rather than folded into the I-series because it is a defect fix, not a new phase. It
repairs something I7 exposed.

---

## The measured problem

Two facts, both reproduced on the current branch:

**1. Interests have no effect whatsoever.**

```
interests=[food]             -> Astons Specialties, Thomson Plaza, Pizza Hut, Red Bowl
interests=[museums, history] -> Astons Specialties, Thomson Plaza, Pizza Hut, Red Bowl
IDENTICAL? True
```

**2. Placeholders outrank real data.** The top four Singapore candidates are Maxwell Food Centre,
Gardens by the Bay and Skyline Luge — all hand-written M1 seeds — then one real venue. Three of
the top ten are seeds.

### Root cause — one bug, two symptoms

`_overlap()` in `agents/retrieval.py` intersects user interests with `poi.tags`. The two sides
speak different vocabularies:

| Source | `tags` value | Example |
|---|---|---|
| Seed POIs (`core/seeds/pois.yaml`) | curated interest words | `[nature, landmark, kids]` |
| Catalog POIs (`_map_candidate_to_poi`) | **one category** | `[restaurant]` |
| User interests (wizard) | free text | `food`, `museums`, `history` |

So `"food"` never matches `"restaurant"`, and `"museums"` does not even match `"museum"` —
plural. Every catalog POI scores **0** on interest overlap, so interests drop out of the sort
entirely and the order falls through to provenance and `poi.id`. Meanwhile seed POIs are the only
records whose tags can match, so they take the top slots by construction.

This is scaffolding that outlived its purpose: the tag vocabulary was designed when four
hand-tagged POIs *were* the database.

---

## Global Constraints

1. **Deterministic mapping only.** Interest → category is a table, not an LLM call. It must be
   explainable, testable, and identical across runs. Do not add a fifth LLM call site (Tier-F).
2. **No Singapore-shaped assumptions.** The mapping keys off the six universal catalog categories
   (`park`, `food_court`, `restaurant`, `cafe`, `attraction`, `museum`), not off any city.
3. **`backend/core/` imports nothing from `agents/`, `api/`, `gateway/`.**
4. **Money goldens are frozen.** This changes which POIs are *selected*, not any arithmetic. If a
   golden moves, stop — something coupled retrieval to the optimizer.
5. **Provenance survives.** Ranking changes must not drop `needs_verification`, `licence_id` or
   attribution from any candidate.
6. **`make gate`**, whole, pasted whole.

---

## Measured Baseline

Verify in Task 0.

| Metric | Value |
|---|---|
| `make gate` | PASSED, 493 tests |
| catalog POIs (SIN) | 28,540 |
| seed POIs (Singapore) | 4 |
| seeds in top 10 candidates | **3** |
| distinct results for `[food]` vs `[museums, history]` | **none — identical** |
| relevant code | `agents/retrieval.py::_overlap`, `_map_candidate_to_poi`, `retrieve_candidates` |

---

## Task 0: Preflight

- [ ] `git status --porcelain` empty; `make gate` passes.
- [ ] Reproduce both symptoms above and paste the output. If either does not reproduce, stop and
      report — the bug may already be fixed and this plan is then wrong.
- [ ] Branch `feat/r1-interest-aware-retrieval`.

---

## Task 1: An interest vocabulary that maps to categories

- [ ] Failing test first, `evals/test_retrieval_interests.py`:
      `test_different_interests_return_different_venues`. Retrieve with `["food"]` and with
      `["museums", "history"]` against the real catalog fixture and assert the result sets
      **differ**. This is the assertion whose absence let the bug ship.
- [ ] Add `test_interest_matching_is_case_and_plural_tolerant`: `Museums`, `museum`, `MUSEUM` all
      reach the `museum` category.
- [ ] Implement `interests_to_categories(interests: list[str]) -> set[str]` in
      `agents/retrieval.py`. A literal table, normalised by casefold + simple singularisation
      (trailing `s`). Suggested coverage — extend as you see fit, but keep it explicit:

      food, dining, restaurants, eat, cuisine      -> restaurant, food_court, cafe
      cafe, coffee, bakery                          -> cafe
      nature, parks, outdoors, gardens, hiking      -> park
      museums, history, art, culture, galleries     -> museum, attraction
      sightseeing, landmarks, architecture          -> attraction
      nightlife, bars                               -> restaurant, attraction

- [ ] An interest that maps to nothing must be **ignored**, not treated as a filter — a user
      typing "relaxing" should not receive zero venues.
- [ ] `_overlap` scores a catalog POI by whether its category is in the mapped set. Keep the
      existing behaviour for seed POIs whose tags already use the interest vocabulary.
- [ ] `make gate`. Commit: `fix(retrieval): map user interests onto catalog categories`.

## Task 2: Decide the seed-POI policy explicitly

Seed POIs are real places but carry placeholder prices (`# VERIFY` comments) and
`needs_verification: true`. They were the whole POI universe in M1; now they compete with a real
catalog and win by accident.

- [ ] Failing test first: when a region has an **active** catalog, retrieval returns **no** seed
      POIs. When it has **no** catalog, seed POIs are still returned (they are the honest
      fallback, and `RegionCapability` already reports `catalog_status`).
- [ ] Implement in `retrieve_candidates`: `kb.pois(city)` is the fallback source, not an
      additional source, when a catalog is active.
- [ ] Anti-vacuity: assert the no-catalog case actually returns seeds — otherwise the test passes
      by returning nothing in both branches.
- [ ] Check for duplicates before deciding: Gardens by the Bay almost certainly exists in the
      Overture catalog too. Report whether the seeds are genuine duplicates of catalog entries. If
      they are, that strengthens the case for dropping them when a catalog exists.
- [ ] `make gate`. Commit: `fix(retrieval): catalog supersedes seed POIs when one is active`.

## Task 3: Prove personalisation end to end

- [ ] Print the top 10 candidates for three genuinely different interest sets — `["food"]`,
      `["museums", "history"]`, `["nature", "parks"]` — on the real Singapore catalog. Paste all
      three lists in your report.
- [ ] They must be visibly different and each must look plausible for its interests. If
      `["museums", "history"]` returns restaurants, the mapping is wrong; say so rather than
      shipping it.
- [ ] Repeat for **one non-Singapore region** (Paris or Mumbai) to confirm nothing is
      Singapore-shaped.
- [ ] `make gate`. Commit: `test(retrieval): personalisation across interests and regions`.

## Task 4: Report

- [ ] `reports/r1_interest_aware_retrieval.md`: before/after candidate lists, the vocabulary
      table, the seed-POI decision and its rationale, whether seeds duplicate catalog entries,
      and anything left open.
- [ ] `DEVIATIONS.md` rows for the vocabulary choices (Tier C) and the seed-POI policy.

---

## Explicitly out of scope

- **Semantic/embedding interest matching.** A deterministic table is explainable and testable; an
  embedding model is neither, and this is not where the LLM budget should go.
- **Richer tags on catalog POIs.** Overture gives one primary category. Deriving more from
  `alternate` categories is a separate, larger piece of work.
- **Distance/quality re-ranking.** Ranking already sorts by distance from the region centroid.
  Changing that is a different concern from interest matching.
- **Deleting the seed POIs.** They remain the honest fallback for regions with no catalog, and
  golden tests depend on them.
- **The empty budget for five of six regions.** Real, separate, strategic — do not fix it here.

---

## Final Response Requirements

1. **Per-task status** — `done` / `partial` / `not started`.
2. **Full `make gate` output**, pasted whole.
3. **Before/after top-10 lists** for all three interest sets, plus the non-Singapore region.
4. **The seed-POI duplication finding.**
5. **Every vocabulary decision**, with its `DEVIATIONS.md` row.
6. **Everything not done**, and why.

Do not push. Do not open a PR. Report and stop.

---

## Self-Review Notes

- Do three different interest sets genuinely produce three different lists? Paste them.
- Does an unmapped interest ("relaxing") return venues, or silently zero the results?
- Did any golden move? (It must not — this changes selection, not arithmetic.)
- Does the no-catalog branch still return seed POIs, and did I assert it non-vacuously?
- Does the fix work for Paris and Mumbai, or did I encode Singapore's category mix?
- Do candidates still carry `needs_verification`, `licence_id` and attribution?
