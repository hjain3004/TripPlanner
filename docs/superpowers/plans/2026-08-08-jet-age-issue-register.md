# Jet-age issue register — Bodoni shell, issued documents

**Date:** 2026-08-08
**Status:** PLAN — *geometry* approved 2026-08-08. **Type and ground are NOT settled — see §11 before executing anything.**
**Doubles as the handoff prompt.** Self-sufficient from a cold start; read §0 first.
**Supersedes:** the visual direction in `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md`
§4 (the 6px celadon plate) and `frontend/PROBE_REV2_HANDOFF_PROMPT.md` (defects D1 and D3 are
resolved here by a different route — do **not** execute that handoff, it is now obsolete).

---

## 0. Read these first, in this order

1. `CLAUDE.md` — the agent brief. The five non-negotiables, decision tiers, and ambiguity protocol bind you.
2. `DEVIATIONS.md` — recent judgement calls, including the Tier-F row this plan requires you to add (§6).
3. `frontend/design/CONTRACT.md` — the frozen F1 contract. **This plan changes it.** §3 and §6 are edited by you, in the same commit as the code.
4. `frontend/design/probes/three-directions-1440.html` and its three PNGs — the approved artifact. Direction A's document, Direction C's shell.
5. The token layer you are changing: `frontend/src/themes/base.css` (170 lines), `frontend/src/themes/singapore.css` (34 lines).

Do **not** re-read the 17 specs in `docs/specs/`. Do not reopen the direction question — three directions were rendered and judged on 2026-08-08; the hybrid won.

---

## 1. What was decided, and why

The frontend has been paused since 2026-07-28 with a known problem: **neo-brutalism was specced but never appeared on screen.** The diagnosis is not an implementation bug. Five core neo-brutalist mechanics are each forbidden at the token layer, and `CONTRACT.md` freezes them as Tier-F:

| Neo-brutalism requires | Shipped tokens say |
|---|---|
| `border-radius: 0` | `--radius-m: 12px` |
| Hard offset shadow, no blur | `--shadow-1/2/3` all layered and blurred |
| 2–4px solid borders | `--color-border` is a 10%-opacity hairline; §3 mandates 1px |
| Grotesque/mono display type | Bodoni Moda — a Didone |
| High saturation | Muted palette; lacquer capped at <2% of any screen |

So the direction could never render, no matter how well it was implemented. Rev 1 admitted neo-brutalism only as a scoped `issue`-register offset plate at 6px celadon, and the human's own review concluded it "reads as a soft drop shadow, precisely the treatment the spec claims to be replacing."

**The approved resolution is a two-register system.** Not a compromise — the register split the spec already describes, with a second register strong enough to actually read:

- **Shell register (unchanged).** Landing, marketing, navigation, wizard chrome, illustration. Bodoni Moda, 12px radius, soft layered shadow, 10% hairline. This is the calm environment. It stays exactly as shipped.
- **Issue register (new).** Every *computed artifact*. Space Grotesk, 0 radius, 2px rules, a 12px brass offset plate, mono metadata, and a split-flap treatment for the money moment. This reads as an issued travel document — a boarding pass, a ticket, a receipt.

The governing idea: **brutalist geometry reads as *printed*, not aggressive.** That is the register a tool handling ₹153,000 of someone's money can afford.

Rejected, with reasons recorded so they are not relitigated:
- **Synthwave/CRT retro-futurism** (what the style database returns for the term): executed fairly in the probe and it looks good, but it renders the savings figure as glowing cyan on near-black. Wrong trust register for a money tool. The database itself flags it ⚠ eye-strain and scopes it to gaming/entertainment.
- **Pure jet-age everywhere:** strongest single frame, but retires Bodoni — the most distinctive asset in the system — and strands the orthographic illustration work.

---

## 2. The register boundary — the rule that keeps this coherent

> **A surface enters the issue register if and only if it renders a number the deterministic kernel computed.**

