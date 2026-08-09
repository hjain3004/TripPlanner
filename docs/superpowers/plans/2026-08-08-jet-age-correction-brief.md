# Correction brief — Jet Age issue register, first implementation pass

**Written:** 2026-08-08, after reviewing the implementation of
`docs/superpowers/plans/2026-08-08-jet-age-issue-register.md` §4.
**Repo:** `/Users/himanshu_jain/TripPlanner` · **Branch:** `main` · nothing committed.
**Read with:** `2026-08-08-jet-age-execution-handoff.md` (still current — §2 settled decisions,
§3 stroke mechanic, §5 Tier-F guards all stand unchanged).

**Read this before touching anything. Do not restart the plan. Most of it is correct.**

---

## 0. Verdict

Steps 1–4 landed and the register mechanically works. **Three defects remain**, one of which
silently blocks the entire step-5 rollout. The human's report — *"implemented the plan but I can't
see any changes on localhost"* — is **not** a plumbing failure. It is a coverage failure plus a
token-namespace mismatch. Diagnosis below is evidence, not inference; reproduce it before changing
anything.

---

## 1. What is already correct — do NOT redo this

Verified in a live browser against the running dev server:

- **Fonts.** Poiret One is loaded and exposed as `--font-poiret-one`. Bodoni, Schibsted and Roboto
  Mono all still present.
- **The `@theme inline` bridge works.** It resolves at the consuming element, which is the whole
  point of the `inline` keyword. Identical probe element in two contexts:

  | | inside `.register-issue` | in the shell |
  |---|---|---|
  | `font-display` | **Poiret One** | Bodoni Moda |
  | `shadow-1` | **none** | layered shadow |
  | `border-border` | **full-opacity mangrove** | 10%-opacity hairline |

- **`registers.css` exists, is correct, and is imported** as the 5th and last line of
  `globals.css`'s import manifest. Token-lint R5 respected — imports only.
- **`OffsetPlate` renders its `::before` plate at `top:12px; left:12px`.** `SplitFlap` exists and is
  wired into `/kitchen-sink`.

**Do not re-litigate any of the above.** If you find yourself editing `base.css`'s `@theme inline`
block, stop — it is not the bug.

---

## 2. Defect 1 — the bridged radius tokens are not the ones components use

**This is the blocker. Fix it first.**

Measured *inside* a `.register-issue` subtree on the live page:

```
rounded-sm   → 6px      ← used by payment-strategy-card, transfer-plan-panel
rounded-md   → 12px     ← used by decision-ledger
rounded-full → 9999px   ← used by itinerary-timeline
rounded-m    → 0px  ✓   bridged to --th-radius-m, but no component uses it
rounded-l    → 0px  ✓   bridged to --th-radius-l, but no component uses it
```

The register zeroes `--th-radius-s/m/l`. Those feed the `rounded-s` / `rounded-m` / `rounded-l`
utilities. **Every product component uses Tailwind's built-in `rounded-sm` / `rounded-md` /
`rounded-full` instead**, which are not wired to `--th-*` at all. Plan §3 assumed components consume
the bridged names. They do not.

Consequence: when the step-5 components finally render, **their corners stay rounded** and the
register looks broken. This would almost certainly be misdiagnosed as "the design doesn't work."

**Fix — pick one, and log it in `DEVIATIONS.md` either way:**

- **Preferred: converge the component classes.** Replace `rounded-sm`→`rounded-s`,
  `rounded-md`→`rounded-m`, `rounded-lg`→`rounded-l` across product components. This is what
  `CONTRACT.md` already intends — it notes `--radius-s` "shadows Tailwind's logical `rounded-s*`
  utility" and that token-lint forbids `rounded-s*`/`rounded-e*` precisely so the logical variants
  don't collide. **Read that token-lint rule before you start** — you may need to amend it, and
  that is a `CONTRACT.md` change requiring its own DEVIATIONS row.
- **Alternative: bridge the built-in names too**, adding `--radius-sm: var(--th-radius-s)` etc. to
  the `@theme inline` block. Lower churn, but it means two names for one concept forever. If you
  choose this, say so explicitly in the DEVIATIONS row and update `CONTRACT.md` §2 so the next
  person isn't misled.

`rounded-full` is a separate call: `CONTRACT.md` reserves `--radius-full` for "genuine status pills
and compact controls." A 0-radius register arguably should not zero pills. **Decide deliberately and
write down the decision** — do not let it fall out of a find-and-replace.

---

## 3. Defect 2 — `.register-issue` was applied by find-and-replace

The class is on roughly every element in 12 files — `<span>`, `<li>`, text wrappers, icon elements.
Examples: `payment-strategy-card.tsx` has ~30 occurrences; `transfer-plan-panel.tsx` has ~45.

