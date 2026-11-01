# Japan Philatelic Split Landing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the additive Japan philatelic frontend layer from the stranded `codex/japan-philatelic-reconciliation` branch onto `main`, while explicitly deferring that branch's `plan/page.tsx` refactor, which `main`'s F5/F5.1 editable-itinerary work has superseded.

**Architecture:** The stranded branch is 13 commits, last touched 2026-08-12, now 249 commits behind `main`. Its commits are interdependent — cherry-picking cascades (verified empirically: only 4 of 13 apply clean, and later failures are caused by earlier skips, not by real conflicts). So this plan does **not** cherry-pick. It re-applies the branch's *final file states* onto `main` in dependency order, one reviewable task per concern, each with its own test cycle. The one genuinely superseded piece — rewiring `frontend/src/app/plan/page.tsx` to the extracted `results-view.tsx` — is carved out entirely and left for a separate future plan.

**Tech Stack:** Next.js (App Router) + TypeScript strict, Tailwind with semantic `--th-*` design tokens, Vitest (unit), Playwright (e2e + axe), a custom `scripts/token-lint.mjs` design-token linter, `next/font/google` for typography.

---

## Global Constraints

Copied from `CLAUDE.md` / `AGENTS.md`; every task's requirements implicitly include these.

- **This is a frontend-only plan.** Do not touch `backend/`, `contract/openapi.json`, any golden test, or any money math. If a task appears to require a backend change, stop and report — that is out of scope.
- **Never compute money on the frontend.** Render fields from the API; never derive, sum, or reformat a monetary or points value.
- **Provenance must survive.** `TrustChip` / provenance fields (`source_url`, `last_verified`, `verified_by`, `needs_verification`, `confidence`) must keep rendering. Never style them away.
- **Never use `localStorage` or `sessionStorage`.** Never commit secrets.
- **Semantic tokens only.** No raw color literals in product/app source, no `#000`/`bg-black`/`text-black`/`border-black`, no neon/glow, no blurred shadows. `scripts/token-lint.mjs` enforces this and must stay at 0 violations.
- **Tier-F changes require a `DEVIATIONS.md` row** with columns `date, doc§, question, decision, rationale, affected_files`. Task 8 covers the one Tier-F row this plan needs.
- **Behavior changes and refactors are separate commits.** Frontend gate green between them.
- **Any feature not in the specs needs a `SCOPE+` DEVIATIONS entry, and the default answer is no.** This plan adds no new features — it lands already-specified, already-reviewed work.
- **Do not re-derive visual direction.** It is settled. The authoritative specs are on `main` already:
  - `docs/superpowers/specs/2026-08-09-japan-frontend-foundation-design.md`
  - `docs/superpowers/specs/2026-08-11-japan-philatelic-figma-reconciliation-design.md`
  - `docs/superpowers/plans/2026-08-11-japan-philatelic-frontend-reconciliation.md` (the original plan; this document is its salvage successor)

---

## Context: what was actually found

Read this before starting. It is the reason the plan is shaped the way it is, and it corrects two intuitions that would otherwise send you down the wrong path.

**1. `main` is already half-migrated to the philatelic direction.** This was not obvious. `main` already contains:
- `frontend/src/themes/japan.css` — **byte-identical** to the branch's version
- `frontend/src/app/layout.tsx` loading **Poiret One** (the philatelic display face)
- both Japan design specs and the original plan
- `frontend/design/refs/philatelic/japan-atlas-stamp-concept.webp`

So the visual direction is not a pending decision. Parts of it shipped through another route.

**2. `main`'s `frontend/design/CONTRACT.md` is stale documentation, not a competing contract.** It still describes the F1 system (Bodoni Moda display) while `main`'s own `layout.tsx` loads Poiret One. The branch's `CONTRACT.md` describes what `main` already does. Updating it is a documentation correction, not a design change — but it still gets a `DEVIATIONS.md` row because `CONTRACT.md` is Tier-F (Task 8).

**3. `main` has a live theme-resolver bug.** `frontend/src/lib/theme/resolver.ts` on `main` reads:

```ts
let globalTheme: DestinationTheme = "natural";

// Default to japan for testing as per J1 spec
globalTheme = "japan";

if (primaryCountryCode === "JP") {
  globalTheme = "japan";
}
```

The unconditional assignment overrides the fallback, so **every destination renders the Japan theme**. The branch fixes this. Task 1 lands it first because it is the highest-value, smallest, most independent piece.

**4. The branch's `natural.css` edits are WCAG contrast fixes**, not aesthetic churn — darkening `--th-text-muted`, `--th-accent-4`, and two shadow tokens. That is why `tests/contrast.test.ts` changes alongside them.

**5. Cherry-picking does not work.** Verified in a throwaway worktree: replaying all 13 commits onto `main` yields 4 clean and 9 conflicted, and several conflicts are *artifacts of earlier skips* (`0303485` conflicts on `results-view.tsx` only because `a53b414`, which creates that file, was skipped). Do not attempt `git cherry-pick`. Re-apply final file states.

**6. Import paths moved.** `main` relocated generated API output to `frontend/src/lib/api/generated/` (the I8A.2.1 isolation change) and exposes a hand-maintained facade at `frontend/src/lib/api/index.ts`. Branch files importing `@/lib/api/types.gen` **must be rewritten to `@/lib/api`**, which is `main`'s own convention. Affects exactly two files: `results-view.tsx` and `japan-visual-fixture.ts`.

