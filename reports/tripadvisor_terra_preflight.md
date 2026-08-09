# Tripadvisor Terra Preflight Report

Date: 2026-08-09 (re-run, corrected)
Repository: `/Users/himanshu_jain/TripPlanner`
Branch at preflight: `docs/tripadvisor-terra-integration-preflight` (worktree at
`.worktrees/tripadvisor-terra-integration`, off `main` @ `095874e`)
Status: **BLOCKED — I0 and I2 prerequisites not formally gated. No Tripadvisor implementation
started.**

## Correction to the 2026-08-09 15:39 run below

The original run of this report (preserved unedited below) stopped because the frontend
typecheck/token-lint/contrast gate was red from the in-progress Poiret/register work. That
frontend work is a separate, concurrent effort (tracked in `reports/milestone_J0.md`, which
records the gate restored to green as of 17:32 the same day) and is explicitly out of scope for
this integration per the current task instructions ("ignore the frontend errors part, another
agent is already taking care of that").

Re-running the actual determinative check — whether Phase I0 and I2 of
`docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md` have **formally** passed
their gates — finds they have not, independent of the frontend gate entirely. This is the real
blocker, and it would have blocked implementation even with a green frontend gate.

**I0 (evidence-graph correctness repair):** DEVIATIONS.md records several I0-shaped fixes landed
2026-07-29 (budget/edges/contradiction/resolution work). But `docs/superpowers/plans/
2026-08-02-itinerary-i0-evidence-hardening.md` requires, as its Task 7 exit criteria, a
`reports/itinerary_i0_evidence_hardening.md` gate report, an `identity.py` module (Task 3, typed
exact identity), a finished `SqliteEvidenceStore` (Task 5), and boundary tests
(`test_evidence_boundary.py`, Task 7). Checked directly:

```
$ ls reports/ | grep -i itinerary
(no output — the report does not exist)
$ ls backend/gateway/evidence/identity.py
ls: gateway/evidence/identity.py: No such file or directory
$ cd backend && .venv/bin/pytest -q
133 passed, 1 warning in 2.17s
```

133 tests still pass (the floor holds, no regression), but I0 has no gate report and is missing
at least Tasks 3, 5, and 7 of its own plan. **I0 has not formally passed its gate.**

**I2 (place contracts, registry, sample adapter):** searched the entire backend for any trace of
the I2 deliverables named in the itinerary design §14 (`Place`, `PlaceSearchRequest`,
`PlaceCandidate`, `SamplePlaceAdapter`, a provider registry):

```
$ grep -rl "SamplePlaceAdapter\|PlaceSearchRequest\|ProviderRegistry\|provider_registry" backend --include="*.py"
(no output)
$ find backend/gateway -maxdepth 1 -type d
backend/gateway
backend/gateway/evidence
backend/gateway/__pycache__
```

`backend/gateway/` contains only the `evidence/` module. **I2 does not exist at all** — zero
files, not merely an un-gated draft.

## Decision (corrected)

Per the task's explicit branch for this situation, implementation does not proceed. Instead:

- `docs/superpowers/plans/2026-08-09-tripadvisor-terra-integration.md` was written — a forward
  design/task plan for Phase I8, explicitly marked "DO NOT EXECUTE" until both gates are re-checked
  and pass.
- This report was corrected in place rather than silently left wrong, since the original blocking
  reason no longer applies but the conclusion (BLOCKED) is unchanged for an independent reason.
- No code, registry entry, credential, or adapter was added.

## Original preflight (2026-08-09, 15:39) — preserved for record

## Scope

This preflight evaluated whether the official Tripadvisor Terra service can be integrated now
without violating TripPlanner's deterministic gateway architecture, phase order, evidence
requirements, and hard USD 0 out-of-pocket profile.

No provider adapter, MCP configuration, credential, runtime REST client, frontend change, or
Tripadvisor activation record was added.

## Persistent-doc drift

`AGENTS.md` and `CLAUDE.md` currently disagree.

- `AGENTS.md` says Frontend F1-F4 have landed, `backend/gateway/evidence/` exists with 8 tested
  modules, and the backend regression baseline is 133 tests.
- `CLAUDE.md` still contains older checkpoint language saying frontend is paused/scaffolded,
  later layers are scaffolds, and the backend regression floor is 100.

Per the task instruction, this drift was reported rather than silently resolved. Specs remain the
authority over both files.

## Preflight commands

```bash
cd backend
.venv/bin/pytest evals/ -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/

cd ../frontend
npx tsc --noEmit
node scripts/token-lint.mjs
npx vitest run tests/contrast.test.ts tests/contract.test.ts
```

## Observed results

Backend:

- `backend` pytest: **133 passed**, 1 known Starlette/httpx deprecation warning.
- `backend` strict mypy over `core/ agents/ api/ gateway/`: **clean**, 42 source files.

Frontend:

- `npx tsc --noEmit`: **failed**.
  - `src/app/kitchen-sink/views/RegisterSpecimenView.tsx:76`
  - `AppliedOffer` fixture is missing required `stacking_class`.
- `node scripts/token-lint.mjs`: **failed** with 4 violations.
  - `src/app/globals.css:5` `globals-manifest`
  - `src/components/product/offset-plate.tsx:14` `no-direct-var`
  - `src/components/product/split-flap.tsx:15` `no-direct-var`
  - `src/components/product/split-flap.tsx:20` `no-direct-var`
- `npx vitest run tests/contrast.test.ts tests/contract.test.ts`: **failed**.
  - `tests/contrast.test.ts`
  - `--th-display-stroke-ratio` has no bridge mapping.
  - 1 failed, 100 passed.

## Decision (original run, superseded below)

The Tripadvisor branch must not proceed while the existing frontend Poiret/register work leaves
the required preflight gate red. This follows the task instruction:

> If the frontend typecheck or token gate is red because of the existing Poiret/register work,
> stop. Do not bundle frontend repairs into the Tripadvisor branch.

## Phase sequencing status (original run)

Tripadvisor Terra remains Phase I8 per
`docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md`.

At minimum, the adapter requires:

- I0: correct persistent evidence graph and zero-cost budget enforcement.
- I2: normalized place contracts, provider registry, activation checks and `SamplePlaceAdapter`.

This preflight stopped before implementation because the frontend gate was already red. No
Tripadvisor runtime work should begin until the preflight is green and I0/I2 completion is
verified by their reports and gates.

## Runtime transport decision

No runtime transport was selected in code. Unchanged by the correction below.

The intended architectural direction remains:

- Prefer official Terra REST for runtime after prerequisites exist, because REST gives explicit
  endpoint allowlisting, request sizing, deterministic entity accounting, and stable typed
  parsing.
- Treat the official Terra MCP endpoint (`https://docs.terra.tripadvisor.com/mcp`) as developer
  tooling only unless a later adapter proves deterministic schema enumeration, budget
  enforcement, credential isolation, and fixture-testable error behavior without exposing raw
  tools to an LLM.

## Activation status

- Tripadvisor adapter enabled: **no**.
- Tripadvisor MCP configured in repo: **no**.
- API key added: **no**.
- Live smoke test run: **no**.
- Lifetime entity ceiling configured: **not implemented**; planned default remains 900 only when
  the adapter phase is reached.
- Account-level overage mechanically prevented: **not verified**.

## Next required action (corrected, 2026-08-09 re-run)

The frontend gate is no longer the blocker (see the correction at the top of this report) and does
not need repair before this integration can proceed — that work belongs to a separate, concurrent
session. The actual next required action is:

1. Execute (or have executed) the I0 plan's remaining tasks —
   `docs/superpowers/plans/2026-08-02-itinerary-i0-evidence-hardening.md` Tasks 3, 5, 6, 7 in
   particular — through to a passing Gate I0 and a written
   `reports/itinerary_i0_evidence_hardening.md`.
2. Write and execute a separate `itinerary-i2-contracts` plan (not part of this task's scope) to
   land `Place`, `PlaceSearchRequest`, `PlaceCandidate`, the provider registry, and
   `SamplePlaceAdapter`, gated per the itinerary design §14 Gate I2 criteria.
3. Re-run the precondition check at the top of
   `docs/superpowers/plans/2026-08-09-tripadvisor-terra-integration.md` — only once both pass does
   that plan's Task 1 become executable.
4. No Tripadvisor credential, registry entry, or adapter code should be added before that
   precondition check passes clean.
