# TripPlanner F1 — continuation prompt for opencode

Copy everything below this line into opencode as your instruction. It is written to
be self-sufficient for a model with no memory of prior sessions, and more explicit
than usual because it targets a weaker model than the one that did Phase 0.

---

## 0. What you are picking up

You are continuing the TripPlanner frontend build. **Phase 0 (design freeze) is
already complete and is FROZEN — do not redo it, do not re-open it, do not
"improve" it.** You are starting at **Phase 1** of a 6-phase plan. Read this whole
prompt before writing any code or running any command.

## 1. Mandatory read order — do this first, in this exact order

1. `AGENTS.md` (repo root) — project rules, decision-authority tiers, non-negotiables.
   This overrides your default instincts. Read it fully.
2. `DEVIATIONS.md` (repo root) — every judgment call already made on this project,
   including six new rows added in the Phase 0 session (two Tier-F: the font/palette
   revision, and a Tailwind v4 `@theme` vs `@theme inline` spec-bug fix). Do not
   re-decide anything already logged here.
3. `frontend/F1_IMPLEMENTATION_PLAN.md` — the approved plan. Its "Decisions already
   made" table and Phase 0 are done; you execute **Phase 1 through Phase 6** exactly
   as written there. This prompt adds skill/tool mapping and checkpoints around that
   plan — it does not replace it. When this prompt and the plan disagree on a
   mechanical detail, the plan wins; when they disagree on process/skill usage, this
   prompt wins (it's more current).
4. `frontend/design/CONTRACT.md` — the FROZEN design contract: exact fonts, exact
   OKLCH token values for every `--th-*`/`--color-*` slot, exact type scale with
   which heading level is allowed to use which font, exact motion tokens and
   reduced-motion substitutions. **This is your source of truth for every visual
   value you write. Never invent a color, size, timing, or font choice that isn't in
   this file.** If you think a value in it is wrong, say so in your final report —
   do not silently change it.
5. `docs/specs/06_implementation_protocol.md` — decision tiers (Tier F/C/V), the
   ambiguity protocol, and the self-review gates. Read this fully. It tells you
   exactly what to do when something is unclear: make the conservative choice that
   changes no Tier-F behavior, log it to `DEVIATIONS.md` in the same 6-column format
   as existing rows, and keep going. **Do not stop and ask a human** unless it's one
   of the six items in its §7 (paid services, legal wording, replacing placeholder
   data, publishing, going commercial, or a confirmed Tier-F spec bug you've already
   audited). Everything else: decide, log, proceed.
6. `docs/specs/10_frontend_build_plan.md` — stack (Tier F, frozen), tooling/MCP
   workflow, repo layout, milestone gates. §3's MCP tool order is mandatory: check
   an official registry (shadcn MCP) before hand-writing any component.
7. `docs/specs/11_design_system_and_theming.md` — token architecture. §1's
   `@theme` vs `@theme inline` warning is not theoretical — it was a real spec bug
   caught and fixed this session (see `DEVIATIONS.md`). Read it before touching
   `base.css`.
8. `frontend/FRONTEND_HANDOVER.md` — background context only, useful for the "why"
   behind product/research decisions (§6 travel-product research synthesis, §7
   component research). Where it conflicts with the plan or `CONTRACT.md` (it still
   says "Fraunces + Instrument Sans" and the sorbet palette in places, and lists
   `--color-savings-highlight` where the frozen name is `--color-savings`), the plan
   and `CONTRACT.md` win — this document predates the design freeze.

## 2. Ground rules that override your instincts

- **Money/points/rewards math is never computed by you or by frontend code, ever.**
  Every number you render comes from a backend response or an MSW fixture already
  computed. If a number isn't in the data, don't derive it — flag it as missing.
- **Design decisions in `CONTRACT.md` and `DEVIATIONS.md` are frozen.** Do not
  re-pick a font, re-tune a color, add a new accent, or change a motion timing. The
  system that produced them (multiple rounds of user review + rendered comparisons)
  already happened; redoing it wastes the user's remaining budget on this feature
  and risks silently diverging from what they approved.
- **No `localStorage`/`sessionStorage` anywhere. No secrets committed. No dark mode.**
- Lacquer red (`--color-accent-4`, hue 30) is capped at **under 2% of any screen's
  surface** — accent rules, the wordmark slash, route-node markers, the
  "Recommended" notch label only. Never a section fill, never a large text run.
  Check yourself against this before committing any screen that uses it.
- Every registry component (shadcn, Magic UI, Aceternity — anything pulled via MCP)
  is reviewed **line by line**, including comments, before commit, and rewired to
  semantic tokens (`bg-primary`, `text-text-muted`, etc.) in the same commit. Never
  leave a hardcoded palette from a registry component in the codebase.
- **Git actions that push, merge, or open PRs need the human present and confirming**
  — this is assumed to be an interactive session with the user at the keyboard, not
  an autonomous run. Prepare commits/PRs, then explicitly wait for their go-ahead
  before merging or force-pushing anything.
- After **every** phase below, run its stated verification before moving to the
  next phase. If a check fails, fix it — do not proceed with a known-red check, and
  do not claim a phase is done in your final report if its check didn't pass.
  **Gates are ground truth, not your own summary of what you did.** If `make
  gate-f1` or any sub-check fails, trust the failure over your own assessment that
  "it looks right."

## 3. Skill and MCP usage — explicit map, so you never guess

If a skill name below isn't found under that exact name in your skill list, search
your available skills for the closest match by description before skipping the step
— do not silently skip a skill just because the exact name differs.

| When | Skill(s) to invoke | Why |
|---|---|---|
| Before Phase 1, verifying Next.js 16 / Tailwind v4 / shadcn CLI current syntax | Context7 MCP (or your docs-lookup MCP) | These libraries moved recently; don't trust training-data memory of their APIs — verify against current docs before scaffolding. |
| Phase 2, structuring the token architecture and its accessibility implications | `ecc:design-system`, `ecc:frontend-a11y` | Token architecture and a11y are intertwined (contrast pairs, focus rings) — these skills carry the structural discipline for both. |
| Phase 2, any Tailwind v4 `@theme`/`@theme inline` question you're unsure about | Context7 MCP | Verify against current Tailwind v4 docs, not memory — this is the exact class of bug that was already caught once this session. |
| Phase 3–4, building primitives and product wrapper components | `emil-design-eng`, `apple-design`, `ecc:make-interfaces-feel-better`, `ecc:react-patterns` | Emil Kowalski's component-polish philosophy and Apple's interaction/materials discipline (press feedback, translucency, spatial consistency) apply to every primitive you compose, even though the typography/palette decisions those skills would normally drive are already frozen in `CONTRACT.md`. |
| Phase 4, building `RouteSpine`'s SVG line-drawing and any staged/stagger entrance | `ecc:motion-foundations`, `ecc:motion-advanced` | `motion-advanced` specifically covers SVG path-drawing (`stroke-dashoffset`) technique; `motion-foundations` covers spring/token structure. Use the exact motion table in `CONTRACT.md` §6 for the actual timing/easing values — these skills are for *how* to implement them correctly in Motion for React, not for choosing new values. |
| Phase 4, acquiring any shadcn/Magic UI/Aceternity component | shadcn MCP (`get_add_command_for_items`, `list_items_in_registries`) | Never hand-write a component that exists in a configured registry; never invent registry component props from memory — always query the MCP. |
| After every client/server-boundary change or animation-mount change (Phase 3 onward) | Next.js DevTools MCP (`get_errors`) | Hydration mismatches are this stack's most likely failure mode. Query this after every such change — don't wait until something visibly breaks. |
| Whenever you hit a bug you don't immediately understand (any phase) | `superpowers:systematic-debugging` (or `ecc:react-build` for a build-specific failure) | Don't guess-and-check fixes. Follow a systematic diagnosis before changing code. |
| End of each phase, before moving to the next | `ecc:react-review` (and `ecc:typescript-reviewer`/`ecc:react-testing`-class review for `.ts`/`.tsx` you just wrote) | Self-review pass on what you just wrote. Fix any high-severity finding before proceeding — don't accumulate review debt across phases. |
| Phase 5, building the kitchen sink | No new skill — execute directly against `CONTRACT.md` and the plan's Phase 5 checklist. Re-read `frontend/design/refs/palette/celadon-mangrove-forward.html` and its screenshots as your visual reference for "does this look like the approved direction." | |
| Phase 6, motion audit as gate evidence | `improve-animations` (read-only — it produces an audit, it does not implement) | Run this before declaring the gate passed; attach its findings to your final report even if you don't act on all of them. |
| Phase 6, verification discipline | `ecc:e2e-testing`, `ecc:verification-loop`, `ecc:delivery-gate`, `superpowers:verification-before-completion` | The last one especially: do not report Phase 6/F1 complete without having actually run every command in §7 below and observed it pass, not assumed it would. |
| Throughout, tracking your own progress across 6 phases + sub-checklists | Your task/todo tracking tool, if you have one (mirrors how the Phase 0 session tracked its 6 sub-steps) | A weaker model benefits more from externalized state than from holding a 6-phase plan in working memory. |

MCP tool order, restated from spec 10 §3 because it matters more with a weaker
model: **frontend-design guidance (if you have that skill) → shadcn MCP for
components → Figma MCP only if a source frame exists (none does yet) → Playwright
MCP for visual/interaction verification → Next.js DevTools MCP after
client/server-boundary changes → Chrome DevTools MCP (F4 only, not needed this
milestone) → Context7 for current library APIs.**

## 4. Phase-by-phase execution

Each phase below names its section in `frontend/F1_IMPLEMENTATION_PLAN.md` — go
read that section's full detail (exact commands, exact file trees, exact CSS
snippets) before starting; this prompt gives you the checkpoints and skill usage
around it, not a duplicate of its content.

