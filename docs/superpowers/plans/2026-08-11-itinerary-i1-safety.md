# Itinerary I1 — Closed-World Safety

**Date:** 2026-08-11
**Status:** PLAN — not yet executed.
**Doubles as the handoff prompt.** Self-sufficient from a cold start; read §0 first.
**Supersedes nothing.** It *extends* `2026-07-29-itinerary-accuracy.md`, which remains the
task-level work order. Read both. Where they conflict, this file wins (it is newer and
reconciled against the current code).

---

## 0. Read these first, in this order

1. `CLAUDE.md` — the agent brief. The five non-negotiables, decision tiers, and ambiguity
   protocol bind you.
2. `DEVIATIONS.md` — recent judgement calls. Do not re-decide settled questions.
3. `docs/specs/06_implementation_protocol.md` — decision tiers, ambiguity protocol, gates.
4. `docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md` — **§14 Phase I1 and
   §15** are the authority for what I1 means and where it sits. Also read §5.4 (freshness
   classes) and §7 (deterministic composition), which define behaviour this phase must honour.
5. `docs/superpowers/plans/2026-07-29-itinerary-accuracy.md` — **the base work order.** Its §1
   (what is wrong), §2 (decisions taken — do not reopen), §4 (facts about the seed data), and
   §5 (tasks T1–T5) are still correct and still binding.
6. The code you are changing: `backend/agents/retrieval.py`, `backend/agents/planner.py`,
   `backend/agents/models.py:70` (`ItineraryItem`), `backend/core/models.py:181` (`POI`) and
   `:192` (`open_hours`).

Do **not** re-read all 17 specs.

---

## 1. What this phase is

Phase I1, "closed-world itinerary safety": make the itinerary the product already ships
*honest and mechanically feasible*, using only the existing seeded Singapore data. No new data
sources, no providers, no MCP, no network.

The financial kernel (M1–M3) is complete and trustworthy. The itinerary is not: today an LLM
composes the schedule and the only validation is that POI IDs and dates exist. A day can
schedule a POI on the weekday it is closed, or three stops across the island in an hour, and
nothing catches it. I1 closes that gap.

---

## 2. Sequencing — the I0 relationship, and what you must log

The design's chain (§15) is `I0 → I1 → …`. **I0 is not complete.** Verified 2026-08-11:
`backend/gateway/evidence/` has 8 modules and 33 tests, but against
`2026-08-02-itinerary-i0-evidence-hardening.md` it is missing `identity.py` entirely,
`Edge.created_by_run`, endpoint/direction validation in `add_edge()`, four of seven persisted
node types in `store.py`, the `_run_id_for()` `"r1"` fallback removal, and — most importantly —
zero-spend enforcement (`PlanBudget.max_cost_minor` still defaults to `None` and
`BudgetLedger` has no `record_external_cost()`). There is no
`reports/itinerary_i0_evidence_hardening.md`.

**I1 is nevertheless being run first, deliberately.** I1 is closed-world: it reads the seeded
SQLite KB, calls no provider, and writes nothing to the evidence graph. Nothing in the I1 task
list depends on graph identity, lineage, or budget. I0's purpose (design §14) is "make the
graph safe enough to support place identity and lineage" — that matters at I2/I3 when multiple
providers arrive, not here.

**Your first commit must be a `DEVIATIONS.md` row recording this**, in the standard columns:
date `2026-08-11`, doc§ `itinerary design §14/§15`, question "I1 before I0 — permitted?",
decision "yes, I1 is closed-world and provider-free", rationale as above, affected files. Do
not skip this. Do not silently proceed as if the chain said `I1 → I0`.

**Hard boundary that follows from it:** I0's zero-spend enforcement is still absent, so this
phase must not add any code path that could call a paid service. No HTTP client, no adapter,
no credential, no `gateway/` import from the itinerary path. If you find yourself needing one,
you have left I1's scope — stop and report.

---

## 3. Reconciling the 2026-07-29 base plan

Execute `2026-07-29-itinerary-accuracy.md` §5 (Phase A: A1–A3, Phase B: T1–T5) as written,
with these corrections. Everything not listed here is still accurate.

