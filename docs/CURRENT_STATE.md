# Current state

**Evidence date:** 2026-10-09
**Repository state:** reconciliation branch `codex/reconcile-cp2-japan`, with the CP2/Japan
implementation and documentation baseline merged by a real merge commit. The exact final commit,
test count, and gate output are recorded in `reports/cp2_japan_documentation_integration.md`.

This page is the short, evidence-linked answer to “what is real right now?” It intentionally
separates shipped code, disabled experiments, and plans.

## Shipped backend foundations

- The deterministic Kernel MVP, optimizer, transfer pathfinder, M2/M3 orchestration, provenance,
  accounts A1/A2, CP1 planning domain, and CP2 conversational/session API are present. The current
  backend regression count must be taken from the verification run in the accompanying report,
  not copied from an older checkpoint.
- The API exposes `/plan`, `/plan/{job_id}`, `/plan/recompute`, `/plan/refresh-prose`,
  `/places/search`, account routes, and authenticated `/planning/preferences` plus
  `/planning/sessions` routes in `backend/api/main.py` and `backend/api/conversation.py`.
- CP2 confirmation starts the existing non-live planning path exactly once and records durable
  session/audit state; it does not activate Gondola, Tripadvisor, crawling, booking, or payment.
- The frontend's mock environment is the default. The browser API facade and MSW handlers supply
  deterministic fixture responses; live mode is an explicit environment choice.

## Gateway and provider status

| Surface | Current evidence | Status |
|---|---|---|
| Travel gateway contracts and `SampleAdapter` | `backend/gateway/travel/`, G1 report | shipped, offline/default |
| Reference importers and catalog gateway | `backend/gateway/reference/`, `catalog/`, G2 report | shipped, offline |
| Gondola adapter and MCP transport | `backend/gateway/travel/adapters/gondola/`, PR #12, G3.1/G3.2 reports | code and fixtures shipped; registry-disabled by default; `/plan` not wired |
| Tripadvisor Terra | `backend/gateway/places/adapters/tripadvisor/`, I8A.2.1 report | fixture path shipped; live transport disabled and activation pending |
| Financial ingestion | no production implementation; only the untracked robust-ingestion plan | not started; do not start FI1 here |

Gondola's live work is not equivalent to production activation. The report records verified tool
argument shapes, safety boundaries, and a repeated unstructured response; it explicitly does not
claim a captured structured response/normalization proof. No booking, payment, transfer, or
`mcp:write` path is enabled.

## Frontend status

The frontend is implemented beyond the old F1 handover:

- Next.js 16 App Router routes include `/`, `/plan`, `/plan/conversation`, `/profile`,
  `/kitchen-sink`, and `/theme-proof`.
- `/plan/conversation` and `/profile` are the CP2 conversational/profile surfaces. They use typed
  controls, authenticated API calls, server-owned session state, explicit confirmation, and no
  browser storage.
- `/plan` contains the five-step wizard, MSW-backed job polling, report rendering, editable
  itinerary operations, deterministic recompute, prose refresh, freshness indicators, and card
  guidance. The editable itinerary work is evidenced by the F5/F5.1 reports and current source.
- `frontend/src/app/layout.tsx` loads Poiret One, Schibsted Grotesk, and Roboto Mono. The root
  passes `null` to the deterministic resolver and therefore uses the natural fallback; explicit
  `JP` is used only by the theme-proof/kitchen-sink visual proof and typed Japan fixtures.
- The MSW fixture corpus remains Singapore/India-oriented (`DEL`/`SIN`, Marina Bay, and INR), even
  though the shell has Japan theme files. Japan is therefore a visual direction/partial shell
  state, not proof of a complete Japan data pack or localized product journey.
- `frontend/design/CONTRACT.md` is reconciled in this branch. The old
  `frontend/FRONTEND_HANDOVER.md` is retained as history but now has a stale-status banner.

## Worktree and branch reality

The CP2/Japan implementation is present in this checkout and has been reconciled with the three
documentation commits from `origin/main`. Separate FI0 worktrees and the original main-worktree
untracked files were not modified, moved, reset, or cleaned.

## What is explicitly not claimed

- No CP3/G3.4 integration, financial-ingestion implementation, crawler SDK, credential, or live
  provider/MCP/API call was added by this reconciliation. CP2/Japan code is included because it
  was already present on the implementation branch being reconciled.
- A report saying “complete” for an older milestone does not mean its later live activation or
  integration follow-up is complete.
- The untracked plans and image directory are not canonical until deliberately committed.