---

## Scope

### In scope (this plan)

The additive philatelic layer: the theme-resolver fix, contrast tokens, the approved stamp asset and its typed accessor, the `DestinationStamp` component, the `results-view.tsx` component **as a new standalone component**, kitchen-sink surfaces, token-lint rules and the design-drift guardrail, the visual gate reference screenshots, and the documentation catch-up.

### Out of scope (deliberately deferred)

**Rewiring `frontend/src/app/plan/page.tsx` to use `results-view.tsx`.** On the branch, `plan/page.tsx` shrank 689 → 509 lines by extracting a 215-line `results-view.tsx`. On `main` it *grew* to 872 lines with the F5 editable-itinerary and F5.1 interaction-hardening work — drag-and-drop, `requestSeqRef` optimistic-concurrency locking, `AddItem`/`ReplaceItem` operations, per-section `SectionFreshness`. Those did not exist when the extraction was written. Redoing the extraction against them is a design task, not a merge resolution.

**Consequence you must accept:** after this plan, `results-view.tsx` exists and is used by `RegisterSpecimenView`, while `plan/page.tsx` keeps its own inline rendering. That is a known, temporary duplication. It is the explicit seam where the deferred work will pick up. **Do not "helpfully" wire `plan/page.tsx` to `results-view.tsx` as a drive-by.** That is the entire reason this plan is a split.

Write the follow-up plan only after this one lands and its gate passes.

---

## File Structure

Files this plan creates or modifies, grouped by the task that owns them.

| File | Task | Responsibility |
|---|---|---|
| `frontend/src/lib/theme/resolver.ts` | 1 | Deterministic, allowlisted country-code → theme resolution |
| `frontend/tests/theme-resolver.test.ts` | 1 | *(new)* Proves normalization + no city-name guessing |
| `frontend/src/themes/natural.css` | 2 | WCAG-compliant fallback theme tokens |
| `frontend/tests/contrast.test.ts` | 2 | *(modify, conflict surface)* Contrast regression |
| `frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp` | 3 | *(new)* The approved runtime stamp asset |
| `frontend/public/img/japan/philatelic/MANIFEST.md` | 3 | *(new)* Asset provenance/licence record |
| `frontend/src/lib/design/philatelic-assets.ts` | 3 | *(new)* Typed accessor for approved assets |
| `frontend/tests/philatelic-asset.test.ts` | 3 | *(new)* Proves only approved assets are referenced |
| `frontend/src/components/product/destination-stamp.tsx` | 4 | *(new)* The stamp component |
| `frontend/e2e/destination-stamp.spec.ts` | 4 | *(new)* Rendering + a11y |
| `frontend/src/components/product/results-view.tsx` | 5 | *(new)* Standalone typed results renderer |
| `frontend/src/mocks/japan-visual-fixture.ts` | 5 | *(new)* Typed visual fixture |
| `frontend/tests/japan-visual-fixture.test.ts` | 5 | *(new)* Fixture conforms to `FinalReport` |
| `frontend/src/app/kitchen-sink/views/*.tsx` (6 files) | 6 | Kitchen-sink surfaces |
| `frontend/src/app/kitchen-sink/page.tsx` | 6 | *(conflict surface)* View registration |
| `frontend/src/components/product/{Illustrations,booking-checklist,count-up}.tsx` | 6 | Token-discipline cleanups |
| `frontend/src/app/theme-proof/page.tsx` | 6 | Theme proof surface |
| `frontend/src/mocks/handlers.ts` | 6 | *(conflict surface)* MSW wiring |
| `frontend/src/mocks/fixtures.json` | 6 | *(conditional delete)* Orphaned only if the merged `ItineraryView` drops its import — see Step 6.4 |
| `frontend/scripts/token-lint.mjs` | 7 | Design-token lint rules |
| `frontend/tests/design-drift.test.ts` | 7 | *(new)* Guardrail against contract drift |
| `frontend/design/CONTRACT.md` | 8 | *(Tier-F)* Design contract doc catch-up |
| `DEVIATIONS.md` | 8 | Tier-F row |
| `frontend/design/refs/philatelic/**` | 9 | *(new)* Gate reference screenshots + candidates |
| `frontend/e2e/japan-*.spec.ts`, `figma-reconciliation.spec.ts`, `r0-initial-route-bundle.spec.ts` | 9 | *(new)* Visual + shell + bundle gates |
| `reports/frontend_japan_philatelic_landing.md` | 10 | Milestone report |
| `CLAUDE.md` / `AGENTS.md` | 10 | Checkpoint (must stay byte-identical) |

---

## Setup (do this once, before Task 1)

- [ ] **Step 0.1: Create an isolated worktree**

```bash
cd /Users/himanshu_jain/TripPlanner
git worktree add .worktrees/feat-japan-philatelic-landing -b feat/japan-philatelic-landing main
cd .worktrees/feat-japan-philatelic-landing
```

- [ ] **Step 0.2: Install frontend dependencies**

```bash
cd frontend && npm ci
```

- [ ] **Step 0.3: Capture a real baseline — do not trust any number in any document**