### Phase 1 — Git hygiene and scaffold (plan §"Phase 1")

1. Commit the `DEVIATIONS.md`/spec/CLAUDE.md/AGENTS.md changes from Phase 0 if not
   already committed. Open a PR for `feat/m3-evals-provenance` → `main`.
2. **Stop and wait for the human to confirm the PR is merged to `main`** before
   proceeding — do not merge it yourself, do not branch off an unmerged base.
3. Once confirmed merged: `git pull` on `main`, branch `feat/f1-frontend-foundation`.
   Preserve `docs/research/17_orchestration_substrate_adk.md` (unrelated user work
   — do not delete or move it).
4. Scaffold per the plan's exact `create-next-app` → sibling-dir → `rsync` sequence
   (it exists because `create-next-app` refuses non-empty directories and
   `FRONTEND_HANDOVER.md` isn't on its allowlist — don't improvise a different
   scaffolding approach).
5. Create the full repo layout from spec 10 §4. `tsconfig.json`: add
   `noUncheckedIndexedAccess` and `noImplicitOverride`. **Do not** enable
   `exactOptionalPropertyTypes` — it breaks generated shadcn components.
6. Verify Next.js 16 / Tailwind v4 / shadcn CLI current flags via Context7 before
   running scaffolding commands, not from memory.

