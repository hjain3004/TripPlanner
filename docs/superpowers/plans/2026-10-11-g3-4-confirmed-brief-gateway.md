# G3.4 Confirmed-Brief Gateway Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Native execution with one independent whole-branch review is recommended because the interfaces are tightly coupled.

**Goal:** Make an authenticated, confirmed Trip Brief drive the existing planning pipeline through the travel gateway, with honest inventory evidence in the results workspace and preserved deterministic financial behavior.

**Architecture:** Keep the four Kernel LLM roles and their graph/contracts intact. Compile the confirmed snapshot into deterministic intake text and validated travel requests; reject an intake result that contradicts confirmed facts before searching. Use an injected, bounded travel service inside the existing costing stage, preserve the sample-price compatibility path, and expose only display-safe summaries. Default production construction is sample-only; existing Gondola fixtures exercise integration without activating its unverified live path.

**Tech Stack:** Existing Python/Pydantic/FastAPI/SQLite, travel adapters, Next.js/TypeScript, pytest, Vitest, Playwright. No new dependency, SDK, credential or service.

**Spec:** `docs/superpowers/specs/2026-08-21-conversational-trip-planning-design.md` §§4.2, 8–9, 11–15; `docs/specs/16_data_gateway_and_adapters.md` §§3–17; `docs/specs/12_integration_contract.md` §§8–9; `docs/specs/06_implementation_protocol.md` §§1, 3, 5–7.

**Starting evidence:** CP3 commit `26864ee915da2b5dd0b49ccca38e9d939eff7719`, 1326 backend tests passed / 1 skipped, strict mypy 152 files, Vitest 163 passed, complete browser suite 458 passed / 74 existing skips, exact clean-tree gate passed. These are historical baselines, not G3.4 acceptance claims.

**Status:** PLAN ONLY — awaiting review and execution-method selection. The user's “ok” authorized writing this plan, not running live acceptance or implementing an unseen plan.

## Global Constraints

- “The Kernel MVP continues to have exactly four LLM call sites: intake, planner, critic, and explainer.” Retain intake; do not introduce a typed bypass, another role, changed stage order or larger retry/call ceiling.
- “LLMs and the frontend still never compute money or points.” Preserve integer money, all `backend/core/`, seeds and golden expectations. New source amounts are inputs to existing deterministic conversion/optimization, never financial KB writes.
- “All provider I/O goes through the reviewed, profile-eligible allowlist in 09/16; `backend/core/` never imports it.” Place and travel registries stay distinct.
- “The active provider profile is `student_noncommercial`” with a hard “USD 0 out-of-pocket” ceiling. Positive/unknown cost fails closed.
- “Normal CI has no external network.” No OAuth/keychain access, live LLM/provider calls, MCP discovery, bookings, transfers, crawling or public deployment in this implementation.
- “Schema, OpenAPI snapshot, generated frontend types, runtime validation, MSW fixtures, frontend consumers, and contract tests ship together.” Public changes belong in one coordinated commit/PR.
- Quotes are comparable only when traveler mix, dates, trip type, cabin/room, currency and price scope align. Do not treat observations as quotes or cash prices as award availability.
- Do not modify authoritative specs. CP4 intent routing/replanning, FI work, new providers, new account acquisition, durable job infrastructure and live activation are excluded.
- The historical G3 plan's no-pipeline-edit rule scoped its adapter-only work. This new, reviewed product-integration plan permits wiring within existing stages, not a frozen graph or arithmetic change; log that distinction.

## Review Focus

1. A confirmed wallet or numeric trip fact differs from LLM intake: reject the mismatch before provider selection, never plan using invented facts (Task 1).
2. A party-total fare is multiplied again, a one-way result masquerades as round-trip, or an unknown room/fee scope enters costing: fail closed with a visible limitation (Tasks 2–3).
3. Confirmation replay, critic loops or process restart reset the call ceiling or silently requery: one stable budget identity per confirmed revision; no recovery-triggered dispatch (Task 4).
4. A stale quote crosses final assembly/edit/prose-refresh boundaries: no TTL extension, silent sample substitution or unconfirmed provider invalidation (Tasks 2, 4–5).
5. A missing/unsafe link, contradictory trust state, raw provider secret or cross-user context reaches the workspace: validate, redact and authorize on the server; render typed state only (Tasks 4–5).

