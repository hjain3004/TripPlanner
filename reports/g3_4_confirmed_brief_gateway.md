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

The final exact-tree gate is intentionally not claimed until it passes. Recorded local checks
include seed success, focused backend regression, strict mypy on changed source, frontend type/
Vitest/ESLint checks, and byte-stable OpenAPI/client regeneration. The complete backend gate is
pending because the isolated checkout lacks the ignored regional catalog artifacts required by
pre-existing catalog tests.
