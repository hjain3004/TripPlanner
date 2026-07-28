# TripPlanner F3 — continuation prompt for opencode

Copy everything below this line into opencode. F1 and F2 are complete and
gate-verified for real (not just claimed): `make gate-f1` and `make gate-f2` both
pass with genuine e2e coverage, real WCAG contrast checks, zero-violation axe
runs, and contract tests including a "no orphan numbers" money-safety check. You
are starting F3: the staged loading experience, the full results page, and
provenance rendering.

## 0. A standing rule, added after three rounds of the same mistake

Every prior milestone on this project shipped a gate that initially passed by
**narrowing what it checked** rather than by the underlying thing being correct:
F1's first contrast check used an OKLCH-lightness heuristic instead of real WCAG
math; F1's e2e suite ran under the wrong Playwright config and silently skipped
most of its coverage; F2's axe check filtered out real violations (a genuine
contrast failure, a heading-level skip, a missing landmark) before asserting
zero. All three were caught by actually running the gate and reading full
output, not by trusting a summary.

**Do not repeat this pattern.** If a check is inconvenient to pass honestly: fix
the underlying issue, or explicitly skip it with a `test.skip()`/comment stating
why and log a `DEVIATIONS.md` row — never filter, narrow, or loosen an assertion
to force green. When you report this milestone done, paste real command output.

## 1. Read first, in order