| Stale in the 07-29 plan | Current truth |
|---|---|
| §8: "off `main` (currently `deecb96`)" | `main` has moved. Branch off current `origin/main` (`aa08dd4` or later — `git fetch` first). |
| §6: defers UI trust propagation because "the frontend is paused" | The frontend is **not** paused — another agent is actively running a Japan/Jet-Age redesign (`reports/milestone_J0.md`–`J5.md`). **The deferral still holds**, but for a different and stronger reason: see §5 below. Do not treat "frontend is now active" as permission to change the contract. |
| §7.2: mypy "clean on 36 files… also keep `mypy --strict gateway/` clean (10 files)" | Use one invocation: `.venv/bin/mypy --strict core/ agents/ api/ gateway/` — currently clean on **42 files**. |
| §7.1: "133 tests currently pass. That is the floor." | Still exactly right. Unchanged. |
| Referred to as an uncommitted/untracked file | It is committed and tracked now. Edit it freely if a task's detail turns out wrong; say so in your report. |

`2026-07-29-itinerary-accuracy.md` §2 ("decisions taken — do not reopen") and §3 (the ordering
constraint: provenance must be load-bearing *before* any new POI source) remain binding and are
reinforced by the design. Do not reopen them.

---

## 4. Scope I1 requires that the 07-29 plan does not yet cover

The 07-29 plan predates the itinerary design. Four items in design §14's I1 definition are not
in its task list. Add them.

- **N1 — Scheduled times on itinerary items.** Gate I1 requires "no overlap," which is not
  expressible today: `ItineraryItem` (`agents/models.py:70`) carries `poi_id`, a free-text
  `start_hint: str | None`, and `meal_slots`. The deterministic composer must assign real
  start/end instants per item and the validator must check them. Read §5 before you change any
  model — *where* these times live is constrained.
- **N2 — Timezone-aware hours.** Design §14 says "structured **timezone-aware** intervals and
  exceptions." The 07-29 plan's A1/T3 say "structured weekly-hours type plus explicit closure
  dates" without timezone. Singapore is single-timezone so this is latent today, but model it
  tz-aware now — retrofitting a timezone into a schedule type after I3 adds other cities is
  exactly the kind of change this phase exists to avoid.
- **N3 — Final schedule construction leaves the LLM.** The 07-29 plan's T2 only moves
  `fallback_itinerary` into `core/itinerary/`; the happy path still has the LLM emitting the
  final `DraftItinerary` (`planner.py:108`). Design §14 requires final schedule construction to
  be deterministic. Target shape: the LLM proposes *selection and ordering* (which POIs, in
  what sequence, with qualitative reasons); `core/itinerary/` deterministically assigns times,
  checks feasibility, and produces the committed schedule. **The planner remains exactly one of
  the four Tier-F call sites** — you are changing what the call *returns*, not adding or
  removing a call site. Do not introduce a fifth.
- **N4 — A separate validator emitting structured reasons and verification tasks.** Distinct
  from composition. It must produce machine-readable rejection reasons, and explicit
  user-facing verification tasks. Honour design §5.4: unknown hours **do not** become open — a
  non-time-critical stop may be scheduled carrying a visible verification task, while a
  timing-critical or reservation-dependent stop is excluded until verified. The LLM critic may
  propose a revision but must never override a failed constraint (design §7).

---

## 5. The contract trap — read before touching any model

`contract/openapi.json` exists and is snapshotted. Spec 12 §8 and `CLAUDE.md`'s repo
boundaries require that a schema change, the OpenAPI snapshot, generated client code, MSW
fixtures, and the UI **all ship in one PR**. The frontend is concurrently mid-redesign by
another agent.

Therefore: **I1 must not change the public API contract.** The design puts API/frontend
exposure in Phase **I6**, and that is where it belongs.

Concretely — the timing and feasibility work of N1/N4 lives *internally*, in
`backend/core/itinerary/`, and is consumed by the composer and validator. It does not need to
appear in the `/plan` response to deliver its value: the itinerary becomes *provably feasible*
even while the times themselves stay unexposed. I6 surfaces them later.

Verify this explicitly before you finish:

```bash
git diff --exit-code -- contract/openapi.json
```

