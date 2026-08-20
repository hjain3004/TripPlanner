# Itinerary I0 — Evidence Graph Hardening Implementation Plan

> **For the implementing agent:** REQUIRED SKILL: use
> `superpowers:executing-plans` or `superpowers:subagent-driven-development` to execute this
> plan task-by-task. Use `superpowers:test-driven-development` for every behavior change and
> `superpowers:verification-before-completion` before declaring the phase complete.

**Goal:** Repair the evidence graph's correctness and persistence defects so place, route and
itinerary evidence can safely depend on it in I1–I8.

**Architecture:** Keep `backend/gateway/evidence/` deterministic and provider-independent.
Strengthen its typed temporal/run metadata, make edges and identity resolution invalid-state
resistant, route contradictions through explicit per-schema policies, and persist the complete
graph idempotently in SQLite. Nothing in this phase calls a provider, adds a credential, changes
Kernel money behavior or alters the API/OpenAPI contract.

**Tech stack:** Python 3.11+, Pydantic v2, stdlib `sqlite3`, pytest, mypy strict, Ruff. No new
runtime dependency and no network access.

**Source design:**
`docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md` Phase I0.

**Current baseline verified 2026-08-02:**

- `cd backend && .venv/bin/pytest -q` — **133 passed**, one third-party deprecation warning.
- `cd backend && .venv/bin/mypy --strict gateway/ agents/ api/ core/` — clean, 42 files.
- I0-owned Ruff surface — **10 existing errors**.
- Full `gateway/ evals/` Ruff surface — **41 existing errors**; unrelated historical eval lint
  is not silently folded into this behavior phase.
- Existing unrelated untracked files:
  `docs/superpowers/plans/2026-07-29-itinerary-accuracy.md` and
  `frontend/PROBE_REV2_HANDOFF_PROMPT.md`. Preserve them exactly.

---

## Binding constraints

1. **USD 0 out of pocket.** `PlanBudget.max_cost_minor` defaults to zero and positive external
   spend fails closed across provider and LLM calls. This phase installs nothing and calls no
   service.
2. **No money math.** The graph stores and compares normalized evidence. It does not compute
   rewards, fees, points value or effective cost.
3. **No graph-to-kernel import.** `backend/core/` imports neither `gateway` nor `agents`.
4. **No LLM or provider I/O.** No HTTP, MCP, filesystem discovery or secret access.
5. **No deletion of lineage.** Claims and resolution records remain addressable after
   supersession or reversal.
6. **Status and lifecycle remain orthogonal.** `stale`/`verify_required` describe evidence;
   `active`/`superseded` describe graph lifecycle.
7. **Behavior and cleanup are separate commits.** Do not auto-fix Ruff across all of `evals/`.
8. **`docs/specs/` remains read-only.** Log a conflict rather than editing an authoritative spec
   during implementation.
9. **The 12 optimizer goldens and transfer goldens must not change.** An empty diff over
   `backend/evals/golden/` is part of the final gate.

---

## Intended file map

```text
backend/gateway/evidence/
  budget.py             # zero-cost ledger
  nodes.py              # typed run/source/claim/evaluation metadata
  identity.py           # discriminated identity contracts
  edges.py              # direction/type validation and duplicate prevention
  invariants.py         # graph audit, including bypassed construction
  freshness.py          # typed expiry and supersession
  resolution.py         # exact, reversible resolution records
  contradiction.py      # per-schema comparison policies
  store.py              # complete idempotent SQLite persistence

backend/evals/
  conftest.py
  test_evidence_budget.py
  test_evidence_nodes.py
  test_evidence_edges.py              # new
  test_evidence_invariants.py
  test_evidence_freshness.py
  test_evidence_resolution.py
  test_evidence_contradiction.py
  test_evidence_store.py
  test_evidence_boundary.py           # new

reports/itinerary_i0_evidence_hardening.md
```

Do not add place-provider contracts here; those belong to I2. `identity.py` supplies only the
closed set required to stop current quote/observation claims being merged arbitrarily.

---

## Task 1 — Enforce zero spend and type temporal/run ownership

**Files**

