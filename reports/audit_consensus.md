# Audit reconciliation — Codex and Claude

**Date reconciled:** 2026-08-17
**Inputs:** `reports/audit_findings_codex.md` (written first) and `reports/audit_findings_claude.md` (read afterward)
**Scope:** Evidence reconciliation only. No plan was executed and no production code was changed.

## Executive conclusion

The two audits agree on the most important product-level defect: real-catalog retrieval is not semantically connected to user interests. Codex additionally found six runtime defects that Claude did not report, including a broken live LLM configuration, 4.8-second “instant” recompute, an empty-wallet crash, no-op picker filters, missing regional areas, and incorrect spend-category mapping.

Claude’s report is valuable but partly historical. Several assertions no longer reproduce on the 2026-08-17 worktree, and its “dead scaffolding” section mixes genuine cleanup opportunities with untracked cache, intentionally archived plans, a still-canonical Singapore palette, and a future routing capability that the project does not yet claim. Those should not be accepted as one undifferentiated defect.

## 1. AGREED

### A. Real-catalog interest-aware retrieval is broken

Both auditors independently found the legacy-tag mismatch. Claude showed identical Singapore catalog results for `food` versus `museums/history`; Codex showed zero exact interest overlap and identical top candidates for food versus architecture in Mumbai, Dubai, New York, London, and Paris.

Current reproduction:

```text
BOM same_top5=True food overlap=0 architecture overlap=0
DXB same_top5=True food overlap=0 architecture overlap=0
NYC same_top5=True food overlap=0 architecture overlap=0
LON same_top5=True food overlap=0 architecture overlap=0
PAR same_top5=True food overlap=0 architecture overlap=0
```

The deterministic London fallback also produced exactly the same 32 POIs for food and architecture:

```text
food         fallback=True hotel_area=unknown items=32
architecture fallback=True hotel_area=unknown items=32
same_itinerary True
```

**Consensus severity: High.** Claude did not assign a formal severity. This is not just relevance tuning; a headline user input is functionally ignored over five of six active regions. The right test is a real-catalog metamorphic relevance test, not another seed fixture assertion.

Nuance: Claude’s universal wording (“interests have no effect”) is too broad on the current tree. Singapore’s legacy seeds make some exact tags affect ordering. That exception is itself evidence of the obsolete two-vocabulary system, not evidence that retrieval is healthy.

### B. The active catalogs are whole-city files, not the implemented tiled format

Both audits verified this fact:

```text
$ find backend/catalogs -maxdepth 3 -type f
backend/catalogs/active_sg-core.json
backend/catalogs/active_bom-core.json
backend/catalogs/active_dxb-core.json
backend/catalogs/active_nyc-core.json
backend/catalogs/active_lon-core.json
backend/catalogs/active_par-core.json
...summary JSON files...

$ find backend/catalogs -type f \( -name '*tile*' -o -name '*.sqlite' \)
<no output>
```

**Consensus classification:** known and intentional as a rollout state, not a newly hidden defect. `CLAUDE.md` already says tiled storage is implemented but active catalogs remain compacted whole files. However, whole-file loading becomes a genuine defect where request-time code repeatedly reparses those files; that consequence is Codex finding H2.

### C. The live hosted-model path is not currently viable

Claude recorded historical 8B fallback and unverified 70B explainer behavior. Codex reproduced a stronger current failure: both model IDs now return `404 model_not_found`.

```text
configured 70B API request:
status=needs_clarification stage=intake
intake provider returned HTTP 404: model `llama-3.3-70b-versatile` does not exist...

explicit 8B planner run:
used_fallback True
repair_attempted True
items 31
caveat0 Planner fallback used: planner provider returned HTTP 404:
model `llama-3.1-8b-instant` does not exist or you do not have access to it.
```

**Consensus severity: Critical for the current configured live demo.** The old report’s diagnosis—8B tool-calling quality—is historical. Today, fallback occurs before model behavior can be evaluated. `HostedFreeTier` also has no second-model fallback despite `CLAUDE.md` claiming one.

### D. Five regions have no cost-support data

Both auditors reproduced the behavior: Singapore has sample flight/hotel/FX/per-diem data; Mumbai, Dubai, New York, London, and Paris do not. Those regions return `budget_supported=False`, explicit known gaps, and effectively zero budgets.

We agree on the runtime fact but not on whether it is a discrepancy; see §4. The current behavior is honest and documented.

## 2. CLAUDE FOUND, CODEX MISSED

### A. Singapore seeds take the first three places for matching legacy interests

