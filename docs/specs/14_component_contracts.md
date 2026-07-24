# 14 — Product Component Contracts

Components in `components/product/`, composed from themed shadcn primitives. Contract rules (Tier F): props are typed against **generated API types** (12 §1) — a component receiving report data takes the report sub-object, never re-shaped ad-hoc types; components consume **semantic tokens only** (11 §2); every component renders a sensible empty/loading/error variant; all are exercised on the kitchen-sink route with fixture data.

Inventory (name → key props → notes):

**Wizard**
- `WizardShell` — `{steps, current, onNavigate}` — progress rail, focus management, live region (13 §2).
- `StepTrip / StepStyleBudget / StepInterests / StepCardsPoints / StepReview` — each `{value, onChange, errors}` with per-step Zod schema colocated.
- `CardSelectGrid` — `{catalog: CardSummary[], selected: string[], onToggle}` — abstract gradient tiles, keyboard listbox, "unknown card" affordance.
- `PointsBalanceInput` — `{cards, balances, onChange}` — appears only for selected transferable currencies.
- `BudgetSlider` — `{minor, currency, onChange}` — formatted via `formatMoney`, tabular-nums.
- `TagPicker` — `{vocab, selected, max?, onToggle}` — used for interests & dietary.
- `UnresolvedQuestions` — `{questions: string[], answers, onChange}` — the needs_clarification variant block.

**Loading**
- `StageTracker` — `{stageIndex, stagesTotal, stageLabels, indeterminate}` — real-progress rule baked in: no props accept a synthetic percentage.
- `QuipRotator` — `{quips: Quip[], intervalMs=6000}` — Doc 15 filtering applied by the hook that feeds it, not inside.
- `ResultsSkeleton` — `{}` — mirrors results layout exactly (dimension-stable, 13 §6).

**Results**
- `VerdictHeader` — `{totals, confidence, destination, days}` — three-number strip, `CountUp` children, confetti trigger logic (threshold prop, default 300bp).
- `CountUp` — `{valueMinor|value, currency?, durationMs=800}` — animates to the exact prop value; reduced-motion renders final instantly; never formats independently of `formatMoney`.
- `ItineraryTimeline` — `{days, quality}` — day cards + drawn line; renders `FallbackBadge` when quality="fallback".
- `TripMap` — `{days, hotelArea, flight}` — lazy; static-image fallback prop for no-WebGL.
- `PaymentStrategyCard` — `{assignment: LineAssignment}` — card tile, offers, benefit rows, `RunnerUpDisclosure`, explanation atoms list.
- `RunnerUpDisclosure` — `{runnerUp}` — collapsed by default; renders delta from fields only.
- `TransferPlanPanel` — `{advice: TransferAdvice}` — REDEEM/PAY_CASH/NO_DATA variants; `VerifyCheckpoint` gating visual lock of steps; step arrows with ratio/time chips; leftover note.
- `VerifyCheckpoint` — `{checked, onChange, programUrl}` — warning-styled, checkbox-gated (13 §4.5).
- `BookingChecklist` — `{steps}` — in-memory check state, progress ring, completion confetti (single).
- `TrustChip` — `{kind: "verified"|"warning", date?, note?}` — the only way provenance renders (no bespoke variants).
- `EvidenceBadge` (G1+) — `{evidence: EvidenceSummary}` from generated types — renders live/cached/estimated/stale/verify-required plus an unobtrusive experimental/source-method label; never promotes `community_mcp` or `scraper_wrapper` evidence to a verified first-party source.
- `ConfidenceBadge` — `{score}` — thresholds per 13 §5.
- `AssumptionsFooter` — `{assumptions, disclaimers, minVerifiedDate}` — disclaimers rendered verbatim.

**Shared**
- `ThemeProvider` — sets `.theme-<destination>` on `<html>` from the plan's destination; default singapore.
- `FrostedPanel`, `SectionHeading`, `MoneyText` (`{minor, currency, emphasis?}` — the sole money formatter), `EmptyState`, `ErrorCard` (`{taxonomyKey, traceId?}` — one component for every 12 §4 row).

Anything not listed is Tier V, but new components touching report data must follow the props-from-generated-types rule and be added to the kitchen-sink route in the same PR.
