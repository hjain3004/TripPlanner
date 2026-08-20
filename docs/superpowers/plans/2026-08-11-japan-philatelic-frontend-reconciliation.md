# Japan Philatelic Frontend Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile the useful compositions in the saved Figma Make export with the current frontend, repair the known post-J5 design/gate regressions, and add one human-approved historical Atlas Japan stamp as a restrained destination artifact.

**Architecture:** Keep the existing Next.js application, generated API contract, MSW boundary, deterministic rendering rules, and semantic theme system. Extract the existing results renderer into a reusable typed component, provide a type-valid frontend-only Japan visual fixture, and pass an approved philatelic asset into that component explicitly. `DestinationStamp` is presentation-only: it never fetches, generates, infers a country, computes a route, or changes trust state. The production `/plan` path continues to render without a stamp until upstream code can supply an explicit destination artifact; it must not guess Japan from free-form city text.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, Tailwind CSS 4 semantic tokens, Motion for React (existing dependency), MSW, Vitest, Playwright, axe-core, Next Image, manual Google AI Pro/Nano Banana creative generation, optional Inkscape/VTracer/SVGcode cleanup.

## Global Constraints

- Read first: `AGENTS.md`, `DEVIATIONS.md`, the newest root `reports/*.md`, `docs/specs/06_implementation_protocol.md`, `docs/superpowers/specs/2026-08-09-japan-frontend-foundation-design.md`, and `docs/superpowers/specs/2026-08-11-japan-philatelic-figma-reconciliation-design.md`.
- Invoke the available equivalents of `superpowers:using-superpowers`, `superpowers:test-driven-development`, `superpowers:verification-before-completion`, `superpowers:requesting-code-review`, `frontend-design:frontend-design`, `emil-design-eng`, `design:accessibility-review`, `design:design-system-management`, and `review-animations` before their relevant work.
- Work in an isolated `codex/` or feature branch/worktree. Never stage or rewrite unrelated backend/evidence-graph/itinerary work already present in the user's working tree.
- Do not modify `docs/specs/`, `backend/`, `contract/openapi.json`, generated API files, runtime MCP/provider configuration, or optimizer behavior.
- Do not import `design/Premium Travel Itinerary Planner/` wholesale. It is visual/composition reference only.
- USD 0 additional out-of-pocket. Do not add a Gemini key, image API, paid asset, overage-capable service, or runtime generator.
- No frontend money/points arithmetic. Formatting an already-computed minor-unit, basis-point, or micro-unit field for display is allowed; deriving savings, totals, transfer outcomes, or ratios is not.
- Every displayed financial number must come from a type-valid fixture/report artifact and remain covered by the no-orphan-number gate.
- Preserve visible provenance and evidence meaning. A stamp never means verified, paid, booked, transferred, or government approved.
- No black, neon, blurred/glowing shadow, generic hover lift, `transition-all`, or `scale: 0` entrance in touched experiences.
- Poiret One is limited to page-level display roles and approved marks. Never faux-bold it. H2–H6, navigation, money, points, and dense UI use Schibsted Grotesk; metadata uses Roboto Mono.
- Main surfaces are square, use 2px destination-ink rules, and use zero-blur hard offsets. Rounded geometry remains only for semantically round controls/chips/nodes and the stamp artifact.
- All tests follow red → green → refactor. Run the named failing test before implementation and record that it fails for the intended reason.
- Commit only after each task's focused gate is green. Keep behavior repairs separate from visual changes.
- `DEVIATIONS.md` already contains the SCOPE+ entry for this program. Add another row only for a genuinely new judgment call; do not duplicate it.

## Target File and Interface Map

```text
frontend/src/app/plan/page.tsx
  owns intake, polling, and failure state; delegates completed reports
    -> frontend/src/components/product/results-view.tsx
         renders FinalReport in the frozen section order
         accepts an optional ApprovedPhilatelicAsset only from an explicit caller

frontend/src/mocks/japan-visual-fixture.ts
  owns { primaryCountryCode: "JP", report: FinalReport }
    -> kitchen-sink Japan results proof
    -> Figma-reconciled Explore/Deals/Itinerary/Proof previews

frontend/src/lib/design/philatelic-assets.ts
  allowlists reviewed runtime assets
    -> frontend/src/components/product/destination-stamp.tsx
         presentational image + accessible HTML route/date overlay
         no API, theme, fixture, arithmetic, or country inference

frontend/public/img/japan/philatelic/
  sanitized runtime asset + provenance/license/generation manifest

frontend/src/lib/theme/resolver.ts
  null/unknown -> natural; explicit JP -> japan
  no city lookup, locale lookup, network, or LLM
```

The raw Figma export remains outside this graph. It contributes composition references only and is never imported by runtime source.

---

## Task 1: Establish an Honest Baseline and Repair the Bundle Gate

**Files:**

- Delete: `frontend/tests/bundle-check.test.ts`
- Create: `frontend/e2e/r0-initial-route-bundle.spec.ts`
- Create: `reports/frontend_japan_philatelic_reconciliation.md` (initial baseline section only)