**Checkpoint before Phase 2:** `frontend/` has a working Next.js app, `npm run dev`
starts without error, the full directory layout from spec 10 §4 exists (empty dirs
like `lib/api/`/`mocks/` are fine — they stay empty until F2).

### Phase 2 — Token architecture (plan §"Phase 2") — **HIGHEST RISK PHASE**

The plan itself flags this as the highest-risk phase, and it's the phase most
likely to produce a subtle, silently-wrong result from a weaker model. Take it
slower than the others.

1. `shadcn init` **first**, with the exact flags in the plan (`--base radix`,
   `--css-variables`, baseColor `neutral`). Commit its output as-generated before
   writing any tokens over it — do not guess shadcn v4's variable surface from
   memory or from older shadcn knowledge.
2. Register Magic UI and Aceternity registry namespaces in `components.json`.
   Install **zero** components from them at this phase — they're not needed until
   F3/F4.
3. Write `frontend/src/themes/base.css` with the two-block structure the plan gives
   verbatim (plain `@theme` for static primitives with no `var()` refs; `@theme
   inline` for the destination-variable bridge and the vendor-compatibility alias
   block). Copy the exact `--th-*` OKLCH values from `CONTRACT.md` §3 into
   `singapore.css` — do not re-derive or re-round them.
4. Before moving on, **explicitly re-read the "law" stated in the plan's Phase 2
   section and in `CONTRACT.md` §3**: destination-dependent values live either
   inside `.theme-<dest>` as `--th-*` or inside `@theme inline`; product code
   consumes only Tailwind utilities, never `var(--color-*)`/`var(--th-*)` directly.
