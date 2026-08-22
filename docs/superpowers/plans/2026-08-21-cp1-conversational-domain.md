# CP1 Conversational Planning Domain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the persisted preference profile, strict interview contracts, deterministic
question policy, resumable planning-session domain, confirmed Trip Brief, privacy behavior, and
test gates that CP2–CP5 can safely build on.

**Architecture:** `backend/accounts/` remains the only database write boundary for user-owned
state. A new pure `backend/planning/` package owns conversational contracts and deterministic state
transitions, while a small repository adapter serializes those models through opaque typed
snapshots in `AccountStore`. CP1 adds no API route, frontend UI, LLM call, provider call, or change
to the frozen Kernel pipeline.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, SQLite, pytest, Hypothesis, strict mypy,
Ruff.

**Spec:** `docs/superpowers/specs/2026-08-21-conversational-trip-planning-design.md`

## Global Constraints

- Read `CLAUDE.md`, `DEVIATIONS.md`, the newest report, `docs/specs/06_implementation_protocol.md`,
  `docs/specs/17_accounts_and_persistence.md`, and the design spec above before editing.
- Execute in an isolated worktree created with `superpowers:using-git-worktrees`; suggested branch:
  `feat/cp1-conversational-domain`.
- Start from the integration branch that already contains this design commit. Do not stack CP1 on
  an unmerged implementation branch unless the human explicitly chooses that base.
- Capture the actual baseline with `make gate` before Task 1. Do not copy historical test counts
  from `CLAUDE.md` into the report as if they were current.
- `docs/specs/` is read-only. The approved dated design is the authority for this scope.
- CP1 contains no FastAPI route, OpenAPI change, frontend change, LLM call, MCP/provider call,
  live network call, or positive external spend.
- `backend/core/` imports neither `accounts/` nor `planning/`. `accounts/` imports neither
  `planning/`, `agents/`, nor `api/`. `planning/` may import typed values from `core/` and
  `accounts/`, but imports neither `agents/`, `api/`, nor `gateway/`.
- `AccountStore` remains the only public database write boundary. `planning/repository.py` delegates
  persistence to it and contains no SQLAlchemy session or engine access.
- Every stored model inherits `AccountModel` and therefore uses `extra="forbid"`. Never store PAN,
  expiry, CVV/CVC, PIN, bank credentials, loyalty passwords, raw provider responses, hidden model
  reasoning, or secrets.
- All time and IDs are injected. No new domain function calls `datetime.now()`, `date.today()`,
  `uuid4()`, or random APIs internally.
- The normal interview remains 8–12 decisions: exactly eight core questions followed by zero to
  four applicable adaptive questions. Required facts and explicit hard-constraint acknowledgement
  cannot be delegated.
- CP1 provides an assistant-suggestion seam but invokes no LLM. CP3 owns the required adaptive LLM
  call, replay fixtures, and call budgets.
- No provider can be invoked before mandatory confirmation. CP1 proves this structurally by keeping
  `planning/` free of `gateway/` imports; CP2/G3.4 later add runtime call-order tests.
- Do not alter `agents/pipeline.py`, `agents/intake.py`, `agents/planner.py`, gateway adapters,
  optimizer/pathfinder behavior, frozen goldens, `contract/openapi.json`, or frontend files.
- Use TDD for every behavior change: failing test, observed failure, minimal implementation,
  passing focused test, then commit.
- Every judgment call is logged in `DEVIATIONS.md`. Final milestone documentation must describe
  what is genuinely implemented and explicitly list CP2/CP3/G3.4/CP4 as unimplemented.
- If `AGENTS.md` or `CLAUDE.md` is edited, they remain byte-identical.

---

## Locked File Map

### New production files

- `backend/planning/__init__.py` — package marker and intentionally small public surface.
- `backend/planning/answers.py` — strict question IDs, answer payloads, delegation/memory scope,
  and answer-to-question validation.
- `backend/planning/question_catalog.py` — complete approved core/adaptive catalog and metadata.
- `backend/planning/contracts.py` — planning-session, progress, Trip Brief, confirmation, and
  profile-update-proposal models.
- `backend/planning/policy.py` — pure start/next/answer/suggestion/review transitions and adaptive
  applicability rules.
- `backend/planning/brief.py` — deterministic brief assembly, preference-update proposals, and
  confirmation transition.
- `backend/planning/repository.py` — typed serializer/delegator over `AccountStore`; no direct SQL.

### Existing production files modified

- `backend/accounts/models.py` — durable preference models, opaque planning-session snapshot, and
  privacy export additions.
- `backend/accounts/db.py` — `travel_preferences` and `planning_sessions` tables.
- `backend/accounts/store.py` — preference/session CRUD, optimistic version enforcement, expiry,
  export, and delete integration.
- `backend/pyproject.toml` — package the new `planning` module.
- `Makefile` — include `planning/` in strict type and zero-tolerance lint gates.
- `backend/evals/test_no_stubs.py` — scan `planning/` as production code.

### New tests

- `backend/evals/test_cp1_boundaries.py`
- `backend/evals/test_cp1_preferences.py`
- `backend/evals/test_cp1_answers_catalog.py`
- `backend/evals/test_cp1_session_store.py`
- `backend/evals/test_cp1_policy.py`
- `backend/evals/test_cp1_brief.py`
- `backend/evals/test_cp1_acceptance.py`

### Milestone documentation

- `reports/cp1_conversational_domain.md`
- `DEVIATIONS.md`
- `AGENTS.md`
- `CLAUDE.md`

---

### Task 1: Establish the pure planning package and enforce its boundaries

**Files:**
- Create: `backend/planning/__init__.py`
- Create: `backend/evals/test_cp1_boundaries.py`
- Modify: `backend/pyproject.toml`
- Modify: `Makefile`
- Modify: `backend/evals/test_no_stubs.py`

**Interfaces:**
- Consumes: existing AST import-boundary pattern from `backend/evals/test_a1_boundary.py`.
- Produces: importable `planning` package included in packaging, strict mypy, Ruff, and stub scans.

- [ ] **Step 1: Write the failing boundary and gate-scope tests**

Create `backend/evals/test_cp1_boundaries.py` with an AST helper copied by value from the existing
boundary test and these assertions:

```python
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _first_party_imports(path: Path) -> set[str]:
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _offenders(package: str, forbidden: set[str]) -> list[str]:
    root = BACKEND / package
    return [
        str(path.relative_to(BACKEND))
        for path in sorted(root.rglob("*.py"))
        if forbidden & _first_party_imports(path)
    ]


def test_planning_package_exists() -> None:
    assert (BACKEND / "planning" / "__init__.py").is_file()


def test_core_never_imports_planning_or_accounts() -> None:
    assert _offenders("core", {"planning", "accounts"}) == []


def test_accounts_never_imports_planning_agents_or_api() -> None:
    assert _offenders("accounts", {"planning", "agents", "api"}) == []


def test_planning_is_pure_domain_code() -> None:
    assert _offenders("planning", {"agents", "api", "gateway"}) == []
```

Extend `test_no_stubs.py` so `PRODUCTION_PACKAGES` includes `"planning"`. Add a test that reads
`backend/pyproject.toml` and the root `Makefile` and asserts `planning` appears in the package list,
mypy command, and zero-tolerance Ruff command.

- [ ] **Step 2: Run the focused tests and observe the expected failure**

Run:

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_boundaries.py evals/test_no_stubs.py
```

Expected: `test_planning_package_exists` fails because the package does not exist, and the new gate
scope assertion fails because packaging/type/lint scopes omit `planning`.

- [ ] **Step 3: Add the package and wire it into every production gate**

Create an empty `backend/planning/__init__.py`. Add `"planning"` to the setuptools `packages` list.
Change the `make gate` strict commands to:

```make
cd $(BACKEND) && .venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/
cd $(BACKEND) && .venv/bin/ruff check accounts/ planning/ agents/ gateway/ evals/
```

Do not lower or alter any existing gate. Add `"planning"` to `PRODUCTION_PACKAGES` in
`test_no_stubs.py`.

- [ ] **Step 4: Run focused tests and static checks**

Run:

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_boundaries.py evals/test_no_stubs.py
.venv/bin/mypy --strict planning/
.venv/bin/ruff check planning/ evals/test_cp1_boundaries.py evals/test_no_stubs.py
```

