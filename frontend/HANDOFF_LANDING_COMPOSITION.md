# Handoff — F1.5: Landing page composition + visual gates

**Status:** ready to implement. Self-sufficient for a cold start — you do not need any
prior conversation. Read this file top to bottom before touching code.

**Branch:** `feat/f1-frontend-foundation` (current). Do not merge to `main`.

---

## 0. Why this task exists (read this — it determines how you work)

F1–F4 shipped a design system, 22 primitives, a wizard, a results page, and ~2,720
lines of tests and gates. Every gate was green. The product still looked like an
unstyled HTML assignment, because:

1. **No phase ever had "build the landing page" as a deliverable.** F1 ended at a
   `/kitchen-sink` showroom, F2 = wizard, F3 = results, F4 = performance. The landing
   page fell between milestones and is still the Next.js scaffold placeholder.
2. **`CONTRACT.md` §7 deferred component anatomy to `design/contracts/<Component>.md`,
   which was never written.** The frozen contract covers tokens, type, and motion — and
   formally excludes layout.
3. **Every gate checks vocabulary, never composition.** token-lint's 12 rules all forbid
   bad *values*. Nothing asked "does this class resolve?" or "does this match the
   approved picture?"

Two independent bug classes came out of that. Both are your responsibility here:

- **Composition never built** — primitives exist but are imported *only* by
  `/kitchen-sink`. The house is unfurnished.
- **Dead token classes** — e.g. `text-on-primary` is not a real token (the token is
  `--color-text-on-primary`, so the class is `text-text-on-primary`). Tailwind silently
  generates nothing and the element inherits its parent color. This made the landing
  CTA's label invisible (~1.1:1) and the active wizard step's numeral vanish. Five such
  classes existed. **They are already fixed** (see §5), but the *gate* that catches them
  does not exist yet, and you are building it.

**The governing lesson: passing gates is not evidence of a working product. You must
look at the rendered page.** See §7 — it is not optional.

---

## 1. Scope

**In scope**

1. Build the landing page (`src/app/page.tsx`) to the approved composition.
2. Wire/finish the site header (`src/components/product/site-header.tsx` — already
   created, currently imported nowhere).
3. Add gate **G1: no-dead-classes** (mechanical).
4. Add gate **G2: product screenshots** (visual, human/agent-reviewed).
5. Write `frontend/reports/f1_5_landing.md`.

**Explicitly out of scope — do not touch**

- Backend anything. No `backend/`, no golden numbers, no `POST /plan`.
- The results page, `/kitchen-sink`, `/theme-proof`, GSAP, Lenis, the map.
- The wizard's logic or flow (`/plan`). You may fix *visual token* bugs there if G1
  finds them, nothing else.
- **Do not reopen fonts, palette, or the type scale.** They are frozen (§3).
- No new dependencies. No `localStorage`/`sessionStorage`. No dark mode.
- Do not create `tailwind.config.*` (Tailwind v4 is CSS-first; token-lint R11 fails it).

---

## 2. Read these first, in this order

| File | What it gives you |
|---|---|
| `frontend/AGENTS.md` | **This is not the Next.js you know.** Read the relevant guide in `node_modules/next/dist/docs/` before writing App Router code. |
| `CLAUDE.md` (repo root) | Project non-negotiables, decision tiers, repo boundaries. |
| `frontend/design/CONTRACT.md` | **The frozen contract.** Fonts, type scale, tokens, radii, motion, breakpoints. |
| `frontend/design/refs/palette/celadon-mangrove-forward.html` | **The exact approved geometry.** Real CSS with real numbers. This is your primary build target. |
| `frontend/design/refs/palette/celadon-mangrove-forward-1440.png` | What that HTML renders as. |
| `frontend/design/refs/brainstorm/calm-route-hybrid-polish-1440.png` | Approved **layout/density/structure**. Its typography is *rejected* — see §3. |
| `frontend/design/refs/brainstorm/MANIFEST.md` | Exactly what each render approves and rejects. |
| `frontend/scripts/token-lint.mjs` | The 12 rules your code must not violate. |

---

## 3. Frozen design facts (do not re-derive, do not "improve")

