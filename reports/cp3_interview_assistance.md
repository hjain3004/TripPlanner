# CP3 — bounded interview assistance

**Status:** COMPLETE — LOCAL/OFFLINE ACCEPTANCE; LIVE ROLE NOT ACTIVATED
**Date:** 2026-10-11
**Branch:** `codex/cp3-interview-assistance`
**Base:** `eccb19885557001fec7a87d5b459998dda646e57` — CP2/Japan PR #13 merge
**Verified implementation/gate commit:** `3788458d2c638ddbb7ca2942a143b59bc235e5f0`

The report was acceptance pending while fixes were made. It is closed only after the exact
committed clean tree above passed `make gate`; subsequent closure edits are documentation-only.
The final handoff supplies the documentation commit's own SHA after its separate gate rerun,
avoiding a self-referential hash in this file.

## Implementation

- Pure strict assistance contracts in `planning/`; provider-agnostic model calls in the separate
  `agents/interview_assistant.py` role; durable reservation/result integration in `api/`.
- The eighth core answer triggers the required adaptive checkpoint. Catalog applicability,
  ranking, 8–12 decisions and a two-slot interview ceiling remain deterministic.
- Optional qualitative text produces a typed candidate. It never writes an answer, profile,
  confirmed brief, financial fact or provider action without the existing explicit user path.
- SQLite CAS commits each reservation before dispatch. Request fingerprints distinguish identical
  replay from conflicting event reuse. Spent slots survive failure, interruption and reopen.
  The 30-second recovery grace avoids cancelling an active call and never invokes it again.
- Personalized catalog wording and grounded acknowledgements render through the server contract.
  Contradictions reference exact answers and block planning until a traveler reviews/amends an
  affected answer. Standard controls remain usable in degraded mode.
- OpenAPI, generated client, MSW fixtures and UI ship together.

## Development evidence

- Fresh seeded baseline initially failed 19 catalog-dependent tests (missing ignored artifacts).
  Copying the existing local regional catalogs resolved every failure. Baseline gate:
  **1266 passed, 1 skipped**, mypy **149 files**, Ruff **6 legacy findings / ceiling 12**,
  `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`.
- Strict assistant/API tests were run red before implementation, including replay, hostile
  output, request conflicts, typed consent, two-connection concurrency and interruption recovery.
- CP3 focused tests: **59 passed**, including actual hosted timeout/429/404 no-retry dispatch,
  backtracking, cache reuse and reopened-database budget retention. The updated kernel/target-layer
  guard adds a transitive isolation proof.
- Complete backend run before the five additional dispatch/backtracking cases:
  **1321 passed, 1 skipped**. Strict mypy: **152 source files**.
- Frontend TypeScript passed; full Vitest: **163 passed across 10 files**. Complete ESLint has
  zero errors; scoped CP3 lint and token lint passed. Webpack production build passed.
- A complete backend run caught only the older package-wide I5 guard; that guard is now scoped to
  preserve the four frozen kernel callers while permitting the approved isolated CP3 role.
- Independent whole-branch review found five Important issues, no Critical issues. All five
  were fixed with regression coverage: grouped payment-number redaction, financial prose with
  number words, complete bounded input preservation, truthful failed-review status and automatic
  interrupted-interpretation recovery. No deferred minor findings were reported.
- Supplemental emitted-class gate initially produced nine false positives on selectors that
  exist in the compiled CSS. Its escaped opacity/variant parser is now repaired and proved by
  positive/negative executable tests; it reports zero dead classes without suppressions.
- Final browser rerun and committed clean-tree gate passed; exact evidence follows.

## Review/verification corrections

The first full browser run completed **457 passed, 74 skipped, 1 failed**. The sole failure was
`f1-gate.spec.ts` → `Poiret One applied on display headings` in Chromium: a bare `h1.first()`
read an outgoing Proof node during its tab unmount and returned an empty computed font family.
The test now targets the selected UI specimen and polls the same expected Poiret font. Its
four-project focused rerun passed **4/4**; no product typography, retry or skip was changed.
The complete 532-case browser rerun passed **458 tests, 74 skipped**. Its existing skips are project-specific
coverage and disabled live integration, not CP3 exemptions.

Production frontend verification uses `npm run build -- --webpack` with the existing linked
dependencies; the default Turbopack build is not claimed. The complete ESLint run has **0 errors,
14 warnings**, all outside the new CP3 implementation (one is the scanner's existing unused
helper). Contrast tests pass in the full Vitest suite. Repeated OpenAPI export and client
regeneration are byte-stable. Generated screenshot/dated contrast captures are not promoted to
committed reference baselines by this implementation.

## Role configuration and provenance

`TRIPWISE_INTERVIEW_LLM_ZERO_SPEND_CONFIRMED=1` enables only an explicitly eligible local/free-tier
configuration. `TRIPWISE_INTERVIEW_LLM_MODEL` chooses the role's single model, otherwise the
existing primary model is used. `TRIPWISE_INTERVIEW_LLM_COST_MICRO_USD` must be exactly `0`.
The role shares the existing backend endpoint/key and never creates a credential; each client
instance allows one provider request with zero automatic retries/fallback. Missing configuration,
rate limits and failed validation degrade to deterministic controls.

The committed persona corpus is **authored synthetic fixture data**, not live captured responses.
Tests record/replay those scripted responses through the existing recording/replay clients in
temporary test directories; normal session storage contains neither prompt nor raw model output.
No live LLM/provider/MCP call or credential activation was performed.

## Boundaries and remaining work