Codex found the vocabulary asymmetry but did not separate seed dominance into its own finding. Reproduced with the active Singapore catalog and `interests=['food', 'nature']`:

```text
1 sg-hawker-maxwell          Maxwell Food Centre     ['food']
2 sg-gardens-by-the-bay      Gardens by the Bay       ['nature','landmark','kids']
3 sg-sentosa-skyline-luge    Skyline Luge Sentosa     ['kids','nature']
4 pl_0fce...                 Astons Specialties       ['restaurant']
5 pl_1062...                 Thomson Plaza            ['restaurant']
...
10 pl_2355...                Burger King Thomson Plaza ['restaurant']
```

The observed ordering is real. I do not accept Claude’s label “placeholder POIs”: these are real, curated venues and spec 08 explicitly preserves sample/recorded fallback data. Nor is “seeds should only be fallback” established by a spec. The defect is that seeds and catalog records use incompatible semantics, guaranteeing unfair ranking. Normalize both through one vocabulary and let quality/relevance decide; do not automatically delete or demote curated records.

**Accepted as:** Medium symptom of the High interest-vocabulary defect, not a separate root-cause priority.

### B. Repository/process clutter — verified item by item

Claude grouped five different things as “dead scaffolding.” Verification does not support treating them as one finding.

#### `backend/accounts/`

```text
$ find backend/accounts -maxdepth 2 -print
backend/accounts
backend/accounts/__pycache__
backend/accounts/__pycache__/projection.cpython-314.pyc
...

$ git ls-files backend/accounts
<no output>
```

This is ignored local bytecode, not repository scaffolding. The claim does **not** reproduce as a repository issue.

#### `backend/ingestion/`

```text
$ find backend/ingestion -maxdepth 2 -print
backend/ingestion
backend/ingestion/__init__.py

$ git ls-files backend/ingestion
backend/ingestion/__init__.py
```

This reproduces, but spec 05 is explicitly unimplemented and offline ingestion remains planned. An empty package has negligible load-bearing or agent-confusion impact. **Intentional-and-fine / Low cleanup**, not a product defect.

#### Plan archive

```text
$ find docs/superpowers/plans -maxdepth 1 -type f | wc -l
36
```

There are now 36 files including the untracked R1 plan, not 35. I found two plan files explicitly marked superseded/historical (`2026-07-28-figma-template-reconciliation.md` and `2026-08-09-tripadvisor-terra-integration.md`), not evidence for “at least 8.” Historical milestone plans are useful provenance, and the mandatory session protocol says to read only the current milestone. A lifecycle index or archive subdirectory could reduce agent risk, but deleting completed plans is not warranted.

#### Four celadon design refs

This claim does **not** reproduce. The four palette artifacts are tracked, but their manifest calls them a durable confirmation render; `frontend/design/CONTRACT.md` cites them, `frontend/src/themes/singapore.css` uses the celadon tokens, and `site-header.tsx` references the render. Japan’s Quiet Blossom theme did not invalidate Singapore’s destination theme.

```text
frontend/design/CONTRACT.md: cites refs/palette and celadon tokens
frontend/src/themes/singapore.css: --th-accent-1/2 are celadon
frontend/src/components/product/site-header.tsx: references the palette render
```

**Rejected:** these are live design evidence, not abandoned debris.

#### `/plan` page and shareability

```text
$ wc -l frontend/src/app/plan/page.tsx
872 frontend/src/app/plan/page.tsx

$ find frontend/src/app -name page.tsx
frontend/src/app/plan/page.tsx
frontend/src/app/theme-proof/page.tsx
frontend/src/app/kitchen-sink/page.tsx
frontend/src/app/page.tsx
```

The 872-line page and absence of `/trip/{job_id}` reproduce structurally. However, Claude supplied no runtime output for refresh loss, and current specs/checkpoint do not claim shareable or persistent trip URLs. Accounts/persistence is explicitly unimplemented spec 17. This is maintainability and future product work, not a present claim–reality discrepancy. Do not elevate it ahead of broken existing behavior.

### C. Historical live-model observations

Claude listed ~8-minute 70B latency, 0/14 full-scenario explainer verification, and 8B fallback for every scenario.

- The P1 report supports these as historical measurements.
- They cannot be reproduced against the current provider because both configured model IDs return `404 model_not_found` immediately.
- One new live 8B run did fall back, but due to 404—not empty candidate sets or tool-calling quality.

Therefore these should remain dated historical evidence, not be presented as current reproduced causes. Once current free models are selected, latency, tool calling, and explainer groundedness must be re-baselined from zero.