That is the whole rule. Apply it mechanically; do not improvise per-component.

**Issue register** (hard): `verdict-header`, `decision-ledger`, `ledger-row`, `money-text`, `payment-strategy-card`, `transfer-plan-panel`, `itinerary-timeline`, `booking-checklist`, `route-spine`, `route-node`, `provenance-band`, `trust-chip`, `confidence-badge`, `notch-label`, `assumptions-footer`.

**Shell register** (unchanged): `site-header`, `Illustrations.tsx`, `SharedUI.tsx`, landing `page.tsx`, wizard steps in `plan/page.tsx`, `stage-tracker`, `quip-rotator`, all `components/ui/*` primitives, all `kitchen-sink/views/*`.

Ambiguous case, pre-decided so you don't have to: **`stage-tracker` stays shell.** It shows pipeline progress, not a computed money figure. `why-this.tsx` follows its parent — it is a disclosure wrapper, not a surface.

---

## 3. Architecture — how the register is delivered

Use the nested-theming bridge that already exists. `base.css`'s `@theme inline` block resolves `--color-*` from `--th-*` **at the consuming element via normal cascade**, not at `:root` — this is exactly the mechanism the Tier-F spec-bug row in `DEVIATIONS.md` was written to protect, and `src/app/theme-proof/page.tsx` already tests nested override. A `.register-issue` class on a subtree re-themes everything inside it, with zero changes to `singapore.css` and zero risk to the shell.

**But three token families are not currently on that bridge and must be moved.** `--radius-*`, `--shadow-*` and the fonts live in the plain `@theme` block in `base.css`, which resolves at `:root` and therefore **cannot** be overridden per-subtree. Without this change the issue register cannot zero its corners. This is the one structural edit:

```css
/* base.css — plain @theme keeps the PRIMITIVE values */
@theme {
  --radius-s-shell: 6px;
  --radius-m-shell: 12px;
  --radius-l-shell: 20px;
  /* ...existing shadow-1..3 stay here as the shell ramp... */
}

/* base.css — @theme inline gains the register bridge */
@theme inline {
  --radius-s: var(--th-radius-s);
  --radius-m: var(--th-radius-m);
  --radius-l: var(--th-radius-l);
  --shadow-1: var(--th-shadow-1);
  --shadow-2: var(--th-shadow-2);
  --font-display: var(--th-font-display);   /* already present */
}
```

`singapore.css` then declares the shell defaults (`--th-radius-m: 12px`, `--th-shadow-1: <existing ramp>`, `--th-font-display: var(--font-bodoni-moda)`), and the new register file overrides them. **Verify after this edit that `rounded-md` still compiles to 12px on shell surfaces** — if the indirection breaks Turbopack utility generation, that is the same class of bug as the `@utility` failure logged in `DEVIATIONS.md` on 2026-07-28, and the fix is the same: explicit `@layer utilities` rules.

### New file: `frontend/src/themes/registers.css`

```css
/* Issue register — computed artifacts read as issued documents.
   Applied to a subtree; inherits everything it does not override. */
.register-issue {
  --th-font-display: var(--font-poiret-one);

  /* Poiret One is single-weight (400 only). font-weight cannot thicken it and a bold
     request yields faux-bold that smears the hairline deco joins. Weight comes from an
     outward stroke instead: one ratio, floored so small headings do not go weedy.
     Approved on a rendered ladder 2026-08-08 (Framer project "Courteous Jargon"). */
  --th-display-stroke-ratio: 0.047;   /* 3.5px at 74px */
  --th-display-stroke-min:  1.75px;   /* floor — below this the face reads weedy */
  --th-display-stroke-max:  4.5px;    /* ceiling — past this the G/R counters close */

  --th-radius-s: 0px;
  --th-radius-m: 0px;
  --th-radius-l: 0px;

  /* Depth comes from the offset plate, never from blur. */
  --th-shadow-1: none;
  --th-shadow-2: none;

  --th-border:  oklch(0.320 0.042 181);        /* mangrove, FULL opacity — not a hairline */
  --th-text:    oklch(0.220 0.008 145);        /* ink, darkened for print weight */
  --th-accent-4: oklch(0.560 0.150 33);        /* lacquer warmed toward jet orange #C8452F */

  --th-plate:   oklch(0.660 0.097 82);         /* brass — the offset plate */
  --th-board:   oklch(0.205 0.005 145);        /* split-flap cell ground */
  --th-board-text: oklch(0.955 0.006 91);
}
```

