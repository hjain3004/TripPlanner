# CP4 Backend Conversational Actions Implementation Plan

> **For agentic workers:** Implement task by task using `superpowers:executing-plans` or `superpowers:subagent-driven-development`. Checkboxes record execution, not design approval or existing behavior.

**Status:** PLAN ONLY. No CP4 implementation or baseline test run was performed while writing this document.

**Goal:** Let an authenticated traveler propose, review, and apply post-plan changes through typed, versioned backend actions, preserving financial correctness, unaffected itinerary days, evidence freshness, and saved history.

**Architecture:** A pure action classifier and invalidation policy surround the existing kernel. An optional bounded interpreter proposes typed actions; an authenticated orchestration service validates and executes them against a server-owned workspace. Accounts owns the opaque workspace and operation records, while orchestration alone understands reports and normalized inventory.

**Tech stack:** Existing FastAPI, Pydantic, SQLAlchemy/SQLite, `LLMClient`, planning repository, itinerary edits, deterministic estimator/kernel, recorded-fixture clients, and OpenAPI code generation. No new runtime dependency is required by this plan.

**Spec:** `docs/superpowers/specs/2026-08-21-conversational-trip-planning-design.md`, especially §§4, 6–12, 14–15; `docs/specs/06_implementation_protocol.md`, `09_target_platform_architecture.md`, `12_integration_contract.md`, `16_data_gateway_and_adapters.md`, and `17_accounts_and_persistence.md`. Authoritative specs remain read-only.

