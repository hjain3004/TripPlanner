# CP1 — Conversational Domain

**Milestone status:** backend domain implementation complete (backend domain only — see
"Explicit limitations" below); milestone-level review and final clean-tree `make gate`
confirmation pending, to be run by the orchestrating process after this report
**Branch:** `feat/cp1-conversational-domain`
**Base:** `main` @ `43c4191` (`git merge-base HEAD main` resolves to `43c419198ee596ae5164c9328fffc3c0bbce6d8f`, the same commit as `main`'s tip at merge-base time — this branch has not diverged from `main` other than by being ahead of it)
**Authoritative design:** `docs/superpowers/plans/2026-08-21-cp1-conversational-domain.md`
**Task briefs/reports:** `.superpowers/sdd/2026-08-21-cp1-conversational-domain/task-{1..7}-{brief,report}.md`

This report is written from evidence executed in this worktree on 2026-08-22 (test runs,
`make gate`, `git diff`, and direct reads of `backend/planning/`'s actual source). It does not
copy claims from the design plan or from task reports without independently confirming them
against the committed code.

Per project convention, this report does not name a "final commit hash." The commit created by
this task (Step 4, below) is a historical waypoint, not a permanent identifier of milestone
state — later review-fix commits (dispatched separately, after this report is written) will
move `HEAD` forward. Run `git log` / `git rev-parse HEAD` for the actual current state.

## 1. What CP1 is

CP1 builds a pure, deterministic conversational-planning *domain* — the typed data model,
persistence, and business rules for an 8-to-12-decision trip interview that resolves into a
confirmed, typed Trip Brief. It is not connected to any API route, any frontend, any LLM
call, or the production `/plan` pipeline. See "Explicit limitations" (§7) for the precise
boundary.

## 2. Branch/base and test counts

- **Base:** `main` @ `43c4191` (identical to the merge-base of `HEAD` and `main`).
- **Baseline (pre-CP1), per the last-recorded checkpoint in `CLAUDE.md`/`AGENTS.md`
  (2026-08-20):** 898 backend tests passing, strict mypy clean across 127 source files.
- **Final, measured on this worktree by an actual `make gate` run (2026-08-22, captured
  verbatim in §5 below):** **1071 passed, 1 skipped** (1072 collected), strict mypy clean
  across **134** source files.
- Net: CP1 added roughly 173 new passing tests and 7 new/expanded source files under strict
  mypy scope (`backend/planning/` — 6 modules — plus `backend/accounts/`'s existing files
  extended for travel preferences and planning-session storage).
- A CP1-focused subset (all 7 `evals/test_cp1_*.py` files plus the accounts A1/A2 regression
  suite, run with `CP1_MERGE_BASE` set so the merge-base-dependent boundary test actually
  runs instead of skipping) was also executed directly and is reproduced in §5.

## 3. New tables/models/modules and public method signatures

All signatures below were read directly from the committed source on 2026-08-22, not copied
from the design plan or task reports — several evolved during implementation (e.g.
`InterviewProgress` and `MAX_ADAPTIVE_DECISIONS` are not mentioned in the plan's own
interface list; they were added as internal decisions during tasks 5 and 3/5 respectively).

### `backend/planning/` (new package, 6 modules, strict-mypy-clean, zero non-test imports of
`agents`/`api`/`gateway`/network/LLM/SQL packages — see §4)

**`planning/answers.py`** — `QuestionId` (15-member `StrEnum`); 9 closed answer-payload
`BaseModel`s (`TripEssentialsPayload`, `PurposePartyPayload`, `BudgetObjectivePayload`,
`FlightPreferencesPayload`, `StayPreferencesPayload`, `DailyRhythmPayload`,
`ExperiencesFoodPayload`, `HardConstraintsPayload`, `AdaptiveDetailPayload`); the
`AnswerPayload` union; `ANSWER_TYPE_BY_QUESTION: dict[QuestionId, type[AnswerPayload]]`;
`PROFILE_UPDATE_ELIGIBLE_TYPES: frozenset[type[AnswerPayload]]` (exactly the six core payload
types that may propose a durable profile update); `InterviewAnswer` (question id, optional
typed payload, `delegated: bool`, `memory_scope: Literal["trip_only",
"propose_profile_update"]`, `client_event_id`, `answered_at`), whose model validator enforces
payload/question-type matching, delegated-answers-carry-no-payload, and the profile-update
eligibility gate.

**`planning/question_catalog.py`** — `QuestionDefinition` (frozen `BaseModel`: id, phase,
prompt, answer_kind, `required: bool`, `allow_delegate: bool`, priority, impact_domains,
profile_sections); `CORE_QUESTION_ORDER: tuple[QuestionId, ...]` (the 8 fixed core questions,
priorities 10-80); `ADAPTIVE_QUESTION_IDS: frozenset[QuestionId]` (the 7 adaptive questions,
priorities 110-170); `DEFAULT_QUESTION_CATALOG: tuple[QuestionDefinition, ...]` — the full,
code-defined 15-question catalog (see §4 for the "code-defined, not YAML" decision).

**`planning/contracts.py`** — `PlanningSessionStatus` (`StrEnum`: interviewing,
awaiting_assistant, reviewing, confirmed, planning, complete, failed, abandoned);
`AssistanceStatus` (`StrEnum`: not_run, complete, degraded); `TravelerHomeContext`;
`ProfileUpdateProposal` (`proposal_id`, `section`, `candidate_profile:
TravelPreferenceProfile`, `source_question_id`); `TripBrief` (typed, one field per section,
`None` when delegated, plus `adaptive_details`, `delegated_questions`,
`applied_profile_preferences`, `applied_profile_sections`, `assumptions`, `wallet:
UserWallet`); `ConfirmedBriefSnapshot` (`revision: int = Field(ge=1)`, `brief: TripBrief`,
`confirmed_at`); `PlanningSession` (id, user_id, status, `version: int = Field(ge=0)`,
timezone-aware `created_at`/`updated_at`/`expires_at`, home, wallet, `profile_defaults:
TravelPreferenceProfile | None`, `answers: dict[QuestionId, InterviewAnswer]`,
`current_question_id`, `suggested_question_ids`, `processed_event_ids`,
`assistance_status`, `interview_llm_calls: int = Field(default=0, ge=0, le=2)`,
`pending_profile_updates: list[ProfileUpdateProposal]`, `confirmed_briefs:
list[ConfirmedBriefSnapshot]`, `saved_trip_id`), whose model validator enforces
timezone-awareness, `updated_at >= created_at`, `expires_at > updated_at`, no duplicate
processed/suggested question ids, and strictly-increasing `confirmed_briefs` revisions.

**`planning/policy.py`** — the deterministic interview state machine. Module-level constants:
`MIN_DECISIONS = 8`, `MAX_DECISIONS = 12`, `MAX_ADAPTIVE_DECISIONS = 4`,
`SESSION_RETENTION = timedelta(days=30)`. Five typed errors under `PlanningPolicyError`
(`StaleSessionVersionError`, `UnexpectedQuestionError`, `DelegationNotAllowedError`,
`InvalidAssistantSuggestionError`). `InterviewProgress` (`completed`, `minimum_total`,
`maximum_total`, `status`). Public functions (all pure — `now` is always caller-injected):
- `start_interview(*, user_id: str, session_id: str, home: TravelerHomeContext, wallet:
  UserWallet, profile_defaults: TravelPreferenceProfile | None, now: datetime, expires_at:
  datetime) -> PlanningSession`
- `next_question(session: PlanningSession) -> QuestionDefinition | None`
- `record_answer(session: PlanningSession, answer: InterviewAnswer, *, expected_version: int,
  now: datetime) -> PlanningSession`
- `record_assistant_suggestions(session: PlanningSession, question_ids: list[QuestionId], *,
  assistance_status: Literal["complete", "degraded"], llm_calls: int, expected_version: int,
  now: datetime) -> PlanningSession`
- `interview_progress(session: PlanningSession) -> InterviewProgress`

**`planning/brief.py`** — deterministic Trip Brief assembly and confirmation. Three typed
errors (`BriefNotReadyError`, `BriefMismatchError`, `BriefAlreadyConfirmedError`; the fourth
stale-version case reuses `planning.policy.StaleSessionVersionError`). Public functions:
- `assemble_trip_brief(session: PlanningSession) -> TripBrief`
- `build_profile_update_proposals(session: PlanningSession, *, now: datetime) ->
  list[ProfileUpdateProposal]`
- `confirm_trip_brief(session: PlanningSession, brief: TripBrief, *, expected_version: int,
  now: datetime) -> PlanningSession`

**`planning/repository.py`** — `PlanningSessionRepository(store: AccountStore)`:
`create(session: PlanningSession) -> PlanningSession`; `get(*, user_id: str, session_id: str)
-> PlanningSession | None`; `save(session: PlanningSession, *, expected_version: int) ->
PlanningSession`; `list_for_user(user_id: str) -> list[PlanningSession]`;
`delete_expired(*, now: datetime) -> int`. Never imports SQLAlchemy or an engine/session
directly — every read/write delegates to the injected `AccountStore`.

### `backend/accounts/` (extended, not new)

- `accounts/models.py`: `TravelPreferenceProfile` (six preference groups —
  `FlightPreferences`, `StayPreferences`, `RhythmPreferences`, `ExperiencePreferences`,
  `ConstraintPreferences`, `OptimizationPreferences` — each field wrapped in
  `PreferenceValue[T]` carrying `source: PreferenceSource` and `updated_at`);
  `PreferenceSource = Literal["user_profile_edit", "user_confirmed_from_trip"]` (no
  `"llm_inferred"` member — see §4); `PlanningSessionSnapshot` (id, user_id, status, version,
  updated_at, expires_at, saved_trip_id, `payload_json: str` — explicitly documented as
  opaque; see §4).
- `accounts/db.py`: new `TravelPreferenceRow` (one row per user, `user_id` primary key +
  `payload` Text column) and `PlanningSessionRow` (id primary key, user_id, status, version,
  updated_at, expires_at, saved_trip_id, payload).
- `accounts/store.py`: `put_travel_preferences`/`get_travel_preferences`;
  `create_planning_session_snapshot`, `get_planning_session_snapshot` (ownership-scoped —
  a session belonging to a different user is indistinguishable from a nonexistent one),
  `put_planning_session_snapshot(..., *, expected_version: int)` (atomic compare-and-swap via
  a single SQL `UPDATE` whose `WHERE` matches id + owner + expected version; `rowcount != 1`
  raises `StalePlanningSessionError` rather than retrying or overwriting),
  `planning_session_snapshots(user_id) -> list[...]`, `delete_expired_planning_sessions(*,
  now: datetime) -> int` (never sweeps a session with `saved_trip_id` set, even past its own
  `expires_at`). `export_user` now includes `travel_preferences` and `planning_sessions`;
  `delete_user` now deletes `TravelPreferenceRow` and `PlanningSessionRow` for the user.

## 4. Proof of specific CP1 guarantees

### 4.1 Eight core plus bounded adaptive termination

`planning/question_catalog.py` fixes exactly 8 core questions
(`CORE_QUESTION_ORDER`, priorities 10-80, all `required=True`) and 7 adaptive questions
(`ADAPTIVE_QUESTION_IDS`, priorities 110-170, all `required=False`).
`planning/policy.py` caps how many of those 7 can actually be asked in one interview at
`MAX_ADAPTIVE_DECISIONS = 4`, and `record_assistant_suggestions` enforces `queue =
queue[:max(min(MAX_ADAPTIVE_DECISIONS, MAX_DECISIONS - total_answered), 0)]` — so a session
can never exceed `MAX_DECISIONS = 12` or fall below `MIN_DECISIONS = 8`.

This is proven, not just asserted, by a Hypothesis property test —
`backend/evals/test_cp1_policy.py:1077`,
`test_the_policy_always_terminates_within_eight_to_twelve_decisions`, `@given` a composite
strategy over purpose/children/adults/accessibility/points/max_stops/stay-tradeoff/food
(`@settings(max_examples=100, deadline=None)`). Each of the 100 generated example paths drives
a real `start_interview` → 8×`record_answer` → `record_assistant_suggestions(..., [],
assistance_status="degraded", llm_calls=0, ...)` → a bounded adaptive-answer loop (capped at
`MAX_ADAPTIVE_DECISIONS + 1` iterations so a genuinely stuck policy would fail the test rather
than hang), then asserts `session.status == REVIEWING`, `MIN_DECISIONS <=
len(session.answers) <= MAX_DECISIONS`, no duplicate answers, and `next_question(session) is
None`. A single hand-picked end-to-end persona is also exercised in
`evals/test_cp1_acceptance.py` (11 decisions: 8 core + 3 adaptive), independently verified
non-vacuous by flipping `points_priority` and confirming the adaptive queue changes
(`task-7-report.md` §"Verification").

### 4.2 Profile writes require explicit consent data; no LLM inference is durable

`accounts.models.PreferenceSource = Literal["user_profile_edit",
"user_confirmed_from_trip"]` has no `"llm_inferred"` (or similar) member — a durable
preference can only be attributed to a direct profile edit or an explicit in-trip
confirmation, never to a model's guess. `InterviewAnswer.memory_scope` is a closed
`Literal["trip_only", "propose_profile_update"]`, gated by `PROFILE_UPDATE_ELIGIBLE_TYPES`
(exactly the 6 core payload types with a durable profile section).
`planning.brief.build_profile_update_proposals` builds fully typed
`ProfileUpdateProposal(candidate_profile: TravelPreferenceProfile, ...)` objects but never
calls `AccountStore.put_travel_preferences` — it does not even receive a store instance,
enforced structurally (the function's own signature takes only `session` and `now`). This is
proven directly by `evals/test_cp1_brief.py:787`,
`test_build_profile_update_proposals_does_not_call_put_travel_preferences`. `confirm_trip_brief`
stores the proposals only as data on `session.pending_profile_updates`; no code path anywhere
in `planning/` performs the actual write.

### 4.3 Optimistic concurrency, idempotency, ownership, expiry, export, and deletion

- **Optimistic concurrency:** `accounts.store.AccountStore.put_planning_session_snapshot(...,
  *, expected_version: int)` issues one SQL `UPDATE ... WHERE id = ? AND user_id = ? AND
  version = ?`; `rowcount != 1` raises `StalePlanningSessionError` instead of retrying or
  overwriting (`backend/accounts/store.py:229-270`). Proven by
  `evals/test_cp1_session_store.py:175`,
  `test_repository_rejects_a_stale_compare_and_swap`. `planning.policy.record_answer` and
  `record_assistant_suggestions` independently re-check `expected_version != session.version`
  and raise `StaleSessionVersionError` before touching state — proven by
  `evals/test_cp1_policy.py:280` and `:785`, and by
  `test_a_stale_expected_version_fails_on_the_second_call_of_a_two_call_sequence` (`:339`).
- **Idempotency:** `record_answer` returns the session unchanged, before the version check
  even runs, whenever `answer.client_event_id` is already in
  `session.processed_event_ids` — a genuine retry's stale `expected_version` must not win a
  race against idempotency. Proven by `evals/test_cp1_policy.py:269`,
  `test_a_repeated_client_event_id_is_idempotent_and_does_not_bump_version`.
- **Ownership:** `get_planning_session_snapshot` returns `None` for a session id that belongs
  to a different `user_id` — "exists but not yours" is indistinguishable from "does not
  exist" (`backend/accounts/store.py:214-227`). Proven by
  `evals/test_cp1_session_store.py:193` (`test_get_returns_none_for_a_different_user`) and
  `:199` (`test_save_rejects_a_cross_user_update`).
- **Expiry:** `delete_expired_planning_sessions(*, now)` hard-deletes sessions past
  `expires_at` unless `saved_trip_id` is set. Proven by
  `evals/test_cp1_session_store.py:260`
  (`test_delete_expired_removes_an_abandoned_session_past_its_expiry`) and `:273`
  (`test_delete_expired_retains_a_session_attached_to_a_saved_trip`). `expires_at` itself is
  a required, caller-injected parameter of `start_interview` — CP1 has no caller that
  derives it from `planning.policy.SESSION_RETENTION = timedelta(days=30)`; that constant
  is defined for a future caller to use, and the 30-day window seen in tests is a fixture
  convention, not enforced behavior.
- **Export/deletion:** `AccountStore.export_user` includes both `travel_preferences` and
  `planning_sessions`; `delete_user` deletes both `TravelPreferenceRow` and
  `PlanningSessionRow` for the user. Proven by
  `evals/test_cp1_preferences.py::test_privacy_export_and_delete_include_travel_preferences`,
  `evals/test_cp1_session_store.py:293` (`test_export_user_includes_planning_sessions`), and
  `:303` (`test_delete_user_removes_planning_sessions`).
- **Round-trip across a real SQLite reopen:** `evals/test_cp1_acceptance.py`'s single
  end-to-end test opens a real temporary SQLite `AccountStore`, drives a full 11-decision
  interview to a confirmed brief, then opens a **second, independent**
  `AccountStore.open(db_path)` against the same file and asserts full session equality plus
  byte-identical confirmed-brief JSON.

### 4.4 `planning/` imports no LLM/provider/network/SQL packages

`evals/test_cp1_boundaries.py::test_planning_package_has_no_network_llm_provider_or_sql_imports`
is an AST walk over every file under `backend/planning/`, checking first-party and
third-party imports against the forbidden set `{"agents", "api", "gateway", "httpx",
"requests", "mcp", "sqlalchemy"}`. A second, independent AST-based guard
(`test_planning_never_calls_a_nondeterministic_clock_or_id_source`) walks every `ast.Call`
node in `planning/` and flags any call resolving (directly or through import-alias
resolution) to `datetime.now`, `date.today`, `uuid4`, or anything starting `random.`/
`secrets.` — deliberately AST-based rather than regex/text-based, because `policy.py`'s own
module docstring narrates these exact call shapes in prose to document their absence, and a
text scan would false-positive on that honest documentation (verified both directions:
synthetic snippets with real occurrences of all five forms are flagged; the real `planning/`
tree is not). `planning/repository.py`'s own module docstring states directly: "This module
never touches SQLAlchemy or a database engine/session directly." All of this is exercised as
part of the real `evals/test_cp1_*.py` and `make gate` runs in §5.

## 5. Exact commands and outcomes

### Focused CP1 suite (7 `evals/test_cp1_*.py` files plus the accounts A1/A2 regression suite,
with `CP1_MERGE_BASE` set so the merge-base-dependent contract/goldens-drift boundary test
runs rather than skipping), executed 2026-08-22 from `backend/`:

```
$ CP1_MERGE_BASE="$(git merge-base HEAD main)" .venv/bin/pytest -q \
  evals/test_cp1_acceptance.py evals/test_cp1_boundaries.py evals/test_cp1_policy.py \
  evals/test_cp1_answers_catalog.py evals/test_cp1_brief.py evals/test_cp1_session_store.py \
  evals/test_cp1_preferences.py evals/test_no_committed_secrets.py evals/test_no_stubs.py \
  evals/test_a1_*.py evals/test_a2_*.py -v
```

```
collected 280 items
evals/test_cp1_acceptance.py .                                           [  0%]
evals/test_cp1_boundaries.py ........                                    [  3%]
evals/test_cp1_policy.py .................................................. [ 22%]
evals/test_cp1_answers_catalog.py ..................................     [ 34%]
evals/test_cp1_brief.py ......................................           [ 47%]
evals/test_cp1_session_store.py ..................                       [ 54%]
evals/test_cp1_preferences.py .....................                      [ 61%]
evals/test_no_committed_secrets.py ...                                   [ 62%]
evals/test_no_stubs.py ....                                              [ 64%]
evals/test_a1_boundary.py .....
evals/test_a1_models.py ...................
evals/test_a1_projection.py ......
evals/test_a1_store.py ............................
evals/test_a2_api.py ...........
evals/test_a2_passwords.py .......
evals/test_a2_store.py ........................
======================== 280 passed, 1 warning in 3.64s ========================
```

### Full backend gate, executed from the worktree root 2026-08-22:

```
$ git status --short --branch
## feat/cp1-conversational-domain
```
(empty — clean tree before the run)

```
$ make gate
```

```
--- pytest (full suite) ---
cd backend && .venv/bin/pytest -q
........................................................................ [  6%]
........................................................................ [ 13%]
........................................................................ [ 20%]
..................................s..................................... [ 26%]
........................................................................ [ 33%]
........................................................................ [ 40%]
........................................................................ [ 47%]
........................................................................ [ 53%]
........................................................................ [ 60%]
........................................................................ [ 67%]
........................................................................ [ 73%]
........................................................................ [ 80%]
........................................................................ [ 87%]
........................................................................ [ 94%]
................................................................         [100%]
=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/fastapi/testclient.py:1
  .../starlette.testclient StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.

evals/test_i4_benchmark.py::test_ortools_outperforms_or_matches_greedy
  <frozen importlib._bootstrap>:491: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute
evals/test_i4_benchmark.py::test_ortools_outperforms_or_matches_greedy
  <frozen importlib._bootstrap>:491: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute
evals/test_i4_benchmark.py::test_ortools_outperforms_or_matches_greedy
  <frozen importlib._bootstrap>:491: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

1071 passed, 1 skipped, 4 warnings in 76.39s (0:01:16)
--- mypy --strict (every source package) ---
cd backend && .venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/
Success: no issues found in 134 source files
--- ruff (zero-tolerance scope) ---
cd backend && .venv/bin/ruff check accounts/ planning/ agents/ gateway/ evals/
All checks passed!
--- ruff (core/ + api/: legacy debt, ratcheted, must not grow) ---
core/ + api/ ruff findings: 7 (ceiling 12)
  NOTE: these are pre-existing M1/M1b findings. ...
--- frozen artifacts ---
GOLDENS_OK
CONTRACT_OK (unchanged, or changed with codegen and fixtures)
BRIEFS_IDENTICAL
--- working tree ---
TREE_CLEAN

================ GATE PASSED ================
```

(The 1 skip in the full-suite pytest run is the same `CP1_MERGE_BASE`-gated boundary test
noted above — it does not skip when the environment variable is set, as shown in the focused
run. This is expected, pre-existing, brief-mandated skip behavior for a bare `pytest -q`
invocation, not a defect.)

This is the same `make gate` invocation the brief's Step 6 (out of scope for this task; run
later by the orchestrating process after any review-fix commits) will run again as the actual
gate-passing confirmation. This run's purpose is report accuracy, not final signoff.

