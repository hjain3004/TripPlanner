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

- Backend regression: `1256 passed, 1 skipped, 3 warnings`.
- CP2 API acceptance: `4 passed` (authentication/CSRF, typed idempotency and stale versions, profile preservation/removal, and exact-once confirmation/job handoff).
- Strict mypy: clean across 149 backend source files.
- Ruff: changed backend scope clean; pre-existing `api/` legacy warnings remain below the project ceiling.
- Frontend TypeScript: clean; ESLint: 0 errors (pre-existing warnings only); token lint: `0 violations`.
- OpenAPI generation completed with `npm run gen:api`; MSW planning/profile handlers added.

## Intentional follow-ups

- CP3 owns bounded LLM interview assistance and contradiction/free-text interpretation. CP2 uses the CP1 deterministic degraded continuation and never pretends an LLM call occurred.
- G3.4 owns wiring a confirmed `TripBrief` to Gondola/provider evidence. The confirmation boundary currently hands the brief to the existing non-live Kernel job exactly once.
- The profile page retains a deterministic preview fallback for unauthenticated local development; authenticated saves use the typed profile endpoint and never silently promote trip answers to durable memory.
