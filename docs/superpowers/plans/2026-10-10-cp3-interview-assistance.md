# CP3 bounded interview assistance implementation plan

> **For agentic workers:** Use superpowers:executing-plans to execute and verify each task. Independent frontend work may run under superpowers:dispatching-parallel-agents; review the integrated branch afterward.

**Goal:** Add bounded semantic interview review and optional free-text interpretation to CP2, with durable call reservations and honest failure behavior.

**Architecture:** Keep `planning/` pure. Add strict suggestion contracts there and run the LLM in `agents/interview_assistant.py`. An HTTP adapter reserves calls through the existing session CAS repository, validates results, and persists only user-visible proposals and diagnostics. Typed answers and confirmation remain authoritative.

**Tech stack:** Existing Python/Pydantic/FastAPI/SQLite, Next.js/TypeScript, scripted and replay LLM clients, pytest, Vitest and Playwright. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-21-conversational-trip-planning-design.md`, especially §§5.2, 11–15.

## Global constraints

- One adaptive review in the normal live path; maximum two interview LLM invocations, including failures, across retries, concurrency, and SQLite reopen.
- Structured answers invoke zero LLM calls except the required checkpoint after the eighth core answer.
- One interpretation may precede that checkpoint; reserve the other slot for review. No schema repair or provider retries.
- At most four applicable catalog follow-ups and eight to twelve answered decisions.
- No autonomous answer/profile write, money math, provider search, or kernel graph change.
- Persist no model prompt, raw response, credential, full transcript, or account identifiers in the LLM input.
- Tests are offline; live use is separately configured and must meet the existing zero-spend profile.

## Review focus

- Concurrent requests and process interruption: reserve once, fail closed, preserve the remaining budget.
- Reused event IDs: identical input replays; changed input conflicts without a call.
- Hostile suggestions: reject unknown/inapplicable IDs, extra fields, unsupported numeric/prose claims and fiscal edits.
- Backtracking: reuses a validated identical semantic input; never resets the durable budget.
- Unavailable assistance: disclose degradation while typed controls and explicit confirmation still work.

## Task 1: strict contracts and assistant

Files: `backend/planning/assistance.py`, `backend/planning/contracts.py`, `backend/planning/policy.py`, `backend/agents/interview_assistant.py`, `backend/agents/llm.py`, `backend/evals/test_cp3_assistant.py`.

- [x] Write strict-output and adversarial tests before implementation; run pytest and observe missing-module failures.
- [x] Define catalog-ranked question proposals, grounded wording, answer candidates and exact-answer contradiction references. Expose a pure `applicable_adaptive_questions(session)` helper.
- [x] Implement `InterviewAssistant.review(session)` and `interpret(session, question_id, text)` through `LLMClient.complete_json`, with bounded compact inputs, strict validation and no repair.
- [x] Configure a distinct interview model using the existing hosted client with retries disabled and a one-call instance ceiling; retain the kernel client's defaults.
- [x] Add scripted replay cases for different personas and a no-op mutation assertion proving personalization depends on the response.
- [x] Run focused tests, strict mypy and Ruff.

## Task 2: durable API integration

Files: `backend/api/interview_assistance.py`, `backend/api/conversation.py`, `backend/evals/test_cp3_api.py`.

- [x] Test the checkpoint, interpretation proposals, authenticated/CSRF/user-scoped access, identical replay, conflicting event IDs, stale versions, concurrent reservations and persistence reopen.
- [x] Reserve each call with CAS before dispatch; store a canonical request fingerprint and a conservative interrupted diagnostic at reservation time.
- [x] Replace CP2's degraded-only seam with the assistant result, grounded acknowledgement and catalog wording; fall back to deterministic branches on failure.
- [x] Add `/planning/sessions/{id}/interpret` returning the existing `SessionOut` plus a proposed typed answer. Acceptance still uses the existing answer/amend route.
- [x] Persist contradiction references and require explicit answer review/amendment before confirmation; include recovery/resume behavior.
- [x] Run all CP1/CP2/CP3 tests and the complete backend suite.

## Task 3: frontend and synchronized contract

Files: `frontend/src/app/plan/conversation/page.tsx`, conversational components, API/MSW fixtures, generated API, `contract/openapi.json`, frontend tests and `frontend/e2e/cp3-assistance.spec.ts`.

- [x] Add optional interpretation controls, a reviewable candidate and explicit save action; preserve typed controls on failure/exhaustion.
- [x] Render server-authored personalized prompts and acknowledgements, and disclose degraded assistance without parsing prose for state.
- [x] Render contradiction review actions and prevent premature confirmation.
- [x] Regenerate OpenAPI/client in this branch and update MSW fixtures.
- [x] Verify TypeScript, Vitest, ESLint, tokens, production build and browser accessibility/resume/failure behavior.

## Task 4: review and acceptance

Files: `DEVIATIONS.md`, synchronized `AGENTS.md`/`CLAUDE.md`, `docs/CURRENT_STATE.md`, `reports/cp3_interview_assistance.md`.

- [x] Obtain a fresh whole-branch review; resolve verified Critical/Important findings with regression tests.
- [x] Record decisions, actual counts and limitations; preserve deferred G3.4/CP4/FI work.
- [x] Commit coherent local changes and run `make gate` on the exact committed clean tree.
- [x] Check spec/golden/seed/kernel preservation and report local branch/worktree/commit evidence.

Execution is authorized by the user's request to continue local development after the CP3 recommendation. No additional plan approval is required.
