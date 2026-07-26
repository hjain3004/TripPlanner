# Frontend Design and Development Handover

**Prepared:** 2026-07-26  
**Audience:** Claude or another implementation agent taking over the TripPlanner frontend  
**Immediate milestone:** F1 — tokens, themed primitives, fonts/assets pipeline, and the kitchen-sink gate  
**Implementation status:** **No frontend code has been written.** This document captures the completed research and design decisions that must precede implementation.

> **Successor document:** `frontend/F1_IMPLEMENTATION_PLAN.md` (2026-07-26) turns this handover into an executable plan. It resolves the §4 documentation conflict, settles the open questions in §3.4 and §14, and adds findings this document could not know — a Tailwind v4 spec bug in `11 §1`, WCAG failures in the frozen palette, and the Boska licensing risk. **Read this handover first for context, then that plan for what to actually do.**

---

## 1. Read this first

The frontend is the product's most important presentation layer. The user does not want a generic AI dashboard, a dense points-and-miles tool, or a booking-site clone. The intended experience is:

> A calm, light, sophisticated trip planner for an ordinary traveler, with expert-grade reward and payment analysis hidden underneath and revealed only when useful.

The deterministic backend performs all money and points calculations. The frontend renders computed artifacts and provenance; it never derives monetary values itself.

Before changing anything:

1. Read `../CLAUDE.md`, `../DEVIATIONS.md`, and the newest report in `../reports/`.
2. Read `../docs/specs/06_implementation_protocol.md`.
3. Read `../docs/specs/10_frontend_build_plan.md` and `../docs/specs/11_design_system_and_theming.md`.
4. Read this handover completely.
5. Do **not** start implementation until the documentation conflict in §4 is resolved.

The current Git branch is `feat/m3-evals-provenance`. Do not put F1 implementation on that branch. First ensure M3 is merged into `main`, preserve all unrelated/untracked user work, then create a dedicated frontend branch such as `feat/f1-frontend-foundation`.

Known untracked items at handover time:

- `.superpowers/` — temporary visual-brainstorm artifacts described below.
- `.playwright-mcp/` — browser-tool output; do not commit.
- `docs/research/17_orchestration_substrate_adk.md` — unrelated user/agent work; preserve it.

---

## 2. Product hierarchy — settled

These decisions were explicitly discussed with and approved by the user.

### 2.1 Audience

- The default user is a **normal traveler**, not a points-and-miles expert.
- The product may offer power-user controls later, but they are an optional layer.
- Do not expose airline-program jargon, transfer arithmetic, fare-source terminology, or card optimization machinery in the first visual layer.

### 2.2 Information model

Think of the product as an iceberg:

- **Visible layer:** trip, recommendation, trade-offs, savings, confidence, next steps.
- **Expandable layer:** exact math, assumptions, sources, verification status, transfer details.
- **Backend layer:** deterministic optimization, provider normalization, agent workflows, provenance propagation.

### 2.3 Recommendation explanation

Every recommendation should have an inline expandable **“Why this?”** control.

The collapsed state gives a plain-language reason. The expanded state may show:

- computed cash and point costs;
- the selected payment/card strategy;
- assumptions and trade-offs;
- transfer path and warning state;
- provenance and last verification;
- what the traveler must verify before transferring or booking.

Never make the user leave the result to understand it. Never lead with the full audit trail.

### 2.4 Motion personality

The approved motion direction is **Guided Reveal**:

- ordinary interaction is quiet and fast;
- the plan may have one orchestrated route-drawing moment;
- recommendations may reveal in a controlled sequence;
- the interface settles and becomes still afterward;
- reduced-motion users receive all content immediately without decorative movement.

Motion is explanatory, not ornamental.

---

## 3. Visual direction — settled at the conceptual level

The chosen working direction is an **Atlas Editorial × Peranakan Modernist hybrid**.

### 3.1 What that means

Borrow the following qualities:

- Atlas/editorial calm: generous space, strong hierarchy, intentional rules and margins.
- Peranakan/architectural identity: geometry, façade rhythm, celadon/lacquer/brass references, and restrained Singapore character.
- Travel wayfinding: airport codes, route lines, stops, dates, and journey progression as information architecture.
- Product rigor: aligned numeric columns, visible verification, and precise microcopy.

