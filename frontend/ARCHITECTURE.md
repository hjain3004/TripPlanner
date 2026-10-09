# Frontend architecture

**Current evidence:** source under `frontend/src`; API boundary under `frontend/src/lib/api` and
`contract/openapi.json`; exact branch/test evidence is in
`reports/cp2_japan_documentation_integration.md`.

## Runtime shape

```text
App Router pages
  ├─ `/`                 landing / route-first editorial shell
  ├─ `/plan`             five-step wizard, polling, report, editable itinerary
  ├─ `/plan/conversation` CP2 typed interview, review, amend, confirm, resume
  ├─ `/profile`          CP2 authenticated preference projection and updates
  ├─ `/kitchen-sink`     component/state proof surface
  └─ `/theme-proof`      theme inspection surface
          │
          ▼
  Providers + MSWProvider
          │
          ├─ mock mode (default): Service Worker handlers and fixtures
          └─ live mode: generated/API facade → configured FastAPI base URL
```

`frontend/src/app/layout.tsx` owns fonts, theme class selection, providers, and the page
transition wrapper. It loads Poiret One, Schibsted Grotesk, and Roboto Mono. The root passes `null`
to the deterministic resolver and uses the natural fallback; explicit `JP` is selected only by
visual proof surfaces and typed Japan fixtures.

## Page and data flow

`/plan` owns the wizard state and submission lifecycle. It composes a typed request from form data,
calls the API facade, polls a typed job status, and renders report fields. Mock reports contain
backend-shaped money/provenance fields. Components render those fields; they must not add, sum,
convert, or invent money, rewards, points, fees, or percentages.

The current page also contains F5/F5.1 editable-itinerary behavior: pure add/replace operations,
single-flight request sequencing, recompute/prose refresh calls, section freshness, and attached
payment guidance. Any future extraction of result rendering must preserve those seams; do not copy an
older plan-page extraction without revalidating this behavior.

## Styling and visual contract

- Semantic Tailwind tokens are defined in `frontend/src/themes/base.css`, `natural.css`,
  `singapore.css`, and `japan.css` and bridged through `globals.css`.
- The approved current direction is Japan-first neo-brutalist structure with calm editorial
  hierarchy and restrained retrofuturist details. `frontend/design/CONTRACT.md` is the reconciled
  contract; the 2026-08-09 Japan foundation spec remains the design input, not proof that every
  planned J-phase item shipped.
- `frontend/ANTI_GENERIC.md` names product-specific primitives such as `DecisionLedger`,
  `MoneyText`, `ProvenanceBand`, and `WhyThis`. Use them to preserve financial readability and
  provenance.
- Fonts and theme names in stale handoff docs are historical unless corroborated by source.

## Contract and trust rules

The frontend contract is generated/derived from `contract/openapi.json`; generated files live under
`frontend/src/lib/api/generated/`, with the hand-maintained facade in `frontend/src/lib/api/index.ts`.
MSW mirrors the HTTP protocol for offline tests.

Every non-trivial displayed fact retains its provenance/trust state. `MoneyText` is the rendering
boundary for currency fields. The UI may format a backend-provided value for display, but may not
perform financial arithmetic.

## Testing and evidence

The repository has Vitest unit/contract/contrast tests and Playwright F1–F5.1 specs. The configured
Playwright projects cover Chromium at 1440, mobile 390, tablet 768, and reduced motion. The old
F1.5 screenshot path is stale; the current baseline attempt and its exact failure/coverage are
recorded in [the current visual-baseline README](design/refs/current/README.md).

Run frontend checks from `frontend/` or through the Makefile targets. Treat a failed build or gate
as evidence about the current environment/tree, not as permission to rewrite product code during a
documentation handoff.

## Known deviations and seams

1. The legacy handover still describes “no frontend code”; it is now bannered as historical.
2. The mock corpus is still Singapore/India-shaped while the visual shell and explicit proof
   surfaces are Japan-oriented.
3. The current results rendering remains integrated with `/plan`; no documentation task should
   introduce a speculative extraction or change the editable-itinerary boundary.