The current Vitest test scans every emitted chunk and therefore fails merely because a deliberately lazy GSAP chunk exists. The actual requirement is that heavy optional libraries are not fetched by the initial landing route.

- [ ] **Step 1: Capture the branch and baseline without changing code**

From the repository root:

```bash
git status --short --branch
cd frontend
npx tsc --noEmit
node scripts/token-lint.mjs
npx vitest run
npm run build
```

Record exact pass/fail counts and the GSAP mismatch in the baseline section of `reports/frontend_japan_philatelic_reconciliation.md`. Do not describe a historical report as a fresh run.

- [ ] **Step 2: Write the failing initial-route resource test**

Create `frontend/e2e/r0-initial-route-bundle.spec.ts`. The test must:

1. subscribe to JavaScript responses before navigation;
2. open `/` in the Chromium desktop project;
3. wait for `networkidle`;
4. inspect only JavaScript resources actually requested by that page;
5. fail if their response bodies contain package markers for `gsap`, `maplibre-gl`, or `lenis`;
6. assert at least one first-party Next chunk was inspected, so a broken collector cannot pass vacuously.

Use response bodies, not hashed filenames, and ignore browser extensions/non-local origins. The test must not click into `/plan` or trigger lazy result animation.

- [ ] **Step 3: Prove the new test describes the intended gate**

Temporarily include a marker known to exist in a requested landing chunk or invert one assertion, then run:

```bash
npx playwright test e2e/r0-initial-route-bundle.spec.ts --project=chromium
```

Confirm it fails for that marker. Remove the deliberate failure immediately.

- [ ] **Step 4: Retire the invalid all-chunks assertion**

Delete `frontend/tests/bundle-check.test.ts`; do not weaken it into an always-green build-exists check. The Playwright test is the replacement because it measures the actual initial route.

- [ ] **Step 5: Run the focused gate**

```bash
npm run build
npx vitest run
npx playwright test e2e/r0-initial-route-bundle.spec.ts --project=chromium
```

Expected: production build succeeds; Vitest no longer has the false GSAP failure; the landing-route resource test passes while lazy chunks remain allowed.

- [ ] **Step 6: Commit the gate repair**

```bash
git add frontend/tests/bundle-check.test.ts frontend/e2e/r0-initial-route-bundle.spec.ts reports/frontend_japan_philatelic_reconciliation.md
git commit -m "test: measure initial route bundle honestly"
```

---

## Task 2: Repair Theme Resolution and the Responsive Preview Shell

**Files:**

- Modify: `frontend/src/lib/theme/resolver.ts`
- Create: `frontend/tests/theme-resolver.test.ts`
- Modify: `frontend/src/app/layout.tsx`
- Modify: `frontend/src/app/theme-proof/page.tsx`
- Modify: `frontend/src/app/kitchen-sink/page.tsx`
- Create: `frontend/e2e/japan-shell.spec.ts`

- [ ] **Step 1: Write resolver tests first**

`frontend/tests/theme-resolver.test.ts` must assert:

```ts
expect(resolveTheme(null).globalTheme).toBe("natural");
expect(resolveTheme("JP").globalTheme).toBe("japan");
expect(resolveTheme("jp").globalTheme).toBe("japan");
expect(resolveTheme("US").globalTheme).toBe("natural");
expect(resolveTheme("ZZ").globalTheme).toBe("natural");
```

It must also confirm the normalized primary code is returned and `secondaryCountryCodes` is an empty array until explicit secondary inputs exist.

- [ ] **Step 2: Run the resolver test and observe the current failure**

```bash
npx vitest run tests/theme-resolver.test.ts
```

Expected failure: null/unknown currently resolve to Japan because of the unconditional testing override.

- [ ] **Step 3: Implement deterministic allowlisted resolution**

In `resolver.ts`, trim and uppercase the input. Return Japan only for `JP`; otherwise return natural. Do not add city-name guessing, browser locale, an LLM, geolocation, or a network lookup.

- [ ] **Step 4: Remove the global Japan testing override**

In `layout.tsx`, apply `resolveTheme(null)` to the root shell. The app must start in `theme-natural` before a destination is explicitly known.

Keep `/theme-proof` as a deliberate proof route: `?theme=japan` passes `JP`; `?theme=natural` passes null. Use the App Router's current async `searchParams` contract if required by the installed Next version.

- [ ] **Step 5: Make the kitchen-sink theme explicit and the navigation responsive**

Replace hardcoded `theme-singapore` with the class returned by `resolveTheme("JP")`.

For widths below 960px, replace the seven-button strip with one labelled native select or one accessible disclosure menu. Requirements:

- 44px minimum target height;
- visible focus ring;
- current preview name is announced;
- no horizontal scrolling at 390px;
- desktop buttons remain real buttons with `aria-pressed`;
- Wallet and Profile labels include `Preview` so they cannot be mistaken for shipping account features.

Do not add a new navigation dependency.

- [ ] **Step 6: Add shell E2E assertions**

