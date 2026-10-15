# CP2 + Japan Reconciliation

Date: 2026-10-07
Integration branch: `codex/reconcile-cp2-japan`
Base: `main` at `c3261ab` (unchanged)

## Inputs and safety

- CP2 input: `feat/cp2-conversational-api-ui`, four commits, clean worktree.
- Japan input: `feat/japan-philatelic-landing`, sixteen commits, with its seven valuable dirty/untracked screenshot files left untouched.
- Old input: `codex/japan-philatelic-reconciliation`, thirteen commits and 249 commits behind `main`. It was inspected only; it was not merged or rebased.
- The main worktree's untracked `docs/examples/` and two Japan plan files were preserved. The plan-file copies were compared against the committed Japan branch versions; the main-worktree copies are user-owned and remain untouched.
- `AGENTS.md` and `CLAUDE.md` were byte-identical before and after integration.

## Old Japan commit matrix

| Old commit | Decision | Reason |
|---|---|---|
| `ec83e31` initial-route bundle gate | Already represented | Current landing has `r0-initial-route-bundle.spec.ts`; the old branch's broad deletions were rejected. |
| `be72b35` deterministic theme scope | Already represented | Superseded by landing `d1b135c`; current resolver is deterministic. |
| `c4708cd` design-contract guardrail | Already represented differently | Landing contains the contract/design-drift work while preserving current files. |
| `a53b414` shared typed results | Already represented | Landing includes `ResultsView` and current generated API layout. |
| `f088f64` typed Japan results fixture | Already represented | Landing includes the typed fixture and tests. |
| `7462d39` Figma composition reconciliation | Already represented | Landing includes the Japan product-surface implementation. |
| `bb4fcde` candidate selection | Already represented | Landing includes both reviewed candidates and manifest. |
| `a122fb7` approved stamp asset | Already represented | Landing includes the approved runtime asset and metadata. |
| `8083d7b` typed destination stamp | Already represented | Landing includes typed asset access and component boundary. |
| `0303485` product placements | Already represented | Landing includes explicit Japan-only placements. |
| `ff33f8b` accessibility hardening | Already represented | Landing includes the accessibility fixes and tests. |
| `57fdf91` gate refresh | Already represented | Landing includes the current gate assertions. |
| `75e4867` gate report/screenshots | Rejected wholesale | The screenshots/report are historical evidence from an obsolete-base branch; current landing gate assets were retained and a fresh reconciliation report is provided here. |

The old branch's final tree was also compared file-by-file. Its apparent differences included deletion of modern backend/gateway/account/report/test work and movement of generated API files from `frontend/src/lib/api/generated/`; none were transplanted. No genuinely superior frontend implementation was found that was absent from the current landing branch.

## Integration decisions and conflicts

1. CP2 was applied first, including the Gondola SDK field-alias fix. OpenAPI, generated client/types, MSW handlers, API routes, UI, and tests stayed synchronized.
2. Japan landing was applied on top. The shared root layout kept CP2's layout wrapper and adopted Japan's `resolveTheme(null)` deterministic theme behavior.
3. `DEVIATIONS.md` retained both CP2.1 acceptance-hardening history and Japan's design/gate decisions; no history was replaced.
4. The Japan landing's MSW fixture extension was retained alongside CP2's planning/profile handlers.
5. A focused browser test exposed a real CP2 defect: `/profile` nested a `<main>` inside the shared layout. The inner landmark was changed to a `div` in a separate fix commit (`c8bf31e`); no test was weakened.
6. No dirty screenshot files were added to the integration branch.

## Verification

- CP2 backend focused tests: **13 passed**.
- CP2 strict mypy scope: **clean, 100 source files**.
- Full backend `make gate`: **passed** — 1,266 passed, 1 skipped, 3 warnings; strict mypy clean across 149 files; ruff clean in zero-tolerance scope; legacy ruff findings 6/12 ceiling; goldens, contract snapshot, brief identity, and clean-tree checks passed.
- Frontend typecheck: **passed**.
- Frontend Vitest: **157 passed** across 8 files.
- Frontend token lint: **0 violations**.
- Frontend ESLint: **0 errors, 15 warnings**.
- Frontend production build: **passed**.
- Focused CP2/Japan Chromium acceptance: **26 passed, 2 skipped**.
- OpenAPI regeneration followed by diff check: **byte-stable**.

The backend gate used the existing ignored local seed database/catalog artifacts through temporary symlinks in the isolated worktree; no such artifacts are tracked or changed. Frontend dependencies were installed offline in the isolated worktree only.

## Preserved work and later archival candidates

Still preserved and intentionally untouched:

- Main worktree: `docs/examples/IMG_2295.jpg` through `IMG_2306.jpg`, `docs/superpowers/plans/2026-08-22-japan-philatelic-landing-handoff.md`, and `docs/superpowers/plans/2026-08-22-japan-philatelic-split-landing.md`.
- `feat/japan-philatelic-landing` worktree: modified `design/refs/f1_5/landing-1440.png`, `landing-390.png`, `landing-768.png`, `landing-reduced-motion.png`; untracked `plan-1440.png`, `plan-390.png`, `plan-768.png`.
- `/Users/himanshu_jain/TripPlanner_I1`: its untracked `frontend/Premium Travel Itinerary Planner.zip` and directory remain untouched.

Candidates for later archival, only after human review: the now-redundant `codex/japan-philatelic-reconciliation` worktree/branch, and the completed CP2/Japan source worktrees once their history and dirty files are no longer needed. Nothing was archived in this task.

`main` was not modified, nothing was pushed, no branch or worktree was deleted, and no committed or uncommitted user work was discarded.
