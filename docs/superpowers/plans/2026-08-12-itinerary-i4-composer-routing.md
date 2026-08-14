# Itinerary I4 — Composer, Route Matrix and OR-Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this
> plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Also required:
> `superpowers:test-driven-development`, `superpowers:systematic-debugging`,
> `superpowers:verification-before-completion`.

**Goal:** Turn the I3 catalog's larger candidate set into valid, pleasant days — with hard
constraints that hold regardless of candidate ordering, a route abstraction that never lies about
whether a duration was routed or estimated, and OR-Tools introduced only behind the interface the
existing deterministic composer already satisfies.

**Architecture:** The I1 greedy composer in `core/itinerary/compose.py` becomes the *baseline
implementation* of a new `Composer` protocol, not the only one. A `RouteMatrix` abstraction sits
between the composer and any travel-time source, so the geodesic estimator stays usable and a real
routing adapter can arrive later without touching the composer. A separate deterministic validator
runs after every draft. OR-Tools is added last, behind the same protocol, with a fixed seed and a
bounded time limit; timeout or infeasibility falls back to the baseline and says why.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, hypothesis (already a dev dependency), mypy
--strict, ruff. **One new runtime dependency: `ortools`** (Apache-2.0, free — see Global
Constraint 2).

---

## Global Constraints

1. **Money goldens are frozen.** `backend/evals/golden/` must not change. The composer's objective
   contains **no money or points arithmetic** (spec §7): admission cost is a normalized costed line
   evaluated later by deterministic financial code. If a golden moves, you have put money math in
   the composer — stop and report.
2. **USD 0 holds.** `ortools` is Apache-2.0 and free to install; adding it costs nothing and calls
   nothing. It must not reach the network at import or solve time. No routing *service* is added in
   this phase — spec §8 says plainly: *"The route implementation can therefore be deferred without
   blocking place discovery or the basic itinerary composer."*
3. **No live network, in tests or at request time.** Valhalla, TomTom, Google and every other
   routing vendor stay out. Spec §8's fallback order stops at level 3 (geodesic estimate) for this
   phase.
4. **An estimate is never labeled routed.** Every `RouteCell` carries an explicit
   `status: "routed" | "estimated"` and a `source`. Spec §5.3: *"An estimate is never labeled routed
   travel time."*
5. **Unknown hours never become open.** Carried forward from I1/I3. Known closed = infeasible.
   Unknown = scheduled only if not timing-critical, with a visible verification task.
6. **`backend/core/` imports nothing from `agents/`, `api/` or `gateway/`.** Enforced by
   `evals/test_evidence_boundary.py` and `evals/test_catalog_boundary.py`. The composer lives in
   `core/`; the catalog lives in `gateway/`. **Orchestration maps gateway output into kernel inputs
   — `core/` must never reach for the catalog itself.**
7. **The LLM cannot override a failed constraint.** Spec §7: the critic may propose a revision; the
   deterministic validator decides. No prompt change in this phase.
8. **No `ruff --fix` outside files you create.** Baseline is **9 errors** on
   `ruff check gateway/ evals/` — do not increase it. Files you create must be at **zero**.
9. **Report numbers you measured.** Not estimated, not retyped.

---

## Measured Baseline

Verify in Task 0. Measured on `feat/i3-open-data-catalog` @ `2cc9257`, 2026-08-12.

| Metric | Value |
|---|---|
| `pytest -q` | **331 passed** |
| `mypy --strict core/ agents/ api/ gateway/` | clean, **65 source files** |
| `ruff check gateway/ evals/` | **9 errors** (ceiling — must not increase) |
| `ruff check gateway/catalog/ evals/test_catalog_*.py` | clean |

---

## Known-Bad Patterns

The full table is in `docs/superpowers/plans/2026-08-11-itinerary-i3-open-data-catalog.md`. **Read
it.** The two that recurred most recently:

- **I3 shipped with ruff at 94 errors against a 9-error ceiling**, reported as "fully green,"
  because only 3 of 12 gate commands were pasted. Paste every command.
- **I3's shuffle-determinism test passed while never exercising the merge path** — the fixture
  produced zero merges, so the code most likely to be order-dependent was never crossed. When you
  write an invariance test, *prove the interesting branch actually runs.*

**Red-then-green is mandatory.** Write the test, run it, **paste the failure**, then implement.