`japan-shell.spec.ts` must verify:

- `/` root element computes the natural theme;
- `/theme-proof?theme=japan` computes Japan tokens;
- `/kitchen-sink` uses Japan, not Singapore;
- mobile navigation changes from Proof to Explore with no horizontal overflow;
- desktop tab buttons expose the selected state.

- [ ] **Step 7: Run focused checks**

```bash
npx vitest run tests/theme-resolver.test.ts
npx playwright test e2e/japan-shell.spec.ts --project=chromium --project=mobile
npx tsc --noEmit
node scripts/token-lint.mjs
```

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/theme/resolver.ts frontend/tests/theme-resolver.test.ts frontend/src/app/layout.tsx frontend/src/app/theme-proof/page.tsx frontend/src/app/kitchen-sink/page.tsx frontend/e2e/japan-shell.spec.ts
git commit -m "fix: restore deterministic Japan theme scope"
```

---

## Task 3: Reconcile the Editable Design Contract and Mechanical Guardrails

**Files:**

- Modify: `frontend/design/CONTRACT.md`
- Modify: `frontend/scripts/token-lint.mjs`
- Modify: `frontend/tests/contrast.test.ts`
- Create: `frontend/tests/design-drift.test.ts`
- Modify: `frontend/src/app/theme-proof/page.tsx`
- Modify: `frontend/src/components/product/SharedUI.tsx`
- Modify: `frontend/src/components/product/Illustrations.tsx`
- Modify: `frontend/src/components/product/verdict-header.tsx`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`

- [ ] **Step 1: Correct the stale editable contract before styling pages**

Update `frontend/design/CONTRACT.md` so it points to the 2026-08-09 and 2026-08-11 approved documents and accurately states:

- Poiret One, 3px stroke, page hero/H1 only;
- Schibsted Grotesk for H2–H6 and all functional/numeric text;
- Roboto Mono for metadata only;
- Japan Quiet Blossom is the golden pack and natural is fallback;
- square 2px principal surfaces and zero-blur offsets;
- no black/neon;
- Figma export is reference-only;
- philately is Japan-only and follows the placement contract.

Remove the obsolete Bodoni/Singapore/soft-shell instructions rather than leaving two contradictory sections.

- [ ] **Step 2: Add failing design-drift checks**

`frontend/tests/design-drift.test.ts` must scan product/app source (excluding `components/ui` vendor internals) and fail on:

- `transition-all`;
- Tailwind `black`, `bg-black`, `text-black`, `border-black`, or raw `#000` variants;
- `font-display` combined with `font-bold`, `font-semibold`, or numeric-value containers in the same class string;
- `initial={{ scale: 0` in touched product/app source;
- a `canvas-confetti` import.

Extend `token-lint.mjs` only for rules that are stable across the whole frontend. Keep file-specific typography assertions in `design-drift.test.ts` to avoid brittle lint heuristics.

- [ ] **Step 3: Run the new test and list every current violation**

```bash
npx vitest run tests/design-drift.test.ts
```

The current Explore, SharedUI, theme proof, Proof animation, and confetti paths should make it fail. Preserve this output in the milestone report's baseline table.

- [ ] **Step 4: Remove generic motion and faux display weight**

Replace `transition-all` with explicit color/border/transform transitions. Replace `scale: 0` entry states with opacity plus at most 8–10px translation, with immediate final state under reduced motion. Do not remove press feedback.

Make H2–H6 and card titles Schibsted. Keep `font-display display-hero` only on page H1/approved large mark, without `font-bold` or `font-semibold`.

- [ ] **Step 5: Remove confetti and the dependency**

Delete confetti behavior from `verdict-header.tsx`. The plan-issued stamp reveal later becomes the single restrained celebration. Remove `canvas-confetti` and its type package through npm so both package files remain synchronized:

```bash
npm uninstall canvas-confetti @types/canvas-confetti
```

Do not replace confetti with another effect.

- [ ] **Step 6: Repair the theme-proof specimen**

Make it accurately demonstrate square 2px panels, hard offsets, explicit transitions, correct type roles, and Japan/natural toggles. It is a proof surface, not a new product page.

- [ ] **Step 7: Run guardrails**

```bash
npx vitest run tests/design-drift.test.ts tests/contrast.test.ts
node scripts/token-lint.mjs
npx tsc --noEmit
```

- [ ] **Step 8: Commit docs and mechanical repairs**

```bash
git add frontend/design/CONTRACT.md frontend/scripts/token-lint.mjs frontend/tests/contrast.test.ts frontend/tests/design-drift.test.ts frontend/src/app/theme-proof/page.tsx frontend/src/components/product/SharedUI.tsx frontend/src/components/product/Illustrations.tsx frontend/src/components/product/verdict-header.tsx frontend/package.json frontend/package-lock.json
git commit -m "refactor: enforce Japan frontend design contract"
```

---

## Task 4: Extract a Reusable Typed Results Surface and Eliminate Derived Savings

**Files:**

