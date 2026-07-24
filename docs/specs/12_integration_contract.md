# 12 — Frontend–Backend Integration Contract

**This is the highest-stakes frontend doc.** Prior projects failed at integration; this contract makes drift structurally difficult rather than relying on discipline. Read together with backend Docs 03 §7–§8.

## 1. Single source of truth

The FastAPI OpenAPI schema (`GET /openapi.json`) is the only contract. Rules (Tier F):

1. Backend Pydantic models generate the schema; the schema generates the frontend types/client; **no hand-written request/response types anywhere in the frontend.**
2. Codegen runs via `npm run gen:api` → `@hey-api/openapi-ts` reading `contract/openapi.json` (a committed snapshot, refreshed by `npm run gen:api:pull` from a running backend). CI regenerates from the committed snapshot and fails on diff vs. committed generated code — stale codegen cannot merge.
3. The committed snapshot is versioned: backend changes that alter the schema must update the snapshot in the same PR (monorepo) — this is the moment drift becomes a visible diff instead of a runtime surprise.
4. Zod schemas for every response body live in `lib/api/schemas.ts`, generated where possible (hey-api Zod plugin) and extended by hand **only** for cross-field rules (§4). Every response is `parse`d at the boundary; a Zod failure is rendered as a distinct "contract error" state (not a generic error) and logged with the mismatch path — this is the drift alarm.

## 2. Transport protocol: async job + polling

The plan pipeline takes 30–60s; a single blocking POST is fragile (proxy timeouts, no progress). **Backend amendment (log as DEVIATIONS `SCOPE+` against Doc 03 §8, approved here):** wrap the pipeline in a job API. Internal pipeline unchanged.

```
POST /plan            body: TripIntakeRequest        → 202 { job_id }
GET  /plan/{job_id}   → PlanJobStatus (poll)
```

```typescript
PlanJobStatus = {
  job_id: string
  status: "queued" | "running" | "needs_clarification" | "complete" | "failed"
  stage:  "intake" | "itinerary" | "costing" | "optimizing" | "transfer" | "critic" | "explaining" | null
  stage_index: number | null        // 1-based, of stages_total
  stages_total: number
  unresolved?: string[]             // when needs_clarification
  report?: FinalReport              // when complete
  error?: { code: string, message: string, trace_id: string }  // when failed
}
```

Frontend polling (Tier F): TanStack Query, `refetchInterval: 1500`, stop on terminal status (`complete | failed | needs_clarification`); client-side ceiling 120s → render timeout state with `trace_id` if available. `stage` drives the loading narration (Doc 13 §3) — the progress UI is **bound to real pipeline stages, never a fake timer**. If `stage` is null while running, show indeterminate shimmer + quips only. No exponential backoff needed at this scale; do not hammer faster than 1s.

## 3. FinalReport consumption rules

The generated `FinalReport` type mirrors backend 03 §7 (plus `transfer_advice` from 07 §6). Frontend rules (Tier F):

1. **Render-only money.** The frontend never computes money/points values — no summing line items, no deriving savings %, no currency conversion. Every displayed number is a field from the report. Count-up animations animate *to* the field value. (Exactly one exception: formatting minor units → display string via one shared `formatMoney(minor, currency)` util.)
2. **Provenance is load-bearing UI.** `provenance_warnings[]`, `confidence`, `assumptions[]`, and per-line `needs_verification` flags render as the trust-badge system (Doc 13 §5). Suppressing them is a spec violation, not a design choice.
3. **Partial-quality flags:** `itinerary_quality: "fallback"` → calm "best-effort itinerary" badge on the itinerary section; missing `transfer_advice` → render the one-line "share balances to unlock" note; empty sections render honest empty states, never invented content.
4. The report footer disclaimers (backend 03 §9) render verbatim from the payload — the frontend does not author compliance copy.

## 4. Error taxonomy → UI mapping (exhaustive; each row is an MSW fixture + test)

| Condition | Detection | UI |
|---|---|---|
| Validation reject | 422 on POST /plan | Inline field errors mapped by pointer path; wizard stays on step |
| Needs clarification | status=needs_clarification | Return to wizard step 1 variant showing `unresolved[]` as targeted questions; resubmit merges answers |
| Pipeline failure | status=failed | Friendly failure card + `trace_id` shown small + retry CTA (re-POST) |
| Contract drift | Zod parse failure | "We hit a version mismatch" state + log; never render unparsed data |
| Timeout | 120s ceiling | Timeout card + retry; job may still complete — retry first re-GETs the same job_id |
| Network | fetch rejection | Offline banner + auto-retry via TanStack defaults (max 3, then failure card) |
| Backend down | POST /plan network fail | Landing renders fully (static); wizard submit shows retryable failure |

