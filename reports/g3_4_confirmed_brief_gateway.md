# G3.4 — Confirmed-brief gateway integration

**Status: COMPLETE** (acceptance closed 2026-10-16 in the integrated tree; the original
2026-10-11 ACCEPTANCE PENDING record is preserved below, followed by the
"Acceptance closure" section)

**Branch:** `codex/g3-4-confirmed-brief-gateway`  
**Reviewed source:** `a24f557b1fc8c6cb847a7b0abb9d0116a461a8a9`  
**Implementation commits:** `cead06a`, `4ccc1c5`, `92390b1`, `d1b77b5`

## Scope delivered

- Canonical deterministic confirmed-input serialization and validation retain the existing
  intake path and reject contradictions before inventory search.
- The confirmed path uses a profile-eligible, sample-default inventory service, bounded fallback,
  explicit price-scope validation, freshness revalidation, and deterministic costing. Sample seed
  semantics and existing award/reference-only behavior are unchanged.
- Confirmation creates an authenticated, owner/session-bound job context. Legacy unowned reads
  remain compatible, while confirmed jobs require the owning session/user on interaction routes.
- Typed itinerary edits preserve admitted inventory costs without provider or LLM calls. Prose
  refresh uses only the existing explainer and the same owner-scoped context.
- OpenAPI, generated client, runtime validation, MSW fixture, and resumable results UI ship
  together. Public evidence exposes safe links and honest fixture/estimated provenance.

## Safety and limitations

Live Gondola structured responses remain unverified. No Gondola transport, OAuth, keychain,
credential, paid service, booking, transfer, crawling, or runtime LLM call was activated.
Product runtime construction remains sample-only even when historical live flags are present.
The UI fixture is explicitly synthetic/sample evidence, not a claim of live provider data.
Regional ignored catalog artifacts were unavailable in this isolated checkout and were not
fabricated. Catalog-dependent baseline tests therefore remain an acceptance blocker until the
approved local seed artifacts are provisioned.

## Review

An independent whole-branch review was obtained. It found three Critical and five Important
issues in the initial implementation. Verified findings were fixed with regression coverage:
admitted quote/cost alignment, multi-room sample rejection, prose-refresh import wiring, error
redaction, public-link sanitization, fallback dimension checks, critic-loop freshness, and typed
edit payloads. The plan's exact six named test modules were not all created; behavior is covered
by the focused G3.4 boundary/parity and existing CP2/CP3 suites.

## Verification ledger

*Historical record of the original isolated G3.4 branch (2026-10-11). It is preserved
unchanged in substance; its "ACCEPTANCE PENDING" conclusion is superseded by the
"Acceptance closure" section at the end of this report.*

The final exact-tree gate is intentionally not claimed because it fails at the pre-existing
regional-catalog fixture boundary. Exact results on the committed tree:

- `make seed PY=.venv/bin/python`: passed; 42 rows seeded.
- Full backend pytest: **1283 passed, 8 skipped, 19 failed**. All 19 failures are regional
  catalog retrieval/recompute assertions; two directly report missing
  `catalogs/active_lon-core.json`, and the remaining failures observe absent regional artifacts.
- Strict mypy: **156 source files**, clean. Zero-tolerance backend Ruff: clean. Contract one-PR
  test: **1 passed**. `AGENTS.md`/`CLAUDE.md` byte-identical and committed tree clean.
- Frontend TypeScript: clean; Vitest: **163 passed across 10 files**; ESLint: 0 errors (14
  pre-existing warnings); token lint: 0 violations; emitted-class lint: 0 dead classes; webpack
  production build: passed.
- Browser suite with live tests disabled: **458 passed, 74 skipped** across 532 tests. Generated
  captures were saved under `/private/tmp/g34-browser-captures`; tracked visual baselines were
  restored unchanged.
- Repeated OpenAPI/client generation: **byte-stable**.

The authoritative `make gate` was run on the clean committed tree and failed fast at the same
19 catalog-dependent tests. No catalog data was fabricated and no gate was narrowed or
suppressed; the report therefore remains **ACCEPTANCE PENDING**.


## Acceptance closure (2026-10-16)

This section closes the single acceptance blocker recorded above. It is **acceptance closure only**: no G3.4,
CP3, FI1 or CP4 implementation was started, and no application code, test, OpenAPI file, generated client,
frontend file, spec, seed, golden or Tier-F arithmetic was changed to achieve it.

**How G3.4 reached the integration tree.** G3.4 (`5ffbbe8`) and CP3 (`a24f557`) arrived only through the
stacked `codex/g3-5-gondola-contract-closure` branch (G3.5 is built on G3.4, which is built on CP3); both are
ancestors of G3.5 `fae3915` and are not ancestors of the G4 or FI0 branches. They entered the integration branch
`codex/integrate-fi0-g3-5-g4` through the G3.5 merge commit `e2f8d18`. No separate G3.4 or CP3 branch tip was merged.

**The original blocker.** The only remaining acceptance blocker was the 19 catalog-dependent backend
failures (1283 passed, 8 skipped, 19 failed), caused by the ignored regional catalog artifacts being unavailable
in the isolated checkout. That account stands as written above.

**What changed, and what did not.**

- No catalog was fabricated, generated or committed. The approved ignored catalog artifacts
  (`backend/catalogs/active_*.json`, 12 files for the SIN, BOM, DXB, NYC, LON and PAR corridors) were later
  provisioned from the user's trusted local copy into the integration worktree; they remain git-ignored and
  `git ls-files backend/catalogs` lists nothing.
- With the catalogs available, the previously blocked regional-catalog assertions pass in the integrated tree. The
  complete backend suite there is **1709 passed, 1 skipped, 0 failed** (the original branch showed 8 skipped and
  19 failed). The focused carried CP3/G3.4 suite (`test_cp3_api.py`, `test_cp3_assistant.py`,
  `test_g3_4_boundaries.py`) is **62 passed**, re-run during this closure.
- The exact integrated committed tree passed `make gate` (pytest, strict mypy including `ingestion/`, Ruff,
  `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`, `GATE PASSED`) at `a76105a` and again at
  `2f34d53`, as recorded in `reports/integration_fi0_g3_5_g4.md`; the closing commit of this documentation
  change was gated again (see that report).
- Frontend, browser and OpenAPI evidence remains valid because those trees did not change: `frontend/` and
  `contract/openapi.json` are byte-identical between the G3.4 HEAD `5ffbbe8`, the G3.5 HEAD
  `fae391582211d0c8c74ea24be71ee0976eb0ad9b` and the integrated tree. The recorded results therefore apply
  unchanged: TypeScript clean, production build passed, Vitest **163 passed across 10 files**, browser suite
  **458 passed, 74 skipped** across 532 tests (run with normal live tests disabled; the skips are the
  pre-existing ones recorded in the CP3 and G3.5 reports), and repeated OpenAPI/client generation **byte-stable**. They were not re-executed in this closure task.

**Still true.** Live Gondola structured responses remain unverified; product runtime construction stays
sample-only; no Gondola transport, OAuth flow, credential, paid service, booking, transfer, crawling or runtime LLM
call was activated by this closure.