Do not copy a magazine literally. This remains a usable travel product.

### 3.2 Geometry

The preferred geometry is sharper and more architectural than the rejected early mockups:

- rectangular panels and split grids;
- hairline rules;
- low-to-medium corner radii, used intentionally;
- asymmetrical editorial composition;
- route lines connecting steps or sections;
- one visually dominant recommendation rather than three equal promotional cards.

Rounded pills are reserved for genuine statuses or compact controls. They are not the default container.

### 3.3 Provisional color direction

The initial spec's sorbet-pastel treatment was rejected when translated literally. The later hybrid direction was received positively, with criticism focused on typography rather than its palette or geometry.

Use this only as the next refinement starting point, not as a frozen token set:

| Role | Provisional value | Intent |
|---|---:|---|
| Limestone background | `#F1EDE4` | warm, quiet canvas |
| Paper surface | `#FAF8F2` | readable working surface |
| Mangrove primary | `#173A34` | deep green identity and actions |
| Ink | `#272A27` | warm near-black |
| Muted text | `#68716B` | secondary explanation |
| Celadon | `#BDD3C9` / `#DBE7E0` | architectural Singapore reference |
| Lacquer red | `#AE493B` | selective emphasis |
| Brass | `#B08C48` | savings/verified value moments |

Requirements before freezing:

- express final colors in OKLCH;
- test every text/surface pair programmatically;
- body text must meet WCAG AA 4.5:1;
- large text must meet 3:1;
- color must never be the only carrier of meaning;
- compare at 390, 768, and 1440 px;
- avoid pastel radial blobs or candy-like gradients.

### 3.4 Typography — partially settled, one choice remains

The user explicitly approved **Schibsted Grotesk** as a readable interface direction (“B is good”).

Use Schibsted Grotesk for:

- navigation;
- form controls;
- body copy;
- explanations;
- result labels;
- monetary and point values;
- buttons;
- dense functional content.

Use a mono face only for small airport codes, timestamps, trace/provenance labels, and similar metadata. It must never dominate the product.

The display/brand choice is narrowed to two user-approved candidates:

1. **Bodoni Moda** — high-contrast, refined, international-wayfinding/editorial character.
2. **Boska** — organic, high-character, travel-journal energy.

The user said options 3 and 4 were good but did not choose a final winner. Do not guess silently.

Recommended next action:

- render **one polished screen twice**, identical except for Bodoni Moda vs. Boska;
- show hero, functional section heading, result heading, mobile heading, numerals, punctuation, and airport codes;
- keep sizes realistic; do not judge only at 90 px;
- ask the user for one final choice;
- prefer a single display family rather than using both unless the user explicitly approves a disciplined two-display-family system.

Practical considerations:

- Bodoni Moda is available through Google Fonts and should integrate cleanly through `next/font`.
- Boska was previewed through Fontshare. Verify its exact license and delivery requirements before committing binaries to a public repository. Fontshare states its fonts are free for personal and commercial use, but individual open/closed-source distribution terms differ. Do not commit a proprietary font file unless its license explicitly allows repository redistribution. See [Fontshare's overview](https://www.fontshare.com/about) and [license descriptions](https://fontshare.com/licenses/sil-ofl).

### 3.5 Typography explicitly rejected

Do not spend another round re-proposing these without a new human request:

- Bricolage Grotesque in an aggressively condensed treatment — judged barely legible.
- Newsreader + Manrope — judged boring/default.
- Fraunces + Instrument Sans — judged weird in the comparison.
- Georgia, Literata, DM Serif Display, and Petrona — judged effectively indistinguishable/default in this context.
- Any “large safe serif + neutral sans + rounded form card” composition.

The problem was not merely font selection. Oversized headings, over-tight tracking, and using display faces in dense functional headings also harmed legibility. The final type scale must constrain display typography to appropriate contexts.

---

## 4. Important documentation conflict — resolve before code

Current specs 10 and 11 freeze:

- Fraunces + Instrument Sans;
- the original Singapore sorbet palette;
- semantic token mechanics and frontend stack.

The user has now explicitly rejected the rendered font and color direction. Therefore:

- the **token architecture remains valid**;
- the **semantic token names remain valid**;
- the **light-theme-only decision remains valid**;
- the exact font families and Singapore color values require a human-approved documentation revision before F1 implementation.

Do not quietly implement Bodoni/Boska/Schibsted while leaving authoritative specs contradictory.

Required resolution sequence:

1. Finalize Bodoni Moda vs. Boska with the user.
2. Refine and contrast-test the hybrid palette.
3. Update `docs/specs/10_frontend_build_plan.md` and `docs/specs/11_design_system_and_theming.md` while still in the design/documentation phase.
4. Update `CLAUDE.md` and `AGENTS.md` identically if their frontend summary changes.
5. Add a clear Tier-F design-change row to `DEVIATIONS.md`.
6. Only then begin F1 implementation.

Do not change any backend Tier-F behavior or golden numbers as part of this work.

---

## 5. Visual artifacts produced during brainstorming

The following local HTML artifacts are under:

```text
.superpowers/brainstorm/87988-1785011410/content/
```

They are currently untracked and are not authoritative by themselves.

### Keep as useful references

| File | Use |
|---|---|
| `visual-direction-v2.html` | Earlier Calm Route direction that established light, calm, spacious intent. |
| `motion-personality.html` | Comparison that led to Guided Reveal approval. |
| `library-theme-research.html` | Library and travel-product research board. Its appearance is documentation-like and **not** a product visual reference. |
| `visual-reset-three-directions.html` | Contains Atlas Editorial, Peranakan Modernist, and International Wayfinding. User approved the A+B hybrid direction. |
| `calm-route-hybrid-polish.html` | Useful for grid, route structure, palette, recommendation-list geometry, and provenance placement. **Ignore its Bricolage typography.** |
| `display-font-real-reset.html` | Current typography decision artifact. Options 3 (Bodoni Moda) and 4 (Boska) were approved as good. |

### Rejected or superseded

| File | Reason |
|---|---|
| `calm-route-foundation.html` | Generic AI/SaaS composition, disliked palette, fallback-like typography. |
| `typography-reset.html` | Options A and C rejected; B survives only as Schibsted UI direction. |
| `heading-font-round-two.html` | Entire round rejected as too default/Calibri-like. |
| `visual-direction.html` | Early exploration; superseded by later Calm Route work. |

### Preserve the useful references properly

Before deleting or ignoring `.superpowers/`:

1. Capture the approved HTML references at 390, 768, and 1440 px.
2. Save durable screenshots under `frontend/design/refs/`.
3. Add a short manifest stating what each screenshot approves and what it does not approve.
4. Add `.superpowers/` and `.playwright-mcp/` to `.gitignore` after the references are preserved.

Do not commit the entire brainstorm runtime.

---

## 6. Travel-product research synthesis

The intended product should combine lessons, not clone interfaces.

### Google Flights

Take:

- dominant query clarity;
- “best” versus merely “cheapest”;
- flexible-date and trade-off visibility;
- calm comparison hierarchy.

Reference: [Google Flights' calendar, date-grid, and price-graph patterns](https://blog.google/products-and-platforms/products/travel/how-to-find-the-best-deal-on-your-next-flight/).

### Wanderlog

Take:

- itinerary and map as two views of the same journey;
- route sequence as the organizing structure;
- trip-level cohesion.

Reference: [Wanderlog](https://wanderlog.com/).

### point.me

Take:

- plain-language guidance for non-experts;
- cash/portal/transfer comparisons;
- explicit transfer next steps.

Do not reproduce a reward-program search interface as the homepage.

Reference: [point.me](https://www.point.me/?os=app).

### Seats.aero

Take later:

- advanced award filters;
- broad/flexible airport search;
- power-user availability views.

Do not use its dense expert layout as the default traveler experience.

Reference: [Seats.aero search documentation](https://docs.seats.aero/article/37-how-to-search-with-the-explore-vs-search-tool).

### AwardWallet

Take:

- clear organization of cards, balances, benefits, and expiry;
- itinerary and rewards in one place.

Avoid turning the product into a finance dashboard.

Reference: [AwardWallet](https://awardwallet.com/).

The final visual formula is:

> Google Flights' decision clarity + Wanderlog's spatial itinerary + point.me's guided rewards logic + restrained Singapore architectural character.

---

## 7. Component and library research

Research broadly; install narrowly.

### 7.1 Foundation

Use [shadcn/ui](https://ui.shadcn.com/docs/components) as the owned, accessible component foundation.

Likely components by milestone:

#### F1

- Button
- Card or Item where a true surface is needed
- Badge/status
- Tooltip
- Tabs
- Accordion/Collapsible
- Sheet/Dialog/Drawer as appropriate
- Skeleton
- Progress
- Sonner/toast
- Separator

#### F2

- Field
- Input
- Select/Combobox/Command
- Date Picker/Calendar
- Radio Group
- Checkbox/Switch where semantically correct
- Step progress
- Drawer/Sheet for mobile refinement

#### F3

- product-specific recommendation row/panel;
- route timeline;
- expandable “Why this?”;
- provenance block;
- verification warning;
- comparison drawer;
- itinerary/map composition.

Do not install every component during F1 merely because it may be useful later.

### 7.2 Motion

Use Motion for React as the normal animation system:

- staged entrance;
- layout transitions;
- disclosure;
- SVG path drawing where appropriate;
- reduced-motion behavior.

GSAP/ScrollTrigger remains limited to the later results-page cinematic sequence specified in docs. Do not introduce a second general-purpose animation runtime during F1.

### 7.3 Particularly relevant discoveries

- [mapcn](https://www.mapcn.dev/) — MapLibre-based, Tailwind-styled map components.
- [flightcn](https://flightcn.yencheng.dev/) — airport markers, great-circle routes, multi-leg journeys, and IATA-aware route overlays.

These are strong F3/F4 candidates. Do not install them during F1.

### 7.4 Selective inspiration/adoption

- [Magic UI](https://magicui.design/docs/components): consider Blur Fade, Progressive Blur, Number Ticker, Dotted Map, or Scroll Progress only when a real use case exists.
- [Animate UI](https://animate-ui.com/docs): useful accessible animated-primitive reference.
- Motion Primitives: useful copy-owned reference for small interactions.
- [Aceternity UI](https://ui.aceternity.com/components): Timeline, Tracing Beam, Expandable Cards, and stateful controls may inspire local product components.

Every registry component must be:

1. queried through the official shadcn workflow rather than invented from memory;
2. reviewed line by line;
3. rewired to semantic tokens immediately;
4. checked for keyboard and reduced-motion behavior;
5. checked for unnecessary dependencies;
6. removed if it undermines F4 performance budgets.

The official shadcn registry directory is available at [registries.json](https://ui.shadcn.com/r/registries.json).

### 7.5 Deliberately avoid

- marquees;
- particles, meteors, auroras, and animated gradient noise;
- rainbow/shimmer buttons;
- 3D/glare/tilt cards;
- cursor effects;
- parallax walls;
- generic bento-grid heroes;
- animated globes when a useful map is needed;
- destination-card walls;
- booking-site urgency and scarcity theater;
- decorative motion that repeats on every interaction.

Good components can still be wrong for this product.

---

## 8. Model-proof frontend foundation

The user intends to use cheaper models for much of the implementation. The foundation must remove taste decisions from their work.

Claude should produce the following before delegating repetitive implementation:

### 8.1 Frozen design contract

- final font families and delivery mechanism;
- complete semantic token table;
- complete type scale with line height, tracking, and allowed contexts;
- spacing scale;
- radius rules;
- shadow/elevation rules;
- border rules;
- breakpoint behavior;
- motion tokens;
- reduced-motion substitutions.

### 8.2 Component contracts

For every F1 primitive, document:

- purpose;
- allowed variants;
- anatomy;
- default, hover, focus, active, disabled, loading, error, and selected states as applicable;
- keyboard behavior;
- mobile behavior;
- token usage;
- forbidden styling;
- one approved screenshot.

### 8.3 Anti-generic guardrail

Add a short checklist that every frontend PR must pass:

- Does it resemble a generic AI/SaaS dashboard?
- Are cards being used because they are necessary, or because they are easy?
- Are there too many pills?
- Is one decision visually dominant?
- Is advanced complexity progressively disclosed?
- Are route/wayfinding patterns communicating structure rather than decorating?
- Is the display font confined to readable contexts?
- Are money and points rendered from fixture/backend fields without calculation?
- Is provenance visible and understandable?
- Does the page remain calm after animation completes?

### 8.4 Ticket format for cheaper models

Each implementation ticket should contain:

- exact files allowed to change;
- visual reference;
- component contract;
- required tokens;
- explicit non-goals;
- acceptance test;
- screenshot sizes;
- console/type-check expectations.

Do not ask a cheaper model to “make it premium” or “choose tasteful colors.” Those decisions belong in the frozen contract.

---

## 9. Tooling and skills for Claude

Verify connections at session start rather than assuming they survived a restart.

Expected developer MCP/tooling:

- shadcn;
- Figma;
- Playwright;
- Chrome DevTools;
- Next.js DevTools;
- Context7.

Do **not** connect Gondola or another travel-provider MCP during F1. Provider work remains after F4/G1.

Recommended skill sequence:

### Design completion

- `frontend-design`
- ECC `frontend-design-direction`
- ECC `design-system`
- ECC `taste`
- ECC `make-interfaces-feel-better`
- ECC `frontend-a11y`
- ECC `motion-foundations`
- Matt Pocock `to-spec` or equivalent specification skill

### Planning

- Superpowers `writing-plans`
- Matt Pocock `wayfinder` for repo navigation if needed
- ECC `frontend-patterns`
- ECC `react-patterns`
- ECC `react-performance`

### Implementation and verification

- Superpowers `test-driven-development`
- Matt Pocock `implement`
- ECC `e2e-testing`
- ECC `verification-loop`
- ECC `delivery-gate`
- Superpowers `verification-before-completion`
- Superpowers `requesting-code-review`

Do not invoke every skill simultaneously. Use the relevant skill at the phase where it constrains a concrete decision.

Required tool order during UI implementation follows spec 10:

1. frontend design guidance;
2. shadcn MCP for components;
3. Figma only when there is a source frame or approved library asset;
4. Playwright for visual and interaction verification;
5. Next.js DevTools after client/server or animation changes;
6. Chrome DevTools at F4 and after animation-heavy changes;
7. Context7 for current library APIs.

---

## 10. F1 implementation sequence

Do not skip gates or combine provider work with F1.

### Phase 0 — finish and document design

1. Compare Bodoni Moda and Boska in the same polished screen.
2. Obtain final user approval.
3. Refine and contrast-test the hybrid palette.
4. Update specs 10 and 11 plus agent briefs.
5. Preserve visual references under `frontend/design/refs/`.
6. Write a detailed F1 implementation plan.

### Phase 1 — safe project initialization

1. Ensure M3 is merged and branch from updated `main`.
2. Confirm `frontend/` contains no implementation that must be preserved.
3. Initialize the frozen Next.js App Router + strict TypeScript stack.
4. Use Tailwind CSS v4 CSS-first configuration.
5. Configure shadcn only after the project exists and `components.json` can be inspected.
6. Do not introduce `tailwind.config.js` token definitions.
7. Do not add localStorage/sessionStorage.

### Phase 2 — token architecture

Implement:

```text
frontend/src/themes/base.css
frontend/src/themes/singapore.css
frontend/src/themes/_template.css
```

Preserve the three-layer architecture from spec 11:

- shared primitives and component tokens;
- destination-specific primitive-to-semantic mapping;
- components consuming semantic tokens only.

Add programmatic contrast tests before styling a large component set.

### Phase 3 — typography and asset pipeline

- use the approved fonts through a license-safe mechanism;
- define display, UI, numeric, and metadata roles;
- use tabular numerals for money/points;
- self-host approved destination images;
- record source and license in the asset manifest;
- avoid recognizable faces and brand logos;
- use Lucide icons only unless the spec is deliberately revised.

### Phase 4 — primitives

Acquire components through shadcn, then rewire them to semantic tokens.

Create product-level wrappers/compositions only when they express a stable product concept, such as:

- provenance badge;
- verification warning;
- savings highlight;
- route step;
- “Why this?” disclosure.

Do not structurally modify shadcn primitives unless the component contract requires it. Prefer composition.

### Phase 5 — product-flavored kitchen sink

The kitchen sink must prove the design system without pretending to be the finished product.

It should include:

- type scale;
- palette and contrast pairs;
- surfaces and elevation;
- button and field states;
- badges and provenance;
- route/wayfinding sample;
- numeric alignment;
- disclosure behavior;
- loading and error states;
- modal/sheet/dialog behavior;
- reduced-motion preview.

It must not become a generic wall of component cards.

### Phase 6 — Gate F1

Required evidence:

- Playwright screenshots at 390, 768, and 1440 px;
- axe contrast/accessibility checks;
- zero console errors;
- strict TypeScript clean;
- hairline borders, shadow ramp, and type scale visibly present;
- focus states visible;
- keyboard navigation usable;
- reduced-motion behavior verified;
- no unapproved dependencies or hardcoded palette values;
- `reports/frontend_F1.md` written with the exact commands and results.

Do not call F1 complete because the page renders.

---

## 11. F2–F4 roadmap

This is orientation only. Do not pull later work into F1.

### F2 — contract and intake

- generate the API client from `contract/openapi.json`;
- add Zod boundary validation;
- use MSW v2 fixtures;
- implement the five-step wizard;
- support clarification loops;
- preserve focus and ARIA announcements;
- no real provider calls.

### F3 — loading and results

- staged loading bound to actual polling states;
- Guided Reveal motion;
- result hierarchy and recommendation list;
- “Why this?” detail;
- transfer checklist;
- provenance and verification;
- MapLibre/OpenFreeMap trip map;
- mapcn/flightcn evaluation;
- every displayed number traceable to fixture JSON.

### F4 — performance and integration

- lazy-load GSAP and MapLibre;
- optimize fonts and images;
- performance trace on landing and results;
- LCP ≤ 2.5 s;
- CLS ≤ 0.1;
- INP ≤ 200 ms;
- Lighthouse accessibility ≥ 95;
- one real frontend-to-Kernel-MVP run using sample data.

F4 “live” means real frontend/backend transport, not live commercial travel inventory.

---

## 12. Non-negotiable frontend rules

1. The frontend never computes money, rewards, discounts, fees, point values, or transfer arithmetic.
2. Every numeric statement comes from a backend or fixture artifact.
3. Provenance is never styled away.
4. “Verify before transfer” remains the first transfer step.
5. No localStorage or sessionStorage.
6. No secrets.
7. No direct travel-provider calls from components.
8. No runtime crawling.
9. No dark mode during the MVP.
10. No provider/MCP implementation during F1.
11. No registry component is committed without line-by-line review and semantic-token rewiring.
12. No autonomous booking or point transfer.

---

## 13. What was not done

At handover time:

- no `package.json` exists under `frontend/`;
- no Next.js project is initialized;
- no component has been installed;
- no design tokens have been committed;
- no Figma source file has been created;
- no contract client has been generated;
- no MSW fixtures exist;
- no frontend tests exist;
- no provider gateway or runtime adapter exists;
- no travel-provider MCP has been activated;
- authoritative specs have not yet been revised for the newly rejected fonts/palette.

Do not claim otherwise in status reports.

---

## 14. Claude's recommended first response/work session

Claude should:

1. Confirm it read this handover and the mandatory session-start documents.
2. Inspect the two current typography candidates in `display-font-real-reset.html`.
3. Produce one polished Bodoni-vs.-Boska comparison using the approved hybrid geometry and Schibsted UI layer.
4. Ask the user for the final typography choice.
5. Refine the palette and run contrast checks.
6. Update the authoritative documentation before implementation.
7. Invoke the planning skill and write the F1 implementation plan.
8. Only after plan approval, initialize and implement F1 on a clean frontend branch.

The expensive model's job is to freeze taste, contracts, and gates. Cheaper models should receive bounded implementation tickets and objective visual/test evidence.

