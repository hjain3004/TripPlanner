# Handoff — land the Japan philatelic frontend layer (split from the stranded branch)

**Written:** 2026-08-22 · **Repo:** `/Users/himanshu_jain/TripPlanner` · **Base branch:** `main` @ `c3261ab`
**For:** the agent executing `docs/superpowers/plans/2026-08-22-japan-philatelic-split-landing.md`
**Status of that plan:** unblocked, self-reviewed, ready. Start at Setup Step 0.1.

---

## 0. Read these, in this order, before touching anything

1. `CLAUDE.md` — the agent brief. Five non-negotiables, decision tiers (F/C/V), ambiguity protocol.
2. `docs/superpowers/plans/2026-08-22-japan-philatelic-split-landing.md` — **the plan you are executing.** Read it whole before step 1, especially its "Context: what was actually found" section and its "Out of scope" section.
3. `frontend/design/CONTRACT.md` — the design contract. Task 8 replaces it. Read the current one first so you understand what it says today.
4. `DEVIATIONS.md` — how judgment calls get logged here. You will add exactly one row (Task 8; the text is written out for you).

**Do not** read the 17 specs in `docs/specs/`. **Do not** re-derive the visual direction — it was settled on 2026-08-08 and the philatelic work is already partly shipped on `main`. Every relevant finding is in the plan's Context section.

---

## 1. What you are actually doing, in one paragraph

A frontend branch (`codex/japan-philatelic-reconciliation`, 13 commits, last touched 2026-08-12) implemented the Japan philatelic visual system but never merged, and `main` has since moved 249 commits past it. Most of that branch is still good and still wanted. One part of it is genuinely superseded: it refactored `frontend/src/app/plan/page.tsx` by extracting a `results-view.tsx` component, while `main` grew that same file from 689 to 872 lines with F5/F5.1 editable-itinerary work that did not exist when the extraction was written. Your job is to land everything **except** that rewiring, in ten reviewable tasks, leaving the plan-page integration for a separate future plan.

---

## 2. Already decided — do not relitigate

- **Do not cherry-pick.** It was tested empirically in a throwaway worktree: 4 of 13 commits apply clean, 9 conflict, and several of those conflicts are artifacts of earlier skips rather than real disagreements. The plan re-applies final file states instead. This is settled.
- **Do not wire `plan/page.tsx` to `ResultsView`.** After this work, `results-view.tsx` and `plan/page.tsx` will duplicate rendering logic. That is known, intended, and temporary. The plan checks `git status --short frontend/src/app/plan/page.tsx` at three separate steps specifically to catch you doing it by reflex. If you think you should close that duplication, you have misread the task.
- **`CONTRACT.md` gets replaced, not merged.** `main`'s copy is stale documentation that contradicts `main`'s own running code (it says Bodoni Moda; `layout.tsx` loads Poiret One). Replacing it is a correction. It still gets a Tier-F DEVIATIONS row — the exact text is in Task 8, Step 8.4.
- **The theme-resolver change is a bug fix, not a preference.** `main` currently renders the Japan theme for every destination because of an unconditional assignment. Task 1.

---

## 3. The five traps

These will bite you if you move fast. Each has a step in the plan; this is the summary.

1. **Five files are "conflict surface"** — `main` changed them after the branch forked: `frontend/tests/contrast.test.ts`, `frontend/src/mocks/handlers.ts`, `frontend/src/app/kitchen-sink/page.tsx`, `frontend/src/app/kitchen-sink/views/ItineraryView.tsx`, `frontend/e2e/f1-gate.spec.ts`. **Hand-merge every one.** Overwriting with the branch's version silently deletes newer coverage — `handlers.ts` alone has ~287 lines of newer route handlers on `main`.
2. **Two import paths moved.** `main` relocated generated API output to `frontend/src/lib/api/generated/` and exposes a facade at `@/lib/api`. `results-view.tsx` and `japan-visual-fixture.ts` still import `@/lib/api/types.gen`, which no longer exists. Rewrite both to `@/lib/api` (Task 5, Step 5.2).
3. **`fixtures.json` is a conditional delete.** The branch deletes it; `main`'s `ItineraryView.tsx:13` still imports it. Whether it goes depends on how you merged `ItineraryView`. Run the grep in Step 6.4 and act on the result — do not delete first and fix imports after.
4. **zsh mangles `$J:frontend/...`.** Always brace it: `git show "${J}":path`. Bare `$J:fr` gets eaten by zsh modifier expansion and produces a confusing "ambiguous argument" error.
5. **A `gateguard` hook blocks working-tree writes** (`rm -rf`, `git rm`, `git checkout -- <file>`) and demands a facts preamble each time. Tasks 3–9 do a lot of those. Run with `ECC_GATEGUARD=off`, or add `pre:bash:gateguard-fact-force` and `pre:edit-write:gateguard-fact-force` to `ECC_DISABLED_HOOKS`, or expect to be interrupted constantly.

---

## 4. Skills to use

- **`superpowers:subagent-driven-development`** — the plan's own required sub-skill. Fresh implementer subagent per task, dedicated reviewer between tasks. Use this unless told otherwise.
- **`superpowers:test-driven-development`** — Task 1 is written red-first and must stay that way. Do not write the resolver fix before the failing test.
- **`superpowers:verification-before-completion`** — before any "done"/"passing" claim. Run the command, read the output, then speak.
- **`superpowers:requesting-code-review`** — Task 10, Step 10.7, against the whole `main..HEAD` diff.
- **`superpowers:finishing-a-development-branch`** — only after the gate passes, to decide integration.
- **`superpowers:systematic-debugging`** — if a screenshot diff or e2e failure is not immediately obvious. Do not re-baseline a reference screenshot to make a diff disappear.

---

## 5. Definition of done

All of these, verified by running them, not by assertion:

- `make gate-f1` prints `Gate F1: All checks passed.`
- `cd frontend && npx vitest run` green; `npx tsc --noEmit` exit 0; `node scripts/token-lint.mjs` 0 violations
- `git diff --stat main..HEAD -- backend/ contract/` is **empty** (this is a frontend-only plan)
- `git diff --stat main..HEAD -- frontend/src/app/plan/page.tsx` is **empty** (the deferred boundary)
- `cmp CLAUDE.md AGENTS.md` reports identical
- `reports/frontend_japan_philatelic_landing.md` exists and every number in it was copied from output you actually saw

---

## 6. Things you will read that are wrong

- **`reports/frontend_japan_philatelic_reconciliation.md` exists only on the stranded branch.** It documents a tree that no longer exists and describes the plan-page refactor you are *not* landing. Link to it as history; never copy it into your report.
- **`main` still references Bodoni Moda** in `frontend/src/app/page.tsx` and `frontend/src/app/kitchen-sink/views/UiComponentsView.tsx`, even though `layout.tsx` loads Poiret One. Task 8, Step 8.3 tells you how to decide whether those are dead references. If unsure, leave them and say so in the report.
- **Any test count quoted in any older report is stale.** Capture your own baseline at Setup Step 0.3 and compare against that.

---

## 7. What to report back

1. The task-by-task commit list with hashes.
2. The verbatim `make gate-f1` output and unit-suite totals.
3. The `fixtures.json` decision from Step 6.4 and the grep result that drove it.
4. Any leftover Bodoni references you left in place, and why.
5. Anything you hand-merged where you were unsure whether you preserved both sides — flag it explicitly for the reviewer rather than hoping it passes.

**Do not write "complete" anywhere until the gate has passed on a clean tree.** This project has shipped that specific mistake twice (the Gondola milestone and CP1 task 8); both were caught in review. Do not make it three.
