# Frontend design contract — frozen for F1

This is the model-proof foundation the handover (§8.1) and plan (Phase 0.6) require:
a contract specific enough that a cheaper model can implement components against it
without making taste decisions. It supersedes anything in `docs/specs/10_frontend_build_plan.md`
and `docs/specs/11_design_system_and_theming.md` only where this file is *more specific*
(exact px/OKLCH/timing values); those specs remain authoritative for architecture,
milestone gates, and Tier-F/C/V classification. Component-level detail (variants,
states, forbidden styling) belongs in `frontend/design/contracts/<Component>.md`,
written per-component in Phase 4 — this file is the shared foundation those depend on.

Evidence trail: `frontend/design/refs/brainstorm/` (approved geometry/route/ledger
references), `frontend/design/refs/font-decision/` (Boska disqualified, no comparison
built — see below), `frontend/design/refs/palette/` (celadon/mangrove-forward
confirmation render + contrast matrix), `DEVIATIONS.md` (Tier-F rows for both).

---

## 1. Fonts — families and delivery

| Role | Family | Delivery | Contexts |
|---|---|---|---|
| Display | **Bodoni Moda** (variable, `opsz 6..96`) | `next/font/google`, `font-optical-sizing: auto` (opsz auto-tracks to rendered size — no manual axis wiring needed) | hero, h1, h2 **only** — never h3 and below, never body, never money/points, never dense functional headings |
| UI | **Schibsted Grotesk** (400/500/600/700) | `next/font/google` | navigation, body, form controls, buttons, result labels, h3 and below, **all monetary and point values** |
| Mono | **Roboto Mono** (400/500) | `next/font/google` | airport codes, timestamps, provenance/trace labels, overline eyebrows, small metadata only — never dominant |

**Boska is rejected, no live comparison built.** Fontshare's own site titles its
ITF-FFL license page "Closed Source License," and that license prohibits sharing
font files publicly or with third parties — incompatible with self-hosting `.woff2`
binaries in this public repository. Per the plan's own Phase 0.2 rule, this resolves
the choice by default rather than by rendered judgment. See `DEVIATIONS.md`'s
Tier-F design-change row.

None of the three fonts are self-hosted binaries; all load through `next/font/google`,
so there is no font-license-in-repo question for F1.

---

## 2. Type scale — sizes, and the allowed-contexts rule that stops display leakage

The rejected rounds failed for a specific, recurring reason (handover §3.5): oversized
headings, over-tight tracking, and display faces used in dense functional headings.
This table is the mechanical guard against repeating it — per component/heading, check
the row, don't improvise.

| Token | Size (clamp) | Line-height | Letter-spacing | Font | Allowed contexts |
|---|---|---|---|---|---|
| `--text-hero` | `clamp(3.5rem, 2rem + 6vw, 6rem)` (56→96px) | `1.0` | `-0.02em` | Display | Landing hero only. One per page. |
| `--text-h1` | `clamp(2.5rem, 1.8rem + 3vw, 3.5rem)` (40→56px) | `1.05` | `-0.02em` | Display | Page-level heading, at most one per view. |
| `--text-h2` | `clamp(1.75rem, 1.4rem + 1.8vw, 2.25rem)` (28→36px) | `1.05` | `-0.015em` | Display | Section headings ("A clear route through the trade-offs.") — the largest size a *repeating* section header may use. |
| `--text-h3` | `clamp(1.375rem, 1.25rem + 0.6vw, 1.5rem)` (22→24px) | `1.15` | `-0.005em` | **UI, not display** | Card/row/component titles (e.g. `.decision h3`), dialog titles, any heading that repeats more than once per view. |
| `--text-body` | `1rem` (16px) | `1.6` | `0em` | UI | Paragraphs, descriptions, form labels' helper text. |
| `--text-caption` | `0.8125rem` (13px) | `1.5` | `0.01em` | UI or Mono | Metadata, timestamps, fine print. Mono for provenance/codes specifically. |

**The rule, stated plainly:** Bodoni Moda appears in exactly three contexts — hero,
h1, h2. Every other heading level, every money figure, every points figure, every
route-form value, every button label uses Schibsted Grotesk. If a design calls for a
fourth display context, that is a contract change, not a per-component judgment call.

`font-variant-numeric: tabular-nums` is mandatory on every rendered number (Tier F,
spec 11 §2) — money, points, counts, dates in numeral form.

---

## 3. Semantic token table (Tier F — components use ONLY these)

Mechanics: static primitives below (type scale, spacing, radii, shadow ramp, motion
durations) live in a plain `@theme` block in `base.css`. The destination-variable
bridge (`--color-* : var(--th-*)`) **must** live in `@theme inline` — see
`DEVIATIONS.md`'s Tier-F spec-bug row for why plain `@theme` silently breaks nested
theming. Product code consumes only `bg-*`/`text-*`/`border-*`/`shadow-*` Tailwind
utilities — never `var(--color-*)` or `var(--th-*)` directly in product code.

