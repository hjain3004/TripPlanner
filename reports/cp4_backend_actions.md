# CP4 backend actions — ACCEPTANCE PENDING

This report records the CP4 backend checkpoint on `codex/cp4-backend-actions`.
It does not claim UI acceptance, live activation, provider activation, or deployment.

## Implemented evidence

- Task 4 semantic interpretation is bounded to one `complete_json` call, uses a
  separate zero-spend configuration, redacts sensitive text, grounds outputs against
  approved context, and distinguishes malformed model output from transport failure.
- Task 5 exposes authenticated workspace initialization/read, proposal, approval,
  rejection, and explicit workspace-revision-save routes. Durable reservations and
  result commits remain the account-store CAS boundary.
- Task 6 adds transport-free pinned inventory reuse and server-controlled inventory
  domain selection. The existing default remains both domains and sample-only; the
  admitted snapshot is now captured on gateway job completion for future workspace
  retention.
- OpenAPI and the generated client are synchronized; repeated generation is byte-stable.
  MSW has stateful workspace/proposal fixtures and no CP4 UI screen was added.

## Verification so far

- `make seed PY=.venv/bin/python`: passed; local seed catalog provisioned.
- Focused CP4/A4 tests: passed (including the corrected legacy A4 schema regression).
- Frontend: TypeScript passed; 12 Vitest files / 218 tests passed; ESLint reported
  only existing warnings; production build passed.
- Contract drift: `CONTRACT_DRIFT_OK`.
- Full backend suite after the compatibility fix: 2193 passed, 1 skipped.
- Strict mypy: clean across 161 backend source files. Zero-tolerance Ruff scopes:
  clean. Focused CP4/A4 regressions after review fixes: 120 passed.

## Independent review

The independent whole-branch review found one Critical and seven Important findings.
Verified fixes include: fail-closed unsupported approvals instead of reporting success,
sanitized semantic text before durable reservation, active-operation marking around
interpreter/recompute work, exact accepted-result bytes for A4 selection, fingerprints
bound to result/version selection, atomic workspace checks inside A4 store transactions,
strict number/date grounding, legacy recompute blocking once CP4 owns a session, and
contract regeneration after removing runtime-only error-code casts. The retained
admitted snapshot is captured from gateway job completion, and A4 store methods
re-check result/version selection inside their write transactions. Reviewer's focused
regression set passed after the fixes.

## Boundaries and limitations

- No live provider, model, OAuth, credential, paid service, booking, transfer, or
  external network activation was used.
- The frontend workspace remains deferred; this is backend contract delivery only.
- Provider-invalidating, scoped-replan, and profile-approval execution remain
  explicitly fail-closed until their offline deterministic execution paths are wired;
  they never report a false successful approval or make provider calls.
- Exact-clean-tree `make gate` remains pending.