- Modify: `backend/gateway/evidence/budget.py`
- Modify: `backend/gateway/evidence/nodes.py`
- Modify: `backend/gateway/evidence/freshness.py`
- Modify: `backend/evals/conftest.py`
- Modify: `backend/evals/test_evidence_budget.py`
- Modify: `backend/evals/test_evidence_nodes.py`
- Modify: `backend/evals/test_evidence_freshness.py`

### Contract after this task

```python
class PlanBudget(BaseModel):
    # existing non-cost fields unchanged
    max_cost_minor: int = Field(default=0, ge=0)

class BudgetLedger:
    external_cost_minor: int
    def record_external_cost(self, amount_minor: int) -> None: ...

class Source(BaseModel):
    source_id: str
    run_id: str
    provider: str
    adapter_id: str
    retrieved_at: AwareDatetime
    source_url: str
    terms_ref: str | None

class Claim(BaseModel):
    # existing fields unchanged
    expires_at: AwareDatetime | None = None

class Run(BaseModel):
    run_id: str
    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None

class Evaluation(BaseModel):
    # existing fields unchanged
    run_id: str
```

`AwareDatetime` is `pydantic.AwareDatetime`. Expiry moves out of arbitrary `payload` and into
typed claim metadata. Do not retain two expiry sources.

### Steps

- [ ] Add failing tests first:

  - `test_plan_budget_defaults_to_zero_external_spend`
  - `test_budget_ledger_accepts_zero_cost`
  - `test_budget_ledger_rejects_first_positive_cost_without_incrementing`
  - `test_budget_ledger_rejects_cumulative_cost_above_explicit_cap`
  - `test_source_requires_timezone_aware_retrieved_at`
  - `test_run_rejects_ended_at_before_started_at`
  - `test_claim_requires_timezone_aware_expiry`
  - `test_claim_expires_at_exact_expiry_instant`

- [ ] Run the red tests:

  ```bash
  cd backend
  .venv/bin/pytest evals/test_evidence_budget.py evals/test_evidence_nodes.py \
    evals/test_evidence_freshness.py -q
  ```

  Expected: failures for the absent cost ledger and string/naive timestamp acceptance.

- [ ] Implement `BudgetLedger.record_external_cost()` using integer-only addition. Validate
  `amount_minor >= 0`; check the prospective total before mutating the ledger; raise
  `BudgetExhausted("max_cost_minor=... exhausted")` on overflow.

- [ ] Add `run_id` to `Source` and `Evaluation`. Update only evidence fixtures/tests in this
  task; no runtime API consumes these models yet.

- [ ] Replace string timestamps with `AwareDatetime`. Add a `Run` model validator requiring
  `ended_at is None or ended_at >= started_at`.

- [ ] Change `is_expired(claim, now)` to accept an aware `datetime` and return
  `now >= claim.expires_at`. This exact equality follows spec 16: evidence is live only while
  `now < expires_at`.

- [ ] Update `mark_stale()` and evidence fixtures to use typed datetimes. Remove
  `payload["expires_at"]` everywhere in the repository.

- [ ] Run the focused tests until green, then:

  ```bash
  cd backend
  .venv/bin/mypy --strict gateway/evidence/budget.py gateway/evidence/nodes.py \
    gateway/evidence/freshness.py
  ```

- [ ] Commit only Task 1:

  ```bash
  git add backend/gateway/evidence/budget.py backend/gateway/evidence/nodes.py \
    backend/gateway/evidence/freshness.py backend/evals/conftest.py \
    backend/evals/test_evidence_budget.py backend/evals/test_evidence_nodes.py \
    backend/evals/test_evidence_freshness.py
  git commit -m "fix(gateway): enforce zero spend and typed evidence time"
  ```

---

## Task 2 — Make invalid and duplicate edges unrepresentable

**Files**

- Modify: `backend/gateway/evidence/edges.py`
- Modify: `backend/gateway/evidence/invariants.py`
- Modify: `backend/gateway/evidence/freshness.py`
- Create: `backend/evals/test_evidence_edges.py`
- Modify: `backend/evals/test_evidence_invariants.py`
- Modify: `backend/evals/test_evidence_freshness.py`

