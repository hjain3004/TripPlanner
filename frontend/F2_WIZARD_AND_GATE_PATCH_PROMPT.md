# TripPlanner F2 — wizard rebuild + gate-rigor patch for opencode

Copy everything below this line into opencode. This is a follow-up to the F2 work
you already completed. The backend async job wrapper is solid and verified (100
backend tests passing, no Tier-F regression) — don't touch
`backend/api/job_manager.py`, `backend/agents/pipeline.py`'s `on_stage` callback,
or the `TripIntakeRequest`/`PlanJobStatus` models. This patch is scoped to two
things: (1) the intake UI was built as a single-page form instead of the 5-step
wizard the product spec called for, and (2) `gate-f2` currently only runs
`lint + typecheck + build` — none of the wizard flow, accessibility, or contract
checks it was supposed to run actually exist yet.

## 0. The one fact that changes how you build the wizard

`TripIntakeRequest` (check `backend/agents/models.py` yourself to confirm) is:

```python
class TripIntakeRequest(BaseModel):
    raw_request: str
    wallet: UserWallet | None = None
```

`UserWallet` is genuinely structured (`card_ids: list[str]`,
`points_balances: dict[str, int]`) — but everything else (origin, destination,
dates, budget style, interests) is **one free-text string**, because the backend
intake pipeline stage uses an LLM to parse natural language into a structured
trip spec internally. This means: **the 5-step wizard's step schema is a
frontend product decision (Tier C — "frontend details not otherwise frozen" per
`docs/specs/06_implementation_protocol.md` §1), not something read off the
backend contract.** You are not missing a "real" 5-field schema somewhere — you
are building a guided-input UI that *composes* structured local state into the
one `raw_request` string the backend actually accepts, plus the one field
(`wallet`) that does map directly to real backend structure.

## 1. Read first

