# TripPlanner Frontend — Design Freeze + F1 Foundation

## Context

The backend is done through M3. `frontend/` contains exactly one file: `FRONTEND_HANDOVER.md`. No `package.json`, no Next.js project, no tokens, no components.

The handover records a completed design brainstorm that ended in a blocked state: the user approved an **Atlas Editorial × Peranakan Modernist** hybrid direction (limestone canvas, mangrove green, hairline rules, zero radius, route-line wayfinding) and approved **Schibsted Grotesk** for UI — but specs 10 and 11 still freeze the *rejected* Fraunces + Instrument Sans and the *rejected* Singapore sorbet palette. Implementing F1 against contradictory authoritative specs is how a codebase and its docs permanently diverge.

So this work has two halves: **freeze the design and fix the docs (Phase 0)**, then **build the foundation (Phases 1–6)**. The output is not just a rendering page — it is a design contract rigid enough that cheaper models can implement F2–F4 without making taste decisions, with the rules enforced by scripts rather than prose.

Decisions confirmed with the user this session: brand name is **TripPlanner**; display font resolved by license-check-then-rendered-comparison; **M3 merges to main before any frontend branch**; full contract layer with automated enforcement; palette shifts to celadon/mangrove-forward with lacquer capped as a rare accent; spec 11 §1's token bridge is a confirmed bug and gets fixed.

**Provenance:** written 2026-07-26 in a planning session that read `FRONTEND_HANDOVER.md`, specs 06/10/11/12/13/14/15, `DEVIATIONS.md`, and the `.superpowers/` brainstorm artifacts. This file *is* that plan, saved into the repo. It is untracked until someone runs `git add frontend/F1_IMPLEMENTATION_PLAN.md`.

**Emil Kowalski's skills are installed** (globally, via `npx skills@latest add emilkowalski/skills` — that repo has no `.claude-plugin/marketplace.json`, so it is *not* a Claude Code plugin marketplace and `/plugin marketplace add` does not work on it). Verified available: `apple-design`, `emil-design-eng`, `animation-vocabulary`, `find-animation-opportunities`, `improve-animations`. Note the repo README advertises `review-animations` and `pick-ui-library`, but **neither is present in the installed set** — use `improve-animations` for the audit role instead.

---

## Cold-start checklist for the implementing session

This plan is written to be picked up by a fresh session with no prior context.

1. Read `CLAUDE.md` → `DEVIATIONS.md` → newest file in `reports/` → `docs/specs/06_implementation_protocol.md` → `docs/specs/10_frontend_build_plan.md` + `11_design_system_and_theming.md` → `frontend/FRONTEND_HANDOVER.md` → this file.
2. **Do not re-litigate the design.** The direction, brand name, palette strategy, and motion personality are settled below. The handover §3.5 lists typography already rejected — do not re-propose it.
3. **Do not start at Phase 1.** Phase 0 revises authoritative specs; skipping it means implementing against documentation that contradicts the code, which is the specific failure this plan exists to prevent.
4. Confirm the two blocking facts are still true before scaffolding: `main` contains M3, and `frontend/` has no `package.json`.
5. The brainstorm artifacts are at `.superpowers/brainstorm/87988-1785011410/content/` — untracked and deletable. Phase 0.1 preserves the four approved ones before anything touches `.gitignore`.

### Decisions already made with the user — do not reopen

| Decision | Value |
|---|---|
| Brand name | **TripPlanner** (wordmark *treatment* is still open; the name is not) |
| Display font | Bodoni Moda vs Boska, resolved by license check then rendered comparison (Phase 0.2) |
| UI font | Schibsted Grotesk — approved, settled |
| Palette | Approved hybrid, but **celadon/mangrove-forward**; lacquer red capped <2% of surface |
| Git | M3 merges to `main` first; frontend work on `feat/f1-frontend-foundation` |
| Contract depth | Full — frozen contract + per-component contracts + automated lints |
| Spec 11 §1 token bridge | Confirmed bug; fix to `@theme inline`, log Tier-F row |
| Scope | Phase 0 + F1 only. F2–F4 and G1+ stay out. |

---

## The design thesis

