# Figma template reconciliation — fixing the PR #4 integration

**Date:** 2026-07-28
**Status:** PLANNED — not started. Frontend development is **paused**; this plan waits.
**Owner decision:** The Figma Make design is now the **visual template for the frontend**. Keep it. Do not revert it. Fix the integration around it.
**Blocking:** Nothing. This plan may be picked up at any time. Backend work (specs 17/18, Gates A1/A2) takes priority and is independent of it.

Read this whole file before touching the frontend. It is written to be self-sufficient
from a cold start — you should not need to re-read the F1–F4 handoff prompts, re-run the
design probes, or re-derive any visual direction.

---

## 1. What happened (cold-start context)

Figma Make produced a code bundle for a "Premium Travel Itinerary Planner". Unlike the
F1–F4 frontend built in-repo, it composes **actual product screens** — Explore, Deals,
Proof, Wallet, Profile, Itinerary — rather than a catalogue of tokens and primitives.
The human judged it materially better than the in-repo work and adopted it.

Someone then integrated it into `frontend/` on `feat/f1-frontend-foundation`, and that
was merged to `main` as PR #4 (`0a41492`). **The integration is broken.** The bundle
itself was internally consistent; the port broke it in two mechanical ways:

| | Figma bundle | After integration |
|---|---|---|
| Views live at | `src/app/views/` | `src/app/kitchen-sink/views/` (one level deeper) |
| `import '../../components/product/SharedUI'` | resolves correctly | resolves to `src/app/components/` — does not exist |
| `--color-lacquer` | defined, `src/styles/theme.css:28` | stylesheet never ported — every reference is dead |

Commit `627dfcb` ("fix CSS var resolution for lacquer") rewrote `bg-lacquer` →
`bg-[var(--color-lacquer)]`, i.e. it pointed harder at a variable that does not exist.
Treat that commit message as misleading, not as evidence the problem was solved.

### Measured state

| ref | `npx tsc --noEmit` | `node scripts/token-lint.mjs` |
|---|---|---|
| `7aa7ee9` (pre-merge) | 0 errors | 0 violations |
| `origin/main` (`0a41492`) | **44 errors** | **160 violations** |

Both gates went green → red in one merge. `git log 7aa7ee9..origin/main -- DEVIATIONS.md`
is empty: no `SCOPE+` entry was filed, as `AGENTS.md` requires.

### Where the artifacts live

- **Canonical template:** `design/Premium Travel Itinerary Planner/` — the untracked Figma
  Make bundle (Vite + React 18 + Tailwind v4 + Radix). **Currently untracked. See Task 0.**
- `design/Premium Travel Itinerary Planner.zip` — 700K redundant copy of the above.
- Integrated (broken) copy: `frontend/src/components/product/{SharedUI,ItineraryUI,Illustrations}.tsx`
  and `frontend/src/app/kitchen-sink/views/*.tsx` on `origin/main`.
- `docs/superpowers/specs/2026-07-28-plate-and-proof-design.md` — the earlier visual
  direction doc, still marked `PAUSED — not approved for implementation`. See Task 10.

---

## 2. What is and is not changing

**The palette is not changing.** This matters and is easy to get wrong. The Figma bundle's
`src/styles/theme.css` defines `--th-accent-4: oklch(0.536 0.135 30)` — byte-identical to
`frontend/src/themes/singapore.css:25`. The Figma design was built **on top of the approved
celadon/mangrove palette**, not as a replacement for it. Specs 10 §2 and 11 §1/§3 stand.

**What changes is composition.** The template contributes screen-level layout, density,
and the idea that product views beat swatch grids. Adopt that. Do not treat the bundle as
authority on tokens, typing, provenance, or money handling — the in-repo rules win there.

**Exactly one genuine conflict exists:** the accent-4 (lacquer) surface budget. See Task 9.

---

## 3. Ground rules for whoever executes this

- **Do not revert `0a41492`.** The design is the deliverable. Fix forward.
- **[STALE] Do not re-derive visual direction.** (Direction has been re-derived in `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md` — refer to that document instead).
- Behaviour changes and refactors are separate commits (`AGENTS.md`, Anti-drift).
- The five non-negotiables in `AGENTS.md` bind this work. Task 4 exists because of #1.
- Work on a branch off `main`: `feat/figma-template-reconciliation`.
- Tasks 1–3 are strictly ordered. Tasks 4–8 may be done in any order after 3. Task 9 is a
  human decision and blocks nothing. Task 10 is bookkeeping, do it last.