- Create: `frontend/src/components/product/results-view.tsx`
- Modify: `frontend/src/app/plan/page.tsx`
- Modify: `frontend/src/components/product/verdict-header.tsx`
- Modify: `frontend/e2e/f3-results.spec.ts`
- Modify: `frontend/e2e/f3-no-orphan-numbers.spec.ts`

- [ ] **Step 1: Add a failing regression for frontend-derived savings**

In `f3-results.spec.ts`, assert the verdict renders the report's `savings_pct_bp` as a formatted percentage and does not render a currency savings figure derived from `gross_minor - effective_cost_minor`.

Do not change fixture values to make this pass.

- [ ] **Step 2: Run the focused E2E and see the failure**

```bash
npx playwright test e2e/f3-results.spec.ts --project=chromium -g "verdict"
```

- [ ] **Step 3: Extract `ResultsView` without changing section order**

Move the current results renderer and its `Row` helper from `app/plan/page.tsx` into `components/product/results-view.tsx`.

Use this contract:

```ts
type ResultsViewProps = {
  report: FinalReport;
  onRetry?: () => void;
};
```

Task 9 will add the optional artifact prop after its type exists. `/plan` calls `ResultsView` with the report and retry handler only. The extraction must preserve loading, polling, error, section ordering, provenance, and generated API types.

- [ ] **Step 4: Remove the currency savings derivation**

`VerdictHeader` must show gross cost, effective cost, and the already-provided `savings_pct_bp` as a formatted percentage. It must not subtract fields. Keep `MoneyText` render-only.

If formatting basis points is shared, create a pure display formatter that converts the supplied storage unit to its written form; do not compute a business outcome.

- [ ] **Step 5: Tighten no-orphan-number coverage**

Remove the existing broad exception that accepts any positive currency difference merely because it could have been derived. Every currency value must match an actual `_minor` field in the fixture. Keep explicit allowances only for storage-unit formatting and structural day indices.

- [ ] **Step 6: Run regression checks**

```bash
npx tsc --noEmit
npx vitest run tests/contract.test.ts
npx playwright test e2e/f3-results.spec.ts e2e/f3-no-orphan-numbers.spec.ts --project=chromium
```

- [ ] **Step 7: Commit the behavior repair separately**

```bash
git add frontend/src/components/product/results-view.tsx frontend/src/app/plan/page.tsx frontend/src/components/product/verdict-header.tsx frontend/e2e/f3-results.spec.ts frontend/e2e/f3-no-orphan-numbers.spec.ts
git commit -m "refactor: share typed results rendering"
```

---

## Task 5: Create a Type-Valid Japan Visual Fixture Without Changing the API

**Files:**

- Create: `frontend/src/mocks/japan-visual-fixture.ts`
- Modify: `frontend/src/mocks/handlers.ts`
- Modify: `frontend/tests/contract.test.ts`
- Create: `frontend/tests/japan-visual-fixture.test.ts`
- Modify: `frontend/src/app/kitchen-sink/views/RegisterSpecimenView.tsx`

- [ ] **Step 1: Define the frontend-only wrapper test**

The fixture module must expose a wrapper, not add fields to `FinalReport`:

```ts
type DestinationVisualFixture = {
  id: "japan-golden";
  primaryCountryCode: "JP";
  report: FinalReport;
};
```

Tests must parse `report` through the existing Zod schema, assert `primaryCountryCode === "JP"`, and assert every provenance-bearing invented inventory item is marked sample/estimated and `needs_verification` where the contract supports it.

- [ ] **Step 2: Run the absent-fixture test and observe failure**

```bash
npx vitest run tests/japan-visual-fixture.test.ts
```

- [ ] **Step 3: Build the Japan visual fixture from generated types**

Create an India→Japan visual report using only existing `FinalReport` fields and `satisfies FinalReport`. Use an explicit airport/city representation consistently (for example `DEL` → `TYO`) and a fixed future date. Every money/points number must be a literal field in this fixture; no component may invent a figure later.

Rules:

- This is sample visual evidence, not a backend golden or live quote.
- Do not name a provider that was not actually queried.
- Source URLs may be empty only where the existing contract permits it, paired with visible sample/verification status.
- Verify-before-transfer remains checklist step one.
- Do not claim account synchronization, seat availability, or a live offer.

Expose it through `fixtureHandlers.japanVisualReport()` only for test/preview use. Do not make it the default MSW response for ordinary `/plan` submissions.

- [ ] **Step 4: Turn Register Specimen into the Japan results proof**

Replace its hand-authored assignments and money strings with the shared `ResultsView` plus `japanVisualFixture.report`. Rename visible copy to `Japan results preview` and clearly label it `Frontend visual fixture · sample data`.

The preview wrapper passes `resolveTheme(japanVisualFixture.primaryCountryCode)`; the report itself remains API-valid and unmodified.

- [ ] **Step 5: Run fixture and contract gates**

```bash
npx vitest run tests/japan-visual-fixture.test.ts tests/contract.test.ts
npx tsc --noEmit
node scripts/token-lint.mjs
```

