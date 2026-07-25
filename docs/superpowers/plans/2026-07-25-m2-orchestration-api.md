# M2 Orchestration API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build the governed M2 pipeline and `POST /plan` FastAPI endpoint from spec 03 without changing frozen M1/M1b kernel behavior.

**Architecture:** M2 adds a plain Python coordinator under `backend/agents/` with exactly four LLM call sites: intake, planner, critic, and explainer. Deterministic retrieval, estimation, optimizer/pathfinder integration, report assembly, groundedness validation, tracing, and API transport remain code-owned and typed. `backend/core/` remains pure and does not import `agents/` or `api/`.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLAlchemy 2, PyYAML, FastAPI, pytest, mypy strict, deterministic fake LLM client for tests.

## Global Constraints

- M2 has exactly four LLM call sites: intake, planner, critic, explainer.
- LLMs never compute money, points, rewards, fees, ratios, discounts, percentages, or transfer values.
- No LangGraph, CrewAI, AutoGen, ReAct, dynamic tool selection, dynamic MCP discovery, agent delegation, long-term memory, crawling, live travel data, booking, payment, or transfer execution.
- `backend/core/` imports nothing from `agents/` or `api/`.
- Normal tests never call a real LLM, network endpoint, provider, MCP server, or crawler.
- Every recoverable LLM failure returns a typed fail-soft response rather than HTTP 500.
- Optimizer/core exceptions map to HTTP 500 with a trace ID.
- Trace events must include node/name, timestamps, trace/request ID, optional model/tokens, deterministic artifact hash, and attributes.
- `docs/specs/` is read-only.

---

## File Map

- Create `backend/agents/models.py`: M2 Pydantic contracts (`TripSpec`, `DraftItinerary`, `CriticVerdict`, `FinalReport`, trace, API request/response).
- Create `backend/agents/llm.py`: provider-neutral `LLMClient`, deterministic `ScriptedLLMClient`, env-configured hosted/local stubs, schema-repair helper.
- Create `backend/agents/intake.py`: intake call site and catalog/card validation.
- Create `backend/agents/retrieval.py`: deterministic POI/area retrieval and prompt-safe rows.
- Create `backend/agents/planner.py`: planner call site, referential validation, repair retry, deterministic fallback itinerary.
- Create `backend/agents/estimator.py`: deterministic conversion from itinerary + samples into `CostedTrip`.
- Create `backend/agents/critic.py`: critic call site and bounded revision decision support.
- Create `backend/agents/report.py`: deterministic report/checklist/totals/provenance assembly.
- Create `backend/agents/explainer.py`: explainer call site and template fallback.
- Create `backend/agents/groundedness.py`: deterministic numeric groundedness validator.
- Create `backend/agents/trace.py`: trace event writer with deterministic artifact hashes.
- Create `backend/agents/pipeline.py`: fixed M2 coordinator.
- Create `backend/agents/config.yaml`: M2 node limits and per-diem constants.
- Create `backend/api/app.py`: FastAPI app factory and `POST /plan`.
- Modify `backend/pyproject.toml`: add FastAPI/test client dependencies and package data.
- Modify `Makefile`: add `test-m2`, `typecheck-m2`, `gate-m2`.
- Create focused tests under `backend/evals/test_m2_*.py`.
- Create `reports/milestone_2.md` and refresh `AGENTS.md`/`CLAUDE.md` after Gate M2.

## Task 1: Contracts and LLM Test Double

**Files:**
- Create: `backend/agents/__init__.py`
- Create: `backend/agents/models.py`
- Create: `backend/agents/llm.py`
- Test: `backend/evals/test_m2_models.py`
- Test: `backend/evals/test_m2_llm.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `TripSpec`, `DraftItinerary`, `CriticVerdict`, `FinalReport`, `PlanRequest`, `PlanResponse`, `TraceEvent`, and `ScriptedLLMClient.complete_json(...)`.
- Consumes: `core.models.UserWallet`, `OptimizationPrefs`, `CostedTrip`, `OptimizerResult`, `TransferAdvice`.

- [x] **Step 1: Add dependencies and write failing contract tests**

Write tests asserting: valid `TripSpec`, invalid traveler count, invalid 2-night range, invalid 8-night range, mutable list defaults are isolated, fake LLM invocation counts, schema failure then repair retry.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_models.py evals/test_m2_llm.py -q
```

