# 10 — Frontend Build Plan & Tooling Protocol

Frontend counterpart to `00_README_BUILD_PLAN.md`. Same working discipline: Doc 06's decision tiers, DEVIATIONS.md, and self-review gates apply verbatim, with the frontend-specific gates defined in §5. The implementer reads this doc, then 12 (integration contract) and 11 (design system) fully, before writing code.

## 1. Product bar

This frontend is the product's face and must read as premium: light-themed, cinematic, Apple-grade restraint with destination personality. The differentiated content — the payment strategy, savings math, and transfer plan — must be presented with the same trust-signal care the backend computes it with. "Generic AI-generated dashboard" is a failure state even if every feature works.

## 2. Stack (Tier F — frozen)

- Next.js (App Router) + TypeScript strict. Server components for data/shell; animation leaves are `"use client"`.
- Tailwind CSS v4, CSS-first config: all tokens in `@theme` per Doc 11. No `tailwind.config.js` token definitions.
- shadcn/ui as the component base, themed via semantic tokens only (Doc 11 §2).
- Motion (`motion` package, `motion/react`) as the default animation library. GSAP 3.13 + ScrollTrigger **only** for the results-page cinematic scroll timeline and SVG route drawing (Doc 13 §4). Lenis for smooth scroll on the results page only.
- MapLibre GL JS + OpenFreeMap tiles for the trip map. No Mapbox (free-tier trap), no Google Maps.
- TanStack Query + `@hey-api/openapi-ts` generated client + Zod boundary schemas (Doc 12).
- MSW v2 for all local dev and tests; the frontend must build fully against mocks before the backend is ever attached.
- Fonts via `next/font`: Bodoni Moda (variable, `opsz 6..96`, `next/font/google`, display — hero/h1/h2 contexts only, see Doc 11 §3 type-scale allowed-contexts table) + Schibsted Grotesk (UI/body/money, `next/font/google`) + Roboto Mono (metadata/provenance/airport codes, `next/font/google`). Images via `next/image`, AVIF/WebP, self-hosted curated set (no Unsplash API hotlinking — general-license downloads only; prefer Pexels/Pixabay; no recognizable faces).
- View Transitions API as progressive enhancement only; Motion `AnimatePresence` is the baseline page transition.

Tier C: exact shadcn components used, folder structure below `src/`, Storybook vs. a `/kitchen-sink` route (default: kitchen-sink route — cheaper), ESLint config. Tier V: everything else per Doc 06.

## 3. Tooling & MCP workflow

Priority order when building UI:

1. **frontend-design skill** — the default design brain. Loaded at the start of every UI session; its aesthetic-direction guidance is subordinate to Doc 11's tokens (tokens win conflicts).
2. **shadcn MCP server (official)** — the component acquisition path. Free, no API key, operates against registries configured in `components.json`. Configure the default shadcn registry plus shadcn-compatible third-party registries for animated/marketing components (e.g. Magic UI-class registries) as needed. Rule: **never hand-write a component that exists in a configured registry; never invent registry component props — query the MCP.** Installed components are then themed via semantic tokens.
3. **Figma MCP** — used when a screen has a Figma source (hero, results header). Treat Figma as design *source*, code as truth after generation. Budget-aware: low-tier Figma seats cap MCP usage (~6 calls/month) — batch reads, screenshot frames into the repo (`design/refs/`) as durable references instead of re-querying.
4. **Playwright MCP** — the eyes. Every gate in §5 runs through it: navigate → screenshot at 390/768/1440px → read console → compare against the spec checklist. Also drives the interaction tests (wizard flow, polling states) headlessly.
5. **Chrome DevTools MCP (official Google)** — the performance auditor: record a performance trace on the landing and results pages, extract CWV, diagnose regressions. Used at Gate F4 and after any animation-heavy change.
6. **Next.js DevTools MCP (official Vercel)** — the inner-loop diagnostic. Next.js 16+ exposes a built-in MCP endpoint at `/_next/mcp`; `next-devtools-mcp` connects the agent to the running dev server for live runtime errors (hydration failures with component stacks), forwarded browser console logs/rejections/failed fetches (16.2+), route structure, and version-matched docs from `node_modules`. Protocol: after every component change touching client/server boundaries or animation mounts, query `get_errors` before moving on — hydration mismatches are this stack's most likely failure mode and must never accumulate silently.
7. Optional: a docs MCP (e.g. Context7-class) if the implementer hits API drift in Tailwind v4 / Motion; otherwise official docs via web fetch.