### Singapore pack values (`.theme-singapore`)

**Two-Register System:**
The UI uses two distinct registers (Tier F design change, 2026-08-08):
- **Shell register (default):** Bodoni Moda display, 12px radii, soft shadow ramp, 10% hairline border.
- **Issue register (`.register-issue`):** Poiret One display (with `--th-display-stroke-*` tokens for weight instead of `font-weight`), 0 radii, `shadow-none`, 2px full-opacity mangrove rules, 12px brass offset plate (`OffsetPlate`), split-flap styling for money (`SplitFlap`). Applied **if and only if** the surface renders a number computed by the deterministic kernel.
| Semantic token | OKLCH value | Source role |
|---|---|---|
| `--color-bg` | `oklch(0.947 0.013 87)` | limestone `#F1EDE4` |
| `--color-surface` | `oklch(0.979 0.008 91)` | paper `#FAF8F2` |
| `--color-surface-raised` | `oklch(0.990 0.005 91)` | slightly above paper |
| `--color-surface-overlay` | `oklch(0.979 0.008 91 / 0.72)` | frosted, pair with `--blur-overlay` |
| `--color-border` | `oklch(0.28 0.01 145 / 0.10)` | hairline, ~10% opacity |
| `--color-text` | `oklch(0.281 0.007 145)` | ink `#272A27` |
| `--color-text-muted` | `oklch(0.525 0.014 157)` | tuned from `0.539` during F3 for AA 4.5:1 on `--color-bg` (within spec 11 §3's ±0.03 L tolerance) |
| `--color-text-faint` | `oklch(0.660 0.014 157)` | decorative/hint only — never the sole rendering of required content (2.91:1 on paper, below AA) |
| `--color-text-on-primary` | `oklch(0.979 0.008 91)` | paper, for text on mangrove |
| `--color-primary` | `oklch(0.320 0.042 181)` | mangrove `#173A34` |
| `--color-primary-hover` | `oklch(0.270 0.042 181)` | darkened mangrove |
| `--color-accent-1` | `oklch(0.848 0.027 167)` | celadon-1 `#BDD3C9` |
| `--color-accent-2` | `oklch(0.917 0.016 161)` | celadon-2 `#DBE7E0` |
| `--color-accent-3` | `oklch(0.660 0.097 82)` | brass `#B08C48` |
| `--color-accent-4` | `oklch(0.536 0.135 30)` | lacquer `#AE493B` — **<2% of any screen's surface, never a section fill or large text run**; accent rules, wordmark slash, route-node markers, the "Recommended" notch only |
| `--color-success` | `oklch(0.580 0.120 155)` | decorative (fills, rules) |
| `--color-success-text` | `oklch(0.450 0.120 155)` | text — 6.52:1 on paper |
| `--color-warning` | `oklch(0.700 0.130 75)` | decorative — staleness/verify meaning, amber hue (deliberately not lacquer; see below) |
| `--color-warning-text` | `oklch(0.450 0.130 75)` | text — 7.09:1 on paper |
| `--color-danger` | `oklch(0.550 0.180 25)` | unchanged; 5.00:1 on paper, no text pair needed |
| `--color-savings` | `oklch(0.660 0.097 82)` | decorative — brass, same value as accent-3 (this is the money moment) |
| `--color-savings-text` | `oklch(0.450 0.097 82)` | text — 7.04:1 on paper |

**Forbidden styling:** any accent color as the sole carrier of meaning (Tier F, spec
11 §2) — pair with an icon or label. `--color-warning` intentionally does **not**
reuse the lacquer hue: `RouteNode`'s warning-state marker may use `--color-accent-4`
directly as a component-specific choice, but the general `--color-warning` semantic
token keeps its own amber hue so it stays visually distinct from `--color-danger`
(hue 75 vs. 25/30 — collapsing them would make two different meanings look identical).

### Shape, depth, motion (shared across all theme packs — `base.css` plain `@theme`)

| Token | Value |
|---|---|
| `--radius-s` | `6px` — shadows Tailwind's logical `rounded-s*` utility; token-lint forbids `rounded-s*`/`rounded-e*` in product code. Note: built-in sizes (`--radius-sm`, `--radius-md`, `--radius-lg` etc.) are also bridged to `--th-radius-*` in `base.css` to allow components to use standard Tailwind classes (like `rounded-sm`) while still responding to register theming. |
| `--radius-m` | `12px` |
| `--radius-l` | `20px` |
| `--radius-full` | `9999px` — reserved for genuine status pills and compact controls, never a default container shape. Note: the `issue` register explicitly keeps this rounded (does not zero it). |
| `--shadow-1` | rest state — layered, low-opacity, soft (e.g. `0 1px 2px oklch(0.281 0.007 145 / 0.06), 0 8px 24px oklch(0.281 0.007 145 / 0.05)`) |
| `--shadow-2` | hover state — one step heavier |
| `--shadow-3` | modal/overlay — heaviest, paired with `--blur-overlay` |
| `--blur-overlay` | `16px` |
| `--dur-fast` | `180ms` |
| `--dur-base` | `320ms` |
| `--dur-slow` | `650ms` |
| `--ease-brand` | `cubic-bezier(0.22, 1, 0.36, 1)` — confident settle; components read this token, never hardcode a curve |

**Depth rule (Tier F):** For **shell surfaces only**, elevation = surface tint + layered shadow + hairline border
together, never shadow alone. (Issued documents in the `issue` register use an offset plate instead.) Borders are 1px at ~8–10% text-color opacity (asserted
at Gate F1 as a *visibility* threshold — ΔL after alpha compositing — not a 3:1
contrast ratio, since hairlines compositing at ~10% opacity land near 1.05:1 by
design). **Focus rings** are the exception: they carry the real 3:1 WCAG obligation
and are tested against every surface they can appear on.

**Border rule:** every border is `1px solid var(--color-border)` unless a component
contract explicitly calls for a heavier rule (e.g. the featured-decision box in the
ledger, or the `issue` register's 2px document border). No arbitrary border colors or widths in product code.

---

## 4. Spacing scale

Tailwind v4's default spacing scale (`4px` base unit, `space-1`…`space-96`) is used
as-is — Tier V, no custom spacing tokens. Section padding follows the geometry proven
in `calm-route-hybrid-polish.html`: generous outer margins (~60px desktop / ~22px
mobile), hairline-separated rows rather than card gaps for repeating list items (the
ledger pattern), asymmetrical split grids (53/47, not 50/50) for hero-style
compositions.

---

## 5. Breakpoints

Matches the three required screenshot viewports (Doc 10 §5 gates): **390px** (mobile,
single column, `.hero`/`.decision`/`.section-heading` grids collapse to 1 column),
**768px** (tablet, `.decision` keeps a compressed 4-column grid, summary column
hidden), **1440px** (desktop, full grid). Breakpoint values: `max-width: 960px` for
the tablet collapse, `max-width: 650px` for the mobile collapse — matching the
brainstorm reference CSS, not arbitrary new values.

---

## 6. Motion tokens and reduced-motion substitutions

Motion personality is **Guided Reveal** (handover §2.4): ordinary interaction quiet
and fast, one orchestrated route-drawing moment, controlled-sequence reveals, the
interface settling and becoming still afterward. Exact vocabulary (per
`animation-vocabulary`), each stated as trigger + property + duration token + easing
token + stagger + reduced-motion substitution:

| Effect | Trigger | Property | Duration | Easing | Stagger | Reduced-motion substitution |
|---|---|---|---|---|---|---|
| **Stagger entrance** (recommendation rows, wizard steps) | View/section enters | `opacity`, `transform: translateY` | `--dur-slow` (650ms) total | `--ease-brand` | 80ms between siblings | All items render at full opacity immediately, no translate |
| **Line drawing** (RouteSpine SVG path) | Section enters / step advances | `stroke-dashoffset` | `--dur-slow` | `--ease-brand` | — | Path renders fully drawn (`stroke-dashoffset: 0`) immediately |
| **Accordion** (Why This? disclosure) | Click/tap | `height` via Motion layout animation, `opacity` on content | `--dur-base` (320ms) | `--ease-brand` | — | Instant show/hide, no height animation |
| **Hover effect** (buttons, decision rows) | Pointer enter | `background-color`, `border-color`, or `color` shift to `-hover` token | `--dur-fast` (180ms) | `ease-out` | — | Unaffected — hover feedback is not motion in the reduced-motion sense |
| **Press/tap feedback** (buttons) | Pointer down | `transform: scale(0.98)` | `--dur-fast` | `ease-out` | — | Unaffected (per apple-design §1: feedback on press, not release, and reduced-motion targets *decorative* movement, not input feedback) |

Global rule: `prefers-reduced-motion: reduce` replaces every slide/stagger/draw effect
above with an instant state or a plain opacity crossfade — never removes the content,
never removes press/hover feedback (apple-design §14). Every `[data-motion]` element
must compute `opacity >= 0.99` under reduced motion (Gate F1 assertion, plan Phase 6)
— the specific bug this catches is an entrance animation's `initial={{opacity:0}}`
never resolving and leaving content permanently invisible.

**Engine:** Motion for React only at F1 (Doc 10 §2 Tier F). No GSAP/Lenis/second
animation runtime until F3's results-page cinematic scroll.

---

## 7. What this contract does not cover

Component anatomy, variants, and per-component forbidden styling are
`frontend/design/contracts/<Component>.md`, written in Phase 4 for each of
`RouteSpine`/`RouteNode`, `DecisionLedger`/`LedgerRow`, `MoneyText`, `ProvenanceBand`,
`TrustChip`, `WhyThis`, `NotchLabel`. Ticket format for delegated implementation work
is the handover §8.4 format, unchanged by this contract.