Expected: import failures because `agents.models` and `agents.llm` do not exist.

- [x] **Step 2: Implement contracts and fake LLM**

Implement `agents.models` with strict Pydantic fields and validators. Implement `ScriptedLLMClient` with per-node scripted outcomes, exceptions, schema-invalid payloads, timeout marker, and invocation counts. Implement `complete_with_repair(client, node, system, user, schema, ...)` with one validation repair retry.

- [x] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_models.py evals/test_m2_llm.py -q
.venv/bin/python -m mypy --strict agents/models.py agents/llm.py
```

Expected: all focused tests pass and mypy is clean.

Commit:

```bash
git add backend/agents backend/evals/test_m2_models.py backend/evals/test_m2_llm.py backend/pyproject.toml
git commit -m "feat: add m2 contracts and llm test double"
```

## Task 2: Intake and Retrieval

**Files:**
- Create: `backend/agents/intake.py`
- Create: `backend/agents/retrieval.py`
- Test: `backend/evals/test_m2_intake.py`
- Test: `backend/evals/test_m2_retrieval.py`

**Interfaces:**
- Consumes: `ScriptedLLMClient`, `TripSpec`, `KnowledgeBase`.
- Produces: `run_intake(raw_request, kb, llm) -> IntakeResult` and `retrieve_candidates(spec, kb, limit=40) -> RetrievalContext`.

- [x] **Step 1: Write failing intake/retrieval tests**

Tests cover complete request, missing dates as unresolved clarification, ambiguous/unknown cards as unresolved, invalid traveler count, unsupported origin/destination as unresolved, city filtering, overlap ranking, cap, and stable repeatability.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_intake.py evals/test_m2_retrieval.py -q
```

Expected: import failures because intake and retrieval modules do not exist.

- [x] **Step 2: Implement intake and retrieval**

Intake validates cards against `kb.cards()` and preserves unresolved inputs. Retrieval uses only city-matching curated POIs, ranks by interest-tag overlap with stable tie-breakers, caps at 40, and returns compact POI/area rows.

- [x] **Step 3: Verify and commit**

Run focused tests plus M1/M1b regressions:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_intake.py evals/test_m2_retrieval.py -q
.venv/bin/python -m pytest evals/ -k "optimizer or transfer" -q
.venv/bin/python -m mypy --strict agents/
```

Commit:

```bash
git add backend/agents/intake.py backend/agents/retrieval.py backend/evals/test_m2_intake.py backend/evals/test_m2_retrieval.py
git commit -m "feat: add intake and deterministic retrieval"
```

## Task 3: Planner and Deterministic Fallback

**Files:**
- Create: `backend/agents/planner.py`
- Test: `backend/evals/test_m2_planner.py`

**Interfaces:**
- Consumes: `TripSpec`, `RetrievalContext`, `ScriptedLLMClient`.
- Produces: `run_planner(spec, retrieval, llm, revision_notes=None) -> PlannerResult`.

- [x] **Step 1: Write failing planner tests**

Tests cover schema-valid itinerary, unknown POI retry, unknown area retry, planner exception fallback, dates matching trip dates, no duplicate POIs in fallback, and fallback quality flag.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_planner.py -q
```

Expected: import failure for `agents.planner`.

- [x] **Step 2: Implement planner**

Call the planner LLM once, retry once on schema/referential failure, then fallback to deterministic area-clustered day packing. Validate all POI IDs and hotel area IDs against retrieved context.

