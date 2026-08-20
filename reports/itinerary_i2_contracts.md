# I2 Contracts Handoff Report

## Tasks Completed

### Task 1 — Field-level provenance identity
* Added `PlaceClaimIdentity` to `gateway/evidence/identity.py`.
* Created `gateway/places/identity.py` and `gateway/places/contracts.py`.
* Tests added in `evals/test_place_contracts.py`.

### Task 2 — Search, candidate, and partial-result contracts
* Added PlaceSearchRequest, PlaceCandidate, PartialPlaceResult in `contracts.py`.
* Added validation logic to prevent scope broadening in adapters.
* Defined `PlaceProviderAdapter` in `gateway/places/protocol.py`.

### Task 3 — Provider registry and activation-profile checks
* Implemented `ProviderRegistry` and `ProviderRegistryEntry` in `gateway/places/registry.py`.
* Filter logic guarantees deterministic ordering based on remaining quota, budget, and priority.
* Tests in `evals/test_place_registry.py` to ensure only enabled/allowed profiles are selected.

### Task 4 — SamplePlaceAdapter and sanitized fixtures
* Implemented `SamplePlaceAdapter` that reads synthetic data from JSON.
* Ensure deterministic behavior (byte-identical responses) with fixed timestamps.
* Tests in `evals/test_place_sample_adapter.py`.

### Task 5 — Evidence-graph integration for place claims
* Added logic in `gateway/places/evidence.py` to add `PlaceCandidate` claims as nodes (Claim) in the EvidenceGraph.
* Added `PLACE_CLAIM` to `ClaimKind` in `gateway/evidence/nodes.py`.
* Tests in `evals/test_place_evidence_integration.py` to ensure invariants and SQLite storage round-trips.

### Task 6 — Source/licence manifest, capability reporting, Gate I2
* Added `SourceLicenceManifest` and `get_provider_manifest` in `gateway/places/registry.py`.
* Added AST boundary test in `evals/test_place_boundary.py` to forbid network/MCP imports in `gateway/places`.
* Verified the gate output cleanly.

## Commits
```
165038c feat(gateway): add source/licence manifest and capability reporting
4923230 feat(gateway): attach place claims to the evidence graph
7df4788 feat(gateway): add SamplePlaceAdapter and sanitized fixtures
b59cb5b feat(gateway): add place provider registry and activation checks
8763370 feat(gateway): add place search and partial-result contracts
17296b9 feat(gateway): add place identity and claim provenance contracts
```

## Test Count
Before: 232 tests
After: 258 tests

## Confirmations
- No new dependencies were added.
- No new credentials were added.
- No env changes were made.
- No network access is used by the adapter.

## Exact Gate I2 Output

```bash
$ cd backend
$ .venv/bin/pytest -q
........................................................................ [ 27%]
........................................................................ [ 55%]
........................................................................ [ 83%]
..........................................                               [100%]
=============================== warnings summary ===============================
.venv/lib/python3.14/site-packages/fastapi/testclient.py:1
  /Users/himanshu_jain/TripPlanner/backend/.venv/lib/python3.14/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
258 passed, 1 warning in 1.95s

$ .venv/bin/pytest evals/test_place_*.py -q
......................                                                   [100%]
22 passed in 0.12s

$ .venv/bin/mypy --strict core/ agents/ api/ gateway/
Success: no issues found in 54 source files

$ .venv/bin/ruff check gateway/places/ evals/test_place_*.py
All checks passed!

$ cd ..
$ git diff --exit-code -- backend/evals/golden/ && echo "GOLDENS UNCHANGED"
GOLDENS UNCHANGED

$ git diff --exit-code -- contract/openapi.json && echo "CONTRACT UNCHANGED"
CONTRACT UNCHANGED

$ git diff --check

$ cmp AGENTS.md CLAUDE.md && echo "BRIEFS IDENTICAL"
BRIEFS IDENTICAL

$ git status --short

$ git log --oneline HEAD~6..HEAD
165038c feat(gateway): add source/licence manifest and capability reporting
4923230 feat(gateway): attach place claims to the evidence graph
7df4788 feat(gateway): add SamplePlaceAdapter and sanitized fixtures
b59cb5b feat(gateway): add place provider registry and activation checks
8763370 feat(gateway): add place search and partial-result contracts
17296b9 feat(gateway): add place identity and claim provenance contracts
```