Registry sources for the shadcn MCP (`components.json`): the default shadcn registry, plus **Magic UI** (kinetic text, bento grids, animated beams) and **Aceternity UI** (parallax, 3D cards, spotlight) for cinematic components. Rules: every registry install is (a) rewired to semantic tokens in the same commit — these ship hardcoded palettes that silently break theming — and (b) checked against the F4 performance budget before keeping (some pull three.js-class dependencies; if a component drags WebGL into the bundle, find a lighter equivalent or build it with Motion/GSAP).

MCP security protocol (applies to the whole toolchain): registry-fetched and community-authored component code is reviewed line-by-line like a stranger's PR before commit — comments included, not just JSX. Never run the toolchain with blanket auto-approve on tool calls; content-reading tools chained to local execution is the canonical injection path. No MCP server outside this doc's list is added without a DEVIATIONS entry.

Explicitly rejected (record in DEVIATIONS if revisited): 21st.dev Magic MCP (repo stalled Feb 2026, paid, restrictive free tier, community-snippet injection risk — browse the website for inspiration only, and treat any copied snippet as an untrusted PR requiring line-by-line review); Framer as a build target (no official MCP; hosted builder conflicts with the typed-contract architecture — motion reference only); Lovable for production code (same conflict; throwaway explorations only); localStorage/sessionStorage anywhere (in-memory + backend state only).

## 4. Repo layout

```
frontend/
  src/
    app/                    # routes: / (landing), /plan (wizard), /plan/[jobId] (loading+results)
    components/ui/          # shadcn-installed primitives (themed, never edited structurally)
    components/product/     # composed product components (Doc 14)
    themes/                 # base.css, singapore.css, _template.css (Doc 11)
    lib/api/                # generated client + zod schemas + query hooks (Doc 12; generated/ is gitignored-regenerated)
    lib/motion/             # shared variants, easings, useReducedMotionSafe
    content/quips/          # wit packs (Doc 15)
    mocks/                  # MSW handlers + fixture FinalReports (incl. fallback/partial variants)
  design/refs/              # Figma frame screenshots, motion references
  e2e/                      # Playwright specs
```

## 5. Milestones & gates (self-reviewed per Doc 06 §5; emit reports/frontend_FN.md)

**F1 — Foundation.** Tokens (11), themed shadcn primitives, kitchen-sink route rendering every component in the Singapore theme, fonts/images pipeline.
Gate: Playwright screenshots of kitchen-sink at 3 viewports reviewed against Doc 11's checklist (contrast pairs AA-verified programmatically via axe; hairline borders, shadow ramp, type scale present); zero console errors; `tsc --noEmit` clean.

**F2 — Intake + contract.** Generated API client, Zod schemas, MSW handlers for all response variants, the 5-step wizard, submit → job creation.
Gate: Playwright drives the full wizard happy path + a `needs_clarification` loop against MSW; a11y checks (focus moves to step heading, ARIA announcements fire, axe clean); contract tests from Doc 12 §7 green.

**F3 — Loading + results.** Staged loading experience bound to polling states, quip rotator, full results scroll story with count-ups, payment strategy cards, transfer plan, map, checklist, trust badges.
Gate: Playwright walks a mocked complete flow and screenshots every results section; fallback/partial fixtures render their badges; groundedness spot-check (every number on screen exists in the fixture JSON — scripted); reduced-motion run shows content without motion.

**F4 — Performance & polish.** Image/font optimization, lazy-loading GSAP/MapLibre, page transitions.
Gate: Chrome DevTools MCP performance trace on landing + results (mobile emulation): LCP ≤ 2.5s, CLS ≤ 0.1, INP ≤ 200ms on interactions; Lighthouse a11y ≥ 95; bundle check (GSAP + MapLibre not in initial JS).

Backend does not need to exist until F3-end; the switch from MSW to network is a one-line env change (Doc 12 §8), and F4 includes one end-to-end run against the real Kernel MVP backend using sample data. "Live" at F4 means real frontend↔backend transport, not a live travel-inventory provider. Provider-backed UI extensions begin in G1+ under 09/12/16.