- [x] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_planner.py -q
.venv/bin/python -m mypy --strict agents/
```

Commit:

```bash
git add backend/agents/planner.py backend/evals/test_m2_planner.py
git commit -m "feat: add governed itinerary planner"
```

## Task 4: Cost Estimator and Kernel Integration

**Files:**
- Create: `backend/agents/estimator.py`
- Test: `backend/evals/test_m2_estimator.py`
- Test: `backend/evals/test_m2_kernel_integration.py`

**Interfaces:**
- Produces: `estimate_costed_trip(spec, itinerary, retrieval, kb) -> EstimatorResult`; `run_optimizer_and_transfers(costed, spec, kb) -> KernelResult`.

- [x] **Step 1: Write failing estimator/integration tests**

Tests assert exact traveler/night multiplication, cheapest route flight, hotel area fallback, attraction FX conversion, per-diem assumptions, optimizer result present, transfer advice `REDEEM` when award evidence exists, `NO_DATA` when it does not, and verify-before-transfer remains checklist step 1.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_estimator.py evals/test_m2_kernel_integration.py -q
```

Expected: import failures for estimator/integration functions.

- [x] **Step 2: Implement estimator and integration**

Use only `KnowledgeBase`, `core.optimizer.optimize`, and `core.transfer.find_transfer_plans`. Convert non-home attraction/per-diem minor units with `kb.fx_rate`; choose deterministic assumptions from config constants; never call an LLM.

- [x] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_estimator.py evals/test_m2_kernel_integration.py -q
.venv/bin/python -m pytest evals/ -k "optimizer or transfer" -q
.venv/bin/python -m mypy --strict agents/
```

Commit:

```bash
git add backend/agents/estimator.py backend/evals/test_m2_estimator.py backend/evals/test_m2_kernel_integration.py backend/agents/config.yaml
git commit -m "feat: add deterministic estimator and kernel integration"
```

## Task 5: Critic Loop, Report Assembly, Explainer, Groundedness, and Trace

**Files:**
- Create: `backend/agents/critic.py`
- Create: `backend/agents/report.py`
- Create: `backend/agents/explainer.py`
- Create: `backend/agents/groundedness.py`
- Create: `backend/agents/trace.py`
- Test: `backend/evals/test_m2_critic_loop.py`
- Test: `backend/evals/test_m2_groundedness.py`
- Test: `backend/evals/test_m2_trace.py`

**Interfaces:**
- Produces: `run_critic(...)`, `assemble_report(...)`, `run_explainer(...)`, `validate_groundedness(...)`, `TraceRecorder`.

- [x] **Step 1: Write failing tests**

Tests cover critic pass/no revision, blocking issue revision, max two revisions, critic exception caveat, hallucinated amount rejection, miles/points allowlist support, explainer schema/exception/groundedness fallback, trace schema, deterministic artifact hashes, and no secret fields in trace.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_critic_loop.py evals/test_m2_groundedness.py evals/test_m2_trace.py -q
```

Expected: import failures for these modules.

- [x] **Step 2: Implement deterministic report/explainer/trace**

Assemble all money/checklist/provenance in code before explainer. Explainer may return prose only if schema-valid and grounded against structured artifacts. Trace writes JSONL into an ignored runtime directory and failures do not break the pipeline.

- [x] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_critic_loop.py evals/test_m2_groundedness.py evals/test_m2_trace.py -q
.venv/bin/python -m mypy --strict agents/
```

Commit:

```bash
git add backend/agents/critic.py backend/agents/report.py backend/agents/explainer.py backend/agents/groundedness.py backend/agents/trace.py backend/evals/test_m2_critic_loop.py backend/evals/test_m2_groundedness.py backend/evals/test_m2_trace.py
git commit -m "feat: add critic report explainer and tracing"
```

## Task 6: Pipeline Coordinator

**Files:**
- Create: `backend/agents/pipeline.py`
- Test: `backend/evals/test_m2_pipeline_failsoft.py`

**Interfaces:**
- Produces: `run_pipeline(request: PlanRequest, kb: KnowledgeBase, llm: LLMClient, trace_dir: Path | None = None) -> PlanResponse`.

- [x] **Step 1: Write failing pipeline tests**

Tests cover happy path, clarification state, each LLM node killed independently, planner fallback, critic caveat, explainer template fallback, deterministic repeated fake-client output, max two revisions, global timeout without waiting, and optimizer exception producing an error response with trace ID.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_pipeline_failsoft.py -q
```