The approved direction sits uncomfortably close to a known AI-design default (warm cream + high-contrast serif + terracotta + hairline rules). The escape is not a new direction — it is that the cliché is **decorative**, applied to any subject, while ours must be **derived** from this subject. Three systems do that work, and everything else stays quiet.

**1. The Route Spine — the signature element.** One primitive: a rule with station nodes. Node states are `done` (filled mangrove) / `current` (ringed) / `pending` (hollow) / `warning` (lacquer). It is the *same* component expressing every sequence in the product:

| Where | What the spine encodes |
|---|---|
| Wizard (F2) | 5 intake steps |
| Loading (F3) | the 7 real backend pipeline stages — never a synthetic timer |
| Itinerary (F3) | day-by-day journey |
| Transfer plan (F3) | points transfer path, verify-first node locked |
| Booking checklist (F3) | ordered pre-booking steps |

This is structure encoding real sequence, not numbered markers as decoration. F1 ships `RouteSpine` + `RouteNode` and proves all four node states in the kitchen sink.

**2. The Ledger — money as typography, never as cards.** Recommendations render as a bordered ruled list with aligned numeric columns (`tabular-nums`), mono unit labels, and hairline row rules. One row is visually dominant. This is a financial-statement pattern, and it is the direct opposite of three equal pricing cards. Cards are used only where a true surface is required.

**3. The Provenance Band — honesty as a visible aesthetic element.** Source and last-verified date render as a mono ledger footnote banded by hairlines, at the foot of any section carrying computed facts. Not a tooltip, not hidden behind an info icon. Spec 12 §3 makes suppressing it a spec violation; this makes it a design feature instead of a compliance tax.

**The one aesthetic risk: notch grammar.** Labels interrupt hairline rules rather than sitting inside pills — the "Recommended" marker breaks the ledger's top rule and bleeds past its left edge. It comes from Peranakan façade tilework, and it solves a real problem (marking the dominant option without adding another pill to a product the handover says already risks too many pills). It repeats as a system: section labels, status markers, the verify checkpoint. Rounded pills are reserved for genuine statuses and compact controls only.

**Palette consequence of the anti-cliché decision:** mangrove `#173A34` and celadon `#BDD3C9`/`#DBE7E0` carry the identity. Lacquer red is capped at **<2% of any screen's surface** — accent rules, the wordmark slash, warning nodes — and is never a section fill. Terracotta-on-cream is the tell; deep green with celadon is not.

---

## Phase 0 — Freeze the design, fix the docs (no implementation)

Nothing in Phases 1–6 starts until this completes.

**0.1 Preserve the brainstorm references.** Screenshot the four approved artifacts in `.superpowers/brainstorm/87988-1785011410/content/` (`calm-route-hybrid-polish.html`, `visual-reset-three-directions.html`, `display-font-real-reset.html`, `motion-personality.html`) at 390/768/1440 via Playwright MCP into `frontend/design/refs/brainstorm/`, with a `MANIFEST.md` stating for each what it approves and what it explicitly does **not** (e.g. hybrid-polish approves grid/route/ledger geometry, not its Bricolage typography). Only then add `.superpowers/` and `.playwright-mcp/` to `.gitignore`.

**0.2 Resolve the display font.** Fetch and read Boska's actual license from Fontshare. Fontshare ships fonts under two licenses and only one permits redistribution:
- **SIL OFL** → self-hosting in this public repo is fine; proceed to comparison.
- **ITF-FFL (closed source)** → redistribution prohibited; **Bodoni Moda wins by default**, stated plainly to the user rather than silently substituted.

If OFL: build `frontend/design/refs/font-decision/` — one polished screen rendered twice, identical but for the display face, using the approved hybrid geometry and Schibsted Grotesk UI layer. It must show hero, functional section heading, result heading, mobile heading at realistic size, tabular numerals (`₹96,400` / `₹38,600`), punctuation, and airport codes (`BOM → SIN`). Judged at real sizes, not at 90px. **Ask the user for one final choice.** Single display family unless they explicitly ask for two.

**0.3 Freeze the palette.** Convert the hybrid hex set to OKLCH and fill all ~22 `--th-*` slots. Render the approved layout twice — lacquer-forward vs celadon-forward — for the user to judge the anti-cliché shift rendered rather than described.