```bash
cd frontend
npx tsc --noEmit; echo "tsc exit: $?"
node scripts/token-lint.mjs; echo "token-lint exit: $?"
npx vitest run 2>&1 | tail -5
```

Record the actual output. Every later "did I break something?" comparison is against *this*, not against a figure quoted in a report.

- [ ] **Step 0.4: Confirm the source branch is reachable**

```bash
git rev-parse --verify codex/japan-philatelic-reconciliation
git log --oneline -1 codex/japan-philatelic-reconciliation
```

Expected: resolves to `75e4867 docs: record Japan philatelic frontend gate`. If it does not resolve, stop — the branch is the source of every file in this plan.

Throughout this plan, `$J` means `codex/japan-philatelic-reconciliation`. In zsh, **always brace it** — `git show "${J}":path` — because bare `$J:frontend/...` gets mangled by zsh modifier expansion.

---

### Task 1: Fix the theme resolver

`main` renders the Japan theme for every destination because of an unconditional assignment. This is the smallest, highest-value, fully independent piece — land it first.

**Files:**
- Modify: `frontend/src/lib/theme/resolver.ts`
- Test: `frontend/tests/theme-resolver.test.ts` (create)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `resolveTheme(primaryCountryCode: string | null): ThemeResolution` where `ThemeResolution = { globalTheme: DestinationTheme; primaryCountryCode: string | null; secondaryCountryCodes: string[] }` and `DestinationTheme` is the existing exported union in that file. Task 6's surfaces rely on `"natural"` being returned for non-`JP` input.

- [ ] **Step 1.1: Write the failing test**

Create `frontend/tests/theme-resolver.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { resolveTheme } from "../src/lib/theme/resolver";

describe("theme resolver", () => {
  it.each([
    { input: null, expectedTheme: "natural", expectedPrimary: null },
    { input: "JP", expectedTheme: "japan", expectedPrimary: "JP" },
    { input: "jp", expectedTheme: "japan", expectedPrimary: "JP" },
    { input: "US", expectedTheme: "natural", expectedPrimary: "US" },
    { input: "ZZ", expectedTheme: "natural", expectedPrimary: "ZZ" },
  ] as const)("resolves $input to $expectedTheme", ({ input, expectedTheme, expectedPrimary }) => {
    const resolved = resolveTheme(input);

    expect(resolved.globalTheme).toBe(expectedTheme);
    expect(resolved.primaryCountryCode).toBe(expectedPrimary);
    expect(resolved.secondaryCountryCodes).toEqual([]);
  });

  it("trims and normalizes explicit country codes without guessing from cities", () => {
    expect(resolveTheme(" jp ").globalTheme).toBe("japan");
    expect(resolveTheme("Tokyo").globalTheme).toBe("natural");
    expect(resolveTheme("").globalTheme).toBe("natural");
  });
});
```

- [ ] **Step 1.2: Run it and confirm it fails for the right reason**

```bash
cd frontend && npx vitest run tests/theme-resolver.test.ts
```

Expected: FAIL. Cases `US`, `ZZ`, `Tokyo`, `""`, and `null` all return `"japan"` instead of `"natural"`. If they pass, the bug is already fixed — stop and re-read `resolver.ts` before continuing.

- [ ] **Step 1.3: Replace the resolver body**

In `frontend/src/lib/theme/resolver.ts`, replace the body of `resolveTheme` with:

```ts
export function resolveTheme(primaryCountryCode: string | null): ThemeResolution {
  const normalizedPrimary = primaryCountryCode?.trim().toUpperCase() || null;
  // Japan is the only allowlisted destination pack. Unknown falls back to natural.
  const globalTheme: DestinationTheme = normalizedPrimary === "JP" ? "japan" : "natural";

  return {
    globalTheme,
    primaryCountryCode: normalizedPrimary,
    secondaryCountryCodes: [],
  };
}
```

Leave the `ThemeResolution` type and every import untouched.

- [ ] **Step 1.4: Run the test and confirm it passes**

```bash
cd frontend && npx vitest run tests/theme-resolver.test.ts
```

Expected: PASS, 6 cases.

- [ ] **Step 1.5: Confirm nothing else regressed**

```bash
cd frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -5
```

Any newly failing test is almost certainly a surface that silently depended on the theme always being `japan`. Do **not** re-break the resolver to make it pass — fix the surface, or note it for Task 6 if it is a kitchen-sink view this plan rewrites anyway.

- [ ] **Step 1.6: Commit**

```bash
git add frontend/src/lib/theme/resolver.ts frontend/tests/theme-resolver.test.ts
git commit -m "fix(frontend): resolve theme deterministically instead of forcing japan"
```

---

### Task 2: Land the WCAG contrast tokens

**Files:**
- Modify: `frontend/src/themes/natural.css`
- Modify: `frontend/tests/contrast.test.ts` *(conflict surface — merge by hand, do not overwrite)*

**Interfaces:**
- Consumes: Task 1's `"natural"` return, which is what makes this theme reachable at all.
- Produces: `--th-text-muted`, `--th-accent-4`, `--th-shadow-1`, `--th-shadow-2` at AA-compliant values. Tasks 6 and 9 render against these.

- [ ] **Step 2.1: Apply the four token changes**

