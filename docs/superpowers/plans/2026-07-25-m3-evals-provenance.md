# M3 Evals and Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Milestone 3 evaluation infrastructure, provenance/disclaimer validation, and the generated evaluation report required by specs 04 and 06.

**Architecture:** M3 adds evaluation-only judge contracts, clients, fixtures, aggregation, metrics, and report generation under `backend/evals/`. Runtime code remains the fixed M2 pipeline with exactly four LLM call sites; the only runtime change is deterministic report footer/disclaimer and related provenance rendering fields in `FinalReport`. Evaluation code must never be imported by `backend/agents/`, `backend/api/`, or `backend/core/`.

**Tech Stack:** Python 3.11+, Pydantic v2, PyYAML, pytest, mypy strict, deterministic scripted judge client, optional env-configured hosted judge stub disabled without credentials.

## Global Constraints

- Product runtime keeps exactly four LLM call sites: intake, planner, critic, explainer.
- LM judge is evaluation-only and lives under `backend/evals/`.
- `backend/agents/`, `backend/api/`, and `backend/core/` must not import `evals.judge` or any evaluator module.
- No frontend work, provider gateway, travel-provider API, crawling, MCP connection, ReAct, long-term memory, booking, payment, or transfer execution.
- `docs/specs/` is read-only.
- Existing M1, M1b, and M2 behavior is frozen; no optimizer/transfer math changes.
- Judge runs in normal tests are offline/scripted only; optional live judging is disabled without explicit credentials.
- Judge scores and variance are evaluation metrics, not financial values, so ordinary numeric statistics are allowed in `backend/evals/`.
- Report footer must state: computed from data last verified on `{min last_verified}`; informational, not financial advice; verify prices and offer terms before paying.

---

## File Map

- Create `backend/evals/judge.py`: typed judge contracts, judge client protocol, scripted judge, disabled hosted adapter, prompt builder, schema repair.
- Create `backend/evals/itinerary_fixtures.py`: three hand-scored anchors and eight golden itinerary cases using existing `TripSpec`, `DraftItinerary`, and seeded POI/area IDs.
- Create `backend/evals/itinerary_eval.py`: run anchors, run three judge passes per golden case, aggregate means/mins/variance/latency/tokens, enforce gates.
- Create `backend/evals/report.py`: generate one-page Markdown evaluation report.
- Create `backend/evals/test_m3_judge.py`: judge schema/rejection/prompt/client tests.
- Create `backend/evals/test_m3_itinerary_eval.py`: anchor ranking, golden gate, metrics, report generation tests.
- Create `backend/evals/test_m3_runtime_guards.py`: runtime import guard, provenance warning rendering, footer/disclaimer tests.
- Modify `backend/agents/models.py`: add deterministic `footer: str` to `FinalReport`.
- Modify `backend/agents/explainer.py`: compute min `last_verified` over used facts and append deterministic footer.
- Modify `Makefile`: add `test-m3`, `typecheck-m3`, `gate-m3`.
- Modify `backend/pyproject.toml`: include any new package data if fixture YAML files are added.
- Create/update `backend/evals/report.md`: generated one-page M3 evaluation artifact.
- Create `reports/milestone_3.md`: final gate record.
- Update `AGENTS.md` and `CLAUDE.md`: checkpoint after Gate M3 passes; keep files byte-identical.
- Update `DEVIATIONS.md`: only for M3 Tier-C choices discovered during implementation.

## Task 1: Judge Contracts and Offline Client

**Files:**
- Create: `backend/evals/judge.py`
- Test: `backend/evals/test_m3_judge.py`

**Interfaces:**
- Consumes: `agents.models.TripSpec`, `DraftItinerary`, `RetrievalContext`; Pydantic `BaseModel`.
- Produces:
  - `JudgeScores`
  - `JudgeVerdict`
  - `JudgeRunResult`
  - `LatencySummary`
  - `TokenTotals`
  - `JudgeClient`
  - `ScriptedJudgeClient`
  - `HostedJudgeClient`
  - `complete_judge_with_repair(...) -> JudgeVerdict`
  - `build_judge_prompt(...) -> tuple[str, str]`

- [ ] **Step 1: Write failing schema and client tests**