### Contract after this task

```python
class Edge(BaseModel):
    kind: EdgeKind
    src: str
    dst: str
    created_by_run: str

class EvidenceGraph(BaseModel):
    # existing node dictionaries
    edges: list[Edge]

    def add_edge(self, edge: Edge) -> None:
        """Validate endpoints/direction and add once; exact repeats are idempotent."""
```

Allowed endpoint contracts:

| Edge | Source | Destination | Extra rule |
|---|---|---|---|
| `SUPPORTS` | `Source` | `Claim` | source ID equals claim's `source_id` |
| `CONTRADICTS` | `Claim` | `Claim` | different IDs; reverse orientation is the same edge |
| `SUPERSEDES` | new `Claim` | old `Claim` | old claim points to new claim |
| `RESOLVED_TO` | member `Claim` | canonical `Claim` | different IDs |
| `DERIVED_FROM` | `Artifact` | `Claim` or `Artifact` | different IDs |
| `EVALUATED_BY` | `Claim` or `Artifact` | `Evaluation` | subject ID equals source ID |

### Steps

- [ ] Write parameterized failing tests covering all six valid directions and at least one
  invalid direction for each edge kind.

- [ ] Add explicit tests:

  - `test_add_edge_rejects_missing_endpoint`
  - `test_add_edge_is_idempotent_for_exact_duplicate`
  - `test_contradiction_reverse_orientation_is_duplicate`
  - `test_supports_requires_claim_source_pointer`
  - `test_evaluated_by_requires_matching_subject`
  - `test_invariant_audit_finds_edge_inserted_by_model_copy_bypass`

- [ ] Run red tests:

  ```bash
  cd backend
  .venv/bin/pytest evals/test_evidence_edges.py evals/test_evidence_invariants.py -q
  ```

- [ ] Implement one internal endpoint classifier in `edges.py`; do not duplicate direction
  logic in each caller.

- [ ] Make `EvidenceGraph.add_edge()` validate node existence, direction and semantic pointer
  rules before mutation. Exact duplicate insertion is a no-op. For `CONTRADICTS`, compare a
  normalized key with sorted endpoints so reverse insertion is also a no-op.

- [ ] Keep `check_invariants()` as a full audit for deserialized or model-copied graphs that may
  bypass `add_edge()`. Have it reuse the same validator and turn exceptions into deterministic
  violation strings.

- [ ] Update every edge construction in `freshness.py` and evidence tests with
  `created_by_run`; do not use a default such as `r1`.

- [ ] Run focused tests and strict typing.

- [ ] Commit only Task 2:

  ```bash
  git add backend/gateway/evidence/edges.py backend/gateway/evidence/invariants.py \
    backend/gateway/evidence/freshness.py backend/evals/test_evidence_edges.py \
    backend/evals/test_evidence_invariants.py backend/evals/test_evidence_freshness.py
  git commit -m "fix(gateway): enforce evidence edge contracts"
  ```

---

## Task 3 — Replace arbitrary resolution with typed exact identity

**Files**

- Create: `backend/gateway/evidence/identity.py`
- Modify: `backend/gateway/evidence/nodes.py`
- Modify: `backend/gateway/evidence/edges.py`
- Modify: `backend/gateway/evidence/resolution.py`
- Modify: `backend/gateway/evidence/invariants.py`
- Modify: `backend/evals/conftest.py`
- Modify: `backend/evals/test_evidence_nodes.py`
- Modify: `backend/evals/test_evidence_resolution.py`
- Modify: `backend/evals/test_evidence_invariants.py`

### Identity types

Implement a Pydantic discriminated union, not `tuple[str, ...]` and not fuzzy name matching:

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
    segments: tuple[FlightSegmentIdentity, ...]
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
```

Expose `EvidenceIdentity` as the discriminated union and add `identity: EvidenceIdentity` to
`Claim`. A sandbox fixture uses the identity of the domain claim it represents; fixture/sample is
an evidence kind, not an identity kind.

### Resolution contract

```python
class ResolutionState(StrEnum):
    ACTIVE = "active"
    REVERSED = "reversed"

