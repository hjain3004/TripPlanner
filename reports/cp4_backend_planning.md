# CP4 backend planning recovery

**Status:** PLAN ONLY — backend implementation and CP4 UI acceptance remain pending.

**Date:** 2026-10-24 (America/Los_Angeles).

**Source:** `codex/a4-saved-trips` at `a172c19b405a42b7d2b8cbf6c9337737760ba50d`.

**Planning branch:** `codex/cp4-backend-plan` in `/Users/himanshu_jain/.codex/worktrees/cp4-backend-plan/TripPlanner`.

## Recovered state

- A4's five requested closure items are implemented and recorded in [a4_closure.md](a4_closure.md).
- [PR #16](https://github.com/hjain3004/TripPlanner/pull/16) is OPEN, targets `main`, has head `a172c19`, and reported merge state CLEAN when inspected. Backend, frontend, contract drift, and container/full-stack smoke CI checks all completed successfully. No merge or PR change was performed.
- A4's report records 2,006 backend tests passed / 1 skipped and 218 frontend Vitest tests passed. Those are inherited report figures, not tests rerun during planning.
- No existing CP4 plan file was found in the A4 source tree. The conversation's interrupted investigation had reached intent/invalidation design, inventory reuse, and recompute behavior.

## Deliverable

[CP4 backend implementation plan](../docs/superpowers/plans/2026-10-24-cp4-backend-actions.md) contains nine tasks: admitted-price recompute, pure action/impact contracts, durable operations, bounded interpretation, authenticated proposals, scoped planning, confirmed invalidation/profile changes, contract/acceptance synchronization, and final review/gates.

The plan explicitly preserves later CP4 frontend acceptance, A4's explicit saving behavior, frozen kernel arithmetic/call sites, and the provider/credential/spend boundaries. It does not begin deployment or FI work.

## Source finding

`api/conversation.py:recompute_confirmed_session` currently obtains optimizer/report fields through legacy recompute before replacing the flight/hotel cost lines with retained admitted lines. If those prices differ, the report can become internally inconsistent. Task 1 requires a non-vacuous numerical reproduction before changing assembly; this planning session did not execute that regression or label the issue fixed.

## Verification

- Checked exact source HEAD, clean source status, A4 closure report, relevant domain/orchestration interfaces, and PR #16's live CI status.
- Reviewed the plan against the conversational spec's seven intents, invalidation table, one-call interpretation ceiling, scoped-day preservation, approval boundary, privacy, and frozen kernel graph.
- Documentation scope only. No dependencies installed, catalogs copied, seed command, backend/frontend tests, or `make gate` run. Running the product gate is required during implementation; no acceptance result is claimed for CP4.
- Planning document checks and any independent review dispositions are recorded in the final handoff.

## Independent plan review

A separate read-only reviewer found no Critical issues and two Important defects. Both were corrected: the impact function now receives action/workspace context, and A4 first-save/append must atomically save a selected durable CP4 result rather than a stale process-local report. The plan adds equal-brief/different-action tests and approve/restart/concurrent-first-save coverage. Documentation whitespace checks pass; the plan's relative source links resolve.

## Preservation

A4, the primary checkout, and all prior branches/worktrees were preserved. Only this new planning worktree received documentation edits. No model/provider invocation, credential use, AWS resource, public deployment, push, PR edit, or merge occurred. Public GitHub API access was read-only.