In `frontend/src/themes/natural.css`, make exactly these substitutions:

```css
/* --th-text-muted: oklch(0.550 0.010 60.0);  ->  */
--th-text-muted: oklch(0.500 0.012 60.0);

/* --th-accent-4: oklch(0.600 0.020 60.0);  ->  */
--th-accent-4: oklch(0.500 0.020 60.0);

/* --th-shadow-1: 6px 6px 0 oklch(0.600 0.020 60.0);  ->  */
--th-shadow-1: 6px 6px 0 oklch(0.500 0.020 60.0);

/* --th-shadow-2: 8px 8px 0 oklch(0.600 0.020 60.0);  ->  */
--th-shadow-2: 8px 8px 0 oklch(0.500 0.020 60.0);
```

Change nothing else in the file. `--th-shadow-3` is already correct.

- [ ] **Step 2.2: Inspect both versions of the contrast test before touching it**

```bash
git diff main codex/japan-philatelic-reconciliation -- frontend/tests/contrast.test.ts
```

`main` added 12 lines here after the branch forked; the branch rewrote ~30. **Merge by hand.** Keep every assertion `main` added, and add the branch's assertions for the four tokens above. Overwriting with the branch's version silently deletes `main`'s newer coverage.

- [ ] **Step 2.3: Run the contrast gate**

```bash
cd frontend && npx vitest run tests/contrast.test.ts
```

Expected: PASS. If a ratio fails, the token value is wrong — fix the token, never loosen the threshold.

- [ ] **Step 2.4: Commit**

```bash
git add frontend/src/themes/natural.css frontend/tests/contrast.test.ts
git commit -m "fix(frontend): raise natural theme tokens to WCAG AA contrast"
```

---

### Task 3: Land the approved stamp asset and its typed accessor

**Files:**
- Create: `frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp`
- Create: `frontend/public/img/japan/philatelic/MANIFEST.md`
- Create: `frontend/src/lib/design/philatelic-assets.ts`
- Create: `frontend/tests/philatelic-asset.test.ts`

**Interfaces:**
- Consumes: nothing.
- Produces: `JAPAN_ATLAS_STAMP` (a `const satisfies ApprovedPhilatelicAsset`) and the `ApprovedPhilatelicAsset` type. Task 4's `DestinationStamp` imports `JAPAN_ATLAS_STAMP`.

- [ ] **Step 3.1: Extract the asset and manifest**

```bash
J=codex/japan-philatelic-reconciliation
mkdir -p frontend/public/img/japan/philatelic
git show "${J}":frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp > frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp
git show "${J}":frontend/public/img/japan/philatelic/MANIFEST.md > frontend/public/img/japan/philatelic/MANIFEST.md
```

- [ ] **Step 3.2: Verify the asset is intact, not a truncated text write**

```bash
file frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp
ls -l frontend/public/img/japan/philatelic/japan-atlas-stamp-01.webp
```

Expected: reported as a WebP image with a non-trivial byte size. If it reports as ASCII text, the redirect mangled it — re-extract with `git show ... > file` from a clean shell, and confirm before proceeding.

- [ ] **Step 3.3: Create the typed accessor**

Create `frontend/src/lib/design/philatelic-assets.ts`:

```ts
export type ApprovedPhilatelicAsset = {
  id: "japan-atlas-01";
  countryCode: "JP";
  src: string;
  width: number;
  height: number;
  alt: string;
};

export const JAPAN_ATLAS_STAMP = {
  id: "japan-atlas-01",
  countryCode: "JP",
  src: "/img/japan/philatelic/japan-atlas-stamp-01.webp",
  width: 520,
  height: 693,
  alt: "Fictional Atlas Japan travel stamp",
} as const satisfies ApprovedPhilatelicAsset;
```

- [ ] **Step 3.4: Land the asset guardrail test**

```bash
J=codex/japan-philatelic-reconciliation
git show "${J}":frontend/tests/philatelic-asset.test.ts > frontend/tests/philatelic-asset.test.ts
```

Read it before running it. It proves the referenced file exists on disk and that no unapproved philatelic asset is referenced from source.

- [ ] **Step 3.5: Run it**

```bash
cd frontend && npx vitest run tests/philatelic-asset.test.ts
```

Expected: PASS. A failure naming a missing file means Step 3.1 did not write where the test looks — fix the path, do not weaken the test.

- [ ] **Step 3.6: Commit**

```bash
git add frontend/public/img/japan/philatelic frontend/src/lib/design/philatelic-assets.ts frontend/tests/philatelic-asset.test.ts
git commit -m "feat(frontend): add approved Japan philatelic asset and typed accessor"
```

---

### Task 4: Land the DestinationStamp component

**Files:**
- Create: `frontend/src/components/product/destination-stamp.tsx`
- Create: `frontend/e2e/destination-stamp.spec.ts`

**Interfaces:**
- Consumes: `JAPAN_ATLAS_STAMP` from Task 3.
- Produces: `DestinationStamp` (named export). Task 5's `results-view.tsx` and Task 6's `ExploreView` / `theme-proof` import it.

- [ ] **Step 4.1: Extract the component**

```bash
J=codex/japan-philatelic-reconciliation
git show "${J}":frontend/src/components/product/destination-stamp.tsx > frontend/src/components/product/destination-stamp.tsx
```