Create `backend/evals/test_m3_judge.py` with tests:

```python
def test_judge_scores_accepts_exact_five_dimensions() -> None
def test_judge_scores_rejects_missing_dimension() -> None
def test_judge_scores_rejects_out_of_range_score() -> None
def test_judge_scores_rejects_invented_dimension() -> None
def test_scripted_judge_counts_invocations_and_repairs_once() -> None
def test_scripted_judge_rejects_malformed_json_after_repair() -> None
def test_hosted_judge_is_disabled_without_credentials() -> None
def test_judge_prompt_contains_rubric_constraints() -> None
```

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_judge.py -q
```

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'evals.judge'`.

- [ ] **Step 2: Implement judge contracts and offline client**

Implement `backend/evals/judge.py` with:

```python
class JudgeScores(BaseModel):
    model_config = ConfigDict(extra="forbid")
    groundedness: int = Field(ge=1, le=5)
    interest_match: int = Field(ge=1, le=5)
    geographic_coherence: int = Field(ge=1, le=5)
    pacing: int = Field(ge=1, le=5)
    budget_respect: int = Field(ge=1, le=5)

class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scores: JudgeScores
    rationale: str = Field(min_length=1)
```

The judge prompt must include these exact constraints:

- use only supplied evidence;
- do not reward prose style;
- do not infer unstated attraction facts;
- groundedness is 5 only if all POIs and areas are supplied and no factual claim is invented;
- geographic coherence concerns area clustering;
- pacing concerns item count, durations and trip pace;
- budget respect concerns style/budget consistency with selected facts.

Implement repair behavior: one retry on `ValidationError` or malformed JSON, then raise `JudgeCallError`.

- [ ] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_judge.py -q
.venv/bin/python -m mypy --strict evals/judge.py
```

Expected: all focused tests pass and mypy is clean.

Commit:

```bash
git add backend/evals/judge.py backend/evals/test_m3_judge.py
git commit -m "feat: add m3 judge contracts"
```

## Task 2: Fixtures, Anchors, Aggregation, and Gate Logic

**Files:**
- Create: `backend/evals/itinerary_fixtures.py`
- Create: `backend/evals/itinerary_eval.py`
- Test: `backend/evals/test_m3_itinerary_eval.py`

**Interfaces:**
- Consumes: `JudgeClient`, `JudgeVerdict`, `TripSpec`, `DraftItinerary`, seeded `KnowledgeBase`.
- Produces:
  - `AnchorItinerary`
  - `GoldenItineraryCase`
  - `ItineraryAggregate`
  - `AnchorValidationResult`
  - `EvaluationSummary`
  - `GateStatus`
  - `load_anchor_itineraries() -> list[AnchorItinerary]`
  - `load_golden_itineraries() -> list[GoldenItineraryCase]`
  - `run_itinerary_evaluation(kb, judge, runs_per_case=3) -> EvaluationSummary`
  - `assert_gate_m3(summary) -> None`

- [ ] **Step 1: Write failing fixture/evaluation tests**

Create `backend/evals/test_m3_itinerary_eval.py` with tests:

```python
def test_three_anchor_itineraries_are_ranked_correctly(tmp_path) -> None
def test_eight_golden_itineraries_run_three_times_each(tmp_path) -> None
def test_golden_gate_requires_mean_at_least_four_min_dimension_three_and_groundedness_five(tmp_path) -> None
def test_latency_percentiles_and_token_totals_are_recorded(tmp_path) -> None
def test_gate_failure_lists_case_and_dimension(tmp_path) -> None
```

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_itinerary_eval.py -q
```

Expected: FAIL during collection with missing fixture/evaluation modules.

- [ ] **Step 2: Implement anchors and golden cases**

Create three anchor itineraries:

- `anchor_good`: grounded, interest-matching, area-clustered, moderate pacing.
- `anchor_scattered`: same supplied POIs but ping-pongs across more areas.
- `anchor_overpacked`: too many high-duration items for relaxed pace.

Create eight golden itinerary cases spanning:

- budget/balanced/luxury styles;
- relaxed/moderate/packed pace;
- nature, food, kids, landmark/nightlife, and shopping interest mixes;
- DEL-SIN and BOM-SIN supported routes where seed flights exist.