- [ ] **Step 6: Commit fixture and proof wiring**

```bash
git add frontend/src/mocks/japan-visual-fixture.ts frontend/src/mocks/handlers.ts frontend/tests/contract.test.ts frontend/tests/japan-visual-fixture.test.ts frontend/src/app/kitchen-sink/views/RegisterSpecimenView.tsx
git commit -m "test: add typed Japan visual results fixture"
```

---

## Task 6: Reconcile Explore, Deals, Itinerary, Proof, Wallet, and Profile

**Files:**

- Modify: `frontend/src/app/kitchen-sink/views/ExploreView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/DealsView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/ItineraryView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/ProofView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/WalletView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/ProfileView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/RegisterSpecimenView.tsx`
- Modify: `frontend/src/components/product/SharedUI.tsx`
- Modify or delete if no longer needed: `frontend/src/mocks/fixtures.json`
- Create: `frontend/e2e/figma-reconciliation.spec.ts`

- [ ] **Step 1: Write behavior/content assertions before visual refactoring**

The E2E test must verify:

- Explore contains three destination compositions but no fake redemption count or fake hotel deal;
- Deals identifies its report as sample evidence and contains no `constantly monitor`, `active bonus`, or invented expiry claim;
- Itinerary uses report/fixture values and displays provenance/sample status;
- Proof renders a source → partner → redemption chain from `TransferAdvice`, not hardcoded Chase/Amex/ANA figures;
- Wallet and Profile visibly say `Preview only` and do not show masked card digits, fake sync timestamps, passport storage, or fabricated account balances;
- all six views fit 390px without document overflow.

- [ ] **Step 2: Run the test and confirm current failures**

```bash
npx playwright test e2e/figma-reconciliation.spec.ts --project=mobile
```

- [ ] **Step 3: Reconcile Explore**

Keep the three-part discovery rhythm and existing Japan illustrations. Convert containers to square, ruled editorial surfaces. Remove generic hover lift, floating circular action buttons, false financial claims, and cursor affordances from non-interactive cards. Use calm descriptive copy; no stamp yet.

- [ ] **Step 4: Reconcile Deals**

Keep the asymmetric lead-story + narrow rail composition. Feed it from `japanVisualFixture.report.transfer_advice` or another existing type-valid sample report. Label evidence meaning visibly. If the fixture does not contain an active multiplier, do not invent one for the rail; show `No verified live bonuses in this sample` or fixture-backed transfer paths instead.

- [ ] **Step 5: Reconcile Itinerary**

Use the normalized report fixture and existing `RouteNode`, `ItineraryTimeline`, `DecisionLedger`, `MoneyText`, and provenance primitives. Preserve the route spine. Remove the separate JSON source if all consumers migrate; otherwise give it an explicit typed schema and honest sample provenance. Do not claim `AwardHacker API`, Amex FHR credit, or live hotel prices unless those exact facts exist in the typed fixture.

- [ ] **Step 6: Rebuild Proof from typed transfer artifacts**

Render the first non-dominated plan's source currency, `TransferStep` nodes, award program/route, provided amounts, and provenance. Empty/NO_DATA/PAY_CASH states must use honest copy. Replace blank `scale: 0` nodes with line draw plus opacity/translation and immediate reduced-motion state.

- [ ] **Step 7: Quarantine Wallet and Profile as previews**

Retain their broad composition only. Replace fake accounts, balances, PAN digits, sync status, passport details, and security claims with labelled empty-state anatomy. Mention that specs 17/18 must land before accounts and acquisition behavior. No functional-looking control may imply that a connection exists.

- [ ] **Step 8: Run reconciliation gates**

```bash
npx playwright test e2e/figma-reconciliation.spec.ts --project=chromium --project=mobile
npx vitest run
npx tsc --noEmit
node scripts/token-lint.mjs
```

- [ ] **Step 9: Commit the composition reconciliation**

```bash
git add frontend/src/app/kitchen-sink/views frontend/src/components/product/SharedUI.tsx frontend/src/mocks/fixtures.json frontend/e2e/figma-reconciliation.spec.ts
git commit -m "feat: reconcile Figma travel compositions"
```

If `fixtures.json` was deleted, stage the deletion explicitly. Never stage the raw Figma export.

---

## Task 7: Generate Two Japan Stamp Candidates and Stop for Human Approval

**Files:**

- Reference: `frontend/design/refs/philatelic/japan-atlas-stamp-concept.webp`
- Create: `frontend/design/refs/philatelic/candidates/japan-atlas-stamp-a.webp`
- Create: `frontend/design/refs/philatelic/candidates/japan-atlas-stamp-b.webp`
- Create: `frontend/design/refs/philatelic/CANDIDATES.md`

This is a manual creative task. It is deliberately a hard checkpoint.

- [ ] **Step 1: Use the locked prompt without reinterpretation**

