# Milestone Report: Phase I8A / I8A.1 / I8A.2 / I8A.2.1 — Offline-First Tripadvisor Terra Adapter

**Status:** OFFLINE DEVELOPMENT COMPLETE — LIVE ACTIVATION PENDING
**Date:** 2026-08-17
**Branch:** `feat/i8a-tripadvisor-offline-adapter`
**Final backend baseline:** 592 tests passing, strict mypy clean across 92 source files, ruff clean across `agents/`, `gateway/`, and `evals/`.
**Live smoke test:** Not run. No credentials, billing setup, live requests, public deployment, G1, or I8B work were performed.

---

## 1. Executive Summary

Phase I8A through I8A.2.1 implements an offline-first Tripadvisor Terra place adapter behind `backend/gateway/`, with sanitized fixture replay, strict normalized place evidence, fail-soft orchestration, provider diagnostics, a persistent entity ledger, and disabled-by-default provider registry wiring.

The runtime transport remains offline fixture replay unless a future human-approved live activation completes the account, billing, zero-spend, schema, and terms checklist. Tripadvisor is not activated merely because an MCP server, environment variable, package, or generated client exists.

---

## 2. Student / Non-Commercial Terms and Licence Record

- Project profile: `student_noncommercial`.
- Out-of-pocket ceiling: **USD 0**.
- Tripadvisor free allowance is treated as a one-time lifetime allowance, not a monthly reset.
- Internal safety ceiling: **900 billable entities**, leaving a safety margin below the referenced 1,000 lifetime free allowance.
- Licence ID used in normalized evidence: `tripadvisor-discover`.
- Official live terms, rate limits, attribution, caching rights, and billing controls must be rechecked before any live activation. The current work does not rely on billable live data.

---

## 3. Provider / Server Owner and Fixed Endpoint

- Provider: Tripadvisor Terra.
- Developer documentation/MCP reference endpoint: `https://docs.terra.tripadvisor.com/mcp`.
- Runtime adapter owner in TripPlanner: `backend/gateway/places/adapters/tripadvisor/`.
- Current live transport implementation is a disabled structural MCP transport with static tool names. REST remains preferred for future runtime activation unless MCP schemas, tool lists, budgets, response limits, and non-LLM invocation can be proven deterministic.
- No arbitrary Tripadvisor URLs are accepted or constructed.

---

## 4. Credential Policy

- No credential was configured or used.
- Live transport reads only server-side environment variable names; no secret values are committed.
- A credential value must never be placed in frontend code, generated clients, docs, fixtures, `.claude/launch.json`, URLs, or logs.
- Environment variables alone do not enable Tripadvisor. Registry activation and a trusted ledger are still required.
- `PlaceGatewayError` redacts API keys, bearer tokens, auth headers, and known env-key values before storing `str(exc)`, `repr(exc)`, or `args`.

---

## 5. Data Sent to Tripadvisor

Current implementation sends no live data to Tripadvisor.

The first future live slice, if activated, is restricted to bounded factual place enrichment:

- text query;
- destination/city constraint;
- optional category;
- bounded result limit.

Traveler names, emails, payment/card details, loyalty credentials, free-form private preferences, booking requests, and arbitrary URLs are out of scope.

---

## 6. Retention and Caching Restrictions

- Raw Tripadvisor responses are not persisted.
- Fixture JSON is sanitized and treated as synthetic/offline replay.
- Fixture envelope metadata is outside the provider wire schema under `_metadata`.
- Until current contractual permission is documented, retain only normalized TripPlanner provenance and external IDs where permitted.
- Reviews, photos, descriptions from live responses, feeds, and scraped consumer-page content remain disabled.
- Tripadvisor content is not copied into the financial knowledge base.

---

## 7. Attribution Requirements

Normalized claims include:

- `source_id="tripadvisor_terra"`;
- `licence_id="tripadvisor-discover"`;
- source URL when available;
- attribution text requiring Tripadvisor acknowledgement/link-back.