Contrast is a real constraint here, not a formality. Hand-checked before writing any code:
- `#68716B` muted on `#FAF8F2` paper ≈ **4.7:1** — passes body, barely. Keep, don't lighten.
- `#B08C48` brass on paper ≈ **2.8:1** — **fails AA as text.** Savings is the money moment, so this blocks the gate.
- Spec 11 §3's `--th-warning: oklch(0.70 0.13 75)` and `--th-savings: oklch(0.72 0.11 85)` land ≈2.2–2.5:1 — same failure.

Fix mechanically, not by redesign: ship **paired tokens** — a decorative `--th-savings` (fills, rules, underlines) and a darker `--th-savings-text` (L≈0.45, hue held) for text on light surfaces. Same split for `warning` and `success`.

**0.4 Revise the authoritative specs.** Surgical edits only — the token *architecture*, semantic token *names*, and light-theme-only decision all remain valid and untouched.
- `docs/specs/10_frontend_build_plan.md` §2 — font families line.
- `docs/specs/11_design_system_and_theming.md` §1 — `@theme` → `@theme inline` (see 0.5); §3 — the Singapore pack values and typography-voice line.
- Resolve the `--color-savings-highlight` (11 §2) vs `--color-savings` (13 §4.1) naming inconsistency to one name.
- Reconcile the quip-count floor: 11 §5 says ≥30, 15 §3 says ≥40. State that 30 is the pack floor and 40 the Singapore target.
- Mirror any frontend-summary change into `CLAUDE.md` **and** `AGENTS.md` identically.

**0.5 DEVIATIONS rows.** Following the existing 6-column format (`date · doc§ · question · decision · rationale · affected_files`). The existing uncommitted pre-F1 row is under-specified against protocol §2 — rewrite it to quote both conflicting passages verbatim. New rows:
- **Tier-F design change** — fonts + palette revision, quoting the superseded spec text.
- **Tier-F spec bug** — spec 11 §1's `@theme` bridge is broken in Tailwind v4; corrected to `@theme inline`; nested-theme proof test added as the gate.
- `--radius-s` shadows Tailwind's logical-side `rounded-s` utility.
- Savings/warning/success split into decorative + text token pairs.
- Magic UI / Aceternity registry namespaces registered in `components.json` but zero components installed at F1.

**0.6 Write the frozen design contract** → `frontend/design/CONTRACT.md`: font families and delivery, full semantic token table, type scale **with allowed contexts per size** (this is what stops display type leaking into dense functional headings — the handover names it as a root cause of the rejected rounds), spacing scale, radius rules, shadow/elevation rules, border rules, breakpoints, motion tokens, reduced-motion substitutions.

---

## Phase 1 — Git hygiene and scaffold

Commit the DEVIATIONS work, open a PR for `feat/m3-evals-provenance`, **user merges it**, then branch `feat/f1-frontend-foundation` off updated `main`. Preserve `docs/research/17_orchestration_substrate_adk.md` (unrelated user work).

`create-next-app` refuses non-empty directories and `FRONTEND_HANDOVER.md` is not on its allowlist. Scaffold to a sibling and `rsync` in, rather than temporarily relocating the handover:

```bash
npx create-next-app@latest frontend-scaffold \
  --typescript --tailwind --app --src-dir --eslint --empty \
  --skip-install --use-npm --import-alias "@/*" --yes
rsync -a frontend-scaffold/ frontend/ && rm -rf frontend-scaffold
cd frontend && npm install
```

Then create the spec-10 §4 frozen layout (`src/app/`, `components/ui/`, `components/product/`, `themes/`, `lib/api/`, `lib/motion/`, `content/quips/`, `mocks/`, plus `design/refs/`, `e2e/`, `scripts/`, `tests/`). `lib/api/` and `mocks/` stay empty until F2 but exist now so the layout can't drift.

tsconfig: add `noUncheckedIndexedAccess` and `noImplicitOverride`. **Do not** enable `exactOptionalPropertyTypes` — generated shadcn components trip it constantly and the only fixes are structural edits to `components/ui/`, which spec 10 §2 forbids.

Keep create-next-app's generated `frontend/AGENTS.md`, prepending an authority-order preamble pointing at root `AGENTS.md` and specs 10/11.