class ResolutionRecord(BaseModel):
    # existing fields
    state: ResolutionState = ResolutionState.ACTIVE
    reversed_by_run: str | None = None

class EvidenceGraph(BaseModel):
    resolutions: dict[str, ResolutionRecord]

def resolve(
    graph: EvidenceGraph,
    claim_ids: list[str],
    *,
    created_by_run: str,
    rule: Literal["exact_identity"] = "exact_identity",
) -> ResolutionRecord: ...

def unresolve(
    graph: EvidenceGraph,
    resolution_id: str,
    *,
    reversed_by_run: str,
) -> None: ...
```

Define `ResolutionState` and `ResolutionRecord` in `nodes.py`; `resolution.py` owns the
operations. This keeps `edges.py -> nodes.py` one-way and avoids a circular import between the
graph container and resolution functions.

### Steps

- [ ] Write failing identity validation tests for an empty segment list, naive datetimes and each
  union discriminator.

- [ ] Replace the permissive resolution tests with these cases:

  - exact identity with different prices resolves
  - different cabin, fare conditions, flight segment, hotel rate plan or award program rejects
  - missing claim ID rejects before graph mutation
  - duplicate member ID rejects
  - mixed identity kinds reject
  - superseded member rejects
  - resolution record and all members remain addressable
  - unresolve marks the record `REVERSED`, records `reversed_by_run`, removes only that
    resolution's active `RESOLVED_TO` edges and is idempotent
  - member input order does not change the canonical choice
  - a lexicographically smaller but stale/older/verify-required claim does not beat stronger
    evidence merely because of its ID

- [ ] Run red tests:

  ```bash
  cd backend
  .venv/bin/pytest evals/test_evidence_nodes.py evals/test_evidence_resolution.py \
    evals/test_evidence_invariants.py -q
  ```

- [ ] Implement exact equality over the typed identity model. Do not normalize provider payloads
  here and do not add fuzzy hotel/place matching; those belong to I2/I3.

- [ ] Select the canonical member without reading price values. Rank by:

  1. active lifecycle only (superseded members were already rejected),
  2. `needs_verification=False` before `True`,
  3. freshness priority `live`, `cached`, `estimated`, `verify_required`, `stale`,
  4. newest cited `Source.retrieved_at`,
  5. `claim_id` only as the final total-order tie-breaker.

  This keeps the result deterministic but prevents arbitrary lexicographic IDs from overriding
  stronger evidence.

- [ ] Store the record in `graph.resolutions` before adding `RESOLVED_TO` edges. A reversed record
  remains stored and addressable.

- [ ] Extend `check_invariants()` to verify resolution members/canonical IDs, edge agreement,
  active/reversed state and run existence.

- [ ] Run focused tests and `mypy --strict gateway/evidence/`.

- [ ] Commit only Task 3:

  ```bash
  git add backend/gateway/evidence/identity.py backend/gateway/evidence/nodes.py \
    backend/gateway/evidence/edges.py backend/gateway/evidence/resolution.py \
    backend/gateway/evidence/invariants.py backend/evals/conftest.py \
    backend/evals/test_evidence_nodes.py backend/evals/test_evidence_resolution.py \
    backend/evals/test_evidence_invariants.py
  git commit -m "fix(gateway): require typed exact evidence identity"
  ```

---

## Task 4 — Make contradiction detection schema-aware and order-independent

**Files**

- Modify: `backend/gateway/evidence/contradiction.py`
- Modify: `backend/evals/test_evidence_contradiction.py`

### Policy after this task

Keep named basis-point thresholds, but select the comparison field by evidence kind and identity:

| Evidence | Required typed identity | Integer comparison field | Threshold |
|---|---|---|---|
| current flight/hotel cash quote | flight/hotel quote | `total_minor` | 200 bp |
| cached flight observation | flight observation | `total_minor` | 1000 bp |
| award availability | award quote | `points_required` | 0 bp |
| sandbox/reference fact | any | none | no automatic contradiction |

The detector does not interpret arbitrary provider fields. Missing, boolean, non-integer or
non-positive comparison values are non-comparable and produce no edge plus a deterministic reason
available to the caller. Define a small `ContradictionResult(edges, skipped)` model rather than
silently dropping malformed pairs.

Use the symmetric formula:

```python
delta_bps = abs(left_value - right_value) * 10_000 // min(left_value, right_value)
```

Contradiction requires `delta_bps > threshold`; equality does not contradict.

### Steps

- [ ] Add failing tests for:

  - reversing claim IDs and input order produces the same normalized edge/result
  - award claims compare `points_required`, not `total_minor`
  - price observations and current quotes never compare to each other
  - different typed identities never compare
  - exact threshold does not contradict; one basis point above does
  - zero/negative/bool/string/missing values create a skipped reason, not a crash
  - sandbox and reference facts are explicitly unsupported

- [ ] Run red test:

  ```bash
  cd backend
  .venv/bin/pytest evals/test_evidence_contradiction.py -q
  ```

- [ ] Replace `flight_identity()` and universal `total_minor` access with the table above. Reuse
  `Claim.identity`; do not reconstruct identity from payload.

- [ ] Give each returned edge `created_by_run` from a required function argument. Return edges in
  stable `(kind, src, dst)` order.

- [ ] Run focused tests and strict typing.

- [ ] Commit only Task 4:

  ```bash
  git add backend/gateway/evidence/contradiction.py \
    backend/evals/test_evidence_contradiction.py
  git commit -m "fix(gateway): compare contradictions by evidence schema"
  ```

---

## Task 5 — Persist the complete graph idempotently in SQLite

**Files**

- Modify: `backend/gateway/evidence/store.py`
- Modify: `backend/evals/test_evidence_store.py`

### Store contract after this task

`SqliteEvidenceStore.save(graph)` persists:

- sources
- claims
- artifacts
- runs
- evaluations
- resolution records, including reversed state
- edges, including authoring run

`SqliteEvidenceStore.load(run_id)` returns the run-authored subgraph plus every source, claim,
artifact, evaluation, resolution and edge needed to make that subgraph's lineage pointers
addressable. It must pass `check_invariants()` before returning.

SQLite schema requirements:

- `PRAGMA foreign_keys = ON` for applicable same-table relationships.
- `PRAGMA user_version = 2` after migration.
- one table per node/record type; JSON bodies remain schema-normalized Pydantic JSON.
- `edges` primary key: `(kind, src, dst, created_by_run)`.
- explicit indexes on node `run_id`, resolution `created_by_run` and edge
  `created_by_run/src/dst`.
- transaction around validation, synchronization and inserts.
- use parameterized SQL only.

### Steps

- [ ] Replace the two narrow round-trip tests with a complete graph fixture containing two runs,
  two sources, claims, an artifact derived from a claim and another artifact, an evaluation, an
  active resolution, a superseded claim and all six edge kinds.

- [ ] Add failing tests:

  - `test_round_trip_preserves_every_node_record_and_edge`
  - `test_save_same_graph_twice_is_byte_and_row_count_idempotent`
  - `test_save_updated_run_removes_stale_edges_for_that_run`
  - `test_save_updated_run_does_not_delete_other_run`
  - `test_load_run_includes_cross_run_lineage_closure`
  - `test_reversed_resolution_survives_round_trip`
  - `test_save_rejects_invalid_graph_before_writing`
  - `test_failed_save_rolls_back_all_tables`
  - `test_v1_store_migrates_without_losing_sources_claims_or_edges`

- [ ] Create the red v1 fixture inside the test using the old three-table SQL; do not commit a
  binary SQLite file.

- [ ] Run red tests:

  ```bash
  cd backend
  .venv/bin/pytest evals/test_evidence_store.py -q
  ```

- [ ] Replace `_run_id_for()` and its `"r1"` fallback. Every persisted object now carries or
  deterministically references a real authoring run.

- [ ] Before mutation, call `check_invariants()` and raise a typed `EvidenceStoreError` containing
  stable violations. Never persist a partially invalid graph.

- [ ] On save, collect touched run IDs from nodes, records and edges in the supplied graph. Upsert
  addressable nodes/records. Synchronize edges and resolutions authored by touched runs inside the
  same transaction so removed edges do not remain stale in SQLite. Never delete claims merely
  because they are absent from a partial run view.

- [ ] Implement v1-to-v2 migration in one transaction. Preserve the old rows, backfill edge/source
  run ownership only when it can be derived uniquely from connected claims, and raise a clear
  migration error rather than inventing `r1` when it cannot.

- [ ] Build the loaded graph with nodes first and validated edges second. Resolve cross-run
  lineage recursively until no new referenced node IDs are discovered.

- [ ] Run focused tests and strict typing.

- [ ] Commit only Task 5:

  ```bash
  git add backend/gateway/evidence/store.py backend/evals/test_evidence_store.py
  git commit -m "fix(gateway): persist complete evidence graphs idempotently"
  ```

---

## Task 6 — Separate stale from superseded and clean the I0-owned surface

**Files**

- Modify: `docs/superpowers/specs/2026-07-28-evidence-graph-orchestration-design.md`
- Modify: `docs/superpowers/specs/2026-07-29-visual-system-reconciled.md`
- Modify: `docs/superpowers/plans/2026-07-28-evidence-graph-core.md`
- Modify: `docs/superpowers/plans/2026-07-29-visual-system-reconciliation.md`
- Modify: I0-owned files under `backend/gateway/evidence/` and `backend/evals/test_evidence_*.py`
- Modify: `backend/evals/conftest.py`
- Delete: `test_fix2.py`
- Modify: `backend/evals/test_evidence_nodes.py`

This task is documentation/test-placement/lint cleanup only. Do not change graph behavior.

### Steps

- [ ] Move `test_contradicts_field_removed` from root `test_fix2.py` into
  `backend/evals/test_evidence_nodes.py`, then delete `test_fix2.py`. Verify it appears in normal
  pytest collection.

- [ ] Remove the stale `contradicts: list[str]` field from the 2026-07-28 design example. State
  that `CONTRADICTS` edges are canonical.

- [ ] Correct both visual mappings:

  - `FreshnessState.STALE` → grey plate with diagonal **STALE** overprint.
  - `LifecycleState.SUPERSEDED` → graph lifecycle treatment with diagonal **SUPERSEDED**
    overprint; it is not a freshness status.

  This is a contract clarification for I6, not frontend implementation in I0.

- [ ] Add a top-of-file status note to the old evidence-core plan: implementation landed; this
  I0 plan supersedes its code snippets. Do not mechanically rewrite its historical tasks.

- [ ] Fix only the 10 known Ruff findings in the I0-owned surface. Use Ruff's suggestions but
  review the diff; do not run `--fix` across all evals.

- [ ] Run:

  ```bash
  cd backend
  .venv/bin/pytest --collect-only -q | rg test_contradicts_field_removed
  .venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py
  ```

  Expected: the moved test is collected and the scoped Ruff command is clean.

- [ ] Commit only Task 6:

  ```bash
  git add docs/superpowers/specs/2026-07-28-evidence-graph-orchestration-design.md \
    docs/superpowers/specs/2026-07-29-visual-system-reconciled.md \
    docs/superpowers/plans/2026-07-28-evidence-graph-core.md \
    docs/superpowers/plans/2026-07-29-visual-system-reconciliation.md \
    backend/gateway/evidence backend/evals/conftest.py backend/evals/test_evidence_*.py \
    test_fix2.py
  git commit -m "docs: align evidence lifecycle and test discovery"
  ```

---

## Task 7 — Prove the I0 boundary and publish its gate report

**Files**

- Create: `backend/evals/test_evidence_boundary.py`
- Create: `reports/itinerary_i0_evidence_hardening.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `DEVIATIONS.md` only if implementation made a judgment call not already specified