- [ ] **Step 4.2: Read it and confirm its imports resolve on `main`**

```bash
head -12 frontend/src/components/product/destination-stamp.tsx
```

It should import only `JAPAN_ATLAS_STAMP` (Task 3) plus modules that exist on `main`. If it imports `@/lib/api/types.gen`, rewrite that to `@/lib/api` — see Context finding 6.

- [ ] **Step 4.3: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 4.4: Land the e2e spec**

```bash
J=codex/japan-philatelic-reconciliation
git show "${J}":frontend/e2e/destination-stamp.spec.ts > frontend/e2e/destination-stamp.spec.ts
```

- [ ] **Step 4.5: Run it**

```bash
cd frontend && npx playwright test destination-stamp.spec.ts --config=e2e/playwright.config.ts --reporter=list
```

Expected: PASS. If it fails because the stamp is not mounted on any route yet, that is legitimate — the surfaces that mount it land in Task 6. Note the failure, proceed, and re-run this spec at Step 6.6. Do not delete or skip the spec.

- [ ] **Step 4.6: Commit**

```bash
git add frontend/src/components/product/destination-stamp.tsx frontend/e2e/destination-stamp.spec.ts
git commit -m "feat(frontend): add typed DestinationStamp component"
```

---

### Task 5: Land results-view and the typed visual fixture — as standalone units

**Read the "Out of scope" section again before starting.** You are landing `results-view.tsx` as a **new, standalone component**. You are **not** wiring `plan/page.tsx` to it.

**Files:**
- Create: `frontend/src/components/product/results-view.tsx`
- Create: `frontend/src/mocks/japan-visual-fixture.ts`
- Create: `frontend/tests/japan-visual-fixture.test.ts`

**Interfaces:**
- Consumes: `DestinationStamp` from Task 4.
- Produces, with these **exact** names (verified against the branch — do not guess or rename):
  - `results-view.tsx`: `export function ResultsView({ report, onRetry, destinationArtifact }: ResultsViewProps)`
  - `japan-visual-fixture.ts`: `export type DestinationVisualFixture`, `export const japanVisualFixture: DestinationVisualFixture`, and `export function createJapanVisualReport(): FinalReport`

  Task 6's `DealsView`, `ItineraryView`, `ProofView`, and `RegisterSpecimenView` import these. Note the fixture module exposes **both** a static `japanVisualFixture` const and a `createJapanVisualReport()` factory — check which one each consumer actually imports rather than assuming.

- [ ] **Step 5.1: Extract all three files**

```bash
J=codex/japan-philatelic-reconciliation
git show "${J}":frontend/src/components/product/results-view.tsx > frontend/src/components/product/results-view.tsx
git show "${J}":frontend/src/mocks/japan-visual-fixture.ts > frontend/src/mocks/japan-visual-fixture.ts
git show "${J}":frontend/tests/japan-visual-fixture.test.ts > frontend/tests/japan-visual-fixture.test.ts
```

- [ ] **Step 5.2: Rewrite the two moved import paths**

`main` relocated generated API output. Both files import a path that no longer exists. In `frontend/src/components/product/results-view.tsx`, change line 4:

```ts
// from:
import type { FinalReport } from "@/lib/api/types.gen";
// to:
import type { FinalReport } from "@/lib/api";
```

In `frontend/src/mocks/japan-visual-fixture.ts`, change line 1:

```ts
// from:
import type { FinalReport, Provenance } from "@/lib/api/types.gen";
// to:
import type { FinalReport, Provenance } from "@/lib/api";
```

`@/lib/api` is `main`'s hand-maintained facade (`frontend/src/lib/api/index.ts`) and re-exports both `FinalReport` and `Provenance`. This is the convention every other file on `main` uses.

- [ ] **Step 5.3: Confirm no stale generated-path imports remain**

```bash
cd frontend && grep -rn "lib/api/types.gen" src/ tests/ e2e/ || echo "clean"
```

Expected: `clean`.

- [ ] **Step 5.4: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0. A `FinalReport` shape mismatch here means the backend contract moved since the branch forked — report it rather than casting or loosening the type.

- [ ] **Step 5.5: Run the fixture conformance test**

```bash
cd frontend && npx vitest run tests/japan-visual-fixture.test.ts
```

Expected: PASS.

- [ ] **Step 5.6: Confirm you did NOT touch the deferred file**

```bash
git status --short frontend/src/app/plan/page.tsx
```

Expected: **no output**. If `plan/page.tsx` shows as modified, revert it — that is the deferred work.

- [ ] **Step 5.7: Commit**

```bash
git add frontend/src/components/product/results-view.tsx frontend/src/mocks/japan-visual-fixture.ts frontend/tests/japan-visual-fixture.test.ts
git commit -m "feat(frontend): add standalone typed results view and Japan visual fixture"
```

---

### Task 6: Land the kitchen-sink and product surfaces

The largest task. Three of its files are on the conflict surface and need hand-merging rather than overwriting.

