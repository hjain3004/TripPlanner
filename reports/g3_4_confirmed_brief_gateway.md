# G3.4 — Confirmed-brief gateway integration

**Status: ACCEPTANCE PENDING**

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
