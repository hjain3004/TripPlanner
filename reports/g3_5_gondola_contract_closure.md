# G3.5 — Gondola response-contract closure

**Status: COMPLETE**

**Branch:** `codex/g3-5-gondola-contract-closure`  
**Reviewed base:** `5ffbbe85c0349b48098887b79e165139f08fe480`  
**Implementation commit:** `2c212db`

## Scope delivered

- Corrected the verified Gondola request argument shapes for hotel and flight calls,
  including the provider's `departure_date`, `num_passengers`, and `cabin_class` names.
- Added deterministic request builders with conservative rejection of unsupported rooms,
  children, and infants rather than silently changing provider semantics.
- Added a typed `GondolaDiscoveryEvidence` contract for the verified `{result: string}`
  provider-Markdown response. It is explicitly verify-required, not a normalized quote, and
  not costable; raw prose and provider links are not exposed through the evidence model.
- Made the native hotel/flight quote parsers reject Markdown discovery envelopes, so no
  provider prose can enter inventory selection, deterministic costing, or the Kernel.
- Added a sanitized, format-preserving replay fixture and fixture-transport support for the
  separate discovery evidence path. The fixture is synthetic and makes no live-data claim.
- Corrected the smoke/bootstrap/refresh scripts and tests to use the observed request contract
  and to report Markdown as discovery-only. No live script was run.

The sample-only runtime, four Kernel LLM roles, stage order, JSON contracts, arithmetic, seeds,
goldens, intake, and existing award/reference-only behavior are unchanged. No OpenAPI or
frontend contract changes were needed for this conservative closure.

## Safety and limitations

The verified live response is provider Markdown, not a typed inventory response. It does not
reliably provide currency, tax/fee scope, total scope, segment timing, room/cancellation
semantics, or a safe booking link. Therefore this branch deliberately does not normalize,
price, or promote it to a `FlightQuote`/`HotelQuote`. Future live activation requires a new
verified normalization contract. Gondola remains disabled by default; no live provider call,
OAuth flow, keychain access, credential activation, booking, transfer, paid service, or runtime
LLM call was made.

## Verification ledger

- `make seed PY=.venv/bin/python`: passed; 42 rows seeded.
- Focused Gondola/smoke suite: **194 passed** initially; after review fixes, the focused
  regression set passed **81 tests**.
- Full backend pytest after review fixes: **1348 passed, 1 skipped** (8 warnings from
  existing/shared cache permissions and library deprecations).
  permissions).
- Strict mypy: **158 source files**, clean. Required Ruff scopes clean.
- Frontend: TypeScript clean; Vitest **163 passed across 10 files**; ESLint 0 errors and 14
  existing warnings; token lint clean; emitted-class lint clean; webpack production build passed.
- Browser suite with normal live tests disabled: **458 passed, 74 skipped** across 532 tests.
  Generated captures were saved under `/private/tmp/g35-browser-captures`; tracked visual
  baselines were restored unchanged.
- Repeated OpenAPI/client generation: **BYTE_STABLE**.

## Independent review

The independent whole-branch review found no Critical issues and four actionable findings:

- the OAuth refresh script could treat the real Markdown envelope as a generic structured
  fixture;
- request wrappers could silently drop unadvertised application constraints;
- fixture replay did not preserve synthetic-fixture provenance; and
- an invalid discovery tool could raise an untyped `KeyError`.

All four were fixed in `23c6315` with regression coverage. Markdown is now handled as explicit
verify-required discovery in the refresh script, unsupported request dimensions fail closed,
fixture evidence carries `synthetic_fixture`, capture date, and fixture name, and invalid tools
raise a typed gateway error.

## Final acceptance

The exact committed tree passed `make gate` after the documentation closure:

- Full backend pytest: **1348 passed, 1 skipped**.
- Strict mypy: **158 source files**, clean.
- Zero-tolerance Ruff: clean; legacy core/api findings remained at the ratcheted ceiling of 6
  (ceiling 12).
- Frozen goldens: **GOLDENS_OK**.
- Contract/codegen guard: **CONTRACT_OK**.
- Brief identity: **BRIEFS_IDENTICAL**.
- Working tree: **TREE_CLEAN**.

**GATE PASSED.**

## Review

An independent whole-branch review is being obtained against the complete branch diff. Verified
Important/Critical findings, if any, will be fixed with regression coverage before the final
documentation commit and gate.