---

## Task 0: Preflight

- [ ] **Step 1: Confirm state**

```bash
cd /Users/himanshu_jain/TripPlanner
git status --short          # must be empty
git branch --show-current   # expect: main, after the I3 merge
cd backend && .venv/bin/pytest -q | tail -2
.venv/bin/mypy --strict core/ agents/ api/ gateway/ | tail -2
.venv/bin/ruff check gateway/ evals/ 2>&1 | tail -2
```

Expect **331 passed**, **65 files**, **9 ruff errors**. If any differs, stop and report.

- [ ] **Step 2: Branch**

```bash
git checkout -b feat/i4-composer-routing
```

- [ ] **Step 3: Add the OR-Tools dependency but do not use it yet**

In `backend/pyproject.toml`, add to `[project] dependencies`:

```toml
    "ortools>=9.10",
```

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -c "from ortools.sat.python import cp_model; print('ortools ok')"
.venv/bin/pytest -q | tail -2   # still 331 — adding a dep changes nothing yet
```

```bash
git add backend/pyproject.toml
git commit -m "build: add ortools for the I4 composer"
```

---

## File Structure

**Create:**

```
backend/core/itinerary/contracts.py    # RouteMatrix, ItineraryConstraints, ItineraryDraft,
                                       #   ItineraryValidation, RouteCell, RejectionReason
backend/core/itinerary/protocol.py     # Composer protocol both implementations satisfy
backend/core/itinerary/routing.py      # GeodesicRouteSource -> RouteMatrix
backend/core/itinerary/validate.py     # deterministic post-draft validator
backend/core/itinerary/greedy.py       # I1 baseline, moved behind the protocol
backend/core/itinerary/ortools_composer.py
backend/evals/test_i4_contracts.py
backend/evals/test_i4_routing.py
backend/evals/test_i4_constraints.py
backend/evals/test_i4_validator.py
backend/evals/test_i4_invariance.py    # the Gate I4 headline
backend/evals/test_i4_ortools.py
backend/evals/test_i4_fallback.py
backend/evals/test_i4_benchmark.py
```

**Modify:**

- `backend/core/itinerary/compose.py` — keep `haversine_km`, `estimate_travel_min`,
  `check_poi_hours`, `ScheduleWarning`, `ComposerResult`; re-export from `greedy.py` so existing
  imports keep working
- `backend/agents/planner.py` — select a composer through the protocol
- `backend/agents/retrieval.py` — Task 10 only, catalog wiring
- `backend/pyproject.toml` — register `core.itinerary` submodules if needed

**Do not delete `compose.py`.** `agents/planner.py` and `evals/test_i1_safety.py` import from it.
Re-export rather than move, exactly as I0's boundary fix re-exported from `agents/models.py`.

---

## Task 1: The Four Contracts I2 Skipped

Spec §14 named these as I2 deliverables; they were never built. They belong here because I4 is what
consumes them.

**Files:** Create `core/itinerary/contracts.py`; Test `evals/test_i4_contracts.py`

**Produces:** `RouteCell`, `RouteMatrix`, `ItineraryConstraints`, `ItineraryDraft`,
`ItineraryValidation`, `RejectionReason` — used by every later task.

- [ ] **Step 1: Write the failing tests**

```python
# backend/evals/test_i4_contracts.py
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from core.itinerary.contracts import (
    ItineraryConstraints,
    ItineraryValidation,
    RouteCell,
    RouteMatrix,
)


def _cell(**over: object) -> RouteCell:
    base = dict(
        origin_place_id="pl_a", destination_place_id="pl_b", mode="transit",
        duration_min=18, distance_km=4.2, retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="geodesic_estimate", status="estimated", confidence=0.6,
    )
    base.update(over)
    return RouteCell(**base)  # type: ignore[arg-type]


def test_every_route_cell_carries_source_and_status() -> None:
    """Spec 8: each cell carries origin/destination, mode, duration, distance,
    retrieval time, source and confidence."""
    c = _cell()
    assert c.status == "estimated" and c.source and c.confidence is not None


def test_a_cell_cannot_claim_routed_status_without_a_routing_source() -> None:
    """Spec 5.3: 'An estimate is never labeled routed travel time.'"""
    with pytest.raises(ValidationError):
        _cell(status="routed", source="geodesic_estimate")


