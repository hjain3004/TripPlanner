# Handoff — execute the Jet Age issue register (frontend)

**Written:** 2026-08-08 · **Repo:** `/Users/himanshu_jain/TripPlanner` · **Branch:** `main`
**For:** the agent implementing `docs/superpowers/plans/2026-08-08-jet-age-issue-register.md` §4
**Status of that plan:** unblocked. §11 is closed, §3 and §4 carry resolved values. Start at step 1.

---

## 0. Read these, in this order, before touching anything

1. `CLAUDE.md` — the agent brief. Five non-negotiables, decision tiers (F/C/V), ambiguity protocol.
   **Note its "Current checkpoint" section is stale in three places; see §7 below.**
2. `docs/superpowers/plans/2026-08-08-jet-age-issue-register.md` — **the plan you are executing.**
   Read it whole. §3 (architecture), §4 (work order), §5 (Tier-F guards), §6 (DEVIATIONS row),
   §7 (acceptance), §11 (decision record).
3. `frontend/design/CONTRACT.md` §1–3 — the frozen contract this work amends.
4. `DEVIATIONS.md` — how judgment calls get logged here. You will add to it.

**Do not** re-read the 17 specs in `docs/specs/`. **Do not** re-derive the visual direction — five
rounds of probing already happened across two sessions and every rejection is on record in §11 and
in §2 of this document.

---

## 1. What you are actually doing, in one paragraph

The frontend is **already built**. Routes `/`, `/plan` (687 lines), `/kitchen-sink`, `/theme-proof`
exist; there are 17 shadcn primitives in `frontend/src/components/ui/` and 26 product components in
`frontend/src/components/product/`. F1–F4 landed and gated. **You are not building pages.** You are
introducing a second visual register — a hard, "issued document" treatment — and applying it to the
subset of existing components that render numbers the deterministic kernel computed. Everything else
keeps the calm editorial shell it already has. This is a token-layer change plus a re-skin, executed
in seven steps that each end green.

---

## 2. Settled — do not reopen, do not re-probe

**Geometry (Direction A), approved on a rendered 1440px comparison:**
0 radius · 2px rules · 12px offset plate (6px was the rev-1 failure — do not reduce) ·
mono metadata · split-flap for the money moment.

**The register boundary rule** — this is what keeps the system coherent:
> A surface enters the issue register **if and only if** it renders a number the deterministic
> kernel computed.

Component lists are in plan §2. Do not extend the register by taste.

**Type — settled 2026-08-08 on a rendered ladder:**

| Role | Face | Constraint |
|---|---|---|
| Display — hero, h1, h2 | **Poiret One** (400 — its only weight) | Caps, tracked ≈0.09–0.10em, **never below 40px**. Weight comes from stroke, never `font-weight`. |
| UI — h3 down, body, all money | **Schibsted Grotesk** (unchanged) | Body at **500**; 600 is the ceiling before it competes with display. `tabular-nums` mandatory on every number. |
| Mono — data, codes, provenance | **Roboto Mono** (unchanged) | Datelines, airport codes, provenance labels, split-flap cells. |

**Display stroke tokens** (in plan §3, `.register-issue`):
`--th-display-stroke-ratio: 0.047` · `--th-display-stroke-min: 1.75px` · `--th-display-stroke-max: 4.5px`
Below the floor the face reads weedy. Above the ceiling the `G` aperture and `R` bowl fill in and it
stops reading as Streamline Moderne. Both bounds were verified on a rendered counter-closure check
at 96px.

**Ground stays light.** Dark-first was raised and explicitly overruled by the human:
*"no i dont want light on dark... dont change the color scheme."* The singapore palette is unchanged —
limestone `#F1EDE4`, paper `#FAF8F2`, ink `#272A27`, mangrove `#173A34`, celadon `#BDD3C9`,
brass `#B08C48`, lacquer `#AE493B` (capped <2% of surface). The contrast matrix, aXe baselines and
gate screenshots are all built for light and remain valid.

**Rejected outright — never resurface:**
- **Synthwave / neon / CRT retro-futurism.** Human's words: *"absolutely terrible and i don't want
  anything even remotely resembling this."*
- **Faces:** Bodoni Moda 400 and 600, Instrument Serif, Fraunces 600, Space Grotesk 700,
  Abril Fatface, Alfa Slab One, Pirata One, Monoton, Josefin Sans, Julius Sans One, Limelight.

---

## 3. The stroke mechanic — the one non-obvious implementation detail

Poiret One ships **one weight**. `font-weight: 700` produces browser faux-bold, which smears the
hairline deco joins. Weight must come from an outward stroke painted *behind* the fill:

