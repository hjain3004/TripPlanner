# Itinerary accuracy — make provenance load-bearing, then compose deterministically

**Date:** 2026-07-29
**Status:** PLAN — approved direction, not yet executed.
**Doubles as the handoff prompt.** Self-sufficient from a cold start; read §0 first.

---

## 0. Read these first, in this order

1. `CLAUDE.md` — the agent brief. The five non-negotiables, the decision tiers, and the ambiguity protocol bind you.
2. `DEVIATIONS.md` — recent judgement calls. Do not re-decide settled questions.
3. `docs/specs/06_implementation_protocol.md` — decision tiers, ambiguity protocol, gates.
4. `docs/specs/01_data_model.md` §POI and §Provenance, and `docs/specs/03_*` for the pipeline graph.
5. The code you are changing: `backend/agents/retrieval.py` (43 lines), `backend/agents/planner.py` (124 lines), `backend/core/models.py:181` (`POI`) and `:22` (`Provenance`).

Do **not** re-read all 17 specs.

---

## 1. Context — what is actually wrong

Hallucination in the itinerary path is already prevented, and well. `validate_itinerary`
(`agents/planner.py:26`) rejects any `poi_id` outside the retrieved set, any unknown
`hotel_area_id`, and any date outside the trip window; `run_planner` does validate → one
repair attempt → deterministic `fallback_itinerary`; temperature is `0.0`. The LLM selects
and orders IDs from a closed set. It cannot invent a place.

The exposure is **bad data becoming a validated wrong answer.** `validate_itinerary` checks
that a POI *exists*, never that its contents are true. Four specific holes:

**H1 — retrieval ignores provenance.** `retrieve_candidates` (`retrieval.py:33`) sorts by
interest overlap, area, id, slices to 40. `confidence`, `needs_verification` and
`last_verified` are never read. Every POI ranks as if equally trustworthy.

**H2 — the planner is blind to trust.** `_poi_row` (`retrieval.py:15`) is the exact string
the LLM sees: id, name, area, tags, price, duration, open_hours. No provenance field is in
it. The model cannot prefer verified data because it is never told which rows are verified.

**H3 — `open_hours` is free text.** `core/models.py:192` types it `str`. Real seed values
include `"08:00-20:00; closed Mon"` — a closure rule encoded in prose. Nothing can check a
visit date against it, so "scheduled on the day it is closed" is undetectable. The M3 anchor
rubric will not catch it either; that rubric grades geography and pacing.

**H4 — no travel-time feasibility.** POIs carry `lat`/`lon`, so distance is computable with
no provider and no key, but nothing computes it. `fallback_itinerary` slices a sorted list
by `PACE_ITEMS` (relaxed 1 / moderate 2 / packed 3), grouping by area, never checking
whether a day is physically doable.

---

## 2. Decisions taken — do not reopen

| Question | Decision |
|---|---|
| Buy or build itinerary curation? | **Build.** It is a composition problem over free POI data, not an inventory lookup. No provider holds "a good itinerary." |
| An MCP server for curation? | **No.** MCP is a transport for someone else's data or tools. Wrapping our own logic in it routes our code → protocol → our code, and collides with non-negotiable #5 (no dynamic MCP discovery, no agent-to-agent delegation). |
| Where does the composer live? | **`backend/core/itinerary/`**, beside the optimizer and transfer pathfinder — deterministic, golden-testable, and `core/` imports nothing from `agents/`. |
| Does the pipeline graph change? | **No.** Planner stays one of the four Tier-F call sites. What changes is the split inside it: LLM proposes an ordering, deterministic composer validates feasibility. |
| Add OSM/Overpass and Wikivoyage now? | **No — not in this plan.** They are the right sources, but they must land *after* provenance is load-bearing. See §6. |

---

## 3. The ordering constraint that matters most

Adding third-party POI data before H1/H2 are fixed injects unverified crowd-sourced rows
into a retrieval layer that treats them as equal to curated ones, and they flow straight
into a confident, fully-validated itinerary. **That is the concrete mechanism by which this
component's accuracy gets ruined, and it is an ordering mistake, not a sourcing one.**
T1 is a prerequisite for any new POI source. Do not reorder.

---

## 4. Two facts about the current data you must know before you start

- **All four seed POIs are `confidence: 1.0`, `needs_verification: true`, `verified_by: UNVERIFIED`.** So a confidence *threshold* is a no-op on today's data. Do not conclude your filter is broken when behaviour does not change — write tests with synthetic fixtures that carry varied provenance. The discriminators that currently differ are `verified_by` and `last_verified`.
- **`core/seeds/pois.yaml` holds exactly 4 POIs and `areas.yaml` 4 areas**, and the file header says *"structure only. VERIFY hours/prices."* Four POIs cannot exercise a pacing or travel-time composer. **Build test fixtures; do not expand the seed set.** Replacing seed placeholders with real verified data requires human approval (CLAUDE.md ambiguity protocol) — if you think the seeds must grow, stop and ask.

---

## 5. Tasks — one commit each, full test suite green between

### Phase A — spec pass (docs only, no code)