def test_route_matrix_lookup_is_symmetric_for_estimates() -> None:
    m = RouteMatrix(cells=[_cell()])
    assert m.duration_min("pl_a", "pl_b", "transit") == 18
    assert m.duration_min("pl_b", "pl_a", "transit") == 18


def test_missing_cell_returns_none_rather_than_zero() -> None:
    """A missing route must never silently read as 'no travel time'."""
    m = RouteMatrix(cells=[_cell()])
    assert m.duration_min("pl_a", "pl_zzz", "transit") is None


def test_constraints_reject_a_negative_travel_budget() -> None:
    with pytest.raises(ValidationError):
        ItineraryConstraints(max_daily_travel_min=-1)


def test_validation_result_lists_structured_reasons_not_prose() -> None:
    v = ItineraryValidation(
        valid=False,
        rejections=[{"code": "closed_day", "place_id": "pl_a", "detail": "closed Monday"}],
    )
    assert v.valid is False
    assert v.rejections[0].code == "closed_day"
```

- [ ] **Step 2: Run and paste the failure**

- [ ] **Step 3: Implement.** `RouteCell` needs a model validator enforcing that
  `status == "routed"` requires a `source` that is not `"geodesic_estimate"`. `RejectionReason.code`
  is a `Literal` covering at minimum: `overlap`, `closed_day`, `unknown_hours_timing_critical`,
  `travel_budget_exceeded`, `travel_time_infeasible`, `accessibility_excluded`,
  `fixed_window_violated`, `no_evidence_backed_place_id`.

- [ ] **Step 4: Paste the pass. Commit**

```bash
git commit -m "feat(core): add route matrix and itinerary contracts"
```

---

## Task 2: Geodesic Route Source

**Files:** Create `core/itinerary/routing.py`; Test `evals/test_i4_routing.py`

**Consumes:** `haversine_km` and `estimate_travel_min` — **already in `core/itinerary/compose.py`
at lines 84 and 98. Import them; do not reimplement.**

**Produces:** `build_geodesic_matrix(places, mode) -> RouteMatrix`

- [ ] **Step 1: Write the failing tests**

```python
def test_every_generated_cell_is_marked_estimated() -> None:
    m = build_geodesic_matrix(three_places, mode="transit")
    assert all(c.status == "estimated" for c in m.cells)
    assert all(c.source == "geodesic_estimate" for c in m.cells)


def test_matrix_covers_every_ordered_pair() -> None:
    m = build_geodesic_matrix(three_places, mode="transit")
    assert m.duration_min("pl_1", "pl_2", "transit") is not None
    assert m.duration_min("pl_2", "pl_3", "transit") is not None


def test_durations_match_the_existing_i1_estimator_exactly() -> None:
    """I4 must not silently re-tune I1's travel constants."""
    from core.itinerary.compose import estimate_travel_min
    m = build_geodesic_matrix(two_places, mode="transit")
    expected = estimate_travel_min(1.28, 103.85, 1.29, 103.86)
    assert m.duration_min("pl_1", "pl_2", "transit") == expected


def test_matrix_construction_is_order_independent() -> None:
    a = build_geodesic_matrix(three_places, mode="transit")
    b = build_geodesic_matrix(list(reversed(three_places)), mode="transit")
    assert sorted(c.model_dump_json() for c in a.cells) == \
           sorted(c.model_dump_json() for c in b.cells)


def test_a_place_without_coordinates_is_reported_not_guessed() -> None:
    m, unroutable = build_geodesic_matrix_with_gaps(places_one_missing_coords, mode="transit")
    assert "pl_nocoord" in unroutable
```

- [ ] **Step 2-4: red, implement, green, commit**

```bash
git commit -m "feat(core): build route matrices from geodesic estimates"
```

---

## Task 3: Composer Protocol and the Baseline Behind It

**Files:** Create `core/itinerary/protocol.py`, `core/itinerary/greedy.py`;
Modify `core/itinerary/compose.py`

**This is a refactor, not a behavior change.** Per `CLAUDE.md` → Anti-drift: *"Behavior changes and
refactors are separate commits; golden tests green between them."* This task must change **zero**
test expectations.

- [ ] **Step 1: Write the characterization test first**

```python
def test_greedy_composer_matches_compose_itinerary_exactly(spec, retrieval) -> None:
    """The protocol wrapper must be behavior-identical to the I1 function."""
    from core.itinerary.compose import compose_itinerary
    from core.itinerary.greedy import GreedyComposer
    legacy = compose_itinerary(spec, retrieval)
    wrapped = GreedyComposer().compose(spec, retrieval)
    assert wrapped.model_dump_json() == legacy.model_dump_json()
