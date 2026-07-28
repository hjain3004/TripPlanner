# TripPlanner F1 — gate-rigor patch prompt for opencode

Copy everything below this line into opencode. This is a narrow, bounded follow-up
to the F1 build you already completed — not a redo of F1's component/token work,
which is solid. It closes a specific gap between what Gate F1 was specified to
check and what actually got built.

---

## 0. What happened and why this exists

`reports/frontend_F1.md` reports Gate F1 as passing, and the scaffold, token
architecture, fonts, 16 shadcn primitives, 7 product wrappers, motion library, and
kitchen sink are all real and good. But a post-hoc check of the actual gate
tooling found it materially weaker than `frontend/F1_IMPLEMENTATION_PLAN.md`
Phase 6 specified:

- `frontend/scripts/token-lint.sh` checks 6 hardcoded token values via string-match
  against `singapore.css`. The spec calls for a script that also catches raw color
  literals, inline SVGs, arbitrary Tailwind values, `localStorage`/`sessionStorage`
  use, shadcn vendor-utility class names leaking outside `components/ui/`, the
  `--radius-s`/`rounded-s*` collision, and hardcoded duration/cubic-bezier values.
  None of that exists yet.
- `frontend/scripts/contrast-check.sh` computes **OKLCH lightness deltas** on 3
  pairs against a `>0.15` threshold. That is not a WCAG contrast ratio. There is no
  `culori` dependency in `package.json`, so the actual sRGB-relative-luminance math
  that produced the AA-safe token pairs in `frontend/design/CONTRACT.md` §3 during
  Phase 0 was never re-implemented as a real, running check — this is currently
  **not verifying AA compliance**, just "these two colors differ somewhat."
- No root `Makefile` `gate-f1` target exists — `make gate-f1` from the repo root
  fails. Frontend has its own disconnected `make gate`.
- No `frontend/design/refs/f1/` evidence bundle (screenshots at 390/768/1440 +
  reduced-motion, `axe-report.json`, `contrast-matrix.md`, `MANIFEST.md`) was
  committed.
- `reports/frontend_F1.md` cites `DEVIATIONS.md` rows (lacquer accent-4 budget
  enforcement, the Playwright baseURL workaround) that do not actually exist in
  `DEVIATIONS.md` — it still ends at the Phase 0 rows.

Fix these five things. Do not touch the token values, component code, fonts, or
kitchen sink content unless a fix genuinely requires it (e.g., adding a missing
`data-motion` attribute so the reduced-motion assertion has something to check).

## 1. Read first

