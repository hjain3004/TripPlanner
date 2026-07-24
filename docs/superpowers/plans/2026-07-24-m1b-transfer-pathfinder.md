# M1b Transfer Pathfinder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the deterministic points-transfer calculator required by spec 07, including exhaustive one/two-hop search, integer-only valuation, mandatory verify-before-transfer instructions, golden tests, and the M1b gate report.

**Architecture:** Transfer facts extend the existing typed knowledge base, while all search and arithmetic live under `backend/core/transfer/`. The module is pure code: it reads curated facts through `KnowledgeBase`, returns typed `TransferAdvice`, never calls an LLM or provider, and never executes a transfer. M2 will consume this public interface after M1b passes.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, PyYAML, pytest, mypy strict.

## Global Constraints

- All money uses integer minor units; percentages use integer basis points; point values use integer micro-major units.
- Destination units floor after each transfer hop; required source units round up to the edge increment.
- Search only acyclic paths of one or two edges.
- Golden expected values and the worked example in spec 07 win over conflicting prose formulas.
- The first checklist step is always verify availability before transfer.
- The module never executes transfers, bookings, payments, provider calls, or LLM calls.
- Every transfer edge, bonus, program, and award-chart fact carries `Provenance`.
- `backend/core/` imports nothing from `agents/`, `api/`, or the future provider gateway.
- Tests use fictional or recorded data and never access the network.

---

## File Map

- Modify `backend/core/models.py`: add transfer-domain input/output models and the recommendation enum.
- Modify `backend/core/db.py`: persist transfer fact rows and expose deterministic read methods.
- Create `backend/core/transfer/arithmetic.py`: integer transfer, inverse transfer, FX, and valuation primitives.
- Create `backend/core/transfer/pathfinder.py`: enumerate paths, build plans, rank, prune, and recommend.
- Create `backend/core/transfer/checklist.py`: deterministic irreversible-action checklist rendering.
- Modify `backend/core/transfer/__init__.py`: expose only `find_transfer_plans`.
- Create `backend/evals/transfer_harness.py`: load self-contained transfer golden fixtures.
- Create `backend/evals/test_transfer_pathfinder.py`: exact worked-example and edge-case assertions.
- Create `backend/evals/test_transfer_determinism.py`: byte-identical result gate.
- Create `backend/evals/golden/transfer_demo.yaml`: canonical spec-07 worked example.
- Create `backend/evals/golden/transfer_edge_cases.yaml`: required edge cases in a named case list.
- Create `backend/core/seeds/loyalty_programs.yaml`: fictional Kernel-MVP program rows.
- Create `backend/core/seeds/transfer_edges.yaml`: fictional Kernel-MVP transfer rows.
- Create `backend/core/seeds/transfer_bonuses.yaml`: fictional Kernel-MVP bonus rows.
- Create `backend/core/seeds/award_chart_entries.yaml`: fictional Kernel-MVP award rows.
- Modify `backend/pyproject.toml`: include the new seed files through the existing `seeds/*.yaml` rule; no dependency change.
- Modify `Makefile`: add `test-transfer` and `gate-m1b`.
- Create `reports/milestone_1.md`: record the already-passing M1 gate and reviewed float findings.
- Create `reports/milestone_1b.md`: record the M1b gate, test summary, and deviations.
- Modify `DEVIATIONS.md`: record the unit correction and conservative answers to underspecified M1b cases.

### Task 1: Close the M1 gate record

**Files:**

- Create: `reports/milestone_1.md`

**Interfaces:**

- Consumes: the existing M1 optimizer, golden fixtures, and spec 06 §5 gate.
- Produces: the milestone report required before M1b begins.

- [x] **Step 1: Run the exact M1 tests**

Run from `backend/`:

```bash
.venv/bin/python -m pytest evals/ -k optimizer -q
.venv/bin/python -m pytest evals/ -k determinism -q
.venv/bin/python -m mypy --strict core/
.venv/bin/python -m core.optimizer demo | diff -u evals/golden/demo_expected_output.txt -
grep -rn "float" core/optimizer core/models.py
```

Expected:

- optimizer: `12 passed`;
- determinism: `3 passed`;
- mypy: `Success: no issues found`;
- diff: no output and exit code 0;
- float findings are limited to confidence/geo annotations and documentation, not money arithmetic.

- [x] **Step 2: Create the milestone report**

Write `reports/milestone_1.md` with this structure and the observed command output:

```markdown
# Milestone 1 — deterministic rewards kernel

**Date:** 2026-07-24
**Status:** PASS

## Gate

- [x] Twelve optimizer golden cases pass.
- [x] Canonical demo output is byte-identical.
- [x] Two-run and all-golden determinism tests pass.
- [x] Property tests pass in the full suite.
- [x] `mypy --strict core/` is clean.
- [x] Float audit reviewed: only provenance confidence and geographic fields use floats; every money/points path remains integer-only.
- [x] Spec-01 Pydantic models and seeded SQLite facade are present.

## Test summary

- Python 3.14.6
- Optimizer golden selection: 12 passed
- Determinism selection: 3 passed
- Full pre-M1b suite: 20 passed
- Strict type check: 13 source files clean

## Deviations

See the M1 section of `DEVIATIONS.md`; no golden value was changed.
```

- [x] **Step 3: Re-run the full existing suite**

Run:

```bash
.venv/bin/python -m pytest evals/ -q
```

Expected: `20 passed`.

- [x] **Step 4: Commit the gate record**

```bash
git add reports/milestone_1.md
git commit -m "docs: record milestone 1 gate"
```

If the workspace is still not a Git repository, omit the commit command and record that fact in the M1 report; do not initialize Git implicitly.

### Task 2: Add transfer-domain contracts

**Files:**

- Modify: `backend/core/models.py`
- Test: `backend/evals/test_transfer_pathfinder.py`

**Interfaces:**

- Consumes: `Provenance`, `UserWallet`, and integer money conventions from `core.models`.
- Produces: `LoyaltyProgram`, `TransferEdge`, `TransferBonus`, `AwardChartEntry`, `AwardTarget`, `TransferStep`, `TransferPlan`, `InfeasiblePlan`, `Recommendation`, and `TransferAdvice`.

- [x] **Step 1: Write model validation tests**

Create `backend/evals/test_transfer_pathfinder.py` initially with:

```python
from datetime import date

import pytest
from pydantic import ValidationError

from core.models import (
    AwardTarget,
    LoyaltyProgram,
    Provenance,
    RecommendationKind,
    TransferEdge,
)

PROV = Provenance(
    source_type="manual_curation",
    last_verified=date(2026, 7, 24),
    verified_by="UNVERIFIED",
    needs_verification=True,
    confidence=1.0,
)


def test_transfer_edge_rejects_zero_ratio_and_increment() -> None:
    with pytest.raises(ValidationError):
        TransferEdge(
            id="bad",
            from_id="card",
            to_id="program",
            ratio_from=0,
            ratio_to=1,
            min_transfer=0,
            increment=0,
            transfer_time_hours_typical=0,
            transfer_time_hours_max=0,
            provenance=PROV,
        )


def test_award_target_defaults_to_home_currency() -> None:
    target = AwardTarget(
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        travelers=2,
    )
    assert target.home_currency == "INR"
    assert RecommendationKind.NO_DATA.value == "NO_DATA"
```

- [x] **Step 2: Run the tests and verify failure**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -q
```

Expected: collection fails because the transfer models do not exist.

- [x] **Step 3: Add the transfer models**

Append the following model family to `backend/core/models.py`, using `Field(gt=0)` for ratios, increments, travelers, and award costs, and `Field(ge=0)` for balances, times, fees, and computed amounts:

```python
class LoyaltyProgram(BaseModel):
    id: str
    kind: Literal["airline", "hotel", "card_currency"]
    name: str
    alliance: str | None = None
    booking_url: str | None = None
    provenance: Provenance


class TransferEdge(BaseModel):
    id: str
    from_id: str
    to_id: str
    ratio_from: int = Field(gt=0)
    ratio_to: int = Field(gt=0)
    min_transfer: int = Field(ge=0)
    increment: int = Field(gt=0)
    transfer_time_hours_typical: int = Field(ge=0)
    transfer_time_hours_max: int = Field(ge=0)
    provenance: Provenance


class TransferBonus(BaseModel):
    id: str
    edge_id: str
    bonus_bp: int = Field(ge=0)
    valid_from: date
    valid_to: date
    provenance: Provenance


class AwardChartEntry(BaseModel):
    id: str
    program_id: str
    origin: str
    destination: str
    cabin: Literal["economy", "premium", "business", "first"]
    trip_type: Literal["one_way", "round_trip"]
    miles_cost: int = Field(gt=0)
    fees_minor: int = Field(ge=0)
    fees_currency: str
    operating_airline_hint: str | None = None
    availability_note: str | None = None
    provenance: Provenance


class AwardTarget(BaseModel):
    origin: str
    destination: str
    cabin: Literal["economy", "premium", "business", "first"]
    trip_type: Literal["one_way", "round_trip"]
    travelers: int = Field(gt=0)
    home_currency: str = "INR"


class RecommendationKind(str, Enum):
    REDEEM = "REDEEM"
    PAY_CASH = "PAY_CASH"
    NO_DATA = "NO_DATA"


