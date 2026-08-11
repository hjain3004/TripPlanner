# Itinerary I0 — Tasks 3–7 Work Order

**Date:** 2026-08-11
**Scope:** Complete Phase I0. Tasks 1 and 2 are already done and committed.
**Branch/worktree:** `feat/i0-evidence-hardening` at
`/Users/himanshu_jain/TripPlanner/.worktrees/itinerary-i0-evidence-hardening`
**Not in scope:** Phase I2. It is a separate work order written after I0 lands. Do not start it.

---

# PART 0 — READ THIS ENTIRE SECTION BEFORE WRITING ANY CODE

## 0.1 The eight failures from the previous phase

The previous phase (I1) was executed by an agent that reported it complete **four separate
times**, and each time a reviewer found it was not. Every one of these was mechanically
checkable. They are listed here because avoiding them is the single most important part of this
task.

| # | What happened | What it should have been |
|---|---|---|
| 1 | Reported "mypy clean across all 38 files" when the gate command covers **44** files. A narrower target list was run and its output presented as the gate. | Run the exact gate command. Never substitute a smaller target set. |
| 2 | **Zero commits.** All work sat uncommitted despite the plan requiring one commit per task, with a specific first commit. | Commit per task, in order, before starting the next. |
| 3 | Skipped an entire section (§4) of the controlling document — did the obvious task list from an older referenced plan, missed the newer document's additional scope. | Read the whole document. Restate the task list before starting. |
| 4 | Reported "Gate passed" when 2 of the gate's 3 clauses were unimplemented. | The gate is a list of commands and assertions, not a judgment call. |
| 5 | Added three features; **test count went 151 → 151.** Claimed TDD. Existing tests were edited instead of new ones added. | New behavior means new test functions. Count must rise. |
| 6 | Wrote `patch_compose.py`, `patch_tests.py`, `commit_script.sh` to modify files, then left them in the tree — while reporting "the worktree is completely clean." Twice. | Edit files directly. Never write patch scripts. Paste `git status` before claiming clean. |
| 7 | Implemented *detection* and called it done: emitted `ScheduleWarning(kind="closed_day")` but never wired it to a rejection, so a known-closed venue was still delivered to the user with a caveat attached. Reported "ironclad" and "Gate fully passed." | A warning is not enforcement. If a rule says X must not happen, a test must prove X is *rejected*. |
| 8 | Introduced `start_time: str` ("HH:MM") two commits after the same phase replaced prose time strings with a structured type. | Match conventions the current branch just established. |

**The meta-pattern: confident completion claims that a single command would have disproved.**
Assume every claim you make will be checked with a command. Run the command yourself first.

## 0.2 Banned behaviors (hard rules)

1. **Never write a script to patch source files.** No `patch_*.py`, no `fix_*.sh`, no
   `commit_script.sh`. Edit files directly with your editor tool. If you create any temporary
   file, delete it before committing, and confirm with `git status --short`.
2. **Never substitute a narrower verification command.** The gate commands in Part 3 are literal.
   Copy them character for character.
3. **Never claim a state you have not just verified.** The words "clean", "passing", "complete",
   "ironclad", "flawless", "fully passed" may only appear in your report immediately adjacent to
   the pasted raw output of the command that proves them.
4. **Never edit an existing test to accommodate new behavior when you should be adding one.**
   Editing is allowed only when a signature genuinely changed. New behavior = new test function.
5. **Never leave a computed signal unenforced.** If you compute a violation, something must
   consume it and change the outcome, and a test must prove the outcome changed.
6. **Never modify `backend/evals/golden/` or `contract/openapi.json`.** Both are checked by the
   final gate. If either changes, stop and report.
7. **Never run `ruff --fix` across the whole repo.** Only across files you created in this task.
8. **Do not proceed to the next task until the current task is committed.**

## 0.3 Mandatory per-task closing protocol

At the end of **every** task (3, 4, 5, 6, 7), run this block and **paste the raw output verbatim**
into your response. Not a summary. Not "all passing". The actual text.

```bash
cd /Users/himanshu_jain/TripPlanner/.worktrees/itinerary-i0-evidence-hardening/backend
.venv/bin/pytest -q 2>&1 | tail -3
.venv/bin/mypy --strict core/ agents/ api/ gateway/ 2>&1 | tail -3
.venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py 2>&1 | tail -3
cd ..
git status --short
git log --oneline -1
```

