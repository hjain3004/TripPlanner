# Reconciled Visual System — calm shell, issued documents

**Date:** 2026-07-29
**Status:** PLANNED — not started. Produces documentation and one static probe. No product code.
**Scope:** Frontend design system only. The frontend remains **paused**; this does not resume it.
**Blocking:** Nothing. `docs/superpowers/plans/2026-07-28-figma-template-reconciliation.md`
still gates any implementation of the register.

Written to be self-sufficient from a cold start. You should not need to re-derive the
visual direction or re-run any probe.

---

## 1. Context

The frontend has **three competing visual sources of truth**. Adding a fourth direction
without resolving them is how the PR #4 breakage happened.

| Source | Status | Says |
|---|---|---|
| `frontend/design/CONTRACT.md` | frozen F1 contract | soft layered shadows, 1px hairlines, `--radius-m: 12px`. Line 125 marks the depth rule **Tier F** |
| `docs/superpowers/specs/2026-07-28-plate-and-proof-design.md` | PAUSED | plate/proof printing metaphor, three registers (`structure`/`signal`/`value`) |
| `design/Premium Travel Itinerary Planner/` | adopted 2026-07-28 as "frozen visual template" | calm editorial composition, but components use `rounded-none` throughout |

The owner wants neobrutalism in a **calm, destination-toned register** — a soothing shell
where computed artifacts read as issued travel documents. Explicitly *not* the
bright-coloured kind.

Three findings shaped this plan:

1. **This is not a pivot.** "Plate & Proof" is already a *printing* metaphor (plate =
   printing plate, proof = printer's proof); its §4.3 establishes a "proof register." The
   ticket direction is a fourth register in an existing system, not a new philosophy.
2. **The Figma template already leans neobrutalist** — `rounded-none` throughout,
   contradicting `CONTRACT.md`'s 12px default. Direction B of the owner's own
   `visual-reset-three-directions` probe is a boarding pass with a celadon offset block.
3. **The organising idea:** do not call it a hard offset shadow. In printing, a second
   plate slightly **out of register** produces exactly that offset colour block. The
   offset is the plate metaphor taken literally, not neobrutalism borrowed. This gives a
   principled rule for its use and makes contradictions render as literal misregistration.

**Outcome:** one authoritative visual spec resolving every conflict, plus a static 1440px
probe proving the direction before the design system commits to it.

---

## 2. Decisions taken — do not reopen

| Conflict | Resolution |
|---|---|
| Figma bundle vs Plate & Proof | **Figma wins composition, layout, page structure.** Plate & Proof wins palette, the register system, and the posterized illustration technique. |
| Soft shadow (Tier-F depth rule) vs offset plate | **Scope the rule.** Shell surfaces keep surface-tint + layered shadow + hairline. The `issue` register uses an offset plate, no blur. Requires a Tier-F row in `DEVIATIONS.md`. |
| 1px hairline vs 2px ticket rule | **No amendment needed.** `CONTRACT.md:132` already permits a heavier rule where "a component contract explicitly calls for" one. The `issue` register is such a contract. |
| `--radius-m: 12px` vs `rounded-none` | Shell keeps its radii. `issue` register is `0`. Both correct in their own scope. |
| accent-4 <2% budget vs stamps | Budget holds. Lacquer becomes **mandatory on exactly one thing** — `verify_required` — and optional nowhere. This **closes Task 9** of the figma-template-reconciliation plan. |

---

## 3. The `issue` register

A fourth register alongside `structure` (mangrove lines), `signal` (lacquer, nothing at
rest), and `value` (brass, money only).

> **The document treatment is earned, not decorative.** An element renders as an issued
> document if and only if it represents a computed artifact the kernel produced and a
> validator checked. Nothing decorative is ever a ticket.

This is the discipline that makes the visual language *mean* something, which is the
product's thesis.

**Form:** sharp corners (radius `0`); a solid celadon-1 block offset `+6px/+6px` with **no
blur**; a 2px mangrove rule; mono field labels uppercase at ~10–11px with `0.16em`
tracking; Schibsted Grotesk heavy for data fields and airport codes; Bodoni Moda on the
calm shell **only**, never inside a document.

**State mapping.** These five values are the `FreshnessState` enum in
`backend/gateway/evidence/nodes.py`, corrected on 2026-07-29 to match spec 16 §3. Do not
invent states:

| status | Treatment |
|---|---|
| `live` | full offset plate, crisp registration |
| `cached` | offset plate in celadon-2 (lighter) |
| `estimated` | dashed 2px rule, **no** offset plate — nothing was issued |
| `stale` | plate greyed, diagonal `STALE` overprint |
| `verify_required` | lacquer stamp — the one place lacquer is mandatory |

**Lifecycle Mapping (LifecycleState):**

| Status | Treatment |
|---|---|
| `active` | default plate |
| `superseded` | graph-lifecycle treatment with diagonal `SUPERSEDED` overprint |

| Graph concept | Treatment |
|---|---|
| `CONTRADICTS` edge | two plates visibly out of register — double-vision offset |
| `DERIVED_FROM` lineage | printed verification strip along the bottom edge, mono |
| transfer plan | detachable stub, perforated rule (dotted `border-top`) |
| verify-before-transfer | boarding-pass checklist row, unticked box, lacquer |

---

## 4. Deliverables

### A — the probe (the real deliverable)

Create `frontend/design/probes/issue-register-1440.html`.

Reuse the pattern in `frontend/design/probes/plate-and-proof-still.html` verbatim:
standalone HTML, `body { width: 1440px }`, a Google Fonts link for the three families, and
a `:root` block under the existing comment convention *"Values lifted verbatim from
frontend/src/themes/singapore.css — no invented colour."*

```css
--paper-deep: oklch(0.947 0.013 87);   /* limestone */
--paper:      oklch(0.979 0.008 91);   /* paper     */
--ink:        oklch(0.281 0.007 145);
--ink-muted:  oklch(0.525 0.014 157);
--ink-faint:  oklch(0.660 0.014 157);
--structure:  oklch(0.320 0.042 181);  /* mangrove  */
--celadon-1:  oklch(0.848 0.027 167);
--celadon-2:  oklch(0.917 0.016 161);
--value:      oklch(0.660 0.097 82);   /* brass     */
--signal:     oklch(0.536 0.135 30);   /* lacquer   */
--rule:       oklch(0.28 0.01 145 / 0.10);
```

**Introduce no new hex or OKLCH value.**

Must show, against the calm shell for contrast: a flight document in all five status
states; a transfer-plan stub with perforation; a contradiction as two misregistered
plates; a provenance strip; the verify-before-transfer checklist row.

### B — the spec

Create `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md` — the single source
of truth. Records the register system, the `issue` contract, the state mapping, and every
conflict resolution in §2. Self-sufficient from a cold start.

### C — document updates

- `frontend/design/CONTRACT.md` — scope §3's depth rule to shell surfaces; add the `issue`
  register as an explicit component contract under the line-132 border exemption.
- `docs/specs/11_design_system_and_theming.md` — the `issue` register tokens.
- `docs/superpowers/specs/2026-07-28-plate-and-proof-design.md` — status becomes
  `SUPERSEDED BY 2026-07-29-visual-system-reconciled.md`. Carry its palette, register, and
  posterize findings forward; do not discard them.
- `design/README.md` — note Figma remains authoritative for **composition only**.
- `DEVIATIONS.md` — one **Tier-F** row for the scoped depth rule, following the precedent
  of the `@theme` → `@theme inline` row.
- `docs/superpowers/plans/2026-07-28-figma-template-reconciliation.md` — its §3 ground rule
  *"Do not re-derive visual direction… no new probes"* is now **stale** and would mislead
  the next agent. Point it at the reconciled spec and mark **Task 9 closed**.

---

## 5. Verification

1. Screenshot the probe at 1440px. Compare against
   `frontend/design/probes/plate-and-proof-still-1440.png` — the two must read as **one
   system**, not two.
2. `grep -o 'oklch([^)]*)' frontend/design/probes/issue-register-1440.html | sort -u`
   → every value must appear verbatim in `frontend/src/themes/singapore.css`.
3. Measure lacquer surface area in the screenshot. Under 2%, with only `verify_required`
   stamps and the checklist row using it.
4. Re-check the AA contrast pairs in `CONTRACT.md` §2 for any text now sitting on a celadon
   offset plate rather than paper. State the computed ratios.
5. `git status` → only docs and the probe HTML changed. Zero files under `frontend/src/`
   or `backend/`.
6. The probe PNG is gitignored (`.gitignore` excludes `frontend/design/probes/*.png`); the
   **HTML is tracked**. Commit markup, not renders.

---

## 6. Out of scope

- No product code. `frontend/src/` untouched; the frontend stays paused.
- No implementation of the register — that folds into the figma-template-reconciliation
  plan when frontend work resumes.
- No new palette, fonts, or destination themes.
- Not fixing the 44 TypeScript errors on `origin/main` — that is reconciliation Task 1.
- No `backend/` changes.

---

## 7. Execution notes

Branch: `docs/visual-system-reconciled`, off `main`.

**Skills to invoke:** `superpowers:using-superpowers` first; `frontend-design` before
writing any CSS (this is aesthetic work, not mechanical); `superpowers:verification-before-completion`
before reporting done; `claude-in-chrome` or `chrome-devtools` to screenshot at 1440px.
Do **not** invoke `brainstorming` or `writing-plans` — the direction is decided here.

**If a §2 decision looks wrong:** implement it as written, log the objection in
`DEVIATIONS.md`, and raise it in the report. Do not silently deviate.

**Do not push, merge, or open a PR.** Leave the branch local and report.

### Two known risks

- **The probe is the real test.** The spec can be written from §2–§3 in an hour; whether
  "calm neobrutalism" reads as *calm* rather than merely quiet is only answerable by
  looking at it next to the existing plate-and-proof render. If the probe fails that
  comparison, **the spec changes, not the probe**.
- **Scoping the Tier-F depth rule leaves two depth models** — soft for shell, offset for
  documents. That is more complexity than one model. It is judged correct because it is
  what makes the document treatment mean something, but if the probe shows the two models
  fighting, collapsing to one is the fallback.