```css
.display-stroked {
  font-family: var(--font-poiret-one);
  font-weight: 400;                    /* never raise this */
  paint-order: stroke fill;            /* stroke behind fill → grows outward, counters stay open */
  -webkit-text-stroke-color: currentColor;
  -webkit-text-stroke-width: max(
    var(--th-display-stroke-min),
    calc(1em * var(--th-display-stroke-ratio))
  );
}
```

**Verify before shipping:** `-webkit-text-stroke` is prefixed but supported in every current engine.
`paint-order` on HTML text is the newer half of the pair. If `paint-order` is ignored the stroke
centres on the outline and eats the counters — glyphs get muddier, not broken. **Check Safari and
Firefox at gate time.** Chromium and Framer's renderer both handle it correctly; those are confirmed.

**Body copy never takes a stroke.** Schibsted Grotesk has real weights 400–900 with a variable axis.
A 1.75px stroke on 13px text is roughly a quarter of the glyph height and closes every aperture into
a blob. Use `font-weight: 500`.

---

## 4. The work order

From plan §4. **Each step ends green. Do not batch. Do not skip the checkpoints.**

1. **Fonts.** Add Poiret One (400) via `next/font/google` in `frontend/src/app/layout.tsx`, exposing
   `--font-poiret-one`. Add the `.display-stroked` utility from §3 above. Schibsted and Roboto Mono
   stay. Bodoni stays as the *shell* display face until step 5 retires it from the issue register.
2. **Bridge.** Move radius / shadow / display-font onto the `@theme inline` bridge per plan §3. Add
   `--th-*` defaults to `singapore.css`.
   **⚠ CHECKPOINT — this is the dangerous step. Nothing should change visually.** Screenshot the
   landing page and `/plan` before and after, and diff. If anything moved, **stop and fix before
   continuing** — there is precedent in this repo for Turbopack silently failing to generate
   utilities, and that failure looks like a design problem when it is a build problem.
3. **Register file.** Add `frontend/src/themes/registers.css`. Import it in `globals.css` — that file
   is pinned by token-lint R5 to imports only, so **add the one line and nothing else.** Apply
   `.register-issue` to exactly **one** component (`decision-ledger`) as a spike.
   **⚠ CHECKPOINT:** confirm the subtree goes 0-radius and 2px-bordered while the shell is untouched.
4. **Primitives.** Build `components/product/offset-plate.tsx` and `components/product/split-flap.tsx`
   per plan §3. Add both to `/kitchen-sink`.
5. **Roll out.** Apply the register to the plan §2 issue list, component by component, screenshotting
   each. **This is where Bodoni leaves the issue register.**
6. **Contrast + gates.** Rebuild the contrast matrix, re-run all gates (plan §7).
7. **Docs.** Update `CONTRACT.md` §3 and §6; add the `DEVIATIONS.md` rows from §5 below; update the
   `CLAUDE.md` checkpoint including the corrections in §7 of this document.

---

## 5. Tier-F — what must not move, and what you must log

**Guards (plan §5) — violating any of these is a defect, not a judgment call:**
- **No money math on the frontend.** `SplitFlap` receives an already-formatted string. No
  `Intl.NumberFormat`, no arithmetic, no rounding, no parsing. Feed it `MoneyText`'s output. This is
  non-negotiable #1 in `CLAUDE.md`: render fields, never compute.
- **`font-variant-numeric: tabular-nums` stays mandatory** on every rendered number, including inside
  split-flap cells.
- **Provenance never styles away.** `TrustChip`, `ProvenanceBand`, `ConfidenceBadge` change register,
  not visibility. `verify_required` stays lacquer and stays prominent.
- **No accent colour as the sole carrier of meaning.** Every state keeps its icon or label.
- **Lacquer stays under 2% of any screen's surface.** Never a section fill, never a large text run.

**Required `DEVIATIONS.md` rows — write these BEFORE the change lands, not after:**
1. The geometry/register row already drafted in plan §6.
2. **A new row for the display-face swap.** `CONTRACT.md` line 23 freezes **Bodoni Moda** as the
   display face — replacing it inside the issue register moves a **Tier-F** value. The plan §6 row as
   written covers geometry and register only and does **not** cover this. Widen it or add a second row.
3. **A row for the stroke tokens**, since `--th-display-stroke-*` introduces a new mechanic to the
   token layer that `CONTRACT.md` §2 does not currently describe.

Format: `date, doc§, question, decision, rationale, files`.

---

## 6. Acceptance — you are done when

Plan §7 is authoritative. At minimum:
- All gates in `frontend/` pass (`make` targets; see the Makefile for the gate list).
- TypeScript compiles clean — `npx tsc --noEmit` exits 0. It did before you started; keep it that way.
- Backend regression stays at **133 tests passing**, `mypy --strict` clean on 42 production files.
  You should not be touching backend at all — if that number moves, you broke something out of scope.