Then state, in one line each:
- Test count before this task → after this task (it must have **increased**).
- Whether `git status --short` was empty (it must be).

If a command errors, paste the error. Do not describe it. Do not proceed.

## 0.4 If the venv is missing

The worktree may not have its own venv. Use the main one — it works:
`/Users/himanshu_jain/TripPlanner/backend/.venv/bin/pytest` etc. If tests fail with
`sqlite3.OperationalError: no such table: cards`, copy the fixture:
`cp /Users/himanshu_jain/TripPlanner/backend/core/tripwise.sqlite <worktree>/backend/core/tripwise.sqlite`
That is a local artifact, gitignored, not part of your diff.

---

# PART 1 — WHERE THINGS STAND

## 1.1 Baseline (verified 2026-08-11)

- **161 tests passing.** This is your floor. It must never drop.
- `mypy --strict core/ agents/ api/ gateway/` → **clean, 44 source files.**
- Ruff on the I0-owned surface (`gateway/evidence/`, `evals/test_evidence_*.py`,
  `evals/conftest.py`) → **10 errors.** Task 6 drives this to 0.
- Ruff on the full `gateway/ evals/` surface → **41 errors.** This is historical debt outside
  this phase. It must not *increase*. Do not "fix" it.
- `AGENTS.md` and `CLAUDE.md` **differ at line 51.** Task 7 reconciles them.
- `test_fix2.py` exists at the **repository root** (not under `backend/`). Task 6 relocates it.

## 1.2 What Tasks 1 and 2 already changed (do not redo, do not regress)

Commit `abed6ff` — *fix(gateway): enforce zero spend and typed evidence time*:
- `PlanBudget.max_cost_minor: int = Field(default=0, ge=0)` — was `None`.
- `BudgetLedger.record_external_cost(amount_minor)` — checks the prospective total *before*
  mutating, so a rejected call leaves state untouched. `BudgetLedger.external_cost_minor` exists.
- `Source.retrieved_at`, `Claim.expires_at`, `Run.started_at`, `Run.ended_at` are
  `pydantic.AwareDatetime`. Naive timestamps are rejected at construction.
- `Claim.expires_at` is a **typed field**, no longer `payload["expires_at"]`. There is no second
  expiry source. Do not reintroduce one.
- `Source.run_id` and `Evaluation.run_id` are required.
- `Run` rejects `ended_at < started_at`.
- `is_expired(claim, now: datetime)` and `mark_stale(graph, claim_id, now: datetime)` take aware
  datetimes. Expiry is `now >= expires_at` (exact instant counts as expired).

Commit `97c94de` — *fix(gateway): enforce evidence edge contracts*:
- `Edge.created_by_run: str` is **required**. There is no `"r1"` default anywhere. Every call
  site threads a real run id.
- `EvidenceGraph.add_edge()` validates endpoints, direction, and kind-specific pointer rules
  before mutating; raises `InvalidEdge` (exported from `edges.py`). Exact duplicates are a no-op.
  `CONTRADICTS` normalizes orientation, so a reverse-inserted edge is the same edge.
- `validate_edge_endpoints(graph, edge) -> str | None` in `edges.py` is the **single** classifier.
  `check_invariants()` calls it too. **Do not write a second copy of edge validation logic.**
- `detect_contradictions(graph, claim_ids, *, created_by_run: str)` already takes the run id.

## 1.3 Conventions this branch has established — match them

- Timestamps are `AwareDatetime`, never `str`.
- Run ownership is explicit and required, never defaulted.
- Validation lives in one shared function reused by both the mutation path and the audit path.
- Tests are typed: `def test_x() -> None:`.
- Test files are `backend/evals/test_evidence_*.py`.

---

# PART 2 — THE TASKS

The authoritative detail is
`docs/superpowers/plans/2026-08-02-itinerary-i0-evidence-hardening.md`, Tasks 3 through 7. That
document predates Tasks 1–2, so where it conflicts with Part 1.2 above, **Part 1.2 wins**. The
essential contracts are restated below so you do not have to reconcile two documents from memory.

