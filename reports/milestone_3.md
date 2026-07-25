# Milestone 3 — Critic Evals, Provenance Rendering, and Report Gate

Date: 2026-07-25  
Branch: `feat/m3-evals-provenance`  
Scope: spec 04 only. No frontend, provider gateway, crawling, provider APIs, or MCP/provider configuration was added.

## Result

M3 is complete.

Implemented evaluation-only judge contracts, offline judge scripting, anchor/golden itinerary fixtures, aggregate scoring, Gate M3 assertions, generated `backend/evals/report.md`, and runtime report footer/disclaimer provenance coverage. The product runtime remains the fixed M2 Kernel MVP pipeline; evaluation code is not imported by `backend/agents/`, `backend/api/`, or `backend/core/`.

## Gate M3

Command:

```bash
make gate-m3 PY=.venv/bin/python
```

Result:

- M3 tests: 19 passed.
- Strict typing: 35 source files clean.
- `backend/evals/report.md` generated.
- Gate M3 status: PASS.

Report summary:

- Anchor ordering: `anchor_good > anchor_scattered > anchor_overpacked`.
- Golden itineraries: 8.
- Judge runs per golden itinerary: 3.
- Overall mean: 4.20.
- Groundedness mean: 5.00.
- Groundedness minimum: 5.
- Latency: p50 0 ms, p95 0 ms under the offline scripted judge.
- Token accounting: 5,508 prompt tokens, 648 completion tokens, 6,156 total offline-estimated tokens.

## Full regression verification

Fresh verification also passed:

- `make gate-m1 PY=.venv/bin/python`
  - Optimizer selection tests: 14 passed.
  - Determinism selection tests: 5 passed.
  - Strict core typing: 16 source files clean.
  - Canonical demo output: byte-identical.
  - Float audit: only known non-money confidence/geo/cache matches.
- `make gate-m1b PY=.venv/bin/python`
  - Transfer tests: 20 passed.
  - Strict core typing: 16 source files clean.
- `make gate-m2 PY=.venv/bin/python`
  - M2 tests: 38 passed.
  - Strict core/agents/api typing: 31 source files clean.
  - Known Starlette/httpx deprecation warning only.
- `make test PY=.venv/bin/python`
  - Full backend regression: 97 passed.
  - Known Starlette/httpx deprecation warning only.
- `cd backend && .venv/bin/python -m mypy --strict core/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py`
  - 35 source files clean.

## Implemented files

- `backend/evals/judge.py`
  - Strict judge score/verdict schemas.
  - Scripted offline judge client.
  - Hosted judge stub disabled without explicit credentials.
  - Prompt builder and one-repair completion path.
- `backend/evals/itinerary_fixtures.py`
  - Three anchor itineraries.
  - Eight golden itinerary cases across styles, paces, origins, budgets, and interests.
- `backend/evals/itinerary_eval.py`
  - Anchor ranking, repeated judge runs, aggregate metrics, latency/token summaries, and Gate M3 assertions.
- `backend/evals/report.py`
  - Deterministic offline report generator.
- `backend/evals/report.md`
  - Generated M3 evaluation report.
- `backend/agents/models.py`
  - Added deterministic `FinalReport.footer`.
- `backend/agents/explainer.py`
  - Emits the footer/disclaimer from computed provenance.
- `backend/evals/test_m3_*.py`
  - M3 judge, evaluation, report, footer, and runtime-boundary tests.
- `Makefile`
  - Added `test-m3`, `typecheck-m3`, and `gate-m3`.

## Runtime boundary checks

M3 keeps evaluation outside request-time runtime:

- `backend/agents/` does not import `evals.judge`.
- `backend/api/` does not import `evals.judge`.
- `backend/core/` does not import `evals.judge`.
- `POST /plan` remains the M2 fixed Kernel MVP path.

## Provenance rendering coverage

Runtime reports now include a deterministic footer:

```text
Computed from data last verified on <date>; informational, not financial advice; verify prices and offer terms before paying.
```

The footer uses computed artifacts rather than LLM-generated claims. Tests cover that the footer includes the minimum relevant last-verified date and the disclaimer language.

## Deviations

One M3 Tier-C decision was logged in `DEVIATIONS.md`:

- Offline scripted Gate M3 runs use deterministic whitespace-token estimates because hosted judge credentials are intentionally not required for normal gates.

## Next milestone

F1 is next: specs 10 and 11, frontend design tokens and primitives. Provider gateway, runtime travel MCPs, crawling, live APIs, and award/cash provider adapters remain out of scope until the documented later milestones authorize them.