- Contrast matrix rebuilt and passing; aXe baselines green on the light ground.
- Screenshots of `/`, `/plan` and `/kitchen-sink` at 1440px, attached to the report.
- `reports/` gets a written record, consistent with how M1–M3 were reported.

---

## 7. Corrections to inherited docs — do not trust these blindly

`CLAUDE.md`'s "Current checkpoint" block is stale in three places, all verified 2026-08-08:
- It says the backend regression floor is **97 / 100 tests**. **It is 133.**
- It says *"There is no provider gateway."* **Stale** — `backend/gateway/evidence/` exists with 8
  tested modules.
- It describes the display font as **Bodoni Moda** and the frontend as paused at F1 Phase 0. Both are
  out of date: F1–F4 landed, and the display face for the issue register is now Poiret One.

Fix these in step 7. Do not silently work around them.

---

## 8. Out of scope — do not do these in the same change

- Anything in `backend/`. No provider gateway, no crawling, no provider APIs, no MCP/provider work.
- The **script eyebrow slot** is still unresolved (three candidates were rendered last session:
  Parisienne, Petit Formal Script, Yellowtail; none chosen). Dropping the script entirely and using
  Roboto Mono for eyebrows is the lower-risk option and needs a human decision. **Ship without it.**
- Any dark-mode or ground change. Settled: light.
- Retiring Bodoni from the *shell*. It stays as the shell display face; only the issue register
  changes.

---

## 9. Skills to invoke

- **`superpowers:executing-plans`** — invoke this first, before touching code. The plan has
  checkpoints at steps 2, 3 and 5 and this skill is how you honour them.
- **`superpowers:verification-before-completion`** — before claiming any gate passes.
- **`superpowers:systematic-debugging`** — if step 2's bridge change moves anything visually. That is
  a bug hunt, not a design decision. Precedent exists for silent Turbopack utility-generation failures.
- **`superpowers:requesting-code-review`** — before declaring done.
- **`frontend-design`** — for the re-skin judgment inside the already-decided direction.
- **Do NOT invoke `superpowers:brainstorming`.** The direction is decided and rendered.
- **Caution on `ui-ux-pro-max`:** useful for contrast and motion lookups (`--domain ux`,
  `--domain color`), but its style database returns *synthwave* for "retro-futurism," which is the
  one thing explicitly rejected here.

---

## 10. Working notes / traps

- **A GateGuard hook fires before the first Bash, Write and Edit of every session.** It demands
  importers, affected API, data schemas, and the user's verbatim instruction. State the four facts
  concisely and retry the identical call. `ECC_GATEGUARD=off` disables it if it blocks setup work.
- **The human judges visually and has overruled type proposals four times.** Prose descriptions of
  fonts were consistently wrong; rendered comparisons were consistently right. **Render it and show
  it.** Batch candidates into one render rather than iterating one at a time — probe iteration cost
  ~$98 in one prior session.
- **Reference renders that already exist:** `frontend/design/probes/*.html` with matching `.png`
  (geometry, serifs, mastheads, deco faces, role map, stroke weight). The approved stroke ladder also
  exists as a Framer project named **"Courteous Jargon"** (`tTwTLi9kcMXC8LyV3VPy`) in the human's
  account — that is exploration only and is **not** a source of truth. The repo is.
- **Rendering probes locally:** the Browser pane proved unreliable (hung on scroll). What works: a
  throwaway `.probe-shot.mjs` **inside `frontend/`** so `@playwright/test` resolves, chromium at
  1440×1200 `deviceScaleFactor: 2`, `waitForTimeout(2500)` for webfonts, screenshot `fullPage`, then
  delete the script.
- **Superseded, do not execute:** `frontend/PROBE_REV2_HANDOFF_PROMPT.md`. The plan instructs
  deleting it.

---

## 11. Git state — read before your first commit

Nothing from the last two sessions is committed. Untracked and worth committing early so the rejected
directions stay on record:
- `frontend/design/probes/` — probe HTML + PNGs. **Note:** this directory also holds ~6.4 MB of design
  binaries whose Wikimedia sources are CC BY-SA and need attribution before committing. Check before
  you `git add -A`.
- `frontend/design/refs/font-decision/` — the two reference screenshots the type decision came from.
- `docs/superpowers/plans/2026-08-08-*.md` — the plan, the session handoff, and this document.

Behaviour changes and refactors are **separate commits**, with tests green between them. Step 2 is a
pure refactor and must be its own commit.

---

## 12. How the human will verify this

They review before merging and they judge visually. Expect to be asked for:
1. The before/after screenshot diff from **step 2**, proving nothing moved.
2. A 1440px screenshot of the `decision-ledger` spike from **step 3**, showing the register boundary
   holding — hard inside, calm outside.
3. Gate output, quoted, not summarised.
4. The `DEVIATIONS.md` rows, since this moves Tier-F values.

Do not report a step complete because the code exists. A step is complete when its checkpoint passes.