**Base:** `a172c19b405a42b7d2b8cbf6c9337737760ba50d`, the reviewed A4 closure, branch `codex/a4-saved-trips`. PR [#16](https://github.com/hjain3004/TripPlanner/pull/16) was OPEN with four successful CI checks when this plan was written. CP4 may stack on that commit; do not merge the PR or rewrite its branch as part of implementation without authorization.

## Scope and completion labels

This plan delivers the **CP4 backend**, OpenAPI, generated client/facade, and faithful MSW behavior. It does not deliver the synchronized chat/workspace UI. Report `CP4 BACKEND COMPLETE; UI ACCEPTANCE PENDING` only after all backend gates pass. Full CP4 remains pending until its visual workspace and browser acceptance are implemented. This follows A4's explicit backend-first contract delivery; it does not waive eventual spec-12 UI acceptance.

Deployment, AWS sizing, native Anthropic integration, FI work, welcome offers, new provider activation, and a distributed/durable job runner are outside this plan. Normal tests use scripted/replay clients, controlled clocks, local catalogs, and raising transports. No paid or credential-dependent calls are authorized.

## Global constraints

- Keep the kernel pipeline graph, intake boundary, four kernel LLM call sites, frozen money semantics, and golden values unchanged. Do not introduce the post-plan interpreter into `run_pipeline`'s import graph.
- UI commands make zero interpretation calls; unresolved semantic text permits at most **one** interpreter invocation per message. No interpreter repair, provider fallback, hidden retry, or model substitution may create a second invocation.
- Domain invalidation is deterministic. The interpreter may not choose domains, prices, providers, tools, effect status, or approval status.
- No financial arithmetic in model prose or frontend code. No booking, payment, transfer execution, autonomous KB update, or inferred profile write.
- Keep all state owner-scoped, CAS-protected, idempotent, exportable, and deletable. Wrong owner and missing resource have the same 404 response.
- Historical reports/briefs/revisions retain their original canonical bytes. Read old saved reports verbatim; do not coerce them through current models.
- Reuse normalized evidence only within its original expiry and retention basis. Copying evidence never refreshes its timestamps or upgrades its trust status.
- Scope is expressed as explicit dates, not a loosely interpreted phrase such as “tomorrow.” Resolve relative dates from the itinerary/time-zone context or ask for clarification.
- Persist only validated visible events and typed proposals. Do not store raw prompts, model reasoning, credentials, provider payloads, or unredacted sensitive text.
- Existing default production factories remain sample-only. CP4 offline injection does not activate a live adapter.
- Preserve every existing worktree and branch. Use an isolated CP4 implementation branch; do not implement on A4 or on the dirty primary checkout.

## Review focus

1. Admitted prices differ from seed prices: every displayed total and payment allocation must derive from the final admitted cost lines (Task 1).
2. Two browser tabs approve conflicting actions: exactly one commits; the other sees a typed stale conflict, with no duplicate dispatch or revision (Tasks 3, 5, 8).
3. A partial-day change returns a full itinerary: reject out-of-scope mutations and keep unaffected day payloads byte-identical (Task 6).
4. Evidence expires, a job disappears, or the process crashes between reservation and completion: no silent refresh or second paid/provider dispatch (Tasks 3, 6–8).
5. A saved old revision, deleted trip, changed wallet, or late profile edit is used as the base: verify exact ownership/version/context and never overwrite newer state (Tasks 2, 5, 7–8).

## Existing-code findings the implementer must preserve

| Source | Verified interface / limitation | Planning consequence |
|---|---|---|
| `core/itinerary/edits.py` | `apply_edit` supports move/remove/reorder/add/replace | Reuse these types; no second edit language |
| `agents/recompute.py` | `recompute_itinerary` runs a legacy estimate and then the kernel | Preserve its standalone behavior; add a confirmed-report assembly path |
| `api/conversation.py:recompute_confirmed_session` | Replaces flight/hotel lines **after** recompute has calculated optimizer/report fields | Task 1 must reproduce inconsistent admitted-price totals before fixing assembly order |
| `agents/gateway_estimator.py` | `estimate_confirmed_inventory(..., snapshot, booking_date=...)` admits normalized quotes | Preserve price scopes, integer conversions, and selected evidence; do not invent quote payloads from summaries |
| `gateway/travel/service.py` | `search` returns `TravelInventorySnapshot`; `revalidate` is local freshness handling | Capture admitted snapshots without another search; reuse domains only through request-compatible snapshots |
| `api/main.py:_run_job` | `on_inventory` currently retains a summary, not a normalized snapshot | Add a data-retention seam without adding/changing kernel execution nodes |
| `agents/planner.py` | One planner attempt may run discovery up to six calls, followed by a repair attempt | Reusing `run_planner` does not imply one call or zero provider I/O |
| `planning/policy.py:amend_answer` | Rejects already-confirmed sessions | Do not call the pre-plan amendment API for CP4; add an explicit post-plan transition |
| `planning/brief.py` | Existing typed profile proposals and confirmed snapshots | Reuse payloads, but never approve a stale full-profile replacement |
| A4 storage/routes | Explicit save and append-only revisions; process-local reruns | Working edits do not automatically append a saved revision; saving remains explicit |

## Settled interfaces and decisions

### Intent and impact contracts

Create `planning/post_plan.py`, keeping it pure (only existing domain/Pydantic/stdlib imports, no agents, API, network, clock, random, or SQL imports).

Define a discriminator union `PostPlanAction` with exactly these `kind` values:

- `deterministic_edit`: existing `ItineraryEdit`.
- `scoped_itinerary_replan`: nonempty unique `affected_dates`, a typed `BriefPatch`, and optional bounded day-theme text.
- `provider_invalidating_change`: typed `BriefPatch` only; no client-authored domain list.
- `wallet_or_objective_change`: a request to adopt the current stored wallet and/or a typed objective patch. No caller-supplied card balances or credentials.
- `explanation_request`: an existing artifact/line/quote identifier and an approved explanation topic.
- `profile_update_proposal`: an approved preference section and typed candidate fields.
- `clarification_required`: a bounded safe question with explicit choices where possible.

`BriefPatch` replaces complete existing answer payloads by approved `QuestionId` values; use `ANSWER_TYPE_BY_QUESTION` for validation. It is not an arbitrary field path or JSON patch. Revalidate cross-field traveler/date consistency and preserve untouched sections. Money, dates, and counts from natural language require exact supporting user input and a visible typed confirmation; ambiguous conversions become clarification. Unsupported constraints remain explicit limitations, never claimed as enforced.

Functions:

```python
classify_command(text: str, context: RoutingContext) -> PostPlanAction | None
compute_impact(before: TripBrief, after: TripBrief, *,
    action: PostPlanAction, context: ImpactContext) -> ActionImpact
apply_brief_patch(brief: TripBrief, patch: BriefPatch) -> TripBrief
```

`RoutingContext` contains only approved item IDs/names/dates and allowed choices. `ImpactContext` contains the current itinerary dates/item references, existing day-specific overrides, retained hotel area, and canonical search-semantic fingerprints; it has no provider handle or arbitrary model fields. `ActionImpact` contains server-derived invalidated domains, affected dates, required confirmation, inventory reuse eligibility, and explanation-only status. Caller/model supplied impact values are forbidden. The action/context arguments distinguish edits, explanations, and day-local overrides even when the two global briefs are identical.

Preserve spec §9's invalidation table. A flight-only change queries flights only; a hotel-only change queries hotels only. Destination/date/party changes invalidate all affected inventory and dependent outputs. Food/interests/pace/accessibility changes reuse flight/hotel evidence while recalculating affected itinerary costs. Wallet/objective changes reuse inventory unless request semantics actually change.

### Working state and persistence

Create `agents/post_plan_models.py` with `PostPlanWorkspace`: session/owner identity, workspace version, source job or saved revision reference, confirmed-brief revision, validated current report, current Trip Brief, sanitized normalized inventory context (only when retention permits), report-schema fingerprint, created/updated time, and expiry. A `result_id` addresses the exact accepted report bytes.

Accounts stores opaque JSON through `PostPlanWorkspaceSnapshot` and `PostPlanOperation` in `accounts/models.py`; account modules must not import agents/gateway/planning models. Add account tables and additive migrations in `accounts/db.py`; no destructive recreation or backfill that rewrites saved reports.

Use a current-workspace row plus immutable accepted-result rows. Operation records reference result IDs instead of embedding a second report. The current row points to its latest result. Saved revisions remain separate, explicitly user-saved records. Workspace retention follows its parent session/trip; privacy export and account/trip/session deletion cover every new row.

`PostPlanOperation` records operation kind, canonical caller-request fingerprint, expected versions, status (`reserved`, `complete`, `failed`, `interrupted`), validated proposal/result reference, consumed call slots, and sanitized error. Namespace client IDs separately from system-completion IDs, following A4 closure. Replay compares caller-controlled request data, not generated IDs/timestamps, and runs before stale-version checks. Reuse with changed text/action/base/version/decision is a typed conflict.

Store interfaces (keyword-only identity/version arguments):

```python
get_post_plan_workspace(*, user_id: str, session_id: str) -> PostPlanWorkspaceSnapshot | None
reserve_post_plan_operation(*, user_id: str, session_id: str,
    operation: PostPlanOperation, expected_workspace_version: int,
    expected_session_version: int) -> PostPlanOperation
commit_post_plan_operation(*, user_id: str, session_id: str,
    event_id: str, fingerprint: str, expected_workspace_version: int,
    workspace: PostPlanWorkspaceSnapshot, session: PlanningSessionSnapshot,
    report_json: str | None) -> PostPlanOperation
```

The final commit uses one SQLite write transaction to CAS the workspace/session, mark the proposal terminal, and insert an accepted result/event. Proposal creation/reservation advances the workspace operation version and returns its new value; approval uses that returned value and the recorded report-base result ID. Result IDs remain unchanged for proposal/clarification/rejection-only transitions. No DB lock is held during model/provider calls. Late completions compare the reservation and base versions; they cannot replace newer work. Reserve before dispatch and never dispatch a recovered reservation again. Interrupted work retains its consumed budget and exposes retry as a **new explicit action**. This provides operation recovery, not a durable background-job runner.

Planning defaults to record as Tier C at implementation: 20 interpreter calls/session, 10 scoped-replan actions/session, 100 action records/session, and a 2 MiB report bound. Reuse A4's 25 saved revisions/trip. Limits produce typed outcomes; they never silently evict an idempotency key and allow redispatch. Inputs are bounded to 2,000 characters; oversize text is visibly rejected rather than truncated. Clocks and IDs are injected outside the pure domain.

### Backend routes

New router `api/post_plan.py`, mounted under `/planning/sessions/{session_id}`:

| Method and suffix | Request / result |
|---|---|
| `POST /workspace` | Initialize from an owned completed job or specified saved trip/revision; idempotent; never invokes a model/provider |
| `GET /workspace` | Current typed workspace, pending proposals, operation status, diagnostics, versions |
| `POST /actions` | `client_event_id`, expected session/workspace versions, exactly one of typed action or text; returns proposal/clarification |
| `POST /actions/{proposal_id}/approve` | Event ID and expected versions; executes the exact stored proposal |
| `POST /actions/{proposal_id}/reject` | Event ID and expected versions; no computation/provider dispatch |
| `POST /workspace/revisions` | Explicitly append the current accepted result to the attached saved trip using A4 storage rules |

All mutations require CSRF. `POST /actions` never applies an edit; typed and semantic proposals share approval semantics. An approval with external work returns 202 plus a durable operation ID; `GET /workspace` exposes progress. Immediate actions may return 200. Exactly one terminal approval or rejection is allowed.

Preserve A4's first-save route as the explicit first-save capability. For a session with a CP4 workspace, extend `POST /account/trips` and `POST /account/trips/{trip_id}/revisions` with `source_result_id` and `expected_workspace_version`; both are required when that workspace exists. Read the exact accepted result from the workspace/result store instead of `_finished_report()`'s process-local job. Missing selection returns typed `409 WORKSPACE_REVIEW_REQUIRED`, never a silent original-job save. Bind the chosen result, workspace CAS, attachment, mutation event, and new trip/revision in one transaction. Sessions without a CP4 workspace retain A4 behavior. After restart an already accepted durable result remains explicitly savable; an unfinished job does not become recoverable. Regenerate A4 error unions, facade types, and mock fixtures for these additive capabilities.

Declare actual typed errors in OpenAPI: missing resources 404, expired unattached session 410, stale/idempotency/in-progress/needs-review conflicts 409, oversized requests 413, invalid payloads 422, exhausted quota 429, mapped store unavailability 503. Malformed JSON retains FastAPI validation behavior. Never include exception internals in a response.

Profile proposals create a CP4 action with the affected section and its original fingerprint. Approval merges only that section against the current profile in the same transaction as terminal action state; a competing change to that section yields a conflict. Unrelated concurrent profile edits survive. Do not reuse CP2's whole-profile write followed by a separate session save.

### Inventory reuse and scoped planning

Capture the normalized snapshot that was actually admitted by the completed job. Extend the gateway/job data seam to retain it; do not modify the kernel pipeline graph. A `PinnedInventoryService` in `gateway/travel/reuse.py` returns deep copies of an eligible captured snapshot and locally revalidates it. It retains original provider IDs, scopes, timestamps, expiry, and revisions. It never invokes a transport and never passes the data through a registry that would fabricate a new price scope.

For partial invalidation, the service receives a server-derived allowed-domain set and merges only newly queried domains. Add keyword-only `domains` to `TravelInventoryService.search`, defaulting to both for all existing callers. No request or model may set this argument directly. Reuse checks compare complete normalized search requests plus retained preferences that the present request schema cannot encode. An itinerary-generated hotel-area change must not silently change the retained hotel search.

`agents/post_plan_execution.py` owns:

```python
recompute_confirmed_report(report: FinalReport, *, itinerary: DraftItinerary,
    spec: TripSpec, kb: KnowledgeBase, now: datetime) -> FinalReport
run_scoped_replan(workspace: PostPlanWorkspace, action: ScopedItineraryReplan,
    *, kb: KnowledgeBase, llm: LLMClient, now: datetime) -> FinalReport
```

Deterministic recomputation builds POI/per-diem lines for the edited draft, retains admitted flight/hotel lines and selected evidence, then runs the kernel **once on that final costed trip**, then assembles all report totals/payments/transfer guidance. Never replace prices after optimizer/report assembly. Retain the booking date for the retained evidence; fresh-search paths use their explicit new booking context.

Scoped planning may reuse `run_planner` with an optional injected local-only discovery registry (threaded into `_call_planner`; default behavior unchanged). Pin hotel area, provide unchanged days as locked context, and validate the returned candidate. At most the existing two planner attempts and six discovery calls/attempt are permitted (12 planner invocations/action); use a persistent reservation and an invocation guard. The interpreter call is separate from this planner budget. No critic loop, intake call, provider discovery, or automatic explainer is added for a scoped action.

Only affected dates may be replaced. Recompose affected days with local routing and retain all unaffected day payloads, POIs, order, evidence, and notes exactly. Global interests/pace changes affect all days; a day-specific preference patch is stored as an override for those dates, not silently promoted into a global `TripSpec` change. Enforce cross-day uniqueness and hard constraints after splicing. Unsatisfied hard constraints reject the candidate or produce explicit partial/clarification output; warnings alone must not claim success.

For expired/missing/incompatible evidence, return `INVENTORY_REVIEW_REQUIRED` without a transport call. An explicit invalidation proposal can obtain fresh evidence after approval. It shows affected domains and whether refresh may change price. No silent sample replacement of previously admitted evidence. Changed dates must satisfy the existing 3–7-night range and be future-valid relative to the injected clock; past-date reruns require explicit date correction.

Explanations use references to computed artifact fields and deterministic templates initially. Do not silently invoke the explainer. The existing explicit prose-refresh path remains available and grounded; it must consume the authoritative CP4 report and CAS against the workspace base.

## Execution tasks

### Task 1 — Reproduce and fix admitted-price recomputation

**Files:** create `agents/post_plan_execution.py` and `evals/test_cp4_recompute.py`; modify `api/conversation.py`; leave legacy `agents/recompute.py` defaults unchanged.

**Interfaces:** produce `recompute_confirmed_report` above. It accepts only server-owned report/spec/itinerary objects and no LLM/provider argument.

- [ ] Write `test_confirmed_edit_kernel_uses_admitted_prices`: use admitted flight/hotel amounts and channels that differ materially from seeds; assert final cost lines, optimizer totals, payment-line allocations, report budget, and transfer result equal a fresh `run_kernel` over those exact final lines.
- [ ] Run `cd backend && .venv/bin/pytest -q evals/test_cp4_recompute.py`; demonstrate failure against the current splice-after-assembly behavior, not just a missing import.
- [ ] Implement final-line assembly and route confirmed recompute through it. Preserve selected quote IDs, provenance, caveats, assumptions, booking date, stale prose/critic flags, and the legacy standalone recompute response.
- [ ] Test empty wallets, missing one inventory domain, party-total versus sample scopes, changed payable activities, and zero model/provider calls. Use distinct values so a seed fallback cannot pass accidentally.
- [ ] Run the new tests and existing `test_recompute_endpoint.py`, `test_travel_gateway_parity.py`, and `test_g3_4_boundaries.py`; commit `fix(planning): recompute rewards from admitted inventory prices`.

### Task 2 — Pure intents, patch validation, and deterministic impact

**Files:** create `planning/post_plan.py`, `evals/test_cp4_intents.py`, `evals/test_cp4_impact.py`.

**Interfaces:** produce `PostPlanAction`, `RoutingContext`, `BriefPatch`, `ActionImpact`, and the three domain functions above.

- [ ] Add parameterized tests for all seven intents and every invalidation-table row, including mixed changes whose impacts union rather than cancel.
- [ ] Add exact remove/move/reorder matches, duplicate venue-name ambiguity, nonexistent items/dates, contradictory scope, numeric/date extraction, unsupported accessibility claims, and arbitrary patch/provider fields. Ambiguous input yields clarification.
- [ ] Implement conservative deterministic matching. Known controls use existing edit types; natural-language matching must not pretend to understand an unsupported phrase.
- [ ] Assert pace/interests never authorize flight/hotel calls, objective-only changes do not imply a new hotel search, and room/occupancy changes do. The pure package import test must remain non-vacuous.
- [ ] Pass identical before/after global briefs with remove, day-local pace change, and explanation actions. Assert distinct affected-date/confirmation/explanation impacts from the validated action/context rather than guessing from brief differences.
- [ ] Run both new test files plus CP1 policy/brief tests; commit `feat(planning): define post-plan actions and deterministic impact`.

### Task 3 — Durable workspace, operation reservations, and result commits

**Files:** modify `accounts/models.py`, `accounts/db.py`, `accounts/store.py`; create `agents/post_plan_models.py`, `api/post_plan_service.py`, `evals/test_cp4_storage.py`, `evals/test_cp4_recovery.py`.

**Interfaces:** produce the three store methods above plus owner-scoped workspace creation, privacy export, expiry, and deletion. Orchestration validates opaque payloads on entry; historical saved reports remain verbatim.

- [ ] Test migration from a real pre-CP4 database without changing account/wallet/trip/revision bytes, then reopen SQLite. Update the A1 exact-table inventory for the explicitly added workspace/result/operation tables; retain the exact-set assertion and all isolation/seed-preservation checks.
- [ ] Test identical replay before version checks, changed caller payload under the same ID, isolated client/system namespaces, and two actual connections/threads competing at one expected version.
- [ ] Implement transactional reservations and commits. Include report result references, consumed call slots, interrupted recovery, terminal decision exclusivity, and bounded records without unsafe eviction.
- [ ] Inject failure between each commit step: no partial workspace/session/event state survives. Account/trip/session deletion racing with completion must not recreate deleted data. Prove privacy export and deletion after reopening SQLite.
- [ ] Initialize from an owned completed job without calls. Saved-revision initialization checks schema fingerprint and exact source spec/context; incompatible history remains readable and returns a typed rebuild requirement for editing.
- [ ] Run the new files plus A4 privacy/idempotency/scoping tests and the account table-boundary test; commit `feat(accounts): persist post-plan operations with atomic commits`.

### Task 4 — One-call semantic interpretation with replay evidence

**Files:** create `agents/post_plan_interpreter.py`, `evals/test_cp4_interpreter.py`, `evals/recorded/post_plan/corpus.json`; extend the existing LLM configuration examples and `evals/test_i5_call_sites.py`.

**Interfaces:** `PostPlanInterpreter.interpret(context: RoutingContext, text: str) -> PostPlanAction`; `get_post_plan_llm() -> LLMClient`. The API owns reservations and counters; the interpreter has no account/store/provider object.

- [ ] Test zero calls for deterministic matches, exactly one `node="post_plan_interpret"` invocation for semantic text, one call even for malformed output/timeout/rate-limit, and no call after the session budget is exhausted.
- [ ] Use CP3's guarded configuration pattern with separate post-plan variables; hosted dispatch stays disabled unless the existing zero-spend conditions are explicitly satisfied. Use `max_tokens=1000`, `timeout_s=20`, no tools, and no transport/model retries.
- [ ] Reject invented IDs/dates/amounts/fields, injected tools, sensitive payment text, oversized text, unsupported fiscal assertions, and model-chosen impacts. Redact secrets before dispatch; do not persist unsanitized input.
- [ ] Add authored synthetic personas with declared provenance, recording/replay round trips, and a teeth test: replacing semantic interpretation with always-clarify must fail the nuanced-action acceptance cases.
- [ ] Extend only the exact target-platform caller allowlist; transitive kernel traversal must still reach exactly its original four callers and neither assistant.
- [ ] Run the new file plus CP3 assistant/budget/call-site guards; commit `feat(agents): interpret bounded post-plan action proposals`.

### Task 5 — Proposal API, approvals, and deterministic actions

**Files:** create `api/post_plan.py`, `evals/test_cp4_api.py`, `evals/test_cp4_concurrency.py`; modify `api/main.py`, `api/conversation.py`, `api/saved_trips.py`, the A4 transactional store helpers, and the service from Task 3.

**Interfaces:** implement the six route capabilities above; return typed `PostPlanWorkspaceOut`, `ActionProposalOut`, `ActionOutcomeOut`, and `PostPlanErrorResponse`. Keep response impact fields server-derived.

- [ ] Test 401/403, indistinguishable owner/missing 404, stale workspace/session versions, conflicting IDs, approve/reject races, rollback, and real database-lock-to-503 mapping.
- [ ] Implement proposal creation without effects. Approve deterministic edits through Task 1; adopt a current wallet only with visible approval and a wallet fingerprint recheck. Explanation requests read computed artifacts only.
- [ ] Ensure legacy confirmed recompute/prose routes use the same workspace version authority once initialized, so old clients cannot overwrite an approved CP4 result. Advance the report's existing `travel_inventory.inventory_revision` on each accepted report change and compare the legacy `expected_inventory_revision` with that value; do not substitute the latest value on behalf of a stale caller. Keep evidence generation/expiry independent of this report edit counter. Keep pre-CP4 response compatibility and declare new conflicts.
- [ ] Wire A4 first-save and append to the selected authoritative CP4 result when a workspace exists; leave job-based behavior for untouched A4 sessions. Test approve → first save, restart → first save, approve → append, missing result selection, and concurrent apply/save: save the selected version or return a conflict, never save the original or a newer unreviewed result. The store must atomically bind result selection/attachment/idempotency.
- [ ] Explicit revision saving uses the exact accepted result bytes, A4 limits, client/system namespaces, and one transaction; a retry cannot save a later unrelated result. Unattached workspaces use explicit A4 first-save and never autosave.
- [ ] Test simultaneous A4 rerun/CP4 apply behavior: one active mutation path per source session/workspace or a typed conflict. No stale job completion may overwrite newer work.
- [ ] Run new API/concurrency files plus A4 and CP2/G3.4 regressions; commit `feat(api): expose versioned post-plan proposal and approval routes`.

### Task 6 — Scoped replanning and inventory reuse

**Files:** create `gateway/travel/reuse.py`, `evals/test_cp4_scoped_replan.py`, `evals/test_cp4_inventory_reuse.py`; modify `gateway/travel/service.py`, `agents/planner.py`, `api/job_manager.py`, `api/main.py`, and Task 1 execution/service code.

**Interfaces:** produce `PinnedInventoryService` and `run_scoped_replan`; capture the actual admitted normalized snapshot at job completion, without a second search. Inject a local-only planner discovery registry through optional keyword parameters; legacy defaults and kernel graph stay unchanged.

- [ ] Test unchanged quote IDs, price scopes, original timestamps, and expiry across reuse; no current time may become a new retrieval time.
- [ ] Make every live inventory/place/routing transport raise. A pace/day-theme replan must still succeed through local evidence and produce **zero transport calls**, even if the model proposes discovery.
- [ ] Assert unaffected day canonical JSON remains identical. Reject extra/duplicate/out-of-range dates and attempts to alter locked hotel area, unsupported venue IDs, immovable events, or unaffected days. Validate the resulting schedule and unique activity references.
- [ ] Assert bounded 12 planner calls per scoped action including repair, recorded reservation on failure, deterministic fallback, and no automatic critic/intake/explainer invocation. Exceeding budget must not dispatch again.
- [ ] Missing/expired context returns a review requirement, keeps the old report, and invokes no provider. Recompute all affected financial outputs through Task 1 only after a valid itinerary is accepted.
- [ ] Run the new files and I1/I5 planner/schedule/boundary tests; commit `feat(planning): replan scoped days with retained inventory evidence`.

### Task 7 — Confirmed invalidation and explicit profile changes

**Files:** extend `api/post_plan_service.py`, `agents/post_plan_execution.py`, gateway reuse; create `evals/test_cp4_invalidation.py`, `evals/test_cp4_profile_updates.py`.

**Interfaces:** `execute_approved_action` dispatches only a stored server-computed impact and a matching reservation. Provider-changing input re-enters `compile_confirmed_input` and the unchanged intake boundary on the full replan path.

- [ ] Prove proposal/decline/stale approval makes zero provider calls. A single approval of date/destination/party changes permits exactly the bounded required domain calls; repeated approval does not repeat them.
- [ ] Prove flight-only and hotel-only invalidations do not query the other domain, preserve reusable evidence, and reject changed search semantics not representable by the retained request. Keep sample fallback explicit and existing scope rules intact.
- [ ] Build a new confirmed snapshot rather than calling `amend_answer` on confirmed sessions. Preserve old briefs/revisions, current wallet consent, plan limits, and failure diagnostics. Failure leaves the prior accepted workspace/report visible.
- [ ] Test past-date corrections, invalid trip length, absent catalog corridor, changed booking context, stale wallet, partial provider failure, and expiry during execution. No plan is labeled fully successful when required evidence is missing.
- [ ] Test profile proposals make no write; approval preserves unrelated concurrent preferences; conflicts within the proposed section fail atomically. Account identity/private wallet metadata never appears in model inputs.
- [ ] Run both files and CP2 profile/confirmation regressions; commit `feat(planning): execute confirmed domain invalidations and profile updates`.

### Task 8 — Contract synchronization and combined backend acceptance

**Files:** `contract/openapi.json`, generated frontend API, facade, MSW handlers/typed errors, `frontend/tests/post-plan-mocks.test.ts`; create `evals/test_cp4_acceptance.py`, `evals/test_cp4_boundaries.py`; update D1 runtime variable docs/guards for any new switches.

**Interfaces:** generated discriminated action/impact/workspace/errors match actual route behavior. No frontend screen is introduced; later UI uses these exact contracts.

- [ ] Define each route's real error models/statuses, including FastAPI validation unions. Generate OpenAPI and client twice, checking byte stability and no unexplained tracked diff.
- [ ] Add stateful mock tests for replay/conflicts, proposal versus applied state, explicit rejection, progress/failure, budget exhaustion, and result-specific saved revisions. Mock GET must not itself execute an action or append a revision.
- [ ] Run offline personas through interview → confirm → plan → initialize → propose → approve → explicit save → reopen SQLite. Different personas must yield material scoped differences, with exact untouched days and original revision bytes preserved.
- [ ] Include two-connection contention, restart after reservation, account deletion mid-work, legacy edit races, expired quotes, semantic no-op teeth, model/provider outage, and all quota failure paths. Confirm every declared intent and invalidation row has an exercised behavior.
- [ ] Verify AST boundaries: core imports no accounts/planning/agents/gateway/ingestion/API; pure planning does no network/SQL/nondeterminism; interpreter remains outside kernel graph; no crawler/cloud/native-Claude code enters CP4.
- [ ] Run `scripts/check-contract-drift.sh`, frontend `npx tsc --noEmit`, Vitest, lint/token checks, and production build. Changed existing frontend consumers must pass their applicable tests; defer new CP4 UI/browser acceptance explicitly.
- [ ] Commit `test(planning): verify conversational actions and synchronize contracts`.

### Task 9 — Independent review, documentation, and exact committed-tree gate

**Files:** `reports/cp4_backend_actions.md`, relevant current-state/index docs, `DEVIATIONS.md`; if brief checkpoint is updated, change `AGENTS.md` and `CLAUDE.md` identically.

- [ ] Record each new Tier-C default, artifact retention decision, phase boundary, and admitted-price correction. Keep older acceptance evidence historical.
- [ ] Obtain independent whole-branch review; fix verified Critical/Important findings with regression tests. Record rejected findings with evidence and deferred findings with concrete consequences.
- [ ] In a clean implementation worktree provision existing approved ignored regional catalogs, run `make seed`, then the full backend suite and required contract/frontend checks. Do not claim a baseline number from this planning document.
- [ ] Commit all implementation/report changes, then run `make gate` on that exact clean commit. Require `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`, and `GATE PASSED`. A report-only follow-up requires the final gate again.
- [ ] Record actual counts, exact SHA, full gate result, kernel/source diffs, remaining UI acceptance, operation recovery limitations, and provider status. Do not claim full CP4 completion, deployment, live acceptance, push, or merge.

## Execution order and handoff

Use three implementation sessions if needed: Tasks 1–3 (financial assembly, domain, storage), Tasks 4–5 (interpretation/API), Tasks 6–9 (scoped replanning, invalidation, contract/review/gates). Commit/checkpoint at task boundaries and record remaining work. These are sequential dependencies, not parallel branches with incompatible contracts.

Before execution verify A4's HEAD and PR status again. If PR #16 has merged, a normal branch from the merge is acceptable only after proving `a172c19` is its ancestor; otherwise stack from the exact A4 commit. Preserve A4 and every existing worktree. No merge of PR #16 is authorized by this plan.

## Self-review / requirement map

| Requirement | Owning task |
|---|---|
| Seven intents, deterministic first, one interpreter call/message | 2, 4, 5 |
| Financial correctness on final admitted cost lines | 1, 5–7 |
| Ownership, CAS, idempotency, durable consumed budgets, privacy | 3, 5, 8 |
| Confirmed facts/history preserved; no pre-plan amendment bypass | 2, 3, 7 |
| Scoped day changes, zero provider I/O, exact unaffected days | 6 |
| Invalidation table and explicit re-query confirmation | 2, 7 |
| Wallet consent, section-safe profile approval, explanation grounding | 5, 7 |
| Replay corpus, teeth tests, failure/expiry/restart acceptance | 3–8 |
| OpenAPI/client/MSW consistency | 8 |
| Independent review, frozen artifacts, exact clean commit gate | 9 |
| Synchronized conversation/visual UI and browser acceptance | Deferred CP4 UI phase; full CP4 remains pending |

No task grants new provider, credential, spend, cloud, booking, transfer, or spec-edit authority.

## Independent plan review

A separate read-only reviewer found no Critical issues and two Important planning defects. Both were fixed before handoff: impact calculation now receives the validated action and workspace context, and A4 first-save/append explicitly consume selected durable CP4 results with atomic version/attachment checks. Task 2 tests distinguish equal-brief actions; Task 5 tests first-save after approval/restart and concurrent apply/save. This is review of a plan, not acceptance of an implementation.