All fixture POI IDs and area IDs must come from existing seeds.

- [ ] **Step 3: Implement aggregation and gates**

For each golden case, run `runs_per_case=3` judge calls. Aggregate:

- per-dimension means;
- overall mean;
- per-dimension minima;
- population variance per dimension;
- p50 and p95 latency milliseconds;
- total prompt/completion tokens.

Gate rules:

- anchors ranked `good > scattered > overpacked`;
- each golden case overall mean ≥ 4.0;
- no golden case dimension mean < 3.0;
- every groundedness score equals 5.

- [ ] **Step 4: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_itinerary_eval.py -q
.venv/bin/python -m mypy --strict evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py
```

Expected: focused tests pass and mypy is clean.

Commit:

```bash
git add backend/evals/itinerary_fixtures.py backend/evals/itinerary_eval.py backend/evals/test_m3_itinerary_eval.py
git commit -m "feat: add m3 itinerary evaluation gate"
```

## Task 3: Runtime Provenance Rendering and Footer Disclaimer

**Files:**
- Modify: `backend/agents/models.py`
- Modify: `backend/agents/explainer.py`
- Test: `backend/evals/test_m3_runtime_guards.py`

**Interfaces:**
- Consumes: `FinalReport`, `EstimatorResult`, `KernelResult`, provenance on used facts.
- Produces:
  - `FinalReport.footer: str`
  - deterministic footer builder in `agents.explainer`
  - provenance warning rendering test
  - runtime import guard test

- [ ] **Step 1: Write failing runtime tests**

Create `backend/evals/test_m3_runtime_guards.py` with tests:

```python
def test_report_footer_contains_min_last_verified_and_disclaimer(tmp_path) -> None
def test_provenance_warnings_render_for_seeded_needs_verification_fact(tmp_path) -> None
def test_runtime_packages_do_not_import_evals_judge() -> None
```

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_runtime_guards.py -q
```

Expected: FAIL because `FinalReport.footer` does not exist and footer text is absent.

- [ ] **Step 2: Implement footer and provenance rendering**

Add `footer: str = ""` to `FinalReport`. In `build_final_report`, compute the minimum `last_verified` among used flight, hotel, assignment provenance flags' source rows where available, and transfer plan award rows. If no dated facts are available, use `"UNKNOWN"`.

Footer text must include:

```text
Computed from data last verified on {date}; informational, not financial advice; verify prices and offer terms before paying.
```

Do not change optimizer result fields or money math.

- [ ] **Step 3: Verify and commit**

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_runtime_guards.py evals/test_m2_reporting.py evals/test_m2_api.py -q
.venv/bin/python -m mypy --strict agents/ api/
```

Expected: M3 runtime tests and M2 report/API regressions pass.

Commit:

```bash
git add backend/agents/models.py backend/agents/explainer.py backend/evals/test_m3_runtime_guards.py
git commit -m "feat: add report provenance footer"
```

## Task 4: Report Generation and M3 Make Targets

**Files:**
- Create: `backend/evals/report.py`
- Create/update: `backend/evals/report.md`
- Modify: `Makefile`
- Test: `backend/evals/test_m3_itinerary_eval.py`

**Interfaces:**
- Consumes: `EvaluationSummary`.
- Produces:
  - `render_markdown_report(summary) -> str`
  - `write_report(summary, path=Path("evals/report.md")) -> Path`
  - `python -m evals.report`
  - `make test-m3`, `make typecheck-m3`, `make gate-m3`

- [ ] **Step 1: Add failing report generation tests**

Extend `backend/evals/test_m3_itinerary_eval.py` with:

```python
def test_eval_report_markdown_contains_gate_status_means_latency_tokens_and_limitations(tmp_path) -> None
def test_report_module_writes_backend_evals_report_md(tmp_path) -> None
```

Run:

```bash
cd backend
.venv/bin/python -m pytest evals/test_m3_itinerary_eval.py -q
```

Expected: FAIL because `evals.report` does not exist.

- [ ] **Step 2: Implement report generator and Make targets**

Report must be one page and include:

- Gate M3 status;
- anchor ordering result;
- golden itinerary count and runs per case;
- overall mean;
- per-dimension means;
- p50/p95 latency;
- token totals;
- generated timestamp or deterministic run date;
- limitations: offline scripted judge by default, no live provider calls, no runtime evaluator.

Add Make targets:

```make
test-m3:
	cd $(BACKEND) && $(PY) -m pytest evals/test_m3_*.py -q

