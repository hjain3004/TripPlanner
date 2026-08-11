# Merge I0 + I1, and Fix the Boundary Violation They Expose

**Date:** 2026-08-11
**Goal:** Get `feat/i0-evidence-hardening` and `feat/i1-safety` onto `main`, green, and report the
real merged baseline so phase I2 can start.

**This is not a mechanical merge.** The two branches are individually green and jointly red. Read
Part 1 before touching git.

---

## PART 0 — RULES

1. Paste raw command output for every verification. No summaries.
2. **Never weaken or delete a test to make the merge pass.** If a test blocks the merge, the test
   is telling you something true. This is the entire point of Part 1.
3. `backend/evals/golden/` and `contract/openapi.json` must not change.
4. No `ruff --fix` outside files you create. A previous phase reformatted all of `evals/` against
   instructions; do not repeat that.
5. Report numbers you **measured**, never estimated. Three separate reports in this project have
   quoted file/test counts that did not survive checking.

---

## PART 1 — THE CONFLICT YOU MUST FIX

Both branches fork from `origin/main` (`aa08dd4`).

- `feat/i0-evidence-hardening` — worktree `.worktrees/itinerary-i0-evidence-hardening`,
  206 tests, Gate I0 green.
- `feat/i1-safety` — worktree `/Users/himanshu_jain/TripPlanner_I1`, 159 tests, Gate I1 green.

**The collision.** I1 added `backend/core/itinerary/compose.py`, whose line 18 reads:

```python
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, RetrievalContext, TripSpec
```

I0 added `backend/evals/test_evidence_boundary.py::test_core_does_not_import_gateway_or_agents`,
which walks `backend/core/**/*.py` with `ast` and asserts no import whose module starts with
`agents`. **After the merge that test fails.**

It is not a false positive. `CLAUDE.md` → Repo boundaries states plainly:

> `backend/core/` imports nothing from `agents/` or `api/`.

I1 violated a stated architectural invariant; I0 built the check that catches it. Neither branch
could see it in isolation. Git will report **no textual conflict** in these files — the merge will
appear clean and the test suite will then go red.

### The fix — move the types down, re-export up

`agents/ → core/` is the allowed direction. `core/ → agents/` is not. So the five types
`core/itinerary/compose.py` needs must live in `core/`:

`TripSpec`, `RetrievalContext`, `DraftItinerary`, `ItineraryDay`, `ItineraryItem`.

1. Move those five definitions out of `backend/agents/models.py` into `backend/core/` — either
   into `core/models.py` or a new `core/trip_models.py` (your call; say which and why).
   `TripSpec` already depends on `core.models.UserWallet` and `core.models.OptimizationPrefs`, so
   this direction is natural, not forced.
2. In `backend/agents/models.py`, **re-export** them so every existing `from agents.models import
   TripSpec` keeps working unchanged. Do not update dozens of call sites; that is churn and risk.
3. Change `core/itinerary/compose.py` to import them from `core/`.
4. `agents/models.py` may still import from `core/` — that direction is fine.

**Forbidden alternatives**, for the record: do not relax the boundary test; do not move
`compose.py` back into `agents/` (the 2026-07-29 plan §2 deliberately placed the composer in
`core/` so it is deterministic and golden-testable); do not add a suppression or `# noqa`.

---

## PART 2 — SEQUENCE

Work on `main` in the primary worktree at `/Users/himanshu_jain/TripPlanner`.
**Warning:** that worktree may hold another agent's uncommitted frontend changes. Run
`git status --short` first. If anything under `frontend/` is dirty, **stop and report** — do not
stash, commit, or discard someone else's work.

- [ ] **Step 1 — record the two baselines yourself.** In each worktree run
      `.venv/bin/pytest -q | tail -2`. Expect 206 (I0) and 159 (I1). If either differs, stop and
      report.
- [ ] **Step 2 — merge I0 first** (it is the larger, more foundational change):
      `git checkout main && git merge feat/i0-evidence-hardening`.
      Expect a clean merge. Run the suite; expect 206. Paste it.
- [ ] **Step 3 — merge I1**: `git merge feat/i1-safety`.
      Expect a **`DEVIATIONS.md` conflict** — both branches appended a section. Resolve by
      **keeping both**, I0's section then I1's. Never drop either.
      Also check `AGENTS.md` / `CLAUDE.md`: I0 edited both with an I0 checkpoint bullet. If I1
      touched them too, keep both bullets and re-verify `cmp AGENTS.md CLAUDE.md` at the end.
- [ ] **Step 4 — watch the boundary test fail.** Run `.venv/bin/pytest -q`. It should now report a
      failure in `test_core_does_not_import_gateway_or_agents`. **Paste that failure.** If it does
      not fail, stop and report — it means the merge did not land what you think it did.
- [ ] **Step 5 — apply the Part 1 fix.** Move the five types, re-export from `agents/models.py`,
      repoint `compose.py`.
- [ ] **Step 6 — verify.** The boundary test passes, and every other test still passes. No test was
      edited to achieve this.
- [ ] **Step 7 — commit the fix** (the merges are their own commits already):
      `fix(core): move trip and itinerary types into core to honor the import boundary`

---

## PART 3 — MERGED GATE

```bash
cd /Users/himanshu_jain/TripPlanner/backend
.venv/bin/pytest -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/
.venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py
.venv/bin/ruff check gateway/ evals/ 2>&1 | tail -2
cd ..
git diff --exit-code -- backend/evals/golden/ && echo "GOLDENS UNCHANGED"
git diff --exit-code -- contract/openapi.json && echo "CONTRACT UNCHANGED"
git diff --check
cmp AGENTS.md CLAUDE.md && echo "BRIEFS IDENTICAL"
git status --short
git log --oneline -6
```

Expected: all tests pass — the merged total should be roughly **232** (206 + 159 − 133 shared
baseline), but **measure it, do not assume it**; mypy clean; I0-owned ruff zero; goldens and
OpenAPI unchanged; briefs identical; tree clean apart from any pre-existing frontend changes you
were told not to touch.

Do **not** push. Do **not** open a PR. Leave `main` local and report.

---

## PART 4 — YOUR FINAL RESPONSE

1. The two pre-merge baselines you measured.
2. The `DEVIATIONS.md` conflict: how you resolved it, and confirmation both sections survive.
3. **The pasted boundary-test failure from Step 4**, before your fix.
4. Where you moved the five types and why.
5. The full Part 3 gate output, pasted raw.
6. **The merged `main` commit sha and the exact merged test count.** Phase I2 branches from this
   sha and uses this number as its floor — a wrong figure here propagates.
7. Anything you could not complete, stated plainly.