**Files:**
- Modify: `frontend/src/app/kitchen-sink/views/{DealsView,ExploreView,ProfileView,ProofView,RegisterSpecimenView,WalletView}.tsx`
- Modify: `frontend/src/app/kitchen-sink/page.tsx` *(conflict surface)*
- Modify: `frontend/src/app/kitchen-sink/views/ItineraryView.tsx` *(conflict surface)*
- Modify: `frontend/src/mocks/handlers.ts` *(conflict surface)*
- Modify: `frontend/src/app/theme-proof/page.tsx`
- Modify: `frontend/src/components/product/{Illustrations,booking-checklist,count-up}.tsx`
- Modify: `frontend/src/app/layout.tsx`

**Interfaces:**
- Consumes: `DestinationStamp` (Task 4), `ResultsView` + `japanVisualFixture` / `createJapanVisualReport()` (Task 5), `resolveTheme` (Task 1).
- Produces: rendered surfaces that Task 9's visual specs screenshot.

- [ ] **Step 6.1: Overwrite the eleven non-conflicting files**

These are files `main` has not touched since the fork, so the branch's final state applies directly:

```bash
J=codex/japan-philatelic-reconciliation
for f in \
  frontend/src/app/kitchen-sink/views/DealsView.tsx \
  frontend/src/app/kitchen-sink/views/ExploreView.tsx \
  frontend/src/app/kitchen-sink/views/ProfileView.tsx \
  frontend/src/app/kitchen-sink/views/ProofView.tsx \
  frontend/src/app/kitchen-sink/views/RegisterSpecimenView.tsx \
  frontend/src/app/kitchen-sink/views/WalletView.tsx \
  frontend/src/app/theme-proof/page.tsx \
  frontend/src/components/product/Illustrations.tsx \
  frontend/src/components/product/booking-checklist.tsx \
  frontend/src/components/product/count-up.tsx \
  frontend/src/app/layout.tsx ; do
  git show "${J}":"$f" > "$f"
done
```

- [ ] **Step 6.2: Verify `layout.tsx` did not regress the font setup**

```bash
grep -nE "Poiret|Schibsted|Roboto_Mono" frontend/src/app/layout.tsx
```

`main` already loads all three faces. The branch's version should too. If the branch's version drops one that `main` loads, keep `main`'s font wiring and take only the branch's structural changes.

- [ ] **Step 6.3: Hand-merge the three conflict-surface files**

For each, diff both versions first and keep both sides' intent:

```bash
git diff main codex/japan-philatelic-reconciliation -- frontend/src/app/kitchen-sink/page.tsx
git diff main codex/japan-philatelic-reconciliation -- frontend/src/app/kitchen-sink/views/ItineraryView.tsx
git diff main codex/japan-philatelic-reconciliation -- frontend/src/mocks/handlers.ts
```

`handlers.ts` is the one to be most careful with: `main` added ~287 lines of newer route handlers after the fork, and the branch adds only a small `japan-visual-fixture` wiring. **Keep all of `main`'s handlers** and add the branch's fixture wiring on top. Overwriting deletes live mock routes.

- [ ] **Step 6.4: Resolve the `fixtures.json` coupling**

The branch **deletes** `frontend/src/mocks/fixtures.json` (1669 bytes) because its rewritten `ItineraryView.tsx` switches to `japan-visual-fixture` instead. But `main`'s `ItineraryView.tsx:13` still has:

```ts
import fixtures from "@/mocks/fixtures.json";
```

So the deletion is coupled to how you merged `ItineraryView.tsx` in Step 6.3. Decide explicitly:

```bash
cd frontend && grep -rn "mocks/fixtures.json" src/ tests/ e2e/ || echo "no remaining importers"
```

- If that prints **`no remaining importers`** — your merged `ItineraryView` fully adopted the branch's `japan-visual-fixture` source. Delete the now-orphaned file:
  ```bash
  git rm frontend/src/mocks/fixtures.json
  ```
- If it prints **any importer** — keep `fixtures.json`. Do not delete a file something still imports just because the branch deleted it. Note the retention in Task 10's report as intentional.

Never delete it and "fix the import after." Run the grep, then act on what it actually says.

- [ ] **Step 6.5: Typecheck**

```bash
cd frontend && npx tsc --noEmit
```

Expected: exit 0.

- [ ] **Step 6.6: Run lint and the full unit suite**

```bash
cd frontend && npx eslint . && npx vitest run 2>&1 | tail -6
```

Expected: no lint errors; unit suite green.

- [ ] **Step 6.7: Re-run the stamp spec deferred from Task 4**

```bash
cd frontend && npx playwright test destination-stamp.spec.ts --config=e2e/playwright.config.ts --reporter=list
```

Expected: PASS now that the surfaces mounting `DestinationStamp` exist.

- [ ] **Step 6.8: Confirm the deferred file is still untouched**

```bash
git status --short frontend/src/app/plan/page.tsx
```

Expected: no output.

- [ ] **Step 6.9: Commit**

```bash
git add frontend/src/app frontend/src/components/product frontend/src/mocks/handlers.ts
git commit -m "feat(frontend): land Japan philatelic kitchen-sink and product surfaces"
```

---

### Task 7: Land the token-lint rules and the design-drift guardrail

**Files:**
- Modify: `frontend/scripts/token-lint.mjs`
- Create: `frontend/tests/design-drift.test.ts`

**Interfaces:**
- Consumes: the surfaces from Task 6 (they must already be token-clean for the stricter rules to pass).
- Produces: an enforcement gate. Nothing imports from this task.