**Before you begin, restate these five task names back to me in your first response.** This is a
check that you read the whole document.

- Task 3 — Typed exact identity and reversible resolution
- Task 4 — Schema-aware, order-independent contradiction detection
- Task 5 — Complete idempotent SQLite persistence
- Task 6 — Lifecycle docs, test relocation, and I0-surface lint
- Task 7 — Boundary tests, Gate I0, and the report

---

## Task 3 — Typed exact identity and reversible resolution

**Problem being fixed:** `resolution.py` currently merges claims using `flight_identity()`, which
builds a `tuple[str, ...]` out of `.payload.get(...)` string lookups. Any two claims whose
payloads happen to stringify the same will merge. Canonical selection is
`sorted(claim_ids)[0]` — a lexicographic accident, so a stale unverified claim can win over
fresh verified evidence.

**Files:** create `backend/gateway/evidence/identity.py`; modify `nodes.py`, `edges.py`,
`resolution.py`, `invariants.py`, `evals/conftest.py`, `evals/test_evidence_nodes.py`,
`evals/test_evidence_resolution.py`, `evals/test_evidence_invariants.py`.

### Contracts

In `identity.py`, a Pydantic **discriminated union** on `kind`. Not tuples. Not fuzzy matching.

```python
class FlightSegmentIdentity(BaseModel):
    origin: str
    destination: str
    departure_at: AwareDatetime
    arrival_at: AwareDatetime
    operating_carrier: str
    flight_number: str

class FlightQuoteIdentity(BaseModel):
    kind: Literal["flight_quote"]
    segments: tuple[FlightSegmentIdentity, ...]   # must be non-empty
    cabin: str
    fare_conditions: str

class FlightObservationIdentity(BaseModel):
    kind: Literal["flight_price_observation"]
    provider: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    stops: int
    observed_bucket: AwareDatetime

class HotelQuoteIdentity(BaseModel):
    kind: Literal["hotel_quote"]
    property_key: str
    check_in: date
    check_out: date
    occupancy_key: str
    room_type: str
    rate_plan: str

class AwardQuoteIdentity(BaseModel):
    kind: Literal["award_quote"]
    program_id: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    operating_carrier: str

class ReferenceFactIdentity(BaseModel):
    kind: Literal["reference_fact"]
    namespace: str
    entity_id: str
    field: str

EvidenceIdentity = Annotated[
    FlightQuoteIdentity | FlightObservationIdentity | HotelQuoteIdentity
    | AwardQuoteIdentity | ReferenceFactIdentity,
    Field(discriminator="kind"),
]
```

`Claim` gains `identity: EvidenceIdentity`. A sandbox fixture carries the identity of the domain
claim it represents — fixture/sample is an *evidence kind*, not an identity kind.

In `nodes.py` (so `edges.py → nodes.py` stays one-way and there is no circular import):

```python
class ResolutionState(StrEnum):
    ACTIVE = "active"
    REVERSED = "reversed"

class ResolutionRecord(BaseModel):
    resolution_id: str
    members: list[str]          # >= 2
    canonical_id: str
    rule: str
    confidence: float
    created_by_run: str
    state: ResolutionState = ResolutionState.ACTIVE
    reversed_by_run: str | None = None
```

`ResolutionRecord` **moves out of `resolution.py` into `nodes.py`.** `EvidenceGraph` gains
`resolutions: dict[str, ResolutionRecord]`.

In `resolution.py` (operations only):

```python
def resolve(graph, claim_ids: list[str], *, created_by_run: str,
            rule: Literal["exact_identity"] = "exact_identity") -> ResolutionRecord: ...
def unresolve(graph, resolution_id: str, *, reversed_by_run: str) -> None: ...
```

`flight_identity()` is **deleted.** Resolution compares `Claim.identity` by exact model equality.

### Canonical selection — ranked, not lexicographic

Select the canonical member by, in order:

1. active lifecycle only (superseded members are rejected before this point);
2. `needs_verification == False` before `True`;
3. freshness priority: `live`, `cached`, `estimated`, `verify_required`, `stale`;
4. newest cited `Source.retrieved_at`;
5. `claim_id` — **only** as the final total-order tie-break.