Expected: import failure for `agents.pipeline`.

- [x] **Step 2: Implement coordinator**

Run the fixed graph in spec order. Do not add dynamic loops beyond two planner revisions. Return typed clarification responses for intake failures/unresolved input and typed error responses for deterministic-core exceptions.

- [x] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_pipeline_failsoft.py -q
.venv/bin/python -m mypy --strict agents/
```

Commit:

```bash
git add backend/agents/pipeline.py backend/evals/test_m2_pipeline_failsoft.py
git commit -m "feat: add fixed orchestration pipeline"
```

## Task 7: FastAPI Endpoint

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/app.py`
- Test: `backend/evals/test_m2_api.py`
- Modify: `backend/pyproject.toml`

**Interfaces:**
- Produces: `create_app(kb=None, llm=None, trace_dir=None) -> FastAPI` and module-level `app`.

- [x] **Step 1: Write failing API tests**

Tests cover POST `/plan` happy path, clarification HTTP 200, fail-soft LLM behavior HTTP 200, unexpected core failure HTTP 500 with trace ID, and route has no business arithmetic.

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_api.py -q
```

Expected: missing FastAPI/module failure before dependencies and API exist.

- [x] **Step 2: Implement API and install updated dependencies**

Add FastAPI and httpx/starlette-compatible test dependency in `pyproject.toml`, run install if needed, implement the thin app factory, and ensure tests inject fake KB/LLM.

- [x] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m2_api.py -q
.venv/bin/python -m mypy --strict agents/ api/
```

Commit:

```bash
git add backend/api backend/evals/test_m2_api.py backend/pyproject.toml
git commit -m "feat: expose m2 plan api"
```

## Task 8: Gate, Report, and Checkpoint

**Files:**
- Modify: `Makefile`
- Create: `reports/milestone_2.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `DEVIATIONS.md` only for material Tier-C choices.

**Interfaces:**
- Consumes: all M2 tests and gates.
- Produces: reproducible Gate M2 and persistent checkpoint for M3.

- [x] **Step 1: Add Make targets**

Add `test-m2`, `typecheck-m2`, and `gate-m2`. `gate-m2` runs the full M2 eval set and strict typing for `core/ agents/ api/`.

- [x] **Step 2: Run full final gates**

Run:

```bash
make gate-m1 PY=.venv/bin/python
make gate-m1b PY=.venv/bin/python
make gate-m2 PY=.venv/bin/python
cd backend
.venv/bin/python -m pytest evals/ -q
.venv/bin/python -m mypy --strict core/ agents/ api/
grep -rn "float" core/optimizer core/transfer core/models.py
```

Expected: all gates pass; full suite passes; type checking clean; float audit has no financial arithmetic matches.

- [x] **Step 3: Write docs and verify**

Create `reports/milestone_2.md` with exact command outputs, API elapsed time, fail-soft evidence, groundedness evidence, trace evidence, deviations, and limitations. Update `AGENTS.md` and `CLAUDE.md` current checkpoint to show M2 complete, M3 next, remote present, provider MCPs deferred.

Run:

```bash
git diff --check
cmp -s AGENTS.md CLAUDE.md
git status --short
```

- [x] **Step 4: Commit final gate docs**

```bash
git add Makefile reports/milestone_2.md AGENTS.md CLAUDE.md DEVIATIONS.md
git commit -m "docs: pass milestone 2 gate"
```

## Self-Review

- Spec coverage: tasks cover all four LLM call sites, typed artifacts, deterministic retrieval, planner validation/repair/fallback, deterministic estimator, optimizer/pathfinder integration, critic loop, deterministic report assembly, groundedness, tracing, fail-soft behavior, FastAPI endpoint, gates, and documentation.
- Placeholder scan: no task uses TBD/TODO/deferred wording; each task lists concrete files, commands, and expected failure/pass behavior.
- Type consistency: public names used in later tasks are defined in earlier task interface blocks.
- Phase boundary: no provider gateway, live inventory, crawling, frontend, ReAct, long-term memory, or MCP work is included.