---

## 4. Tasks

### Task 0 — Preserve the template (do this first, even if nothing else is done)

The canonical design template currently exists only as an untracked local folder. A clean
checkout loses it. This is the highest-risk item in the plan and the cheapest to fix.

- Commit `design/Premium Travel Itinerary Planner/` (1.1 MB, source + 3 PNGs).
- Add `design/*.zip` to `.gitignore` — the 700K zip is redundant with the extracted folder.
- Its `ATTRIBUTIONS.md` declares shadcn/ui (MIT) and Unsplash photos. Verify no Unsplash
  binaries are actually bundled — `src/components/figma/ImageWithFallback.tsx` suggests
  images are fetched by URL, in which case only the MIT notice needs carrying. If binaries
  are present, do not commit them (same reasoning as the gitignored probe binaries).
- Add a short `design/README.md` stating that this folder is the frozen visual template,
  is not built or linted, and is not part of the `frontend/` build.

**Verify:** `git status --short` clean; `du -sh design/` ≈ 1.1M.

---

### Task 1 — Restore the build (import depth)

All six `frontend/src/app/kitchen-sink/views/*.tsx` import `../../components/product/…`.
From `src/app/kitchen-sink/views/`, `../../` is `src/app/`. Correct prefix is `../../../`.
10 × TS2307.

- Fix the relative depth in `DealsView`, `ExploreView`, `ItineraryView`, `ProfileView`,
  `ProofView`, `WalletView`.
- Prefer the `@/` alias (`@/components/product/SharedUI`) over relative paths — Task 5
  moves these files again, and the alias survives the move.

**Verify:** `cd frontend && npx tsc --noEmit` — TS2307 count drops to 0. Other errors remain
until Task 3; that is expected.

---

### Task 2 — Reconcile the lacquer token

`--color-lacquer` and `--lacquer` are defined nowhere under `frontend/src/`. The real token
is `--color-accent-4` (`themes/base.css`), fed by `--th-accent-4` (`themes/singapore.css`).

Three spellings are in use across the new files and all three are dead:
`var(--color-lacquer)` (24× `Illustrations.tsx`, 3× `ItineraryUI.tsx`), `var(--lacquer)`
(`ProofView`, `WalletView`), and bare `bg-lacquer` / `text-lacquer` (`SharedUI`, four views).

**Decision: rewrite the references to `accent-4`; do not port `theme.css`.** One name per
token. `base.css` already emits `bg-accent-4` / `text-accent-4` / `border-accent-4` /
`ring-accent-4` as real utilities under `@layer utilities`, so the rewrite targets existing
classes and needs no new CSS. Porting a second alias would give the codebase two names for
one colour, which is how this broke in the first place.

**Verify:** `grep -rn "lacquer" frontend/src/` returns only comments; rendered lacquer
elements are visibly `oklch(0.536 0.135 30)` and not transparent.

---

### Task 3 — De-duplicate the shadowed components

`SharedUI.tsx` and `ItineraryUI.tsx` re-implement eight components that already exist as
gated kebab-case files in `frontend/src/components/product/`, with incompatible props:

| Component | Existing (spec 14) | Figma version |
|---|---|---|
| `MoneyText` | `{minor, currency, emphasis?}` | `{amount, currency='USD'}` |
| `TrustChip` | `{variant, label}` | `{state, verifier}` |
| `ProvenanceBand` | `{sourceUrl, lastVerified, …}` | `{source, date, …}` |
| `LedgerRow` | `{label, value, dominant}` | `{card, value, cost, isChosen}` |
| `DecisionLedger` | `{items}` | `{rows}` |
| `RouteNode` | `{label, …}` | `{title, subtitle, icon}` |
| `WhyThis` | `{summary}` | `{title}` |
| `NotchLabel` | — | — |

- Delete the duplicated exports from `SharedUI.tsx` / `ItineraryUI.tsx`.
- Re-point the views at the existing kebab-case components, adapting call sites to the
  spec-14 prop names. The existing components are the contract; the views bend to them.
- **Keep** the genuinely new components — `FlightRouteCard`, `HighlightBox`, and everything
  in `Illustrations.tsx`. These are the template's actual contribution.
- Where a Figma version looks visually better than the existing one, port the *styling* into
  the existing kebab-case component. Do not fork the component to preserve the look.
