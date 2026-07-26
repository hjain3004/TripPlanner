# TripPlanner F2 — continuation prompt for opencode

Copy everything below this line into opencode. F1 is complete and gate-verified
(`make gate-f1` passes: token-lint 0/12 violations, 68/68 real WCAG contrast
assertions via culori, typecheck clean, production build clean, 89/92 Playwright
tests passed across 4 projects — the 3 skips are intentional, axe runs once by
design). You are starting F2: contract-first types, the intake wizard, MSW.

This is a smaller, denser milestone than F1 but with a sharper failure mode: it
crosses the backend/frontend boundary, and this repo has a hard rule that
schema+codegen+fixtures+UI ship in **one PR, never split** (spec 12 §8). Read
carefully before writing code — the sequencing matters more than usual here.

## 1. Read first, in order

1. `AGENTS.md`, `DEVIATIONS.md` (skim for context — you don't need to re-decide
   anything already logged, including the recent F1 gate-rigor patch rows).
2. `reports/frontend_F1.md` — what F1 actually shipped (16 shadcn primitives, 7
   product wrappers, the token/motion system) so you compose against real
   components, not re-invent them.
3. `frontend/design/CONTRACT.md` — still the frozen visual contract. F2 adds forms
   and data flow, not new visual decisions. Wizard steps use existing primitives
   (Input, Select, Label, etc. from F1) styled per the existing tokens.
4. **`docs/specs/12_integration_contract.md` — read this one fully, twice.** It is
   the actual spec for everything you're building. This prompt summarizes it with
   checkpoints; the spec is the literal source of truth for field names, the error
   taxonomy table, and the MSW fixture list. Do not paraphrase from memory once
   you've read it — re-open it when writing the Zod schemas and fixtures.
5. `docs/specs/10_frontend_build_plan.md` §5's F2 gate criteria.
6. `frontend/FRONTEND_HANDOVER.md` §11 "F2 — contract and intake" for the wizard's
   product intent (background only — spec 12 wins on anything mechanical).

## 2. The repo-boundary rule that matters most here

`backend/core/` never imports from `agents/` or `api/`, and **nothing crosses
`backend/` ↔ `frontend/` except `contract/openapi.json`.** The async job wrapper
(step 3 below) is a thin HTTP layer added in `backend/api/main.py` around the
*existing* synchronous pipeline call — it does **not** restructure
`backend/core/` or `backend/agents/`. The Kernel MVP pipeline itself (the four
LLM call sites, the deterministic optimizer, the golden-test behavior) is
Tier-F-frozen and untouched by this milestone. If you find yourself editing
`backend/core/optimizer/` or changing a golden test's expected value to make F2
work, stop — that's a sign you've misunderstood the task.

## 3. Sequence — do these in order, not in parallel

### 3.1 Log the backend amendment first

Spec 12 §2 states plainly: *"Backend amendment (log as DEVIATIONS `SCOPE+`
against Doc 03 §8, approved here): wrap the pipeline in a job API."* Add that
`DEVIATIONS.md` row **before** writing the backend code — it's pre-approved by
the spec, but the log entry is what makes it a decision instead of an
undocumented change. Include: the two new Pydantic models (`TripIntakeRequest`,
`PlanJobStatus` — copy the field names verbatim from spec 12 §2's TypeScript
sketch), and your job-store choice (an in-memory dict keyed by `job_id` is fine
for this milestone — no persistence requirement exists yet; log it as Tier C).

### 3.2 Backend: wrap the pipeline

`POST /plan` becomes `202 { job_id }` instead of a blocking response;
`GET /plan/{job_id}` returns `PlanJobStatus` for polling. The `stage` field must
reflect **real pipeline stages** (`intake | itinerary | costing | optimizing |
transfer | critic | explaining`), not a synthetic timer — this is Tier F (spec
12 §2: "the progress UI is bound to real pipeline stages, never a fake timer").
Existing backend tests for the synchronous behavior need updating to match the
new async shape — do not leave the old tests red or delete them without
replacement coverage.

**Checkpoint:** run the full backend regression (`make gate-m1 gate-m1b gate-m2
gate-m3`) — it must stay green. This milestone must not touch Kernel MVP Tier-F
behavior or golden numbers.

### 3.3 Commit the OpenAPI snapshot

`contract/openapi.json` is a **committed snapshot** (spec 12 §1.2), refreshed via
`npm run gen:api:pull` from a running backend. Generate it now, against your
updated `/plan` and `/plan/{job_id}` endpoints.

### 3.4 Codegen

`npm run gen:api` → `@hey-api/openapi-ts` reads the committed snapshot, generates
the client/types into `frontend/src/lib/api/`. **No hand-written request/response
types anywhere in the frontend** — if TypeScript can't find a generated type you
need, the schema is wrong, not the frontend.

### 3.5 Zod boundary schemas

