# Evidence Graph Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the storage-agnostic evidence graph core — typed nodes, edges, four binding invariants, deterministic reversible resolution, freshness/supersession, contradiction detection, and per-run budgets — as pure Python with no provider I/O.

**Architecture:** A new `backend/gateway/evidence/` package holding data structures and pure functions only. Every workflow will later emit `Claim` nodes into this graph and read canonical claims back; the orchestrator marshals typed values from it into the kernel. Nothing here performs network calls, and nothing here computes money. The SQLite store is the last task so every preceding task is tested against in-memory fixtures.

**Tech Stack:** Python 3.11+, Pydantic v2, pytest, SQLite (stdlib `sqlite3`). No new third-party dependencies.

**Status:** SHELF PLAN. Implementation begins only after the Kernel MVP and frontend pass their gates (`AGENTS.md` build order). Do not start this because it is written.

**Source spec:** `docs/superpowers/specs/2026-07-28-evidence-graph-orchestration-design.md`

## Global Constraints

- **No money math anywhere in this package.** No arithmetic on prices, points, fees, or discounts. This package moves and validates evidence; `backend/core/` computes. (`AGENTS.md` non-negotiable #1)
- **No network, filesystem discovery, or secret access.** Pure functions over typed values. (spec 09 §4)
- **No LLM calls.** The validator is deterministic by explicit decision (design §2).
- **`backend/core/` must never import this package.** Dependency points one way: gateway → core is forbidden; orchestration maps gateway output into kernel inputs. (`AGENTS.md` repo boundaries)
- **Reuse spec 16 names. Do not invent parallel ones.** `EvidenceMeta` (§3), `FlightQuote` / `HotelQuote` / `AwardQuote` / `FlightPriceObservation` (§5), freshness states (§8), identity rules (§10).
- **Money is integer minor units** everywhere it appears in a type signature. (Tier F)
- **A merge is never a delete.** Every superseded or resolved-away object stays addressable. (design §4 invariant 4)
- **Strict typing.** `mypy --strict` must pass on every file added here, matching the existing backend standard (35 source files currently clean).
- Behaviour changes and refactors are separate commits. (`AGENTS.md` anti-drift)

## File Structure

```
backend/gateway/__init__.py
backend/gateway/evidence/__init__.py
backend/gateway/evidence/nodes.py         # Claim, Source, Artifact, Run, Evaluation
backend/gateway/evidence/edges.py         # EdgeKind, Edge, EvidenceGraph
backend/gateway/evidence/invariants.py    # the four invariants
backend/gateway/evidence/freshness.py     # status transitions + supersession
backend/gateway/evidence/resolution.py    # spec 16 §10 identity rules, reversible
backend/gateway/evidence/contradiction.py # disagreement detection
backend/gateway/evidence/budget.py        # PlanBudget, PartialResult
backend/gateway/evidence/store.py         # SQLite-backed graph store

tests/gateway/evidence/conftest.py
tests/gateway/evidence/test_nodes.py
tests/gateway/evidence/test_invariants.py
tests/gateway/evidence/test_freshness.py
tests/gateway/evidence/test_resolution.py
tests/gateway/evidence/test_contradiction.py
tests/gateway/evidence/test_budget.py
tests/gateway/evidence/test_store.py
```

One responsibility per file. `nodes.py` and `edges.py` are data only; every other module is pure functions over them.

---

### Task 1: Amend spec 09 with the design

This is documentation, not code, and it comes first so the implementation has an authoritative
target. `docs/specs/` is read-only *during implementation* — this task is the deliberate
amendment that closes that window before implementation opens.

**Files:**
- Modify: `docs/specs/09_target_platform_architecture.md` — §4 (boundary rules), §5 (workflow contracts), §6 (orchestration policy), §12 (testing)
- Modify: `DEVIATIONS.md`

**Interfaces:**
- Consumes: nothing.
- Produces: the authoritative spec text every later task implements against.

- [ ] **Step 1: Add the evidence graph to §4 boundary rules**

Under the existing `### Data Gateway` block, append:

```markdown
### Evidence graph

- Lives under `backend/gateway/evidence/`.
- Holds `Claim`, `Source`, `Artifact`, `Run`, `Evaluation` nodes and
  `SUPPORTS`, `CONTRADICTS`, `SUPERSEDES`, `RESOLVED_TO`, `DERIVED_FROM`,
  `EVALUATED_BY` edges.
- Four binding invariants: every claim has a source or is marked inference;
  every artifact names an authoring run and version; every evaluation names a
  rubric; every superseded or resolved-away object remains addressable.
- Performs no money arithmetic and no network access.
- Workflows never call each other; they read and write this graph only.
```

- [ ] **Step 2: Add the validator split to §5**

Replace the sentence "`DomainResult` contains normalized evidence, warnings, trace references,
and a declared quality state." with:

```markdown
`DomainResult` contains normalized evidence, warnings, trace references, and a
declared quality state. **The declared state is an input to validation, never the
verdict.** A deterministic validator — separate from the producing workflow —
resolves the verify link, checks quote expiry against wall-clock, confirms price
completeness, and confirms currency/occupancy/room-rate/fare-condition alignment
before permitting any cross-source comparison. It emits
`Evaluation{rubric_id, verdict, reasons}`.
```

- [ ] **Step 3: Add the orchestrator boundary rule and area sequencing to §6**

Append to §6:

```markdown
**Boundary rule.** The orchestrator routes on evidence *status and quality*; it
never reads claim *values* to make a money decision. "Is this good enough to use"
is orchestration; "which is cheaper" is the kernel.

**Area sequencing.** Hotel search runs in the phase-1 fan-out against KB reference
areas ranked by interest overlap — deterministic, and never against a curated
itinerary. There is no cycle between the hotel and itinerary workflows.

Every run declares a `PlanBudget`: max provider calls, max concurrent fan-out,
wall-clock, tokens, retries, cost, and a **minimum evidence bar for finalization**.
On exhaustion the run returns `PartialResult{best_artifact, completed, unresolved,
stop_reason}` and the stop reason renders to the user. Partial failure is never
hidden behind fluent prose.
```

- [ ] **Step 4: Add the four test classes to §12**

```markdown
- Trajectory assertions: workflow sequence matches the state machine; skips are the
  specified skips; no workflow runs twice; budget respected.
- Invariant assertions: the four evidence-graph invariants hold on every finalized run.
- Structural aggregator test: `"provenance" not in DiscoveryCandidate.model_fields`,
  and no code path builds a KB row from any `DiscoveryCandidate` field other than
  `issuer_url_to_verify`.
- Groundedness as graph query: every currency figure in the report reaches a `Claim`
  via `DERIVED_FROM`.
```

- [ ] **Step 5: Log the amendment in DEVIATIONS.md**

Add one row: date `2026-07-28`, doc `09 §4/§5/§6/§12`, question "should the target platform
carry a typed evidence graph?", decision "yes — model adopted, backing store chosen in Task 8",
rationale "multi-provider contradiction and supersession are graph-shaped; retrofitting lineage
is expensive", files `docs/specs/09_target_platform_architecture.md`.

- [ ] **Step 6: Commit**

```bash
git add docs/specs/09_target_platform_architecture.md DEVIATIONS.md
git commit -m "docs: amend spec 09 with the evidence graph and orchestration boundaries"
```

---

### Task 2: Node types

**Files:**
- Create: `backend/gateway/__init__.py` (empty)
- Create: `backend/gateway/evidence/__init__.py` (empty)
- Create: `backend/gateway/evidence/nodes.py`
- Create: `tests/gateway/evidence/conftest.py`
- Test: `tests/gateway/evidence/test_nodes.py`

**Interfaces:**
- Consumes: nothing from earlier code tasks.
- Produces: `ClaimKind`, `FreshnessState`, `Source`, `Claim`, `Artifact`, `Run`, `Evaluation`, and the pytest fixtures `source_a` and `claim_a` used by every later test module.

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_nodes.py
import pytest
from pydantic import ValidationError

from backend.gateway.evidence.nodes import (
    Artifact, Claim, ClaimKind, Evaluation, FreshnessState,
)


def test_claim_requires_source_or_inference_flag() -> None:
    """A claim with neither a source nor is_inference is a malformed node."""
    with pytest.raises(ValidationError):
        Claim(
            claim_id="c1", run_id="r1", adapter_id="sample",
            kind=ClaimKind.CASH_QUOTE,
            payload={"total_minor": 2450000, "currency": "INR"},
            source_id=None, is_inference=False,
            status=FreshnessState.LIVE,
            confidence=0.9, needs_verification=False,
        )


def test_claim_accepts_inference_without_source() -> None:
    claim = Claim(
        claim_id="c2", run_id="r1", adapter_id="derived",
        kind=ClaimKind.REFERENCE_FACT,
        payload={"note": "per-diem assumption"},
        source_id=None, is_inference=True,
        status=FreshnessState.ESTIMATED,
        confidence=0.5, needs_verification=True,
    )
    assert claim.is_inference is True
    assert claim.source_id is None


def test_artifact_requires_run_and_version() -> None:
    with pytest.raises(ValidationError):
        Artifact(artifact_id="a1", kind="CostedTrip", run_id="", version=1,
                 derived_from=["c1"])


def test_evaluation_requires_rubric() -> None:
    with pytest.raises(ValidationError):
        Evaluation(evaluation_id="e1", subject_id="c1", rubric_id="",
                   verdict="accept", reasons=[])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_nodes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/nodes.py
"""Evidence graph node types.

Names follow spec 16 where spec 16 already defines them. Money is integer minor
units. Nothing in this module performs arithmetic on money.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ClaimKind(StrEnum):
    CASH_QUOTE = "cash_quote"
    PRICE_OBSERVATION = "price_observation"
    SANDBOX_FIXTURE = "sandbox_fixture"
    AWARD_AVAILABILITY = "award_availability"
    REFERENCE_FACT = "reference_fact"


class FreshnessState(StrEnum):
    """Spec 16 §8."""
    LIVE = "live"
    CACHED = "cached"
    ESTIMATED = "estimated"
    STALE = "stale"
    SUPERSEDED = "superseded"


class Source(BaseModel):
    source_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)   # ISO-8601
    source_url: str = Field(min_length=1)
    terms_ref: str | None = None


class Claim(BaseModel):
    claim_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    kind: ClaimKind
    payload: dict[str, Any]
    source_id: str | None
    is_inference: bool
    status: FreshnessState
    superseded_by: str | None = None
    contradicts: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    needs_verification: bool

    @model_validator(mode="after")
    def _source_or_inference(self) -> Claim:
        """Invariant 1: every claim has a source or is marked inference."""
        if self.source_id is None and not self.is_inference:
            raise ValueError("claim must have a source_id or is_inference=True")
        return self


class Artifact(BaseModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    run_id: str = Field(min_length=1)          # invariant 2
    version: int = Field(ge=1)                 # invariant 2
    derived_from: list[str] = Field(default_factory=list)


class Run(BaseModel):
    run_id: str = Field(min_length=1)
    started_at: str = Field(min_length=1)
    ended_at: str | None = None


class Evaluation(BaseModel):
    evaluation_id: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    rubric_id: str = Field(min_length=1)       # invariant 3
    verdict: str = Field(min_length=1)
    reasons: list[str] = Field(default_factory=list)
```

```python
# tests/gateway/evidence/conftest.py
import pytest

from backend.gateway.evidence.nodes import (
    Claim, ClaimKind, FreshnessState, Source,
)


@pytest.fixture
def source_a() -> Source:
    return Source(
        source_id="s-a", provider="adapter-a", adapter_id="adapter-a",
        retrieved_at="2026-10-12T10:00:00Z",
        source_url="https://example.test/a", terms_ref=None,
    )


@pytest.fixture
def claim_a(source_a: Source) -> Claim:
    return Claim(
        claim_id="c-a", run_id="r1", adapter_id="adapter-a",
        kind=ClaimKind.CASH_QUOTE,
        payload={
            "carrier": "AI", "flight_number": "AI2384",
            "depart_date": "2026-10-12", "cabin": "economy",
            "fare_conditions": "SAVER",
            "total_minor": 2450000, "currency": "INR",
            "expires_at": "2026-10-12T10:20:00Z",
        },
        source_id="s-a", is_inference=False,
        status=FreshnessState.LIVE, confidence=0.95, needs_verification=True,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_nodes.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Verify strict typing**

Run: `mypy --strict backend/gateway/`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/gateway/ tests/gateway/
git commit -m "feat(gateway): evidence graph node types"
```

---

### Task 3: Edges and the four invariants

**Files:**
- Create: `backend/gateway/evidence/edges.py`
- Create: `backend/gateway/evidence/invariants.py`
- Test: `tests/gateway/evidence/test_invariants.py`

**Interfaces:**
- Consumes: `Claim`, `Source`, `Artifact`, `Run`, `Evaluation` from Task 2.
- Produces: `EdgeKind`, `Edge(kind, src, dst)`, `EvidenceGraph` with `add_claim/add_source/add_artifact/add_run/add_evaluation/add_edge/has_node`, and `check_invariants(graph) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_invariants.py
from backend.gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from backend.gateway.evidence.invariants import check_invariants
from backend.gateway.evidence.nodes import (
    Artifact, Claim, Evaluation, FreshnessState, Source,
)


def test_clean_graph_has_no_violations(claim_a: Claim, source_a: Source) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a"))
    assert check_invariants(g) == []


def test_dangling_superseded_pointer_is_a_violation(
    claim_a: Claim, source_a: Source
) -> None:
    """Invariant 4: a superseded object must remain addressable."""
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a.model_copy(update={
        "status": FreshnessState.SUPERSEDED, "superseded_by": "c-missing",
    }))
    violations = check_invariants(g)
    assert any("c-missing" in v for v in violations)


def test_artifact_with_unknown_derived_from_is_a_violation(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_artifact(Artifact(artifact_id="a1", kind="CostedTrip", run_id="r1",
                            version=1, derived_from=["c-a", "c-nope"]))
    violations = check_invariants(g)
    assert any("c-nope" in v for v in violations)


def test_evaluation_of_unknown_subject_is_a_violation() -> None:
    g = EvidenceGraph()
    g.add_evaluation(Evaluation(evaluation_id="e1", subject_id="c-ghost",
                                rubric_id="freshness.v1", verdict="reject",
                                reasons=["expired"]))
    violations = check_invariants(g)
    assert any("c-ghost" in v for v in violations)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_invariants.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway.evidence.edges'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/edges.py
from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from backend.gateway.evidence.nodes import (
    Artifact, Claim, Evaluation, Run, Source,
)


class EdgeKind(StrEnum):
    SUPPORTS = "SUPPORTS"           # source -> claim
    CONTRADICTS = "CONTRADICTS"     # claim <-> claim
    SUPERSEDES = "SUPERSEDES"       # claim -> claim
    RESOLVED_TO = "RESOLVED_TO"     # claim -> canonical claim
    DERIVED_FROM = "DERIVED_FROM"   # artifact -> claims consumed
    EVALUATED_BY = "EVALUATED_BY"   # claim|artifact -> evaluation


class Edge(BaseModel):
    kind: EdgeKind
    src: str = Field(min_length=1)
    dst: str = Field(min_length=1)


class EvidenceGraph(BaseModel):
    """In-memory graph. Task 8 adds a SQLite-backed equivalent."""
    claims: dict[str, Claim] = Field(default_factory=dict)
    sources: dict[str, Source] = Field(default_factory=dict)
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    runs: dict[str, Run] = Field(default_factory=dict)
    evaluations: dict[str, Evaluation] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)

    def add_claim(self, claim: Claim) -> None:
        self.claims[claim.claim_id] = claim

    def add_source(self, source: Source) -> None:
        self.sources[source.source_id] = source

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts[artifact.artifact_id] = artifact

    def add_run(self, run: Run) -> None:
        self.runs[run.run_id] = run

    def add_evaluation(self, evaluation: Evaluation) -> None:
        self.evaluations[evaluation.evaluation_id] = evaluation

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def has_node(self, node_id: str) -> bool:
        return (
            node_id in self.claims
            or node_id in self.sources
            or node_id in self.artifacts
            or node_id in self.runs
            or node_id in self.evaluations
        )
```

```python
# backend/gateway/evidence/invariants.py
"""The four binding invariants (design §4).

1. Every claim has a source or is marked inference.   (field-level in Claim)
2. Every artifact names an authoring run and version. (field-level in Artifact)
3. Every evaluation names a rubric.                   (field-level in Evaluation)
4. Every superseded or resolved-away object remains addressable.

This module checks the graph-level parts. A violation of 1-3 here means a node
was built by a path that bypassed model validation, or a pointer dangles.
"""
from __future__ import annotations

from backend.gateway.evidence.edges import EvidenceGraph


def check_invariants(graph: EvidenceGraph) -> list[str]:
    """Return human-readable violations. Empty list means the graph is sound."""
    violations: list[str] = []

    for claim_id, claim in graph.claims.items():
        if claim.source_id is None and not claim.is_inference:
            violations.append(
                f"invariant 1: claim {claim_id} has no source and is not inference"
            )
        if claim.source_id is not None and claim.source_id not in graph.sources:
            violations.append(
                f"invariant 1: claim {claim_id} cites missing source {claim.source_id}"
            )
        if claim.superseded_by is not None and not graph.has_node(claim.superseded_by):
            violations.append(
                f"invariant 4: claim {claim_id} superseded by missing "
                f"node {claim.superseded_by}"
            )
        for other in claim.contradicts:
            if other not in graph.claims:
                violations.append(
                    f"invariant 4: claim {claim_id} contradicts missing claim {other}"
                )

    for artifact_id, artifact in graph.artifacts.items():
        for claim_id in artifact.derived_from:
            if claim_id not in graph.claims:
                violations.append(
                    f"invariant 4: artifact {artifact_id} derived from missing "
                    f"claim {claim_id}"
                )

    for evaluation_id, evaluation in graph.evaluations.items():
        if not graph.has_node(evaluation.subject_id):
            violations.append(
                f"invariant 4: evaluation {evaluation_id} judges missing "
                f"subject {evaluation.subject_id}"
            )

    for edge in graph.edges:
        if not graph.has_node(edge.src):
            violations.append(f"edge {edge.kind} has missing src {edge.src}")
        if not graph.has_node(edge.dst):
            violations.append(f"edge {edge.kind} has missing dst {edge.dst}")

    return violations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_invariants.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add backend/gateway/evidence/edges.py backend/gateway/evidence/invariants.py tests/gateway/evidence/test_invariants.py
git commit -m "feat(gateway): evidence graph edges and invariant checks"
```

---

### Task 4: Freshness and supersession

**Files:**
- Create: `backend/gateway/evidence/freshness.py`
- Test: `tests/gateway/evidence/test_freshness.py`

**Interfaces:**
- Consumes: `Claim`, `FreshnessState` (Task 2); `EvidenceGraph`, `Edge`, `EdgeKind` (Task 3).
- Produces: `is_expired(claim, now) -> bool`, `mark_stale(graph, claim_id, now) -> None`, `supersede(graph, old_id, new_claim) -> None`.

Implements spec 16 §8. A superseded claim is never removed — it changes status and gains a
pointer, and a `SUPERSEDES` edge records the replacement.

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_freshness.py
from backend.gateway.evidence.edges import EdgeKind, EvidenceGraph
from backend.gateway.evidence.freshness import is_expired, mark_stale, supersede
from backend.gateway.evidence.nodes import Claim, FreshnessState, Source


def test_claim_expires_after_its_expiry_timestamp(claim_a: Claim) -> None:
    assert is_expired(claim_a, now="2026-10-12T10:19:00Z") is False
    assert is_expired(claim_a, now="2026-10-12T10:21:00Z") is True


def test_claim_without_expiry_never_expires(claim_a: Claim) -> None:
    no_expiry = claim_a.model_copy(update={"payload": {"total_minor": 1}})
    assert is_expired(no_expiry, now="2099-01-01T00:00:00Z") is False


def test_mark_stale_changes_status_but_keeps_the_claim(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    mark_stale(g, "c-a", now="2026-10-12T10:21:00Z")
    assert g.claims["c-a"].status is FreshnessState.STALE
    assert "c-a" in g.claims          # never deleted


def test_supersede_keeps_the_old_claim_addressable(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    replacement = claim_a.model_copy(update={
        "claim_id": "c-a2",
        "payload": {**claim_a.payload, "total_minor": 2510000},
    })
    supersede(g, old_id="c-a", new_claim=replacement)

    assert g.claims["c-a"].status is FreshnessState.SUPERSEDED
    assert g.claims["c-a"].superseded_by == "c-a2"
    assert g.claims["c-a2"].status is FreshnessState.LIVE
    assert any(
        e.kind is EdgeKind.SUPERSEDES and e.src == "c-a2" and e.dst == "c-a"
        for e in g.edges
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_freshness.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway.evidence.freshness'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/freshness.py
"""Freshness transitions and supersession. Implements spec 16 §8.

A superseded claim is never deleted (design §4 invariant 4).
"""
from __future__ import annotations

from datetime import datetime

from backend.gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from backend.gateway.evidence.nodes import Claim, FreshnessState


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def is_expired(claim: Claim, now: str) -> bool:
    """True when the claim carries an expiry that has passed."""
    expires_at = claim.payload.get("expires_at")
    if not isinstance(expires_at, str):
        return False
    return _parse(now) > _parse(expires_at)


def mark_stale(graph: EvidenceGraph, claim_id: str, now: str) -> None:
    """Transition an expired live claim to stale. Idempotent; never deletes."""
    claim = graph.claims[claim_id]
    if is_expired(claim, now) and claim.status is FreshnessState.LIVE:
        graph.claims[claim_id] = claim.model_copy(
            update={"status": FreshnessState.STALE}
        )


def supersede(graph: EvidenceGraph, old_id: str, new_claim: Claim) -> None:
    """Replace `old_id` with `new_claim`, keeping the old claim addressable."""
    old = graph.claims[old_id]
    graph.claims[old_id] = old.model_copy(update={
        "status": FreshnessState.SUPERSEDED,
        "superseded_by": new_claim.claim_id,
    })
    graph.add_claim(new_claim)
    graph.add_edge(
        Edge(kind=EdgeKind.SUPERSEDES, src=new_claim.claim_id, dst=old_id)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_freshness.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add backend/gateway/evidence/freshness.py tests/gateway/evidence/test_freshness.py
git commit -m "feat(gateway): freshness transitions and supersession"
```

---

### Task 5: Deterministic reversible resolution

**Files:**
- Create: `backend/gateway/evidence/resolution.py`
- Test: `tests/gateway/evidence/test_resolution.py`

**Interfaces:**
- Consumes: `Claim` (Task 2); `EvidenceGraph`, `Edge`, `EdgeKind` (Task 3).
- Produces: `ResolutionRecord`, `flight_identity(claim) -> tuple[str, ...]`, `resolve(graph, claim_ids, rule, confidence=1.0, run_id="r1") -> ResolutionRecord`, `unresolve(graph, resolution_id) -> None`.

Identity keys come from **spec 16 §10**. Read that section before implementing; do not invent
matching rules. No LLM participates in resolution (design §2).

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_resolution.py
import pytest

from backend.gateway.evidence.edges import EdgeKind, EvidenceGraph
from backend.gateway.evidence.nodes import Claim, Source
from backend.gateway.evidence.resolution import (
    flight_identity, resolve, unresolve,
)


def test_flight_identity_ignores_price(claim_a: Claim) -> None:
    """Two quotes for the same flight differ in price but share identity."""
    dearer = claim_a.model_copy(update={
        "payload": {**claim_a.payload, "total_minor": 2610000}
    })
    assert flight_identity(claim_a) == flight_identity(dearer)


def test_flight_identity_separates_different_cabins(claim_a: Claim) -> None:
    business = claim_a.model_copy(update={
        "payload": {**claim_a.payload, "cabin": "business"}
    })
    assert flight_identity(claim_a) != flight_identity(business)


def test_resolve_keeps_members_addressable(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))

    record = resolve(g, ["c-a", "c-b"], rule="exact_itinerary_match")

    assert record.canonical_id in ("c-a", "c-b")
    assert set(record.members) == {"c-a", "c-b"}
    assert "c-a" in g.claims and "c-b" in g.claims      # never deleted
    assert any(e.kind is EdgeKind.RESOLVED_TO for e in g.edges)


def test_unresolve_reverses_a_merge_without_rebuilding(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-b"}))
    record = resolve(g, ["c-a", "c-b"], rule="exact_itinerary_match")

    unresolve(g, record.resolution_id)

    assert not any(e.kind is EdgeKind.RESOLVED_TO for e in g.edges)
    assert "c-a" in g.claims and "c-b" in g.claims


def test_resolve_rejects_fewer_than_two_members(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    with pytest.raises(ValueError):
        resolve(g, ["c-a"], rule="exact_itinerary_match")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_resolution.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway.evidence.resolution'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/resolution.py
"""Deterministic, reversible entity resolution.

Identity keys implement spec 16 §10. No LLM participates: a model deciding two
prices are "the same" is money reasoning by the back door (design §2).
A merge is never a delete (design §4 invariant 4).
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from backend.gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from backend.gateway.evidence.nodes import Claim

_RESOLUTION_PREFIX = "res:"
_MEMBER_SEPARATOR = "|"


class ResolutionRecord(BaseModel):
    resolution_id: str = Field(min_length=1)
    members: list[str]
    canonical_id: str = Field(min_length=1)
    rule: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    created_by_run: str = Field(min_length=1)

    @field_validator("members")
    @classmethod
    def _at_least_two(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("a resolution needs at least two members")
        return v


def flight_identity(claim: Claim) -> tuple[str, ...]:
    """Spec 16 §10 flight identity. Deliberately excludes price."""
    p = claim.payload
    return (
        str(p.get("carrier", "")),
        str(p.get("flight_number", "")),
        str(p.get("depart_date", "")),
        str(p.get("cabin", "")),
        str(p.get("fare_conditions", "")),
    )


def resolve(
    graph: EvidenceGraph,
    claim_ids: list[str],
    rule: str,
    confidence: float = 1.0,
    run_id: str = "r1",
) -> ResolutionRecord:
    """Merge claims into a canonical one. Members remain addressable."""
    if len(claim_ids) < 2:
        raise ValueError("a resolution needs at least two members")

    members = sorted(claim_ids)
    canonical_id = members[0]                    # deterministic choice
    record = ResolutionRecord(
        resolution_id=_RESOLUTION_PREFIX + _MEMBER_SEPARATOR.join(members),
        members=members,
        canonical_id=canonical_id,
        rule=rule,
        confidence=confidence,
        created_by_run=run_id,
    )
    for member in members:
        if member != canonical_id:
            graph.add_edge(
                Edge(kind=EdgeKind.RESOLVED_TO, src=member, dst=canonical_id)
            )
    return record


def unresolve(graph: EvidenceGraph, resolution_id: str) -> None:
    """Reverse a merge. Nothing is rebuilt because nothing was destroyed."""
    members = resolution_id.removeprefix(_RESOLUTION_PREFIX).split(_MEMBER_SEPARATOR)
    graph.edges = [
        e for e in graph.edges
        if not (e.kind is EdgeKind.RESOLVED_TO and e.src in members)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_resolution.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add backend/gateway/evidence/resolution.py tests/gateway/evidence/test_resolution.py
git commit -m "feat(gateway): deterministic reversible entity resolution"
```

---

### Task 6: Contradiction detection

**Files:**
- Create: `backend/gateway/evidence/contradiction.py`
- Test: `tests/gateway/evidence/test_contradiction.py`

**Interfaces:**
- Consumes: `ClaimKind` (Task 2); `EvidenceGraph`, `Edge`, `EdgeKind` (Task 3); `flight_identity` (Task 5).
- Produces: `CONTRADICTION_THRESHOLD_BPS: dict[ClaimKind, int]`, `detect_contradictions(graph, claim_ids) -> list[Edge]`.

Threshold is a named per-`kind` constant in basis points, never a literal at a call site
(design §11.2). Comparing two integer minor-unit prices against a threshold produces and stores
no monetary value — this is a comparison, not money math.

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_contradiction.py
from backend.gateway.evidence.contradiction import (
    CONTRADICTION_THRESHOLD_BPS, detect_contradictions,
)
from backend.gateway.evidence.edges import EdgeKind, EvidenceGraph
from backend.gateway.evidence.nodes import Claim, ClaimKind, Source


def test_same_flight_similar_price_is_not_a_contradiction(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)                                        # 2_450_000
    g.add_claim(claim_a.model_copy(update={
        "claim_id": "c-b",
        "payload": {**claim_a.payload, "total_minor": 2455000},  # +0.2%
    }))
    assert detect_contradictions(g, ["c-a", "c-b"]) == []


def test_same_flight_divergent_price_is_a_contradiction(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)                                        # 2_450_000
    g.add_claim(claim_a.model_copy(update={
        "claim_id": "c-b",
        "payload": {**claim_a.payload, "total_minor": 2610000},  # +6.5%
    }))
    edges = detect_contradictions(g, ["c-a", "c-b"])
    assert len(edges) == 1
    assert edges[0].kind is EdgeKind.CONTRADICTS


def test_different_flights_are_never_contradictions(
    claim_a: Claim, source_a: Source
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_claim(claim_a.model_copy(update={
        "claim_id": "c-b",
        "payload": {**claim_a.payload, "flight_number": "AI9999",
                    "total_minor": 9999000},
    }))
    assert detect_contradictions(g, ["c-a", "c-b"]) == []


def test_threshold_is_defined_per_kind() -> None:
    assert ClaimKind.CASH_QUOTE in CONTRADICTION_THRESHOLD_BPS
    assert CONTRADICTION_THRESHOLD_BPS[ClaimKind.CASH_QUOTE] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_contradiction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway.evidence.contradiction'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/contradiction.py
"""Detect disagreement between claims about the same real-world thing.

Thresholds are named per-kind constants in basis points (design §11.2).
Comparing two prices against a threshold produces no monetary value and stores
none; this is not money math.
"""
from __future__ import annotations

from backend.gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from backend.gateway.evidence.nodes import ClaimKind
from backend.gateway.evidence.resolution import flight_identity

CONTRADICTION_THRESHOLD_BPS: dict[ClaimKind, int] = {
    ClaimKind.CASH_QUOTE: 200,          # 2.00%
    ClaimKind.PRICE_OBSERVATION: 1000,  # 10.00% — observations are noisier
    ClaimKind.AWARD_AVAILABILITY: 0,    # any mileage difference is material
}


def detect_contradictions(
    graph: EvidenceGraph, claim_ids: list[str]
) -> list[Edge]:
    """Return CONTRADICTS edges for same-identity claims that disagree."""
    edges: list[Edge] = []
    ids = sorted(claim_ids)

    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1:]:
            left, right = graph.claims[left_id], graph.claims[right_id]
            if left.kind is not right.kind:
                continue
            threshold = CONTRADICTION_THRESHOLD_BPS.get(left.kind)
            if threshold is None:
                continue
            if flight_identity(left) != flight_identity(right):
                continue

            base = left.payload.get("total_minor")
            other = right.payload.get("total_minor")
            if not isinstance(base, int) or not isinstance(other, int) or base == 0:
                continue

            delta_bps = abs(other - base) * 10_000 // base
            if delta_bps > threshold:
                edges.append(
                    Edge(kind=EdgeKind.CONTRADICTS, src=left_id, dst=right_id)
                )
    return edges
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_contradiction.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add backend/gateway/evidence/contradiction.py tests/gateway/evidence/test_contradiction.py
git commit -m "feat(gateway): contradiction detection with per-kind thresholds"
```

---

### Task 7: PlanBudget and PartialResult

**Files:**
- Create: `backend/gateway/evidence/budget.py`
- Test: `tests/gateway/evidence/test_budget.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `PlanBudget`, `PartialResult`, `BudgetExhausted`, `BudgetLedger` with `record_provider_call()`, `record_retry()`, `can_finalize(evidence_count)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_budget.py
import pytest

from backend.gateway.evidence.budget import (
    BudgetExhausted, BudgetLedger, PartialResult, PlanBudget,
)


def _budget(**overrides: int) -> PlanBudget:
    base = dict(max_provider_calls=2, max_fan_out=2, max_wall_clock_s=30,
                max_retries=1, min_evidence_for_finalization=1)
    base.update(overrides)
    return PlanBudget(**base)


def test_ledger_allows_calls_within_budget() -> None:
    ledger = BudgetLedger(_budget(max_provider_calls=2))
    ledger.record_provider_call()
    ledger.record_provider_call()
    assert ledger.provider_calls == 2


def test_ledger_raises_when_provider_calls_exhausted() -> None:
    ledger = BudgetLedger(_budget(max_provider_calls=1))
    ledger.record_provider_call()
    with pytest.raises(BudgetExhausted) as exc:
        ledger.record_provider_call()
    assert "max_provider_calls" in str(exc.value)


def test_cannot_finalize_below_minimum_evidence_bar() -> None:
    ledger = BudgetLedger(_budget(min_evidence_for_finalization=3))
    assert ledger.can_finalize(evidence_count=2) is False
    assert ledger.can_finalize(evidence_count=3) is True


def test_partial_result_requires_a_stop_reason() -> None:
    with pytest.raises(ValueError):
        PartialResult(best_artifact_id=None, completed=[],
                      unresolved=["flights"], stop_reason="")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway.evidence.budget'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/budget.py
"""Per-run budgets. Exhaustion returns a PartialResult with an explicit reason —
partial failure is never hidden behind fluent prose (design §6).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class BudgetExhausted(RuntimeError):
    """Raised when a declared cap is hit."""


class PlanBudget(BaseModel):
    max_provider_calls: int = Field(ge=1)
    max_fan_out: int = Field(ge=1)
    max_wall_clock_s: int = Field(ge=1)
    max_retries: int = Field(ge=0)
    min_evidence_for_finalization: int = Field(ge=1)
    max_tokens: int | None = None
    max_cost_minor: int | None = None


class PartialResult(BaseModel):
    best_artifact_id: str | None
    completed: list[str] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)
    stop_reason: str = Field(min_length=1)


class BudgetLedger:
    """Mutable counter guarding a PlanBudget."""

    def __init__(self, budget: PlanBudget) -> None:
        self.budget = budget
        self.provider_calls = 0
        self.retries = 0

    def record_provider_call(self) -> None:
        if self.provider_calls + 1 > self.budget.max_provider_calls:
            raise BudgetExhausted(
                f"max_provider_calls={self.budget.max_provider_calls} exhausted"
            )
        self.provider_calls += 1

    def record_retry(self) -> None:
        if self.retries + 1 > self.budget.max_retries:
            raise BudgetExhausted(f"max_retries={self.budget.max_retries} exhausted")
        self.retries += 1

    def can_finalize(self, evidence_count: int) -> bool:
        return evidence_count >= self.budget.min_evidence_for_finalization
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_budget.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add backend/gateway/evidence/budget.py tests/gateway/evidence/test_budget.py
git commit -m "feat(gateway): plan budget ledger and partial results"
```

---

### Task 8: SQLite-backed graph store

**Files:**
- Create: `backend/gateway/evidence/store.py`
- Test: `tests/gateway/evidence/test_store.py`

**Interfaces:**
- Consumes: `Claim`, `Source` (Task 2); `Edge`, `EdgeKind`, `EvidenceGraph` (Task 3); `check_invariants` (Task 3).
- Produces: `SqliteEvidenceStore(path)` with `save(graph) -> None` and `load(run_id) -> EvidenceGraph`.

Resolves design §11.1 in favour of SQLite edge tables — no new dependency, cross-run lineage
survives (an in-memory NetworkX graph would lose it), and spec 09 §7's store count does not grow
because this lives alongside the existing relational storage.

- [ ] **Step 1: Write the failing test**

```python
# tests/gateway/evidence/test_store.py
from pathlib import Path

from backend.gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from backend.gateway.evidence.invariants import check_invariants
from backend.gateway.evidence.nodes import Claim, FreshnessState, Source
from backend.gateway.evidence.store import SqliteEvidenceStore


def test_round_trip_preserves_claims_and_edges(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a)
    g.add_edge(Edge(kind=EdgeKind.SUPPORTS, src="s-a", dst="c-a"))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)
    loaded = store.load(run_id="r1")

    assert loaded.claims["c-a"].payload["total_minor"] == 2450000
    assert loaded.sources["s-a"].provider == "adapter-a"
    assert any(e.kind is EdgeKind.SUPPORTS for e in loaded.edges)
    assert check_invariants(loaded) == []


def test_superseded_claims_survive_a_round_trip(
    claim_a: Claim, source_a: Source, tmp_path: Path
) -> None:
    """Invariant 4 must hold across persistence, not only in memory."""
    g = EvidenceGraph()
    g.add_source(source_a)
    g.add_claim(claim_a.model_copy(update={
        "status": FreshnessState.SUPERSEDED, "superseded_by": "c-a2",
    }))
    g.add_claim(claim_a.model_copy(update={"claim_id": "c-a2"}))

    store = SqliteEvidenceStore(tmp_path / "evidence.db")
    store.save(g)
    loaded = store.load(run_id="r1")

    assert loaded.claims["c-a"].status is FreshnessState.SUPERSEDED
    assert loaded.claims["c-a"].superseded_by == "c-a2"
    assert check_invariants(loaded) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/gateway/evidence/test_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.gateway.evidence.store'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/gateway/evidence/store.py
"""SQLite-backed evidence graph persistence.

Design §11.1 resolved in favour of edge tables in the existing relational store:
no new dependency, and cross-run lineage survives.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.gateway.evidence.edges import Edge, EdgeKind, EvidenceGraph
from backend.gateway.evidence.nodes import Claim, Source

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    run_id    TEXT NOT NULL,
    body      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id TEXT PRIMARY KEY,
    run_id   TEXT NOT NULL,
    body     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edges (
    kind   TEXT NOT NULL,
    src    TEXT NOT NULL,
    dst    TEXT NOT NULL,
    run_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_run ON claims(run_id);
CREATE INDEX IF NOT EXISTS idx_edges_run  ON edges(run_id);
"""


class SqliteEvidenceStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        with sqlite3.connect(self.path) as conn:
            conn.executescript(_SCHEMA)

    def _run_id_for(self, graph: EvidenceGraph, node_id: str) -> str:
        claim = graph.claims.get(node_id)
        if claim is not None:
            return claim.run_id
        for candidate in graph.claims.values():
            if candidate.source_id == node_id:
                return candidate.run_id
        return "r1"

    def save(self, graph: EvidenceGraph) -> None:
        with sqlite3.connect(self.path) as conn:
            for source in graph.sources.values():
                conn.execute(
                    "INSERT OR REPLACE INTO sources VALUES (?,?,?)",
                    (source.source_id,
                     self._run_id_for(graph, source.source_id),
                     source.model_dump_json()),
                )
            for claim in graph.claims.values():
                conn.execute(
                    "INSERT OR REPLACE INTO claims VALUES (?,?,?)",
                    (claim.claim_id, claim.run_id, claim.model_dump_json()),
                )
            for edge in graph.edges:
                conn.execute(
                    "INSERT INTO edges VALUES (?,?,?,?)",
                    (edge.kind.value, edge.src, edge.dst,
                     self._run_id_for(graph, edge.dst)),
                )

    def load(self, run_id: str) -> EvidenceGraph:
        graph = EvidenceGraph()
        with sqlite3.connect(self.path) as conn:
            for (body,) in conn.execute(
                "SELECT body FROM sources WHERE run_id = ?", (run_id,)
            ):
                graph.add_source(Source.model_validate_json(body))
            for (body,) in conn.execute(
                "SELECT body FROM claims WHERE run_id = ?", (run_id,)
            ):
                graph.add_claim(Claim.model_validate_json(body))
            for kind, src, dst in conn.execute(
                "SELECT kind, src, dst FROM edges WHERE run_id = ?", (run_id,)
            ):
                graph.add_edge(Edge(kind=EdgeKind(kind), src=src, dst=dst))
        return graph
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/gateway/evidence/test_store.py -v`
Expected: PASS, 2 tests

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && pytest`
Expected: ≥ 100 passing (the existing floor) plus the 27 added here. No existing test changes.

- [ ] **Step 6: Verify strict typing across the package**

Run: `mypy --strict backend/gateway/`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add backend/gateway/evidence/store.py tests/gateway/evidence/test_store.py
git commit -m "feat(gateway): sqlite-backed evidence graph store"
```

---

## Out of scope for this plan

Deferred to a **second plan**, written once G1 lands the gateway skeleton
(`TravelProviderAdapter` implementations, provider registry, quote cache):

- The target orchestrator state machine and its explicit branches.
- The six domain workflows and the `DomainWorkflow` protocol.
- The deterministic validator's link-resolution and price-completeness checks — these need a real
  adapter and a real `EvidenceMeta` to act on.
- Phase-1 concurrent fan-out.
- Trajectory assertions over a real run.
- Groundedness-as-graph-query in the explainer.

Those depend on code that does not exist yet; planning them now would mean inventing interfaces.

## Self-review notes

- **Spec coverage:** design §4 (nodes/edges/invariants) → Tasks 2–3; §6 resolution and budget →
  Tasks 5 and 7; §8 contradiction and supersession → Tasks 4 and 6; §11.1 store → Task 8;
  §11.2 threshold → Task 6; spec 09 amendments → Task 1. Design §5 (aggregators) needs no code
  here — it is a spec 05 invariant, and its structural test is registered in Task 1 Step 4.
- **Naming corrected against spec 16:** the design doc's invented `NormalizedPayload` and
  `SourceRef` are replaced by spec 16's `EvidenceMeta` and concrete quote types; `status`
  implements spec 16 §8; resolution rules implement spec 16 §10. **Update the design doc's §4
  code block to match before executing this plan**, so the two documents do not disagree.
- **Type consistency:** `flight_identity` defined in Task 5, consumed in Task 6; `EvidenceGraph`
  defined in Task 3, consumed in Tasks 4–8; `ClaimKind`/`FreshnessState` defined in Task 2 and
  used throughout; `check_invariants` defined in Task 3, reused in Task 8's round-trip tests.
- **Known gap, deliberate:** `Artifact.run_id` is validated as non-empty but not checked against
  `graph.runs`, because runs are recorded lazily by the orchestrator, which this plan does not
  build. The second plan should tighten this once run lifecycle exists.