### D. Unpushed work and deployment

Claude said “~45 commits unpushed; nothing deployed.” Current verification:

```text
$ git status -sb
## feat/i8a-tripadvisor-offline-adapter
...

$ git rev-list --count origin/main..HEAD
86

$ git rev-list --left-right --count '@{upstream}...HEAD'
fatal: no upstream configured for branch 'feat/i8a-tripadvisor-offline-adapter'
```

The current branch has no upstream and is 86 commits ahead of the locally known `origin/main`, so the broad “substantial work is not on origin/main” concern reproduces more strongly; the number 45 is stale. “Nothing deployed” cannot be proven from Git state alone and was not independently verified.

This is repository-release state, not a runtime defect. It should be handled only after the current mixed milestone history is reviewed; this audit must not push.

### E. Old checkpoint/test-baseline claim

Claude said `CLAUDE.md` was dated 2026-07-28 and claimed 133 tests while actual was 493. That does not reproduce on the current tree:

```text
CLAUDE.md current checkpoint: 2026-08-17
CLAUDE.md backend baseline: 592 tests
full gate: 592 passed
```

The current remaining brief error is different: its Git-status sentence still says F5.1/I8A work is uncommitted although three milestone commits now contain it. Codex recorded that as L1.

## 3. CODEX FOUND, CLAUDE MISSED

These are the highest-value additions because they were independently reproduced but absent from Claude’s audit.

### A. Current live model configuration and fallback claim are broken — Critical

Both documented model IDs return 404, the client has no model fallback, and the API maps provider failure to `needs_clarification`. Claude reported historical model quality/cap problems, not the current total failure or misleading API state.

### B. Real-catalog recompute violates its own latency gate — High

The reported ~350 ms path took 4.803 seconds with only three remaining London items. Each POI lookup reparses the whole catalog. The `<500 ms` test passes because the autouse fixture disables real catalogs and uses fake seed IDs.

### C. Empty-card wallets crash allocation — High

`UserWallet(card_ids=[])` validates, but recompute ends in:

```text
ValueError: min() iterable argument is empty
```

No optimizer or recompute test carries the schema-valid empty wallet through allocation.

### D. Activity-picker category filters are mostly no-ops — Medium

The UI vocabulary does not match the catalog taxonomy. `attractions`, `culture`, and `other` returned zero; `food` returned one legacy seed while `restaurant` returned real results; `nature` returned two seeds while `park` returned real results. The backend filter test does not assert non-empty output, so `[]` passes.

### E. Exact venue search exposes unresolved/wrongly ranked duplicates — Medium

“Buckingham Palace” produced five distinct records including a café. “Metropolitan Museum” ranked a coordinate near JFK before the real Metropolitan Museum of Art. Internal IDs are unique, so current dedupe tests remain green. Honest `verify_required` labeling keeps this Medium rather than High.

### F. Five regions have no area semantics — Medium

Mumbai, Dubai, New York, London, and Paris each return zero area rows and map every catalog POI to `Unknown`; London fallback reports `hotel_area unknown`. Coordinates preserve some routing value, but area-aware planning is still Singapore seed scaffolding.

### G. Real restaurants/cafés are deterministically classified as attractions — Medium

Every sampled `restaurant`/`cafe` from all six catalogs mapped to spend category `attractions`. The estimator only recognizes the legacy literal `food`. Amounts are currently zero, making this dormant, but future price evidence would apply the wrong card/offer rules.

### H. Current Git-status prose is stale — Low

F5.1/I8A work is committed in `8247521`, `f2fc910`, and `a898d16`; `CLAUDE.md` still says it is uncommitted.

## 4. DISAGREEMENTS

### 1. “The core value proposition works in one region out of six” is strategically fair but audit-classification wrong

The runtime observation is correct. The diagnosis “claim/reality mismatch” is not. The authoritative docs say the initial corridor is India→Singapore, mark the five other regions `budget_supported=False`, and I7 explicitly states budget omission is metadata over an unchanged costing pipeline. Six-region rollout was catalog/itinerary rollout, not cash-flight/hotel/FX rollout.

**Codex classification:** intentional-and-fine scope gap, strategically important but not a code defect or undocumented discrepancy. It becomes a discrepancy only if the UI presents those regions as fully cost-optimized despite the capability flag, which neither audit demonstrated.

### 2. Curated Singapore seeds are not “placeholder POIs” that must become fallback-only