### Fonts — CONTRACT.md §1–2
- **Bodoni Moda** (display): hero, h1, h2 **only**. Never h3 or below, never body,
  never money/points, never dense functional headings.
- **Schibsted Grotesk** (UI): navigation, body, form controls, buttons, h3 and below,
  and **all monetary and point values**.
- **Roboto Mono**: airport codes, timestamps, provenance labels, overline eyebrows,
  small metadata. Never dominant.
- `font-variant-numeric: tabular-nums` is mandatory on every rendered number (Tier F).

> The heavy condensed face in `calm-route-hybrid-polish-1440.png` was **rejected** as
> "barely legible" (MANIFEST + handover §3.5). Take that render's *layout, density,
> and structure*; take your *type* from the contract. Same for its red accent — the
> palette froze to celadon/mangrove afterward.

### Type scale — use the tokens, not raw sizes
`text-hero` · `text-h1` · `text-h2` · `text-h3` · `text-body` · `text-caption`

> **Known conflict, decided:** the reference HTML renders the section heading
> ("A clear route through the trade-offs.") at `clamp(40px,4.8vw,64px)`. `CONTRACT.md`
> §2 pins `--text-h2` at 28→36px and **names that exact heading** as the largest a
> repeating section header may use. **Follow the contract — use `text-h2`.** If it
> reads too small beside the reference, say so in your report. Do **not** silently
> upsize it.

### Color tokens — the complete legal set
Use only these as Tailwind utility suffixes (`bg-*`, `text-*`, `border-*`):

```
bg              surface         surface-raised   surface-overlay   border
text            text-muted      text-faint       text-on-primary
primary         primary-hover
accent-1        accent-2        accent-3         accent-4
success         success-text    warning          warning-text      danger
savings         savings-text
```

**Gotchas that already caused shipped bugs:**
- On-primary text is **`text-text-on-primary`** (token is `--color-text-on-primary`).
  `text-on-primary` is dead.
- `bg-canvas`, `text-brass`, `text-primary-text`, `bg-elevated` are **dead** — the real
  ones are `bg-bg`, `text-savings-text` / `text-accent-3`, `text-text-on-primary`,
  `bg-surface-raised`.
- `accent-4` (lacquer) is capped at **<2% of any screen's surface**. Legal uses: accent
  rules, the wordmark slash, route-node markers, the "Recommended" notch. Never a
  section fill or a large text run.
- Never use a color as the sole carrier of meaning — pair with an icon or label.
- Never `var(--color-*)` or `var(--th-*)` in product code (token-lint R8).
- shadcn vendor names (`bg-background`, `text-muted-foreground`, …) are banned outside
  `src/components/ui/` (R6).

### Shape / depth / motion
- `--radius-s` 6px · `--radius-m` 12px · `--radius-l` 20px · `--radius-full` 9999px.
- **`rounded-full` is for genuine status pills and compact controls only — never a
  default container shape.** (A 40px-tall text input at `rounded-lg`→20px reads as a
  pill; that was a real shipped bug.)
- `rounded-s*` / `rounded-e*` are forbidden (R3). `rounded-sm`/`md`/`lg` are fine.
- Elevation = surface tint + layered shadow + hairline border **together**, never shadow
  alone. Borders are `1px solid var(--color-border)`.
- Motion: `--dur-fast` 180ms · `--dur-base` 320ms · `--dur-slow` 650ms · `--ease-brand`.
  Never hardcode ms or `cubic-bezier` in product code (R4). Motion personality is
  **Guided Reveal**: quiet, fast, one orchestrated reveal, then stillness.
- `prefers-reduced-motion` must leave every `[data-motion]` element at `opacity >= 0.99`.
- **Engine: Motion for React only.** No GSAP on this page.

### Breakpoints — CONTRACT.md §5
`max-[960px]` (tablet collapse) and `max-[650px]` (mobile collapse). Screenshot
viewports are **1440 / 768 / 390**.

---

## 4. What to build

Target = `frontend/design/refs/palette/celadon-mangrove-forward.html`. **Open it and
read the CSS** — it carries exact px values for everything below. Reproduce its
geometry with Tailwind utilities and the tokens in §3.