Verify current APIs via **Context7** rather than memory — Next.js 16 (Turbopack default, `next build` no longer lints), Tailwind v4, and the shadcn CLI have all moved.

---

## Phase 2 — Token architecture (highest-risk phase)

**Order matters: `shadcn init` first, commit its output as-generated, then write tokens over it.** shadcn's v4 variable surface is not what earlier versions emitted; writing an alias block against a guessed contract and having `init` overwrite it is strictly worse than reading the real output once.

`shadcn init` with `--base radix` (Magic UI and Aceternity are written against Radix; `--base` is effectively immutable), `--css-variables` (non-negotiable — `false` inlines color utilities into every component and makes theming impossible), baseColor `neutral`. In `components.json`, `tailwind.config` must be `""` — a non-empty value means it mis-detected v3, and that must be fixed before adding any component. Register the Magic UI and Aceternity namespaces now; install **zero** items from them at F1.

**`frontend/src/themes/base.css`** carries two blocks, and the split is the whole ballgame:

```css
/* Layer 1 — static primitives. Plain @theme: no var() refs, safe at :root. */
@theme {
  --text-hero: clamp(3.5rem, 2rem + 6vw, 6rem);   /* + h1, h2, h3, body, caption */
  --radius-s: 6px; --radius-m: 12px; --radius-l: 20px; --radius-full: 9999px;
  --dur-fast: 180ms; --dur-base: 320ms; --dur-slow: 650ms;
  --ease-brand: cubic-bezier(0.22, 1, 0.36, 1);
  --blur-overlay: 16px;
}

/* Layer 2 bridge + Layer 3 — destination-dependent. MUST be inline. */
@theme inline {
  --color-bg: var(--th-bg);
  --color-primary: var(--th-primary);
  /* …full spec 11 §2 semantic contract… */
}
```

Plain `@theme` substitutes `var()` at the **declaring** element (`:root`), not the consuming one. It appears green while `.theme-singapore` sits on `<html>` — because there `:root` and the theme class are the same element — then renders **transparent, with no console error**, the moment a second theme is scoped to a subtree. That is the exact scenario the destination-pack architecture exists for. `@theme inline` emits `.bg-primary { background-color: var(--th-primary) }`, resolving at the consuming element via normal cascade. This is what shadcn's own v4 template does.

**The law, stated at the top of `base.css`:** anything destination-dependent is declared either inside `.theme-<dest>` as `--th-*` or inside `@theme inline`. Product code consumes destination values **only** through Tailwind utilities (`bg-surface`, `text-text-muted`, `shadow-2`) — never `var(--color-*)` in raw CSS or inline styles, which re-introduces the same trap.

**Vendor alias block.** shadcn components hardcode `bg-background`, `text-muted-foreground`, `border-input`, `ring-ring`, etc. — none are spec 11 §2 names. Alias them onto `--th-*` in the same `@theme inline` block under a clearly-marked *"vendor compatibility, product code must never use these"* heading. Consequence: every future `shadcn add` is on-theme with **zero edits** to `components/ui/`, and the vendor vocabulary never leaks into product code.

`globals.css` then reduces to a four-line manifest — `@import "tailwindcss"`, `tw-animate-css`, `../themes/base.css`, `../themes/singapore.css` — with shadcn's `.dark` block and `@custom-variant dark` deleted (no dark mode, Tier F).

Two mechanical landmines, both silent-wrong-render if missed: `--radius-s` shadows Tailwind's logical `rounded-s` utility (accept, lint against `rounded-s*`/`rounded-e*`), and **there is no `--duration-*` namespace in v4** — `duration-fast` will not exist, so add explicit `@utility dur-fast|dur-base|dur-slow` blocks and lint against bare `duration-\d+`.

`singapore.css` fills every `--th-*` slot including the new decorative/text pairs. `_template.css` is the blanked copy with inline instructions.

---

## Phase 3 — Fonts and assets

Display font per Phase 0. Bodoni Moda → `next/font/google`, zero committed files, and its variable `opsz 6..96` axis used properly (low optical size at small sizes, high at display) — a genuine editorial lever most implementations skip. Boska → `next/font/local` with `.woff2` files plus the license text committed alongside.