## Scope and decisions

The recommended approach is **confirmed-session-only gateway wiring**, leaving the unauthenticated legacy `/plan` wizard on its unchanged default path. Switching every legacy call would broaden the confirmation boundary; waiting for live capture would make an external unknown a development gate. Neither is necessary for this plan.

- Successful structured Gondola responses remain unverified (`reports/g3_2_gondola_live_acceptance.md` §17.3–17.5). The production factory constructs only `SampleAdapter`, even if old live environment flags are present. Fixture injection remains explicit in tests; a live transport is not instantiated or enabled. An unstructured `result` string must produce `invalid_response` and sample fallback, not fabricated inventory.
- G1 sample flights preserve a seed per-traveler trip estimate packaged as a synthetic one-way segment. Sample hotels preserve nightly-rate multiplication and existing FX-floor order. This is a **sample package**, not proof of a current return itinerary or room availability. Keep G1 parity; do not “repair” seeds/segments to look real.
- Non-sample quotes need explicit party-total price scope, matching requests and supported channels before supplying cost lines. Unknown scope is alternative-only. Never apply the sample traveler/night multiplier to an external party total.
- The existing Kernel's award target is fixed business/round-trip (`agents/kernel.py`). Do not change it. Expose its seed-backed advice as reference/verify-before-transfer only, with a typed applicability limitation when the confirmed cabin differs. Do not claim new live award availability or a guaranteed personalized comparison; preserve numeric artifacts.
- The CP2 runner currently drops `TripIntakeRequest.wallet`; the compiled request must include the approved wallet for intake to copy. Validate the resulting `TripSpec` against the snapshot rather than silently replacing all intake values with a new typed equivalent.
- `/plan?job_id=…` currently does not hydrate results. Confirmed sessions will navigate to `/plan?session=<id>` and poll the authenticated session job endpoint. Legacy wizard behavior remains intact.
- F5 edits and prose refresh must retain admitted inventory costs without provider calls. Use server-owned, owner-scoped ephemeral context for confirmed sessions; legacy stateless endpoints remain unchanged. If context is absent/expired, return a typed conflict and preserve the displayed report, rather than resetting prices or searching again.
- Keep exact confirmed dates in this slice. A nonzero flexibility window is retained as an explicit limitation; do not fan out or broaden airports/dates. Post-plan changes requiring new searches belong to CP4 and another confirmation.

## File map and interfaces

| File | Responsibility |
|---|---|
| new `backend/agents/confirmed_trip.py` | deterministic snapshot serialization, intake comparison, request projection |
| new `backend/gateway/travel/product.py` | internal inventory snapshot, price-scope/eligibility contracts, safe public summary models |
| new `backend/gateway/travel/service.py` | allowlisted injected adapters, query identity, bounded selection/fallback, clock-driven expiry |
| `backend/agents/gateway_estimator.py` | preserve existing G1 entry point; add confirmed-request quote-to-cost bridge |
| new `backend/api/confirmed_planning.py` | confirmed job construction and owner/revision-bound inventory context |
| `backend/agents/pipeline.py`, `models.py`, `explainer.py`, `recompute.py` | existing-stage seams and additive report projection; no new LLM role |
| `backend/api/conversation.py`, `job_manager.py`, `main.py` | authenticated dispatch, typed job response, owned-job protection and scoped edit/refresh wrappers |
| frontend API schemas/generated/MSW, conversation/plan routes and new inventory component | typed evidence display, session resume and existing interaction compatibility |
| new `backend/evals/test_g3_4_*.py`, frontend unit/browser tests | behavioral integration and boundary proofs |
| `DEVIATIONS.md`, synchronized briefs/current-state/infrastructure, new G3.4 report | actual decisions and acceptance evidence |

The following signatures are the integration contract; define the data classes in the task that owns them:

```python
# Task 1, agents/confirmed_trip.py
def compile_confirmed_input(snapshot: ConfirmedBriefSnapshot) -> ConfirmedTripInput: ...
def validate_confirmed_intake(spec: TripSpec, inputs: ConfirmedTripInput) -> TripSpec: ...
def build_inventory_requests(inputs: ConfirmedTripInput, itinerary: DraftItinerary
                            ) -> tuple[FlightSearchRequest, HotelSearchRequest]: ...

# Task 2, gateway/travel/service.py
class TravelInventoryService:
    async def search(self, flight: FlightSearchRequest, hotel: HotelSearchRequest
                     ) -> TravelInventorySnapshot: ...
    def revalidate(self, snapshot: TravelInventorySnapshot) -> TravelInventorySnapshot: ...

# Task 3, agents/gateway_estimator.py; old function remains unchanged
def estimate_confirmed_inventory(spec: TripSpec, itinerary: DraftItinerary,
                                 kb: KnowledgeBase, snapshot: TravelInventorySnapshot,
                                 *, booking_date: date) -> GatewayEstimateResult: ...

# Task 4, api/confirmed_planning.py
def start_confirmed_job(session: PlanningSession, job_id: str) -> None: ...
def build_travel_service(kb: KnowledgeBase, *, plan_id: str,
                         now: Callable[[], datetime]) -> TravelInventoryService: ...
def resolve_inventory_context(*, user_id: str, session_id: str,
                              job_id: str) -> ConfirmedInventoryContext: ...
```

`ConfirmedTripInput` contains the confirmed snapshot, canonical `raw_request`, expected core fields and deterministic qualitative planner notes. `TravelInventorySnapshot` contains requests, admissible flight/hotel quotes, explicit price scopes and typed diagnostics; never raw SDK payloads. `GatewayEstimateResult` contains the unchanged `EstimatorResult` plus a `TravelInventorySummary`. `ConfirmedInventoryContext` binds snapshot/revision, inventory, latest estimate/report and expiry to one owner/session/job; it is not an approved KB record or a cross-user cache.

The service receives country explicitly from confirmed home context; it cannot infer profile/country
eligibility from free text. Add `country: str` to its constructor, not to the frozen quote contracts.
Use a separate opaque `inventory_revision: int` in context and reports for scoped edits; increment
it on successful recompute, compare-and-swap concurrent edits, and never use a job id as a version.

---

### Task 1: Compile and validate the confirmed planning input

**Files:** Create `backend/agents/confirmed_trip.py`, `backend/evals/test_g3_4_confirmed_input.py`. Read `planning/contracts.py`, `answers.py`, `agents/intake.py`, `core/trip_models.py`; do not modify the frozen models.

**Interfaces:** Consumes `ConfirmedBriefSnapshot`; produces `ConfirmedTripInput`, `ConfirmedInputMismatchError`, and the three Task-1 functions above.

- [ ] Write the pure-input tests first. Use existing CP1 brief fixtures to construct a real snapshot, not an unconfirmed client payload:

```python
from evals.test_cp1_brief import NOW, _reviewing_session
from planning.brief import assemble_trip_brief
from planning.contracts import ConfirmedBriefSnapshot

def test_confirmed_wallet_is_present_in_intake_text():
    snapshot = ConfirmedBriefSnapshot(
        revision=1, confirmed_at=NOW,
        brief=assemble_trip_brief(_reviewing_session()),
    )
    inputs = compile_confirmed_input(snapshot)
    assert "hdfc-infinia" in inputs.raw_request
    assert snapshot.brief.wallet.model_dump() == inputs.expected_fields["wallet"]
    assert "user_id" not in inputs.raw_request
    assert "session_id" not in inputs.raw_request
```

Add literal-table tests: premium_economy maps to gateway `premium`; explicit cabin overrides style; rooms come from `room_count`; dates/origin/destination are copied; `max_stops=0` sets `nonstop_only`; no-preference uses declared existing defaults. Traveler counts must agree with essentials. Derive infants from confirmed ages under 2 and children from remaining ages, record that provider age pricing is unverified until its schema is reviewed; never claim fixture family prices as live verified. List unsupported baggage/seat/schedule/property-kind guarantees as limitations, not fulfilled facts.

