# TripPlanner F4 — continuation prompt for opencode

Copy everything below this line into opencode. F1, F2, and F3 are complete and
gate-verified for real. You are starting F4, the final frontend milestone:
performance, one live frontend↔backend integration run, and polish.

## 0. Read this section first — it is not optional, and it changes how you work

Every prior milestone on this project shipped a gate that initially reported
"passing" while actually verifying less than it claimed:

- F1's first contrast check computed an OKLCH lightness delta instead of a real
  WCAG contrast ratio — it could never have caught a real contrast failure.
- F1's e2e suite ran under the wrong Playwright config path, so 3 of 4 browser
  projects and most assertions silently never executed.
- F2's axe check filtered out real violations (a genuine sub-AA contrast
  failure, a heading-level skip, a missing landmark) from the results array
  before asserting it was empty.
- F3's first "no orphan numbers" test extracted numbers from the fixture
  object and asserted they weren't negative — it never rendered a page or read
  the DOM, so it could not have caught an actual invented number appearing on
  screen.

In every case, the check *existed*, had a plausible name, and *passed* — and
none of that meant the underlying property was true. A prior version of this
prompt told you "don't filter assertions to force a pass," and F3 still shipped
a vacuous check that technically wasn't filtering anything — it was just
testing the wrong thing. Telling you what not to do isn't sufficient. This
section replaces that approach with a mechanical requirement that doesn't
depend on your own judgment of whether a check is "good enough."

### The sabotage-then-verify protocol — mandatory for every check below marked 🔴

For any check whose entire purpose is to catch a specific class of violation
(money-groundedness, accessibility, reduced-motion compliance, performance
budgets), you must demonstrate — not assert, demonstrate — that it actually
catches that violation:

1. State in one sentence what property the check verifies, quoting the exact
   spec or gate requirement it comes from.
2. Write the check.
3. **Sabotage**: temporarily edit the actual application code (never the test
   itself) to introduce a real instance of the violation the check exists to
   catch — e.g., for a groundedness check, hardcode one extra number into a
   component that doesn't come from the fixture; for an accessibility check,
   temporarily strip an ARIA label or drop the contrast on a real text
   element; for a performance budget, temporarily import an unnecessary heavy
   dependency at the top level.
4. Run the check. **It must fail.** Paste the failing output. If it doesn't
   fail, the check does not verify the property — go fix the check, not the
   sabotage.
5. Revert the sabotage exactly. Run the check again. **It must pass.** Paste
   the passing output.
6. Only after both 4 and 5 are demonstrated with real pasted output does this
   check count as done. A check that skips this protocol is assumed vacuous
   until proven otherwise — by you, in your final report, not by whoever
   reviews it after you.

This protocol is expensive to skip honestly and cheap to fake by just saying
you did it — don't. The whole reason this section exists is that four previous
"I verified it, here's the passing output" reports were wrong in exactly this
way. Paste both the failing-output and passing-output for every 🔴 check.

## 1. Read first