```

- [ ] **Step 2: Run it — it fails on import. Paste that.**

- [ ] **Step 3: Implement.** `protocol.py` defines:

```python
class Composer(Protocol):
    name: str
    def compose(
        self, spec: TripSpec, retrieval: RetrievalContext,
        matrix: RouteMatrix | None = None,
        constraints: ItineraryConstraints | None = None,
    ) -> ComposerResult: ...
```

`GreedyComposer.compose` delegates to the existing `compose_itinerary`. Do not rewrite its logic.

- [ ] **Step 4: The entire suite must still pass at 331 + your new tests.** If any pre-existing test
  changed, you altered behavior in a refactor commit. Revert and split.

- [ ] **Step 5: Commit**

```bash
git commit -m "refactor(core): put the greedy composer behind the Composer protocol"
```

---

## Task 4: Hard Constraints and Structured Rejection Reasons

**Files:** Create `core/itinerary/validate.py`; Test `evals/test_i4_constraints.py`

Implement every spec §7 hard constraint as a named, independently testable predicate:

no overlap · arrival/departure buffers · open during the visit interval when hours are trusted ·
travel time fits between adjacent stops · fixed activities inside their window · accessibility
exclusions honored · daily travel and activity limits · every stop resolves to an evidence-backed
`PlaceId`.

- [ ] **Step 1: Write one failing test per constraint.** Eight constraints, at least eight tests,
  each asserting the specific `RejectionReason.code`. Example:

```python
def test_a_stop_without_an_evidence_backed_place_id_is_rejected() -> None:
    result = validate_draft(draft_with_invented_place, matrix, constraints)
    assert result.valid is False
    assert any(r.code == "no_evidence_backed_place_id" for r in result.rejections)


def test_travel_time_that_does_not_fit_is_rejected_with_both_place_ids() -> None:
    result = validate_draft(draft_impossible_transition, matrix, constraints)
    bad = next(r for r in result.rejections if r.code == "travel_time_infeasible")
    assert bad.place_id and bad.detail
```

- [ ] **Step 2-4: red, implement, green, commit**

```bash
git commit -m "feat(core): validate itinerary drafts against hard constraints"
```

---

## Task 5: Soft Objectives and Scoring

**Files:** Modify `core/itinerary/greedy.py`; Test extends `evals/test_i4_constraints.py`

Spec §7 soft objectives: interest fit · geographic coherence · preference for stronger/fresher
evidence · variety without needless category repetition · meal/rest alignment · avoiding
backtracking and rushed transitions · must-dos before optional fillers.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_objective_contains_no_money_or_points_arithmetic() -> None:
    """Spec 7: 'The objective contains no money or points arithmetic.'"""
    import ast, inspect
    from core.itinerary import greedy
    src = inspect.getsource(greedy.score_draft)
    tree = ast.parse(src)
    banned = {"minor", "cents", "points", "reward", "fee", "cashback", "bps"}
    names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (names & banned), f"money math in the composer objective: {names & banned}"


def test_a_must_do_outranks_an_optional_filler() -> None:
    result = GreedyComposer().compose(spec_with_must_do, retrieval, matrix)
    assert "pl_must" in [i.place_id for d in result.itinerary.days for i in d.items]


def test_fresher_evidence_is_preferred_between_equal_candidates() -> None:
    result = GreedyComposer().compose(spec, retrieval_two_equal_one_stale, matrix)
    chosen = [i.place_id for d in result.itinerary.days for i in d.items]
    assert "pl_fresh" in chosen and "pl_stale" not in chosen


def test_scoring_is_deterministic_across_repeated_calls() -> None:
    a = score_draft(draft, matrix, constraints)
    b = score_draft(draft, matrix, constraints)
    assert a == b
```

- [ ] **Step 2-4: red, implement, green, commit.** Weights are Tier C — log them in `DEVIATIONS.md`.

```bash
git commit -m "feat(core): score drafts against soft itinerary objectives"
```