The ordering skew reproduces; the proposed conceptual fix is overconfident. Maxwell Food Centre, Gardens by the Bay, and Skyline Luge are legitimate curated venues, and recorded/sample reliability is an explicit target behavior. Demoting all curated data would sacrifice high-quality anchors. The safe fix target is one semantic taxonomy and comparable ranking/provenance rules, not source-based suppression.

### 3. “Dead scaffolding” is substantially overstated

- `backend/accounts/` is not tracked.
- `backend/ingestion/__init__.py` is an explicit future boundary with negligible cost.
- Only two plan files were found explicitly superseded/historical, not at least eight.
- Celadon references are still canonical for Singapore.
- A monolithic page and non-shareable trips are real design debt, but shareability/persistence is not claimed implemented.

The only actionable point here is lightweight plan lifecycle/index hygiene; none belongs ahead of product paths that currently crash or lie.

### 4. Claude’s exact Singapore “interests are identical” result is not current universal behavior

Current `food` retrieval elevates Maxwell, while `architecture` does not. The defect is stronger and cleaner in the other five regions, where outputs are identical and overlap is zero. Consensus should state “interests are effectively ignored across the real regional taxonomy,” not “interests never affect anything.”

### 5. Historical LLM diagnoses cannot be carried forward after model retirement

The current 8B fallback is a provider 404, not evidence of poor tool calling. The current 70B path never reaches the explainer. After changing models, old 8-minute/0-of-14/fallback rates are baselines for the old models only. They must not be used to predict the replacement without re-running.

### 6. The checkpoint and unpushed-commit counts are stale

The current baseline is 592, not 133/493. Current origin divergence is 86 commits with no branch upstream, not ~45. The general release-management concern remains; the exact claims do not.

## 5. RECOMMENDED ORDER

This is ordering guidance only; nothing should be implemented as part of this audit.

1. **Restore a valid zero-cost live LLM configuration and truthful failure semantics.** Select currently available free models, implement/test the documented model fallback only if it remains intended, and map provider outage/configuration error to a service state rather than user clarification. Re-run the full scenario matrix because old model results are obsolete.
2. **Define one explicit semantic vocabulary across interests, UI filters, catalog categories, fallback ranking, and spend categories.** This single contract addresses the root of H1, no-op chips, seed skew, and restaurant-as-attraction costing. Validate it with real catalogs and metamorphic tests. Do not blindly execute the R1 plan; review it against all four affected surfaces first.
3. **Make real-catalog recompute meet the existing latency claim.** Eliminate per-item full-file reparsing or use the already-designed bounded/indexed mechanism, then make the `<500 ms` test opt into a representative real catalog. Do not merely relax the threshold.
4. **Specify empty-wallet behavior at the optimizer boundary.** Either support a deterministic cash/default channel or reject empty wallets at intake with a typed user-facing rule. A raw `min([])` is unacceptable.
5. **Add regional area semantics or explicitly remove area-dependent promises for unsupported regions.** Derive/curate bounded areas without manufacturing facts; test non-`Unknown` coverage and hotel-area behavior.
6. **Harden exact-venue search and identity resolution.** Add canonical landmark benchmarks, geographic plausibility, and duplicate-cluster behavior while preserving `verify_required` for ambiguity.
7. **Refresh operational documentation.** Correct the Git-status checkpoint and add a small active/completed/superseded index for plan documents. Keep historical plans for provenance.
8. **Only then address future UX architecture** such as `/trip/{job_id}`, durable trip resources, and accounts/persistence under specs 17/18.

### What not to fix now

- Do **not** invent non-Singapore flight/hotel/FX/per-diem values to make budgets nonzero.
- Do **not** remove or automatically demote the curated Singapore seeds; normalize their semantics.
- Do **not** delete the celadon palette evidence; it is still used by the Singapore theme.
- Do **not** execute the R1 plan or any archived plan from this audit.
- Do **not** activate paid providers, Tripadvisor billing, or any path that can exceed the USD 0 ceiling.
- Do **not** prioritize page splitting, accounts, deployment, or shareable URLs over current crashes, no-ops, and false latency/model claims.
- Do **not** treat the gate’s dirty-tree failure as a product regression; the audit input/output files intentionally make the tree dirty.

## Final consensus

The repository is not “mostly fake”: the deterministic kernel, provenance rules, regional catalogs, offline Tripadvisor boundary, and gates are substantial. The discrepancy pattern is narrower and more actionable: the system grew from Singapore seed data to six large catalogs without generalizing the semantic vocabulary, lookup performance, areas, and runtime integration tests. Green gates persist because the default test environment deliberately removes the real catalogs and mocks the provider. The next milestone should close that real-data execution gap before adding another provider or frontend surface.
