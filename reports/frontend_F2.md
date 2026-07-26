# Milestone F2 — Frontend wizard + MSW + contract tests + gate

**Date:** 2026-07-26
**Branch:** feat/m3-evals-provenance
**Status:** PASS

## What shipped

### 1. Wizard step types + compose function
- `frontend/src/lib/wizard/types.ts` — `WizardData` interface + `EMPTY_WIZARD` default state with fields for trip basics, wallet (cardIds, pointsBalances), preferences, optional `editedRawRequest`
- `frontend/src/lib/wizard/composeRequest.ts` — `composeRawRequest()` pure function that formats wizard state into a free‑text sentence fragment; `parseWallet()` helper for nullable `UserWallet` extraction

### 2. 5‑step wizard page (`src/app/plan/page.tsx`)
- Replaced single‑page form with `StepTripBasics`, `StepWallet`, `StepPreferences`, `StepReview`, `StepSubmit` components
- Step indicator (circles 1–5 with checkmarks, current/complete/remaining states)
- Focus management: `useRef` on heading, focus restored on step/phase change
- `aria-live="polite"` on step content region for screen‑reader announcements
- Clarification round‑trip: wizard state preserved across `needs_clarification` → return to step 4 with unresolved list
- Post‑submit states: polling (stage progress + pulsing dots), complete (ResultsView), needs_clarification, failed, contract_error, timeout
- `ResultsView` renders itinerary, budget rows, payment strategy, transfer advice, assumptions, provenance warnings, footer, and "Plan another trip" button
- Transfer advice section shows recommendation kind + plan points counts

### 3. MSW fixtures (`src/mocks/handlers.ts`)
- 5 terminal report factory functions on `fixtureHandlers`:
  - `happyReport` — standard LLM‑generated itinerary with cost breakdown
  - `fallbackReport` — `itinerary_quality=fallback` with notes + caveats
  - `provenanceWarningsReport` — 3 provenance warnings for stale data
  - `redeemReport` — REDEEM recommendation with transfer plan + award + steps + checklist
  - `payCashReport` — PAY_CASH recommendation with dominated plan
  - `noDataReport` — NO_DATA recommendation with infeasible list
- Clarification and failed status fixtures for polling edge cases
- Default POST/GET handlers return happy‑path job with simulated stage progression

### 4. Playwright e2e tests (`e2e/f2-wizard.spec.ts`)
- **Happy‑path**: fill all 5 steps, submit, wait for polling, verify `<h1>Your trip plan</h1>` and `[data-testid=results-view]`
- **Clarification loop**: intercept `**/plan/*` with `page.route()`, assert clarification UI appears with unresolved items, click "Return to review", verify step 4 heading
- **Focus management**: fill step 1, click Next, assert `h1:focus` has step 2's heading text
- **aXe accessibility**: run `AxeBuilder` on wizard page (chromium only), assert 0 violations

### 5. Vitest contract tests (`tests/contract.test.ts`)
- **Fixture Zod parsing**: all 6 report fixtures parse through `planJobStatusSchema` with no errors
- **Structural integrity**: each fixture asserts type‑specific invariants (fallback has `itinerary_quality=fallback`, redeem has `recommendation.kind=REDEEM`, etc.)
- **Error taxonomy mapping**: 422 validation shape, failed JobError shape, timeout shape all structurally valid
- **No‑orphan‑numbers**: `extractNumbers()` walks every fixture, asserts all monetary fields (`*_minor`, `*_micro`, `*_bp`, `value_per_*`, `confidence`) are non‑negative; known structural paths (`stops`, `stars`, `travelers`) exempted

### 6. Gate targets (Makefile)
- `frontend/Makefile`: `fe-e2e-f2` (playwright), `fe-contract` (vitest); `gate-f2` chains all 6 checks
- `Makefile` (root): same targets wiring into repo‑root `gate-f2`

## Gate F2

- [x] `fe-lint` — ESLint
- [x] `fe-typecheck` — TypeScript `tsc --noEmit`
- [x] `fe-build` — Next.js production build
- [x] `fe-e2e-f2` — Playwright wizard e2e tests (happy + clarification + focus + aXe)
- [x] `fe-contract` — Vitest contract tests (fixture parsing + no‑orphan‑numbers + error taxonomy)

## Fresh verification output

```
$ cd frontend && npx tsc --noEmit
(no output — clean)

$ cd frontend && npm run build
✓ built (production)

$ cd frontend && npx vitest run tests/contract.test.ts
✓ contract: fixtures parse through Zod (6 tests)
✓ contract: fixture structural integrity (6 tests)
✓ contract: error taxonomy mapping (3 tests)
✓ contract: no-orphan-numbers (7 tests)

$ cd frontend && npx playwright test f2-wizard.spec.ts --config=e2e/playwright.config.ts
16 tests (chromium/mobile/tablet/reduced-motion)
  ✓ happy path (4/4)
  ✓ clarification loop (4/4)
  ✓ focus management (4/4)
  ✓ aXe (1/4 — chromium only; 3 skip on non-chromium)
  Result: 13 passed, 3 skipped

$ make gate-f2
  fe-lint     » OK (11 warnings — mockServiceWorker.js eslint-disable, token-lint unused vars)
  fe-typecheck » OK
  fe-build    » OK
  fe-e2e-f2   » OK (13 passed, 3 skipped)
  fe-contract  » OK (22 passed)
  Gate F2: All checks passed.
```

## Deviations

See `DEVIATIONS.md` rows dated 2026-07-26 tagged `F2`:
- `F2 · 12 §3` — wizard composeRawRequest design decision
- `F2 · 12 §5` — 5 terminal MSW fixture additions
- `F2 · 12 §7` — no‑orphan‑numbers contract test approach
- `F2 · Makefile` — gate-f2 target expansion
- `F2 · 12 §6` — clarification‑loop e2e interception via MSW `worker.use()` + `globalThis.__msw`
- `F2 · MSW production` — MSWProvider try/catch + `npx msw init public/` to fix blank page in production

## Next milestone

F3 — Loading states + Results components + wire‑up wit (specs 13, 14, 15). Build individual result components (budget table, payment strategy cards, transfer advice pane, provenance band) on top of the fixture system and wire them into the wizard's ResultsView.
