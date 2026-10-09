# Current state

**Evidence date:** 2026-10-08  
**Repository baseline:** `main` and `origin/main` at `c3261ab` (`Merge pull request #12 from
hjain3004/feat/g3-gondola-readonly-mcp`)  
**Documentation branch:** `codex/docs-fable-handoff`

This page is the short, evidence-linked answer to “what is real right now?” It intentionally
separates shipped code, disabled experiments, and plans.

## Shipped backend foundations

- The deterministic Kernel MVP, optimizer, transfer pathfinder, M2/M3 orchestration, provenance,
  accounts A1/A2, and CP1 planning domain are present on the inspected `main` commit. The current
  backend regression count must be taken from the verification run in the accompanying report,
  not copied from an older checkpoint.
- The API exposes the current `/plan`, `/plan/{job_id}`, `/plan/recompute`,
  `/plan/refresh-prose`, `/places/search`, and account routes in `backend/api/main.py`.
- The frontend's mock environment is the default. The browser API facade and MSW handlers supply
  deterministic fixture responses; live mode is an explicit environment choice.

## Gateway and provider status

| Surface | Current evidence | Status |
|---|---|---|
| Travel gateway contracts and `SampleAdapter` | `backend/gateway/travel/`, G1 report | shipped, offline/default |
| Reference importers and catalog gateway | `backend/gateway/reference/`, `catalog/`, G2 report | shipped, offline |
| Gondola adapter and MCP transport | `backend/gateway/travel/adapters/gondola/`, PR #12, G3.1/G3.2 reports | code and fixtures shipped; registry-disabled by default; `/plan` not wired |
| Tripadvisor Terra | `backend/gateway/places/adapters/tripadvisor/`, I8A.2.1 report | fixture path shipped; live transport disabled and activation pending |
| Financial ingestion | no production implementation on `main`; only the untracked robust-ingestion plan | not started; do not start FI1 here |

Gondola's live work is not equivalent to production activation. The report records verified tool
argument shapes, safety boundaries, and a repeated unstructured response; it explicitly does not
claim a captured structured response/normalization proof. No booking, payment, transfer, or
`mcp:write` path is enabled.

## Frontend status

The frontend is implemented beyond the old F1 handover:

- Next.js 16 App Router routes include `/`, `/plan`, `/kitchen-sink`, and `/theme-proof`.
- `/plan` contains the five-step wizard, MSW-backed job polling, report rendering, editable
  itinerary operations, deterministic recompute, prose refresh, freshness indicators, and card
  guidance. The editable itinerary work is evidenced by the F5/F5.1 reports and current source.
- `frontend/src/app/layout.tsx` loads Poiret One, Schibsted Grotesk, and Roboto Mono and currently
  resolves `JP` for the root shell. `frontend/src/lib/theme/resolver.ts` also contains an
  unconditional Japan default, so destination fallback behavior is a documented code gap rather
  than a design contract assumption.
- The MSW fixture corpus remains Singapore/India-oriented (`DEL`/`SIN`, Marina Bay, and INR), even
  though the shell has Japan theme files. Japan is therefore a visual direction/partial shell
  state, not proof of a complete Japan data pack or localized product journey.
- `frontend/design/CONTRACT.md` is reconciled in this branch. The old
  `frontend/FRONTEND_HANDOVER.md` is retained as history but now has a stale-status banner.

## Worktree and branch reality

The repository has separate managed worktrees for the FI0 experiment, CP2, and Japan design work.
They are not merged evidence for this checkout. This branch changes documentation only. No
worktree was deleted, moved, reset, or cleaned.

## What is explicitly not claimed

- No backend product behavior, OpenAPI schema, generated client, frontend product code, financial
  math, provider activation, crawler SDK, credential, or live MCP/API call was added by this
  documentation task.
- A report saying “complete” for an older milestone does not mean its later live activation or
  integration follow-up is complete.
- The untracked plans and image directory are not canonical until deliberately committed.