`AGENTS.md`, `DEVIATIONS.md`, `reports/frontend_F1.md`, `reports/frontend_F2.md`,
`frontend/reports/milestone_f3.md`, `frontend/design/CONTRACT.md`,
`docs/specs/10_frontend_build_plan.md` §5's F4 gate criteria (Chrome DevTools MCP
trace, LCP/CLS/INP thresholds, Lighthouse a11y ≥ 95, bundle checks), and
`docs/specs/12_integration_contract.md` §5 (CORS/env matrix) and §7 (the "one
manual live run happens at Gate F4" line — this is what §4 below implements).

## 2. Ground rules that still apply

Frontend never computes money or points. Registry components reviewed
line-by-line before commit. Git actions that push/merge/open PRs need the human
present. No dark mode. No changes to backend Tier-F pipeline behavior. And now:
no check gets marked done without either passing the sabotage-then-verify
protocol (if it's 🔴) or being explicitly out of scope for that treatment (if
it's not marked 🔴, say so and why in your report).

## 3. Deliverables

### 3.1 Performance — lazy-loading and image/font optimization

Lazy-load GSAP and MapLibre (they should not be in the initial JS bundle for
any route except the results page, and even there, only load when the
scroll/map sections are actually reached or about to be). Optimize images
(`next/image` sizing, AVIF/WebP already required since F1 — confirm it's
actually happening, not just configured). Optimize font loading (check that
`next/font`'s automatic optimization is doing its job — no FOUT/FOIT
regressions).

**🔴 Bundle check**: assert GSAP and MapLibre are absent from the initial JS
payload of routes that don't need them (landing, wizard steps 1–4). Sabotage:
temporarily import `gsap` at the top level of a route that shouldn't have it,
confirm the bundle-size check catches the regression, revert, confirm it
passes clean.

### 3.2 Page transitions

View Transitions API as progressive enhancement (per spec 10 §2's Tier-F stack
note); Motion `AnimatePresence` remains the baseline page transition — this
should already mostly exist from F1's motion library, confirm it's applied
consistently across the now-complete route set (landing → wizard → results).

### 3.3 Performance gate (Chrome DevTools MCP)

Trace the landing page and the results page under mobile emulation. Thresholds
(spec 10 §5, Tier F, do not loosen these):

- LCP ≤ 2.5s
- CLS ≤ 0.1
- INP ≤ 200ms on interactions
- Lighthouse accessibility ≥ 95

**🔴 for the bundle-size portion specifically** (§3.1) — the LCP/CLS/INP/Lighthouse
numbers themselves are inherently real measurements from a real tool (Chrome
DevTools MCP), not something that can be quietly narrowed the way a
hand-written assertion can, so the sabotage protocol isn't required for those
specific numbers — just paste the real trace output.

### 3.4 One live integration run

Per spec 12 §8's runbook and §7's "one manual live run happens at Gate F4":
switch `NEXT_PUBLIC_API_MODE` from `mock` to `live`, point
`NEXT_PUBLIC_API_BASE_URL` at a running instance of the actual backend (not
MSW), and run one real end-to-end flow: wizard submit → real `POST /plan` →
real polling against `GET /plan/{job_id}` → real `FinalReport` rendered on the
results page, using the backend's actual sample/fixture data (not live
travel-provider data — this project has no provider gateway yet, and none is
in scope here). This is the first time in the whole frontend build that MSW is
turned off for a real run.

**🔴** This check is inherently real if you actually do it (a live HTTP round
trip either works or it doesn't) — but the failure mode to avoid is *claiming*
you ran it without actually starting both servers and completing a real
request. Paste the actual terminal output showing the backend process running,
the actual network request/response (not a mocked one), and a screenshot of
the resulting rendered page. If anything in the real response doesn't match
what the generated Zod schemas expect, that's real contract drift — fix it or
log it, don't paper over it.

### 3.5 Env matrix documentation

`frontend/README` gets the six-cell dev/preview/prod × mock/live table spec 12
§5 requires — all six cells stated explicitly, none implied.

## 4. Gate F4

Wire into the established `gate-f4`/`fe-*` Makefile pattern (root +
`frontend/Makefile`), matching `gate-f1`/`gate-f2`/`gate-f3`'s convention. Full
regression check: `make gate-f1 gate-f2 gate-f3 gate-f4` and the backend's
`make gate-m1 gate-m1b gate-m2 gate-m3` all green — this is the last frontend
milestone, so this is the moment to confirm nothing earlier regressed. Paste
the complete real output.

## 5. Skills

`ecc:react-performance` for the bundle/lazy-loading work. `ecc:frontend-a11y`
for the Lighthouse a11y gate. `superpowers:systematic-debugging` if the live
integration run surfaces a real contract mismatch — trace it to the actual
schema difference, don't patch around it blind. `superpowers:verification-before-completion`
before reporting F4 — and specifically, re-read §0 above before writing your
final report.

## 6. Explicitly out of scope

Provider gateway, adapters, crawling, any travel-provider MCP (G1+, requires an
explicit human decision this prompt doesn't grant). Dark mode. Any change to
backend Tier-F pipeline behavior or golden numbers.

## 7. Final report

Write `reports/frontend_F4.md`. For every 🔴-marked check in this prompt, include
both the sabotage-failure output and the reverted-pass output, not just the
final green run. This is the standard the last four milestones should have met
from the start.