### Boundary tests

- [ ] Add an AST test that recursively scans `backend/core/**/*.py` and rejects imports whose
  module begins with `gateway` or `agents`.

- [ ] Add an AST test that scans `backend/gateway/evidence/**/*.py` and rejects imports of
  `requests`, `httpx`, `urllib.request`, `socket`, MCP SDK modules and project secret/config
  loaders. `sqlite3`, `pathlib` in `store.py`, and deterministic stdlib modules remain allowed.

- [ ] Add a zero-spend structural test asserting `PlanBudget` without an explicit cost cap has
  `max_cost_minor == 0` and the first positive recorded cost fails.

- [ ] Run the focused boundary test red, implement only what it exposes, then make it green.

### Final Gate I0

Run from repository root unless a command says otherwise:

```bash
cd backend && .venv/bin/pytest -q
cd backend && .venv/bin/pytest evals/test_evidence_*.py -q
cd backend && .venv/bin/mypy --strict gateway/ agents/ api/ core/
cd backend && .venv/bin/ruff check gateway/evidence/ evals/test_evidence_*.py evals/conftest.py
git diff --exit-code -- backend/evals/golden/
cmp AGENTS.md CLAUDE.md
git diff --check
```

Required results:

- all original 133 tests plus every new I0 test pass;
- no evidence test remains outside normal collection;
- strict typing remains clean;
- the I0-owned Ruff surface has zero findings;
- optimizer/transfer golden fixtures are byte-unchanged;
- canonical agent briefs are identical;
- no paid dependency, credential, live network call or provider configuration was added.

