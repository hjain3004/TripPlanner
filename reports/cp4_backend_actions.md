# CP4 BACKEND COMPLETE; UI ACCEPTANCE PENDING

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
- Task 7 executes all four approved action classes offline: wallet/objective approval
  recomputes from the stored wallet, scoped replans splice only affected dates and
  persist local overrides, provider-invalidating approval refreshes only server-derived
  domains through the sample gateway with request/expiry checks, and profile approval
  atomically merges one preference section with same-section conflict detection.
  Explanation approval returns deterministic report-anchored text; approvals never
  autosave a trip revision.
- OpenAPI and the generated client are synchronized; repeated generation is byte-stable.
  MSW has stateful workspace/proposal/revision fixtures and no CP4 UI screen was added.

## Verification so far

- `make seed PY=.venv/bin/python`: passed; local seed catalog provisioned.
- Focused CP4/A4 tests: passed (including the corrected legacy A4 schema regression).
- Frontend: TypeScript passed; 12 Vitest files / 218 tests passed; ESLint reported
  only existing warnings; production build passed.
- Contract drift: `CONTRACT_DRIFT_OK`.
- Full backend suite on the final tree: 2203 passed, 1 skipped, 3 warnings.
- Strict mypy: clean across 185 backend source files plus 5 ingestion files.
  Zero-tolerance Ruff scopes: clean. Focused CP4/A4 regressions after review fixes:
  Complete focused CP4 suite: 197 passed.
- Frontend checks: TypeScript passed; 12 Vitest files / 218 tests passed; ESLint
  reported 0 errors and 14 existing warnings; production build passed.
- Browser suite with live tests disabled: 568 tests collected, 492 passed and 76
  skipped, with no failures. The 76 skips include the three disabled F4
  live-integration tests; generated visual captures were removed and checked-in
  baselines were restored.

## Independent review

The independent whole-branch review found one Critical and seven Important findings.
The Critical replay/redispatch finding was fixed by making operation fingerprints
independent of stale expected versions and returning the stored terminal outcome before
dispatch. Verified Important fixes add day-theme-aware deterministic scoped selection
and persisted day overrides, server-derived provider domains with request/expiry checks,
deterministic explanation artifacts, explicit post-plan error responses, and stateful
MSW revision replay/conflict behavior. The alleged revision race was not verified:
`add_revision()` already re-checks the selected workspace result/version inside its
single write transaction. Regression tests cover replay, stale wallet, profile-section
conflict/unrelated merge, all four execution classes, and explanation output.

## Boundaries and limitations

- No live provider, model, OAuth, credential, paid service, booking, transfer, or
  external network activation was used.
- The frontend workspace remains deferred; this is backend contract delivery only.
- Live provider/model activation remains disabled; provider-invalidating approval uses
  only the existing sample-only runtime construction and makes no live calls.
- Final `make gate` on commit `bfbde32093e9208f7e7607eb8d8a9904f064e4d5` passed:
  full backend tests, strict mypy, zero-tolerance Ruff, frozen goldens, contract
  checks, brief identity, and clean-tree verification. The fetched `origin/main`
  (`cef3a4d4acad1b46eb3642efa013510f509fab79`) was already an ancestor, so the
  normal integration merge was a no-op and no conflict resolution was required.