`frontend/src/lib/api/schemas.ts` — one Zod schema per response body, generated
where the hey-api Zod plugin covers it, hand-extended **only** for the
cross-field rules spec 12 §4 lists explicitly (if `status=complete` then
`report` present; if `needs_clarification` then `unresolved` non-empty; totals
fields present when report present). Every response gets `.parse()`'d at the
boundary. A Zod failure renders a **distinct "contract error" state** (spec 12
§4's "Contract drift" row) — not a generic error screen, and it logs the
mismatch path. This is the drift alarm the whole architecture depends on; don't
swallow it into a catch-all.

### 3.6 MSW handlers — the full protocol, not just the happy path

`frontend/src/mocks/handlers.ts`: `POST /plan` returns a job id; `GET
/plan/{job_id}` advances a scripted stage sequence with realistic timing
(configurable speed multiplier so tests don't wait 30s). Build **every** fixture
spec 12 §4's error-taxonomy table requires (validation reject, needs
clarification, pipeline failure, contract drift, timeout, network, backend down)
**plus** every terminal-state fixture in §6: happy path, fallback-itinerary
report, report with provenance warnings, report with `transfer_advice` REDEEM,
PAY_CASH, and NO_DATA. Fixture `FinalReport` JSON is hand-maintained and
validated against the Zod schemas in a test — if the schema moves, fixtures must
fail loudly, not silently drift.

### 3.7 The intake wizard

Five-step wizard per the handover's product research (trip basics → cards/points
wallet → preferences → review → submit — confirm exact steps against
`TripIntakeRequest`'s actual generated fields, which are the source of truth,
not this prompt's guess). Build with F1's existing primitives
(`components/ui/`, composed — do not structurally edit them). TanStack Query
drives polling: `refetchInterval: 1500`, stop on terminal status (`complete |
failed | needs_clarification`), client-side 120s ceiling → timeout state with
`trace_id` if available. `needs_clarification` returns the user to step 1 with
`unresolved[]` rendered as targeted questions; resubmission **merges** answers,
it doesn't restart the wizard from empty.

Accessibility (this is gated, not optional): focus moves to each step's heading
on step change; ARIA live-region announcements fire on step transitions and on
error states; nothing here is decorative-only motion — `WhyThis`-style
disclosure patterns from F1 apply if the wizard has any expandable help text.

### 3.8 Error taxonomy → UI mapping

Implement all seven rows of spec 12 §4's table exactly — each row is both an MSW
fixture (3.6) and a distinct UI state. Do not collapse multiple rows into one
generic "something went wrong" screen; the whole point of this table is that
each failure mode gets a specific, honest treatment (e.g., "Backend down" must
still render the static landing page — the wizard submit fails, not the whole
app).

## 4. Contract tests (spec 12 §7) — write these, they're the actual gate

- Fixtures ↔ Zod validation (every MSW fixture parses clean against its schema).
- §4 mapping tests: each fixture, when served, renders its specified UI state.
- **"No orphan numbers" test on the results page** — every currency/miles number
  in the rendered DOM must appear in the fixture JSON it was rendered from. This
  is the frontend mirror of the backend's groundedness gate (Tier-F non-negotiable
  #1: the frontend never computes money). If you find yourself writing `+`, `*`,
  or any arithmetic on a money/points value anywhere in `src/`, stop — render the
  field the backend already computed, don't derive a new one.

## 5. Gate F2 (spec 10 §5)

Playwright: full wizard happy path + a `needs_clarification` loop, driven against
MSW. A11y checks: focus moves to step heading, ARIA announcements fire, axe
clean. Contract tests from §4 above all green. Extend `frontend/e2e/` and the
`make gate-f2`/`fe-*` target pattern established in the F1 gate-rigor patch —
match that Makefile style (root `gate-f2` → `frontend` `fe-*` targets), don't
invent a different convention.

## 6. Dependency budget — F2 unlocks these (forbidden at F1, required now)

`@tanstack/react-query`, `@hey-api/openapi-ts`, `zod`, `msw`. Still forbidden:
`gsap`, `lenis`, `maplibre-gl`, `canvas-confetti` (F3/F4), `storybook`,
`next-themes`, `three`, `framer-motion`, `tailwindcss-animate`.

## 7. The one-PR rule (spec 12 §8) — do not violate this

*"One PR contains: model change + snapshot + generated code + fixtures + UI
updates. Split PRs are the drift vector — forbidden (Tier F)."* If you're tracking
this work across multiple commits, that's fine, but they land as one PR/branch
merge, not split across separate reviewable units. Re-read this section before
opening any PR.

## 8. Skills

`ecc:api-design` and `ecc:typescript-reviewer` for the contract/codegen layer.
`ecc:frontend-a11y` and `ecc:react-patterns` for the wizard (focus management,
ARIA). `superpowers:systematic-debugging` if a Zod schema mismatch or codegen
output doesn't match what you expect — trace it to the actual OpenAPI snapshot
rather than hand-patching a generated file (generated files should never be
hand-edited; if one's wrong, the schema or the codegen config is wrong).
`superpowers:verification-before-completion` before reporting F2 done — same
standard as the F1 gate patch: paste real command output, don't summarize.

## 9. Explicitly out of scope for F2

No results page content beyond what's needed to prove the "no orphan numbers"
test (F3 owns the full results/loading experience — Doc 13). No GSAP, Lenis, or
MapLibre. No live provider calls — MSW only, per spec 12 §6 ("Frontend
Milestones F2–F3 run entirely on MSW"). No dark mode. No changes to Kernel MVP
Tier-F pipeline behavior or golden numbers in `backend/core/`.

## 10. What's next

Once Gate F2 passes — verified by pasted command output, not a summary — stop and
report back. F3 (loading experience, results page, provenance rendering, spec
13/14/15) and F4 (performance, one live integration run) get their own prompts
after F2's actual shape (generated types, wizard field names, fixture structure)
exists to ground them accurately, the same way this prompt could only be written
precisely after F1 actually landed.
