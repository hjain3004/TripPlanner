# Integration — FI0 + G3.5 + G4

**Status: ACCEPTANCE PENDING** — merges, reconciliation, verification and independent review are
complete; the final exact-tree `make gate` result is recorded in the next section once it has run.

**Branch:** `codex/integrate-fi0-g3-5-g4` (local, unpublished)
**Worktree:** `/Users/himanshu_jain/.codex/worktrees/integrate-fi0-g3-5-g4/TripPlanner`
**Integration base:** `eccb19885557001fec7a87d5b459998dda646e57` (`origin/main`; fetched, had **not** advanced)

## Sources and merge commits

All merges are real `git merge --no-ff` commits. Nothing was rebased, squashed, cherry-picked,
force-updated or discarded. Each source HEAD matched its expected SHA and each source worktree was clean
before and after.

| Order | Source branch | Source HEAD | Merge commit |
|---|---|---|---|
| 1 | `codex/g3-5-gondola-contract-closure` | `fae391582211d0c8c74ea24be71ee0976eb0ad9b` | `e2f8d18` |
| 2 | `codex/g4-open-meteo-mcp` | `805fa737315dbd2476962813e34319e1fb6308bb` | `bcbc4d4` (amended once, see below) |
| 3 | `codex/fi0-acceptance-integration` | `95db19df499021b8794378af6d82fe6373dd4650` | `2d21493` |

### Important ancestry disclosure (G3.4 and CP3)

`codex/g3-5-gondola-contract-closure` is **stacked on** the implemented G3.4 confirmed-brief gateway
(`5ffbbe8`), which is stacked on the implemented CP3 interview assistance (`a24f557`). Both are ancestors of
G3.5's HEAD, so a real non-fast-forward merge of G3.5 necessarily brings their commits, their frontend
changes and their OpenAPI contract changes. `codex/g3-4-confirmed-brief-gateway` and
`codex/cp3-interview-assistance` were **not** merged as separate branches (their tips are already ancestors,
so merging them would add nothing and was not done). This is a consequence of G3.5's history, not a new
milestone, and it is also what makes the expected test arithmetic work
(1266 base + 82 from the G3.5 stack + 344 G4 + 17 FI0 = 1709).

G3.4's own report (`reports/g3_4_confirmed_brief_gateway.md`) still says **ACCEPTANCE PENDING**; this
integration does not formally accept G3.4 and does not start any G3.4, CP3, FI1 or CP4 work.

## Conflict resolutions