Copy the exact Nano Banana master prompt from section 9.2 of `docs/superpowers/specs/2026-08-11-japan-philatelic-figma-reconciliation-design.md`. Use the existing Google AI Pro subscription manually. Generate exactly two serious candidates. Vary composition only; keep style, palette, semantics, sparse text, and negative-space requirements fixed.

- [ ] **Step 2: Record generation metadata immediately**

In `CANDIDATES.md`, record for each candidate:

- product/model name shown by the tool;
- generation date;
- exact prompt;
- whether an input/reference image was used;
- visible watermark status;
- malformed text/logos/symbols noticed;
- intended cleanup path;
- local high-resolution source location (do not put a multi-megabyte source in runtime assets).

- [ ] **Step 3: Perform a safety and cultural review**

Reject any candidate containing a real denomination, flag, government seal, postal/airline logo, anime/geisha/samurai cliché, black ink, neon, fake route/date/year, copied modern stamp, malformed `ATLAS`/`JAPAN`, or ambiguous watermark.

- [ ] **Step 4: Show both candidates in context**

Create non-production comparison boards at 390 and 1440px using screenshots/composites of the actual Explore and Japan results surfaces. Do not integrate either candidate into code yet.

- [ ] **Step 5: Stop and request one explicit human selection**

Ask the human to choose A, B, or reject both. Do not continue to Task 8 until the human approves one composition. A watermarked generation may only be a composition reference; it cannot be selected as the production asset.

- [ ] **Step 6: Commit only approved-size reference previews and metadata**

After human selection:

```bash
git add frontend/design/refs/philatelic/candidates frontend/design/refs/philatelic/CANDIDATES.md
git commit -m "design: select Japan philatelic composition"
```

Do not commit high-resolution working files if they are large. Preserve them in the ignored design pipeline path documented in `CANDIDATES.md`.

---

## Task 8: Produce, Sanitize, and Manifest the Runtime Asset

**Files:**

- Create: `frontend/public/img/japan/philatelic/japan-atlas-stamp-01.svg` **or** responsive `.webp`/`.avif` output(s)
- Create: `frontend/public/img/japan/philatelic/MANIFEST.md`
- Create: `frontend/tests/philatelic-asset.test.ts`
- Optionally create: `frontend/scripts/check-philatelic-assets.mjs`

- [ ] **Step 1: Write the failing asset gate before adding production art**

The test/script must fail when the production file or manifest is absent and must enforce:

- SVG ≤ 200 KB, or each largest responsive raster ≤ 160 KB;
- total initial philatelic payload < 250 KB;
- no `<script>`, event-handler attributes, `foreignObject`, external `http(s)` references, embedded fonts, or unreviewed base64 raster inside SVG;
- manifest contains every field listed in design spec section 9.4;
- output path in the manifest exists;
- for SVG, only `ATLAS` and `JAPAN` may appear as baked product words; no route/date/year/denomination. Raster text is a recorded manual visual-review item because a byte-level unit test cannot reliably inspect it.

- [ ] **Step 2: Run the gate and observe the missing-asset failure**

```bash
npx vitest run tests/philatelic-asset.test.ts
```

- [ ] **Step 3: Build the production asset from the approved candidate**

If the approved candidate is clean and the tool permits use, manually correct malformed type and optimize it. If it is watermarked or unsuitable as final output, use it only as layout reference and rebuild from original vector work plus reviewed CC0/Public Domain sources.

For every archival source, visit the original item page and record its rights statement. Search-result thumbnails and aggregators are never license evidence.

Choose efficient SVG only if engraving remains clean after node reduction. Otherwise use responsive WebP/AVIF. Never force a multi-megabyte autotrace into the app.

- [ ] **Step 4: Complete the manifest**

Populate all fields from the spec, including exact prompt and transformation history. For original work, say so explicitly rather than inventing a source URL. Record final byte sizes from disk.

- [ ] **Step 5: Run security and budget checks**

```bash
npx vitest run tests/philatelic-asset.test.ts
node scripts/token-lint.mjs
```

Also open the final asset at roughly 180, 220, and 260 CSS pixels. It must remain legible and cannot rely on text smaller than the browser-rendered HTML overlay.

- [ ] **Step 6: Commit the asset separately**

```bash
git add frontend/public/img/japan/philatelic frontend/tests/philatelic-asset.test.ts frontend/scripts/check-philatelic-assets.mjs
git commit -m "assets: add reviewed Japan Atlas stamp"
```

If the optional script was not created, omit it from the add command.

---

## Task 9: Implement the Typed `DestinationStamp` Presentation Boundary

**Files:**

- Create: `frontend/src/lib/design/philatelic-assets.ts`
- Create: `frontend/src/components/product/destination-stamp.tsx`
- Create: `frontend/e2e/destination-stamp.spec.ts`
- Modify: `frontend/src/app/theme-proof/page.tsx`
- Modify: `frontend/src/themes/base.css` only if a reusable semantic animation utility is required

- [ ] **Step 1: Define the approved asset registry**

Use a readonly type similar to:

```ts
export type ApprovedPhilatelicAsset = {
  id: "japan-atlas-01";
  countryCode: "JP";
  src: string;
  width: number;
  height: number;
  alt: string;
};
```

Export an explicit `JAPAN_ATLAS_STAMP` constant. Do not add a dynamic loader, URL input, filesystem lookup, runtime generator, or user-provided source.

- [ ] **Step 2: Write component E2E cases first**

Add one clearly labelled diagnostic specimen to `/theme-proof?theme=japan`, then test:

- decorative mode produces empty alt and avoids duplicate announcement;
- informative mode has concise alt;
- `routeLabel` and `dateLabel` render as real HTML text;
- no route/date is baked into the image element's alt;
- no postmark obscures the route/date at 200% zoom;
- reduced motion leaves the complete artifact visible;
- asset is not fetched on the ordinary natural landing route.

- [ ] **Step 3: Run the E2E and observe absence**

```bash
npx playwright test e2e/destination-stamp.spec.ts --project=chromium --project=reduced-motion
```

- [ ] **Step 4: Implement one small presentation component**

Required props:

```ts
type DestinationStampProps = {
  asset: ApprovedPhilatelicAsset;
  size: "thumbnail" | "feature";
  decorative?: boolean;
  routeLabel?: string;
  dateLabel?: string;
  issued?: boolean;
};
```

Use `next/image` for raster art or a reviewed local SVG through an image element. Do not inline the generated SVG into TSX. Render route/date in a positioned HTML cartouche and a separate decorative postmark layer. The component must not import the API client, theme resolver, MSW fixture, or money helpers.

`issued` may trigger one 450–650ms settle of at most 8px and a `0.97 → 1` postmark. Never use bounce, spin, confetti, perpetual motion, or `scale: 0`. Server markup must remain visible before hydration.

The theme-proof specimen is a component harness, not a product placement. Keep it under a heading such as `Philatelic artifact proof`; Task 10 will wire the two approved product placements.

- [ ] **Step 5: Run focused gates**

```bash
npx playwright test e2e/destination-stamp.spec.ts --project=chromium --project=mobile --project=reduced-motion
npx tsc --noEmit
node scripts/token-lint.mjs
```

- [ ] **Step 6: Commit the component boundary**

```bash
git add frontend/src/lib/design/philatelic-assets.ts frontend/src/components/product/destination-stamp.tsx frontend/e2e/destination-stamp.spec.ts frontend/src/app/theme-proof/page.tsx frontend/src/themes/base.css
git commit -m "feat: add typed destination stamp artifact"
```

If `base.css` did not change, omit it from the add command.

---

## Task 10: Integrate the Stamp Only at Approved Japan Placements

**Files:**

- Modify: `frontend/src/app/kitchen-sink/views/ExploreView.tsx`
- Modify: `frontend/src/app/kitchen-sink/views/RegisterSpecimenView.tsx`
- Modify: `frontend/src/components/product/results-view.tsx`
- Modify: `frontend/src/app/theme-proof/page.tsx`
- Modify: `frontend/e2e/destination-stamp.spec.ts`
- Create: `frontend/e2e/japan-philatelic-visual.spec.ts`

- [ ] **Step 1: Add failing placement assertions**

Assert exactly:

- one thumbnail in Japan Explore;
- one feature artifact at the Japan visual result's plan-issued/cover moment;
- route and date match `japanVisualFixture.report` fields;
- zero stamps on Wallet, Deals, Proof, payment strategy, transfer panels, provenance bands, errors, and natural landing;
- no stamp repeats as wallpaper or on every itinerary day.

- [ ] **Step 2: Run and observe failure**

```bash
npx playwright test e2e/japan-philatelic-visual.spec.ts --project=chromium
```

- [ ] **Step 3: Integrate Explore thumbnail**

Place the thumbnail as part of the first Japan destination card's composition. It is decorative if the adjacent HTML already says Japan/Mount Fuji. Keep it subordinate to the heading and interaction.

- [ ] **Step 4: Integrate the Japan plan-issued artifact**

`ResultsView` renders a feature stamp only when the caller supplies `destinationArtifact`. `RegisterSpecimenView` supplies `JAPAN_ATLAS_STAMP` plus route/date copied from the visual fixture. `/plan` supplies no artifact and therefore performs no city-country guess.

Use existing report fields for the overlay:

- route: explicit origin/destination from the report or award artifact;
- date: `trip_spec.start_date`;
- no generated year, postmark code, or invented airport pair.

- [ ] **Step 5: Keep theme proof purely diagnostic**

The theme-proof route may show the asset once under a clearly labelled `Philatelic artifact proof` section. Do not make it the product landing page.

- [ ] **Step 6: Run placement and no-orphan gates**

```bash
npx playwright test e2e/destination-stamp.spec.ts e2e/japan-philatelic-visual.spec.ts e2e/f3-no-orphan-numbers.spec.ts --project=chromium --project=mobile
npx tsc --noEmit
node scripts/token-lint.mjs
```

- [ ] **Step 7: Commit integration**

