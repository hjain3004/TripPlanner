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

## Task 3 red proof — design drift guardrail

`npx vitest run tests/design-drift.test.ts` failed before repairs with 34 violations. The failure covered the intended drift categories:

| Category | Representative paths |
|---|---|
| `transition-all` | `ExploreView.tsx`, `theme-proof/page.tsx`, `SharedUI.tsx` |
| faux-bold display typography | `ExploreView.tsx`, `DealsView.tsx`, `ItineraryView.tsx`, `ProofView.tsx`, `WalletView.tsx`, `ProfileView.tsx`, `RegisterSpecimenView.tsx` |
| scale-zero entrances | `ProofView.tsx`, `Illustrations.tsx` |
| raw black | `Illustrations.tsx` |
| confetti import | `verdict-header.tsx`, `booking-checklist.tsx` |

The plan's Task 3 file list omitted some view files that the required broad guardrail intentionally flags. The mechanical repairs stayed limited to typography, transition specificity, scale-zero entrance removal, and confetti removal; content/data reconciliation remains Task 6.

## Task 4 red proof and repairs

Red proof:

- `npx playwright test e2e/f3-results.spec.ts --config=e2e/playwright.config.ts --project=chromium -g "verdict"` failed because the verdict rendered derived currency savings (`₹10,000`) and did not render the supplied `savings_pct_bp` display (`10.0%`).

Additional failures after tightening no-orphan-number coverage:

- `CountUp` rendered transient interpolated money values that did not exist in fixtures.
- The natural fallback muted text token produced 4.48:1 contrast on results-page small text after Task 2 removed the global Japan override.

Repairs:

- Extracted `ResultsView` from `/plan` without changing result section order.
- `VerdictHeader` now renders gross cost, effective cost, and supplied savings percentage only.
- Removed the broad positive-currency-difference allowance from the no-orphan-number test.
- Changed `CountUp` to render the supplied minor-unit value directly.
- Darkened the natural fallback muted text token and raised the natural contrast assertion to AA for small text.

## Task 6 red proof and verification

Red proof:

- `npx playwright test e2e/figma-reconciliation.spec.ts --config=e2e/playwright.config.ts --project=mobile` failed all six assertions before view reconciliation:
  - Explore still showed fake redemption/deal claims.
  - Deals lacked sample-evidence labelling and claimed live monitoring/active multipliers.
  - Itinerary still rendered the old Singapore JSON fixture.
  - Proof still rendered hardcoded Chase/Amex/ANA values.
  - Wallet/Profile lacked preview-only quarantine and showed fake account/document details.
  - Mobile width overflowed at 390px.

Repairs:

- Rebuilt Explore as three editorial Japan destination compositions with no financial claims.
- Rebuilt Deals from the typed Japan visual fixture and labelled it sample evidence.
- Rebuilt Itinerary from `japanVisualFixture.report`, then deleted the obsolete hand-authored `fixtures.json`.
- Rebuilt Proof from typed `TransferAdvice`.
- Replaced Wallet/Profile with preview-only empty-state anatomy and no fake credentials, balances, sync, or document claims.

Verification:

| Command | Result |
|---|---|
| `npx playwright test e2e/figma-reconciliation.spec.ts --config=e2e/playwright.config.ts --project=chromium --project=mobile` | Passed: 11 passed, 1 skipped |
| `npx vitest run` | Passed: 5 files, 123 tests |
| `npx tsc --noEmit` | Passed |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 15 rules |

## Task 7 — approved stamp direction

Human selection:

- Candidate A was selected by the human on 2026-08-12.
- Candidate B was rejected.
- The human explicitly asked not to generate additional stamp/postmark candidates.

Files:

- Candidate A: `frontend/design/refs/philatelic/candidates/japan-atlas-stamp-a.webp`
- Candidate B: `frontend/design/refs/philatelic/candidates/japan-atlas-stamp-b.webp`
- Metadata: `frontend/design/refs/philatelic/CANDIDATES.md`

Process note:

- The implementation plan names manual Google AI Pro / Nano Banana generation. In this Codex
  session the available zero-cost generation path was the built-in `image_gen` tool. No repository
  API key, runtime generator, MCP, provider configuration, or recurring-cost dependency was added.
- The model name was not exposed by the tool output and is recorded as such in candidate/runtime
  manifests.

## Task 8 — runtime asset

Runtime asset:

- Asset ID: `japan-atlas-01`
- Path: `frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp`
- Format: WebP
- Dimensions: 520×693 px
- Bytes: 96,596
- Manifest: `frontend/public/img/japan/philatelic/MANIFEST.md`

Rights and source summary:

- Original generated candidate selected by the human for this non-commercial student project.
- No third-party archival media item is claimed as a source.
- No commercial clearance is implied; commercial use requires legal/source re-review or rebuild from
  licensed/open sources.

Verification:

| Command | Result |
|---|---|
| `npx vitest run tests/philatelic-asset.test.ts` | Passed: 4 tests |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 15 rules |

Manual visual review:

- Runtime asset remained legible at approximately 180, 220, and 260 CSS pixels.
- No visible watermark, denomination, route, date, year, flag, government seal, postal-service logo,
  airline logo, or copied character was observed.

## Task 9 — typed `DestinationStamp` boundary

Changes:

- Added `frontend/src/lib/design/philatelic-assets.ts` as an explicit allowlist for approved
  philatelic assets.