If that command fails, you have changed the contract. **Stop, revert the schema change, and
report** — do not pull the frontend into this branch, and do not regenerate the snapshot.

---

## 6. Gate I1

From design §14, verbatim: *"seeded Singapore schedules have no overlap, known-closed visits or
impossible transitions; every stop resolves to provenance; missing hours visibly propagate; two
runs are byte-identical; all existing money/transfer goldens remain unchanged."*

Run from `backend/` with its venv (there is no repo-root venv):

```bash
cd backend
.venv/bin/pytest -q                                      # floor: 133. Must not drop.
.venv/bin/mypy --strict core/ agents/ api/ gateway/      # currently clean, 42 files
.venv/bin/ruff check core/itinerary/ agents/ evals/test_m2_*.py
cd ..
git diff --exit-code -- backend/evals/golden/            # goldens must not move
git diff --exit-code -- contract/openapi.json            # contract must not move
git diff --check
git status --short                                       # nothing modified under frontend/
```

Plus new tests proving each gate clause:

- a schedule with two overlapping items is rejected;
- a stop on a day the POI is closed is rejected (the `"08:00-20:00; closed Mon"` seed row is
  your fixture);
- a day whose transitions exceed the travel budget is rejected;
- a POI with unknown hours produces a visible verification task rather than a silent
  assumption of "open";
- every committed stop resolves to provenance;
- the same input produces byte-identical output across two runs.

**If a golden value moves, you have changed something Tier-F.** Stop, hand-audit per spec 06
§4, log it, `xfail` the test, and report. Never "improve" a golden.

---

## 7. Skills

Invoke `superpowers:using-superpowers` first, then:

- `superpowers:using-git-worktrees` — isolate this work. The primary worktree has the frontend
  agent's uncommitted changes in it; do not disturb them.
- `superpowers:test-driven-development` — **mandatory for every task in Phase B and every N
  item.** This is accuracy work; the tests are as much the deliverable as the code.
- `superpowers:systematic-debugging` — whenever a test fails for a reason you did not predict,
  before changing production code.
- `superpowers:verification-before-completion` — before reporting done, from a clean tree.
- `superpowers:requesting-code-review` — with the exact base/head SHAs; resolve Critical and
  Important findings before declaring completion.
- `superpowers:finishing-a-development-branch` — present merge/PR/local options; do not choose
  an external action silently.

Do **not** invoke `superpowers:brainstorming` — the direction is settled in the 07-29 plan §2
and design §14. Do **not** invoke frontend or design skills; this phase changes no UI.

---

## 8. Execution notes

- One commit per task (A1–A3, T1–T5, N1–N4), full suite green between. Behaviour changes and
  refactors are separate commits — T2 in particular is a **pure move, zero behaviour change**.
- **Ambiguity protocol:** do not stop and ask. Choose the most conservative option that changes
  no Tier-F behaviour and no golden number, log it in `DEVIATIONS.md`, continue. Ask a human
  **only** for a confirmed Tier-F spec bug, or a belief that the seed data must be expanded
  with real verified values (`core/seeds/` has exactly 4 POIs and 4 areas — **build test
  fixtures, do not expand the seeds**; see 07-29 plan §4).
- Do not push, merge, or open a PR without asking. Leave the branch and report.
- **Write `reports/itinerary_i1_safety.md`:** what landed per task; test count before/after;
  the exact gate command outputs quoted, not paraphrased; confirmation that goldens, the demo,
  and `contract/openapi.json` did not move; deviations added; and — most useful — what you now
  believe the next accuracy risk is, having been inside this code.

---

## 9. The thing to keep in view

The 07-29 plan put it well and it is still the point: a POI with `verified_by: UNVERIFIED` and
a prose opening-hours string can flow through a validator that approves it, an LLM that cannot
question it, and an explainer whose groundedness gate only audits currency amounts — and reach
the user looking exactly as trustworthy as a curator-checked fact.

I1 adds the second half of that sentence: and a *schedule* that no code ever checked for
feasibility can reach the user looking exactly as considered as one that was. The money side of
this product already honours "every number explainable." This phase is where the itinerary side
starts to.