```bash
git add frontend/src/app/kitchen-sink/views/ExploreView.tsx frontend/src/app/kitchen-sink/views/RegisterSpecimenView.tsx frontend/src/components/product/results-view.tsx frontend/src/app/theme-proof/page.tsx frontend/e2e/destination-stamp.spec.ts frontend/e2e/japan-philatelic-visual.spec.ts
git commit -m "feat: blend Japan philately into travel surfaces"
```

---

## Task 11: Full Responsive, Accessibility, Motion, and Performance Gate

**Files:**

- Modify: `frontend/e2e/japan-philatelic-visual.spec.ts`
- Modify as failures require: touched frontend files only
- Create: `frontend/design/refs/philatelic/gate/MANIFEST.md`
- Create screenshots under: `frontend/design/refs/philatelic/gate/`
- Complete: `reports/frontend_japan_philatelic_reconciliation.md`

- [ ] **Step 1: Capture the required visual matrix**

Capture landing, Japan Explore, Japan results hero/itinerary, and reduced-motion Japan results at:

- 390×844;
- 768×1024;
- 1440×900.

Use stable fixture data, disable nondeterministic dates/timers, and name files by route/surface/viewport. Add a manifest with command, fixture ID, commit SHA, viewport, and what each image proves.

- [ ] **Step 2: Run keyboard and axe checks**

Verify:

- preview navigation, buttons, disclosures, and result actions work by keyboard;
- focus is always visible;
- logical heading order and landmarks remain intact;
- stamp art does not duplicate or replace required text;
- no blocking axe violations on landing, Explore, and Japan results;
- 200% zoom causes no overlap or hidden content.

- [ ] **Step 3: Run reduced-motion checks**

Every `[data-motion]` element and the stamp must be visible and stable. There must be no `scale: 0`, blank proof canvas, delayed essential text, confetti, or looping decorative animation.

- [ ] **Step 4: Run the complete frontend gate in this order**

```bash
cd frontend
npx tsc --noEmit
npx eslint .
node scripts/token-lint.mjs
npx vitest run
npm run build
npx playwright test
```

Then rerun the production build immediately before any build-dependent bundle assertion if the test runner does not do so itself.

- [ ] **Step 5: Inspect actual production resources**

Confirm:

- no GSAP, MapLibre, or Lenis response is fetched on `/`;
- philatelic payload stays under 250 KB on a route that displays it;
- natural landing does not fetch the Japan asset;
- no new runtime generator/API dependency exists;
- no console error, hydration warning, or failed asset request appears.

- [ ] **Step 6: Complete the milestone report**

The root report must contain:

- branch and commit range;
- baseline failures and their resolution;
- exact commands with fresh pass counts;
- before/after screenshot links;
- asset ID, rights summary, prompt/model, final format/bytes;
- known limitations: Japan only, visual fixture only, Wallet/Profile preview-only, production `/plan` does not infer a stamp;
- explicit confirmation that backend/API/MCP/provider behavior did not change;
- any new deviations with links to their entries.

- [ ] **Step 7: Request code review and address findings**

Invoke `superpowers:requesting-code-review`. Review for Tier-F arithmetic/provenance violations, asset safety, responsive overflow, SSR visibility, and scope drift. Apply fixes in focused commits and rerun affected gates.

- [ ] **Step 8: Final commit**

```bash
git add frontend/design/refs/philatelic/gate reports/frontend_japan_philatelic_reconciliation.md
git commit -m "docs: record Japan philatelic frontend gate"
```

Do not merge, push, publish, or deploy unless the human explicitly asks.

---

## Human Review Checkpoints

Implementation is not autonomous across these checkpoints:

1. **After Task 6:** show the reconciled Figma-derived pages at 390 and 1440 before philatelic art is integrated. Fix obvious composition drift first.
2. **During Task 7:** human selects candidate A/B or rejects both.
3. **After Task 10:** human reviews the stamp in actual Explore and Japan results screenshots, not an isolated artboard.
4. **After Task 11:** human confirms the artifact feels native and restrained before any merge.

## Definition of Done

- The full frontend gate is freshly green.
- The false all-chunks bundle assertion has been replaced with a real initial-route resource gate.
- Natural is the deterministic fallback; Japan is explicitly selected; kitchen-sink mobile navigation does not overflow.
- Editable frontend documentation no longer contradicts the approved Poiret/Japan/neo-brutalist direction.
- Explore, Deals, Itinerary, and Proof use honest typed/sample content and the strongest Figma compositions without importing the Figma app.
- Wallet/Profile are visibly non-shipping previews with no fake account theatre.
- One reviewed, manifested, sanitized, budget-compliant Atlas Japan stamp exists.
- Stamp placement is limited to Japan Explore and the frontend Japan results proof; natural landing and financial/trust surfaces contain none.
- Production `/plan` does not infer a country or stamp from a city string.
- No backend, API contract, MCP, provider, optimizer, account, or commercial/deployment behavior changed.
- A later model can add another destination only by creating an approved theme/artifact pack and explicit typed selection—not by forking product components.