- Added `frontend/src/components/product/destination-stamp.tsx` as a presentational-only component.
- Added diagnostic specimens to `/theme-proof?theme=japan`.

Boundary confirmation:

- The component does not import the API client, theme resolver, MSW fixture, money helpers, or a
  runtime generator.
- Route and date render as HTML overlay text, not baked into image alt text.
- The ordinary natural landing route does not fetch the philatelic asset.

Verification:

| Command | Result |
|---|---|
| `npx playwright test e2e/destination-stamp.spec.ts --config=e2e/playwright.config.ts --project=chromium --project=mobile --project=reduced-motion` | Passed: 10 passed, 2 skipped |
| `npx tsc --noEmit` | Passed |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 15 rules |

## Task 10 — approved product placements

Changes:

- Japan Explore renders one decorative thumbnail in the Mount Fuji destination card only.
- Japan visual results render one feature artifact only when `ResultsView` receives an explicit
  `destinationArtifact`.
- `/plan` does not pass a destination artifact and does not infer Japan from free-form city strings.
- Deals, Proof, Itinerary, Wallet, Profile, financial panels, provenance bands, and error states do
  not render the stamp.

Latest product-context screenshots:

- `frontend/design/refs/philatelic/gate/explore-390x844.png`
- `frontend/design/refs/philatelic/gate/explore-1440x900.png`
- `frontend/design/refs/philatelic/gate/results-390x844.png`
- `frontend/design/refs/philatelic/gate/results-1440x900.png`

Verification:

| Command | Result |
|---|---|
| `npx playwright test e2e/destination-stamp.spec.ts e2e/japan-philatelic-visual.spec.ts e2e/f3-no-orphan-numbers.spec.ts --config=e2e/playwright.config.ts --project=chromium --project=mobile` | Passed: 20 passed, 4 skipped |
| `npx tsc --noEmit` | Passed |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 15 rules |

## Task 11 — responsive, accessibility, motion, and performance gate

Screenshot matrix:

- Directory: `frontend/design/refs/philatelic/gate/`
- Manifest: `frontend/design/refs/philatelic/gate/MANIFEST.md`
- Viewports: 390×844, 768×1024, 1440×900
- Surfaces: natural landing, Japan Explore, Japan results, reduced-motion Japan results

Task 11 fixes after expanded checks:

- Restored the `/theme-proof` nested theme-token diagnostic swatches required by
  `e2e/f1-theme-scope.spec.ts`.
- Removed nested `main` landmarks from touched frontend pages.
- Corrected heading order in the Explore composition.
- Darkened natural fallback muted/shadow tokens and updated the matching contrast-token test.
- Refreshed stale frontend gate assertions for the current approved landing/kitchen-sink UI.

Focused verification after the initial full-suite failure:

| Command | Result |
|---|---|
| `npx playwright test e2e/f1-theme-scope.spec.ts --config=e2e/playwright.config.ts --project=chromium --project=mobile --project=tablet --project=reduced-motion` | Passed: 4 passed |
| `npx playwright test e2e/f2-wizard.spec.ts e2e/f3-results.spec.ts e2e/f3-no-orphan-numbers.spec.ts e2e/f4-bundle-check.spec.ts e2e/f4-perf-trace.spec.ts --config=e2e/playwright.config.ts --project=tablet --project=reduced-motion` | Passed: 33 passed, 11 skipped |

Ordered frontend gate on 2026-08-12:

| Command | Result |
|---|---|
| `npx tsc --noEmit` | Passed |
| `npx eslint .` | Passed with 0 errors and 16 existing warnings |
| `node scripts/token-lint.mjs` | Passed: 0 violations across 15 rules |
| `npx vitest run` | Passed: 6 files, 127 tests |
| `npm run build` | Passed |
| `npx playwright test --config=e2e/playwright.config.ts` | Passed: 240 passed, 68 skipped |

Production-resource checks covered by Playwright:

- `/` does not fetch GSAP, MapLibre, or Lenis response bodies.
- The natural landing route does not fetch `japan-atlas-stamp-01.webp`.
- A route displaying the stamp keeps the philatelic payload below 250 KB.
- Approved stamp routes produced no console errors or failed asset requests.

Known limitations:

- Japan only.
- Visual fixture only.
- Wallet and Profile remain preview-only.
- Production `/plan` does not infer or render a stamp unless an upstream caller supplies an explicit
  approved destination artifact.

Scope confirmation:

- No backend code was intentionally changed.
- No OpenAPI contract, generated API files, provider/MCP configuration, `docs/specs/`, optimizer
  behavior, or runtime travel-provider integration was intentionally changed.

Git/review status:

- Final reviewed base: `af8a401ac4e468480dc60217929859fb2fc9b412`.
- Final reviewed head: the containing branch head after this report commit; use `git rev-parse HEAD`
  for the exact immutable value.
- A read-only code review was requested after the final commit range existed. The first returned
  Important finding was this report's stale Xcode-license blocker note; this section replaces it
  with the actual final Git/review state.
- Remaining review note classified as Minor: `/theme-proof?theme=japan` intentionally shows separate
  decorative and informative diagnostic stamp specimens for Task 9 accessibility coverage, while
  production placement remains limited to one Explore thumbnail and one explicitly supplied Japan
  visual-results artifact.