Schibsted Grotesk (UI) and Roboto Mono (metadata, airport codes, provenance) via `next/font/google`. Roles: **display** for hero/section headings only, **UI** for everything functional including money, **mono** small and never dominant. `next/font` writes CSS variables onto `<html>`, which is precisely why `--font-display` must live in the `@theme inline` block.

Self-host destination images under `public/img/singapore/` with a `MANIFEST.md` recording source URL, platform, license, and crop intent. Pexels/Pixabay preferred; never the Unsplash API; no recognizable faces; no brand logos. Lucide icons only.

---

## Phase 4 — Primitives and product wrappers

`shadcn add` exactly what the kitchen sink needs and nothing speculative: `button card input label textarea select badge separator accordion dialog sheet tabs tooltip skeleton alert progress`. Use the **shadcn MCP** (`get_add_command_for_items`) so names are registry-validated rather than guessed. Never structurally modify `components/ui/` — the alias block means you don't have to. Compose instead.

Product wrappers in `components/product/`, each expressing a stable product concept:

| Component | Purpose |
|---|---|
| `RouteSpine` / `RouteNode` | the signature primitive; 4 node states |
| `DecisionLedger` / `LedgerRow` | ruled numeric list; notched "Recommended" marker |
| `MoneyText` | **the sole money formatter**, tabular-nums, renders fields only |
| `ProvenanceBand` | mono hairline-banded source + last-verified footnote |
| `TrustChip` | verified / warning — the only way provenance renders |
| `WhyThis` | inline expandable disclosure; plain-language collapsed, math expanded |
| `NotchLabel` | the rule-interrupting label primitive |

Each gets a contract doc in `frontend/design/contracts/<Component>.md`: purpose, variants, anatomy, every applicable state, keyboard behavior, mobile behavior, token usage, **forbidden styling**, and one approved screenshot. Every component renders a sensible empty/loading/error variant (spec 14).

Motion: `lib/motion/` holds shared variants, easings, and a single `useReducedMotionSafe`. Guided Reveal codified from the approved artifact — 80ms stagger, `--dur-slow` (650ms) entrance total, `--ease-brand` everywhere, route-line draw as SVG `stroke-dashoffset`. Use ECC `motion-foundations` for token/spring structure and `motion-advanced` for the SVG path drawing. **Motion for React only** — no GSAP, Lenis, or second animation runtime at F1.

---

## Phase 5 — Kitchen sink

`/kitchen-sink` route, product-flavored, proving the system without pretending to be the finished product: type scale with allowed contexts, palette and contrast pairs, surfaces and elevation, button and field states, badges and provenance, a route/wayfinding sample, numeric alignment, disclosure behavior, loading and error states, modal/sheet/dialog, reduced-motion preview.

**Plus a nested-theme proof section**: a `<div class="theme-proof">` overriding two `--th-*` values, so a Playwright assertion can prove a `.bg-primary` element inside it computes differently from one outside. That single assertion converts the Phase 2 architecture from an assumption into a gate check.

Must not become a generic wall of component cards.

---

## Phase 6 — Gate F1

### Machine-enforced guardrails

**`frontend/scripts/token-lint.mjs`** — zero-dependency Node script, `--json` mode, suppression via `/* token-lint-disable-next-line <rule> -- <reason> */` where the reason is *required*. Scopes `src/app/**`, `src/components/**`, `src/lib/motion/**`; exempts `src/themes/**`. Rules: no raw color literals (strip `href="#…"`/`url(#…)` contexts first to avoid false positives on anchors); no inline `<svg>` (kills the icon-fill false positive at source — Lucide only anyway); no raw radius; no logical-radius utilities; no hardcoded durations or cubic-beziers; `globals.css` must equal the 4-line manifest; **no shadcn vendor utility names outside `components/ui/`**; no `dark:`/`next-themes`; no `var(--color-*)`/`var(--th-*)` in product code; no arbitrary color values; no `localStorage`/`sessionStorage`; no `tailwind.config.*`; no `framer-motion` in the lockfile (registry components drag it in, duplicating the `motion` engine).

The vendor-token rule is what actually enforces spec 11 §2's "components may use ONLY these" — without it, the product vocabulary drifts to shadcn's within a week and destination theming quietly stops meaning anything.

