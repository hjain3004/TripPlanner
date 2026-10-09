# Fable 5.1 frontend handoff

Use this page as the short starting brief. Read [the project index](../docs/INDEX.md),
[current state](../docs/CURRENT_STATE.md), and [frontend architecture](ARCHITECTURE.md) before
touching code.

## Non-negotiable boundaries

- This is a frontend task unless the user explicitly changes scope. Do not edit `backend/`,
  `contract/openapi.json`, generated API output, financial goldens, or provider configuration for a
  visual/docs request.
- Render API-provided money, points, fees, percentages, and provenance. Never calculate them in
  React. Use the existing `MoneyText`/provenance components and preserve verification labels.
- Default to MSW/mock mode. Do not make live provider, MCP, crawler, booking, payment, transfer, or
  credential calls. Gondola and Tripadvisor are disabled/isolated according to
  [infrastructure](../docs/INFRASTRUCTURE.md).
- Do not use `localStorage` or `sessionStorage`; do not commit secrets.
- Specs in `docs/specs/` are read-only and authoritative for architecture/gates. Log any judgment
  call in `DEVIATIONS.md`.

## What exists

- Next.js 16 App Router with `/`, `/plan`, `/kitchen-sink`, and `/theme-proof`.
- `/plan` already has the five-step wizard, mock polling, report sections, editable itinerary,
  recompute/prose refresh, freshness, and payment guidance. Preserve these seams.
- Semantic themes and a Japan-first visual shell exist. The root currently intentionally resolves
  `JP` for the visual proof, while the resolver also contains a known unconditional Japan default.
- `frontend/design/CONTRACT.md` is the current visual contract. The old
  `frontend/FRONTEND_HANDOVER.md` is historical and explicitly stale.

## Safe workflow

1. Check `git status --short`; preserve unrelated dirty and untracked files.
2. Read the relevant route/component, its tests, the API facade, and the matching spec.
3. Make the smallest scoped change with tests. Keep behavior/refactor/documentation commits
   separate when possible.
4. Run the narrow test, then the applicable frontend gate. Capture exact output.
5. Inspect `git diff --check`, `cmp AGENTS.md CLAUDE.md`, and the final diff. Do not call a milestone
   complete from an old report.

## Current open work

- Reconcile resolver/theme selection and the Singapore-shaped mock data only in a separately scoped
  product task.
- If extracting result rendering, start from the current editable `/plan` implementation rather
  than an older Japan branch; do not drop F5/F5.1 interactions.
- Capture a fresh 390/768/1440 visual baseline when the build environment can resolve the declared
  Google fonts. The current attempt is documented in
  `frontend/design/refs/current/README.md`.
- Financial ingestion remains a separate, unstarted planned milestone. Do not begin FI1 here.

## Handoff checklist

Before reporting success, state: files changed, exact test/gate commands and outcomes, commit hash,
clean status, screenshot coverage, and any remaining stale/planned documentation. Confirm explicitly
that no backend/OpenAPI/frontend-product/provider behavior changed if the task was docs-only.