1. `AGENTS.md`, `DEVIATIONS.md` (skim — includes the F1/F2 gate-rigor patch rows;
   don't re-decide anything already logged).
2. `reports/frontend_F1.md` and `reports/frontend_F2.md` — what actually exists:
   16 shadcn primitives, 7 product wrappers (`RouteSpine`/`RouteNode`,
   `DecisionLedger`/`LedgerRow`, `MoneyText`, `ProvenanceBand`, `TrustChip`,
   `WhyThis`, `NotchLabel`), the 5-step wizard, generated API types, Zod schemas,
   MSW fixtures for every spec-12 §4/§6 state. Compose F3 from these — most of
   what a results page needs already exists as a primitive from F1; this
   milestone is largely about wiring real data into them and building the
   loading/scroll experience around them.
3. `frontend/design/CONTRACT.md` — still the frozen visual/motion contract.
4. **`docs/specs/13_*.md`, `docs/specs/14_*.md`, `docs/specs/15_*.md` — read all
   three fully.** (Confirm exact filenames with `ls docs/specs/` — this prompt
   doesn't guess them.) These are F3's actual specs: loading/results page
   structure and the verdict header's exact behavior (13), per-component states
   and anatomy (14), the quip/wit content pack format and rotation rules (15).
   This prompt gives you the sequencing and gate structure around them, not a
   restatement of their content — go read the real numbers, field names, and
   copy rules yourself.
5. `docs/specs/10_frontend_build_plan.md` §5's F3 gate criteria and §2's stack
   rules for GSAP/Lenis/MapLibre scope (see §3 below — these were forbidden
   until now).
6. `docs/specs/12_integration_contract.md` §3 (`FinalReport` consumption rules —
   render-only money, provenance as load-bearing UI, partial-quality flag
   handling) and §4 (error taxonomy — F3 renders results, but the error states
   from F2 still apply if the results page is reached via a retry/refresh path).

## 2. Ground rules that still apply

- **Frontend never computes money or points.** Every number on the results page
  must already exist in the `FinalReport` fixture. F2 built a "no orphan
  numbers" contract test for the wizard/submit flow — extend it (or add a
  parallel one) to cover the full results page now that it renders far more
  numeric content.
- **Provenance is load-bearing UI, not a design choice you can suppress.**
  `provenance_warnings[]`, `confidence`, `assumptions[]`, and per-line
  `needs_verification` render via `TrustChip`/`ProvenanceBand` (already built in
  F1) — wire them to real fixture data, don't invent placeholder states.
  Suppressing them is a spec violation (spec 12 §3.2), not a design decision you
  get to make.
- **Partial-quality flags render honestly.** `itinerary_quality: "fallback"` →
  calm "best-effort itinerary" badge; missing `transfer_advice` → the one-line
  "share balances to unlock" note (already have MSW fixtures for `NO_DATA` from
  F2 — use them); empty sections render honest empty states, never invented
  content.
- **Registry components (Magic UI, Aceternity — registered but unused since
  F1) get reviewed line-by-line and rewired to semantic tokens in the same
  commit if you use any now.** Check the F4 performance budget note in spec 10
  §3 before keeping one — some pull in heavy dependencies.
- **Git actions that push/merge/open PRs need the human present and
  confirming**, same as prior milestones.

## 3. What's newly allowed — scoped narrowly

GSAP 3.13 + ScrollTrigger: **only** for the results-page cinematic scroll
timeline and SVG route drawing (spec 10 §2, spec 13's relevant section). Lenis:
**only** for smooth scroll on the results page. MapLibre GL JS + OpenFreeMap
tiles for the trip map — no Mapbox (free-tier trap), no Google Maps. `canvas-confetti`
is allowed now, but read the exact trigger condition in spec 13 before wiring it
(it's conditional on a savings-percentage threshold, `disableForReducedMotion`
is mandatory, and it's a single burst, not a repeating effect). None of these
four are used anywhere outside the results page — Motion for React remains the
default everywhere else, per spec 10 §2's Tier-F stack rule. Do not introduce a
second general-purpose animation runtime beyond this narrow carve-out.

## 4. Sequence

### 4.1 Staged loading experience

Bind loading UI to the **real** `PlanJobStatus.stage` field from the polling
response (`intake | itinerary | costing | optimizing | transfer | critic |
explaining`) — never a synthetic timer. `RouteSpine` (built in F1, already
proves 4 node states) is the primitive for this per the project's own design
thesis — reuse it, don't build a new progress component. Integrate the quip
rotator per spec 15's exact rules (seeded by `job_id`, stage-aware with generic
fallback, 6s crossfade, `aria-live="off"` since it's decorative). If `stage` is
null while running, indeterminate shimmer + quips only, per spec 12 §2.

### 4.2 Results page — full scroll story

Verdict header (pinned briefly): gross → effective cost → savings, count-ups on
entry, `--color-savings-text` for the savings figure (not the raw decorative
`--color-savings` — that's a fills/rules token, this is text, per `CONTRACT.md`
§3's paired-token rule established in F1). Confetti burst only if the
savings-percentage threshold from spec 13 is met, `disableForReducedMotion:
true`. Payment strategy section via `DecisionLedger`/`LedgerRow` (built, F1).
Transfer plan section wired to real `transfer_advice` data including the
`NO_DATA` honest-empty-state case. Booking checklist. `WhyThis` disclosures
wired to real per-recommendation data (collapsed = plain-language reason,
expanded = computed costs/assumptions/transfer path/provenance, per the
handover's §2.3 information-hierarchy rule this project has held since before
F1). Trip map via MapLibre/OpenFreeMap.

### 4.3 Groundedness and fallback coverage

Every fixture from F2's MSW set (fallback-itinerary, provenance-warnings,
transfer REDEEM/PAY_CASH/NO_DATA) must render its distinct badge/state
correctly on this page — these aren't new fixtures to build, they're the ones
F2 already produced; F3 is where they finally get consumed by real UI.

## 5. Gate F3 (spec 10 §5)

- Playwright walks a mocked complete flow and screenshots every results
  section.
- Fallback/partial fixtures render their badges — one test per fixture from
  §4.3 above, not just the happy path.
- **Groundedness spot-check**: every currency/miles number on the results page
  exists in the fixture JSON it was rendered from — this is the results-page
  extension of F2's "no orphan numbers" test, scripted, not manual.
- Reduced-motion run shows all content present without motion — reuse the
  `[data-motion]` → `opacity >= 0.99` pattern from `CONTRACT.md` §6 and the F1
  gate's reduced-motion project; the GSAP scroll timeline and confetti both
  need real `prefers-reduced-motion` handling, not just the Motion-for-React
  paths.
- Wire this into the established `gate-f3` / `fe-*` Makefile pattern (root +
  `frontend/Makefile`), same convention as `gate-f1`/`gate-f2`. Run
  `make gate-f3` from the repo root yourself and paste the real output.

## 6. Dependency budget — F3 unlocks these

`gsap`, `lenis`, `maplibre-gl`, `canvas-confetti` — each scoped narrowly per §3
above. Still forbidden: `storybook`, `next-themes`, `three`, `framer-motion`,
`tailwindcss-animate`.

## 7. Skills

`ecc:motion-advanced` for the GSAP/ScrollTrigger cinematic timeline and SVG
route-drawing (same skill named in the F1 prompt for `RouteSpine`'s line-draw —
this is its bigger cousin). `apple-design` and `frontend-design` for the reveal
choreography and the map/imagery treatment — this page is the product's most
visually ambitious surface and the anti-generic discipline matters most here.
`ecc:react-performance` — the results page is the heaviest client bundle in the
app (GSAP + MapLibre); watch bundle size even though F4 owns the formal
performance gate. `superpowers:systematic-debugging` for any GSAP/ScrollTrigger
timing bug — these are notoriously easy to get subtly wrong (trigger points,
scrub timing) and hard to debug by guessing. `superpowers:verification-before-completion`
before reporting F3 done, per §0 above.

## 8. Explicitly out of scope for F3

Performance optimization pass, image/font lazy-loading tuning, Lighthouse
scoring (F4). No live provider calls — MSW only (spec 12 §6: "Frontend
Milestones F2–F3 run entirely on MSW"). No dark mode. No changes to backend
Tier-F pipeline behavior. No second animation runtime beyond the narrow
GSAP/Lenis carve-out in §3.

## 9. What's next

Once Gate F3 passes — verified by pasted real command output — stop and report
back. F4 (performance, one live frontend↔backend integration run against the
sample-data backend) gets its own prompt after F3's actual bundle/component
shape exists to ground it.