`DEVIATIONS.md`, `frontend/F1_IMPLEMENTATION_PLAN.md` (specifically its Phase 6
section — this is the literal spec for what you're building here), `frontend/design/CONTRACT.md`
§3 (the exact token values and the contrast pairs already computed by hand in
Phase 0 — your `contrast.test.ts` must reproduce these same numbers, not invent
new ones), and `reports/frontend_F1.md` (what currently exists, so you don't
duplicate work).

## 2. Deliverable 1 — real `token-lint`

Replace `frontend/scripts/token-lint.sh` with `frontend/scripts/token-lint.mjs`
(zero-dependency Node script, per the plan). It must implement every rule listed
in the plan's Phase 6 section:

- No raw color literals in `src/app/**`, `src/components/**`, `src/lib/motion/**`
  (strip `href="#…"`/`url(#…)` anchor contexts first — don't false-positive on
  those). `src/themes/**` is exempt (that's where raw values legitimately live).
- No inline `<svg>` outside `components/ui/` (Lucide icons only elsewhere).
- No raw radius values, no `rounded-s*`/`rounded-e*` utility classes anywhere
  (the `--radius-s` collision with Tailwind's logical-side utility).
- No hardcoded duration or cubic-bezier values — must use the `--dur-*`/
  `--ease-brand` tokens.
- `globals.css` must equal the 4-line manifest (`@import "tailwindcss"`,
  `tw-animate-css`, `../themes/base.css`, `../themes/singapore.css`).
- No shadcn vendor utility names (`bg-background`, `text-muted-foreground`,
  `border-input`, `ring-ring`, etc.) outside `components/ui/`.
- No `dark:` variant or `next-themes` usage anywhere (no dark mode, Tier F).
- No `var(--color-*)` or `var(--th-*)` in product code (only Tailwind utilities).
- No arbitrary color values (`bg-[#...]` etc.).
- No `localStorage`/`sessionStorage`.
- No `tailwind.config.*` file.
- No `framer-motion` in `package-lock.json` (only `motion`).

Support `--json` mode and a suppression comment
(`/* token-lint-disable-next-line <rule> -- <reason> */`) where the reason is
required text, not optional. Wire it into `frontend/Makefile` as `fe-token-lint`.

## 3. Deliverable 2 — real WCAG contrast check

Add `culori` + `@types/culori` as devDependencies (within the F1 dependency
budget — the plan explicitly names these as allowed). Write
`frontend/scripts/parse-theme.ts` (postcss-parses the theme CSS, resolves the
`@theme inline` bridge one level) and `frontend/tests/contrast.test.ts`:

- Convert OKLCH → sRGB via `culori`, compute real WCAG relative luminance and
  contrast ratios (4.5:1 body text, 3:1 large text) — not a lightness delta.
- **Composite alpha over the declared backdrop before computing ratios** — borders
  and overlays carry alpha (`--color-border` is ~10% opacity, `--color-surface-overlay`
  is ~72%); skipping this reports wrong numbers.
- Assert a **hand-authored pair matrix**, not an auto cross-product. Reproduce the
  exact pairs and ratios already computed in `frontend/design/CONTRACT.md` §3 and
  `frontend/design/refs/palette/MANIFEST.md` (e.g. `--color-savings-text` on
  `--color-surface` ≈ 7.04:1, `--color-warning-text` ≈ 7.09:1,
  `--color-success-text` ≈ 6.52:1, `--color-text-muted` on `--color-surface` ≈
  4.75:1). If your computed number differs from those by more than rounding, you
  have a bug in the parser or the theme CSS — not a reason to change the
  threshold.
- **Completeness assertion**: every text and surface token in `CONTRACT.md` §3
  must appear in at least one tested pair — fail loudly if a token was added and
  never tested.
- Borders get a separate **visibility threshold** (ΔL after alpha compositing),
  not the 3:1 ratio — asserting 3:1 on an intentionally-8–10%-opacity hairline
  would fail the approved design by construction. **Focus rings** are the
  exception and do carry the real 3:1 obligation, tested against every surface
  they can appear on.
- Throw on any unresolved token reference. Never skip a token silently.

Wire into `frontend/Makefile` as `fe-contrast`. Delete `contrast-check.sh` once
this replaces it.

## 4. Deliverable 3 — root Makefile integration

Add to the root `Makefile` (which already has `gate-m1`, `gate-m1b`, `gate-m2`,
`gate-m3` targets for the backend — match that style, do not touch those targets):

```make
gate-f1:
	$(MAKE) -C frontend fe-typecheck fe-token-lint fe-contrast fe-build fe-gate-shots
```

Ensure `frontend/Makefile` has matching `fe-typecheck`, `fe-build`, and
`fe-gate-shots` targets (rename/alias existing `typecheck`/`build`/whatever
Playwright target currently exists — keep the frontend-local short names as
aliases if you want, but `fe-*` names must exist and `make gate-f1` from repo
root must work end to end). `fe-e2e-install` (Chromium download) stays a
**non-prerequisite** — don't make a 150MB download part of the gate.

## 5. Deliverable 4 — evidence bundle

Produce and commit `frontend/design/refs/f1/` with deterministic filenames
(re-runs overwrite, not accumulate): Playwright screenshots at 390/768/1440 plus
one reduced-motion screenshot, `axe-report.json` (from `@axe-core/playwright`,
`violations.length === 0` asserted, `incomplete[]` written to the report — do not
silently allowlist anything to force a pass), `contrast-matrix.md` (the pair
matrix from Deliverable 2, human-readable), `MANIFEST.md` describing what each
file is. Confirm your Playwright suite runs against a **production build**
(`next build && next start`), never `next dev` — dev-mode React warnings will
break the console-error assertion. If you fix the "Playwright baseURL not
propagating" issue mentioned in `reports/frontend_F1.md`, do it properly (wire
`use.baseURL` correctly per-project) rather than leaving the full-URL workaround
undocumented — either fix it or log *why* the workaround is the right call, in
DEVIATIONS.md, not just in report prose.

## 6. Deliverable 5 — fix `DEVIATIONS.md` and `reports/frontend_F1.md`

`reports/frontend_F1.md` currently claims certain decisions are logged in
`DEVIATIONS.md` when they aren't. Add the real rows now, in the existing
6-column format (`date · doc§ · question · decision · rationale · affected_files`):

- The lacquer `--color-accent-4` <2%-surface-budget enforcement mechanism you
  actually used (CSS discipline via `NotchLabel`? a lint rule? manual review?
  state which).
- The Bodoni Moda `opsz` axis wiring detail, if anything about how you wired
  `next/font/google`'s variable axis differed from a literal reading of
  `CONTRACT.md` §1.
- The Playwright `baseURL` issue and your actual resolution.
- **A new row documenting this patch itself**: that the first Gate F1 pass
  under-implemented `token-lint` and the contrast check relative to spec, what
  was missing, and what this patch changed. This is the honest record — don't
  quietly overwrite history.

Then update `reports/frontend_F1.md`'s Gate Assertions table and "Key Decisions
Logged" section to reflect what's actually true after this patch, with the real
`make gate-f1` output pasted in, not a restatement of the original claims.

## 7. Skills

`ecc:frontend-a11y` while building the contrast/axe checks. `superpowers:systematic-debugging`
if the culori/postcss parsing produces unexpected numbers — don't loosen a
threshold to make a bug disappear; find why the number is wrong first.
`superpowers:verification-before-completion` before reporting this done: you must
have actually run `make gate-f1` from the repo root and seen it pass, not assumed
the pieces would compose correctly.

## 8. Definition of done — verify every line before reporting complete

- [ ] `make gate-f1` from the **repo root** passes.
- [ ] `frontend/scripts/token-lint.mjs` exists, implements every rule in §2 above,
      and running it against the current `frontend/src/` reports zero violations
      (or documented, reasoned suppressions).
- [ ] `frontend/tests/contrast.test.ts` computes real WCAG ratios via `culori`,
      matches the numbers already in `CONTRACT.md` §3 within rounding, and has a
      completeness assertion that would fail if a token were untested.
- [ ] `make gate-f1` from repo root works end to end (not just `frontend/Makefile`
      targets individually).
- [ ] `frontend/design/refs/f1/` exists with real screenshots, a real
      `axe-report.json` with `violations.length === 0`, and `contrast-matrix.md`.
- [ ] `DEVIATIONS.md` has the new rows from §6, including the honest one about
      this patch itself.
- [ ] `reports/frontend_F1.md` is corrected to match reality, with pasted command
      output as evidence, not restated claims.

Do not report this complete until every box above is independently verified by
you running the command and reading its actual output — this file exists because
the previous report claimed things that weren't true, so the standard now is
higher, not the same.