`docs/specs/` is read-only during implementation, so schema changes go in a dedicated pass
first, matching the 2026-07-28 precedent.

- **A1** — Amend `docs/specs/01_data_model.md`: retype `POI.open_hours` from free string to a structured weekly-hours type plus explicit closure dates. Specify the type; do not implement it.
- **A2** — Amend the spec-03 retrieval contract: retrieval is provenance-aware (ranks and may filter on trust), and `_poi_row` exposes trust to the planner.
- **A3** — Record in `DEVIATIONS.md` that `POI.open_hours` is a **Tier-C** data-model change: it is not money, not a provenance column, not the pipeline graph, not a golden value, so it is outside Tier F. State that explicitly so the next reader does not have to re-derive it.

### Phase B — implementation

- **T1 — provenance-aware retrieval** (`agents/retrieval.py` only). Rank on `needs_verification` / `verified_by` / `last_verified` / `confidence` alongside interest overlap, and add the trust fields to `_poi_row` so the planner sees them. Highest accuracy-per-line change in the plan; no new dependency. Fixes H1 and H2.
- **T2 — refactor: move the composer to `core/`.** Move `fallback_itinerary` from `agents/planner.py` into `core/itinerary/compose.py`; `agents/planner.py` imports and calls it. **Pure move, zero behaviour change**, own commit — anti-drift rule.
- **T3 — structured opening hours.** Implement the A1 type in `core/models.py`, migrate `core/seeds/pois.yaml` (4 rows; `"08:00-20:00; closed Mon"` is the interesting one), keep provenance untouched.
- **T4 — hours feasibility in the composer.** Reject or flag an item scheduled when the POI is closed. Fixes H3.
- **T5 — travel-time budget.** Deterministic haversine over the existing `lat`/`lon`, plus a per-day travel budget. No provider, no key, no network. Catches `anchor_scattered` mechanically instead of via an LLM judge. Fixes H4.

---

## 6. Out of scope

- **No new POI providers.** No OSM/Overpass, no Wikivoyage, no Foursquare, no Tripadvisor. They come after this plan; when they do, they enter as `source_type: crawl_draft` with `needs_verification: true` under non-negotiable #4 (agents propose, humans approve).
- **No freshness propagation to the UI.** Carrying per-item trust onto `ItineraryItem` and out through the API is the right next step, but it changes `contract/openapi.json`, and spec 12 §8 requires schema + snapshot + generated code + MSW fixtures + UI in **one** PR. The frontend is paused, so that PR cannot be completed. **Specified here, deliberately deferred.**
- No changes to the pipeline graph or the four call sites. No `frontend/` changes. No routing/maps provider.
- No expansion of `core/seeds/`.

---

## 7. Verification

Run from `backend/` using its venv (`backend/.venv/bin/python`; there is no repo-root venv):

1. `.venv/bin/python -m pytest -q` — **133 tests currently pass. That is the floor.**
2. `.venv/bin/python -m mypy --strict core/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py` — currently clean on 36 files; keep it clean. Also keep `mypy --strict gateway/` clean (10 files).
3. **The 12 optimizer golden cases and the canonical demo must not move.** `evals/golden/` is money and transfer math and the demo path is optimizer-only, so POI changes should not touch them — *verify this, do not assume it.* If a golden value moves, you have changed something Tier-F: stop, hand-audit per spec 06 §4, log it, `xfail` the test, and report. Never "improve" a golden.
4. `evals/test_m2_retrieval.py` and `evals/test_m2_planner.py` cover the code you are changing — expect to update them, and say in the report what you changed and why.
5. New behaviour needs new tests with synthetic provenance fixtures (see §4).
6. `git status` — nothing modified under `frontend/`.

---

## 8. Execution notes

Branch `feat/itinerary-accuracy`, off `main` (currently `deecb96`). Working tree is clean.

**Skills to invoke:** `superpowers:using-superpowers` first. `superpowers:test-driven-development`
for every task in Phase B — this is accuracy work and the tests are the deliverable as much
as the code. `superpowers:verification-before-completion` before reporting done.
Do **not** invoke `superpowers:brainstorming` — the direction is decided in §2.

**Ambiguity protocol:** do not stop and ask. Choose the most conservative option that changes
no Tier-F behaviour and no golden number, log it in `DEVIATIONS.md` (`date, doc§, question,
decision, rationale, files`), continue. Ask a human **only** for: a confirmed Tier-F spec bug,
or a belief that the seed data must be expanded with real verified values.

**Do not push, merge, or open a PR.** Leave the branch local and report.

**Write `reports/itinerary_accuracy.md`:** what landed per task, the test count before and
after, confirmation the goldens and demo did not move, and — most useful — what you now
believe the *next* accuracy risk is, having been inside this code.

---

## 9. The thing to keep in view

The point of this plan is not to make itineraries prettier. It is that today a POI with
`verified_by: UNVERIFIED` and a prose opening-hours string can flow through a validator that
approves it, an LLM that cannot question it, and an explainer whose groundedness gate only
audits currency amounts — and reach the user looking exactly as trustworthy as a
curator-checked fact. Every task here exists to break one link in that chain.