- Replace `: any` props with real types. Spec 14: props are typed against generated API
  types, "never re-shaped ad-hoc types." Affected: `FlightRouteCard`, `ProvenanceBand`,
  `HighlightBox`, `DecisionLedger.rows`, `RouteNode.icon`.

**Verify:** `npx tsc --noEmit` → 0 errors. No duplicate export names across
`frontend/src/components/product/`.

---

### Task 4 — Restore the single money formatter (non-negotiable #1)

The Figma `MoneyText` takes `amount`, formats `en-US` / **USD** / `minimumFractionDigits: 0`.
The existing one takes `minor`, formats `en-IN` / INR / 2 fraction digits. The frozen
corridor is India → Singapore. `ANTI_GENERIC.md` calls this component "a safety gate, not a
convenience"; `AGENTS.md` non-negotiable #1 forbids a second formatter outright.

Task 3 deletes the duplicate. This task confirms the outcome explicitly because it is the
one finding that is a frozen-tier breach rather than a quality issue:

- Exactly one `MoneyText` exists repo-wide, taking `minor` (integer minor units).
- `minimumFractionDigits === maximumFractionDigits === 2`. The Figma version's `min: 0,
  max: 2` makes the rendered width of a money value depend on its magnitude, which breaks
  column alignment and determinism.
- No view computes money. Rendering `amount / 100` inside `MoneyText` is the *only*
  permitted division, and it stays there.

**Verify:** `grep -rn "MoneyText\|Intl.NumberFormat" frontend/src/` shows one definition and
no arithmetic at any call site.

---

### Task 5 — Separate the product views from the kitchen sink

PR #4 cut `frontend/src/app/kitchen-sink/page.tsx` from 459 → 75 lines, deleting the type
scale, palette, contrast pairs, surfaces, and every shadcn primitive demo. `e2e/f1-gate.spec.ts`
asserts against `/kitchen-sink` in 23 tests, so Gate F1 is currently unrunnable.

The two things serve different purposes and should not share a route:

- Restore the deleted kitchen-sink sections from `git show 7aa7ee9:frontend/src/app/kitchen-sink/page.tsx`.
- Move the six product views to their own route — suggest `/preview` or `/views`.
- Keep the tab shell the Figma bundle uses; it is a reasonable way to browse the six views.

**Verify:** `npm run test:e2e` — 23 F1 gate assertions pass. Both routes render.

---

### Task 6 — Motion correctness

- `SharedUI.tsx:57` renders `<motion.initial>`, which is not a Motion element — `WhyThis`'s
  expand animation is dead. Change to `<motion.div>`.
- Add `"use client"` to `SharedUI.tsx`, `ItineraryUI.tsx`, `Illustrations.tsx`. They use
  `useState` and `motion` and currently work only because `page.tsx` carries the directive.
- Spec 13 §5: every motion respects `prefers-reduced-motion` via the shared
  `useReducedMotionSafe` hook — "a Gate F3 test, not an aspiration." There are zero uses
  across the new files. `ProofView` runs an unconditional 3.2s draw-on sequence and
  `Illustrations.tsx` animates unguarded. Route all of it through the hook.

**Verify:** Gate F3 reduced-motion test passes; `WhyThis` visibly animates on expand.

---

### Task 7 — Token discipline (token-lint back to zero)

160 violations: 84 `no-vendor-utilities`, 64 `no-direct-var`, 12 `no-inline-svg`.

- ~90 uses of shadcn vendor utilities (`bg-card`, `text-muted-foreground`, `bg-secondary`,
  `text-accent-foreground`). `base.css` marks these "vendor compatibility (shadcn) — product
  code must never use these." Map each to its semantic token.
- `no-direct-var`: replace raw `var(--…)` in class strings with the semantic utility.
- `no-inline-svg`: the 12 hits are in `Illustrations.tsx`. Read the rule before acting — if
  it exists to stop ad-hoc icons rather than deliberate illustration, the right outcome may
  be a scoped `token-lint-disable` with a written justification, as `trust-chip.tsx` already
  does. Do not silence it without one.

**Verify:** `cd frontend && node scripts/token-lint.mjs` → 0 violations.

---

### Task 8 — Fixture data

The views hardcode fabricated literals that contradict the frozen corridor and the wallet
model: ANA First JFK→HND, Aman Tokyo, Virgin Atlantic, `$22,400`, `20.3¢/pt`, `184,200 pts`,
`Confidence: 100%`. `frontend/tests/contract.test.ts`'s `no-orphan-numbers` block exists to
prevent exactly this.

- Move all fixture data into JSON under the existing MSW fixture layer (`src/mocks/`).
- Re-key it to the India → Singapore corridor.
- `Confidence: 100%` must go. Provenance confidence is a backend-computed field
  (non-negotiable #3) and 100% is not a value the kernel emits.

**Verify:** `npm run test` — `no-orphan-numbers` passes.

---

### Task 9 — HUMAN DECISION: the accent-4 surface budget

`frontend/design/CONTRACT.md` §3 and spec 10 §2 cap accent-4 (lacquer) at **<2% of any
screen's surface, never a section fill.** The Figma template blows past this: `NotchLabel`,
`TrustChip.warning`, `HighlightBox` default, `RouteNode.warning`, `LedgerRow.notch` and every
monument in `Illustrations.tsx` are lacquer.

This is a real design decision, not a lint fix, and it is the only genuine conflict between
the adopted template and the frozen design system. Two options:

1. **Hold the budget** — recolour most lacquer usages to primary/accent-3, keep lacquer for
   `NotchLabel` and warning states only. Preserves the frozen contract; the template will
   look flatter than the Figma render.
2. **Raise the budget** — amend CONTRACT.md §3 and spec 10 §2 to a higher cap. Requires a
   Tier-F `DEVIATIONS.md` entry, because the constraint is frozen.

Do not choose this unilaterally. Ship Tasks 1–8 with lacquer left as-is and flag it.

**[CLOSED]** Resolved by `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md`: budget holds. Lacquer is mandatory on `verify_required` and optional nowhere.

---

### Task 10 — Documentation and bookkeeping

- **`DEVIATIONS.md`:** file the missing `SCOPE+` entry for PR #4. It introduced
  `Illustrations.tsx`, `HighlightBox`, `FlightRouteCard` and six app surfaces, none in any
  spec inventory, with no entry. Record it retroactively with today's date and a note that
  the human approved the direction after the fact.
- **`docs/superpowers/specs/2026-07-28-plate-and-proof-design.md`:** currently
  `PAUSED — not approved for implementation`. Update the status: the composition direction is
  **superseded by the Figma template**; the palette and typography decisions in it still
  stand and were confirmed independently by the Figma bundle (identical `--th-accent-4`).
- **`AGENTS.md` / `CLAUDE.md` checkpoint:** replace "F1 is the immediate implementation
  milestone" with the current truth — frontend is paused, the Figma bundle in `design/` is
  the visual template, this plan is the resume point. Keep both files identical.
- **`reports/`:** on completion, write `reports/frontend_figma_reconciliation.md` recording
  the before/after gate numbers.

---

## 5. Definition of done

| Check | Command | Target |
|---|---|---|
| Typecheck | `cd frontend && npx tsc --noEmit` | 0 errors |
| Token lint | `cd frontend && node scripts/token-lint.mjs` | 0 violations |
| Unit tests | `cd frontend && npm run test` | pass, incl. `no-orphan-numbers` |
| E2E / Gate F1 | `cd frontend && npm run test:e2e` | 23 assertions pass |
| Backend regression | `cd backend && pytest` | ≥ 100 passing (unchanged floor) |
| Money formatters | `grep -rn "Intl.NumberFormat" frontend/src/` | exactly 1 |
| Template preserved | `git status --short` | `design/` tracked, tree clean |

The milestone is not done because the screens render. It is done when the table above is
green **and** the six product views still look like the Figma render.

---

## 6. Open state at time of writing

`origin/main` is red (44 TS errors). Local `main` is at `7aa7ee9` and green. The human chose
to pause frontend work with the branch in this state rather than revert.

**If main must be green during the pause** (e.g. CI runs on it, or another agent branches
off it), the cheapest correct move is Task 1 alone — six import paths, restores the build
without touching design. Tasks 2–10 can then wait indefinitely.

---

## 7. Why this happened — carry this forward

The in-repo F1–F4 frontend passed every gate it defined: token-lint zero, 23 e2e assertions,
contrast pairs computed, nested theme proof green. It was also a swatch catalogue that never
showed anyone what the product looked like. The Figma bundle failed most of those gates and
was still the better deliverable.

The gates measured conformance and were silent on composition. When frontend work resumes,
Gate F-next needs a check the current set does not have: **a screenshot of a real product
screen with real fixture data, reviewed by a human, before the milestone counts as passed.**
Token discipline is necessary and not sufficient — the discipline is what makes the design
survivable, but it never produced one.