The full historical `gateway/ evals/` Ruff count may remain outside this phase, but it must not
increase above its recorded baseline of 41. Record the ending count in the report; do not edit
unrelated eval files to make the number look better.

### Report

- [ ] Write `reports/itinerary_i0_evidence_hardening.md` with:

  - commit list and behavior delivered per task;
  - before/after backend and focused evidence test counts;
  - exact gate commands and outputs;
  - persistence migration coverage;
  - confirmation of the USD 0 path and no new dependencies;
  - scoped/full Ruff counts;
  - golden-fixture diff result;
  - deviations added, or “none”;
  - the next phase: I1 closed-world itinerary safety.

- [ ] Add a concise I0-complete checkpoint bullet to both `AGENTS.md` and `CLAUDE.md`, including
  the final test count and report path. Apply the same text to both and prove with `cmp`.

- [ ] Invoke `superpowers:requesting-code-review` and give the reviewer the range from the commit
  preceding Task 1 through the current HEAD. Resolve all Critical/Important findings or document
  a technically justified rejection before continuing.

- [ ] Re-run the full Gate I0 after review changes.

- [ ] Commit the gate/report separately:

  ```bash
  git add backend/evals/test_evidence_boundary.py \
    reports/itinerary_i0_evidence_hardening.md AGENTS.md CLAUDE.md DEVIATIONS.md
  git commit -m "test(gateway): close itinerary I0 evidence gate"
  ```