5. Watch for the two landmines the plan names explicitly: `--radius-s` shadows
   Tailwind's `rounded-s*` logical utility (don't use `rounded-s*`/`rounded-e*`
   anywhere in product code), and there is no `--duration-*` namespace in Tailwind
   v4 (add the explicit `@utility dur-fast|dur-base|dur-slow` blocks the plan
   specifies; don't write bare `duration-180` classes expecting them to resolve).

**Checkpoint before Phase 3 — do not skip this even though it's early:** write and
run `frontend/e2e/f1-theme-scope.spec.ts` (the nested-theme proof test from plan
Phase 5, pulled forward as a Phase 2 gate) *now*, not deferred to Phase 5. It should
assert that a `.bg-primary` element inside a `.theme-proof` div with overridden
`--th-*` values computes a different color than one outside it. If this fails, you
have the `@theme` vs `@theme inline` bug — stop, re-read `DEVIATIONS.md`'s Tier-F
spec-bug row, and fix the bridge before writing a single component. This single
check is what separates "looks right in the browser" from "actually correct" for
this phase — the bug it catches produces a fully normal-looking screen with zero
console errors right up until a second theme pack is added.

### Phase 3 — Fonts and assets (plan §"Phase 3")

1. Bodoni Moda via `next/font/google`, using the variable `opsz 6..96` axis
   correctly (per `CONTRACT.md` §1: `font-optical-sizing: auto`, no manual axis
   wiring needed) — display contexts only (hero/h1/h2), per `CONTRACT.md` §2's
   allowed-contexts table. Schibsted Grotesk and Roboto Mono likewise via
   `next/font/google`.
2. `next/font` writes CSS variables onto `<html>` — `--font-display` etc. must live
   in the `@theme inline` block from Phase 2, not a plain `@theme` block (same
   underlying bug class as Phase 2's landmine).
3. Self-host destination images under `public/img/singapore/` with a `MANIFEST.md`
   (source URL, platform, license, crop intent) — Pexels/Pixabay preferred, never
   the Unsplash API, no recognizable faces, no brand logos. Lucide icons only.

**Checkpoint:** a page rendering all three fonts shows Bodoni Moda only on
hero/h1/h2-styled elements and Schibsted Grotesk everywhere else, confirmed by
visual check, not just by reading your own code.

### Phase 4 — Primitives and product wrappers (plan §"Phase 4")

1. `shadcn add` exactly the component list in the plan (button, card, input, label,
   textarea, select, badge, separator, accordion, dialog, sheet, tabs, tooltip,
   skeleton, alert, progress) — nothing speculative. Use the shadcn MCP to validate
   names; never hand-write or guess a registry component's props.
2. Build the product wrappers in `components/product/` — `RouteSpine`/`RouteNode`,
   `DecisionLedger`/`LedgerRow`, `MoneyText`, `ProvenanceBand`, `TrustChip`,
   `WhyThis`, `NotchLabel`. Each needs a contract doc in
   `frontend/design/contracts/<Component>.md` per the plan's format (purpose,
   variants, anatomy, states, keyboard behavior, mobile behavior, token usage,
   forbidden styling, one approved screenshot).
3. Motion: build `lib/motion/` with shared variants/easings and a single
   `useReducedMotionSafe` hook. Implement the exact effects from `CONTRACT.md` §6's
   table (stagger entrance, line drawing, accordion, hover, press) with their exact
   duration/easing tokens — do not invent new timings.
4. Query Next.js DevTools MCP's `get_errors` after building each component that
   touches a client/server boundary or mounts an animation.

**Checkpoint:** every product component renders a sensible empty/loading/error
variant (spec 14 requirement, carried into the plan). No component in
`components/ui/` has been structurally edited — everything is composition over the
Phase 2 alias block.

### Phase 5 — Kitchen sink (plan §"Phase 5")

Build the `/kitchen-sink` route per the plan's checklist. It must read as
product-flavored evidence of the system, not a generic component-library demo wall
— compare against `frontend/design/refs/palette/celadon-mangrove-forward-*.png` and
the brainstorm references in `frontend/design/refs/brainstorm/` for what "on brand"
looks like. If you already built the `.theme-proof` nested-theme section in Phase 2
as a checkpoint, fold it into this route rather than duplicating it.

### Phase 6 — Gate F1 (plan §"Phase 6")

Build every artifact the plan specifies: `frontend/scripts/token-lint.mjs`,
`frontend/tests/contrast.test.ts` + `scripts/parse-theme.ts`, the Playwright suite
(390/768/1440 + reduced-motion project, against a **production build**, never
`next dev`), the root `Makefile`'s `gate-f1` target, `frontend/design/ANTI_GENERIC.md`.

Run `improve-animations` now for a read-only motion audit and attach its findings
to your final report, even for issues you decide not to fix.

## 5. Verification — run every one of these before claiming F1 is done

1. `make gate-f1` — all green: typecheck, token-lint, contrast matrix, production
   build, Playwright screenshots + axe + console + reduced-motion.
2. `frontend/e2e/f1-theme-scope.spec.ts` passes (you should have already gotten
   this green back in Phase 2 — re-run it here as final confirmation nothing
   regressed).
3. `make fe-token-lint` green **after** the full 16-component shadcn add, with
   **zero edits** to `components/ui/` — this proves the vendor alias block works.
4. `make fe-contrast` was green **before** any component existed (Phase 2
   checkpoint) — confirm it's still green now.
5. Manually compare the three committed viewport screenshots against spec 11's
   checklist and `frontend/design/ANTI_GENERIC.md`.
6. Full backend regression still green: `make gate-m1 gate-m1b gate-m2 gate-m3`
   (this work must not touch backend Tier-F behavior or golden numbers — if any of
   these fail, you touched something you shouldn't have).

## 6. Dependency budget — hard boundary

**Allowed at F1:** `next`, `react`, `react-dom`, `motion`; whatever shadcn
auto-installs (`lucide-react`, `clsx`, `tailwind-merge`,
`class-variance-authority`, Radix packages, `tw-animate-css`); dev-only:
`typescript`, `tailwindcss`, `@tailwindcss/postcss`, `postcss`, `eslint`,
`@playwright/test`, `@axe-core/playwright`, `vitest` (node environment only — no
jsdom, no testing-library), `culori` + `@types/culori`.

**Installing any of these at F1 is a gate failure — do not add them even if a
component you like depends on one:** `@tanstack/react-query`, `@hey-api/openapi-ts`,
`zod`, `msw` (these are F2's job), `gsap`, `lenis`, `maplibre-gl`,
`canvas-confetti` (F3/F4), `storybook`, `next-themes`, `three`, `framer-motion`,
`tailwindcss-animate`. If a Magic UI or Aceternity component you're tempted to add
drags in one of these, either find a lighter equivalent or leave it for F3/F4 — do
not pull it into F1 to make the kitchen sink look more impressive.

## 7. Explicitly out of scope — do not do these even if it seems helpful

No backend Tier-F behavior or golden-number changes of any kind. No
`contract/openapi.json` generation, API client, Zod schemas, MSW, or the intake
wizard (that's F2). No results page, map, GSAP, or Lenis (F3). No performance
optimization pass (F4). No provider gateway, adapters, crawling, or any
travel-provider MCP (that's G1+, and explicitly not authorized without a human
decision). No dark mode. No `localStorage`/`sessionStorage`.

The backend's `POST /plan` is synchronous with a `{raw_request: str}` body, while
spec 12 describes an async job+poll API with a wizard-shaped request. This is a
**known, already-logged gap** — it is F2's first task, not yours. Do not attempt to
reconcile it during F1.

## 8. Final report format

When you believe F1 is complete, write `reports/frontend_F1.md` mirroring the
structure of `reports/milestone_3.md` (Date/Branch/Scope preamble → Result → Gate
F1 with literal commands and pass counts → verification output → implemented files
→ boundary checks → Deviations → Next milestone). Include `npm ls --prod
--depth=0` output as evidence no unapproved dependency snuck in. List every
`DEVIATIONS.md` row you added during this work. Explicitly state whether every
item in §5 above passed — don't summarize "F1 is done," show the command output
that proves it.