---

## Task 6: Order Invariance — the Gate I4 Headline

**Files:** Test `evals/test_i4_invariance.py`

**Gate I4:** *"all hard constraints are invariant under candidate ordering."*

I3's lesson applies directly: an invariance test that shuffles inputs which cannot interact proves
nothing. **Your fixtures must contain candidates that genuinely compete** — overlapping time
windows, shared categories, tight travel budgets — and you must prove they do.

- [ ] **Step 1: Write the tests, using `hypothesis` (already a dev dependency)**

```python
from hypothesis import given, settings, strategies as st


@given(order=st.permutations(range(8)))
@settings(max_examples=50, deadline=None)
def test_validity_is_invariant_under_candidate_ordering(order: list[int]) -> None:
    """The chosen itinerary may differ; whether it is VALID must not."""
    candidates = [COMPETING_CANDIDATES[i] for i in order]
    result = GreedyComposer().compose(spec, ctx(candidates), matrix)
    validation = validate_draft(result.itinerary, matrix, constraints)
    assert validation.valid, f"ordering {order} produced an invalid itinerary"


@given(order=st.permutations(range(8)))
@settings(max_examples=50, deadline=None)
def test_the_same_candidate_set_produces_the_same_itinerary(order: list[int]) -> None:
    """Stronger than validity: stable tie-breaking makes the OUTPUT identical too."""
    candidates = [COMPETING_CANDIDATES[i] for i in order]
    result = GreedyComposer().compose(spec, ctx(candidates), matrix)
    assert result.itinerary.model_dump_json() == CANONICAL_ITINERARY_JSON


def test_the_fixture_candidates_actually_compete() -> None:
    """Guard against a vacuous invariance test — see the I3 shuffle-test failure."""
    result = GreedyComposer().compose(spec, ctx(COMPETING_CANDIDATES), matrix)
    scheduled = {i.place_id for d in result.itinerary.days for i in d.items}
    assert len(scheduled) < len(COMPETING_CANDIDATES), \
        "every candidate fit — they do not compete, so invariance is untested"
```

That last test is not optional. **Paste its output.**

- [ ] **Step 2-4: red, implement any tie-breaking fixes, green, commit**

```bash
git commit -m "test(core): prove hard constraints are invariant under candidate ordering"
```

---

## Task 7: OR-Tools Behind the Same Protocol

Spec §7: *"OR-Tools is introduced only behind the same interface after that baseline passes."*
Tasks 3–6 are that baseline. Do not start this task until they are green.

**Files:** Create `core/itinerary/ortools_composer.py`; Test `evals/test_i4_ortools.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_ortools_composer_satisfies_the_same_protocol() -> None:
    from core.itinerary.protocol import Composer
    assert isinstance(ORToolsComposer(), Composer)


def test_solver_runs_single_worker_with_a_fixed_seed() -> None:
    """Spec 7: fixed seed, deterministic ordering, a single worker, bounded time limit."""
    c = ORToolsComposer()
    assert c.solver_params.num_search_workers == 1
    assert c.solver_params.random_seed == ORToolsComposer.SEED
    assert 0 < c.solver_params.max_time_in_seconds <= 10


def test_two_solves_of_the_same_problem_are_identical() -> None:
    a = ORToolsComposer().compose(spec, retrieval, matrix)
    b = ORToolsComposer().compose(spec, retrieval, matrix)
    assert a.itinerary.model_dump_json() == b.itinerary.model_dump_json()


def test_solver_output_passes_the_same_validator() -> None:
    result = ORToolsComposer().compose(spec, retrieval, matrix)
    assert validate_draft(result.itinerary, matrix, constraints).valid


def test_solver_never_touches_the_network() -> None:
    import ast
    from pathlib import Path
    src = Path("core/itinerary/ortools_composer.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            mod = getattr(node, "module", None) or node.names[0].name
            assert mod.split(".")[0] not in {"requests", "httpx", "urllib", "socket"}
```

- [ ] **Step 2-4: red, implement, green, commit**

```bash
git commit -m "feat(core): add an OR-Tools composer behind the Composer protocol"
```

---

## Task 8: Fallback on Timeout and Infeasibility

Spec §7: *"Timeout or infeasibility falls back to the deterministic composer and emits a reason; it
never returns a solver's half-valid assignment as complete."*