G3.4 gateway product wiring, CP4 post-plan interpretation and FI work remain separate. CP3 makes
no travel-inventory provider request before or after confirmation. Existing money arithmetic, seed/golden values,
the kernel pipeline and its four LLM call sites remain unchanged. All other worktrees, branches
and primary-checkout user files are preserved. This development branch has not been pushed or
merged.

## Final acceptance evidence

Commands were executed in this worktree, using its existing linked virtualenv/node_modules and
a worktree-independent mypy cache. No external service was called by acceptance tests.

| Check | Result |
|---|---|
| `make seed PY=.venv/bin/python` | 42 knowledge-base seed rows; passed |
| complete `.venv/bin/pytest -q` after seeding | **1326 passed, 1 skipped**, 3 existing OR-Tools deprecation warnings |
| focused CP3 assistant/API + Kernel isolation | **61 passed** (39 assistant, 20 API, 2 Kernel guards) |
| strict mypy, every source package | **152 source files**, no issues |
| zero-tolerance Ruff + touched API files | all checks passed |
| legacy core/API ratchet | **6 / ceiling 12** in the unchanged gate; direct Ruff also reports one existing UP017, 7 total |
| `npx tsc --noEmit` | passed |
| complete `npx vitest run` | **163 passed, 10 files** |
| complete `npm run lint` | **0 errors, 14 existing warnings** |
| semantic-token / emitted-class checks | zero violations / zero dead classes |
| `npm run build -- --webpack` | production build passed |
| complete Playwright, all four projects, two workers, zero retries | **458 passed, 74 skipped, 0 failed** (532 cases) |
| CP3 browser subset of that complete run | **72 passed**, no skips |
| repeated OpenAPI export and `npm run gen:api` | byte-stable |
| committed clean-tree `make gate` | **GATE PASSED** |

Browser command: `npx playwright test --config=e2e/playwright.config.ts --workers=2 --reporter=line`.
The local production server was stopped afterward. Generated screenshot/contrast captures were
preserved at `/private/tmp/tripplanner-cp3-captures.DuJvnm`; only this run's accidental baseline
writes were restored. No reference-baseline update is included in CP3.

Verified committed-tree gate (`MYPY_CACHE_DIR=/private/tmp/tripplanner-cp3-mypy-cache make gate`):

```text
--- pytest (full suite) ---
cd backend && .venv/bin/pytest -q
1326 passed, 1 skipped, 3 warnings in 77.81s (0:01:17)
--- mypy --strict (every source package) ---
cd backend && .venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/
Success: no issues found in 152 source files
--- ruff (zero-tolerance scope) ---
cd backend && .venv/bin/ruff check accounts/ planning/ agents/ gateway/ evals/
All checks passed!
--- ruff (core/ + api/: legacy debt, ratcheted, must not grow) ---
core/ + api/ ruff findings: 6 (ceiling 12)
  NOTE: these are pre-existing M1/M1b findings. Two are B905 (zip without
  strict=) in core/transfer/pathfinder.py — Tier-F code where strict=True
  changes truncation behavior. Clearing them is its own task with its own
  golden-test run, not a drive-by fix. Lower this ceiling when you do it.
--- frozen artifacts ---
GOLDENS_OK
CONTRACT_OK (unchanged, or changed with codegen and fixtures)
BRIEFS_IDENTICAL
--- working tree ---
TREE_CLEAN

================ GATE PASSED ================
```

The full raw gate output (including progress and warning details) is in
`/private/tmp/tripplanner-cp3-gate-acceptance.log`. The final documentation-tree rerun is saved
separately to `/private/tmp/tripplanner-cp3-gate-final.log` and its SHA is reported in the handoff.
No environment exemption is used: missing catalogs, the font race, and scanner false positives
were root-caused and resolved, not waived.

## Rulings and tradeoffs

1. Permit only the specified interview role outside the Kernel caller set, with a transitive
   four-caller proof. Risk: missed coupling; the new isolation test covers it.
2. Reserve calls durably before dispatch and retain interrupted slots; cache identical reviews,
   fall back on changed reviews. Cost: conservative exhaustion rather than extra hidden calls.
3. Interpret qualitative fields only and require explicit candidate saving. Cost: numeric or
   rejected preferences require typed entry rather than guessed hard facts.
4. Keep hosted assistance off until zero-spend eligibility is confirmed; use one model/attempt
   and honestly authored synthetic fixtures. Cost: default operation has less personalization.
5. Provision existing ignored catalogs locally instead of changing expected values. Risk:
   non-portable local data; the seeded baseline and complete suites prove this worktree.
6. Verify webpack with linked dependencies without changing production build configuration.
   Limitation: the default Turbopack dependency-root path is not verified here.
7. Wait for the actual selected specimen before checking the unchanged display font. Risk:
   selecting a wrong specimen; the heading is unique and all four projects pass.
8. Normalize emitted selector escapes rather than suppressing valid utility reports. Risk:
   weakening the missing-class guard; the real absent-utility negative fixture still fails.

Deferred review minors: none. Deferred product work remains G3.4, CP4, FI1+ and live activation.
`docs/specs/`, the approved conversational design, goldens, all `backend/core/` (including seeds
and Tier-F arithmetic), Kernel pipeline/call sites, themes, dependencies, and visual references
are unchanged against `eccb198`. OpenAPI/frontend changes are intentional CP3 implementation,
not claimed unchanged. Other worktrees and branches were read-only inspected and preserved;
their existing dirty/untracked files were left alone.