class TransferStep(BaseModel):
    from_id: str
    to_id: str
    amount_source: int = Field(ge=0)
    amount_dest: int = Field(ge=0)
    bonus_applied: str | None = None
    transfer_time_hours_typical: int = Field(ge=0)
    transfer_time_hours_max: int = Field(ge=0)


class TransferPlan(BaseModel):
    id: str
    award: AwardChartEntry
    travelers: int = Field(gt=0)
    steps: list[TransferStep]
    points_consumed: int = Field(ge=0)
    source_currency: str
    existing_miles_used: int = Field(ge=0)
    leftover_miles: int = Field(ge=0)
    total_fees_minor: int = Field(ge=0)
    value_per_point_micro: int = Field(ge=0)
    effective_redemption_cost_minor: int = Field(ge=0)
    savings_vs_cash_minor: int
    dominated: bool = False
    checklist_steps: list[str] = Field(default_factory=list)
    provenance_flags: list[str] = Field(default_factory=list)
    explanation: list[str] = Field(default_factory=list)


class InfeasiblePlan(BaseModel):
    award_id: str
    best_path: list[str]
    shortfall_points: int = Field(gt=0)
    shortfall_currency: str
    note: str


class Recommendation(BaseModel):
    kind: RecommendationKind
    plan_id: str | None = None
    reason: str


class TransferAdvice(BaseModel):
    plans: list[TransferPlan]
    infeasible: list[InfeasiblePlan]
    recommendation: Recommendation
```

`home_currency` is the conservative schema extension needed to make spec-07 edge case 9 deterministic. Record it in `DEVIATIONS.md`; it changes no golden value.

- [x] **Step 4: Run model tests**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -q
.venv/bin/python -m mypy --strict core/models.py
```

Expected: both model tests pass; mypy is clean.

- [x] **Step 5: Commit the contracts**

```bash
git add backend/core/models.py backend/evals/test_transfer_pathfinder.py DEVIATIONS.md
git commit -m "feat: add transfer pathfinder contracts"
```

### Task 3: Extend the read-only knowledge base

**Files:**

- Modify: `backend/core/db.py`
- Test: `backend/evals/test_transfer_pathfinder.py`

**Interfaces:**

- Consumes: transfer-domain Pydantic models from Task 2.
- Produces: `programs()`, `program(id)`, `edges_from(ids)`, `bonuses_active(ids, on_date)`, and the typed award-entry query shown in Step 3.

- [x] **Step 1: Add a deterministic facade test**

Append:

```python
from core.db import KnowledgeBase
from core.models import AwardChartEntry, TransferBonus


def test_transfer_kb_queries_are_filtered_and_sorted() -> None:
    program = LoyaltyProgram(
        id="lionmiles",
        kind="airline",
        name="LionMiles",
        booking_url="https://example.test/lionmiles",
        provenance=PROV,
    )
    edge_b = TransferEdge(
        id="b",
        from_id="voyager",
        to_id="lionmiles",
        ratio_from=1,
        ratio_to=1,
        min_transfer=1000,
        increment=500,
        transfer_time_hours_typical=0,
        transfer_time_hours_max=24,
        provenance=PROV,
    )
    edge_a = edge_b.model_copy(update={"id": "a"})
    bonus = TransferBonus(
        id="bonus",
        edge_id="a",
        bonus_bp=2000,
        valid_from=date(2026, 7, 1),
        valid_to=date(2026, 7, 31),
        provenance=PROV,
    )
    award = AwardChartEntry(
        id="award",
        program_id="lionmiles",
        origin="DEL",
        destination="SIN",
        cabin="business",
        trip_type="round_trip",
        miles_cost=62000,
        fees_minor=900000,
        fees_currency="INR",
        provenance=PROV,
    )
    kb = KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        loyalty_programs=[program],
        transfer_edges=[edge_b, edge_a],
        transfer_bonuses=[bonus],
        award_chart_entries=[award],
    )
    assert [edge.id for edge in kb.edges_from(["voyager"])] == ["a", "b"]
    assert [row.id for row in kb.bonuses_active(["a"], date(2026, 7, 24))] == ["bonus"]
    assert [row.id for row in kb.award_entries(
        "DEL", "SIN", "business", "round_trip"
    )] == ["award"]
```

