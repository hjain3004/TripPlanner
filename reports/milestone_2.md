# Milestone 2 - orchestration pipeline and FastAPI

**Date:** 2026-07-25
**Status:** PASS

## What shipped

- Fixed Kernel MVP pipeline in `backend/agents/pipeline.py`.
- Four LLM call sites only: intake, planner, critic, explainer.
- Deterministic retrieval over curated POIs/areas.
- Deterministic cost estimator from sample flights, sample hotels, POIs, FX, and configured per-diems.
- Deterministic optimizer and transfer-pathfinder integration.
- Planner referential validation, one repair attempt, and deterministic fallback itinerary.
- Critic fail-soft behavior and bounded replanning loop.
- Explainer groundedness gate for rupee amounts, with deterministic prose fallback.
- FinalReport assembly with totals, payment strategy rows, booking checklist, assumptions, confidence, and provenance warnings.
- JSON trace file per request with schema-valid `TraceEvent` rows and artifact hashes.
- FastAPI boundary at `backend/api/main.py`:
  - `GET /health`
  - `POST /plan`
- M2 Make targets:
  - `make test-m2 PY=.venv/bin/python`
  - `make typecheck-m2 PY=.venv/bin/python`
  - `make gate-m2 PY=.venv/bin/python`

## Gate M2

- [x] End-to-end demo trip via `POST /plan` completes under 60s.
- [x] `FinalReport` is schema-valid.
- [x] Planner referential-integrity tests are green.
- [x] Groundedness regex gate is implemented and covered by a hallucinated-amount rejection test.
- [x] Fail-soft paths are exercised by tests for intake, planner, critic, and explainer failures.
- [x] Intake fixture suite is green.
- [x] TraceEvents are written and schema-valid.
- [x] No provider, MCP, crawler, booking, payment, or transfer-execution path was added.
- [x] `backend/core/` still imports nothing from `agents/` or `api/`.

## Fresh verification output

`make gate-m2 PY=.venv/bin/python`

```text
cd backend && .venv/bin/python -m pytest evals/test_m2_*.py -q
......................................                                   [100%]

1 warning: Starlette TestClient warns that `httpx` support is deprecated in favor of `httpx2`.

38 passed, 1 warning in 0.92s
cd backend && .venv/bin/python -m mypy --strict core/ agents/ api/
Success: no issues found in 31 source files
Gate M2 checks executed.
```

Full backend regression:

```text
make test PY=.venv/bin/python
78 passed, 1 warning in 1.40s
```

Strict typing over all backend source packages:

```text
cd backend
.venv/bin/python -m mypy --strict core/ agents/ api/
Success: no issues found in 30 source files
```

After adding `agents/config.py`, the final Gate M2 strict check covered 31 files.

Explicit `POST /plan` demo check:

```text
{'status_code': 200, 'status': 'ok', 'has_report': True, 'elapsed_seconds': 0.007}
```

M1 regression gate:

```text
make gate-m1 PY=.venv/bin/python
Optimizer selection: 14 passed, 64 deselected
Determinism selection: 5 passed, 73 deselected
mypy --strict core/: Success: no issues found in 16 source files
Canonical demo diff: exit code 0
Gate M1 checks executed.
```

Float-audit findings from Gate M1:

- `min_confidence` and report/provenance `confidence` are non-money confidence fields.
- `lat`, `lon`, and `centrality_score` are non-money geo/ranking fields.
- Python cache matches appeared because `__pycache__` files existed.
- No money, points, valuation, percentage, fee, or FX arithmetic uses `float`.

M1b regression gate:

```text
make gate-m1b PY=.venv/bin/python
20 passed in 0.24s
mypy --strict core/: Success: no issues found in 16 source files
Gate M1b checks executed.
```

Optional lint:

```text
cd backend
.venv/bin/python -m ruff check core/ agents/ api/ evals/
```

This is not an M2 gate. It currently fails on a mix of pre-existing style rules and new-file style nits, including import ordering, Python 3.11+ modernization suggestions, line length, and FastAPI `Depends(...)` B008 warnings. I did not roll a broad lint/refactor pass into M2 because the backend behavioral gates and strict typing already passed, and unrelated Tier-F core style refactors should be separate from feature work.

## Fail-soft evidence

- Intake LLM exception returns HTTP-200-compatible `PlanResponse(status="needs_clarification")`.
- Intake unresolved fields short-circuit the pipeline before planner/critic/explainer.
- Planner LLM exception uses deterministic fallback itinerary and surfaces a caveat.
- Critic LLM exception is skipped with a caveat.
- Explainer LLM exception uses deterministic prose fallback.
- Hallucinated rupee amount in explainer output is rejected by the groundedness gate and replaced with deterministic prose.

## Trace evidence

The success-path trace writes a JSON file named `<trace_id>.json` containing events in this order:

```text
intake
retrieval
planner
estimator
optimizer
critic
explainer
```

Each event includes a trace ID, node name, timestamps, optional model marker, attributes, and a SHA-256 artifact hash.

## Deviations

See `DEVIATIONS.md` M2 rows:

- Hotel-area fallback by closest `centrality_score`.
- Per-diem constants in `backend/agents/config.yaml`.
- Fixture transfer advice uses the seeded business award target and `voyager-prime` baseline valuation.
- Trace storage as local JSON files.
- FastAPI wiring and local fixture DB seeding behavior.

## Known limitations

- M2 still uses sample/curated local data only. No live flights, hotels, award availability, provider gateway, MCP runtime provider, crawler, account linking, booking, payment, or point transfer execution was added.
- Hosted and local LLM implementations are stubs for runtime configuration; tests use `ScriptedLLMClient`.
- The transfer advice compares seeded award-chart fixtures and must be treated as demonstrative until future provider evidence exists.
- Provider/MCP work remains deferred until the post-F4 target-platform gateway phase unless the human explicitly changes build order.

## Next milestone

M3 is next: spec 04 critic/eval expansion, provenance rendering tests, report footer/disclaimer coverage, and `evals/report.md` generation.
