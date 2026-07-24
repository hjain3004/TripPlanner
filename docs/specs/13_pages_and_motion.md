# 13 — Pages, UX & Motion Spec

Routes: `/` (landing), `/plan` (intake wizard), `/plan/[jobId]` (loading → results, same route, state-driven). Motion division of labor (Tier F): Motion for component/enter/hover/layout; GSAP+ScrollTrigger only inside the results scroll story and SVG route drawing; Lenis mounted on results only.

**Cinematic garnish allowance (post-F4 only, each item individually gated on the F4 budget):** SplitText character-stagger on the landing H1 and verdict header; one scroll-scrubbed image sequence OR pinned parallax scene on the landing (not both); Magic UI/Aceternity registry components per Doc 10's rules. Hard exclusions regardless of gates: WebGL/three.js effects, custom shaders, cursor-follower effects, scroll-jacking beyond ScrollTrigger pinning. The reel-worthy look comes from choreography and typography, not from GPU tricks the demo audience's phones can't run. Every motion respects `prefers-reduced-motion` via a shared `useReducedMotionSafe` — reduced mode swaps movement for opacity fades and disables parallax/pinning/count-up (numbers render final values instantly), confetti, and smooth scroll. This is a Gate F3 test, not an aspiration.

## 1. Landing `/`

Purpose: sell the one differentiating sentence and route to the wizard. Structure (scenes, not sections):
1. **Hero** — full-bleed Singapore dawn imagery under a frosted headline card. H1: "A travel planner that knows your credit cards." Sub: one sentence on effective cost. Primary CTA "Plan my trip". Motion: single staggered fade-up on load (≤ 650ms total); subtle slow Ken-Burns on the image (disabled reduced). LCP element = the hero image: preloaded, priority, AVIF.
2. **How it works** — three steps (trip → cards → strategy) as `whileInView` staggered cards.
3. **Proof strip** — a real (fixture) savings example: "₹153,000 trip → ₹144,223 effective," with the count-up teased on scroll into view.
4. **Trust scene** — provenance/verified-dates/no-credentials positioning ("we never ask for your bank or loyalty logins").
5. Footer with disclaimers.
No GSAP on landing; it must be light and load instantly.

## 2. Intake wizard `/plan`

Five steps, one theme each (Tier F order): 1 Trip (origin/destination/dates/travelers) → 2 Style & budget (style select, budget slider, pace) → 3 Interests (tag picker, dietary) → 4 Cards & points (card-select grid + optional balances) → 5 Preferences & review (objective select, review summary, submit).

Rules: 3–5 inputs per step max; progress indicator with step names; Back never loses state (single client store, e.g. zustand — Tier C); Next disabled until step-valid (Zod per-step schemas derived from TripIntakeRequest); free-text "anything else?" box on step 5 feeds intake's LLM. Card selection renders abstract gradient card tiles with issuer/name text (no logos — 11 §4); selecting flips a subtle 3D tilt (Motion, `whileHover`/`whileTap`). Unknown card names get a "we don't know this card yet" chip → submitted in free-text → may return as `unresolved`.

Accessibility (Tier F, tested at F2): on step change, focus moves to the step `<h2>`; an `aria-live=polite` region announces "Step N of 5, {name}"; all inputs labeled; error summary links focus the field; tag/card pickers are keyboard-operable listboxes; step transition is a 180ms slide (fade in reduced mode).

`needs_clarification` return path: wizard reopens on a dedicated variant of step 5 listing `unresolved[]` as targeted questions above the review; answers merge into the free-text field on resubmit.

## 3. Loading experience `/plan/[jobId]` (status ≠ terminal)