- [x] **Step 2: Run and verify the facade test fails**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py::test_transfer_kb_queries_are_filtered_and_sorted -q
```

Expected: failure because the constructor and query methods do not accept transfer facts.

- [x] **Step 3: Add storage rows and facade collections**

In `backend/core/db.py`:

- import the transfer model classes;
- add `LoyaltyProgramRow`, `TransferEdgeRow`, `TransferBonusRow`, and `AwardChartEntryRow`;
- add optional transfer collections to `KnowledgeBase.__init__` and `from_models`;
- store each collection sorted by id;
- implement the five query methods with exact-match filters and id sorting;
- load and seed `loyalty_programs.yaml`, `transfer_edges.yaml`, `transfer_bonuses.yaml`, and `award_chart_entries.yaml`;
- include those rows in `load_kb`.

Use these public signatures:

- `programs(self) -> list[LoyaltyProgram]`
- `program(self, program_id: str) -> LoyaltyProgram`
- `edges_from(self, currency_ids: list[str]) -> list[TransferEdge]`
- `bonuses_active(self, edge_ids: list[str], on_date: date) -> list[TransferBonus]`
- `award_entries(self, origin: str, destination: str, cabin: str, trip_type: str) -> list[AwardChartEntry]`

`bonuses_active` includes a row iff `valid_from <= on_date <= valid_to`. `award_entries` compares airport codes case-insensitively and returns rows sorted by id.

- [x] **Step 4: Run facade and existing regression tests**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -q
.venv/bin/python -m pytest evals/test_optimizer.py -q
.venv/bin/python -m mypy --strict core/
```

Expected: all tests pass; existing optimizer behavior is unchanged.

- [x] **Step 5: Commit KB support**

```bash
git add backend/core/db.py backend/evals/test_transfer_pathfinder.py
git commit -m "feat: add transfer facts to knowledge base"
```

### Task 4: Implement integer transfer arithmetic

**Files:**

- Create: `backend/core/transfer/arithmetic.py`
- Test: `backend/evals/test_transfer_pathfinder.py`

**Interfaces:**

- Consumes: `TransferEdge`, optional `TransferBonus`, and `FxRate`.
- Produces: exact forward and inverse transfer math used by the pathfinder.

- [x] **Step 1: Add arithmetic tests**

Append:

```python
from core.transfer.arithmetic import (
    convert_minor,
    destination_units,
    minimum_source_units,
    redemption_value_micro,
)


def test_transfer_math_floors_forward_and_rounds_source_up() -> None:
    edge = TransferEdge(
        id="e",
        from_id="card",
        to_id="air",
        ratio_from=3,
        ratio_to=1,
        min_transfer=1000,
        increment=500,
        transfer_time_hours_typical=0,
        transfer_time_hours_max=0,
        provenance=PROV,
    )
    assert destination_units(225000, edge, 2000) == 90000
    assert minimum_source_units(90000, edge, 2000) == 225000
    assert minimum_source_units(41234, edge, 0) == 124000


def test_redemption_value_uses_micro_major_units() -> None:
    assert redemption_value_micro(
        cash_price_minor=19000000,
        fees_minor=1800000,
        points=124000,
    ) == 1387096
```

- [x] **Step 2: Run and verify import failure**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -k "transfer_math or redemption_value" -q
```

Expected: import failure because `arithmetic.py` does not exist.

- [x] **Step 3: Implement the arithmetic primitives**

Create `backend/core/transfer/arithmetic.py` with these functions:

```python
from core.models import FxRate, TransferEdge

MICRO_MAJOR_PER_MINOR = 10_000
BASIS_POINTS = 10_000


def destination_units(source: int, edge: TransferEdge, bonus_bp: int = 0) -> int:
    return (
        source
        * edge.ratio_to
        * (BASIS_POINTS + bonus_bp)
        // edge.ratio_from
        // BASIS_POINTS
    )


