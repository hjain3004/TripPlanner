# Itinerary I0 Evidence Hardening Report

## Overview
This phase hardened the `EvidenceGraph` by transitioning from mutable records to an event-sourced log with strict identity modeling, reversible resolution, order-independent contradiction detection, and idempotent SQLite persistence.

## Commit List & Task Behavior
- `abed6ff fix(gateway): enforce zero spend and typed evidence time` (Tasks 1 & 2): Enforced USD 0 default budget and typed temporal bounds.
- `97c94de fix(gateway): enforce evidence edge contracts` (Task 1 & 2): Enforced edge directionality and type invariants.
- `d285bfb fix(gateway): require typed exact evidence identity` (Task 3): Typed exact identity and reversible `ResolutionRecord` implementation. 
- `fe1d850 fix(gateway): compare contradictions by evidence schema` (Task 4): Order-independent symmetric contradiction detection across kind-specific comparison fields.
- `6d2b85d fix(gateway): persist complete evidence graphs idempotently` (Task 5): Idempotent `SqliteEvidenceStore`, v2 schema migrations, and recursive lineage loading.
- `453e2b4 docs(i0): resolve task 6 and fix i0 lint` (Task 6): Documentation updates, deprecated test relocations, and fixing all I0 surface lint errors.
- `f5bdef7 test(gateway): close itinerary I0 evidence gate` (Task 7): Boundary AST tests, cross-repository document reconciliation, and final Gate I0 validations.

## Test Count
- **Before:** 161 passing tests
- **After:** 196 passing tests

## Persistence Migration Coverage
- Migrated from v1 to v2 schema cleanly within a single transaction using atomic operations.
- Legacy nodes correctly preserve fallback `r1` ownership where derivation from canonical linked lineage isn't possible.

## Security & Costs
- Confirmed USD 0 path defaults with explicit protections against unbudgeted external expenditures. 
- No new dependencies, network calls, or secret credentials were added. Zero-spend structural integrity is verified.

## Linting Metrics
- **Scoped Ruff Count (I0 Surface):** 0 errors (`All checks passed!`)
- **Full Ruff Count:** 31 errors (within the `< 41` historical threshold limit).

## Goldens
- **Golden-diff result:** `GOLDENS UNCHANGED`

## Deviations
- None.

## Next Phase
**Phase I2** — Place contracts, provider registry, `SamplePlaceAdapter`.

---

## Gate I0 Command Outputs

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

**Output:**
```
........................................................................ [ 36%]
........................................................................ [ 73%]
....................................................                     [100%]
=============================== warnings summary ===============================
../../../backend/.venv/lib/python3.14/site-packages/fastapi/testclient.py:1
  /Users/himanshu_jain/TripPlanner/backend/.venv/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
196 passed, 1 warning in 2.10s
........................................................................ [ 75%]
........................                                                 [100%]
96 passed in 0.18s
Success: no issues found in 43 source files
All checks passed!
Found 31 errors.
[*] 13 fixable with the `--fix` option.
GOLDENS UNCHANGED
CONTRACT UNCHANGED
BRIEFS IDENTICAL
f5bdef7 test(gateway): close itinerary I0 evidence gate
453e2b4 docs(i0): resolve task 6 and fix i0 lint
6d2b85d fix(gateway): persist complete evidence graphs idempotently
fe1d850 fix(gateway): compare contradictions by evidence schema
d285bfb fix(gateway): require typed exact evidence identity
97c94de fix(gateway): enforce evidence edge contracts
abed6ff fix(gateway): enforce zero spend and typed evidence time
```