typecheck-m3:
	cd $(BACKEND) && $(PY) -m mypy --strict evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py agents/ api/

gate-m3:
	$(MAKE) test-m3 PY=$(PY)
	$(MAKE) typecheck-m3 PY=$(PY)
	cd $(BACKEND) && $(PY) -m evals.report
```

- [ ] **Step 3: Generate report, verify, and commit**

Run:

```bash
make gate-m3 PY=.venv/bin/python
```

Expected: M3 tests pass, strict typing passes, and `backend/evals/report.md` is written.

Commit:

```bash
git add Makefile backend/evals/report.py backend/evals/report.md backend/evals/test_m3_itinerary_eval.py
git commit -m "feat: generate m3 evaluation report"
```

## Task 5: Final Gate, Milestone Report, and Checkpoint

**Files:**
- Create: `reports/milestone_3.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `DEVIATIONS.md` if M3 logged decisions.
- Modify: `docs/superpowers/plans/2026-07-25-m3-evals-provenance.md` to mark checkboxes complete.

**Interfaces:**
- Consumes: all M3 gates and regression gates.
- Produces: durable M3 checkpoint and final git state.

- [ ] **Step 1: Run fresh full verification**

Run from repo root:

```bash
make gate-m1 PY=.venv/bin/python
make gate-m1b PY=.venv/bin/python
make gate-m2 PY=.venv/bin/python
make gate-m3 PY=.venv/bin/python
make test PY=.venv/bin/python
```

Run from backend:

```bash
cd backend
.venv/bin/python -m mypy --strict core/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py
```

Expected: all gates pass; one Starlette/httpx TestClient warning may appear.

- [ ] **Step 2: Write milestone report**

Create `reports/milestone_3.md` with:

- Gate M3 checklist;
- exact command summaries;
- anchor ordering result;
- golden itinerary aggregate result;
- provenance warning test result;
- footer/disclaimer test result;
- `evals/report.md` generation path;
- known limitations;
- deviations added.

- [ ] **Step 3: Update persistent checkpoint**

Update `AGENTS.md` and `CLAUDE.md` identically:

- M3 formally complete;
- M4 is not defined in backend specs;
- next implementation layer remains frontend F1 unless the human explicitly changes order;
- provider/gateway/MCP runtime work remains deferred.

- [ ] **Step 4: Verify docs and commit**

Run:

```bash
cmp -s AGENTS.md CLAUDE.md
rg -n -- "- \\[ \\]" docs/superpowers/plans/2026-07-25-m3-evals-provenance.md
git status --short
```

Expected:

- `cmp` exits 0;
- `rg` finds no unchecked plan boxes;
- only intended M3 files are modified.

Commit:

```bash
git add AGENTS.md CLAUDE.md DEVIATIONS.md docs/superpowers/plans/2026-07-25-m3-evals-provenance.md reports/milestone_3.md
git commit -m "docs: record milestone 3 gate"
```

## Self-Review Against Specs 04 and 06

- Spec 04 §3 typed judge output: Task 1.
- Missing/out-of-range/invented/malformed judge output rejection: Task 1 tests.
- Judge rubric constraints: Task 1 prompt test.
- Three anchors and correct ranking: Task 2.
- Eight golden itineraries: Task 2.
- Three judge runs per golden itinerary: Task 2.
- Mean ≥ 4.0, no dimension < 3, groundedness = 5: Task 2.
- Metrics for pass rate, judge means, p50/p95 latency, tokens per plan: Tasks 2 and 4.
- One-page `evals/report.md`: Task 4.
- Provenance warnings render for seeded `needs_verification`: Task 3.
- Report footer disclaimers: Task 3.
- Gate M3 final report: Task 5.
- No runtime evaluator call and no runtime import of evals judge: Task 3.
- Existing M1/M1b/M2 behavior preserved: Tasks 3 and 5 regressions.