### 4.1 Shell
`width: min(1440px, 100%)`, centered, `bg-surface`, layered shadow, sitting on the
`bg-bg` body.

### 4.2 Site header (`.topbar`)
Already scaffolded at `src/components/product/site-header.tsx` — review it, correct it
against the reference, and **import it into the landing page** (it is currently wired
nowhere). Grid `1fr auto 1fr`, min-height 76px, 38px side padding, hairline bottom
border. Wordmark uses the **UI face** (a logotype is not a heading context) with the
lacquer `/`. Nav collapses at 960px; the "Student prototype · sample data" label hides
at 650px. Routes that don't exist render as plain text, not dead links.

### 4.3 Hero (`.hero`)
Asymmetric **53% / 47%** split, min-height 630px, hairline divider between halves.
Collapses to one column at 960px.

**Left (`.hero-copy`)** — padding `74px 62px 42px`, right hairline border:
- `.overline` — mono, 10px, uppercase, `.09em` tracking, preceded by a 27×2px lacquer
  rule. Text: `Travel intelligence · made human`
- `h1` — display face, `text-hero`, line-height 1.0, tracking `-0.02em`:
  "One journey." / "Every advantage." — the second line in `text-primary` (mangrove,
  **not** lacquer: a 3-word hero line exceeds the <2% lacquer budget).
- Lede paragraph — `text-text-muted`, ~17px, line-height 1.65, max-width 560px.
- `.trust-line` — pushed to the bottom (`mt-auto`), top hairline, 3 columns: bold UI
  label in `text-primary` over a mono uppercase muted caption.
  `Trip-first / NOT ANOTHER FLIGHT-SEARCH WALL` ·
  `Explainable / EVERY NUMBER HAS A SOURCE` ·
  `Human-controlled / YOU APPROVE EVERY NEXT STEP`

**Right (`.planner`)** — `bg-accent-2` with the draughting grid. **A `grid-paper`
utility already exists in `src/themes/base.css`** — use it; do not inline gradients
(R1 forbids color literals in product code).
- `.planner-head` — "JOURNEY DRAFT · 01/04" (mono, uppercase) and a "Ready" status with
  a small success dot.
- `.route-form` — three route rows on a **vertical wayfinding spine** with a node marker
  per row (lacquer / mangrove / brass). Each row: mono uppercase label, then the value
  in the **UI face at ~26px** (a route value is a functional heading — *not* Bodoni),
  a small muted sub-line, and a right-aligned mono code.
  `Origin / Mumbai / Chhatrapati Shivaji Maharaj International / BOM`
  `Destination / Singapore / Changi International Airport / SIN`
  `Travel window / 12–18 October / Flexible by two days / 6 NTS`
  → **Prefer composing the existing `route-spine` / `route-node` primitives.** If their
  anatomy doesn't fit, say so in your report rather than silently duplicating them.
- `.planner-action` — muted hint text plus a full-bleed mangrove CTA
  ("Continue to your wallet →") linking to `/plan`. Square corners, hairline left
  border. Stacks at 650px.

