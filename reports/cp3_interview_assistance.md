# CP3 — bounded interview assistance

**Status:** ACCEPTANCE PENDING
**Date:** 2026-10-11
**Branch:** `codex/cp3-interview-assistance`
**Base:** `eccb19885557001fec7a87d5b459998dda646e57` — CP2/Japan PR #13 merge

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

## Development evidence so far

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
- Final browser rerun and committed clean-tree gate remain pending.

## Review/verification corrections

The first full browser run completed **457 passed, 74 skipped, 1 failed**. The sole failure was
`f1-gate.spec.ts` → `Poiret One applied on display headings` in Chromium: a bare `h1.first()`
read an outgoing Proof node during its tab unmount and returned an empty computed font family.
The test now targets the selected UI specimen and polls the same expected Poiret font. Its
four-project focused rerun passed **4/4**; no product typography, retry or skip was changed.
The complete 532-case browser rerun remains pending. Its existing skips are project-specific
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
