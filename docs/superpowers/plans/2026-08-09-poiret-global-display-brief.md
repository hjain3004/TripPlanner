# Brief — promote Poiret One to the product's global display face

**Written:** 2026-08-08 · **Repo:** `/Users/himanshu_jain/TripPlanner` · **Branch:** `main`
**Decided by the human:** Poiret One replaces Bodoni Moda as the display face **product-wide**, not
just inside the issue register.

**Read first:** `2026-08-08-jet-age-execution-handoff.md` (§2 settled decisions, §3 stroke mechanic,
§5 Tier-F guards — all still current) and `2026-08-08-jet-age-correction-brief.md` (three open
defects from the first pass). **This brief supersedes the register-scoped font decision in both.**

---

## 0. Why this change exists

The register-scoped approach produced a broken outcome: `verdict-header` was the only product
component carrying the display face, while `/plan/page.tsx` renders six `font-display` h2 section
headings — "Itinerary", "Budget", "Payment strategy", "Points & transfers", "Data quality" — that sit
**outside** any register and therefore rendered **Bodoni Moda**. The results page showed two
competing display faces inches apart in a single column.

Promoting Poiret One globally removes the contradiction and deletes a whole class of "which face
applies here" bugs. It also simplifies the register, which should never have owned a font decision.

---

## 1. STOP — resolve this before writing any code

**The 40px Poiret floor and the h2 type slot are mutually exclusive as currently specified.**

| token | computed range | vs 40px floor |
|---|---|---|
| `--text-hero` | `clamp(3.5rem, 2rem + 6vw, 6rem)` → 56–96px | clears |
| `--text-h1` | `clamp(2.5rem, 1.8rem + 3vw, 3.5rem)` → 40–56px | clears, exactly at the floor |
| `--text-h2` | `clamp(1.75rem, 1.4rem + 1.8vw, 2.25rem)` → **28–36px** | **breaches at every width** |

`CONTRACT.md` §1 permits the display face on **hero, h1 and h2**. `text-h2` never reaches 40px. So
"Poiret wherever display is allowed" cannot be implemented as written. Additionally,
`/plan/page.tsx` lines 224, 276 and 503 use `font-display text-2xl` — a Tailwind built-in at 24px,
not the h1 token — which breaches badly.

**Three resolutions. Pick one, render it, and get the human's sign-off before rollout:**

- **(a) Re-test the floor with the stroke applied. — try this first.** The 40px floor was set for
  *unstroked* Poiret One, before the `--th-display-stroke-*` tokens existed. The stroke exists
  precisely to fix thinness, and the 1.75px floor was chosen so small headings "do not go weedy." It
  is entirely possible 28–36px now holds. **This is a render test, not a judgement call** — build a
  specimen at 28 / 32 / 36 / 40px with the stroke live and show the human. If it holds, nothing else
  changes and the contract rule stands as-is.
- **(b) Narrow the rule to hero + h1 only**, giving h2 to Schibsted Grotesk. Safest. Costs the
  section headings their display treatment, which is much of the editorial character on `/plan`.
- **(c) Raise `--text-h2` to a 40px minimum.** Do **not** pick this casually — it reflows every page
  that uses h2 and invalidates gate screenshots and spacing rhythm across the product.

Whichever wins, the three `text-2xl` h1s on `/plan` must be fixed regardless: either promote them to
`text-h1` or move them to the UI font. A 24px Poiret heading is not acceptable under any option.

---

## 2. Architectural change — the font stops being a register concern

Currently `--th-font-display` and the three `--th-display-stroke-*` tokens live in
`.register-issue` (`frontend/src/themes/registers.css`). **Move them to the shell defaults** —
`singapore.css`, alongside the other `--th-*` defaults — so the whole product inherits them.

After the move, `.register-issue` keeps **only** what makes it an issued document:
`--th-radius-*: 0`, `--th-shadow-*: none`, full-opacity `--th-border`, darkened `--th-text`, and the
`--th-plate` / `--th-board` / `--th-board-text` values. **Delete the `--th-font-display` line and the
stroke tokens from the register.** A register that overrides the display font to the value the shell
already has is dead code that will mislead the next reader.

The `.display-stroked` utility becomes global. Every `font-display` site gets it — the stroke is not
optional decoration, it is how this face reaches usable weight.

---

## 3. Full audit — every `font-display` site in the product

Fix all of these. This is the complete list as of 2026-08-08; re-grep to confirm nothing was added.

| File:line | Tag | Size | Action |
|---|---|---|---|
| `app/page.tsx:22` | h1 | `text-hero` | add `display-stroked` |
| `app/page.tsx:164` | h2 | `text-h2` | add `display-stroked`; **gated on §1** |
| `app/plan/page.tsx:224` | h1 | `text-2xl` | **breach** — promote to `text-h1` or move to UI font |
| `app/plan/page.tsx:276` | h1 | `text-2xl` | **breach** — same |
| `app/plan/page.tsx:503` | h1 | `text-2xl` | **breach** — same |
| `app/plan/page.tsx:553,562,594,604,621,642` | h2 | `text-h2` | add `display-stroked`; **gated on §1** |
| `components/product/verdict-header.tsx:51` | h1 | `text-h1` | already correct — the human added `display-stroked` by hand |
| `components/product/SharedUI.tsx:29` | **h4** | `text-lg` | **contract violation, pre-existing** — see below |