Cross-field Zod refinements (hand-written, tested): if `status=complete` then `report` present; if `needs_clarification` then `unresolved` non-empty; totals fields all present when report present.

## 5. CORS & environments

Backend: `CORSMiddleware` with explicit origins `http://localhost:3000` (dev) and the deployed frontend origin (env `FRONTEND_ORIGIN`); methods `GET, POST, OPTIONS`; headers `Content-Type`; no credentials (no cookies in MVP — stateless jobs). Frontend: `NEXT_PUBLIC_API_BASE_URL` is the only backend-location config; `NEXT_PUBLIC_API_MODE=mock|live` selects MSW vs network. The env matrix (dev/preview/prod × mock/live) is a table in `frontend/README` — six cells, all must be stated, none implied.

## 6. MSW as the contract's second implementation

`src/mocks/handlers.ts` implements the full protocol: POST → job id; GET advances a scripted stage sequence with realistic timing (configurable speed multiplier for tests); terminal fixtures for **every** row in §4's table plus: happy path, fallback-itinerary report, report with provenance warnings, report with `transfer_advice` REDEEM, report with PAY_CASH, report with NO_DATA. Fixture FinalReports are hand-maintained JSON validated against the Zod schemas in a test — if the schema moves, fixtures fail loudly. Frontend Milestones F2–F3 run entirely on MSW.

## 7. Contract tests (CI, both sides)

- Frontend: fixtures↔Zod validation; §4 mapping tests (each fixture renders its state); a "no orphan numbers" test on the results page — every currency/miles number in the DOM must appear in the fixture JSON (mirror of the backend's groundedness gate).
- Backend: schemathesis fuzz against `/openapi.json` (status-code + schema conformance on /plan endpoints); a golden end-to-end: demo trip → poll → response validates against the same committed snapshot the frontend generated from.
- The two sides never test against each other directly in CI; they test against the shared snapshot. One manual live run happens at Gate F4.

## 8. Runbook: changing the contract (goes in frontend/README verbatim)

1. Change backend Pydantic models → run backend, `npm run gen:api:pull` → snapshot diff appears.
2. `npm run gen:api` → regenerate client/types/Zod.
3. Fix type errors (they are the impact analysis), update MSW fixtures (tests force this), update §4 table if taxonomy changed.
4. One PR contains: model change + snapshot + generated code + fixtures + UI updates. **Split PRs are the drift vector — forbidden (Tier F).**

## 9. Target-platform quote/trust extension (post-F4; not part of the current generated contract)

Specs 08/09/16 add live/cached external evidence after the Kernel MVP. Do not preemptively change the F1–F4 OpenAPI schema. In G1+, any public quote summary must carry display-ready values plus:

```typescript
EvidenceStatus = "live" | "cached" | "estimated" | "stale" | "verify_required"

EvidenceSummary = {
  provider_id: string
  artifact_kind: "current_quote" | "price_observation" | "award_quote" | "sample"
  source_method: "sample" | "official_api" | "provider_mcp" | "community_mcp" | "scraper_wrapper" | "open_data"
  stability: "stable" | "experimental"
  retrieved_at: string
  expires_at?: string
  status: EvidenceStatus
  completeness: "complete" | "taxes_uncertain" | "fees_uncertain" | "partial"
  needs_verification: boolean
  attribution?: string
  deep_link_url?: string
  notes: string[]
}
```

Rules:

1. These fields are generated from backend models; the frontend does not infer freshness.
2. `estimated` includes all Kernel MVP sample inventory and sandbox prices.
3. A stale/partial quote cannot be styled as a normal live price.
4. Student-profile experimental/community/scraper-wrapper evidence is visibly labeled and defaults to `needs_verification=true`; the UI never implies commercial endorsement.
5. `price_observation` is never styled or worded as a current/bookable flight. `sample`/Duffel test evidence is always estimated. Cash `current_quote` and `award_quote` remain distinct.
6. Provider raw payloads, credentials, internal errors, and detailed terms/licence metadata do not cross the boundary.
7. New gateway stages must extend the job-stage enum and loading copy in the same contract PR; the UI still binds only to real stages.
8. Every new state receives an MSW fixture, Zod validation, component variant, screenshot, and accessibility test.
9. F4's "live integration run" remains a real transport run against the sample-data backend. The first provider smoke test belongs to G3/G4 and is never normal CI; anonymous/free providers do not require credentials.