Store the record in `graph.resolutions` **before** adding `RESOLVED_TO` edges. A reversed record
stays stored and addressable — `unresolve` sets `state=REVERSED`, records `reversed_by_run`,
removes only that resolution's active `RESOLVED_TO` edges, and is idempotent.

`check_invariants()` gains: resolution members and canonical id exist; edges agree with the
record; `created_by_run`/`reversed_by_run` reference real runs; active vs reversed state is
consistent with the presence of `RESOLVED_TO` edges.

### Required tests (all of them, each a new test function)

Identity validation: empty segment tuple rejected; naive datetime rejected; each of the five
discriminators constructs.

Resolution: same identity with different prices resolves; **different cabin rejects**;
**different fare_conditions rejects**; **different flight segment rejects**; **different hotel
rate_plan rejects**; **different award program rejects**; mixed identity kinds reject; missing
claim id rejects *before any graph mutation*; duplicate member id rejects; superseded member
rejects; record and all members remain addressable after resolve; `unresolve` marks `REVERSED`,
records `reversed_by_run`, removes only its own edges, and is idempotent; **member input order
does not change the canonical choice**; **a lexicographically smaller but stale / older /
verify-required claim does not beat stronger evidence.**

That last one is the point of the whole task. Do not omit it.

**Commit:** `fix(gateway): require typed exact evidence identity`

---

## Task 4 — Schema-aware, order-independent contradiction detection

**Problem being fixed:** `detect_contradictions()` reads `payload["total_minor"]` for every claim
kind and compares via `flight_identity()`. Award claims (measured in points) and price
observations get compared as if they were cash quotes. The delta formula divides by the left
operand, so swapping argument order changes the result.

**Files:** modify `gateway/evidence/contradiction.py`, `evals/test_evidence_contradiction.py`.

### Policy

| Evidence | Required typed identity | Integer comparison field | Threshold |
|---|---|---|---|
| current flight/hotel cash quote | flight or hotel quote | `total_minor` | 200 bp |
| cached flight observation | flight observation | `total_minor` | 1000 bp |
| award availability | award quote | `points_required` | 0 bp |
| sandbox / reference fact | any | none | never contradicts automatically |

Select the comparison field **by evidence kind and identity**. Reuse `Claim.identity` from Task 3;
do not reconstruct identity from payload. Two claims with different typed identities never
compare. Price observations and current quotes never compare to each other.

Symmetric formula — note the `min`, which is what makes it order-independent:

```python
delta_bps = abs(left_value - right_value) * 10_000 // min(left_value, right_value)
```

Contradiction requires `delta_bps > threshold`. Exact threshold does **not** contradict; one
basis point above does.

Missing, boolean, non-integer, or non-positive comparison values are **non-comparable**: they
produce no edge, plus a deterministic reason available to the caller. Return a small model rather
than silently dropping malformed pairs:

```python
class ContradictionResult(BaseModel):
    edges: list[Edge]
    skipped: list[str]   # deterministic reasons
```

Edges carry `created_by_run` from the existing required argument, and are returned in stable
`(kind, src, dst)` order.

### Required tests

Reversing claim ids and input order produces the same result; award claims compare
`points_required` not `total_minor`; observations and current quotes never compare; different
typed identities never compare; exact threshold does not contradict but one bp above does;
zero / negative / bool / string / missing values produce a `skipped` reason rather than a crash;
sandbox and reference facts are explicitly unsupported.

**Note:** `detect_contradictions` returns a bare `list[Edge]` today and three existing tests call
it. Changing the return type to `ContradictionResult` means updating those three call sites —
that is a genuine signature change, so editing those tests is correct here. Adding the new cases
above still requires new test functions.

**Commit:** `fix(gateway): compare contradictions by evidence schema`

---

## Task 5 — Complete idempotent SQLite persistence

**This is the largest task.** `store.py` is currently 87 lines and persists **three** of seven
node types. It still contains `_run_id_for()` with a hardcoded `"r1"` fallback — delete it.

**Files:** modify `gateway/evidence/store.py`, `evals/test_evidence_store.py`.

### Contract

`SqliteEvidenceStore.save(graph)` persists **all** of: sources, claims, artifacts, runs,
evaluations, resolution records (including reversed state), edges (including authoring run).