**`SharedUI.tsx:29` is `<h4 className="font-display font-bold text-lg …">`.** That breaks the frozen
rule twice: display face on an h4 (rule is h1/h2 only), and `font-bold` on a single-weight face,
which produces faux-bold — the exact smearing the stroke work exists to prevent. At `text-lg` (18px)
it is less than half the floor. **Move it to the UI font.** Do not "fix" it by adding the stroke.

Also check `verdict-header`'s `text-h1` at small breakpoints — the clamp bottoms out at exactly
40px, so it sits precisely on the floor with no margin. Any responsive step-down breaches it.

---

## 4. Retire Bodoni Moda

Once §3 is complete, nothing should reference Bodoni. Then:
- Remove the `next/font/google` loader for it from `frontend/src/app/layout.tsx`, and drop the
  `--font-bodoni*` variable. This is a real payload win — it is a variable font with an `opsz` axis.
- Grep for `bodoni` (case-insensitive) across `src/` and `frontend/design/` before deleting; remove
  every stale reference.
- **Do not delete it until §3 is green.** If §1 resolves to option (b), Bodoni is still gone —
  h2 goes to Schibsted, not back to Bodoni.

---

## 5. Tier-F — this moves frozen values, so log it first

`CONTRACT.md` line 23 freezes **Bodoni Moda** as the display face. Replacing it product-wide is a
**Tier-F change**. Per `CLAUDE.md`, the `DEVIATIONS.md` rows land **before** the change, not after.

Required rows (check whether the earlier pass already wrote any — the correction brief flags them as
possibly missing):
1. Display face Bodoni Moda → Poiret One, product-wide.
2. The `--th-display-stroke-*` mechanic, which `CONTRACT.md` §2 does not currently describe.
3. Whatever §1 resolves to — floor re-test, narrowed h2 rule, or type-scale change. All three are
   Tier-F.

Then update `CONTRACT.md` §1 (the face and its constraint column), §2 (the stroke tokens), and the
`CLAUDE.md` checkpoint.

**Unchanged and still frozen:** the light ground and the singapore palette; `tabular-nums` on every
number; money and points stay in Schibsted Grotesk; provenance never styles away; lacquer under 2%.
Promoting the display face changes **nothing** about which text is display text — h3 and below, all
body, and every monetary value remain UI-font. Do not let this change leak into the money surfaces.

---

## 6. Verification

Run this on `/` and on `/plan`, with the dev server up:

```js
// every display heading, its size, and whether the stroke is live
[...document.querySelectorAll('h1,h2,h3,h4')].map(h => {
  const s = getComputedStyle(h);
  return {
    tag: h.tagName,
    px: Math.round(parseFloat(s.fontSize)),
    face: s.fontFamily.split(',')[0].replace(/"/g,''),
    stroke: s.webkitTextStrokeWidth,
    text: h.textContent.trim().slice(0, 28)
  };
});
```

**Passing means:**
- No element reports `face: "Bodoni Moda"`.
- Every element whose face is Poiret One is **≥ the floor §1 settled on**, and reports a non-zero
  `stroke`.
- Every h3/h4 reports Schibsted Grotesk.
- Money and points still report Schibsted with `tabular-nums` (check `font-variant-numeric`).

Then re-run the full gate set, rebuild the contrast matrix — stroked Poiret has different effective
weight than Bodoni, so large-text contrast must be re-measured, not assumed — and re-shoot the gate
screenshots at 1440px.

**Also verify `paint-order: stroke fill` in Safari and Firefox.** Chromium is confirmed good; the
other two are unverified. If `paint-order` is ignored the stroke centres on the outline and eats the
counters. This now affects every heading in the product, not just one, so it is no longer a minor
risk.

---

## 7. Order of work

1. §1 — resolve the floor/h2 contradiction, with a render, and get sign-off. **Nothing else starts
   until this is settled.**
2. `DEVIATIONS.md` rows (§5).
3. Move the font and stroke tokens out of the register into the shell (§2). Its own commit.
4. The §3 audit, including the `SharedUI` h4 fix and the three `text-2xl` h1s. Its own commit.
5. Retire Bodoni (§4).
6. Verification, gates, contrast matrix, screenshots (§6).
7. Then return to the three defects in `2026-08-08-jet-age-correction-brief.md` — the radius
   namespace mismatch, the `.register-issue` find-and-replace spray, and the fact that no route
   renders the register. **Those are still open and are not fixed by this brief.**

---

## 8. What not to do

- Do not start at §3. The §1 contradiction determines what §3 even says.
- Do not use `font-weight` to thicken Poiret One anywhere, ever. It is single-weight; weight comes
  from the stroke. Any `font-bold` next to `font-display` is a bug.
- Do not let the display face reach h3, body, money or points. The h1/h2 boundary is the rule that
  keeps this legible.
- Do not report done because the code compiles. It is done when the §6 probe passes on both routes
  and the human has seen a screenshot.