Register it in `globals.css`'s import manifest — that file is pinned by token-lint R5 to imports only, so add the line and nothing else.

### Two new primitives

- **`components/product/offset-plate.tsx`** — wraps a document. Renders the `::before` plate at `top:12px; left:12px; right:-12px; bottom:-12px`, `background: var(--color-plate)`, `z-index:-1`. The 12px value is the *tested* one; 6px was the rev-1 failure. Do not reduce it without re-rendering.
- **`components/product/split-flap.tsx`** — renders a number as mechanical cells: one cell per glyph, `--color-board` ground, a 1px hairline across the vertical centre of each cell. **It must accept the already-formatted string and never format or compute** (Tier-F non-negotiable #1: render fields, never compute). Feed it `MoneyText`'s output.

---

## 4. Work order

Each step ends green. Do not batch.

1. **Fonts.** Add Poiret One (400 — the only weight it has) via `next/font/google` in `layout.tsx`, exposing `--font-poiret-one`. Schibsted and Roboto Mono stay. Bodoni stays only until step 5 retires it from the issue register; it remains the shell display face. Add the stroke utility alongside — `paint-order: stroke fill` plus `-webkit-text-stroke`, driven by the three `--th-display-stroke-*` tokens in §3. **Body copy never takes a stroke**: Schibsted Grotesk ships 400–900, so weight is the lever there (500 is the approved step; 600 is the ceiling before it competes with display).
2. **Bridge.** Move radius/shadow/display-font onto the `@theme inline` bridge per §3. Add `--th-*` defaults to `singapore.css`. **Nothing should change visually.** Screenshot the landing page before and after and diff — if anything moved, stop and fix before continuing.
3. **Register file.** Add `registers.css`, import it, apply `.register-issue` to exactly one component (`decision-ledger`) as a spike. Confirm the subtree goes 0-radius and 2px-bordered while the shell is untouched.
4. **Primitives.** Build `OffsetPlate` and `SplitFlap`. Add both to `kitchen-sink`.
5. **Roll out.** Apply the register to the §2 issue list, component by component, screenshotting each.
6. **Contrast + gates.** Rebuild the contrast matrix and re-run all gates (§7).
7. **Docs.** Update `CONTRACT.md` §3 and §6; add the `DEVIATIONS.md` row from §6; update the `CLAUDE.md` checkpoint.

---

## 5. Tier-F guards — what must not move

- **No money math on the frontend.** `SplitFlap` receives a formatted string. It has no `Intl.NumberFormat`, no arithmetic, no rounding. If you find yourself parsing a number inside it, you have broken non-negotiable #1.
- **`font-variant-numeric: tabular-nums` stays mandatory** on every rendered number, including inside split-flap cells.
- **Provenance never styles away.** `TrustChip`, `ProvenanceBand` and `ConfidenceBadge` change register, not visibility. `verify_required` remains lacquer and remains prominent — that is the one place the accent is mandatory.
- **No accent colour as sole carrier of meaning.** Every state keeps its icon or label.
- **Backend untouched.** This plan changes no Python. The backend regression floor is **133 tests** (not the 100 in `CLAUDE.md` — that number is stale; correct it while you are in there).
- **`docs/specs/` is read-only.** `CONTRACT.md` is the file you edit.

---

## 6. Required `DEVIATIONS.md` entry

This is a **Tier-F design change**, human-approved on 2026-08-08 after reviewing a three-direction render. Add:

| date | doc§ | question | decision | rationale | affected_files |
|---|---|---|---|---|---|
| 2026-08-08 | **Tier-F design change · CONTRACT.md §3, §6** | Neo-brutalism was specced but could not render — radius, shadow, border, display face and saturation each forbid it at token level. Resolve how? | **Two-register system.** Shell keeps Bodoni/12px/soft-shadow unchanged. New `.register-issue` (Space Grotesk, 0 radius, 2px mangrove rules, 12px brass offset plate, split-flap money) applies to every surface rendering a kernel-computed number. Radius/shadow/display-font move onto the `@theme inline` bridge to make per-subtree override possible. | Three directions were rendered at 1440px with identical real content (`three-directions-1440.html`) and judged by the human. Synthwave rejected on trust register; pure jet-age rejected for retiring Bodoni. The hybrid keeps the editorial voice and gets a second register strong enough to read — rev 1's 6px celadon plate failed precisely because it was not. | `frontend/src/themes/base.css`, `frontend/src/themes/singapore.css`, `frontend/src/themes/registers.css` (new), `frontend/design/CONTRACT.md`, `frontend/src/app/layout.tsx`, `frontend/src/components/product/*` |

---

## 7. Acceptance criteria

**Gates — all must pass, none narrowed.** `make gate-f1 gate-f2 gate-f3 gate-f4`. If a gate fails, fix the cause; do not scope the gate down. That workaround was already made once and reversed on 2026-07-27.

Specifically:
- `fe-token-lint` at **0 violations.** No raw hex or OKLCH in product code — all new colours are tokens in `registers.css`.
- `fe-no-dead-classes` at **0 dead.** New utilities must actually compile.
- **aXe clean, unfiltered.** No filtered violation categories.
- **Contrast, re-verified and written into the matrix:** paper-on-jet for the `verify_required` stamp, board-text-on-board for split-flap cells, ink-on-paper inside the issue register. Every one ≥ 4.5:1. The warmed lacquer `oklch(0.560 0.150 33)` is a *proposal* — measure it, and if paper-on-jet lands below 4.5:1, darken the jet until it passes and record the final value.
- **Reduced motion:** every `[data-motion]` element computes `opacity >= 0.99`. The split-flap's flip animation must degrade to a static rendered number, never to a blank cell.

**Visual:** screenshot landing + `/plan` results at 390/768/1440 into `frontend/design/refs/f5/` with a `MANIFEST.md`. The judgement to answer in your report: *do the documents read as issued objects inside a calm environment, or as two unrelated design languages?* If the second — say so plainly rather than shipping it.

**Mobile is the real risk.** The split-flap at 390px is untested and may not fit. If it doesn't, degrade it to plain tabular numerals at mobile width rather than shrinking cells below legibility.

---

## 8. Out of scope

No backend changes. No provider/gateway/MCP work. No new dependencies beyond the Space Grotesk font. No changes to `docs/specs/`. Do not execute `frontend/PROBE_REV2_HANDOFF_PROMPT.md` — it is superseded; delete it in this commit and note the deletion in your report.

---

## 9. Known risks

1. **The bridge indirection may break Turbopack utility generation** (§3, step 2). Precedent exists: `@utility` in `themes/` silently failed to compile in production on 2026-07-28. Verify in a production build (`npm run build`), not just dev.
2. **Two registers can read as two unrelated designs.** This is the thesis and it is not guaranteed. The probe tested it at document scale; it has not been tested across a full scrolling results page. This is what step 5's per-component screenshots are for.
3. **Bodoni and Space Grotesk in one viewport** is a real pairing risk — a Didone and a geometric grotesque have little in common. That distance is the intent (registers should be legibly different), but if it reads as accident rather than decision, the fix is to widen the gap further, not to close it.

---

## 10. Skills to invoke

- `superpowers:executing-plans` — before starting; this plan has review checkpoints at steps 2, 3 and 5.
- `superpowers:verification-before-completion` — before claiming any gate passes.
- `ui-ux-pro-max:ui-ux-pro-max` — for contrast and motion rule lookups (`--domain ux`, `--domain color`).
- `frontend-design:frontend-design` — if a composition decision is genuinely underspecified here.
- `superpowers:systematic-debugging` — if the step-2 bridge change moves anything visually.

Do **not** invoke `superpowers:brainstorming`. The geometry is decided and rendered.

---

## 11. CLOSED — type register and ground (opened and resolved 2026-08-08)

**§3 and §4 have been rewritten to match this section. They are now current — read them normally.**
This section is kept as the decision record, not as a blocker.

Four rounds of type probing happened after the geometry was approved. The human rejected, in
order: Bodoni Moda 400, then Bodoni 600 / Instrument Serif / Fraunces 600 / Space Grotesk 700
("dont like any of these fonts"), then fat-face / wood-type / blackletter gazette mastheads.

They then supplied two reference images — `frontend/design/refs/font-decision/Screenshot 2026-08-08
at 1.14.59 PM.png` (a film-credit title) and `...1.18.41 PM.png` (an Art Deco diner sign).

**What the references actually are:** Art Deco / Streamline Moderne titling — tall narrow caps,
hairline strokes, high waist, pointed `A` apex, splayed `M`, circular `O`, wide tracking
(≈0.10em). Not the 1980s synthwave strain of retro-futurism that the style database returns, and
not the editorial-serif family this plan originally assumed. The references happen to be
light-on-dark, but that is incidental — see the ground decision below.

### What was decided

1. **Display face is Poiret One**, replacing Space Grotesk in §3 and Bodoni Moda within the issue
   register. Chosen from `deco-1440.html` as closest to the signage reference. Josefin Sans,
   Julius Sans One and Limelight were rejected.
2. **Ground stays light.** Dark-first was raised here and explicitly overruled: *"no i dont want
   light on dark... dont change the color scheme."* The singapore palette — limestone, paper,
   mangrove, celadon, brass, lacquer — is unchanged, and so are the contrast matrix, the aXe
   baselines and every gate screenshot. §4's work order does **not** need rewriting for ground.
3. **Poiret One is single-weight, so it needs both a companion face and a stroke.** Schibsted
   Grotesk keeps h3-and-below, all body, and every monetary value; Roboto Mono keeps metadata.
   Display weight comes from the `--th-display-stroke-*` tokens in §3, not from `font-weight`.
   Ratio 0.047em, floor 1.75px, ceiling 4.5px — approved on a rendered ladder at 74px and a
   counter-closure check at 96px. Below the floor the face reads weedy; above the ceiling the
   `G` aperture and `R` bowl fill in and it stops reading as Streamline Moderne.
4. **The 40px display floor still holds** and is now enforced by the stroke floor rather than by
   convention alone.

### What is still settled

The geometry from Direction A is unchanged and was approved on a rendered comparison: 0 radius,
2px rules, 12px offset plate, mono metadata, split-flap for the money moment, and the §2 register
boundary rule. §5's Tier-F guards are unaffected by any type or ground decision.

### Next action

**§4 is unblocked. Start at step 1.** Geometry, register boundary, type and ground are all
settled; §3 and §4 above already carry the resolved values. The §6 `DEVIATIONS.md` row must be
widened to cover the display-face swap and the stroke tokens — it currently covers geometry and
register only, and the face swap moves a Tier-F row in `CONTRACT.md` §1 (display = Bodoni Moda).
No separate ground decision is needed; light was retained.

**Probe inventory** (all standalone, none shipped, all in `frontend/design/probes/`):
`three-directions-1440.html` (geometry — Direction A won, B rejected outright),
`display-font-1440.html` (serifs — all rejected), `gazette-1440.html` (mastheads — all rejected),
`deco-1440.html` (deco faces on dark ground — **awaiting judgement**).