- [ ] Run `cd backend && .venv/bin/pytest -q evals/test_g3_4_confirmed_input.py`; expect a missing-module failure before implementation.
- [ ] Implement strict frozen data classes and canonical JSON serialization. Include only trip facts, approved wallet and qualitative preferences; exclude account identifiers/profile audit metadata. Map `lowest_cash -> min_cash_outlay`, `highest_value/balanced -> max_savings`, `convenience -> simplicity`; delegated budget/style/pace use CP1's documented assumptions, not model inventions. Preserve `points_priority` as a limitation where the existing kernel cannot express it.

```python
OBJECTIVE_MAP = {
    "lowest_cash": "min_cash_outlay", "highest_value": "max_savings",
    "balanced": "max_savings", "convenience": "simplicity",
}

def validate_confirmed_intake(spec: TripSpec, inputs: ConfirmedTripInput) -> TripSpec:
    actual = spec.model_dump(mode="json")
    mismatches = [name for name, expected in inputs.expected_fields.items()
                  if actual[name] != expected]
    if mismatches:
        raise ConfirmedInputMismatchError(mismatches)
    return spec
```

Canonicalize card-id ordering on both sides before comparison; compare balances without recalculating them. Add mismatch tests for wallet, dates, travelers, budget, home country, objective and currency, plus a no-intake-bypass test. Error text lists field names, not private values.
- [ ] Rerun focused tests; expect all passing. Run strict mypy and Ruff for the new module. Commit `feat: compile confirmed trip inputs for gateway planning`.

### Task 2: Build the bounded inventory service and honest eligibility boundary

**Files:** Create `backend/gateway/travel/product.py`, `service.py`, `backend/evals/test_g3_4_inventory_service.py`. Reuse `registry.py`, `protocol.py`, `freshness.py`, Gondola budget/fixtures; no live transport change.

**Interfaces:** Consumes Task-1 search requests and `TravelProviderAdapter` instances. Produces `TravelInventorySnapshot`, `TravelInventorySummary`, `GatewayDiagnostic`, `QuotePriceScope`, and `TravelInventoryService`.

- [ ] Write tests for default sample-only construction, successful fixture results, recorded unstructured Gondola results, disabled/ineligible/positive-cost providers, malformed/empty responses, domain-independent fallback, and clock-controlled expiry. Implement fixture adapters against the existing protocol; do not mock the service or registry selection.

```python
def test_expiry_equality_is_not_current():
    assert compute_status(source_status="live", retrieved_at=NOW,
                          expires_at=NOW, now=NOW) == "stale"

def test_unknown_price_scope_is_not_cost_eligible():
    assert QuotePriceScope(basis="unknown", scope_verified=False).cost_eligible is False
```

Define `NOW` as an explicit aware fixture datetime. `QuotePriceScope` is a strict model with `basis` in `sample_per_traveler_trip`, `sample_nightly_stay`, `party_total`, `unknown`; only known sample bases or verified matching party totals are cost eligible. A provider name, LLM string or client boolean cannot grant verification.

- [ ] Run `cd backend && .venv/bin/pytest -q evals/test_g3_4_inventory_service.py`; expect missing definitions, then implement the service.
- [ ] Apply registry profile/domain/country, adapter capabilities, zero-cost and transport/schema eligibility before dispatch. The constructor receives an immutable registry, explicit adapter map, plan id and clock. The runtime factory supplies only SampleAdapter. Service selection must not ask an LLM or import OAuth/keychain bootstrap code.

```python
eligible = [entry for entry in registry.select_providers(
    active_profile="student_noncommercial", domain=domain, country=country)
    if entry.monthly_cost_minor == 0 and entry.provider_id in adapters]
```

Validate response request identity and price scope before selection. Materially comparable complete evidence outranks uncertain/partial prices; expired/observed/mismatched quotes cannot become current winners. Do not reconstruct external stops from sample duration encoding. Sample limitations remain explicitly synthetic; unsupported confirmed preferences do not authorize a silent broader search.