Expected: all commands pass.

- [ ] **Step 5: Commit the package boundary**

```bash
git add Makefile backend/pyproject.toml backend/planning/__init__.py \
  backend/evals/test_cp1_boundaries.py backend/evals/test_no_stubs.py
git commit -m "chore(planning): establish conversational domain boundary"
```

---

### Task 2: Add visible, typed, consent-based travel preference storage

**Files:**
- Modify: `backend/accounts/models.py`
- Modify: `backend/accounts/db.py`
- Modify: `backend/accounts/store.py`
- Modify: `backend/evals/test_a1_boundary.py`
- Modify: `backend/evals/test_a1_models.py`
- Modify: `backend/evals/test_a1_store.py`
- Create: `backend/evals/test_cp1_preferences.py`

**Interfaces:**
- Consumes: `AccountModel`, `AccountStore`, `UserExport`, `FORBIDDEN_FIELD_NAMES`.
- Produces: `PreferenceValue[T]`, grouped preference models, `TravelPreferenceProfile`,
  `AccountStore.put_travel_preferences()`, and `AccountStore.get_travel_preferences()`.

- [ ] **Step 1: Write failing model tests for typed preferences and consent provenance**

Define tests that construct the following public interface:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from accounts.models import (
    Cabin,
    ExperiencePreferences,
    FlightPreferences,
    PreferenceValue,
    TravelPreferenceProfile,
)

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_preference_value_requires_an_explicit_human_source() -> None:
    value = PreferenceValue[str](
        value="business",
        source="user_confirmed_from_trip",
        updated_at=NOW,
    )
    assert value.source == "user_confirmed_from_trip"


def test_llm_inference_is_not_a_durable_preference_source() -> None:
    with pytest.raises(ValidationError):
        PreferenceValue[str](value="business", source="llm_inferred", updated_at=NOW)


def test_profile_groups_stable_travel_defaults() -> None:
    profile = TravelPreferenceProfile(
        user_id="u1",
        flight=FlightPreferences(
            cabin=PreferenceValue[Cabin](
                value="economy", source="user_profile_edit", updated_at=NOW
            )
        ),
        experiences=ExperiencePreferences(
            interests=PreferenceValue[list[str]](
                value=["food", "nature"],
                source="user_confirmed_from_trip",
                updated_at=NOW,
            )
        ),
        updated_at=NOW,
    )
    assert profile.flight.cabin is not None
    assert profile.experiences.interests is not None


def test_nested_preference_models_reject_unknown_sensitive_fields() -> None:
    with pytest.raises(ValidationError):
        FlightPreferences.model_validate({"pan": "4111111111111111"})
```

Also test deterministic trimming/de-duplication of list preferences, valid enum ranges, nonnegative
transit/downtime values, and rejection of a full card number or password at every nested level.

- [ ] **Step 2: Run the model tests and verify they fail on missing imports**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_preferences.py -k "preference or profile"
```

Expected: collection fails because the preference models do not exist.

- [ ] **Step 3: Implement the complete typed preference model**

Add these types to `accounts/models.py` after `UserProfile`. Use `AccountModel` for every nested
model and Pydantic `Annotated` bounds for numeric fields.

```python
from typing import Annotated, Generic, TypeVar

PreferenceSource = Literal["user_profile_edit", "user_confirmed_from_trip"]
T = TypeVar("T")


class PreferenceValue(AccountModel, Generic[T]):
    value: T
    source: PreferenceSource
    updated_at: datetime


Cabin = Literal["economy", "premium_economy", "business", "first"]
SeatPreference = Literal["aisle", "window", "middle", "no_preference"]
SchedulePreference = Literal["morning", "afternoon", "evening", "overnight", "no_preference"]
PacePreference = Literal["relaxed", "moderate", "packed"]
OptimizationObjective = Literal["lowest_cash", "highest_value", "convenience", "balanced"]


class FlightPreferences(AccountModel):
    cabin: PreferenceValue[Cabin] | None = None
    max_stops: PreferenceValue[Annotated[int, Field(ge=0, le=3)]] | None = None
    schedule: PreferenceValue[SchedulePreference] | None = None
    checked_baggage: PreferenceValue[bool] | None = None
    airport_flexible: PreferenceValue[bool] | None = None
    seat: PreferenceValue[SeatPreference] | None = None


class StayPreferences(AccountModel):
    lodging_styles: PreferenceValue[list[str]] | None = None
    location_priorities: PreferenceValue[list[str]] | None = None
    room_needs: PreferenceValue[list[str]] | None = None
    location_price_tradeoff: PreferenceValue[Literal["location", "price", "balanced"]] | None = None
    loyalty_programs: PreferenceValue[list[str]] | None = None


class RhythmPreferences(AccountModel):
    pace: PreferenceValue[PacePreference] | None = None
    day_start: PreferenceValue[Literal["early", "normal", "late"]] | None = None
    evening_style: PreferenceValue[Literal["quiet", "flexible", "late"]] | None = None
    downtime_minutes: PreferenceValue[Annotated[int, Field(ge=0, le=360)]] | None = None
    transit_tolerance_minutes: PreferenceValue[Annotated[int, Field(ge=0, le=240)]] | None = None
    day_trip_appetite: PreferenceValue[Literal["none", "one", "multiple"]] | None = None


class ExperiencePreferences(AccountModel):
    interests: PreferenceValue[list[str]] | None = None
    food_interests: PreferenceValue[list[str]] | None = None
    iconic_local_balance: PreferenceValue[Literal["iconic", "balanced", "local"]] | None = None
    nightlife: PreferenceValue[bool] | None = None
    shopping: PreferenceValue[bool] | None = None


class ConstraintPreferences(AccountModel):
    dietary: PreferenceValue[list[str]] | None = None
    accessibility: PreferenceValue[list[str]] | None = None


class OptimizationPreferences(AccountModel):
    objective: PreferenceValue[OptimizationObjective] | None = None
    points_priority: PreferenceValue[Literal["save_points", "use_points", "best_value"]] | None = None


class TravelPreferenceProfile(AccountModel):
    user_id: str
    flight: FlightPreferences = Field(default_factory=FlightPreferences)
    stay: StayPreferences = Field(default_factory=StayPreferences)
    rhythm: RhythmPreferences = Field(default_factory=RhythmPreferences)
    experiences: ExperiencePreferences = Field(default_factory=ExperiencePreferences)
    constraints: ConstraintPreferences = Field(default_factory=ConstraintPreferences)
    optimization: OptimizationPreferences = Field(default_factory=OptimizationPreferences)
    updated_at: datetime
```

Add validators to every list-bearing group that strip entries, drop empty strings, casefold only
taxonomy-like values (`interests`, `food_interests`, `dietary`, `accessibility`), preserve display
case for loyalty programs/room needs, and de-duplicate while preserving first-seen order.

Add all new stored/nested models to the existing forbidden-field reflection test.