Legacy `core/`+`api/` ruff debt (7, ceiling 12) and pre-existing SWIG deprecation warnings
from `evals/test_i4_benchmark.py` predate CP1 and were not touched by it.

### Frozen-path drift check (evidence gathering only, not a substitute for the brief's own
Step 7, which runs after this task):

```
$ git diff --exit-code "$(git merge-base HEAD main)" HEAD -- backend/evals/golden/ \
  contract/openapi.json frontend/ backend/agents/pipeline.py backend/gateway/
```
Exit code 0 (no output) — no drift in any of these frozen/out-of-scope paths as of this run.

## 6. Architecture boundary confirmation

`backend/planning/` imports only `core` (`UserWallet`) and `accounts` (`TravelPreferenceProfile`,
`AccountStore`, `PlanningSessionSnapshot`) among first-party packages — never `agents`, `api`,
or `gateway` — enforced by `evals/test_cp1_boundaries.py`. `backend/core/` continues to import
nothing from `accounts/`, `planning/`, `agents/`, or `api/` (pre-existing invariant, unaffected
by CP1). `backend/agents/pipeline.py` and every file under `backend/gateway/` are byte-identical
to `main` (§5's frozen-path drift check). `contract/openapi.json` and `frontend/` are untouched.
`backend/evals/golden/` is untouched (`GOLDENS_OK` in the gate run above).

## 7. Explicit limitations

CP1 is a backend domain package only. Specifically, CP1 does **not** include:

- **No API.** No FastAPI route exists for starting, answering, or confirming an interview.
  `backend/api/main.py` is untouched.
- **No UI.** No frontend component, page, or wizard exists for the conversational interview.
  `frontend/` is untouched.
- **No LLM invocation.** `record_assistant_suggestions` only *applies* an already-computed
  assistance result to deterministic catalog rules — it performs no LLM call itself, and
  nothing in `planning/` imports an LLM client. The four Kernel MVP LLM call sites (intake,
  planner, critic, explainer) are unchanged.
- **No provider call.** `planning/` has no network, HTTP, or provider-adapter imports at all
  (AST-enforced, §4.4).
- **No production `/plan` integration.** `agents/pipeline.py` is byte-identical to `main` —
  the conversational domain is not wired into the request-time planning flow in any way.
- **No post-plan chat.** CP1 ends at a confirmed Trip Brief; there is no mechanism here for
  editing a plan through conversation after it exists.
- **No profile writes.** `build_profile_update_proposals` produces typed candidates but never
  calls `AccountStore.put_travel_preferences` (§4.2) — approval and the actual write are
  entirely CP2's responsibility.
- **No amendment path.** `confirm_trip_brief` is the sole way a session gets its first
  `ConfirmedBriefSnapshot`; an already-confirmed session can never be reconfirmed in CP1
  (`BriefAlreadyConfirmedError`). Revision 2+ is CP2's responsibility.

## 8. Next milestone

**The next milestone is CP2** (conversational API, authenticated preference endpoints, a
resumable frontend, typed controls, review/amend UI, and mandatory-confirmation job start) —
**not G3.4** (confirmed-brief production gateway/Gondola integration and public evidence
contract) **and not CP3** (required adaptive LLM review, free-text interpretation, replay
corpus, teeth tests, model routing, two-call interview ceiling, degraded assistance UI) out
of order. CP4 (post-plan natural-language intent routing, deterministic edit dispatch, scoped
replanning, provider invalidation confirmation, synchronized chat/workspace UI) and CP5
(cross-persona/live bounded acceptance, full responsive/a11y polish, final program gate)
remain further out. See `docs/superpowers/plans/2026-08-21-cp1-conversational-domain.md`
("Explicitly Deferred") for the authoritative scope statement of each.

## 9. Concerns

- The full-gate `pytest -q` run (76.39s) is dominated by pre-existing, non-CP1 suites
  (catalog builds, optimizer/pathfinder golden tests, etc.); CP1's own focused suite runs in
  under 4 seconds. No performance concern specific to CP1 was found.
- `core/`+`api/` legacy ruff debt sits at 7 findings against a ceiling of 12, unchanged by
  this milestone — noted for visibility, not a CP1 defect.
- Task 6's `DEVIATIONS.md` (task-6 review round 1 entry) flags a real, deliberately unresolved
  design tension for CP2 to account for: a `ProfileUpdateProposal` built from a group where
  every answer was `no_preference`/empty is a silent full-group wipe if ever approved and
  written as-is (the `StayPreferences.loyalty_programs` case is total and permanent, since no
  CP1 question can populate it). This is flagged, not fixed, in CP1 — CP1 never writes a
  proposal to the database at all, so nothing is destroyed today regardless.