### 4.4 Recommendations section
Padding `70px 62px 76px`, `bg-surface`.
- `.section-heading` — two columns, bottom-aligned, hairline under. `h2` ("A clear route
  through the trade-offs.") in the display face at **`text-h2`** (see §3 conflict note),
  with a muted explanatory paragraph right-aligned opposite it.
- `.decision-list` — three rows on a 5-column grid
  (`66px 1.6fr 1fr 180px 130px`), hairline-separated, min-height 126px. **Hairline rules,
  not cards.** Per row: mono index (`01`), title in the **UI face** at `text-h3`
  (h3 never gets the display face), muted summary, cost in the UI face ~22px with
  `tabular-nums` plus a small muted sub-label, a savings/status note, and a
  underline-style "Why this? +" / "Compare +" action.
- **Row 1 is dominant**: `bg-accent-2`, a heavier mangrove-tinted border, bleeding
  ~20px into the margins, with a **"Recommended" notch** — a small filled lacquer label
  interrupting the top border (mono, 9px, uppercase, `text-text-on-primary`). This is
  the one lacquer fill in the composition.
  Content (sample data — copy verbatim, these are illustrative, not computed):
  - `01 · Transfer, then book · Flights with bank points; hotel on the card that earns the most. · ₹96,400 / effective trip cost · Save ₹38,600`
  - `02 · Keep your points · Pay cash today and preserve every transferable point. · ₹135,000 / cash total · 0 points used`
  - `03 · Lowest cash today · Use more points to minimize immediate out-of-pocket spend. · ₹21,800 / + 112,000 points · Cash-first option`
  - Savings text uses **`text-savings-text`** (AA-safe), never raw decorative brass.
- **Provenance footer** — top+bottom hairlines, mono 10px, muted:
  `Verified inputs: flight fixture · hotel fixture · card rules · transfer rules` and,
  right-aligned, `Last verified 25 Jul 2026 · sample data`.
  → Try the existing `provenance-band` primitive; if its API doesn't fit this content,
  report it rather than quietly forking it.

### 4.5 Do NOT build
The `.swatch-strip` contrast bars at the bottom of the reference HTML are **Phase 0
proof scaffolding**, not product UI. Leave them out.

### 4.6 Responsive
Follow the reference's own `@media (max-width: 960px)` and `(max-width: 650px)` blocks —
they specify exactly what collapses, what hides, and what re-stacks. Body must never
scroll horizontally at 390px.

---

## 5. Already done — keep, don't redo

- Five dead token classes fixed across `page.tsx`, `plan/page.tsx`,
  `kitchen-sink/page.tsx`, `booking-checklist.tsx`.
- `input.tsx`: `rounded-lg` → `rounded-md` (the pill-input fix).
- `base.css`: added the `grid-paper` utility (additive; nothing else changed).
- `site-header.tsx`: created, **imported nowhere** — finish and wire it.

The wizard's "Next" button looking washed out is **correct** — it's the `disabled:opacity-50`
state on an empty form. Do not "fix" it.

---

## 6. The two new gates

### G1 — `no-dead-classes` (mechanical)
A Tailwind utility naming a token that doesn't exist generates **no CSS** and silently
inherits. This is the bug class that shipped an invisible button. Catch it.

Implement as a new rule in `frontend/scripts/token-lint.mjs` (keep its existing
suppression-comment convention), or as a sibling script wired into the Makefile.

Requirements:
- Compare classes used in source against the **full production CSS** — run the Next
  build and concatenate **every** CSS chunk in `.next/`. A single route's chunk is not
  enough and will produce false positives for classes used on other routes.
- Extract candidates from **all string literals**, not just `className="…"` attributes —
  the shipped bug lived inside a template literal with a ternary and was missed by a
  naive `className=` regex.
- Restrict to color-bearing prefixes (`text-`, `bg-`, `border-`, `ring-`, `fill-`,
  `stroke-`, `shadow-`, `outline-`, `divide-`, `from-`, `via-`, `to-`, `accent-`,
  `caret-`, `placeholder-`, `decoration-`) to avoid flagging prose.
- Skip non-Tailwind selectors used as JS/CSS hooks. Known ones: `gsap-section`
  (queried by `gsap-entrance.tsx`), `theme-proof` (a `<style>` block in
  `theme-proof/page.tsx`). Use an explicit allowlist with a comment, not a silent skip.
- **Prove it works before you trust it**: temporarily introduce `text-nonexistent-token`,
  confirm the gate fails, remove it, confirm the gate passes. Show both runs in your
  report.

### G2 — product screenshots (visual)
`fe-gate-shots` today screenshots `/kitchen-sink`. Add the **product** routes.

- Capture `/` and `/plan` at **1440×900, 768×1024, 390×844**, plus one
  reduced-motion pass, into a committed directory (follow the existing
  `design/refs/` conventions).
- Run axe on both routes; **zero violations**. Do not add a filter/exclusion list to
  make it pass — a previous session did that and it hid three real violations.
- Assert the landing page's structure, not just HTTP 200. The current e2e test asserts
  only that `/` returns 200 and has a title, which is why nothing caught an empty page.
  At minimum assert: the header exists; the hero `h1` renders; the planner panel and its
  three route rows render; three decision rows render with exactly one marked recommended;
  the provenance footer renders.
- Add a contrast assertion on **rendered** elements (computed color vs. computed
  background), not just abstract token pairs. The token-pair matrix passed while the CTA
  label sat at ~1.1:1, because the pair being compared was never the pair on screen.

Wire both into `make gate-f1` (and `gate-f4` if it enumerates gates explicitly).

---

## 7. Verification protocol — mandatory, and the whole point

**You are not done when the gates pass. You are done when the page looks right and you
have looked at it.**

1. Run the dev server and **take real screenshots** of `/` at 1440, 768, and 390.
2. **Open those PNGs and look at them.** Then open
   `design/refs/palette/celadon-mangrove-forward-1440.png` and compare side by side.
3. Walk this list explicitly, and write the answers into your report:
   - Is the hero an asymmetric split with a planner panel on the right — not a centered
     column?
   - Is every piece of text actually legible? Check each button and each filled surface
     for inherited-color bugs specifically.
   - Are the route nodes on a visible spine?
   - Is the decision list hairline-ruled with one dominant row and a notch — not a stack
     of cards?
   - Is lacquer under ~2% of the surface?
   - Does the display face appear **only** in the hero and the section heading?
   - At 390px: does anything overflow horizontally?
4. Then run `make gate-f1` and the new gates.
5. If you have not viewed a PNG of the page you built, you are not done. Do not report
   completion off green gate output alone — that is precisely the failure that produced
   this handoff.

---

## 8. Skills to invoke

Invoke what your harness actually has; don't fake it. In rough priority:

- **`frontend-design`** — before writing composition code. This is design-execution work
  against a frozen direction; use it for layout/type/spacing judgment, **not** to
  re-explore the direction (that's frozen — see §3).
- **`superpowers:verification-before-completion`** — before you report done. Given the
  failure this handoff exists to correct, treat this as required.
- **`superpowers:systematic-debugging`** — the moment anything renders unexpectedly,
  before guessing at fixes.
- **`ecc:frontend-a11y`** / **`ecc:accessibility`** — for the axe work in G2.
- **`ecc:react-review`** or **`ecc:typescript-reviewer`** — review your own diff before
  reporting.
- **`ecc:motion-foundations`** / **`motion-ui`** — only if you add the Guided Reveal
  entrance. Keep it to one orchestrated moment; restraint is the brief.

**Do not** invoke a brainstorming skill. The design is frozen and re-exploring it is how
scope drifts.

---

## 9. Definition of done

- [ ] `/` renders the approved composition: header, asymmetric split hero with planner
      panel, trust line, section heading, three hairline-ruled decisions with one
      dominant + notch, provenance footer.
- [ ] Header component is wired and correct at all three viewports.
- [ ] `make gate-f1` green — no narrowed scope, no new axe exclusions.
- [ ] G1 `no-dead-classes` implemented, wired, and **demonstrated to fail** on a
      deliberately broken class before passing clean.
- [ ] G2 product screenshots at 1440/768/390 + reduced-motion, committed, axe clean.
- [ ] Landing-page structural e2e assertions exist and pass.
- [ ] Screenshots visually compared against `design/refs/` and the §7 checklist answered
      in writing.
- [ ] Any judgment call logged to `DEVIATIONS.md` (`date, doc§, question, decision,
      rationale, files`).
- [ ] `frontend/reports/f1_5_landing.md` written: what was built, the §7 answers, both
      G1 runs (failing + passing), and anything that didn't fit the frozen contract.
- [ ] Nothing in `backend/` touched. No new dependencies.

## 10. If you get stuck

Follow the ambiguity protocol in `CLAUDE.md`: do **not** stop and ask. Choose the most
conservative option that changes no Tier-F behavior and no golden number, log it in
`DEVIATIONS.md`, and continue. Escalate to a human only for a confirmed Tier-F spec bug,
anything needing paid services or credentials, or a change to the frozen fonts/palette.

If the composition genuinely cannot be built from the existing primitives without
changing their public API, **build the page and report the mismatch** — do not refactor
shared primitives and the page in the same change (`CLAUDE.md`: behavior changes and
refactors are separate commits).