| File | Merge | Conflict | Resolution |
|---|---|---|---|
| `DEVIATIONS.md` | G4 | both sides appended a section at end of file | kept both: the G3.5 section, then the G4 section. Verified by script that every row added by each branch (G3.5 stack 21 lines, G4 12, FI0 2) is present in the merged file. |
| `AGENTS.md`, `CLAUDE.md` | FI0 | the "Current checkpoint" narrative (two hunks each) | one combined, factual checkpoint written identically to both files; per-branch numbers removed from the brief (they were measured on different trees) and pointed to this report; added G3.5 and G4 bullets. `cmp AGENTS.md CLAUDE.md` is byte-identical. |
| `backend/pyproject.toml` | FI0 | auto-merged, reviewed | retains `ingestion`, `gateway.weather`, `gateway.weather.scripts`, the Gondola packages, weather fixture/lockfile package-data and `mcp>=2.3,<3` (the G3.5 side still said `mcp>=1.2`; the merge correctly took G4's bound). |
| `Makefile` | FI0 | auto-merged, reviewed | `gate` still runs full pytest, strict mypy over `core accounts planning agents api gateway` plus `ingestion`, the zero-tolerance Ruff scope plus `ingestion`, the legacy ceiling, and the frozen-artifact/clean-tree checks. |
| `reports/` | all | none | additive: G3.4, G3.5, CP3, G4, FI0 reports all present. |

One process error, disclosed: while resolving the G4 merge a BSD `sed -i -e` invocation failed but the
following `git commit` still ran, so the first G4 merge commit briefly contained conflict markers. It was
unpublished; the markers were removed and the merge commit was amended in place (both parents preserved) before
any further step. The final topology above is the amended one.

## Independent review (against the integration base)

An independent read-only reviewer examined the merge results and cross-branch interactions. No Critical
findings.

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | Important | `docs/CURRENT_STATE.md`, `docs/INFRASTRUCTURE.md`, `docs/INDEX.md` (inherited from the G3.4/CP3 stack, untouched by the merges) still said financial ingestion "not started / absent" and omitted weather and G3.5. | **Fixed**: the three docs now describe FI0 (offline only), G4 (disabled, `community_mcp`, not wired) and G3.5, with the current branch and evidence date. Docs-only; no code change, so no new regression test applies. |
| 2 | Important | `CLAUDE.md`/`AGENTS.md` cite this report, which did not exist yet. | **Fixed**: this report is committed with the doc fixes. |
| 3 | Minor, pre-existing | `pyproject.toml` `packages` omits some subpackages (`gateway.reference*`, `gateway.places.adapters.tripadvisor`); identical at base. | **Not changed** (out of scope for an integration; editable installs work; non-editable installs are not used by the gate). Recorded as a limitation. |
| 4 | Minor | FI0's boundary test forbids only a short list of network/crawler imports and checks only `core`/`agents`/`api` for importing `ingestion`. | **Not changed** (FI0 test strength is FI0's decision and altering it would be a behaviour change to an accepted milestone). The actual state is clean: a grep of every import in `ingestion/` finds only stdlib, pydantic and `urllib.parse`; no other backend package imports `ingestion`; and `test_weather_boundary` independently asserts that `ingestion` does not import weather. |
| 5 | Minor/cosmetic | A DEVIATIONS heading says "documentation only" but also holds two FI0 implementation rows; G3.4/CP3 sections sit near the top of the file. | **Not changed** (preserving every branch's entries and order was an explicit requirement). |

The reviewer's category verdicts: merge-resolution correctness PASS, cross-branch interactions PASS,
safety properties PASS, residual-defect search FAIL only on findings 1 and 2, both now fixed.

## Verification

Environment: fresh `backend/.venv` (mcp 2.3.0) and the approved ignored catalogs copied into
`backend/catalogs/` (both verified ignored; nothing committed). `make seed PY=.venv/bin/python` passed.

| Check | Result |
|---|---|
| Complete backend pytest (pre-doc-fix run) | **1709 passed, 1 skipped** (3 warnings: swig deprecation and similar) |
| Focused: FI0 `test_fi0_ingestion.py` | **17 passed** |
| Focused: G4 `test_weather_*.py` | **344 passed** |
| Focused: G3.5 Gondola + smoke (`test_gondola_*.py`, `test_smoke_gondola_script.py`) | **197 passed** |
| Focused: carried CP3/G3.4 (`test_cp3_api.py`, `test_cp3_assistant.py`, `test_g3_4_boundaries.py`) | **62 passed** |
| Strict mypy, gate scope (`core accounts planning agents api gateway`) | clean, **172 source files** |
| Strict mypy, `ingestion/` | clean, 5 files |
| Strict mypy, all packages in one invocation | clean, **177 source files** |
| Ruff zero-tolerance (`accounts planning agents gateway evals ingestion`) | **All checks passed** |
| Ruff legacy `core/` + `api/` | **6 findings** (ceiling 12) |

The 1709 figure equals the arithmetic estimate in the task, but it is reported because it was measured, not
assumed. Frontend and browser suites were not re-run here (no frontend file was changed by the merges
themselves; the frontend tree is byte-identical to the G3.5 branch's, whose report records those results).

## Unchanged-artifact proof

Compared with the integration base `eccb198`:

- `backend/evals/golden/`: **no diff**.
- all of `backend/core/` (including `backend/core/seeds/`, optimizer and transfer arithmetic): **no diff**.
  No Tier-F arithmetic changed.
- `AGENTS.md` and `CLAUDE.md`: byte-identical to each other.
- `contract/openapi.json` and `frontend/`: **differ from the base**, but only because of the G3.4/CP3/G3.5
  stack; both are **byte-identical to the G3.5 branch** (`git diff fae3915 HEAD -- contract frontend` is
  empty). FI0 and G4 touch neither. The merges and reconciliation changed neither.

## Safety properties confirmed in the merged tree

- Gondola and Open-Meteo are disabled by default (default registries checked directly; the runtime factory
  registers only `SampleAdapter`); nothing in `agents/` or `api/` references them.
- Open-Meteo remains `community_mcp`; its kill switch wins; it is not wired to `/plan`, OpenAPI or the UI.
- No live provider became request-time active; no live call, OAuth flow, booking, payment, transfer or
  mutation capability was enabled by the integration.
- FI0 stays offline: no crawler SDK, Crawl4AI, Firecrawl, scheduler, extraction LLM or network import in
  `backend/ingestion/`.
- No credential, token, account data or raw provider response was committed (diff scan clean); weather and
  Gondola fixtures are labelled synthetic or sanitized capture; no catalog, venv, database or `.env` file is
  tracked.

## Remaining limitations

- G3.4 remains ACCEPTANCE PENDING in its own report; CP3 and G3.4 are present only as G3.5's ancestors.
- Weather historical and climate tools have never been run against the real server (only forecast and current
  conditions were probed once).
- Pre-existing `pyproject.toml` packaging gap for a few subpackages (finding 3).
- Frontend and browser suites were not re-run in this task.
- The branch is local and unpublished; no PR was opened.

## Explicitly not started

FI1, G3.4 acceptance, CP3, CP4, G3.3-style `/plan` wiring, any new live provider activation, any crawler or
fetch implementation, and any new milestone were **not** started.

## Final acceptance

Recorded after the exact-tree gate (see below).