Anatomy (top to bottom): destination hero strip (theme imagery, quiet) → **stage tracker** → **quip rotator** (Doc 15) → skeleton of the results page dimly visible below the fold (sets the mental model of what's coming).

Stage tracker: renders the 7 backend stages as a horizontal step line using `stage_index/stages_total` from PlanJobStatus — real progress only, never a timer (12 §2). Stage labels (display copy, Tier C): Understanding your trip → Designing your days → Pricing it out → Optimizing your cards → Checking your points → Double-checking → Writing it up. Current stage pulses gently; completed stages get a draw-on check (150ms). If `stage` is null: indeterminate shimmer on the tracker, quips carry the wait.

Quip rotator: one quip visible, crossfade every 6s (Doc 15 rules; pauses on hover/focus; `aria-live=off` — decorative). Skeletons use shimmer at `--dur-slow`; reduced-motion: static skeletons, no pulse/shimmer.

On `complete`: the tracker collapses upward, skeleton cross-dissolves into content top-down (900ms staged; instant in reduced mode). On `needs_clarification`/`failed`/timeout: per 12 §4.

## 4. Results scroll story `/plan/[jobId]` (status = complete)

Lenis active; GSAP ScrollTrigger scenes; every number rendered from FinalReport fields only (12 §3).

1. **Verdict header (pinned briefly)** — "Your {N}-day {destination} plan" + the three-number strip: gross → effective cost → savings. Count-ups trigger once on entry (800ms, tabular-nums); savings uses `--color-savings`. A single confetti burst (canvas-confetti, ≤ 80 particles, `disableForReducedMotion`) fires **only if** `savings_pct_bp ≥ 300`.
2. **Itinerary timeline** — vertical day-by-day; each day a card with POI rows (name, area chip, duration, price). Scroll: days fade-up staggered; a thin timeline line draws via ScrollTrigger scrub. Fallback badge here when `itinerary_quality="fallback"`.
3. **Trip map** — MapLibre, theme-tinted style, lazy-mounted on approach (never in initial bundle). Markers per POI grouped by day; hotel area highlighted; flight route as an animated great-circle SVG overlay drawn on scene entry. Static fallback image if WebGL unavailable.
4. **Payment strategy** — the star scene. One card per spend line: recommended card tile (tilt on hover), channel + offers applied, benefit breakdown rows, and a "why not {runner_up}?" expandable rendering the runner-up delta. Section header shows discounts/rewards/forex/fees rollup with mini count-ups. Cap-pool explanations render the optimizer's `explanation` atoms verbatim as a compact "how we got here" list.
5. **Points & transfers** — only when `transfer_advice` present. REDEEM: the plan as a step diagram (transfer arrows with ratios/times), the **VERIFY-first checkpoint visually dominant** (warning-colored, checkbox-gated: transfer steps stay visually locked until the verify item is checked — persuasion via UI, not enforcement), leftover-miles note, vs-cash sentence. PAY_CASH: the numeric reason rendered plainly. NO_DATA: honest one-liner.
6. **Booking checklist** — ordered interactive checklist from `booking_checklist`; checking items animates a progress ring; completing all fires the *other* (single) confetti moment. State is in-memory only.
7. **Assumptions & provenance footer** — assumptions list, min-last-verified date, disclaimers verbatim, "start a new plan" CTA.

## 5. Trust-signal system (used across 4–7)

- **Verified chip**: `✓ verified {date}` quiet chip on facts with fresh provenance.
- **Warning chip**: `--color-warning` dot + "verify before booking" on any `needs_verification`/stale-flagged fact; tooltip carries the provenance note.
- **Confidence**: single report-level indicator in the verdict header (Low/Med/High from `confidence` — thresholds 0.5/0.8, Tier C), tooltip explains it reflects data freshness.
- Badges are calm (caption size, muted) — visible integrity, zero alarm. They may never be styled away (12 §3).

## 6. Performance budget (Gate F4, measured via Chrome DevTools MCP mobile emulation)

LCP ≤ 2.5s (landing & results), CLS ≤ 0.1 (skeleton→content swap must be dimension-stable — skeletons reserve exact layout), INP ≤ 200ms (count-ups and confetti must not block input; confetti uses `useWorker`). Initial JS excludes GSAP, Lenis, MapLibre, canvas-confetti (all dynamic imports on the results route). Transform/opacity-only animation; no layout-property animation anywhere (lint rule if feasible, else grep audit at F4).
