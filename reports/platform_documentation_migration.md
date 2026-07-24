# Platform documentation migration

**Date:** 2026-07-24
**Status:** complete
**Change type:** documentation and product-scope clarification only

## Outcome

The repository now describes one coherent product at two different maturity levels:

1. **Kernel MVP (current implementation):** deterministic rewards, fees, offers, and transfer logic operating on sample trip inventory; four fixed LLM call sites; no request-time provider access.
2. **Unified travel rewards platform (target):** a bounded orchestrator coordinates flight, hotel, award, card/offer, and itinerary workflows. Live inventory enters only through an allowlisted Data Gateway and is normalized before reaching the deterministic kernel.

The target adds live discovery without weakening the existing rules that LLMs do not perform money math, financial knowledge requires provenance and human approval, and the product never autonomously books travel or transfers points.

## Canonical documents added

- `docs/specs/08_product_vision.md` — target user promise, capabilities, phases, evidence states, non-goals, and success criteria.
- `docs/specs/09_target_platform_architecture.md` — component boundaries, workflow design, orchestration, storage, reliability, security, testing, and post-F4 milestones.
- `docs/specs/16_data_gateway_and_adapters.md` — normalized quote contracts, adapter protocol, provider registry, activation checklist, freshness, caching, budgets, error handling, and the G1 gate.

## Existing documents revised

- `AGENTS.md` and `CLAUDE.md` now distinguish permanent invariants from Kernel-MVP-only constraints and remain byte-identical.
- `docs/ARCHITECTURE.md` is the concise orientation for the target platform and current kernel.
- Specs 00, 01, 03, 05, 06, 07, 10, and 12 now use explicit phase boundaries and link to the new canonical specifications.
- `DEVIATIONS.md` records the human-authorized `SCOPE+` decision and why it does not change any frozen optimizer behavior.

## Code impact

No production code needed to change for this migration. The current code is the deterministic kernel described by the Kernel MVP, and changing it now would pull post-F4 work into the wrong milestone.

Code changes are required later, in this order:

1. **G1:** add normalized quote/evidence models, a provider registry, Data Gateway interfaces, and a `SampleAdapter`.
2. **G2:** add open/reference importers such as FX, airport, and licensed POI data.
3. **G3:** add authorized cash flight/hotel adapters one at a time.
4. **G4:** add an authorized award-search adapter and connect transfer recommendations to observed award evidence.

Any API contract change must update the OpenAPI snapshot, generated frontend client, mock fixtures, and UI in the same change.

## Validation

- Canonical agent briefs are byte-identical.
- All 17 specification files are present.
- Local Markdown links resolve across the canonical documents.
- Backend tests: **20 passed**.
- Strict type check: **passed for 13 source files**.
- Ruff was not installed in the existing virtual environment, so that optional lint check was not run.

## Decisions intentionally deferred

- No specific commercial provider is approved by these documents.
- No credentials, paid plan, affiliate agreement, or scraping permission is assumed.
- MCP is an optional transport behind an adapter, not a substitute for provider authorization or a mandatory architecture choice.
- Provider-specific work begins only after access, terms, caching rights, costs, and failure behavior are reviewed through the activation checklist in spec 16.
