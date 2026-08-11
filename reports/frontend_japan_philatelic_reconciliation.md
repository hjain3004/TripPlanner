# Frontend Japan Philatelic Reconciliation Report

Date: 2026-08-11  
Branch: `codex/japan-philatelic-reconciliation`  
Plan: `docs/superpowers/plans/2026-08-11-japan-philatelic-frontend-reconciliation.md`

## Task 1 baseline — before bundle gate changes

Fresh baseline was captured before changing the bundle gate.

Working tree at baseline was the primary checkout on `main`, ahead 2 and behind 3, with unrelated
evidence-graph/itinerary documentation changes already present. Those changes are preserved and
are not part of this frontend branch.

Commands run from `frontend/` unless noted:

| Command | Result |
|---|---|
| `git status --short --branch` from repo root | `main...origin/main [ahead 2, behind 3]`; unrelated modified/deleted/untracked docs and `test_fix2.py` present |
| `npx tsc --noEmit` | Passed; no TypeScript output |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 12 rules |
| `npx vitest run` | Failed: 1 failed, 115 passed, 116 total |
| `npm run build` | Passed after rerun with network permission for Google Fonts |

The Vitest failure is the known invalid bundle assertion:

```text
FAIL tests/bundle-check.test.ts > bundle check — heavy deps absent from initial JS > gsap not in any chunk file
Expected: []
Received: ["3dewhjypacr5m.js"]
```

This test scans every emitted chunk, including deliberately lazy chunks, so it does not measure
the real requirement: heavy optional libraries must not be fetched by the initial landing route.

## Task 1 — honest initial-route bundle gate

Changes:

- Deleted `frontend/tests/bundle-check.test.ts` because it inspected every emitted chunk, including
  lazy chunks that are not requested by `/`.
- Added `frontend/e2e/r0-initial-route-bundle.spec.ts`, which opens `/` in Chromium and inspects
  the first-party JavaScript responses actually fetched by the initial route.
- Used tighter library-code signatures for GSAP so a lazy wrapper/import-path string does not
  falsely fail the route-level gate.

Red proof:

- Temporarily added the known framework marker `TURBOPACK` to the forbidden-marker list.
- `npx playwright test e2e/r0-initial-route-bundle.spec.ts --config=e2e/playwright.config.ts --project=chromium`
  failed against actual initial-route JavaScript responses, proving the gate can catch a forbidden
  first-route marker.
- Removed the temporary marker before the final green run.

Repository command note:

- This repo's Playwright configuration lives at `frontend/e2e/playwright.config.ts`; the plan command
  needs `--config=e2e/playwright.config.ts` to avoid Playwright trying to collect Vitest tests.

Verification:

| Command | Result |
|---|---|
| `npx tsc --noEmit` | Passed |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 12 rules |
| `npx vitest run` | Passed: 2 files, 112 tests |
| `npm run build` | Passed after network permission for Google Fonts |
| `npx playwright test e2e/r0-initial-route-bundle.spec.ts --config=e2e/playwright.config.ts --project=chromium` | Passed: 1 test |