**`frontend/tests/contrast.test.ts`** + `scripts/parse-theme.ts` — postcss-parses the theme CSS, resolves the `@theme inline` bridge one level, converts OKLCH→sRGB via `culori`, and **composites alpha over the declared backdrop** before computing ratios (borders and overlays carry alpha; skipping this reports wildly wrong numbers). Asserts a hand-authored pair matrix rather than an auto cross-product — auto-generating ~40 pairs produces false failures that teach people to loosen the threshold. A **completeness assertion** requires every text and surface token to appear in ≥1 pair, so you cannot add a token and forget to test it. Throws on unresolved tokens; never skips.

Borders are handled separately: spec 11 freezes hairlines at 8–10% opacity, which composites to ~1.05:1, so asserting 3:1 would fail the approved design on day one. Borders assert a *visibility* threshold (ΔL after compositing) — which doubles as the programmatic version of the gate's "hairline borders visibly present" — while **focus rings** carry the real 3:1 obligation and are tested against every surface they can appear on.

**Playwright** at 390/768/1440 plus a reduced-motion project. Runs against a **production build (`next start`), never `next dev`** — the dev overlay pollutes screenshots and React dev-mode warnings break the zero-console-errors assertion. Determinism: `networkidle` → `document.fonts.ready` → `screenshot({ fullPage: true, animations: 'disabled' })`. Plain `page.screenshot()`, not `toHaveScreenshot()` — F1 has no baseline, so pixel comparison would only record whatever exists; visual-regression baselines start at F2. Console guard subscribes to `console` error *and* warning, `pageerror`, and `requestfailed`, with **no allowlist**. axe asserts `violations.length === 0` and writes `incomplete[]` to the report with a named manual sign-off (frosted `--color-surface-overlay` panels land in `incomplete` by design; failing on those guarantees someone disables the rule). The reduced-motion spec asserts every `[data-motion]` element computes `opacity >= 0.99` — the real bug being caught is Motion's `initial={{opacity:0}}` never animating in and leaving content permanently invisible.

**Root `Makefile`**, matching existing backend-gate style:

```make
gate-f1: fe-typecheck fe-token-lint fe-contrast fe-build fe-gate-shots
```

Sub-second browser-free checks run first so a raw hex fails in 2s rather than after a 40s build. `fe-e2e-install` (Chromium download) is deliberately *not* a prerequisite — a 150MB download inside a gate makes it non-reproducible offline.

**`frontend/design/ANTI_GENERIC.md`** — the PR checklist from handover §8.3, plus a ticket template for delegated work (exact files allowed to change, visual reference, component contract, required tokens, explicit non-goals, acceptance test, screenshot sizes, console/type-check expectations).

### Evidence

Committed to `frontend/design/refs/f1/` with deterministic filenames (re-runs overwrite rather than accumulate): screenshots at three viewports plus reduced-motion, `axe-report.json`, `contrast-matrix.md`, `MANIFEST.md`. Churn (`test-results/`, `playwright-report/`, `blob-report/`) is gitignored.

`reports/frontend_F1.md` mirrors the `reports/milestone_3.md` structure — Date/Branch/Scope preamble → Result → Gate F1 with literal commands and pass counts → verification output → implemented files → boundary checks → Deviations → Next milestone. Include `npm ls --prod --depth=0` as the "no unapproved dependencies" evidence.

---

## Dependency budget

**F1 only:** `next`, `react`, `react-dom`, `motion`; auto-installed by shadcn (`lucide-react`, `clsx`, `tailwind-merge`, `class-variance-authority`, Radix, `tw-animate-css`); dev — `typescript`, `tailwindcss`, `@tailwindcss/postcss`, `postcss` (declared explicitly, the contrast parser depends on it directly), `eslint`, `@playwright/test`, `@axe-core/playwright`, `vitest` (node environment only — no jsdom, no testing-library, ~15 packages saved), `culori` + `@types/culori`.

**Installing any of these at F1 is a gate failure:** `@tanstack/react-query`, `@hey-api/openapi-ts`, `zod`, `msw` (F2); `gsap`, `lenis`, `maplibre-gl`, `canvas-confetti` (F3/F4); `storybook`; `next-themes`; `three`; `framer-motion`; `tailwindcss-animate`.

---

## Skills, MCPs, and tools