For sample nonstop/stop limits, inspect the actual typed seed row rather than its synthetic
single segment or note text. Sample hotel packaging does not establish multi-room pricing:
requests for more than one room cannot turn a one-room nightly seed amount into a verified
multi-room total. Keep it alternative-only with an explicit missing-scope diagnostic. Never
multiply by an invented room/child/infant fare factor.

- [ ] Reuse the existing persistent Gondola ledger with a stable confirmed-revision plan id. Count retries and expiry refreshes inside its two-call ceiling; service adds no outer retry. Revalidate before final assembly; refresh at most once only if approved budget/eligibility permits, otherwise stale/fresh fallback with a diagnostic. Normal CI uses fixtures only.
- [ ] Validate every public link as HTTPS with exact reviewed hosts, no userinfo and no control characters. Missing/unsafe links become null plus a limitation; no link-retrieval call or redirect is added. Secret/provider-injection fixtures must not reach diagnostics or later LLM prose unsanitized.
- [ ] Run focused service tests plus existing `test_gondola_*` and travel-boundary tests; expect pass. Commit `feat: add bounded confirmed-trip inventory selection`.

### Task 3: Bridge admitted quotes to existing deterministic costing

**Files:** Modify `backend/agents/gateway_estimator.py`; create `backend/evals/test_g3_4_costing.py`. Read estimator/kernel/explainer; no `core/` change.

**Interfaces:** Consumes Task-2 snapshot and existing `TripSpec`/itinerary; produces `GatewayEstimateResult(estimate: EstimatorResult, summary: TravelInventorySummary)`.

- [ ] Write sample parity tests using `evals/test_travel_gateway_parity.py`'s `_kb`, `_spec`, `_itinerary` fixtures. Independently pin the existing demo flight line at **8,200,000** and hotel line at **6,400,000**; assert full CostedTrip, OptimizerResult and TransferAdvice equality. They are preserved expectations, not newly selected financial constants.
- [ ] Write a separate party-total test with a synthetic complete two-traveler quote of **10001 INR minor units**: the admitted flight line must be exactly **10001**, not 20002. Pin the existing SGD→INR sample rate at `rate_micro=63200000`: a party total of **206 SGD minor units** converts once to **13019 INR minor units** (`206 * 63200000 // 1000000`), not **13018**, the result of separately flooring two 103-minor-unit amounts. These expectations were calculated with deterministic Python during planning; they are test inputs, not edited golden expectations.
- [ ] Run `cd backend && .venv/bin/pytest -q evals/test_g3_4_costing.py evals/test_travel_gateway_parity.py`; expect the missing bridge to fail, then implement it.

```python
# External party total: one deterministic conversion; no traveler/night multiplier.
amount_minor = price_in_home(quote.total_minor, quote.currency, home_currency, kb)
line = SpendLineItem(
    id=f"flight:{quote.id}", label=sanitized_label, category=SpendCategory.FLIGHTS,
    amount_minor=amount_minor, currency=home_currency,
    available_channels=quote.purchasable_channels,
)
```

For sample selections, resolve the actual seed id and reuse the existing multiplication/FX-floor order. Preserve existing POI/per-diem helpers and tie breaks. Never manufacture a SampleFlight/SampleHotel from external data; external selections keep legacy sample picks null and use the new summary. No known purchasing channel or unknown scope means alternative-only, not a guessed reward channel.

- [ ] Test unsupported cabin/room/route, one-way versus return-trip mismatch, absent channels, unknown price scope and a cheap partial quote. Emit missing-domain/subtotal limitations when airfare/stay cannot be costed; do not disguise omitted costs as a complete cheap trip.
- [ ] Keep the fixed Kernel award target and all algorithms unchanged. Summary metadata identifies its reference-only/verify-before-transfer scope and incompatible requested cabins. Reject any attempt to promote cash evidence into an AwardQuote.
- [ ] Rerun focused tests, full golden/optimizer/pathfinder checks, strict types and lint; expect pass. Commit `feat: map confirmed inventory to deterministic cost inputs`.