Frontend attribution UX changes are not included in this branch because the public API contract did not change for I8A.2.1.

---

## 8. Allowed Tools / Endpoints

Current structural allowlist:

- `search_locations`
- `get_location_details`
- `get_catalog_location`

Runtime behavior remains disabled by default. The only exercised adapter path in normal tests is offline fixture replay.

---

## 9. Forbidden Tools / Endpoints

The following remain out of scope and disabled:

- reviews;
- photos;
- Agentic Search;
- feed downloads;
- allowlist writes;
- hotel prices;
- bookings/reservations;
- arbitrary Tripadvisor URLs;
- consumer-page scraping;
- model training/fine-tuning;
- browser/frontend Tripadvisor calls;
- live smoke tests without explicit human approval.

---

## 10. Entity Accounting and Ambiguous-Failure Policy

`TripadvisorEntityLedger` enforces:

- lifetime ceiling: 900 entities;
- explicit persistent SQLite path for live billable transport;
- `is_billable=True` required for live transport;
- no in-memory live ledger;
- atomic `BEGIN IMMEDIATE` reservation before outbound calls;
- reconciliation after response;
- full exposure tracking when actual response count exceeds reservation (`895 + 10 = 905`, not clamped);
- future reservations fail after exhaustion/overage;
- ambiguous post-dispatch failures conservatively settle the full reservation as consumed.

Registry quota eligibility now accepts only a real persistent billable `TripadvisorEntityLedger` through a typed quota source. Fake `get_status()` objects, non-billable ledgers, and in-memory ledgers report zero Tripadvisor quota.

---

## 11. Fixture Provenance

Fixture evidence is not live provider verification.

- Fixture metadata accepts only `cached`, `estimated`, `stale`, and `verify_required`.
- Fixture JSON with `_metadata.status="live"` is rejected as `invalid_response`.
- A buggy non-live transport returning `last_evidence_status="live"` fails closed at the normalizer boundary.
- Fixture claims use `verified_by="fixture:tripadvisor_synthetic"`.
- `retrieved_at` may use fixture capture/construction time.
- `last_verified` represents TripPlanner fixture review/construction time, not provider freshness.
- `needs_verification=True` remains mandatory for fixture replay.
- Missing coordinates remain absent/`None`; no `0.0, 0.0` is manufactured.

---

## 12. Prompt-Injection Defence in Depth

Provider text is treated as untrusted data, never instructions.

Controls include:

- provider text sanitization for obvious prompt-injection phrases and control characters;
- strict normalized field allowlist;
- no raw provider object escaping the adapter;
- no raw provider tools exposed to the LLM;
- no dynamic provider/MCP discovery;
- fail-soft diagnostics rather than model-visible stack traces.

Regex sanitization is only one layer; the primary control is typed gateway isolation and non-instruction treatment of provider content.

---

## 13. Runtime Provider Selection

`POST /places/search` now uses an explicit provider resolver dependency:

```text
POST /places/search
  -> provider resolver dependency
  -> provider registry eligibility
  -> optional typed provider adapter
  -> search_catalog_places(...)
  -> local fallback + safe diagnostics
```

Default runtime behavior:

- provider map is empty;
- `tripadvisor_terra.enabled=False`;
- no Tripadvisor adapter is instantiated;
- no environment variable can activate Tripadvisor;
- local snapshot/KB search remains the normal path.

Tests override the resolver explicitly to exercise fixture adapter behavior through the real HTTP endpoint.

---

## 14. API Generation Reproducibility

Generated frontend API files now live under:

`frontend/src/lib/api/generated/`

Hand-maintained files stay outside the generated directory:

- `frontend/src/lib/api/index.ts`
- `frontend/src/lib/api/client-config.ts`
- `frontend/src/lib/api/schemas.ts`

Generation command:

```bash
cd frontend
npm run gen:api
```

Verified:

- running generation twice preserves wrapper checksums;
- generated output checksums remain stable between runs;
- `PlaceProviderDiagnostic` remains generated and exported through the stable facade;
- `searchPlacesPlacesSearchPost` remains generated and exported through the stable facade.

---

## 15. Acceptance Findings Closed

| Finding | Resolution | Pinning tests/checks |
|---|---|---|
| Non-live fixtures can emit live evidence | Removed live fixture status; reject live fixture metadata; enforce normalizer invariant | `test_fixture_metadata_rejects_live_status`, `test_non_live_transport_claiming_live_status_fails_closed` |
| Registry quota stale/fake | Typed quota source, real persistent billable ledger required, dynamic refresh on `get_entry`/selection/manifest | `test_provider_registry_same_instance_refreshes_900_to_800`, `test_provider_registry_rejects_fake_ledger_quota` |
| Fixture capture presented as provider verification | Added evidence context and honest fixture verifier identity | `test_fixture_claims_use_fixture_review_provenance`, `test_live_normalizer_path_uses_provider_identity_not_fixture_identity` |
| API provider selection missing | Added resolver dependency and test-only fixture override path | `test_search_places_api_test_resolver_invokes_fixture_adapter_through_registry` |
| API generation destructive | Generated output isolated under `generated/`; stable facade preserved | wrapper checksum and double-generation check |
| Documentation stale | Reconciled plans/report and updated acceptance status | this report and I8A plan files |

---

## 16. Verification Evidence

Pre-edit baseline:

```text
backend pytest: 571 passed, 4 warnings
strict mypy: Success, 92 source files
ruff: All checks passed
frontend TypeScript: passed
```

Focused acceptance tests:

```text
cd backend
.venv/bin/pytest evals/test_tripadvisor_adapter.py evals/test_places_search.py -q
80 passed, 1 warning
```

Full backend gate:

```text
cd backend
.venv/bin/pytest -q
592 passed, 4 warnings

.venv/bin/mypy --strict core/ agents/ api/ gateway/
Success: no issues found in 92 source files

.venv/bin/ruff check agents/ gateway/ evals/
All checks passed
```

Frontend gate:

```text
cd frontend
npm run gen:api
npm run gen:api
npx tsc --noEmit
npm run lint
node scripts/token-lint.mjs
```

Observed frontend results:

- generation succeeded twice into `src/lib/api/generated`;
- wrapper checksums unchanged across generation;
- TypeScript passed;
- ESLint exited successfully with 0 errors and existing warnings only;
- token lint passed with 0 violations.

Additional checks:

```text
cmp AGENTS.md CLAUDE.md
git diff --exit-code -- backend/evals/golden/
rg "from gateway|import gateway" backend/core -n
```

Results:

- `AGENTS.md` and `CLAUDE.md` remained byte-identical at check time;
- no golden fixture diff;
- no `backend/core/` imports of `gateway`.

Targeted secret/config scan found only environment-variable names and synthetic test strings; no real Tripadvisor credential value was present.

---

## 17. Activation Checklist Still Required

Live Tripadvisor remains blocked until all of the following are true:

- human explicitly approves live activation;
- dedicated server-only API key exists;
- account dashboard mechanically prevents positive spend/overage;
- exact current Tripadvisor terms, attribution, cache/retention, rate-limit, and billing rules are recorded;
- live schema/tool behavior is validated with sanitized metadata only;
- persistent billable ledger path is configured;
- kill switch is configured and tested;
- live smoke test is explicitly approved and capped at no more than 3 returned entities;
- no frontend/browser access to the credential exists.

---

## 18. Known Limitations