- [ ] **Step 4: Run focused model tests**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_preferences.py evals/test_a1_models.py
.venv/bin/mypy --strict accounts/models.py
.venv/bin/ruff check accounts/models.py evals/test_cp1_preferences.py evals/test_a1_models.py
```

Expected: all pass.

- [ ] **Step 5: Write failing persistence, export, and deletion tests**

Add tests using a temporary `AccountStore`:

```python
def test_travel_preferences_upsert_and_round_trip(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    first = TravelPreferenceProfile(user_id="u1", updated_at=NOW)
    store.put_travel_preferences(first)
    updated = first.model_copy(
        update={
            "flight": FlightPreferences(
                cabin=PreferenceValue[str](
                    value="economy", source="user_profile_edit", updated_at=NOW
                )
            )
        }
    )
    store.put_travel_preferences(updated)
    assert store.get_travel_preferences("u1") == updated


def test_privacy_export_and_delete_include_travel_preferences(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.put_travel_preferences(TravelPreferenceProfile(user_id="u1", updated_at=NOW))
    assert store.export_user("u1", now=NOW).travel_preferences is not None
    store.delete_user("u1")
    assert store.get_travel_preferences("u1") is None
```

Update the exact account-table assertion to require `travel_preferences`.

- [ ] **Step 6: Run the store tests and verify the missing table/method failures**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_preferences.py evals/test_a1_boundary.py evals/test_a1_store.py
```

Expected: failures name the absent row/table and `AccountStore` methods.

- [ ] **Step 7: Implement preference persistence through AccountStore**

Add `TravelPreferenceRow(user_id primary key, payload Text)` to `accounts/db.py`. Add methods with
the exact signatures
`put_travel_preferences(self, preferences: TravelPreferenceProfile) -> TravelPreferenceProfile`
and `get_travel_preferences(self, user_id: str) -> TravelPreferenceProfile | None`.

`put_travel_preferences` must call `_require_user`, upsert exactly one row, and round-trip through
`model_dump_json()`/`model_validate_json()`. Add `travel_preferences` to `UserExport`, populate it in
`export_user`, and delete it before deleting the user. Do not merge partial objects in the store;
callers submit a fully validated replacement profile.

- [ ] **Step 8: Run the complete account regression scope**

```bash
cd backend
.venv/bin/pytest -q evals/test_a1_*.py evals/test_a2_*.py evals/test_cp1_preferences.py
.venv/bin/mypy --strict accounts/
.venv/bin/ruff check accounts/ evals/test_a1_boundary.py evals/test_a1_models.py \
  evals/test_a1_store.py evals/test_cp1_preferences.py
```

Expected: all pass with no behavior change to users, wallets, credentials, sessions, saved trips,
or revisions.

- [ ] **Step 9: Commit preference storage**

```bash
git add backend/accounts/models.py backend/accounts/db.py backend/accounts/store.py \
  backend/evals/test_a1_boundary.py backend/evals/test_a1_models.py \
  backend/evals/test_a1_store.py backend/evals/test_cp1_preferences.py
git commit -m "feat(accounts): add consent-based travel preferences"
```

---

### Task 3: Define strict interview answers and the approved question catalog

**Files:**
- Create: `backend/planning/answers.py`
- Create: `backend/planning/question_catalog.py`
- Create: `backend/evals/test_cp1_answers_catalog.py`

**Interfaces:**
- Consumes: Pydantic v2 and canonical literals compatible with `core.trip_models.TripSpec`.
- Produces: `QuestionId`, nine payload models, `InterviewAnswer`, `QuestionDefinition`,
  `DEFAULT_QUESTION_CATALOG`, `CORE_QUESTION_ORDER`, and `ADAPTIVE_QUESTION_IDS`.

- [ ] **Step 1: Write failing tests for the full catalog and answer validation**

Tests must assert all of these exact IDs exist once:

```python
EXPECTED_CORE = (
    "trip_essentials",
    "purpose_and_party",
    "budget_and_objective",
    "flight_preferences",
    "stay_preferences",
    "daily_rhythm",
    "experiences_and_food",
    "hard_constraints",
)
EXPECTED_ADAPTIVE = {
    "celebration_details",
    "children_needs",
    "mobility_details",
    "points_strategy",
    "flight_tradeoff",
    "hotel_tradeoff",
    "food_depth",
}
```

Add tests proving:

- core order is byte-stable and contains exactly eight IDs;
- every catalog entry has non-empty prompt, answer kind, impact domains, and unique priority;
- only `trip_essentials` and `hard_constraints` disallow delegation;
- `TripEssentialsPayload` normalizes IATA/currency and rejects reversed dates or zero travelers;
- `TripEssentialsPayload` rejects trips outside the Kernel's current 3–7-night range;
- `HardConstraintsPayload(has_constraints=False)` rejects non-empty constraint lists, while
  `has_constraints=True` requires at least one constraint/event/exclusion;
- `InterviewAnswer` rejects a payload whose model does not match its `question_id`;
- delegated answers reject a payload and nondelegated answers require one;
- free-text adaptive detail is trimmed, non-empty, and at most 1,000 characters;
- `memory_scope="propose_profile_update"` is rejected for trip-only question IDs.

- [ ] **Step 2: Run the test and observe missing-module failure**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_answers_catalog.py
```

Expected: collection fails because `planning.answers` and `planning.question_catalog` do not exist.

- [ ] **Step 3: Implement the strict answer contracts**

Define `QuestionId` as a `StrEnum` with all 15 values above. Define these payloads in
`planning/answers.py`:

```python
class TripEssentialsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    origin: str
    destination: str
    start_date: date
    end_date: date
    date_flexibility_days: int = Field(default=0, ge=0, le=14)
    travelers: int = Field(ge=1, le=20)


class PurposePartyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Literal["leisure", "work", "celebration", "family", "mixed"]
    adults: int = Field(ge=1, le=20)
    children_ages: list[int] = Field(default_factory=list)
    companion_notes: str | None = Field(default=None, max_length=500)


class BudgetObjectivePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    budget_minor: int | None = Field(default=None, ge=0)
    currency: str
    travel_style: Literal["budget", "balanced", "luxury"]
    objective: Literal["lowest_cash", "highest_value", "convenience", "balanced"]
    points_priority: Literal["save_points", "use_points", "best_value"]


class FlightPreferencesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cabin: Literal["economy", "premium_economy", "business", "first", "no_preference"]
    max_stops: int | None = Field(default=None, ge=0, le=3)
    schedule: Literal["morning", "afternoon", "evening", "overnight", "no_preference"]
    checked_baggage: bool | None = None
    airport_flexible: bool | None = None
    seat: Literal["aisle", "window", "middle", "no_preference"] = "no_preference"


class StayPreferencesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lodging_styles: list[str] = Field(default_factory=list)
    neighborhood_priorities: list[str] = Field(default_factory=list)
    room_count: int = Field(default=1, ge=1, le=10)
    room_needs: list[str] = Field(default_factory=list)
    location_price_tradeoff: Literal["location", "price", "balanced", "no_preference"]


class DailyRhythmPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pace: Literal["relaxed", "moderate", "packed", "no_preference"]
    day_start: Literal["early", "normal", "late", "no_preference"]
    evening_style: Literal["quiet", "flexible", "late", "no_preference"]
    downtime_minutes: int | None = Field(default=None, ge=0, le=360)
    transit_tolerance_minutes: int | None = Field(default=None, ge=0, le=240)
    day_trip_appetite: Literal["none", "one", "multiple", "no_preference"]


class ExperiencesFoodPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    interests: list[str] = Field(default_factory=list)
    food_interests: list[str] = Field(default_factory=list)
    iconic_local_balance: Literal["iconic", "balanced", "local", "no_preference"]
    nightlife: bool | None = None
    shopping: bool | None = None


class HardConstraintsPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    has_constraints: bool
    dietary: list[str] = Field(default_factory=list)
    accessibility: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    immovable_events: list[str] = Field(default_factory=list)


class AdaptiveDetailPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: str = Field(min_length=1, max_length=1000)
```

Add IATA/currency/list normalization validators, a `TripEssentialsPayload` model validator enforcing
3–7 nights to match the current frozen `TripSpec`, and the hard-constraint consistency validator.
Define `AnswerPayload` as the explicit union of these nine models. Define:

```python
class InterviewAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: QuestionId
    payload: AnswerPayload | None = None
    delegated: bool = False
    memory_scope: Literal["trip_only", "propose_profile_update"] = "trip_only"
    client_event_id: str = Field(min_length=1, max_length=128)
    answered_at: datetime
```

Use a module-level `ANSWER_TYPE_BY_QUESTION` mapping. A model validator must enforce payload type,
delegation consistency, and that only budget, flight, stay, rhythm, experiences, or constraints
answers may propose a profile update. Do not use `Any`.

- [ ] **Step 4: Implement the complete approved catalog**

Define:

```python
class QuestionDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: QuestionId
    phase: Literal["core", "adaptive"]
    prompt: str = Field(min_length=1)
    answer_kind: Literal[
        "trip_essentials", "purpose_party", "budget_objective", "flight", "stay",
        "rhythm", "experiences_food", "hard_constraints", "adaptive_detail"
    ]
    required: bool
    allow_delegate: bool
    priority: int = Field(ge=1)
    impact_domains: list[Literal[
        "flight", "hotel", "award", "itinerary", "cost", "rewards", "profile"
    ]]
    profile_sections: list[Literal[
        "flight", "stay", "rhythm", "experiences", "constraints", "optimization"
    ]] = Field(default_factory=list)
```

Create all 15 definitions explicitly. Core priorities are 10, 20, …, 80 in the order listed.
Adaptive priorities are 110–170 in the listed order. Prompts must use plain traveler-facing
language, not schema names. Exact impact/profile mappings:

| ID | Impacts | Profile section |
|---|---|---|
| trip_essentials | flight, hotel, award, itinerary, cost, rewards | none |
| purpose_and_party | hotel, itinerary | none |
| budget_and_objective | flight, hotel, award, cost, rewards | optimization |
| flight_preferences | flight, award, cost | flight |
| stay_preferences | hotel, itinerary, cost | stay |
| daily_rhythm | itinerary | rhythm |
| experiences_and_food | itinerary, cost | experiences |
| hard_constraints | flight, hotel, itinerary | constraints |
| celebration_details | hotel, itinerary | none |
| children_needs | flight, hotel, itinerary | none |
| mobility_details | flight, hotel, itinerary | constraints |
| points_strategy | award, rewards | optimization |
| flight_tradeoff | flight, award, cost | flight |
| hotel_tradeoff | hotel, itinerary, cost | stay |
| food_depth | itinerary, cost | experiences |

- [ ] **Step 5: Run contract/catalog tests and static checks**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_answers_catalog.py
.venv/bin/mypy --strict planning/answers.py planning/question_catalog.py
.venv/bin/ruff check planning/answers.py planning/question_catalog.py \
  evals/test_cp1_answers_catalog.py
```

Expected: all pass.

- [ ] **Step 6: Commit answer and catalog contracts**

```bash
git add backend/planning/answers.py backend/planning/question_catalog.py \
  backend/evals/test_cp1_answers_catalog.py
git commit -m "feat(planning): define interview answers and question catalog"
```

---

### Task 4: Persist resumable sessions with ownership, optimistic concurrency, and expiry

**Files:**
- Create: `backend/planning/contracts.py`
- Create: `backend/planning/repository.py`
- Modify: `backend/accounts/models.py`
- Modify: `backend/accounts/db.py`
- Modify: `backend/accounts/store.py`
- Modify: `backend/evals/test_a1_boundary.py`
- Create: `backend/evals/test_cp1_session_store.py`

**Interfaces:**
- Consumes: `InterviewAnswer`, `QuestionId`, `TravelPreferenceProfile`, `UserWallet`,
  `AccountStore`.
- Produces: `PlanningSession`, `PlanningSessionSnapshot`, `PlanningSessionRepository`, atomic
  compare-and-swap persistence, ownership scoping, and 30-day expiry deletion.

- [ ] **Step 1: Write failing session contract and persistence tests**

Create tests for:

```python
def test_new_session_is_server_owned_and_version_zero() -> None:
    session = PlanningSession(
        id="ps1",
        user_id="u1",
        status="interviewing",
        version=0,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(days=30),
        home=TravelerHomeContext(
            home_country="IN", home_currency="INR", default_origin="DEL"
        ),
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
    )
    assert session.answers == {}
    assert session.processed_event_ids == []
    assert session.assistance_status == "not_run"


def test_repository_round_trips_a_session(tmp_path: Path) -> None:
    accounts = _user_store(tmp_path)
    repository = PlanningSessionRepository(accounts)
    session = _session()
    repository.create(session)
    assert repository.get(user_id="u1", session_id="ps1") == session


def test_repository_rejects_a_stale_compare_and_swap(tmp_path: Path) -> None:
    repository = _repository_with_session(tmp_path)
    current = repository.get(user_id="u1", session_id="ps1")
    assert current is not None
    v1 = current.model_copy(update={"version": 1, "updated_at": LATER})
    repository.save(v1, expected_version=0)
    stale = current.model_copy(update={"version": 1, "updated_at": LATER})
    with pytest.raises(StalePlanningSessionError):
        repository.save(stale, expected_version=0)
```

Also test cross-user reads return `None`, cross-user updates fail, payload JSON is a JSON object,
reopen persistence, deterministic `(updated_at, id)` ordering, expired unsaved-session deletion,
retention of an expired session with `saved_trip_id`, saved account export inclusion, and user
deletion cascade.

- [ ] **Step 2: Run the session tests and observe missing contracts/repository**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_session_store.py
```

Expected: collection fails because the planning session interfaces do not exist.

- [ ] **Step 3: Define the session and future-compatible brief contracts**

In `planning/contracts.py`, define:

```python
class PlanningSessionStatus(StrEnum):
    INTERVIEWING = "interviewing"
    AWAITING_ASSISTANT = "awaiting_assistant"
    REVIEWING = "reviewing"
    CONFIRMED = "confirmed"
    PLANNING = "planning"
    COMPLETE = "complete"
    FAILED = "failed"
    ABANDONED = "abandoned"


class AssistanceStatus(StrEnum):
    NOT_RUN = "not_run"
    COMPLETE = "complete"
    DEGRADED = "degraded"


class TravelerHomeContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_country: Literal["IN", "AE", "US"]
    home_currency: str
    default_origin: str | None = None


class ProfileUpdateProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str
    section: Literal["flight", "stay", "rhythm", "experiences", "constraints", "optimization"]
    candidate_profile: TravelPreferenceProfile
    source_question_id: QuestionId


class TripBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home: TravelerHomeContext
    trip_essentials: TripEssentialsPayload
    purpose_and_party: PurposePartyPayload | None = None
    budget_and_objective: BudgetObjectivePayload | None = None
    flight_preferences: FlightPreferencesPayload | None = None
    stay_preferences: StayPreferencesPayload | None = None
    daily_rhythm: DailyRhythmPayload | None = None
    experiences_and_food: ExperiencesFoodPayload | None = None
    hard_constraints: HardConstraintsPayload
    adaptive_details: dict[QuestionId, AdaptiveDetailPayload] = Field(default_factory=dict)
    delegated_questions: list[QuestionId] = Field(default_factory=list)
    applied_profile_preferences: TravelPreferenceProfile | None = None
    applied_profile_sections: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    wallet: UserWallet


class ConfirmedBriefSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    brief: TripBrief
    confirmed_at: datetime


class PlanningSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    user_id: str
    status: PlanningSessionStatus
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    home: TravelerHomeContext
    wallet: UserWallet
    profile_defaults: TravelPreferenceProfile | None = None
    answers: dict[QuestionId, InterviewAnswer] = Field(default_factory=dict)
    current_question_id: QuestionId | None = None
    suggested_question_ids: list[QuestionId] = Field(default_factory=list)
    processed_event_ids: list[str] = Field(default_factory=list)
    assistance_status: AssistanceStatus = AssistanceStatus.NOT_RUN
    interview_llm_calls: int = Field(default=0, ge=0, le=2)
    pending_profile_updates: list[ProfileUpdateProposal] = Field(default_factory=list)
    confirmed_briefs: list[ConfirmedBriefSnapshot] = Field(default_factory=list)
    saved_trip_id: str | None = None
```

Add validators that normalize `TravelerHomeContext.home_currency/default_origin`, require a valid
three-letter currency/IATA value, enforce timezone-aware ordered timestamps, unique
event/suggestion IDs, confirmed brief revision ordering, and `expires_at > updated_at`. Do not
store display name, email, a raw transcript, or a provider payload in the planning session.

- [ ] **Step 4: Add the opaque account snapshot and SQL row**

Add to `accounts/models.py`:

```python
class PlanningSessionSnapshot(AccountModel):
    id: str
    user_id: str
    status: Literal[
        "interviewing", "awaiting_assistant", "reviewing", "confirmed", "planning",
        "complete", "failed", "abandoned"
    ]
    version: int = Field(ge=0)
    updated_at: datetime
    expires_at: datetime
    saved_trip_id: str | None = None
    payload_json: str

    @field_validator("payload_json")
    @classmethod
    def check_payload_json(cls, value: str) -> str:
        return _require_json_object(value, "payload_json")
```

Add `PlanningSessionRow` with real `id`, `user_id`, `status`, `version`, `updated_at`, `expires_at`,
nullable indexed `saved_trip_id`, and `payload` columns. Store timestamps as ISO strings, matching
existing indexed-row practice.
Add `planning_sessions` to the exact table test and `UserExport.planning_sessions`.

- [ ] **Step 5: Implement atomic snapshot methods in AccountStore**

Add errors with real docstrings:

```python
class PlanningSessionExistsError(ValueError):
    """Raised when a caller tries to create an existing planning-session ID."""


class StalePlanningSessionError(ValueError):
    """Raised when a compare-and-swap session version no longer matches."""
```

Add methods with these exact signatures:

- `create_planning_session_snapshot(self, snapshot: PlanningSessionSnapshot) -> PlanningSessionSnapshot`
- `get_planning_session_snapshot(self, *, user_id: str, session_id: str) -> PlanningSessionSnapshot | None`
- `put_planning_session_snapshot(self, snapshot: PlanningSessionSnapshot, *, expected_version: int) -> PlanningSessionSnapshot`
- `planning_session_snapshots(self, user_id: str) -> list[PlanningSessionSnapshot]`
- `delete_expired_planning_sessions(self, *, now: datetime) -> int`

For update, require `snapshot.version == expected_version + 1` and issue one SQLAlchemy `update`
whose `WHERE` matches `id`, `user_id`, and `version == expected_version`. If `rowcount != 1`, raise
`StalePlanningSessionError` without retrying or overwriting. For expiry, use
`delete(PlanningSessionRow).where(PlanningSessionRow.expires_at < now.isoformat(),
PlanningSessionRow.saved_trip_id.is_(None))` and return the affected count. A session attached to a
saved trip is retained with that trip rather than swept as abandoned. Export snapshots
deterministically and delete them before the user row.

- [ ] **Step 6: Implement the planning repository adapter**

`planning/repository.py` imports both sides and exposes this exact interface:

- `PlanningSessionRepository.__init__(self, store: AccountStore) -> None`
- `PlanningSessionRepository.create(self, session: PlanningSession) -> PlanningSession`
- `PlanningSessionRepository.get(self, *, user_id: str, session_id: str) -> PlanningSession | None`
- `PlanningSessionRepository.save(self, session: PlanningSession, *, expected_version: int) -> PlanningSession`
- `PlanningSessionRepository.list_for_user(self, user_id: str) -> list[PlanningSession]`
- `PlanningSessionRepository.delete_expired(self, *, now: datetime) -> int`

`create/save` convert a session to `PlanningSessionSnapshot` using
`session.model_dump_json()`. `get/list` parse with `PlanningSession.model_validate_json()`. The
repository must contain no `sqlalchemy` import and no engine/session attribute.

- [ ] **Step 7: Run session, account, boundary, type, and lint checks**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_session_store.py evals/test_cp1_boundaries.py \
  evals/test_a1_boundary.py evals/test_a1_store.py
.venv/bin/mypy --strict accounts/ planning/
.venv/bin/ruff check accounts/ planning/ evals/test_cp1_session_store.py \
  evals/test_cp1_boundaries.py evals/test_a1_boundary.py evals/test_a1_store.py
```

Expected: all pass. Verify `planning/repository.py` has no SQLAlchemy import.

- [ ] **Step 8: Commit resumable persistence**

```bash
git add backend/accounts/models.py backend/accounts/db.py backend/accounts/store.py \
  backend/planning/contracts.py backend/planning/repository.py \
  backend/evals/test_a1_boundary.py backend/evals/test_cp1_session_store.py
git commit -m "feat(planning): persist resumable interview sessions"
```

---

### Task 5: Implement the deterministic 8–12-decision interview policy

**Files:**
- Create: `backend/planning/policy.py`
- Create: `backend/evals/test_cp1_policy.py`

**Interfaces:**
- Consumes: `PlanningSession`, answer contracts, and the complete question catalog.
- Produces: `start_interview()`, `next_question()`, `record_answer()`,
  `record_assistant_suggestions()`, `interview_progress()`, and explicit domain errors.

- [ ] **Step 1: Write failing happy-path, branch, idempotency, and state tests**

Tests must exercise these exact signatures:

- `start_interview(*, user_id: str, session_id: str, home: TravelerHomeContext, wallet: UserWallet, profile_defaults: TravelPreferenceProfile | None, now: datetime, expires_at: datetime) -> PlanningSession`
- `next_question(session: PlanningSession) -> QuestionDefinition | None`
- `record_answer(session: PlanningSession, answer: InterviewAnswer, *, expected_version: int, now: datetime) -> PlanningSession`
- `record_assistant_suggestions(session: PlanningSession, question_ids: list[QuestionId], *, assistance_status: Literal["complete", "degraded"], llm_calls: int, expected_version: int, now: datetime) -> PlanningSession`
- `interview_progress(session: PlanningSession) -> InterviewProgress`

Required tests:

- a new session's first question is `trip_essentials` even when profile defaults exist;
- the eight core questions are always presented in locked order;
- answering the eighth core question moves to `awaiting_assistant`, not directly to review;
- `next_question` returns `None` while awaiting the bounded assistant result;
- a repeated `client_event_id` returns the identical session without incrementing version;
- a mismatched expected version raises `StaleSessionVersionError`;
- an answer for anything except the current question raises `UnexpectedQuestionError`;
- delegated essentials/hard constraints raise `DelegationNotAllowedError`;
- purpose `celebration` makes `celebration_details` applicable;
- children ages make `children_needs` applicable;
- accessibility constraints make `mobility_details` applicable;
- non-empty wallet points plus `use_points`/`best_value` makes `points_strategy` applicable;
- food interests make `food_depth` applicable;
- assistant suggestions are accepted only when IDs are adaptive, applicable, unanswered, unique,
  and present in the approved catalog;
- the policy never returns more than four adaptive questions or more than 12 total decisions;
- recording a complete or degraded assistant result resumes applicable adaptive questions;
- after the final applicable adaptive question—or immediately after an assistant result with no
  applicable adaptive questions—status becomes `reviewing` and `next_question` returns `None`;
- `interview_progress` reports completed decisions and approximate total without claiming an exact
  future adaptive count.

- [ ] **Step 2: Run the policy tests and observe missing implementation**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_policy.py
```

Expected: collection fails on `planning.policy`.

- [ ] **Step 3: Implement errors, constants, and pure version discipline**

Define:

```python
MIN_DECISIONS = 8
MAX_DECISIONS = 12
MAX_ADAPTIVE_DECISIONS = 4
SESSION_RETENTION = timedelta(days=30)

class PlanningPolicyError(ValueError):
    """Base error for deterministic interview-policy violations."""


class StaleSessionVersionError(PlanningPolicyError):
    """The supplied session version is no longer current."""


class UnexpectedQuestionError(PlanningPolicyError):
    """The answer does not belong to the question currently being asked."""


class DelegationNotAllowedError(PlanningPolicyError):
    """A required question cannot be delegated to the planner."""


class InvalidAssistantSuggestionError(PlanningPolicyError):
    """An assistant suggestion is unknown, inapplicable, repeated, or already answered."""
```

Every mutating pure function first verifies `expected_version == session.version`, returns a new
validated `PlanningSession` with `version + 1` and injected `updated_at`, and never mutates its input.
Create `_bump(session, now, **changes)` and round-trip through Pydantic validation rather than
relying on unchecked `model_copy` output.

- [ ] **Step 4: Implement deterministic applicability and selection**

Use explicit predicates keyed by adaptive ID:

```python
def _adaptive_applicable(question_id: QuestionId, session: PlanningSession) -> bool:
    purpose = _payload(session, QuestionId.PURPOSE_AND_PARTY, PurposePartyPayload)
    budget = _payload(session, QuestionId.BUDGET_AND_OBJECTIVE, BudgetObjectivePayload)
    flight = _payload(session, QuestionId.FLIGHT_PREFERENCES, FlightPreferencesPayload)
    stay = _payload(session, QuestionId.STAY_PREFERENCES, StayPreferencesPayload)
    food = _payload(session, QuestionId.EXPERIENCES_AND_FOOD, ExperiencesFoodPayload)
    constraints = _payload(session, QuestionId.HARD_CONSTRAINTS, HardConstraintsPayload)

    if question_id is QuestionId.CELEBRATION_DETAILS:
        return purpose is not None and purpose.purpose == "celebration"
    if question_id is QuestionId.CHILDREN_NEEDS:
        return purpose is not None and bool(purpose.children_ages)
    if question_id is QuestionId.MOBILITY_DETAILS:
        return constraints is not None and bool(constraints.accessibility)
    if question_id is QuestionId.POINTS_STRATEGY:
        has_points = any(session.wallet.points_balances.values())
        return budget is not None and has_points and budget.points_priority != "save_points"
    if question_id is QuestionId.FLIGHT_TRADEOFF:
        return flight is not None and flight.max_stops is None
    if question_id is QuestionId.HOTEL_TRADEOFF:
        return stay is not None and stay.location_price_tradeoff == "balanced"
    if question_id is QuestionId.FOOD_DEPTH:
        return food is not None and bool(food.food_interests)
    return False
```

Selection algorithm:

1. Return the first unanswered core question.
2. After the eighth core answer, set status to `awaiting_assistant` and return no question. This is
   the mandatory CP3 semantic-review seam; do not silently skip across it.
3. `record_assistant_suggestions` filters assistant IDs through applicability and catalog rules,
   then appends deterministically applicable adaptive IDs by catalog priority.
4. Remove answered IDs and truncate to the remaining adaptive/12-decision budget.
5. If candidates exist, set status back to `interviewing` and return the first candidate. When none
   remains, transition to `reviewing` during suggestion recording or the adaptive answer that
   exhausted the candidate list.

Assistant suggestions affect order only; they cannot make an inapplicable question applicable.

- [ ] **Step 5: Implement answer validation, idempotency, cross-answer consistency, and progress**

`record_answer` must:

- return the unchanged session immediately when `client_event_id` was already processed;
- reject non-`interviewing` sessions;
- require the current expected question;
- consult the catalog's `allow_delegate` flag;
- require `PurposePartyPayload.adults + len(children_ages)` to equal
  `TripEssentialsPayload.travelers` once both exist;
- store the answer by ID, append the event ID, choose the next question, and move to `reviewing`
  only when no valid question remains;
- keep processed event IDs in insertion order and reject duplicates through model validation.

`record_assistant_suggestions` is valid only in `awaiting_assistant`, validates the two-call ceiling,
and changes `assistance_status`; it performs no LLM operation. A `complete` result requires
`llm_calls >= 1`; a `degraded` result may use zero calls and still activates deterministic adaptive
branches. CP1 tests use the degraded zero-call transition honestly. CP3 replaces that test fixture
with the required replay-backed/live assistant behavior.

- [ ] **Step 6: Add Hypothesis coverage for bounded termination**

Use Hypothesis to vary celebration/family/accessibility/points/flight/stay/food conditions. Drive
the policy with valid generated payloads through all eight core questions, record a degraded
zero-call assistant result, then answer applicable adaptive details until review. Assert:

```python
assert session.status == PlanningSessionStatus.REVIEWING
assert 8 <= len(session.answers) <= 12
assert len(session.answers) == len(set(session.answers))
assert next_question(session) is None
```

Set `max_examples=100` and `deadline=None`. Do not mock the policy or directly assign status.

- [ ] **Step 7: Run policy tests, types, lint, and existing TripSpec tests**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_policy.py evals/test_m2_models.py evals/test_m2_intake.py
.venv/bin/mypy --strict planning/
.venv/bin/ruff check planning/ evals/test_cp1_policy.py
```

Expected: all pass.

- [ ] **Step 8: Commit the deterministic policy**

```bash
git add backend/planning/policy.py backend/evals/test_cp1_policy.py
git commit -m "feat(planning): add bounded deterministic interview policy"
```

---

### Task 6: Assemble and confirm a canonical Trip Brief without silently writing memory

**Files:**
- Create: `backend/planning/brief.py`
- Create: `backend/evals/test_cp1_brief.py`

**Interfaces:**
- Consumes: a `PlanningSession` in `reviewing`, typed answers, profile defaults, and memory scope.
- Produces: `assemble_trip_brief()`, `build_profile_update_proposals()`, and `confirm_trip_brief()`.

- [ ] **Step 1: Write failing brief assembly and confirmation tests**

Exercise these exact signatures:

- `assemble_trip_brief(session: PlanningSession) -> TripBrief`
- `build_profile_update_proposals(session: PlanningSession, *, now: datetime) -> list[ProfileUpdateProposal]`
- `confirm_trip_brief(session: PlanningSession, brief: TripBrief, *, expected_version: int, now: datetime) -> PlanningSession`

Required cases:

- assembly rejects a session that is not `reviewing`;
- essentials and explicit hard-constraint acknowledgement are always present;
- delegated optional answers become `None`, appear in `delegated_questions`, and produce a calm
  deterministic assumption;
- when a delegated section has profile defaults, its section appears in
  `applied_profile_sections`, its values appear in the filtered
  `applied_profile_preferences` snapshot, and the original profile provenance remains intact;
- all adaptive details survive keyed by their approved question ID;
- wallet data is copied from the session into the brief without summing/changing balances;
- only answers marked `propose_profile_update` produce proposals;
- purpose/party, trip essentials, celebration, and children details never create durable profile
  proposals;
- proposal construction does not call `AccountStore.put_travel_preferences`;
- confirmation requires byte-equivalence with a freshly assembled brief, appends revision 1,
  changes status to `confirmed`, increments the session version, and preserves all answers;
- an existing confirmed snapshot cannot be overwritten or reconfirmed in CP1; CP2's explicit
  amendment transition will create later immutable revisions;
- stale expected version and a mismatched/tampered brief fail closed.

- [ ] **Step 2: Run the tests and observe missing implementation**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_brief.py
```

Expected: collection fails on `planning.brief`.

- [ ] **Step 3: Implement deterministic assembly**

Use a generic `_answer_payload(session, question_id, payload_type) -> P | None` helper that checks
the stored payload instance before returning it. The implementation body of `assemble_trip_brief`
must follow this concrete shape:

```python
def assemble_trip_brief(session: PlanningSession) -> TripBrief:
    if session.status is not PlanningSessionStatus.REVIEWING:
        raise BriefNotReadyError("session must be reviewing before brief assembly")
    essentials = _required_payload(session, QuestionId.TRIP_ESSENTIALS, TripEssentialsPayload)
    constraints = _required_payload(session, QuestionId.HARD_CONSTRAINTS, HardConstraintsPayload)
    delegated = _delegated_in_catalog_order(session)
    applied_sections, applied_preferences, assumptions = _profile_defaults_and_assumptions(
        session, delegated
    )
    return TripBrief(
        home=session.home,
        trip_essentials=essentials,
        purpose_and_party=_answer_payload(
            session, QuestionId.PURPOSE_AND_PARTY, PurposePartyPayload
        ),
        budget_and_objective=_answer_payload(
            session, QuestionId.BUDGET_AND_OBJECTIVE, BudgetObjectivePayload
        ),
        flight_preferences=_answer_payload(
            session, QuestionId.FLIGHT_PREFERENCES, FlightPreferencesPayload
        ),
        stay_preferences=_answer_payload(
            session, QuestionId.STAY_PREFERENCES, StayPreferencesPayload
        ),
        daily_rhythm=_answer_payload(session, QuestionId.DAILY_RHYTHM, DailyRhythmPayload),
        experiences_and_food=_answer_payload(
            session, QuestionId.EXPERIENCES_AND_FOOD, ExperiencesFoodPayload
        ),
        hard_constraints=constraints,
        adaptive_details=_adaptive_details_in_catalog_order(session),
        delegated_questions=delegated,
        applied_profile_preferences=applied_preferences,
        applied_profile_sections=applied_sections,
        assumptions=assumptions,
        wallet=session.wallet,
    )
```

The implementation must not generate prose with an LLM. Assumption strings are fixed templates such
as `"No flight preference supplied; choose a practical option within the confirmed objective."`.
Order all lists by catalog order, never set/dict iteration.

- [ ] **Step 4: Implement typed profile-update proposals without performing writes**

For each eligible core answer with `memory_scope="propose_profile_update"`, construct a candidate
copy of the current `TravelPreferenceProfile` (or a new empty one) and replace only the matching
group:

- budget → `optimization`;
- flight → `flight`;
- stay → `stay`;
- rhythm → `rhythm`;
- experiences/food → `experiences`;
- hard constraints → `constraints`.

Wrap every persisted leaf in `PreferenceValue` with
`source="user_confirmed_from_trip"` and `updated_at=now`. Create one
`ProfileUpdateProposal` per section with a deterministic ID:
`f"{session.id}:{session.version}:{section}"`. The proposal is data only. CP2's authenticated,
CSRF-protected API will later ask the human and call `put_travel_preferences`; CP1 never does.

- [ ] **Step 5: Implement confirmation with canonical equality and immutable history**

Define errors `BriefNotReadyError`, `BriefMismatchError`, and `BriefAlreadyConfirmedError`.
`confirm_trip_brief` must reassemble the brief and compare
`model_dump_json()` byte-for-byte with the supplied brief before accepting it. Append:

```python
ConfirmedBriefSnapshot(
    revision=len(session.confirmed_briefs) + 1,
    brief=brief,
    confirmed_at=now,
)
```

Set `pending_profile_updates` from the proposal builder, status `confirmed`, and increment version.
Require `confirmed_briefs` to be empty and append revision 1. If a snapshot already exists, raise
`BriefAlreadyConfirmedError`. A future amendment transition belongs to CP2; CP1 does not expose an
unreviewed way to rewrite a confirmed session. The list shape is retained so CP2 can append
revision 2+ without changing the stored contract.

- [ ] **Step 6: Run brief, policy, persistence, type, and lint checks**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_brief.py evals/test_cp1_policy.py \
  evals/test_cp1_session_store.py
.venv/bin/mypy --strict planning/ accounts/
.venv/bin/ruff check planning/ accounts/ evals/test_cp1_brief.py \
  evals/test_cp1_policy.py evals/test_cp1_session_store.py
```

Expected: all pass.

- [ ] **Step 7: Commit brief assembly and confirmation**

```bash
git add backend/planning/brief.py backend/evals/test_cp1_brief.py
git commit -m "feat(planning): assemble confirmed trip briefs"
```

---

### Task 7: Prove privacy, determinism, cost isolation, and non-vacuous acceptance

**Files:**
- Create: `backend/evals/test_cp1_acceptance.py`
- Modify: `backend/evals/test_cp1_boundaries.py`
- Modify: `backend/evals/test_no_committed_secrets.py` only if its production-package list is
  explicit and does not already discover `planning/` recursively.

**Interfaces:**
- Consumes: all CP1 public interfaces.
- Produces: end-to-end offline proof from profile/session creation through a confirmed brief, plus
  architecture guards future milestones cannot accidentally bypass.

- [ ] **Step 1: Write the end-to-end acceptance test before adding new guards**

Build a real temporary `AccountStore`, create a user/profile/wallet, project the existing wallet,
start an interview, answer all core and applicable adaptive questions through `record_answer`,
assemble/confirm, persist through `PlanningSessionRepository`, reopen the SQLite database, and
assert the confirmed brief is byte-identical.

The test must use a persona whose answers exercise at least three adaptive branches: celebration,
points strategy, and food depth. Assert 11 decisions, not merely `<= 12`, so catalog/predicate drift
cannot silently reduce coverage. Use these values so no fourth branch is accidentally enabled:

| Answer | Value relevant to branching |
|---|---|
| trip essentials | DEL→SIN, 2026-11-10 through 2026-11-14, 2 travelers |
| purpose/party | celebration, 2 adults, no children |
| budget/objective | balanced, best_value |
| flight | economy, `max_stops=1` |
| stay | `location_price_tradeoff="location"` |
| rhythm | moderate |
| experiences/food | interests food+culture, food interest hawker centres |
| hard constraints | `has_constraints=False`, all constraint lists empty |
| wallet | one card and a positive HDFC points balance |

Answer the resulting `celebration_details`, `points_strategy`, and `food_depth` questions with
`AdaptiveDetailPayload`. After the eighth core answer, record an honest
`assistance_status="degraded"`, zero-call assistant result to activate deterministic adaptive
branches without pretending CP1 invoked an LLM. Persist the initial session, save after every pure
transition with the prior version as `expected_version`, and confirm revision 1 before reopening
the store.

- [ ] **Step 2: Add non-vacuous architecture and privacy guards**

Add tests that:

```python
import os
import subprocess


def _changed_files_against_merge_base() -> list[str]:
    base = os.environ.get("CP1_MERGE_BASE")
    if not base:
        pytest.skip("CP1_MERGE_BASE is required for committed-diff assertions")
    completed = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


def test_planning_package_has_no_network_llm_provider_or_sql_imports() -> None:
    forbidden = {"agents", "api", "gateway", "httpx", "requests", "mcp", "sqlalchemy"}
    offenders = _offenders("planning", forbidden)
    assert offenders == [], offenders


def test_cp1_changes_no_public_contract_or_frozen_goldens() -> None:
    changed = _changed_files_against_merge_base()
    assert "contract/openapi.json" not in changed
    assert not any(path.startswith("backend/evals/golden/") for path in changed)


def test_stored_session_contains_no_forbidden_key_names(tmp_path: Path) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="traveler@example.com", now=NOW, user_id="u1")
    repository = PlanningSessionRepository(store)
    session = start_interview(
        user_id="u1",
        session_id="ps1",
        home=TravelerHomeContext(
            home_country="IN", home_currency="INR", default_origin="DEL"
        ),
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        profile_defaults=None,
        now=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    repository.create(session)
    snapshot = store.get_planning_session_snapshot(user_id="u1", session_id="ps1")
    assert snapshot is not None
    lowered = snapshot.payload_json.casefold()
    for forbidden in FORBIDDEN_FIELD_NAMES:
        assert f'"{forbidden.casefold()}"' not in lowered
```

The changed-file helper compares the milestone branch to its recorded merge base, not only the
working tree. Pass the merge-base ref through `CP1_MERGE_BASE`; a missing variable skips with an
explicit reason. Do not make a green test depend on uncommitted changes or guess a default base.

Also statically reject `datetime.now`, `date.today`, `uuid4`, `random.`, and `secrets.` calls in
`planning/`; their appearance would violate injected determinism.

- [ ] **Step 3: Run acceptance tests and verify any new guard failures are genuine**

```bash
cd backend
CP1_MERGE_BASE="$(git merge-base HEAD main)" .venv/bin/pytest -q \
  evals/test_cp1_acceptance.py evals/test_cp1_boundaries.py \
  evals/test_no_committed_secrets.py evals/test_no_stubs.py
```

Expected: the end-to-end flow passes. Any failure must identify a real import, secret-shaped field,
nondeterministic clock/ID call, contract drift, or missing adaptive branch; do not add allowlists.

- [ ] **Step 4: Run the complete CP1 scope twice and compare canonical artifacts**

```bash
cd backend
.venv/bin/pytest -q evals/test_cp1_*.py evals/test_a1_*.py evals/test_a2_*.py
.venv/bin/pytest -q evals/test_cp1_*.py evals/test_a1_*.py evals/test_a2_*.py
.venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/
.venv/bin/ruff check accounts/ planning/ agents/ gateway/ evals/
```

Expected: identical passing test counts both times, strict mypy clean, Ruff clean in its
zero-tolerance scope.

- [ ] **Step 5: Commit acceptance guards**

```bash
git add backend/evals/test_cp1_acceptance.py backend/evals/test_cp1_boundaries.py \
  backend/evals/test_no_committed_secrets.py
git commit -m "test(planning): prove conversational domain invariants"
```

If `test_no_committed_secrets.py` required no edit, omit it from `git add` rather than touching it
gratuitously.

---

### Task 8: Document CP1 honestly, review the diff, and pass the clean-tree gate

**Files:**
- Create: `reports/cp1_conversational_domain.md`
- Modify: `DEVIATIONS.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: committed CP1 code/test evidence and actual gate output.
- Produces: durable milestone recovery context with no false claim that conversational UI, LLM
  assistance, G3.4 provider wiring, or post-plan chat exists.

- [ ] **Step 1: Write the milestone report from executed evidence**

The report must contain:

- branch/base and baseline/final test counts measured on this worktree;
- exact new tables/models/modules and public method signatures;
- proof of eight core plus bounded adaptive termination;
- proof that profile writes require explicit consent data and no LLM inference is durable;
- proof of optimistic concurrency, idempotency, ownership, expiry, export, and deletion;
- proof that `planning/` imports no LLM/provider/network/SQL packages;
- exact focused and full-gate commands/outcomes;
- explicit limitations: no API, UI, LLM invocation, provider call, production `/plan` integration,
  or post-plan chat in CP1;
- the next milestone is CP2, not G3.4 or CP3 out of order;
- no claim of a “final commit hash” inside the tracked report, because later review-fix commits make
  that claim immediately stale.

- [ ] **Step 2: Log the implementation decisions in DEVIATIONS.md**

Add rows for these approved Tier-C/SCOPE+ choices if implementation used them:

- separate `travel_preferences` row rather than widening `UserProfile`;
- opaque account snapshot plus typed planning repository, preserving the accounts-only SQL boundary;
- 30-day abandoned-session retention;
- code-defined approved catalog rather than YAML/expression DSL;
- eight fixed core questions and maximum four adaptive questions;
- profile proposals contain fully typed candidate profiles but never perform writes in CP1.

Do not log a decision that was not actually implemented.

- [ ] **Step 3: Update the canonical briefs without overstating completion**

Add one checkpoint bullet describing CP1 and one work-remaining bullet each for CP2, CP3, G3.4, and
CP4. Update the test/type baseline using real output. Apply identical edits to `AGENTS.md` and
`CLAUDE.md`, then verify:

```bash
cmp AGENTS.md CLAUDE.md
```

Expected: exit 0 and no output.

- [ ] **Step 4: Run documentation/static checks and commit the milestone record**

```bash
git diff --check
rg -n "T[B]D|T[O]DO|FIXM[E]|implement lat[e]r|wire lat[e]r" \
  reports/cp1_conversational_domain.md DEVIATIONS.md AGENTS.md CLAUDE.md
git add reports/cp1_conversational_domain.md DEVIATIONS.md AGENTS.md CLAUDE.md
git commit -m "docs: record CP1 conversational domain milestone"
```

Expected: `git diff --check` passes. The scan may match historical text in `DEVIATIONS.md` or the
briefs; inspect every match and ensure the new CP1 sections contain no incomplete claim.

- [ ] **Step 5: Invoke the required code-review skill against the full milestone diff**

Use `superpowers:requesting-code-review` with the actual merge base and HEAD. Ask the reviewer to
focus on:

- ownership leaks or cross-user session access;
- non-atomic optimistic updates;
- privacy export/delete omissions;
- preference fields capable of storing forbidden credentials;
- answer/payload mismatches and catalog gaps;
- paths that exceed 12 decisions, dead-end before review, or skip required facts;
- profile writes occurring without explicit approval;
- tests that pass without driving the real policy/store;
- accidental API/LLM/provider/kernel changes.

Do not accept findings blindly. Use `superpowers:receiving-code-review`, reproduce each finding,
fix confirmed issues test-first in focused commits, and record rejected findings with evidence.

- [ ] **Step 6: Run the full gate from a clean committed tree**

Commit all accepted review fixes first. Then run from the repository root:

```bash
git status --short
make gate
```

Expected before `make gate`: empty status output. Expected gate result: full pytest passes; strict
mypy includes `planning/`; Ruff zero-tolerance scope includes `planning/`; goldens unchanged;
contract check passes without a contract change; briefs are byte-identical; tree is clean.

- [ ] **Step 7: Verify the final committed artifact without rewriting the report**

```bash
git status --short --branch
git diff --check "$(git merge-base HEAD main)" HEAD
git diff --exit-code "$(git merge-base HEAD main)" HEAD -- backend/evals/golden/ \
  contract/openapi.json frontend/ backend/agents/pipeline.py backend/gateway/
```

Expected: clean branch, no whitespace errors, and no drift in frozen/out-of-scope paths. If the
branch legitimately contains pre-existing stacked G3 changes because the human chose that base,
compare against the recorded CP1 base instead of `main` and document the exact base; do not pretend
those older changes belong to CP1.

---

## CP1 Definition of Done

CP1 is complete only when all statements below are true:

- A user can have one persisted, typed, exportable, deletable travel-preference profile.
- Durable preference sources are only direct profile edits or explicit trip-confirmed updates.
- A planning session round-trips across SQLite reopen, is user-scoped, versioned, idempotent,
  compare-and-swap protected, and expires after the configured abandoned-session window.
- The approved catalog contains exactly eight ordered core questions and seven bounded adaptive
  questions, with strict answer payload matching.
- Real policy execution reaches review in 8–12 decisions across property-generated paths.
- A reviewing session deterministically assembles and immutably confirms a typed Trip Brief.
- Profile-update proposals are typed but perform no write without future CP2 approval handling.
- `planning/` performs no SQL, network, LLM, provider, money arithmetic, or clock/ID discovery.
- `backend/core/`, the frozen Kernel pipeline, gateway adapters, OpenAPI, frontend, and goldens are
  unchanged.
- Required review is reconciled and `make gate` passes from the final clean committed tree.
- The report states CP1's limitations honestly and identifies CP2 as the next milestone.

## Explicitly Deferred

- CP2: conversational API, authenticated preference endpoints, resumable frontend, typed controls,
  review/amend UI, and mandatory-confirmation job start.
- CP3: required adaptive LLM review, free-text interpretation, replay corpus, teeth tests, model
  routing, two-call interview ceiling, and degraded assistance UI.
- G3.4: confirmed-brief production gateway/Gondola integration and public evidence contract.
- CP4: post-plan natural-language intent routing, deterministic edit dispatch, scoped replanning,
  provider invalidation confirmation, and synchronized chat/workspace UI.
- CP5: cross-persona/live bounded acceptance, full responsive/a11y polish, and final program gate.
