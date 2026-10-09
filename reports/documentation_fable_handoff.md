# Documentation and Fable 5.1 handoff reconciliation

**Date:** 2026-10-08  
**Branch:** `codex/docs-fable-handoff`  
**Scope:** documentation and evidence reconciliation only  
**Status:** acceptance pending for the environment-dependent frontend build/visual gate

## Outcome

Added a canonical reading order and current-state handoff for a fresh model, with explicit
separation between implemented code, disabled provider seams, historical reports, and untracked
plans/assets. Reconciled the frontend contract to the approved Japan-first direction and bannered
the stale pre-implementation frontend handoff.

No backend, OpenAPI, generated client, frontend product source, financial golden, provider
configuration, credential, crawler SDK, live MCP/API call, or authoritative spec was changed.

## Evidence used

- `main`/`origin/main` resolve to `c3261ab`, the merge of Gondola PR #12.
- `backend/gateway/travel/registry.py` enables `sample_travel_adapter` and constructs Gondola as
  environment-controlled/disabled by default; `backend/api/main.py` does not wire `/plan` to that
  registry.
- `backend/gateway/places/registry.py` enables sample/snapshot and keeps Tripadvisor disabled by
  default.
- The current frontend source has App Router pages, MSW, the five-step `/plan` flow, editable
  itinerary behavior, recompute/prose refresh, and Japan theme files. The mock corpus remains
  India/Singapore-shaped.
- `frontend/design/CONTRACT.md` previously described Bodoni/F1 Singapore-era rules while
  `frontend/src/app/layout.tsx` loads Poiret One and `frontend/src/themes/japan.css` exists.

## Files changed

Canonical navigation/current state:

- `docs/INDEX.md`
- `docs/CURRENT_STATE.md`
- `docs/INFRASTRUCTURE.md`
- `docs/ARCHITECTURE.md`
- `AGENTS.md` and `CLAUDE.md` (kept byte-identical)
- `DEVIATIONS.md`

Frontend handoff/contract:

- `frontend/ARCHITECTURE.md`
- `frontend/FABLE_HANDOFF.md`
- `frontend/design/CONTRACT.md`
- `frontend/FRONTEND_HANDOVER.md` (stale-status banner only)
- `frontend/design/refs/current/README.md`

## Existing untracked files: individual disposition

| Path | Classification | Disposition |
|---|---|---|
| `docs/examples/` | user-owned/unclear image set | preserved untouched and untracked |
| `docs/superpowers/plans/2026-08-22-japan-philatelic-landing-handoff.md` | valuable historical/planned Japan handoff | preserved untouched and untracked; not current authority |
| `docs/superpowers/plans/2026-08-22-japan-philatelic-split-landing.md` | valuable historical/planned implementation plan | preserved untouched and untracked; describes deferred plan-page work |
| `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md` | valuable planned FI0–FI6 input | preserved untouched and untracked; no FI1 or crawler work started |

## Screenshot attempt

No fresh screenshots are claimed. `npm run build` failed before serving because `next/font/google`
could not fetch Poiret One, Roboto Mono, or Schibsted Grotesk from `fonts.googleapis.com` in this
restricted environment. The existing Playwright web server invokes that build, so the attempted
landing screenshot run also stopped before browser startup. The failure and existing reference
directories are recorded in `frontend/design/refs/current/README.md`.

## Verification

| Command | Result |
|---|---|
| `cd backend && ./.venv/bin/pytest -q` | `1253 passed, 1 skipped, 3 warnings in 78.88s` |
| `cd frontend && npx vitest run --reporter=dot` | `2 files, 119 passed` |
| `cd frontend && npx tsc --noEmit` | passed |
| `cd frontend && node scripts/token-lint.mjs` | `0 violations across 12 rules. PASS` |
| `cd frontend && npx eslint .` | 0 errors, 14 warnings |
| `make gate-f1` | failed at `fe-build`: three Google-font fetch failures; token/contrast/type phases passed before it |
| `cd frontend && npx playwright test f1-5-landing.spec.ts --config=e2e/playwright.config.ts --reporter=list` | web server failed at the same font build boundary before tests ran |
| `git diff --check` | passed |
| `cmp AGENTS.md CLAUDE.md` | passed |
| product diff stat for `backend/`, `contract/`, `frontend/src/`, package manifests | empty |

The frontend gate is therefore not claimed as passing. No unrelated build or product repair was
attempted.

## Remaining documentation/product gaps

- The resolver's unconditional Japan default and hard-coded root `JP` proof selection need a scoped
  product decision before theme fallback can be called implemented.
- Mock fixtures still describe `DEL`/`SIN` and INR while the visual contract is Japan-first.
- Fresh visual captures at 390/768/1440 and loading/results/editable-itinerary states remain
  pending a build environment with the declared fonts available.
- Gondola structured-response normalization and `/plan` integration remain open per the G3.2
  report. Financial ingestion remains unimplemented and out of scope.
