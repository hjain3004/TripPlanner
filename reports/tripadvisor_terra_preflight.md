# Tripadvisor Terra Preflight Report

Date: 2026-08-09  
Repository: `/Users/himanshu_jain/TripPlanner`  
Branch at preflight: `main`  
Status: **BLOCKED — no Tripadvisor implementation started**

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

## Decision

The Tripadvisor branch must not proceed while the existing frontend Poiret/register work leaves
the required preflight gate red. This follows the task instruction:

> If the frontend typecheck or token gate is red because of the existing Poiret/register work,
> stop. Do not bundle frontend repairs into the Tripadvisor branch.

## Phase sequencing status

Tripadvisor Terra remains Phase I8 per
`docs/superpowers/specs/2026-08-02-itinerary-intelligence-design.md`.

At minimum, the adapter requires:

- I0: correct persistent evidence graph and zero-cost budget enforcement.
- I2: normalized place contracts, provider registry, activation checks and `SamplePlaceAdapter`.

This preflight stopped before implementation because the frontend gate was already red. No
Tripadvisor runtime work should begin until the preflight is green and I0/I2 completion is
verified by their reports and gates.

## Runtime transport decision

No runtime transport was selected in code.

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

## Next required action

Repair the existing frontend Poiret/register gate failures in a separate frontend branch. After
the required preflight is green, re-run this preflight and then verify whether I0 and I2 have
formally passed before writing or executing any Tripadvisor Terra adapter plan.
