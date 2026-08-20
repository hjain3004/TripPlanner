# Audit remediation execution plan

Date: 2026-08-18

Authoritative inputs:

- `reports/audit_consensus.md`
- `reports/audit_findings_codex.md`
- `reports/audit_findings_claude.md`

Reference only:

- `docs/superpowers/plans/2026-08-16-r1-interest-aware-retrieval.md`

Constraints:

- Preserve Tier-F money math and golden values.
- No paid services, runtime crawling, new provider activation, backend/core gateway imports, accounts, deployment, share URLs, or frontend redesign.
- Do not delete or demote curated Singapore POIs; do not remove celadon references.
- Catalog behavior tests must exercise activated representative catalogs, not mocks that bypass real data.
- Use red → green → refactor for every defect.

## Phase A — Truthful live LLM operation

- [ ] Add focused failing tests showing provider/config failures produce `PipelineStatus.ERROR`, not `needs_clarification`.
- [ ] Add focused failing tests for hosted-provider model fallback/retry behavior using a network-free transport monkeypatch.
- [ ] Add focused failing tests proving provider error messages redact request headers/API keys.
- [ ] Implement zero-cost-safe hosted model selection:
  - environment-configured ordered model list;
  - one bounded fallback to the next configured model for model-not-found style failures;
  - no fallback loop that can exceed the configured call ceiling;
  - no network calls in tests.
- [ ] Route `LLMCallError`/`LLMTimeoutError` from intake as a runtime error while preserving genuine user clarification behavior.
- [ ] Run focused LLM/intake/pipeline tests.

## Phase B — Canonical travel-interest/category vocabulary

- [ ] Add failing taxonomy tests for UI filter terms, user-interest terms, provider catalog categories, and spend category mapping.
- [ ] Add failing real-catalog retrieval probes across SIN, BOM, DXB, NYC, LON, and PAR proving different interests yield different top candidates where representative categories exist.
- [ ] Add failing picker search tests proving visible filters return real matching catalog venues and are non-vacuous.
- [ ] Add failing estimator tests proving restaurants/cafés map to `SpendCategory.DINING`, while non-food POIs remain attractions/other.
- [ ] Implement one canonical pure taxonomy module in `backend/core/` that does not import gateway.
- [ ] Apply taxonomy at ranking/filter/spend-category boundaries while preserving raw provider category strings and provenance.
- [ ] Update frontend picker filter values/labels only as required to match canonical categories; no redesign.
- [ ] Run focused taxonomy, retrieval, estimator, places search, and frontend picker tests.

## Phase C — Fast real-catalog recomputation

- [ ] Add a failing real-catalog recompute benchmark that uses activated catalogs and catalog-backed itinerary items.
- [ ] Add a focused test proving repeated catalog POI lookup does not reparse the same active catalog for every itinerary item.
- [ ] Implement bounded snapshot catalog caching keyed by path metadata.
- [ ] Ensure cache behavior remains deterministic and does not persist raw provider responses beyond existing active catalog artifacts.
- [ ] Run focused recompute and catalog-cache tests.

## Phase D — Valid empty-wallet behavior

- [ ] Add failing API/product-path tests for empty-card wallets in plan and recompute.
- [ ] Add optimizer-level tests pinning a cash-only/no-rewards result instead of a crash when the wallet has no valid cards.
- [ ] Implement explicit cash-only optimizer fallback with zero discounts, zero rewards, no fabricated card benefits, and an assumption explaining the fallback.
- [ ] Preserve existing golden optimizer behavior for non-empty wallets.
- [ ] Run focused optimizer, recompute, and API tests.

## Phase E — Regional location semantics and exact venue search

- [ ] Add failing real-catalog tests proving regional POIs no longer all map to `Unknown` area where coordinates exist.
- [ ] Add failing exact venue search tests for Buckingham Palace and the Metropolitan Museum case, checking category/geographic plausibility and no confident implausible duplicate priority.
- [ ] Implement evidence-honest deterministic geographic cell area labels for regions without curated area rows; do not invent neighborhood names.
- [ ] Implement exact-search ranking that prefers exact/near-exact name, category compatibility, geographic plausibility, and deterministic identity clustering.
- [ ] Run focused area/search tests and real-catalog probes across all six destinations.

## Documentation and verification

- [ ] Update `AGENTS.md` and `CLAUDE.md` identically with the new checkpoint.
- [ ] Add `DEVIATIONS.md` entries for conservative implementation judgments.
- [ ] Write `reports/audit_remediation_execution.md` with actual verification output and remaining gaps.
- [ ] Run final verification:
  - all new focused tests;
  - complete backend suite;
  - strict mypy;
  - ruff;
  - contract/OpenAPI drift checks;
  - frontend TypeScript/lint/token checks;
  - relevant Playwright tests for picker filtering/error states if present;
  - real-catalog retrieval probes across all six destinations;
  - real-catalog recompute benchmark;
  - empty-wallet API probe;
  - bounded live LLM smoke only if valid free credentials/models are available;
  - complete `make gate`.
- [ ] Request read-only code review with exact base and head commits.
- [ ] Address critical/important review findings before completion.
- [ ] Make clean, logically separated commits only if the working tree contains only in-scope changes and user-owned unrelated work is preserved.