It is **functionally inert** — the class only declares custom properties, and those inherit to
descendants anyway — so this is not why nothing renders. It is still wrong:

1. **It makes the register boundary unauditable.** The §2 rule is the thing keeping this system
   coherent. You cannot review a boundary that is on every node.
2. **It swept in surfaces that fail the boundary rule.** `assumptions-footer`, `booking-checklist`,
   `route-spine`, `route-node`, `provenance-band` do not render kernel-computed numbers. Per plan §2
   they do not belong in the register at all.

**Fix:** revert the spray. Apply `.register-issue` **once, at the component root**, and only for the
components plan §2 actually names. Re-read plan §2 for the list — do not reconstruct it from the
current diff, which is the corrupted source.

**Watch for a Tier-F trap while reverting:** `provenance-band.tsx` and the trust/confidence
components are subject to guard §5 — "provenance never styles away." Removing the register from them
is correct, but verify `verify_required` still renders lacquer and still reads prominently
afterwards. That guard is non-negotiable.

---

## 4. Defect 3 — no route can display the work, so nothing was ever verified

Count of `.register-issue` in the **served HTML**, per route:

| Route | Count | Why |
|---|---|---|
| `/` | 0 | renders only `SiteHeader` + `TrustChip` — neither modified |
| `/theme-proof` | 0 | no modified component |
| `/plan` | 0 | **wizard state only** |
| `/kitchen-sink` | 2 | the only place it mounts |

`/plan` imports six modified components, but they mount **only after a plan job completes**. The
backend is not running — nothing listening on `:8000`, `/health` unreachable. So the page never
leaves the wizard and none of the work is reachable.

**This is why step 5 was reported complete without anyone seeing it.** A step is not complete
because the code exists.

**Fix:**
1. **Start the backend** so `/plan` reaches its results state. Without this you cannot verify step 5
   and must not claim it.
2. **Give `/kitchen-sink` a full issue-register specimen** — every §2 component in its register form,
   with realistic fixture data, on one page. That becomes the standing visual gate and removes the
   backend dependency from future review.
3. If `/plan` cannot be driven end-to-end, say so plainly in the report and mark step 5 blocked.
   Do not mark it done.

---

## 5. How to verify — run this, do not eyeball it

With the dev server up, in the browser console on a page that mounts the register:

```js
const host = document.querySelector('.register-issue');
const mk = (parent, cls) => { const d = document.createElement('div'); d.className = cls;
  parent.appendChild(d); const s = getComputedStyle(d);
  const r = { radius: s.borderRadius, font: s.fontFamily, shadow: s.boxShadow.slice(0,20) };
  d.remove(); return r; };
console.table({
  'register: rounded-sm':   mk(host, 'rounded-sm'),
  'register: rounded-md':   mk(host, 'rounded-md'),
  'register: font-display': mk(host, 'font-display'),
  'shell:    font-display': mk(document.body, 'font-display'),
});
```

**Passing means:** every `register:` radius reads `0px`, `register: font-display` reads Poiret One,
and `shell: font-display` still reads Bodoni Moda. If the shell row changes, you have broken the
shell — that is worse than the original bug.

Also confirm per route, which is the check that was missed:

```js
['/', '/plan', '/kitchen-sink'].forEach(async p =>
  console.log(p, ((await (await fetch(p)).text()).match(/register-issue/g) || []).length));
```

---

## 6. Order of work

1. Defect 1 (radius namespace) — with the `DEVIATIONS.md` row and any `CONTRACT.md` amendment.
2. Defect 2 (revert the spray, apply at roots per §2) — its own commit, no behaviour change bundled.
3. Defect 3 (kitchen-sink specimen + backend up), then re-run step 5 properly.
4. Re-run step 6 gates and the §5 verification above.

Steps 1 and 2 are separate commits. Do not bundle them.

---

## 7. Still outstanding from the original handoff

- The **DEVIATIONS rows** required by handoff §5 — the display-face swap moves a Tier-F value in
  `CONTRACT.md` line 23. Check whether these were written; if not, they must land **before** more
  changes, not after.
- The **stroke utility** from handoff §3 — verify `paint-order: stroke fill` is actually applied to
  display text in the register, and check it in **Safari and Firefox**. Chromium is confirmed good;
  the other two are unverified. If `paint-order` is ignored the stroke centres and muddies the
  counters.
- **Nothing is committed.** See handoff §11 for the CC BY-SA attribution caveat on
  `frontend/design/probes/` before any `git add -A`.

---

## 8. What not to do

- Do not restart the plan or re-derive the visual direction. Handoff §2 is settled.
- Do not edit the `@theme inline` block hunting for the bug. It is not there.
- Do not report a step complete because the code exists. It is complete when its checkpoint renders.