### Task 4: Wire authenticated confirmation, pipeline and safe interaction context

**Files:** Create `backend/api/confirmed_planning.py`, `backend/evals/test_g3_4_pipeline.py`, `test_g3_4_api.py`, `test_g3_4_edit_context.py`; modify `agents/pipeline.py`, `agents/recompute.py`, `api/conversation.py`, `api/job_manager.py`, `api/main.py`.

**Interfaces:** Consumes Tasks 1–3; produces the three Task-4 functions above and a `ConfirmedInventoryContext`. Extend `run_pipeline` with optional keyword-only `confirmed_input` and `inventory_service`; absent arguments retain the legacy path exactly. Context remains owner/revision/job bound and server-owned.

- [ ] Write real authenticated/CSRF tests using CP2 `_client`/`_csrf`, real SQLite and scripted Kernel LLM fixtures. GET/create/answer/review/amend/interpret must dispatch zero inventory searches; confirmed matching snapshots may dispatch. Tampered/stale confirmation returns existing typed conflicts without calls.
- [ ] Write two-thread/two-connection confirmation tests: one durable job id, one query set, no raw SQLite exception; repeated confirmation never resets the budget. Validate failed process-local job lookup reports honest unavailable/retry-needed state, not permanently queued or an automatic restart.
- [ ] Run the new tests and observe missing confirmed-job integration, then wire it inside existing stages:

```python
intake = run_intake(raw_request, kb, llm)  # retain existing error/clarification handling
spec = intake.trip_spec
if confirmed_input is not None:
    spec = validate_confirmed_intake(spec, confirmed_input)
# Existing retrieval/planner -> costing -> optimizer -> critic -> explainer order remains.
# At costing, confirmed_input + inventory_service choose estimate_confirmed_inventory;
# without them, call the existing estimate_costed_trip unchanged.
```

On mismatch, return `NEEDS_CLARIFICATION` with field-name diagnostics **before** constructing/dispatching a search. Keep planner/critic/explainer JSON contracts and role count unchanged. Carry qualitative confirmed constraints into existing planner revision notes; disclose unsupported accessibility/fare guarantees rather than asserting they were met.

- [ ] The confirmed job runner uses the persisted snapshot, not the request body or mutable profile. Derive `plan_id=f"{session.id}:revision:{snapshot.revision}"`; retries/new process-local job ids reuse it. Default `build_travel_service` remains sample-only. Reuse the job's admitted search set during critic loops; never start an unbounded provider loop or extend stale TTL.
- [ ] Set an optional owner id on confirmed JobState objects. Protect those jobs on **both** the session-job route and the legacy `/plan/{job_id}` route: anonymous/different-owner reads return 404, while existing unowned legacy wizard jobs retain their behavior. Test both surfaces with actual authenticated clients. The confirmed runner converts unexpected exceptions to a fixed safe JobError, never public `str(exc)` or provider bodies.
- [ ] Keep summaries available internally before their public exposure: add an optional keyword-only `on_inventory: Callable[[GatewayEstimateResult], None] | None` callback to `run_pipeline`. Invoke it with the final chosen estimate only after final freshness validation. The confirmed runner stores it in owner-scoped JobState context; Task 5 then projects it into the additive public report. Legacy callers supply no callback. Do not change the `EstimatorResult` or LLM JSON contracts to smuggle raw quotes through traces/prompts.
- [ ] Add owner-scoped, CSRF-protected session wrappers for existing typed interactions:
  `POST /planning/sessions/{id}/recompute` with existing edit plus expected inventory revision;
  `POST /planning/sessions/{id}/refresh-prose` with expected inventory revision.
  `resolve_inventory_context` checks authenticated ownership, the persisted job/revision link,
  context lifetime and the current quote status. The client cannot supply prices, quotes, providers or ownership claims.