`SqliteEvidenceStore.load(run_id)` returns the run-authored subgraph **plus every** source,
claim, artifact, evaluation, resolution and edge needed to make that subgraph's lineage pointers
addressable (resolve recursively until no new referenced ids appear). It must pass
`check_invariants()` before returning.

Schema requirements:
- `PRAGMA foreign_keys = ON`; `PRAGMA user_version = 2` after migration.
- One table per node/record type; JSON bodies are schema-normalized Pydantic JSON.
- `edges` primary key: `(kind, src, dst, created_by_run)`.
- Explicit indexes on node `run_id`, resolution `created_by_run`, and edge
  `created_by_run` / `src` / `dst`.
- One transaction around validate → synchronize → insert.
- **Parameterized SQL only.** No string interpolation into SQL, ever.

Behavior:
- Call `check_invariants()` **before** any mutation; raise a typed `EvidenceStoreError` carrying
  the stable violation list. Never persist a partially invalid graph.
- On save, collect touched run ids from nodes, records and edges in the supplied graph. Upsert
  addressable nodes/records. Synchronize edges and resolutions authored by touched runs **inside
  the same transaction**, so an edge removed in memory does not linger in SQLite.
- **Never delete a claim merely because it is absent from a partial run view.**
- v1 → v2 migration in one transaction: preserve old rows, backfill edge/source run ownership
  only where it derives uniquely from connected claims, and **raise a clear migration error
  rather than inventing `"r1"`** when it cannot.
- Build the loaded graph nodes-first, validated-edges-second.

### Required tests

`test_round_trip_preserves_every_node_record_and_edge`,
`test_save_same_graph_twice_is_byte_and_row_count_idempotent`,
`test_save_updated_run_removes_stale_edges_for_that_run`,
`test_save_updated_run_does_not_delete_other_run`,
`test_load_run_includes_cross_run_lineage_closure`,
`test_reversed_resolution_survives_round_trip`,
`test_save_rejects_invalid_graph_before_writing`,
`test_failed_save_rolls_back_all_tables`,
`test_v1_store_migrates_without_losing_sources_claims_or_edges`.

Build the fixture as a complete graph: two runs, two sources, several claims, an artifact derived
from a claim *and* from another artifact, an evaluation, an active resolution, a superseded
claim, and all six edge kinds. Create the v1 fixture **inside the test** using the old
three-table SQL — **do not commit a binary SQLite file.**

**Commit:** `fix(gateway): persist complete evidence graphs idempotently`

---

## Task 6 — Lifecycle docs, test relocation, and I0-surface lint

Documentation, test placement and lint only. **Do not change graph behavior in this commit.**

1. Move `test_contradicts_field_removed` from the repo-root `test_fix2.py` into
   `backend/evals/test_evidence_nodes.py`, then **delete `test_fix2.py`**. Verify it appears in
   normal collection:
   `cd backend && .venv/bin/pytest --collect-only -q | grep test_contradicts_field_removed`
2. In `docs/superpowers/specs/2026-07-28-evidence-graph-orchestration-design.md`, remove the
   stale `contradicts: list[str]` field from the example and state that `CONTRADICTS` edges are
   canonical.
3. In `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md` and
   `docs/superpowers/plans/2026-07-29-visual-system-reconciliation.md`, correct both visual
   mappings: `FreshnessState.STALE` → grey plate with diagonal **STALE** overprint;
   `LifecycleState.SUPERSEDED` → graph-lifecycle treatment with diagonal **SUPERSEDED**
   overprint. Supersession is **not** a freshness status. This is a contract clarification for
   phase I6, not frontend work — write no CSS.
4. Add a top-of-file status note to `docs/superpowers/plans/2026-07-28-evidence-graph-core.md`:
   implementation landed; the 2026-08-02 I0 plan supersedes its code snippets. Do not rewrite its
   historical tasks.
5. Fix **only** the 10 Ruff findings on the I0-owned surface. Review the diff; do not run
   `--fix` across all of `evals/`.

Verify: `.venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py`
→ must report **zero**. And `.venv/bin/ruff check gateway/ evals/` must be **≤ 41**.

**Commit:** `docs: align evidence lifecycle and test discovery`

---