- [ ] **Step 7.1: Extract both files**

```bash
J=codex/japan-philatelic-reconciliation
git show "${J}":frontend/scripts/token-lint.mjs > frontend/scripts/token-lint.mjs
git show "${J}":frontend/tests/design-drift.test.ts > frontend/tests/design-drift.test.ts
```

- [ ] **Step 7.2: Run token-lint**

```bash
cd frontend && node scripts/token-lint.mjs
```

Expected: 0 violations. Non-zero means a Task 6 surface still uses a raw literal or forbidden utility — **fix the surface, never relax a rule**. Rules are Tier-F design discipline.

- [ ] **Step 7.3: Run the drift guardrail**

```bash
cd frontend && npx vitest run tests/design-drift.test.ts
```

Expected: PASS.

- [ ] **Step 7.4: Commit**

```bash
git add frontend/scripts/token-lint.mjs frontend/tests/design-drift.test.ts
git commit -m "test(frontend): enforce design-token discipline and drift guardrail"
```

---

### Task 8: Documentation catch-up — CONTRACT.md and the Tier-F row

**Files:**
- Modify: `frontend/design/CONTRACT.md` *(Tier-F)*
- Modify: `DEVIATIONS.md`

- [ ] **Step 8.1: Replace the stale contract**

```bash
J=codex/japan-philatelic-reconciliation
git show "${J}":frontend/design/CONTRACT.md > frontend/design/CONTRACT.md
```

- [ ] **Step 8.2: Verify it now matches what the code actually does**

```bash
grep -niE "poiret|bodoni" frontend/design/CONTRACT.md frontend/src/app/layout.tsx
```

The contract should name **Poiret One** as the display face, matching `layout.tsx`. If `CONTRACT.md` still says Bodoni Moda, Step 8.1 did not take effect.

- [ ] **Step 8.3: Check for leftover Bodoni references in source**

```bash
cd frontend && grep -rln "Bodoni" src/ || echo "clean"
```

`main` still references Bodoni in `src/app/page.tsx` and `src/app/kitchen-sink/views/UiComponentsView.tsx`. If those references are dead (a class name no font maps to), remove them. If removing changes rendering, leave them and record it as open work in Task 10's report rather than guessing.

- [ ] **Step 8.4: Add the Tier-F DEVIATIONS row**

Append a new section at the end of `DEVIATIONS.md`, matching the existing table format exactly (`date, doc§, question, decision, rationale, affected_files`):

```markdown
## Japan Philatelic Landing — design contract catch-up

| date | doc§ | question | decision | rationale | affected_files |
|---|---|---|---|---|---|
| 2026-08-22 | 11 · Tier-F | `frontend/design/CONTRACT.md` on `main` still described the F1 system (Bodoni Moda display) while `main`'s own `layout.tsx` already loaded Poiret One and shipped `themes/japan.css` — the frozen contract and the running code disagreed about the display face. | Replaced `CONTRACT.md` with the Japan philatelic contract from `codex/japan-philatelic-reconciliation`, which documents the typography, theme scope, and surface rules `main` already implements. Recorded as Tier-F because `CONTRACT.md` freezes design tokens, even though this change makes the document describe reality rather than changing behavior. | A frozen contract that contradicts the shipped code provides no guarantee — it silently licenses either reading. Correcting the document is the conservative move; changing the code to match a stale document would have reverted an already-approved, already-shipped visual direction. | `frontend/design/CONTRACT.md` |
```

- [ ] **Step 8.5: Commit**

```bash
git add frontend/design/CONTRACT.md DEVIATIONS.md
git commit -m "docs(frontend): align design contract with shipped philatelic system"
```

---

### Task 9: Land the visual gate specs and reference screenshots

**Files:**
- Create: `frontend/design/refs/philatelic/**` (CANDIDATES.md, 2 candidate webp, gate/MANIFEST.md, 11 gate png)
- Create: `frontend/e2e/{japan-philatelic-visual,japan-shell,figma-reconciliation,r0-initial-route-bundle}.spec.ts`
- Modify: `frontend/e2e/{f1-5-landing,f3-no-orphan-numbers}.spec.ts`
- Modify: `frontend/e2e/f1-gate.spec.ts` *(conflict surface)*

- [ ] **Step 9.1: Extract the reference material**

```bash
J=codex/japan-philatelic-reconciliation
git checkout "${J}" -- frontend/design/refs/philatelic
```

- [ ] **Step 9.2: Extract the four new specs and two modified ones**

```bash
J=codex/japan-philatelic-reconciliation
for f in \
  frontend/e2e/japan-philatelic-visual.spec.ts \
  frontend/e2e/japan-shell.spec.ts \
  frontend/e2e/figma-reconciliation.spec.ts \
  frontend/e2e/r0-initial-route-bundle.spec.ts \
  frontend/e2e/f1-5-landing.spec.ts \
  frontend/e2e/f3-no-orphan-numbers.spec.ts ; do
  git show "${J}":"$f" > "$f"
done
```

- [ ] **Step 9.3: Hand-merge `f1-gate.spec.ts`**

```bash
git diff main codex/japan-philatelic-reconciliation -- frontend/e2e/f1-gate.spec.ts
```