Verify MCP connections at session start rather than assuming they survived a restart. ECC's `taste` skill is music-video creative direction, not UI, and does not apply.

| Phase | Skills | MCP / tools |
|---|---|---|
| 0 design | `frontend-design`, **`apple-design`**, ECC `frontend-design-direction`, ECC `design-system` | Playwright (reference screenshots), WebFetch (Boska license) |
| 0 docs | **`animation-vocabulary`** (exact names for the motion contract), Superpowers `writing-plans` | — |
| 2 tokens | ECC `design-system`, ECC `frontend-a11y` | **Context7** (Tailwind v4 `@theme inline`, Next 16) |
| 3–4 build | **`emil-design-eng`**, **`apple-design`**, ECC `make-interfaces-feel-better`, ECC `motion-foundations`, `motion-advanced`, `react-patterns` | **shadcn MCP** (never hand-write a registry component or invent props), Next.js DevTools MCP (`get_errors` after every client/server-boundary change — hydration mismatch is this stack's likeliest failure) |
| 5–6 gate | **`improve-animations`** (read-only motion audit as gate evidence), ECC `e2e-testing`, `verification-loop`, `delivery-gate`, Superpowers `verification-before-completion` | Playwright MCP, Chrome DevTools MCP (F4, not F1) |

`find-animation-opportunities` is an F3 tool (Guided Reveal, results scroll story), not F1 — at F1 the correct answer to "what else could animate?" is almost always *nothing*.

**Two of these are load-bearing, not decoration:**

- **`apple-design` covers typography optical sizing, tracking, and leading** — which is exactly the Bodoni Moda `opsz 6..96` decision in Phase 3, and exactly the failure mode the handover blames for the rejected rounds ("oversized headings, over-tight tracking, display faces in dense functional headings"). Use it when writing the type scale's allowed-contexts table, not after.
- **`animation-vocabulary` serves the model-proof goal.** The handover §8 warns "do not ask a cheaper model to make it premium." The same applies to motion: "make it smooth" is not a spec. Phase 0.6's contract must state each motion as trigger + property + duration token + easing token + stagger + reduced-motion substitution, and that skill supplies the precise term for each effect so the contract is unambiguous.

**Figma is not used at F1** — there is no source frame, and spec 10 §3 notes low-tier seats cap MCP usage at ~6 calls/month. Code is the source of truth. **No travel-provider MCP** (Gondola et al.) — provider work begins after F4/G1.

Every registry component, if any are ever added: reviewed line-by-line including comments, rewired to semantic tokens in the same commit, checked for keyboard and reduced-motion behavior, checked for unnecessary dependencies.

---

## Verification

1. `make gate-f1` — typecheck, token-lint, contrast matrix, production build, Playwright screenshots + axe + console + reduced-motion. All green.
2. `frontend/e2e/f1-theme-scope.spec.ts` proves nested `.theme-*` override re-colors `bg-primary` — the Phase 2 architecture check.
3. `make fe-token-lint` green **after** the 16-component shadcn add with zero edits to `components/ui/` — proves the vendor alias block works.
4. `make fe-contrast` green **before** any component exists — the matrix must catch a real violation as its first catch, not a backlog.
5. Manual review of the three committed viewport screenshots against spec 11's checklist and the anti-generic list.
6. Full backend regression still green (`make gate-m1 gate-m1b gate-m2 gate-m3`) — nothing in this work touches backend behavior or golden numbers.

---

## Explicitly out of scope

No backend Tier-F behavior or golden-number changes. No `contract/openapi.json` generation, API client, Zod schemas, MSW, or wizard (F2). No results page, map, GSAP, or Lenis (F3). No performance work (F4). No provider gateway, adapters, crawling, or travel-provider MCP (G1+). No dark mode. No `localStorage`/`sessionStorage`.

**Known gap logged, not fixed here:** the backend's `POST /plan` is synchronous and takes `{raw_request: str}`, while spec 12 §2 specifies an async job + poll API with a wizard-shaped `TripIntakeRequest`. Spec 12 pre-approves the job wrapper as a `SCOPE+` deviation, but that row does not exist yet. This is F2's first task and must ship as one PR (model change + snapshot + generated code + fixtures + UI) per spec 12 §8.
