# Audit remediation execution report

Date: 2026-08-18

Authoritative inputs:

- `reports/audit_consensus.md`
- `reports/audit_findings_codex.md`
- `reports/audit_findings_claude.md`

Reference-only plan:

- `docs/superpowers/plans/2026-08-16-r1-interest-aware-retrieval.md`

Execution plan:

- `docs/superpowers/plans/2026-08-18-audit-remediation.md`

## Summary

Implemented the consensus audit remediation without activating paid providers, runtime crawling, Tripadvisor live transport, provider MCP runtime transport, new accounts/deployment/share URL work, or Tier-F money/golden changes.

Fixed areas:

1. Truthful live LLM/provider failure handling.
2. Canonical travel-interest/category vocabulary across interests, picker filters, provider categories and spend categories.
3. Cache-backed real-catalog recompute path.
4. Valid empty-wallet behavior.
5. Regional location semantics and exact venue search ranking.

## Implemented behavior

### A. Truthful live LLM operation

- `HostedFreeTier` now supports:
  - `TRIPWISE_LLM_MODEL`;
  - optional `TRIPWISE_LLM_FALLBACK_MODELS`;
  - optional ordered `TRIPWISE_LLM_MODELS`;
  - one bounded provider-call counter across primary/fallback attempts;
  - redaction of provider response bodies containing bearer/API-key material.
- Intake now distinguishes:
  - hosted provider/model/network failures → `PipelineStatus.ERROR`;
  - schema-repair failures from scripted/model output → clarification;
  - missing replay fixtures → clarification/offline-regression workflow.

### B. Canonical travel taxonomy

Added `backend/core/travel_taxonomy.py` as the single vocabulary mapping layer.

Canonical category mappings include:

- `food`, `restaurant`, `cafe`, `food_court` → dining;
- `museum`, `gallery`, `culture` → culture;
- `park`, `garden`, `nature` → nature;
- `attraction`, `landmark`, `architecture`, `palace` → landmark/attractions.

Raw provider category strings remain in place-search results and evidence. The taxonomy is used only for ranking/filter/spend classification boundaries.

### C. Fast real-catalog recompute

- Added a bounded in-process snapshot cache in `SnapshotPlaceAdapter`, keyed by absolute path, mtime and size.
- Repeated `get_catalog_poi()` calls against the same active catalog now share one parsed snapshot.
- Warm real-catalog recompute benchmark result from product probe: `111.63 ms`.

### D. Empty-wallet behavior

- Empty or invalid-card wallets now produce explicit `cash_only` assignments.
- Cash-only output has zero offers, zero card rewards, zero inferred card benefits and a visible optimizer assumption.
- Existing non-empty wallet optimizer golden behavior remains unchanged.

### E. Regional area semantics and exact search

- Regional catalog POIs with coordinates now receive deterministic `geo-cell:<iata>:<lat>:<lon>` area IDs.
- Generated geo-cell areas are marked `needs_verification=True` and are explicitly coordinate buckets, not invented neighborhoods.
- Exact search now ranks by:
  - category compatibility;
  - curated seed priority;
  - geographic plausibility;
  - name match quality;
  - deterministic tie-breaks.

## Product-path probe output

Real-catalog retrieval across all six destinations produced different top candidates for `food` vs `culture` interests:

- SIN: different = true.
- BOM: different = true.
- DXB: different = true.
- NYC: different = true.
- LON: different = true.
- PAR: different = true.

Picker-visible London filters returned real matching venues:

- `food`: food court / restaurant results.
- `culture`: museum results.
- `nature`: park results.
- `attractions`: attraction results.

Exact search probes:

- `LON / Buckingham Palace` first result: `Buckingham Palace`, `attraction`, `51.507191160113116, -0.1285437347862065`.
- `NYC / Metropolitan Museum` first result: `Metropolitan Museum`, `museum`, `40.79431193891246, -73.94302017001124`.

Empty-wallet probe:

- status `ok`;
- assignment card IDs: `cash_only`;
- rewards value: `0`.

Live LLM smoke:

- Previous checkpoint: not run because the existing ignored `backend/.env` free-tier LLM credentials had not been sourced in that session.

## Post-remediation live LLM smoke

Date: 2026-08-19.

Scope:

- One bounded live product smoke through the real FastAPI app and `/plan` endpoint.
- Existing ignored `backend/.env` free-tier LLM credentials were sourced locally; no credential values, bearer tokens, request headers, raw provider responses, or prompts were written to this report.
- No Tripadvisor live transport, paid travel provider, booking action, runtime crawling, consumer-page scraping, MCP runtime activation, or new provider credential/account activation was used.

Sanitized configuration:

- Provider host: `api.groq.com`.
- `.env` configured primary model: `llama-3.3-70b-versatile`.
- Model preflight result: configured primary was not listed by the provider.
- Command-local smoke model: `openai/gpt-oss-20b`.
- Command-local fallback model: `qwen/qwen3.6-27b`.
- Provider-call ceiling: `TRIPWISE_LLM_MAX_CALLS=6`.

Bounded command shape:

```bash
cd backend
set -a
source .env
set +a
export TRIPWISE_LLM_MODEL='openai/gpt-oss-20b'
export TRIPWISE_LLM_FALLBACK_MODELS='qwen/qwen3.6-27b'
export TRIPWISE_LLM_MAX_CALLS=6
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
```

Request shape:

- Endpoint: `POST /plan`.
- Scenario: four-night Delhi to Singapore trip, 2026-09-01 to 2026-09-05, two travelers, HDFC Infinia card, balanced food/nature focus.
- Job ID: `5e6b2b54bdde435db838dd20a54298a8`.

Terminal result:

- Status: `complete`.
- Final stage: `explaining`.
- Elapsed wall time reported by poller: `70.1s`.
- `has_report`: `true`.
- `unresolved`: `null`.
- `error`: `null`.

Trace metadata:

- Trace file: `00a176a0d2534e739f4b6b22c9abdb63.json`.
- Stage count: `7` (`intake`, `retrieval`, `planner`, `estimator`, `optimizer`, `critic`, `explainer`).
- Planner metadata: `repair_attempted=True`, `used_fallback=True`.
- Interpretation: the real LLM path completed and produced a report payload, but planner tool-calling quality still required the deterministic planner fallback. This is accepted product behavior for the current free-tier smoke; it is not evidence that hosted weak models satisfy the full discovery-quality target.

Safety findings:

- Secret handling: server logs and command output did not include API keys, bearer headers, or raw provider bodies.
- Provider/model failure classification: the retired configured primary was detected during model-list preflight and avoided with command-local model selection; no runtime provider error occurred during the product smoke.
- Fallback behavior: deterministic planner fallback was used after repair, and the pipeline still completed with `has_report=true`.
- Zero paid provider activation: preserved. The smoke used only existing free-tier LLM credentials and local/offline travel data.

## Verification

Backend:

- `cd backend && .venv/bin/pytest -q` → `617 passed, 4 warnings in 70.64s`.
- `cd backend && .venv/bin/mypy --strict core/ agents/ api/ gateway/` → success, `93 source files`.
- `cd backend && .venv/bin/ruff check agents/ core/ gateway/ evals/test_*audit* evals/test_recompute_endpoint.py evals/test_optimizer.py evals/test_hosted_llm_client.py evals/test_m2_pipeline.py evals/test_places_search.py` → pass.

Frontend:

- `cd frontend && npx tsc --noEmit` → pass.
- `cd frontend && node scripts/token-lint.mjs` → `0 violations across 12 rules`.
- `cd frontend && npm run lint` → pass with 14 pre-existing warnings.
- `cd frontend && npx vitest run tests/contrast.test.ts tests/contract.test.ts` → `119 passed`.

Contract/codegen:

- `cd frontend && npm run gen:api` → generated 4 files.
- `git diff --exit-code -- contract/openapi.json frontend/src/lib/api/generated` → no drift.

Final clean-tree gate:

- `make gate` → passed:
  - backend suite: `617 passed, 4 warnings`;
  - strict mypy: success across `93 source files`;
  - ruff: pass;
  - golden artifacts unchanged;
  - contract one-PR check pass;
  - `AGENTS.md`/`CLAUDE.md` identical;
  - working tree clean.

## Remaining limitations

- Tripadvisor live transport remains disabled pending billing/account activation.
- The bounded live LLM smoke completed, but planner tool-calling still fell back deterministically under the tested free-tier model.
- Active static catalogs remain single-file compacted artifacts even though tiled spatial format exists.