- Live provider verification is unimplemented and pending schema/account validation.
- Tripadvisor runtime adapter remains disabled.
- REST-vs-MCP runtime transport remains a future activation decision; current live MCP transport is structural and disabled.
- Reviews/photos/feeds/Agentic Search/allowlist writes/hotel pricing/bookings remain out of scope.
- Local fixture replay is useful for adapter behavior, not evidence freshness.
- Regex sanitization is not a complete prompt-injection defence by itself.

---

## 19. Exact Git Status at Report Update

The working tree is intentionally dirty and contains preserved F5.1, I8A, I8A.1, I8A.2, and I8A.2.1 work. Per the prompt, no reset, clean, checkout, push, merge, PR, or misleading mixed commit was performed.

Final `git status --short` captured after final verification:

```text
 M AGENTS.md
 M CLAUDE.md
 M DEVIATIONS.md
 M backend/agents/explainer.py
 M backend/agents/models.py
 M backend/agents/recompute.py
 M backend/agents/retrieval.py
 M backend/api/main.py
 M backend/core/itinerary/compose.py
 M backend/core/itinerary/edits.py
 M backend/core/models.py
 M backend/core/trip_models.py
 M backend/evals/test_itinerary_edits.py
 M backend/gateway/places/contracts.py
 M backend/gateway/places/registry.py
 M contract/openapi.json
 M docs/superpowers/plans/2026-08-09-tripadvisor-terra-integration.md
 M frontend/eslint.config.mjs
 M frontend/package.json
 M frontend/src/app/plan/page.tsx
 M frontend/src/components/product/itinerary-timeline.tsx
 M frontend/src/components/product/payment-strategy-card.tsx
 M frontend/src/components/product/transfer-plan-panel.tsx
 M frontend/src/components/product/trip-map.tsx
 M frontend/src/components/product/verdict-header.tsx
 M frontend/src/lib/api/client-config.ts
 D frontend/src/lib/api/client.gen.ts
 D frontend/src/lib/api/client/client.gen.ts
 D frontend/src/lib/api/client/index.ts
 D frontend/src/lib/api/client/types.gen.ts
 D frontend/src/lib/api/client/utils.gen.ts
 D frontend/src/lib/api/core/auth.gen.ts
 D frontend/src/lib/api/core/bodySerializer.gen.ts
 D frontend/src/lib/api/core/params.gen.ts
 D frontend/src/lib/api/core/pathSerializer.gen.ts
 D frontend/src/lib/api/core/queryKeySerializer.gen.ts
 D frontend/src/lib/api/core/serverSentEvents.gen.ts
 D frontend/src/lib/api/core/types.gen.ts
 D frontend/src/lib/api/core/utils.gen.ts
 M frontend/src/lib/api/index.ts
 M frontend/src/lib/api/schemas.ts
 D frontend/src/lib/api/sdk.gen.ts
 D frontend/src/lib/api/types.gen.ts
 M frontend/src/mocks/handlers.ts
?? backend/agents/search.py
?? backend/evals/test_places_search.py
?? backend/evals/test_tripadvisor_adapter.py
?? backend/gateway/places/adapters/tripadvisor/
?? backend/gateway/places/fixtures/tripadvisor/
?? docs/superpowers/plans/2026-08-16-f5-1-itinerary-interaction-hardening.md
?? docs/superpowers/plans/2026-08-17-itinerary-i8a-1-tripadvisor-hardening.md
?? docs/superpowers/plans/2026-08-17-itinerary-i8a-2-1-final-acceptance.md
?? docs/superpowers/plans/2026-08-17-itinerary-i8a-2-acceptance-closure.md
?? docs/superpowers/plans/2026-08-17-itinerary-i8a-tripadvisor-offline-adapter.md
?? frontend/e2e/f5-itinerary-hardening.spec.ts
?? frontend/src/components/product/activity-picker-dialog.tsx
?? frontend/src/lib/api/generated/
?? reports/f5_1_itinerary_interaction_hardening.md
?? reports/itinerary_i8a_tripadvisor_offline_adapter.md
```