---

## Execution discipline

1. Create or switch to `codex/itinerary-i0-evidence-hardening`; do not work directly on `main`.
2. Read `DEVIATIONS.md`, the newest report, spec 06, this plan and only the referenced evidence
   specs before editing.
3. Invoke `superpowers:test-driven-development`; every behavior task starts with a demonstrated
   failing test.
4. If a red test fails for an unexpected reason, invoke `superpowers:systematic-debugging`
   before changing production code.
5. Preserve the two unrelated untracked files named in the baseline.
6. Keep commits aligned with the seven tasks. Never combine a behavior change with broad lint or
   refactor cleanup.
7. Do not push, deploy, activate a provider or request a credential as part of I0.
8. Before claiming completion, invoke `superpowers:verification-before-completion`, run the gate
   from a clean working tree and quote the observed results in the report.
9. Finish with `superpowers:finishing-a-development-branch`; present merge/PR/local options to the
   human rather than choosing an external action silently.

---

## I0 exit condition

I0 is complete only when the evidence graph can reject malformed relationships before mutation,
resolve only typed exact identities, detect contradictions without input-order dependence,
round-trip every graph object idempotently, distinguish freshness from lifecycle, enforce zero
external spend by default, and pass the final gate with every prior golden unchanged.

Only then write/execute the separate I1 closed-world itinerary-safety plan. Do not begin Overture,
Wikimedia/OSM ingestion, OR-Tools, routing, MapLibre or provider/MCP work in the I0 branch.