- [ ] Pure itinerary edits retain admitted flight/hotel lines, recompute POI costs through existing helpers and make zero LLM/provider calls. Prose refresh uses the existing single explainer call and the same authoritative estimate. Missing/expired/stale context returns 409 `INVENTORY_REVIEW_REQUIRED`; cross-user lookup returns 404; neither redispatches or silently replaces prices. Explicit rebuilding remains the separate confirmation path, not CP4 implementation.
- [ ] Test that an injected fixture price survives both edit and prose refresh, that stale context preserves the previous report, and that a different user cannot read/edit it. Do not persist provider raw payloads or quote caches in AccountStore. Preserve the existing process-local limitation and provider retention rules.
- [ ] Run every new test plus CP1/CP2/CP3, Kernel call-site/transitive import, privacy and existing F5 tests. Run the complete backend suite and commit `feat: wire confirmed planning through the bounded travel gateway` only when green. Public schema work in Task 5 is coordinated as one contract/UI commit.

### Task 5: Ship the normalized product contract and resumable results UI together

**Files:** Modify `backend/agents/models.py`, `agents/explainer.py`, `api/conversation.py`, `contract/openapi.json`, `frontend/src/lib/api/generated/`, `frontend/src/lib/api/schemas.ts`, `frontend/src/mocks/handlers.ts`, `frontend/src/app/plan/conversation/page.tsx`, `frontend/src/app/plan/page.tsx`; create `frontend/src/components/product/travel-inventory.tsx`, `frontend/tests/g3-4-inventory.test.ts`, `frontend/e2e/g3-4-inventory.spec.ts`.

**Interfaces:** Add optional `FinalReport.travel_inventory: TravelInventorySummary | None = None`; type session-job output as existing `PlanJobStatus` instead of `dict[str, Any]`. Preserve all legacy report fields. Each quote summary includes the spec-12 EvidenceSummary fields plus source amount/currency, converted line amount, explicit price scope, selected/alternative identity and material limitations. No raw SDK payload, internal trace/error, credential or guessed availability is public.

- [ ] Write runtime-validator and browser tests first: missing legacy field remains backward compatible; malformed metadata, sample claiming live, observation claiming bookable, unsafe links, missing fees and inconsistent source/price scope fail safely. Exercise all five trust statuses with honest fixture provenance; no synthetic fixture is described as live-captured evidence.
- [ ] Add the normalized backend summary and generated contract in the same working change as consumers. Use only deterministic amounts copied from quote/SpendLineItem/Kernel artifacts. Expose price-subtotal and reference-award limitations as typed flags, never parse LLM prose.
- [ ] Regenerate locally without starting a real backend:

```bash
cd backend
.venv/bin/python -c 'import json; from pathlib import Path; from api.main import app; Path("../contract/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")'
cd ../frontend
npm run gen:api
```

- [ ] In conversation, link the workspace with its session id. In `/plan`, initialize a confirmed-session polling branch from the query string and call the authenticated session job endpoint; do not POST `/plan` again. Keep ordinary wizard submission unchanged. Use session-scoped edit/prose endpoints only for this branch and preserve current single-flight/stale-response guards.

```tsx
<TrustChip
  variant={evidence.needs_verification ? "needs-verification" : "verified"}
  label={evidence.status.replaceAll("_", " ")}
/>
```

The complete component also shows provider/attribution, source amount via MoneyText, retrieval/expiry, completeness and limitations. Stale/partial is never green/live styling; use warning variants where required. Render safe HTTPS links with `rel="noopener noreferrer"`; null links render no invented action. Never multiply, convert or sum amounts in React.

- [ ] Browser assertions: Build is the first query boundary; confirmation-to-results navigation works; refresh resumes without another job/search; two personas produce different approved search inputs; outage/invalid-response shows sample attribution; unsafe URLs are absent; accessibility and overflow pass at 1440/768/390 and reduced motion; F5 typed edits retain inventory amounts; expired-context errors keep the old report visible.
- [ ] Run complete frontend types/Vitest/ESLint/token/emitted-class checks and production build. Run all browser specs with live tests disabled, restoring only generated captures owned by this run after preserving them separately. Re-export OpenAPI/regenerate again and compare bytes. Commit all public models/snapshot/generated client/runtime schemas/MSW/UI/tests together as `feat: expose confirmed travel inventory evidence in the workspace`.