**Files:** Modify `core/itinerary/ortools_composer.py`; Test `evals/test_i4_fallback.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_timeout_falls_back_to_greedy_and_says_so() -> None:
    c = ORToolsComposer(max_time_seconds=0.001)  # forces a timeout
    result = c.compose(spec, retrieval_large, matrix)
    assert result.fallback_reason == "solver_timeout"
    assert result.composer_used == "greedy"
    assert validate_draft(result.itinerary, matrix, constraints).valid


def test_infeasible_problem_falls_back_rather_than_returning_a_partial_assignment() -> None:
    result = ORToolsComposer().compose(spec, retrieval_infeasible, matrix)
    assert result.fallback_reason == "solver_infeasible"
    assert result.composer_used == "greedy"


def test_a_partial_day_returns_structured_reasons_not_silence() -> None:
    """Spec 12: 'Partial results remain structured.'"""
    result = ORToolsComposer().compose(spec, retrieval_partial, matrix)
    assert result.itinerary.days[0].unmet_needs
    assert all(r.code for r in result.itinerary.days[0].rejections)


def test_the_fallback_result_is_never_silently_labeled_optimal() -> None:
    result = ORToolsComposer(max_time_seconds=0.001).compose(spec, retrieval_large, matrix)
    assert result.composer_used != "ortools"
```

- [ ] **Step 2-4: red, implement, green, commit**

```bash
git commit -m "feat(core): fall back deterministically when the solver times out or is infeasible"
```

---

## Task 9: Wire the Composer Into the Planner

**Files:** Modify `backend/agents/planner.py`; Test extends `evals/test_i1_safety.py` — **do not
edit existing I1 assertions**, add new ones.

- [ ] **Step 1: Write the failing tests**

```python
def test_planner_selects_a_composer_through_the_protocol() -> None:
    result = plan_itinerary(spec, retrieval, composer=GreedyComposer())
    assert result.composer_used == "greedy"


def test_planner_still_rejects_unsafe_schedules_from_either_composer() -> None:
    """I1's guarantee must survive I4. _UNSAFE_WARNING_KINDS still enforced."""
    for composer in (GreedyComposer(), ORToolsComposer()):
        result = plan_itinerary(spec_forcing_closed_day, retrieval, composer=composer)
        assert result.used_fallback is True


def test_the_llm_cannot_override_a_failed_constraint() -> None:
    """Spec 7: the critic proposes; the validator decides."""
    result = plan_itinerary(spec, retrieval, composer=GreedyComposer(),
                            llm=ScriptedLLMClient(proposes_invalid_revision=True))
    assert validate_draft(result.itinerary, matrix, constraints).valid
```

- [ ] **Step 2-4: red, implement, green.** The full suite must still pass — I1's safety tests are
  the regression net here.

```bash
git commit -m "feat(agents): select the itinerary composer through the protocol"
```

---

## Task 10: Catalog Benchmark and Gate I4

**Files:** Modify `backend/agents/retrieval.py`; Create `evals/test_i4_benchmark.py`,
`reports/itinerary_i4_composer_routing.md`; Modify `DEVIATIONS.md`, `CLAUDE.md`, `AGENTS.md`

This is where I3's catalog finally reaches the planner.

**⚠ Expected-change warning.** Feeding the catalog into retrieval will change the *itinerary*
demo output. It must **not** change any money golden — those are driven by
`core/seeds/sample_flights.yaml` / `sample_hotels.yaml`, not by POIs. Decision rule:

- `backend/evals/golden/` changes → **stop and report.** You have coupled the composer to money math.
- `test_demo_output.py` itinerary text changes → expected. Update the fixture **in this commit
  only**, and quote the before/after diff in your report.

- [ ] **Step 1: Write the benchmark test**

Gate I4: *"benchmark fixtures beat or match the baseline on coherence without any validity
regression."*

