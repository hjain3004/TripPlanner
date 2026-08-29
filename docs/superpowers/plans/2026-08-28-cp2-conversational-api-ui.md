# CP2 — Conversational Session API and Pre-Plan UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Expose CP1's deterministic interview and preference domain through authenticated APIs and a resumable, accessible pre-plan workspace that requires explicit Trip Brief confirmation before starting the existing non-live planning job.

**Architecture:** Keep `backend/planning/` authoritative for question policy, answers, Trip Brief assembly and session invariants. Add a thin authenticated API boundary that maps typed HTTP requests to that domain and to the existing legacy/sample planning job only after confirmation. Add a server-owned frontend state machine consuming structured session events; no browser storage, prose parsing, live providers or new LLM calls.

**Tech Stack:** FastAPI, Pydantic v2, SQLAlchemy/SQLite account persistence, Next.js/React/TypeScript, generated OpenAPI client, Zod, MSW, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-21-conversational-trip-planning-design.md`

## Global Constraints

- Read `CLAUDE.md`, `DEVIATIONS.md`, newest `reports/`, and spec 06 before work.
- Preserve frozen Kernel money math, four existing Kernel LLM call sites, golden fixtures, and `backend/core/` boundaries.
- No Gondola, Tripadvisor, other provider, booking, transfer, live LLM, or positive-spend call in CP2.
- `Build my trip` is the first possible planning/provider boundary and is idempotent.
- No `localStorage` or `sessionStorage`.
- OpenAPI, generated client, Zod schemas, MSW fixtures, consumers and contract tests ship together.
- Keep `AGENTS.md` and `CLAUDE.md` byte-identical; do not edit `docs/specs/`.
- Preserve unrelated user files in the main checkout; all work occurs in this worktree.

## Dependency Order and Parallelism

The coordinator owns the public contract, generated artifacts, integration, documentation and Git commits. Freeze request/response models before dispatching implementation workers.

After contract freeze, these lanes may run in parallel with disjoint files:

1. Backend session/profile services, routes and backend tests.
2. Interview/review presentational components and accessibility tests.
3. Profile-preferences page/components and accessibility tests.

Do not parallelize edits to `backend/api/main.py`, OpenAPI/generated files, Zod/MSW wrappers, shared design tokens, or final docs. Generate contracts once, then wire all consumers in sequence.

## Tasks

### Task 1: Freeze CP2 public contracts

**Files:** Create focused API contract modules under `backend/api/` as needed; tests under `backend/evals/`.

- Define typed request/response models for session creation/resume, answer/skip/amend, review, confirmation, planning-job reference/progress, preference read/update/reset/remove, conversation events, controls, and typed errors.
- Include user scope, optimistic `version`, idempotent `client_event_id`, confirmation readiness, profile source, pending proposals, assumptions and expiry.
- Prove malformed controls, stale versions, unknown question IDs, cross-user access and missing CSRF fail closed.
- Run focused tests and inspect the generated schema shape before implementation proceeds.

### Task 2: Harden CP1 preference approval semantics

**Files:** `backend/planning/brief.py`, `backend/accounts/store.py` or focused account module, backend tests.

- Write failing tests for partial profile updates, explicit reset/remove, trip-only overrides and all-empty/no-preference proposals.
- Implement the smallest merge/approval behavior that cannot erase unspecified or unrelated preference fields.
- Preserve audit/source metadata and privacy export/delete behavior.

### Task 3: Implement authenticated planning-session API

**Files:** Focused API router/service modules, `backend/api/main.py` only for registration, backend tests.

- Create/read/resume user-scoped sessions from profile defaults.
- Submit answers/skips with expected-version CAS and `client_event_id` idempotency.
- Support back/amend, deterministic review state, and confirmation exactly once.
- Reject confirmation until required facts and hard-constraint acknowledgement are complete.
- Return structured events and typed control definitions; never make the UI infer state from prose.
- Add provider/LLM tripwires proving nothing external runs before confirmation.

### Task 4: Implement confirmation-to-job boundary

**Files:** API planning service and focused tests; do not alter frozen Kernel internals without a documented ruling.

- Deterministically serialize confirmed `TripBrief` into the existing sample/legacy planning request.
- Start the existing planning job exactly once, preserve the confirmed snapshot, and return a job reference.
- Prove duplicate confirmation and concurrent confirmation cannot start two jobs.
- Preserve honest existing planning failures and progress semantics.

### Task 5: Generate and synchronize the contract

**Files:** `contract/openapi.json`, `frontend/src/lib/api/generated/`, `frontend/src/lib/api/schemas.ts`, `frontend/src/mocks/handlers.ts`, fixtures and contract tests.

- Regenerate OpenAPI and the Hey API client once from the implemented backend.
- Update hand-maintained wrappers/Zod schemas and MSW handlers without editing generated files manually.
- Add one-PR drift tests covering every CP2 route and response variant.

### Task 6: Build interview workspace presentation

**Files:** New focused components under `frontend/src/components/product/` and the appropriate app route; component tests.

- Render one primary question at a time with typed quick replies, multi-select, date/traveler controls, sliders where appropriate, optional free text, skip, back, review and progress.
- Show profile-derived versus trip-only values and deterministic acknowledgements.
- Render review sections for facts, defaults, trip-only choices, wallet/objective, delegated choices, assumptions and pending profile proposals.
- Keep `Build my trip` disabled until the API says the brief is ready.
- Preserve the existing light premium neo-brutalist/retrofuturist design and semantic tokens.

### Task 7: Build profile-preferences UI

**Files:** New profile route/components and focused tests.

- Display every stored preference group with source/update state.
- Support explicit edit, reset and remove actions with accessible confirmation.
- Use server state only; never browser storage.
- Keep cards, points and wallets in their existing account projection.

### Task 8: Wire server state, resume and failure behavior

**Files:** Frontend API/state hooks and page composition; MSW/E2E tests.

- Create/resume sessions after authentication and refresh.
- Submit versioned events, recover stale-version responses, prevent double submission and preserve visible state on errors.
- Map structured events directly to controls; do not parse assistant text.
- Show expiry, unauthorized, CSRF, validation, profile-write and planning-job failures honestly.

### Task 9: Accessibility and responsive acceptance

**Files:** Frontend tests and only necessary component fixes.

- Prove keyboard/screen-reader operation, focus movement, polite announcements, 44px targets, reduced motion and no 390px overflow.
- Test desktop, tablet and mobile review/confirmation paths.
- Use `design:accessibility-review` findings as actionable test cases.

### Task 10: End-to-end personas and gates

**Files:** `frontend/e2e/` and backend evaluation tests.

- Add deterministic solo-value, family-accessibility and flexible-delegating personas.
- Prove materially different confirmed briefs, refresh/resume, amendment, confirmation and exactly-once job start.
- Prove zero provider/LLM calls before confirmation and zero LLM calls in CP2.

### Task 11: Review, documentation and completion

- Run focused tests after every TDD cycle.
- Run `make gate` from a clean committed tree.
- Run frontend lint, typecheck, token lint, contract tests, build and relevant Playwright suites.
- Request and receive a full code review; fix Critical/Important findings test-first and re-review.
- Write `reports/cp2_conversational_api_ui.md` with actual test counts, product-run evidence, limitations and deviations.
- Update `AGENTS.md` and `CLAUDE.md` identically, including that PR #12 already merged G3 and that production Gondola integration is G3.4.
- Commit coherent changes; do not push, merge, deploy or activate live services.

## Acceptance Checklist

- [ ] Authenticated user can view/edit/reset/remove visible preferences.
- [ ] User can create, resume, answer, skip, amend and review a server-owned interview.
- [ ] Interview remains within the approved 8–12 decision policy.
- [ ] Profile defaults, trip-only overrides and explicit proposals remain distinct.
- [ ] Confirmation is mandatory and exactly once.
- [ ] Existing non-live planning starts only after confirmation and cannot double-start.
- [ ] No provider or LLM call occurs before confirmation; CP2 adds no LLM call.
- [ ] OpenAPI/generated/Zod/MSW/frontend contract is synchronized in one change set.
- [ ] Responsive and accessibility tests pass.
- [ ] Backend gate, frontend gates and full review pass from a clean tree.
