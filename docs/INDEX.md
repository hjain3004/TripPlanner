# Documentation index

This is the navigation page for the current TripPlanner repository. It is a map, not a second
specification. When documents disagree, use the authority order below and record a deviation before
changing behavior.

## Read in this order

1. [Current state](CURRENT_STATE.md) — what is actually on this reconciliation branch, what is enabled, and what is
   still planned.
2. [Infrastructure](INFRASTRUCTURE.md) — runtime boundaries, persistence, provider profile, and
   verification surfaces.
3. [Frontend architecture](../frontend/ARCHITECTURE.md) — the implemented Next.js structure and
   its backend contract boundary.
4. [Fable handoff](../frontend/FABLE_HANDOFF.md) — the short execution brief for a fresh frontend
   model.
5. [Frontend visual contract](../frontend/design/CONTRACT.md) — the reconciled Japan-first contract
   for the shipped direction, with known code deviations called out.
6. [Visual baseline](../frontend/design/refs/current/README.md) — what was captured, what could not
   be captured, and why.
7. [Architecture orientation](ARCHITECTURE.md) — the one-page product and system overview.
8. [Decision protocol](specs/06_implementation_protocol.md) — gates, authority, and deviation rules.
9. [Authoritative specs](specs/) — read only; the specs win over orientation and handoff prose.

## Authority map

| Question | Source of truth |
|---|---|
| Product scope, target platform, provider profile | `docs/specs/08_product_vision.md`, `09_target_platform_architecture.md`, `16_data_gateway_and_adapters.md` |
| Kernel money, optimizer, transfer, and provenance behavior | `docs/specs/00`–`07` and the committed tests/goldens |
| API wire contract | `contract/openapi.json` and generated client output |
| Implemented backend behavior | `backend/`, its tests, and the current milestone reports |
| Implemented frontend behavior | `frontend/src/`, `frontend/e2e/`, frontend tests, and [frontend architecture](../frontend/ARCHITECTURE.md) |
| Approved Japan visual direction | `docs/superpowers/specs/2026-08-09-japan-frontend-foundation-design.md`, then the reconciled `frontend/design/CONTRACT.md` |
| Historical milestone claims | The named report for that milestone; do not promote a report's planned work to current behavior |

`AGENTS.md` and `CLAUDE.md` are synchronized agent briefs. They are onboarding context, not a
replacement for the specs or for the evidence-linked current-state page.

## Deliberately untracked inputs

The following existing files were inspected and preserved without absorbing them into this docs
commit. They remain invisible to a fresh clone until deliberately committed:

| Path | Classification | Treatment |
|---|---|---|
| `docs/examples/` | User-owned or unclear image set | untouched and untracked |
| `docs/superpowers/plans/2026-08-22-japan-philatelic-landing-handoff.md` | Valuable historical/planned Japan handoff | committed on this branch; retained as historical context, not current authority |
| `docs/superpowers/plans/2026-08-22-japan-philatelic-split-landing.md` | Valuable historical/planned implementation plan | committed on this branch; useful for deferred plan-page work, not current authority |
| `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md` | Valuable planned FI0–FI6 design input | untouched and untracked; no ingestion implementation is implied here |

This classification is intentional: the two Japan plans are already committed historical inputs;
the image set and financial-ingestion plan remain user-owned/untracked and are not absorbed here.

## Historical and planned references

- [Japan foundation design](superpowers/specs/2026-08-09-japan-frontend-foundation-design.md) is
  the approved design input; it is not a statement that every J-phase item is implemented.
- [Gondola acceptance report](../reports/g3_2_gondola_live_acceptance.md) records partial live
  schema/argument verification and the still-open structured-normalization proof.
- [Japan landing handoff](superpowers/plans/2026-08-22-japan-philatelic-landing-handoff.md) and
  [Japan split-landing plan](superpowers/plans/2026-08-22-japan-philatelic-split-landing.md) are
  committed historical/planned records; the implemented CP2/Japan branch is the current evidence.
- [Robust financial ingestion plan](superpowers/plans/2026-10-07-robust-financial-ingestion.md)
  remains a plan; it does not authorize FI1 or any crawler work.