`DEVIATIONS.md` (specifically the F1 gate-rigor-patch rows — that patch is the
precedent for how this one should be documented: honestly, admitting what was
missing, not just describing what's new), `reports/frontend_F2.md` (what
currently exists — the Zod schemas, codegen output, MSW handler shape, and the
existing single-page `/plan` state table are all reusable), `docs/specs/12_integration_contract.md`
§2–§4 and §6 again (the error taxonomy and fixture list you're completing),
`frontend/design/CONTRACT.md` (still the frozen visual contract — new wizard
steps use existing F1 primitives, no new visual decisions).

## 2. Deliverable 1 — rebuild `/plan` as a real 5-step wizard

Step breakdown (adjust field grouping if you find a better product fit, but keep
5 steps and log any change as a Tier-C `DEVIATIONS.md` row):

1. **Trip basics** — origin, destination, travel dates/window, traveler count.
   Structured local form state; not sent to the backend as separate fields.
2. **Wallet** — card selection (`card_ids`) and points balances
   (`points_balances`). This step's state maps **directly** to the real
   `UserWallet` shape — no composition needed, send as-is.
3. **Preferences** — budget style, pace, interests. Structured local state.
4. **Review** — show the user a preview of what will actually be sent: the
   composed `raw_request` text (see below) and the wallet summary. Let them edit
   the raw text directly here before submitting — this is the escape hatch if
   the composition produces something awkward.
5. **Submit** — triggers `POST /plan`, transitions into the existing
   polling/complete/error states from the current implementation (those are
   fine as built — you're not rebuilding the post-submit states, just what
   feeds into them).

**Write one pure function**, e.g. `composeRawRequest(wizardState): string`, that
turns steps 1 and 3's structured state into the natural-language string sent as
`raw_request`. Keep it in one place (`src/lib/wizard/composeRequest.ts` or
similar), not scattered string concatenation across components — step 4 needs to
call the exact same function the submit step uses, so the preview is never
stale relative to what actually gets sent. This function assembles text from
user-entered facts; it performs **no arithmetic and computes no money/points
value** (Tier-F non-negotiable #1 still applies to this function).

**Accessibility (gated in Deliverable 3, build it now):** focus moves to each
step's heading on step change. ARIA live-region announcements fire on step
transitions and on validation errors within a step. Back/forward navigation
between steps preserves all entered state — don't reset a later step's state
when the user goes back to an earlier one.

**`needs_clarification` handling:** all wizard state (steps 1–3's structured
data, not just the composed string) must persist in one client-side state object
across a clarification round-trip. When the backend returns
`needs_clarification` with `unresolved[]`, show those as a targeted list the
user can act on — at minimum, return them to the review step (4) with the
`unresolved[]` items called out and the raw text still editable; if you can
reasonably map an unresolved item back to a specific earlier step, do so, but
the review-step fallback is acceptable. **Resubmission must merge into existing
state, never reset the wizard to empty.**

Compose with F1's existing primitives (`components/ui/` — Input, Select, Label,
etc.). Do not structurally edit them.

## 3. Deliverable 2 — the missing MSW fixtures

Spec 12 §6 requires terminal fixtures for: happy path (exists), fallback-itinerary
report, report with provenance warnings, report with `transfer_advice` REDEEM,
PAY_CASH, and NO_DATA. Check `backend/core/models.py` / `backend/agents/models.py`
for the real `FinalReport`, `TransferAdvice`, and `RedemptionPath` shapes before
writing these — don't guess field names, the Zod schemas you already generated
must validate every fixture you write. Add these alongside the existing
`fixtureHandlers` in `frontend/src/mocks/handlers.ts`.

## 4. Deliverable 3 — real Playwright wizard e2e test

New spec file (e.g. `frontend/e2e/f2-wizard.spec.ts`), registered in the existing
`frontend/e2e/playwright.config.ts` project setup (reuse the config-path lesson
from the F1 gate patch — make sure this spec actually gets picked up by whatever
command `fe-gate-shots`/`fe-e2e` ends up calling). Cover:

- Full happy path: all 5 steps → submit → polling → complete, against the MSW
  happy-path fixture, asserting the review step's preview matches what the
  fixture's request ultimately reflects.
- The `needs_clarification` loop: submit → clarification response → verify
  wizard state (wallet, prior text) is still present, not wiped → resubmit →
  complete.
- Focus moves to each step heading on transition (assert via
  `page.evaluate(() => document.activeElement)` or equivalent).
- axe accessibility check on at least the wizard's step-1 and review-step
  renders (`violations.length === 0`).

## 5. Deliverable 4 — contract tests (the ones that were skipped entirely)

- Fixtures ↔ Zod validation: every MSW fixture (existing + the ones you add in
  Deliverable 2) parses clean against `schemas.ts`.
- Spec 12 §4 mapping tests: each error-taxonomy fixture, when served, renders
  its specified UI state (contract error, timeout, failed, etc.).
- **"No orphan numbers" test** — this is the one that was missing and matters
  most. On the complete/results state, assert every currency/points number
  rendered in the DOM appears in the fixture `FinalReport` JSON it was rendered
  from. This is the frontend's actual enforcement of "never compute money" —
  without it, nothing currently catches a future accidental `total + fee`
  creeping into a component.

## 6. Deliverable 5 — wire it all into `gate-f2` for real

Both `Makefile` (root) and `frontend/Makefile` currently define `gate-f2` as
`fe-lint fe-typecheck fe-build` (frontend) / `fe-lint fe-typecheck fe-build`
(root) — neither runs anything from Deliverables 3–4. Extend the `fe-*` target
set (matching the naming pattern the F1 gate-rigor patch established:
`fe-token-lint`, `fe-contrast`, etc.) to add something like `fe-e2e-f2` (runs
the new wizard spec) and `fe-contract` (runs the fixture/Zod/orphan-numbers
tests — pick whichever test runner you used, vitest or Playwright component
tests, and be consistent with what F1's `fe-contrast` already uses). `gate-f2`
must chain all of it. Run `make gate-f2` from the **repo root** yourself and
read the real output before claiming this is done.

## 7. Deliverable 6 — honest `DEVIATIONS.md` and `reports/frontend_F2.md` correction

Same pattern as the F1 gate-rigor patch: add rows for (a) the wizard step
schema being a Tier-C frontend decision derived from `TripIntakeRequest`'s
actual (minimal) shape, with the `composeRawRequest` approach explained, (b) a
row admitting `gate-f2` initially shipped without e2e/contract checks and what
this patch added, quoting real before/after. Update `reports/frontend_F2.md`'s
gate section with pasted `make gate-f2` output showing the full check set
passing, not the original lint/typecheck/build-only claim.

## 8. Skills

`ecc:frontend-a11y` and `ecc:react-patterns` for the step-focus/ARIA work.
`ecc:api-design` if the `composeRawRequest` shape needs iteration.
`superpowers:systematic-debugging` if a fixture fails Zod validation — check the
real backend model shape, don't loosen the schema to fit a guessed fixture.
`superpowers:verification-before-completion` before reporting this done.

## 9. Definition of done

- [ ] `/plan` is a real 5-step wizard: trip basics, wallet, preferences, review,
      submit — not a single form.
- [ ] `composeRawRequest` is one pure function, used identically by the review
      step's preview and the actual submit call.
- [ ] Focus-per-step and ARIA announcements work, verified by an e2e assertion,
      not just implemented and assumed.
- [ ] `needs_clarification` preserves all prior wizard state across the
      round-trip — verified by an e2e test, not just code review.
- [ ] All 6 terminal MSW fixtures from spec 12 §6 exist and validate against Zod.
- [ ] A wizard happy-path e2e test and a clarification-loop e2e test both exist
      and pass.
- [ ] The "no orphan numbers" test exists and passes.
- [ ] `make gate-f2` from the repo root runs all of the above and passes — paste
      the real output, don't summarize.
- [ ] `DEVIATIONS.md` and `reports/frontend_F2.md` reflect what's actually true.

Do not report this complete without having run `make gate-f2` yourself and read
its real output, including the e2e and contract test sections specifically —
those are the parts that didn't exist before this patch.