`main` added 44 lines here after the fork; the branch rewrote ~109. Keep `main`'s newer assertions and add the branch's stamp/philatelic assertions. Do not overwrite.

- [ ] **Step 9.4: Run the visual and shell specs**

```bash
cd frontend && npx playwright test japan-philatelic-visual.spec.ts japan-shell.spec.ts figma-reconciliation.spec.ts --config=e2e/playwright.config.ts --reporter=list
```

Expected: PASS. Screenshot diffs against the landed references are the point of this task — a diff means a Task 6 surface does not match the approved composition. Fix the surface; do not re-baseline the reference screenshots to make a diff disappear.

- [ ] **Step 9.5: Run the bundle gate**

```bash
cd frontend && npx playwright test r0-initial-route-bundle.spec.ts --config=e2e/playwright.config.ts --reporter=list
```

Expected: PASS. This spec measures the *initial route* payload specifically — it replaced an older test that scanned every emitted chunk including deliberately lazy ones.

- [ ] **Step 9.6: Run the full F1 gate**

```bash
make gate-f1
```

Expected: `Gate F1: All checks passed.`

- [ ] **Step 9.7: Commit**

```bash
git add frontend/design/refs/philatelic frontend/e2e
git commit -m "test(frontend): land Japan philatelic visual, shell, and bundle gates"
```

---

### Task 10: Milestone report and checkpoint

**Files:**
- Create: `reports/frontend_japan_philatelic_landing.md`
- Modify: `CLAUDE.md` and `AGENTS.md` (must end byte-identical)

- [ ] **Step 10.1: Run the full frontend gate set from a clean tree**

```bash
git status --short   # must be empty
make gate-f1
cd frontend && npx vitest run 2>&1 | tail -6
```

Record the **actual** numbers. Do not write a number into the report that you have not just seen printed.

- [ ] **Step 10.2: Confirm this plan changed no backend behavior**

```bash
git diff --stat main..HEAD -- backend/ contract/
```

Expected: **empty**. If anything appears, it does not belong to this plan.

- [ ] **Step 10.3: Confirm the deferred work is genuinely still deferred**

```bash
git diff --stat main..HEAD -- frontend/src/app/plan/page.tsx
```

Expected: **empty**. This is the plan's defining boundary.

- [ ] **Step 10.4: Write the report**

Create `reports/frontend_japan_philatelic_landing.md` covering, with real evidence:
- what landed, task by task, with the commit hash for each
- the verified gate output from Step 10.1 (exact counts, no rounding, no figure copied from an older report)
- the theme-resolver bug this fixed, and that `main` previously rendered the Japan theme for every destination
- **explicitly**: that `plan/page.tsx` was not rewired, that `results-view.tsx` and `plan/page.tsx` currently duplicate rendering, and that closing that duplication is separate future work
- any leftover Bodoni references from Step 8.3 that were left in place, and why
- whether `frontend/src/mocks/fixtures.json` was deleted or retained at Step 6.4, and which grep result drove that

**Do not copy the branch's own report** (`reports/frontend_japan_philatelic_reconciliation.md`, which exists only on `codex/japan-philatelic-reconciliation`). It documents a tree that no longer exists, quotes gate results for that tree, and describes the `plan/page.tsx` refactor this plan deliberately does not land — importing it verbatim would assert things that are not true of `main`. Instead, **link to it as the historical record** of the original work and note that the plan-page portion of it remains unlanded.

Do **not** write "complete" anywhere until Step 10.1 has actually passed on a clean tree. This project has shipped that mistake twice — once on the Gondola milestone, once on CP1 task 8. Both were caught in review. Do not make it a third.

- [ ] **Step 10.5: Update the checkpoint in both files**

Add a bullet to the `## Current checkpoint` section of `CLAUDE.md`, then:

```bash
cp CLAUDE.md AGENTS.md
cmp CLAUDE.md AGENTS.md && echo IDENTICAL
```

They must be byte-identical — `AGENTS.md` is a copy of `CLAUDE.md`.

- [ ] **Step 10.6: Commit**

```bash
git add reports/frontend_japan_philatelic_landing.md CLAUDE.md AGENTS.md
git commit -m "docs: record Japan philatelic landing milestone"
```

- [ ] **Step 10.7: Request a whole-branch code review**

Use `superpowers:requesting-code-review` against the full `main..HEAD` diff before opening a PR. Two things to ask the reviewer to check specifically:
1. that no hand-merged file (`contrast.test.ts`, `handlers.ts`, `kitchen-sink/page.tsx`, `ItineraryView.tsx`, `f1-gate.spec.ts`) silently dropped assertions or handlers `main` added after the fork;
2. that the report's claims match the gate output rather than restating an older document.

---

## After this plan

The stranded branch `codex/japan-philatelic-reconciliation` can be deleted **only** once this branch has merged and a reviewer has confirmed nothing else on it is wanted. Until then it is the sole copy of the deferred `plan/page.tsx` refactor — treat it as reference material, not dead weight.

The follow-up plan — rewiring `plan/page.tsx` to `ResultsView` against `main`'s F5/F5.1 editable-itinerary logic — should be written fresh after this lands, against the then-current `plan/page.tsx`. Do not write it from the stranded branch's version, which predates drag-and-drop, `requestSeqRef` concurrency locking, and `SectionFreshness`.