```python
def test_ortools_matches_or_beats_greedy_on_coherence() -> None:
    for fixture in BENCHMARK_FIXTURES:
        g = GreedyComposer().compose(*fixture)
        o = ORToolsComposer().compose(*fixture)
        assert validate_draft(o.itinerary, *fixture[2:]).valid, "validity regression"
        assert score_draft(o.itinerary, ...) >= score_draft(g.itinerary, ...), \
            f"{fixture.name}: OR-Tools scored below the baseline"


def test_every_scheduled_route_cell_has_provenance_and_status() -> None:
    """Gate I4: 'every scheduled route cell has provenance/status'."""
    result = ORToolsComposer().compose(spec, retrieval_from_catalog, matrix)
    for day in result.itinerary.days:
        for item in day.items:
            if item.travel_from_previous is not None:
                assert item.travel_from_previous.source
                assert item.travel_from_previous.status in ("routed", "estimated")
```

Use **at least 4 benchmark fixtures** drawn from the I3 catalog: a sparse day, a dense day, a day
with a fixed reservation, and a day with unknown hours.

- [ ] **Step 2: Wire retrieval to the catalog.** Orchestration maps `SnapshotPlaceAdapter` output
  into `RetrievalContext`. **`core/` must not import `gateway/`** — the mapping happens in
  `agents/`. The boundary tests will catch you.

- [ ] **Step 3: Update `DEVIATIONS.md`** — soft-objective weights (Task 5), OR-Tools time limit and
  seed (Task 7), benchmark fixture selection (Task 10), and the `ortools` dependency addition.

- [ ] **Step 4: Update `CLAUDE.md` and `AGENTS.md`** with an I4 checkpoint. **Keep them
  byte-identical.**

- [ ] **Step 5: Write `reports/itinerary_i4_composer_routing.md`**, following
  `reports/itinerary_i3_open_data_catalog.md`.

- [ ] **Step 6: Run Gate I4 and paste every line**

```bash
cd /Users/himanshu_jain/TripPlanner/backend
.venv/bin/pytest -q
.venv/bin/pytest evals/test_i4_*.py -q
.venv/bin/pytest evals/test_i1_safety.py evals/test_determinism.py -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/
.venv/bin/ruff check core/itinerary/ evals/test_i4_*.py
.venv/bin/ruff check gateway/ evals/ 2>&1 | tail -2
cd ..
git diff --exit-code -- backend/evals/golden/ && echo "GOLDENS_OK"
git diff --exit-code -- contract/openapi.json && echo "CONTRACT_OK"
cmp AGENTS.md CLAUDE.md && echo "BRIEFS_IDENTICAL"
git status --short
git log --oneline -14
```

| Check | Required |
|---|---|
| Total tests | > 331, all passing |
| `test_i4_*` | all passing |
| I1 safety + determinism | still passing, **unedited** |
| mypy `--strict` | clean; report the count you measure |
| ruff on files you created | zero |
| ruff `gateway/ evals/` | ≤ 9 |
| **Money goldens** | **unchanged** |
| OpenAPI | unchanged |
| `AGENTS.md` ≡ `CLAUDE.md` | identical |
| `git status --short` | empty |

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "docs: close itinerary I4 composer and routing gate"
```

**Do not push. Do not open a PR.** Report.

---

## Final Response Requirements

1. Task 0 baseline, pasted.
2. Per task: pasted red phase, pasted green phase, test-count delta, commit sha.
3. **Task 6's `test_the_fixture_candidates_actually_compete` output** — proof the invariance test
   is not vacuous.
4. Whether OR-Tools beat or merely matched the baseline on each benchmark fixture, with numbers.
5. The `test_demo_output.py` before/after diff, if it changed.
6. Full Gate I4 output, raw.
7. `DEVIATIONS.md` rows added, quoted.
8. Anything incomplete, stated plainly.

---

## Self-Review Notes

Spec coverage: §7 inputs (Task 1), hard constraints (Task 4), soft objectives (Task 5), solver
behavior (Tasks 3, 7, 8), separate validator (Task 4) · §8 route-matrix contract (Tasks 1, 2), map
rendering deferred to I6, Valhalla explicitly out of scope (Global Constraint 3) · §12 partial
results (Task 8) · Gate I4 criteria: ordering invariance (Task 6), solver determinism (Task 7),
documented fallback (Task 8), route provenance (Task 10), benchmark without validity regression
(Task 10).

**Deferred to I5:** the `search_places` tool and the bounded discovery loop. I4 composes from
whatever candidates retrieval supplies; it does not let the model go looking.

**Deferred to I6:** MapLibre rendering, OpenAPI changes, any frontend work. I4 is backend-only —
which is why `contract/openapi.json` must not move.