### Task 6: Independent review and exact-tree acceptance

**Files:** `DEVIATIONS.md`, synchronized `AGENTS.md`/`CLAUDE.md`, `docs/CURRENT_STATE.md`, `docs/INFRASTRUCTURE.md`, `frontend/ARCHITECTURE.md`, new `reports/g3_4_confirmed_brief_gateway.md`.

**Interfaces:** Consumes the complete branch from Tasks 1–5; produces verified evidence and a local clean branch, not a live-activation claim.

- [ ] Review the whole branch independently against this plan and the approved design. Investigate every verified Important/Critical finding, reproduce it red, fix it, and rerun relevant complete suites. Review the five failure classes above explicitly, including real concurrent reservation/confirmation and unsupported confirmed preferences.
- [ ] Log judgment calls as they occur. Report status is **ACCEPTANCE PENDING** until the exact committed tree passes. Correct naming drift only in the handoff documents being updated: product wiring is G3.4, not the historical G3.3 label; do not rewrite historical spec/report evidence.
- [ ] Seed and run the full backend suite, strict source-package typing and complete frontend/browser checks. No narrowed command can be reported as the full gate:

```bash
make seed PY=.venv/bin/python
cd backend && .venv/bin/pytest -q
MYPY_CACHE_DIR=/private/tmp/tripplanner-g3-4-mypy-cache .venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/
cd ../frontend
npx tsc --noEmit
npx vitest run
npx eslint .
node scripts/token-lint.mjs
npm run build -- --webpack
node scripts/no-dead-classes.mjs
# Start the production build on loopback, then:
npx playwright test --config=e2e/playwright.config.ts --workers=2 --reporter=line
```

Build before the emitted-class check. Webpack is the documented existing linked-dependency option, not a claim that default Turbopack was verified. No checkout may be provisioned with another worktree's credentials; missing ignored regional catalogs may be copied from the existing local artifacts and documented, never treated as an expected-value exemption.

- [ ] Commit coherent changes; keep refactoring separate from behavior. From the repository root run `MYPY_CACHE_DIR=/private/tmp/tripplanner-g3-4-mypy-cache make gate` against that exact committed clean tree. Record every count, skip, warning, gate marker and verification SHA in the report.
- [ ] After the passing gate, close the report/briefs, commit documentation and rerun the gate on that final committed tree. Check `git diff --exit-code <reviewed-plan-base> -- backend/core backend/evals/golden docs/specs docs/superpowers/specs` and `cmp AGENTS.md CLAUDE.md`. AST tests must prove no provider import/network in core or pure planning and no fifth Kernel caller.
- [ ] Show final hash, clean status, complete test/gate results, live activation still disabled, and all other worktrees/branches preserved. Do not push, merge, delete branches/worktrees, start FI/CP4, bootstrap OAuth or spend money without a separate human request.

## Execution setup and self-review

At execution time use the worktree skill and app worktree tools: create/reuse an appropriate isolated G3.4 worktree from the **reviewed plan commit**, a descendant of CP3 `26864ee`. Suggested branch: `codex/g3-4-confirmed-brief-gateway`. Verify clean status and the base; leave the primary checkout, CP3 and all existing worktrees alone.

Spec coverage: confirmed-brief authority and retained intake (Task 1/4), provider eligibility/budgets/fallback/schema uncertainty (Task 2), price completeness/financial parity (Task 3), confirmation/recovery/edit invalidation boundaries (Task 4), public evidence/contract/resume/accessibility (Task 5), review/gates/documentation (Task 6). Post-plan semantic routing and further provider-invalidating changes are intentionally CP4, not missing G3.4 work.

Self-review: interfaces agree across tasks; all five review-focus classes have assigned regression cases; no new financial algorithm, authoritative-spec edit, live capture claim or activation prerequisite is inferred. The plan does not promise a live Gondola schema proof. The plan requires a complete offline product path even if Gondola remains unverified.
