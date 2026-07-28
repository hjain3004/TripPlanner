# Handoff — F1.5 completion (recover from interrupted run)

**Status:** in progress, build is RED. Self-sufficient for a cold start.
**Branch:** `feat/f1-frontend-foundation`. Do not merge to `main`. Nothing is committed.

A prior agent completed most of F1.5 and then terminated mid-edit, leaving a syntax
error that breaks the production build. Your job is to fix it, finish the remaining
items, and — most importantly — **actually look at the rendered page**.

Read `frontend/HANDOFF_LANDING_COMPOSITION.md` first. It is the original task spec
(scope, frozen design facts, composition blueprint, verification protocol). This file
only covers what is left.

---

## 0. Ground rules

- Do not reopen fonts, palette, or type scale. Frozen. See `frontend/design/CONTRACT.md`.
- Do not touch `backend/`. No new dependencies. No `localStorage`/`sessionStorage`.
- Do not create `tailwind.config.*` (Tailwind v4 is CSS-first; token-lint R11 fails it).
- `frontend/AGENTS.md`: this is **not** the Next.js you know (v16, Turbopack). Read the
  relevant guide in `node_modules/next/dist/docs/` before writing App Router code.
- Log every judgment call to `DEVIATIONS.md` as `date, doc§, question, decision,
  rationale, files`.

---

## 1. BLOCKER — fix this first

`npm run build` fails:

```
./src/components/product/site-header.tsx:10:2  Expression expected
Import trace: site-header.tsx -> app/page.tsx
```

**Cause.** `src/components/product/site-header.tsx` line 9 puts a `/* ... */`
suppression comment *inside* a `/** ... */` JSDoc block. The inner `*/` terminates the
JSDoc early, so lines 10–16 parse as code.

**Do not fix this by relocating the comment.** The suppression only exists to silence a
false positive, and the false positive is a defect in the gate script:

`scripts/no-dead-classes.mjs` → `extractUtilityClasses()` (~line 66) runs its utility
regex over raw source lines. It strips suppression comments (line 73) but nothing else,
so ordinary prose inside comments is scanned. The JSDoc sentence *"the one deliberate
accent-4 (lacquer) use"* yields `accent-4` as a candidate class.

**Correct fix, in this order:**

1. In `scripts/no-dead-classes.mjs`, strip comment bodies before extraction — remove
   `//`-to-EOL and `/* ... */` spans (keep the existing suppression-comment handling,
   which must run first so suppressions still register). Better still, scan only
   `className=` / `class=` attribute values; either is acceptable, prose must not be
   scanned.
2. Delete the now-unnecessary suppression on `site-header.tsx` line 9 and restore the
   JSDoc block to valid syntax.
3. Keep the line-39 suppression on `hover:text-primary-hover` / `hover:border-primary-hover`
   — that one is legitimate. Verify it still registers after your change.
4. While in the script: the strip regex on line 73 uses `\S+` for the rule name and does
   not handle multi-rule suppressions, unlike `SUPPRESSION_RE` on line 29. Make them
   consistent.

**Then rebuild.** `.next/` is stale (built before the break). `no-dead-classes` scans
compiled CSS in `.next/`, so any PASS against the stale build is meaningless. Always
`npm run build` before running it.

---

## 2. Reconcile the gate targets

The prior agent wired the two new gates into `frontend/Makefile`'s `gate` target only:

```make
gate:    fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots fe-no-dead-classes fe-product-shots
fe-gate: fe-token-lint fe-contrast fe-typecheck fe-build fe-gate-shots      # <- not updated
```

The root `Makefile`'s `gate-f1` (line 98) was also not updated. Decide on one canonical
F1 gate, wire `fe-no-dead-classes` and `fe-product-shots` into it consistently across
both Makefiles, and make sure ordering puts `fe-build` before `fe-no-dead-classes`.
Log the choice in `DEVIATIONS.md`.

---

## 3. Prove G1 actually catches something

The handoff requires G1 be **demonstrated to fail**. Seed a known-dead class (e.g.
`text-on-primary`, the original bug — the real token is `text-text-on-primary`) into a
component, rebuild, confirm `no-dead-classes` exits non-zero and names the class, then
revert the seed. Record the observed output in the report.

---

## 4. Run G2 and do the visual comparison — this is the whole point

`e2e/f1-5-landing.spec.ts` exists and is wired as `fe-product-shots`. It has never been
run against a working build.

1. Build, start the server, run it. Capture `/` and `/plan` at **1440 / 768 / 390** plus
   reduced-motion. Commit the screenshots to `frontend/design/refs/product/` (the
   directory does not exist yet — create it) with a `MANIFEST.md` alongside, matching the
   format used by the sibling folders in `frontend/design/refs/`.
2. axe must be clean. Do not add new axe exclusions to make it pass.
3. **Open the screenshots and compare them, side by side, against:**
   - `frontend/design/refs/palette/celadon-mangrove-forward-1440.png` (and its `.html`,
     which carries the exact approved geometry)
   - `frontend/design/refs/brainstorm/calm-route-hybrid-polish-1440.png` (layout,
     density and structure only — its typography is **rejected**)
   - `frontend/design/refs/brainstorm/MANIFEST.md` for what each render approves/rejects
4. Answer §7 of `HANDOFF_LANDING_COMPOSITION.md` in writing, question by question. If a
   §7 answer is "no", fix the page — not the question.

A green gate is not evidence the page looks right. Prior runs proved that twice.

---

## 5. Write the report

`frontend/reports/f1_5_landing.md`, following the shape of the existing
`frontend/reports/frontend_F4.md`:

- What was built (landing composition, site header, G1, G2).
- The G1 fail-demo output from §3.
- The §7 answers from §4, verbatim.
- Both gates' final output.
- Anything knowingly left undone.

---

## 6. Definition of done

- [ ] `npm run build` green; `npx tsc --noEmit` clean.
- [ ] `no-dead-classes.mjs` no longer scans comment prose; the JSDoc suppression is gone;
      the line-39 hover suppression still registers.
- [ ] G1 demonstrated to fail on a seeded dead class, then reverted.
- [ ] Gate targets consistent across `Makefile` and `frontend/Makefile`.
- [ ] Canonical F1 gate green — no narrowed scope, no new axe exclusions.
- [ ] Product screenshots at 1440/768/390 + reduced-motion committed under
      `frontend/design/refs/product/` with a `MANIFEST.md`.
- [ ] Screenshots visually compared against `design/refs/`; §7 answered in writing.
- [ ] `frontend/reports/f1_5_landing.md` written.
- [ ] `DEVIATIONS.md` rows added for every judgment call.
- [ ] Nothing in `backend/` touched. No new dependencies.

---

## 7. If you get stuck

Stop and report what you tried. Do not silently narrow gate scope, add axe exclusions,
or delete failing assertions to reach green — that is the exact failure mode this task
exists to correct.
