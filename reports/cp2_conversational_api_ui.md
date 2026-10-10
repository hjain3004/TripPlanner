# CP2 — Conversational Session API and Pre-Plan UI

**Status:** Implemented on `feat/cp2-conversational-api-ui`; live providers and paid services remain disabled.

## Delivered

- Authenticated, user-scoped planning-session API under `/planning/sessions` with create/resume, typed answers, skips, review, amendment, profile-update approval, confirmation, and job polling.
- CSRF protection on every state-changing conversational/profile route; SQL-backed compare-and-swap versions and `client_event_id` idempotency are preserved from CP1.
- Persisted user-visible `ConversationEvent` records and an exact-once `planning_job_id` marker. Confirmation assembles and byte-validates the CP1 `TripBrief` before starting the existing non-live planning job; no provider search occurs before confirmation.
- Partial profile updates preserve unspecified groups; explicit reset/removal remains separate from trip-only answers.
- OpenAPI was regenerated from the FastAPI app; generated TypeScript SDK/types, the stable API facade, MSW fixtures, and frontend consumers were synchronized in the same change.
- New light, premium conversational UI components provide typed controls, explicit “No preference — choose for me”, progress, skip/back/review affordances, profile/trip source tags, assumptions, and confirmation gating. `/plan/conversation` is the authenticated pre-plan workspace; `/profile` exposes editable preference groups and persistence attempts through the profile API.

## Verification

- Historical CP2 baseline before CP2.1: `1256 passed, 1 skipped, 3 warnings`.
- CP2 API acceptance after CP2.1: `13 passed` (authentication/CSRF, typed idempotency and stale versions, profile preservation/removal, server-owned back/reload, structured transitions, concurrent confirmation, retryable start failure, and exact-once job handoff).
- Strict mypy: clean across 149 backend source files.
- Ruff: changed backend scope clean; pre-existing `api/` legacy warnings remain below the project ceiling.
- Frontend TypeScript: clean; ESLint: 0 errors (pre-existing warnings only); token lint: `0 violations`.
- OpenAPI generation completed with `npm run gen:api`; MSW planning/profile handlers added.

## Intentional follow-ups

- CP3 owns bounded LLM interview assistance and contradiction/free-text interpretation. CP2 uses the CP1 deterministic degraded continuation and never pretends an LLM call occurred.
- G3.4 owns wiring a confirmed `TripBrief` to Gondola/provider evidence. The confirmation boundary currently hands the brief to the existing non-live Kernel job exactly once.
- The profile page retains a deterministic preview fallback for unauthenticated local development; authenticated saves use the typed profile endpoint and never silently promote trip answers to durable memory.

## CP2.1 — Acceptance hardening closure

This remediation pass started from independent review reproductions rather than treating the original CP2 report as proof. Confirmed gaps included fabricated profile defaults, missing server-owned back navigation, invalid amendment payloads, duplicated frontend control vocabularies, lost resumed traveler state, insufficient confirmation-race recovery, absent browser coverage, and conflicting test counts.

The original failures were reproduced before implementation: stale confirmation raised `ValueError: snapshot.version (13) must equal expected_version + 1 (12)`, and a three-person party answer reached the API with an invalid `adults + children_ages` payload. The Gondola alias commit `bb4b3b1` was retained as valid scope; its regression test proves both snake_case and camelCase SDK fields without a live call.

### Delivered

- `go_back()` is a pure, persisted, user-scoped, CSRF/CAS/idempotent transition that removes the preceding answer and sanitizes inapplicable adaptive state. It is unavailable after confirmation except through amendment.
- `amend_answer()` validates the answer kind and structured payload, rebuilds the review brief, increments the version, and never mutates an earlier confirmed snapshot.
- `QuestionOut.control` is a Pydantic discriminated union rendered from the server. OpenAPI emits `oneOf` plus a `type` discriminator; generated TypeScript and the stable facade are regenerated. MSW includes session back, amendment, approval, confirmation and job handlers.
- Profile preferences are projected from authenticated server data for all six groups and all persisted fields. Save/reset/remove update the UI only after successful responses; failed writes preserve the draft and show an actionable message. No browser storage is used.
- Resume hydration preserves structured travelers, dates and prior answers. Child-age input is normalized to `number[]` before submission.
- Confirmation keeps one durable planning job id, is idempotent for duplicate events, and serializes racing event ids in-process. A post-persistence job-start failure becomes a retryable `planning_error`; the job manager remains process-local rather than a distributed lease.
- Chromium coverage proves unauthenticated handling, server-issued options, refresh-safe traveler hydration, profile success/failure/reset/remove, accessibility, and mobile overflow: **10/10 passed**. Service workers are blocked only in these route-mocking tests so deliberate HTTP failures are observable.

### Final verification

- Backend: `1266 passed, 1 skipped, 3 warnings` from one complete `cd backend && .venv/bin/pytest -q` run.
- Strict mypy: clean across 149 files.
- Frontend: TypeScript clean; Vitest `128 passed`; token lint `0 violations`; ESLint `0 errors` (14 pre-existing warnings); production build clean.
- Browser: conversational `4/4` and profile `6/6` Chromium tests passed; the profile axe run has no violations.
- No live provider, Gondola, LLM, booking, or paid service was activated.

### Independent review follow-up

The independent review found four Important issues and one Minor contract ambiguity, all fixed before completion: adaptive back now reconstructs full catalog order (so it reopens the last adaptive answer); a fresh party selection writes the displayed adult default and numeric child ages into the payload; confirmation failure reloads the persisted failed session so retry uses the new version; failed asynchronous jobs are reconciled into the durable session on job polling; and profile read–merge–write mutations are serialized in the process-local student runtime. `date_flexibility_days` is explicitly marked optional in the public control contract and excluded from completeness requirements unless present. Focused regression tests and the full gates were rerun after these fixes.

### Remaining boundaries

CP2.1 does not add CP3's bounded LLM interview assistance, CP4's post-plan intent routing, or G3.4's confirmed-brief Gondola wiring. Confirmation starts the existing non-live planning job only after explicit approval. Multi-process/distributed job claiming remains outside the student prototype scope and is documented as a limitation rather than presented as global exactly-once execution.