## Task 7 — Boundary tests, Gate I0, and the report

**Files:** create `backend/evals/test_evidence_boundary.py` and
`reports/itinerary_i0_evidence_hardening.md`; modify `AGENTS.md`, `CLAUDE.md`, and `DEVIATIONS.md`.

### Boundary tests

1. An **AST-based** test that walks `backend/core/**/*.py` and fails on any import whose module
   starts with `gateway` or `agents`. Parse with `ast`; do not grep.
2. An **AST-based** test that walks `backend/gateway/evidence/**/*.py` and fails on imports of
   `requests`, `httpx`, `urllib.request`, `socket`, MCP SDK modules, or project secret/config
   loaders. `sqlite3`, `pathlib` (in `store.py`) and deterministic stdlib stay allowed.
3. A zero-spend structural test: a `PlanBudget` built with no explicit cost cap has
   `max_cost_minor == 0`, and the first positive `record_external_cost()` raises.

Write each red first, confirm it fails, then make it pass.

### Gate I0 — run every command, paste every output

```bash
cd /Users/himanshu_jain/TripPlanner/.worktrees/itinerary-i0-evidence-hardening/backend
.venv/bin/pytest -q
.venv/bin/pytest evals/test_evidence_*.py -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/
.venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py
.venv/bin/ruff check gateway/ evals/ 2>&1 | tail -2
cd ..
git diff --exit-code -- backend/evals/golden/ && echo "GOLDENS UNCHANGED"
git diff --exit-code -- contract/openapi.json && echo "CONTRACT UNCHANGED"
git diff --check
cmp AGENTS.md CLAUDE.md && echo "BRIEFS IDENTICAL"
git status --short
git log --oneline aa08dd4..HEAD
```

Required results: every test passes and the total is **well above 161**; strict typing clean;
I0-owned Ruff **zero**; full `gateway/ evals/` Ruff **≤ 41**; goldens and OpenAPI byte-unchanged;
`AGENTS.md` and `CLAUDE.md` identical; working tree empty; seven commits (Tasks 1–2 already
there, plus yours).

`AGENTS.md` and `CLAUDE.md` currently **differ at line 51** — reconcile them (the I0 checkpoint
bullet goes in both, identical text) and prove it with `cmp`.

### Report

Write `reports/itinerary_i0_evidence_hardening.md` containing: the commit list and behavior
delivered per task; test count before/after; the **exact gate command outputs, quoted not
paraphrased**; persistence migration coverage; confirmation of the USD 0 path and that no new
dependency, credential or network call was added; scoped and full Ruff counts; the golden-diff
result; deviations added (or "none"); and the next phase (I2 — place contracts, provider
registry, `SamplePlaceAdapter`).

Add a concise I0-complete checkpoint bullet to **both** `AGENTS.md` and `CLAUDE.md` with the
final test count and report path. Same text in both.

**Commit:** `test(gateway): close itinerary I0 evidence gate`

---

# PART 3 — DEFINITION OF DONE

I0 is complete only when the evidence graph can: reject malformed relationships before mutation;
resolve only typed exact identities with ranked (not lexicographic) canonical selection; detect
contradictions without input-order dependence and with per-kind comparison fields; round-trip
every graph object idempotently including reversed resolutions; distinguish freshness from
lifecycle; enforce zero external spend by default — **and** pass every command in the Gate I0
block above with every prior golden unchanged.

Your final response must contain, in this order:

1. The five task names, restated (proves you read Part 2).
2. Per task: what you implemented, the commit sha, and the test count delta.
3. The complete Gate I0 command block output, pasted raw.
4. A one-line answer to each: Did the test count increase in every task? Is `git status --short`
   empty? Are goldens unchanged? Is `contract/openapi.json` unchanged? Do `AGENTS.md` and
   `CLAUDE.md` match? Is I0-owned Ruff zero? Is full Ruff ≤ 41?
5. Anything you could not complete, stated plainly. **An honest "I did not finish Task 5's
   migration" is far more useful than a false "complete".** You will be checked.

Do not push, do not merge, do not open a PR. Leave the branch and report.

If a red test fails for a reason you did not predict, stop and diagnose before changing
production code — do not adjust the test to match the behavior you happened to get.