def round_up_to_increment(value: int, increment: int) -> int:
    return ((value + increment - 1) // increment) * increment


def minimum_source_units(required_dest: int, edge: TransferEdge, bonus_bp: int = 0) -> int:
    if required_dest <= 0:
        return 0
    numerator = required_dest * edge.ratio_from * BASIS_POINTS
    denominator = edge.ratio_to * (BASIS_POINTS + bonus_bp)
    raw = (numerator + denominator - 1) // denominator
    source = round_up_to_increment(max(raw, edge.min_transfer), edge.increment)
    while destination_units(source, edge, bonus_bp) < required_dest:
        source += edge.increment
    return source


def redemption_value_micro(cash_price_minor: int, fees_minor: int, points: int) -> int:
    if points <= 0:
        return 0
    return max(0, cash_price_minor - fees_minor) * MICRO_MAJOR_PER_MINOR // points


def opportunity_cost_minor(points: int, value_micro_major_per_point: int) -> int:
    return points * value_micro_major_per_point // MICRO_MAJOR_PER_MINOR


def convert_minor(amount_minor: int, rate: FxRate) -> int:
    return amount_minor * rate.rate_micro // 1_000_000
```

The two `MICRO_MAJOR_PER_MINOR` conversions deliberately follow the worked example and existing `points_value_minor` helper. Spec 07's prose divisors/multipliers are dimensionally inconsistent; record the hand audit in `DEVIATIONS.md` and keep the worked expected value `1_387_096`.

- [x] **Step 4: Run arithmetic tests and strict typing**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -k "transfer_math or redemption_value" -q
.venv/bin/python -m mypy --strict core/transfer/arithmetic.py
```

Expected: all selected tests pass and mypy is clean.

- [x] **Step 5: Commit arithmetic**

```bash
git add backend/core/transfer/arithmetic.py backend/evals/test_transfer_pathfinder.py DEVIATIONS.md
git commit -m "feat: add integer transfer arithmetic"
```

### Task 5: Implement path enumeration, plan construction, and recommendations

**Files:**

- Create: `backend/core/transfer/pathfinder.py`
- Create: `backend/core/transfer/checklist.py`
- Modify: `backend/core/transfer/__init__.py`
- Test: `backend/evals/test_transfer_pathfinder.py`

**Interfaces:**

- Consumes: `AwardTarget`, `UserWallet`, `KnowledgeBase`, baseline valuations, cash price, and date.
- Produces: the typed `find_transfer_plans` interface shown in Step 4.

- [x] **Step 1: Add the worked-example test**

Add a `worked_example_kb()` helper containing the fictional programs, E1–E4, B1, and two award entries from spec 07 §7. Then add:

```python
from core.models import AwardTarget, RecommendationKind, UserWallet
from core.transfer import find_transfer_plans


def test_transfer_worked_example_recommends_lionmiles() -> None:
    advice = find_transfer_plans(
        target=AwardTarget(
            origin="DEL",
            destination="SIN",
            cabin="business",
            trip_type="round_trip",
            travelers=2,
        ),
        wallet=UserWallet(
            card_ids=["voyager-prime"],
            points_balances={"voyager-prime": 140000},
        ),
        kb=worked_example_kb(),
        baseline_valuations={"voyager-prime": 1000000},
        cash_price_minor=19000000,
        on_date=date(2026, 7, 24),
    )
    assert advice.recommendation.kind is RecommendationKind.REDEEM
    assert advice.recommendation.plan_id == "lion-award:E1"
    plan = advice.plans[0]
    assert plan.points_consumed == 124000
    assert plan.total_fees_minor == 1800000
    assert plan.value_per_point_micro == 1387096
    assert plan.effective_redemption_cost_minor == 14200000
    assert plan.savings_vs_cash_minor == 4800000
    assert plan.checklist_steps[0].startswith("VERIFY (blocking):")
    assert "Do NOT transfer" in plan.checklist_steps[0]
    sky = next(row for row in advice.infeasible if row.award_id == "sky-award")
    assert sky.shortfall_points == 85000
```

- [x] **Step 2: Run and verify public-interface failure**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py::test_transfer_worked_example_recommends_lionmiles -q
```

Expected: import failure because `find_transfer_plans` is not exported.

- [x] **Step 3: Implement deterministic checklists**

Create `backend/core/transfer/checklist.py` with:

```python
from core.models import LoyaltyProgram, TransferBonus, TransferPlan


def build_checklist(
    plan: TransferPlan,
    program: LoyaltyProgram,
    bonuses: dict[str, TransferBonus],
) -> list[str]:
    url = program.booking_url or "the loyalty program's official site"
    rows = [
        (
            "VERIFY (blocking): Confirm "
            f"{plan.award.cabin} award space for {plan.travelers} on "
            f"{plan.award.origin}→{plan.award.destination} for your selected dates at {url}. "
            "Do NOT transfer until you can see the seats. Transfers are irreversible."
        )
    ]
    if any(step.transfer_time_hours_max > 0 for step in plan.steps):
        rows.append(
            "Warning: award space can disappear during a non-instant transfer; "
            "prefer an instant path when the value gap is small."
        )
    for step in plan.steps:
        bonus = bonuses.get(step.bonus_applied or "")
        suffix = (
            f", includes bonus {bonus.id} expiring {bonus.valid_to.isoformat()}"
            if bonus is not None
            else ""
        )
        rows.append(
            f"Transfer {step.amount_source} {step.from_id} → "
            f"{step.amount_dest} {step.to_id} "
            f"(typically {step.transfer_time_hours_typical}h, "
            f"up to {step.transfer_time_hours_max}h{suffix})."
        )
    rows.append(
        f"Book on {program.name} for "
        f"{plan.award.miles_cost}×{plan.travelers} miles + "
        f"{plan.total_fees_minor} {plan.award.fees_currency} minor units in fees."
    )
    if plan.leftover_miles:
        rows.append(f"Leftover: {plan.leftover_miles} miles will remain in {program.name}.")
    rows.append(
        f"Chart last verified {plan.award.provenance.last_verified.isoformat()}; "
        "award availability is never guaranteed by this tool."
    )
    return rows
```

- [x] **Step 4: Implement pathfinder internals**

Create `backend/core/transfer/pathfinder.py` with `REDEEM_MARGIN_BP = 11_500` and these exact typed interfaces:

- `_paths(source_ids: list[str], target_id: str, edges: list[TransferEdge]) -> list[list[TransferEdge]]`
- `_active_bonus_by_edge(path: list[TransferEdge], bonuses: list[TransferBonus]) -> dict[str, TransferBonus]`
- `_required_source(need_dest: int, path: list[TransferEdge], bonuses: dict[str, TransferBonus]) -> int`
- `_forward_steps(source: int, path: list[TransferEdge], bonuses: dict[str, TransferBonus]) -> list[TransferStep]`
- `_mark_dominated(plans: list[TransferPlan]) -> list[TransferPlan]`
- `find_transfer_plans(target: AwardTarget, wallet: UserWallet, kb: KnowledgeBase, baseline_valuations: dict[str, int], cash_price_minor: int, on_date: date) -> TransferAdvice`

Implement the bodies with these exact rules:

1. `_paths` returns every acyclic one-edge and two-edge path from a wallet-balance key to the award program, sorted by the joined edge ids.
2. `_required_source` walks the path backward with `minimum_source_units`.
3. `_forward_steps` walks forward with `destination_units`, recording the active bonus id and each edge's timing.
4. Convert award fees to `target.home_currency` with the matching `FxRate`; if currencies differ and no rate exists, skip that award and add an infeasible row whose note states the missing FX pair.
5. Existing destination balance reduces required award miles before path search.
6. For each feasible path, calculate:

```python
total_fees = converted_fee_per_person * target.travelers
value_per_point = redemption_value_micro(cash_price_minor, total_fees, source_required)
opportunity_cost = opportunity_cost_minor(
    source_required,
    baseline_valuations[source_id],
)
effective_cost = total_fees + opportunity_cost
savings = cash_price_minor - effective_cost
```

7. A zero-transfer plan has no steps, `points_consumed=0`, `source_currency=award.program_id`, `value_per_point_micro=0`, fees-only effective cost, and can be recommended when savings are positive because it requires no irreversible card-to-program transfer.
8. Feasible plans sort by `(-savings, hop_count, typical_hours, id)`.
9. A plan is dominated only when another plan is at least as good on savings, hop count, and max transfer time and strictly better on one. Retain the best dominated two-hop plan with `dominated=True`; drop other dominated plans.
10. Recommend the first non-dominated plan when savings are positive and either it is zero-transfer or `value_per_point_micro * 10_000 >= baseline_value * REDEEM_MARGIN_BP`. Otherwise return `PAY_CASH` with both computed values in the reason.
11. No matching award rows returns `NO_DATA` with the exact reason `No transfer advice for this route; no award-chart evidence is available.`
12. Build checklists only after ranking and dominance marking so every returned plan is complete.

Export the public function from `backend/core/transfer/__init__.py`:

```python
from core.transfer.pathfinder import find_transfer_plans

__all__ = ["find_transfer_plans"]
```

- [x] **Step 5: Run the worked example**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py::test_transfer_worked_example_recommends_lionmiles -q
```

Expected: pass with the exact spec-07 values.

- [x] **Step 6: Commit pathfinding**

```bash
git add backend/core/transfer backend/evals/test_transfer_pathfinder.py
git commit -m "feat: implement deterministic transfer pathfinder"
```

### Task 6: Add all required golden and determinism cases

**Files:**

- Create: `backend/evals/transfer_harness.py`
- Create: `backend/evals/golden/transfer_demo.yaml`
- Create: `backend/evals/golden/transfer_edge_cases.yaml`
- Modify: `backend/evals/test_transfer_pathfinder.py`
- Create: `backend/evals/test_transfer_determinism.py`

**Interfaces:**

- Consumes: the public `find_transfer_plans` function only.
- Produces: exact regression coverage for spec 07 §§7–8 and the M1b determinism gate.

- [x] **Step 1: Create the fixture loader**

Implement `backend/evals/transfer_harness.py` with:

```python
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from core.db import KnowledgeBase
from core.models import (
    AwardChartEntry,
    AwardTarget,
    FxRate,
    LoyaltyProgram,
    Provenance,
    TransferBonus,
    TransferEdge,
    UserWallet,
)
from core.transfer import find_transfer_plans

GOLDEN_DIR = Path(__file__).parent / "golden"


def _prov(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("provenance") or {
        "source_type": "manual_curation",
        "last_verified": "2026-07-24",
        "verified_by": "UNVERIFIED",
        "needs_verification": True,
        "confidence": 1.0,
    }


def run_transfer_case(case: dict[str, Any]):
    def with_prov(row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "provenance": _prov(row)}

    kb = KnowledgeBase.from_models(
        cards=[],
        reward_rules=[],
        offers=[],
        point_valuations=[],
        fx_rates=[FxRate.model_validate(with_prov(row)) for row in case.get("fx_rates", [])],
        loyalty_programs=[
            LoyaltyProgram.model_validate(with_prov(row))
            for row in case.get("programs", [])
        ],
        transfer_edges=[
            TransferEdge.model_validate(with_prov(row))
            for row in case.get("edges", [])
        ],
        transfer_bonuses=[
            TransferBonus.model_validate(with_prov(row))
            for row in case.get("bonuses", [])
        ],
        award_chart_entries=[
            AwardChartEntry.model_validate(with_prov(row))
            for row in case.get("awards", [])
        ],
    )
    return find_transfer_plans(
        target=AwardTarget.model_validate(case["target"]),
        wallet=UserWallet.model_validate(case["wallet"]),
        kb=kb,
        baseline_valuations=case["baseline_valuations"],
        cash_price_minor=case["cash_price_minor"],
        on_date=date.fromisoformat(case["on_date"]),
    )
```

- [x] **Step 2: Create the canonical worked fixture**

Write `transfer_demo.yaml` from spec 07 §7 with:

- programs `lionmiles`, `skyorchid`, and `grandstay`;
- edges E1–E4 with the exact ratios/times/minimums/increments;
- active B1 at 2,000 bp on E2;
- LionMiles and SkyOrchid award rows;
- wallet balance `voyager-prime: 140000`;
- baseline `voyager-prime: 1000000`;
- cash price `19000000`;
- exact expected P1 and infeasible SkyOrchid values asserted in Task 5.

- [x] **Step 3: Create the named edge-case fixture list**

Write `transfer_edge_cases.yaml` with a top-level `cases` list and these exact names and expectations:

```yaml
cases:
  - name: increment_rounding
    expect: {points_consumed: 124000, leftover_miles: 300}
  - name: existing_destination_balance
    expect: {points_consumed: 119000, existing_miles_used: 5000}
  - name: bonus_inside_window
    expect: {points_consumed: 225000, bonus_applied: B1}
  - name: bonus_outside_window
    expect: {recommendation: PAY_CASH}
  - name: zero_transfer
    expect: {points_consumed: 0, first_checklist_prefix: "VERIFY (blocking):"}
  - name: minimum_transfer
    expect: {points_consumed: 1000, leftover_miles: 900}
  - name: margin_gate
    expect: {recommendation: PAY_CASH}
  - name: no_data
    expect: {recommendation: NO_DATA}
  - name: dominated_two_hop_retained
    expect: {dominated_two_hop_count: 1}
  - name: foreign_fee_conversion
    expect: {total_fees_minor: 2528000}
```

For each row, include full self-contained `programs`, `edges`, `bonuses`, `awards`, `target`, `wallet`, `baseline_valuations`, `cash_price_minor`, and `on_date`. For `foreign_fee_conversion`, use SGD 200.00 per traveler (`fees_minor=20000`), two travelers, and `SGD→INR rate_micro=63200000`, yielding INR 25,280.00 (`total_fees_minor=2528000`).

- [x] **Step 4: Parametrize exact edge assertions**

Add a parametrized test that loads each case, asserts the recommendation enum, and then asserts every expected plan field, bonus id, dominated count, or checklist prefix by key. Fail on unknown expectation keys so fixture typos cannot silently pass.

- [x] **Step 5: Add byte determinism**

Create `backend/evals/test_transfer_determinism.py`:

```python
from pathlib import Path

import yaml

from evals.transfer_harness import GOLDEN_DIR, run_transfer_case


def test_transfer_results_are_byte_identical() -> None:
    demo = yaml.safe_load((GOLDEN_DIR / "transfer_demo.yaml").read_text())
    first = run_transfer_case(demo).model_dump_json()
    second = run_transfer_case(demo).model_dump_json()
    assert first.encode() == second.encode()


def test_every_transfer_edge_case_is_byte_identical() -> None:
    payload = yaml.safe_load((GOLDEN_DIR / "transfer_edge_cases.yaml").read_text())
    for case in payload["cases"]:
        first = run_transfer_case(case).model_dump_json()
        second = run_transfer_case(case).model_dump_json()
        assert first == second, case["name"]
```

- [x] **Step 6: Run the complete M1b test set**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py evals/test_transfer_determinism.py -q
.venv/bin/python -m mypy --strict core/
```

Expected: every worked and edge case passes; mypy is clean.

- [x] **Step 7: Commit the golden suite**

```bash
git add backend/evals/transfer_harness.py backend/evals/test_transfer_pathfinder.py backend/evals/test_transfer_determinism.py backend/evals/golden/transfer_demo.yaml backend/evals/golden/transfer_edge_cases.yaml
git commit -m "test: add transfer pathfinder golden suite"
```

### Task 7: Add sample seeds and prove round-trip persistence

**Files:**

- Create: `backend/core/seeds/loyalty_programs.yaml`
- Create: `backend/core/seeds/transfer_edges.yaml`
- Create: `backend/core/seeds/transfer_bonuses.yaml`
- Create: `backend/core/seeds/award_chart_entries.yaml`
- Modify: `backend/evals/test_transfer_pathfinder.py`

**Interfaces:**

- Consumes: the fictional worked-example facts.
- Produces: a complete local sample KB usable by M2 without real provider credentials.

- [x] **Step 1: Add a seed round-trip test**

Use `tmp_path` to call `seed_database`, then `load_kb`, and assert:

```python
assert [row.id for row in kb.programs()] == ["grandstay", "lionmiles", "skyorchid"]
assert [row.id for row in kb.edges_from(["voyager-prime"])] == ["E1", "E2", "E3"]
assert kb.award_entries("DEL", "SIN", "business", "round_trip")
```

- [x] **Step 2: Run and verify the test fails**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -k seed_round_trip -q
```

Expected: failure because the new seed files do not exist.

- [x] **Step 3: Add fictional seed rows**

Copy the canonical worked-example facts into the four seed files. Every row uses:

```yaml
provenance:
  source_url:
  source_type: manual_curation
  last_verified: 2026-07-24
  verified_by: UNVERIFIED
  needs_verification: true
  confidence: 1.0
  notes: Fictional Kernel-MVP demonstration data; not a real transfer or award claim.
```

Do not insert real Indian card/program ratios without separate human verification.

- [x] **Step 4: Run seed and regression tests**

Run:

```bash
.venv/bin/python -m pytest evals/test_transfer_pathfinder.py -q
.venv/bin/python -m core.db seed
.venv/bin/python -m pytest evals/ -q
```

Expected: seed counts include all four transfer tables and the complete suite passes.

- [x] **Step 5: Commit sample data**

```bash
git add backend/core/seeds backend/evals/test_transfer_pathfinder.py
git commit -m "feat: seed fictional transfer demonstration data"
```

### Task 8: Add and pass Gate M1b

**Files:**

- Modify: `Makefile`
- Create: `reports/milestone_1b.md`
- Modify: `DEVIATIONS.md`

**Interfaces:**

- Consumes: all M1b code and tests.
- Produces: a reproducible gate and authorization to begin M2.

- [x] **Step 1: Add Make targets**

Add:

```make
test-transfer: ## Gate M1b: transfer pathfinder golden and edge tests
	cd $(BACKEND) && $(PY) -m pytest evals/test_transfer_pathfinder.py evals/test_transfer_determinism.py -q

gate-m1b: test-transfer typecheck ## Run the complete Gate M1b
	@echo "Gate M1b checks executed."
```

Add both names to `.PHONY`.

- [x] **Step 2: Run M1 and M1b together**

Run from the repository root with the existing venv interpreter:

```bash
make gate-m1 PY=.venv/bin/python
make gate-m1b PY=.venv/bin/python
cd backend && .venv/bin/python -m pytest evals/ -q
```

Expected:

- M1 remains green;
- all transfer golden/edge/determinism tests pass;
- strict mypy passes;
- the full suite has no regressions.

- [x] **Step 3: Review the transfer money-path float audit**

Run:

```bash
grep -rn "float" backend/core/transfer backend/core/models.py
```

Expected: no float arithmetic in `core/transfer`; any hits in `core/models.py` remain provenance confidence or geographic fields.

- [x] **Step 4: Write the M1b report**

Create `reports/milestone_1b.md` containing:

- PASS/FAIL for every spec-07 §7–§8 case;
- exact pytest and mypy counts;
- byte-determinism result;
- the unit audit showing why micro-major to minor divides by 10,000;
- confirmation that verify-before-transfer is checklist step 1;
- confirmation that no provider, MCP, LLM, booking, or transfer execution was added;
- links to every M1b deviation.

- [x] **Step 5: Commit the gate**

```bash
git add Makefile reports/milestone_1b.md DEVIATIONS.md
git commit -m "docs: pass milestone 1b gate"
```

## Self-Review

- Spec coverage: models, KB facade, one/two-hop enumeration, active bonuses, rounding, feasibility, valuation, ranking, margin, dominance, checklist, FX, all ten edge cases, determinism, seeds, and M1b reporting are assigned to tasks.
- Placeholder scan: implementation tasks contain concrete signatures, formulas, commands, expected outputs, and fixture values; no deferred implementation marker remains.
- Type consistency: all public names originate in `core.models` or `core.transfer`; `find_transfer_plans` matches spec 07 and its test harness; the KB methods use the same model names throughout.
- Phase boundary: no MCP, external API, runtime crawling, frontend, or M2 orchestration work is pulled into M1b.
