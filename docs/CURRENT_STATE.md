# Current state

**Evidence date:** 2026-10-30 (FI3 review dry-run, held-card welcome-status backend slice and PDF
real-library compatibility integrated; D1 deployment foundation was added 2026-10-21, see
`docs/DEPLOYMENT.md` and `reports/d1_deployment_foundation.md`)
**Latest integration (2026-10-30):** `codex/integrate-fi3-welcome-pdf`, based on `origin/main`
`6f0859b`, merges three branches with real merge commits: FI3 (`codex/fi3-review-dry-run`),
spec 18 Case A welcome-status (`codex/held-card-welcome-status`) and the PDF compatibility closure
(`codex/pdf-compatibility-closure`). Combined verification, the one defect found, and the
revision each check ran on are in `reports/integration_fi3_welcome_pdf.md`. The paragraph below
describes the earlier 2026-10-21 integration and was not re-verified by this one.
**Earlier repository state (2026-10-21):** local, unpublished integration branch `codex/integrate-fi0-g3-5-g4`, based on
`eccb198` (CP2/Japan merged through PR #13). It merges, with real non-fast-forward merges, the G3.5
Gondola contract closure (stacked on the implemented G3.4 and CP3 work), the G4 Open-Meteo
weather-context adapter, and the FI0 offline financial-ingestion foundation. Combined verification,
review dispositions and gate evidence are in `reports/integration_fi0_g3_5_g4.md`; per-milestone
evidence is in `reports/cp3_interview_assistance.md`, `reports/g3_4_confirmed_brief_gateway.md`,
`reports/g3_5_gondola_contract_closure.md`, `reports/g4_open_meteo_weather_context.md` and
`reports/fi0_financial_ingestion_foundation.md`. The earlier baseline is in
`reports/cp2_japan_documentation_integration.md`.

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
- A3 persistent wallet product wiring is complete on the isolated A3 branch: authenticated wallet
  API/UI, seeded card-product selection, owner-scoped versioned mutations with durable idempotency,
  privacy export/delete, and session-snapshotted wallet projection. Known limitations remain
  documented in `reports/a3_wallet_product_wiring.md` (mobile header navigation, running-session
  wallet reconciliation, missing KB card-to-loyalty mapping, and the internal non-CAS wrapper).
- The frontend's mock environment is the default. The browser API facade and MSW handlers supply
  deterministic fixture responses; live mode is an explicit environment choice.
- CP3 adds the required adaptive interview checkpoint, optional free-text interpretation,
  validated answer proposals, contradiction review and honest degraded assistance. Durable
  SQLite CAS reservations cap the interview at two LLM calls across retries, concurrent clients,
  backtracking and reopen. The hosted role remains disabled until an eligible zero-spend/local
  configuration is explicitly confirmed; development and acceptance use offline fixtures.
  Acceptance: backend **1326 passed, 1 skipped**, strict mypy **152 files**, frontend Vitest
  **163 passed**, complete browser suite **458 passed, 74 existing skips**, clean-tree `make gate` passed.

- G3.4 confirmed-brief integration arrived via the stacked G3.5 branch; its acceptance was closed on 2026-10-16
  after the integrated tree passed the exact-tree gate. Confirmed sessions validate canonical facts before bounded inventory search,
  use sample-only runtime construction with explicit price-scope/freshness checks, preserve
  admitted costs through typed edits, and bind jobs/interactions to the authenticated owner and
  planning session. The contract, generated client, MSW fixture, and resumable results UI are
  synchronized. Live Gondola remains disabled and its structured responses remain unverified;
  no provider credentials or paid services were used. See
  `reports/g3_4_confirmed_brief_gateway.md`.
- **FI3 financial review and activation dry-run** is an offline local operator tool
  (`python -m ingestion.review_server`; schema version 4). A named curator inspects an FI2
  proposal with its snapshot, exact evidence spans and findings, then approves, rejects, edits
  through FI2 validation or requests re-verification. Decisions are durable across SQLite
  reopen; approved decisions become a deterministic, content-addressed bundle that a read-only
  dry-run checks against an in-memory knowledge base. **There is no KB apply**, no live source,
  and nothing is authorized for activation; it is not traveler-facing and adds nothing to the
  product OpenAPI or frontend. The loopback browser app was run in a real browser, which found
  and fixed a login-blocking `Referrer-Policy` defect. See `reports/fi3_review_activation_dry_run.md`.
- **Held-card welcome-window status (spec 18 Case A)** is a backend-only authenticated route,
  `POST /account/wallet/{entry_id}/welcome-status`, owner-scoped (a foreign id reads as missing)
  and computed from the server's stored trip revision. The shipped offer catalog is **empty**, so
  it reports `unknown` / `NO_APPROVED_OFFER` until humans add verified offers. A points bonus is
  never valued without a verified card-to-points-program mapping, which does not exist. Unknown
  `opened_on` or prior spend stays unknown; spend is only ever "conditional". No traveler UI, no
  Case B, and no change to the optimizer or any total. See `reports/held_card_welcome_status.md`.
- **PDF parsing compatibility** with the real `pdfplumber` is demonstrated for benign generated
  PDFs through the production isolation path; the missing-dependency simulation is deterministic.
  The real-library module is skipped by `make gate` (the gate interpreter lacks the optional
  dependency), so it must be run explicitly. The worker is a process boundary, **not** an OS
  sandbox. See `reports/pdf_real_library_compatibility.md`.

## Gateway and provider status

| Surface | Current evidence | Status |
|---|---|---|
| Travel gateway contracts and `SampleAdapter` | `backend/gateway/travel/`, G1 report | shipped, offline/default |
| Reference importers and catalog gateway | `backend/gateway/reference/`, `catalog/`, G2 report | shipped, offline |
| Gondola adapter and MCP transport | `backend/gateway/travel/adapters/gondola/`, PR #12, G3.1/G3.2 reports | code and fixtures shipped; registry-disabled by default; `/plan` not wired |
| Tripadvisor Terra | `backend/gateway/places/adapters/tripadvisor/`, I8A.2.1 report | fixture path shipped; live transport disabled and activation pending |
| Open-Meteo weather context | `backend/gateway/weather/`, G4 report | third-party `community_mcp`; disabled by default; contextual evidence only; not wired to `/plan`, OpenAPI or the UI; one bounded anonymous forecast probe, sanitized capture committed |
| Financial ingestion | `backend/ingestion/`, FI0 report, `docs/superpowers/plans/2026-10-07-robust-financial-ingestion.md` | FI0 offline contracts, policy, SQLite queue and audit only; no crawler, network, scheduler or extraction LLM; FI1 not started |

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
- The conversational route renders personalized server questions and acknowledgements, previews
  interpreted candidates before explicit answer saving, and blocks planning on unresolved
  contradictions. Typed controls remain available when assistance fails or reaches its limit.
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

CP2/Japan is merged on GitHub. CP3, G3.4 and G3.5 (one stacked line), G4 and FI0 were developed in their own local
worktrees from that merge and are combined only on the local integration branch. All source branches and worktrees,
and the primary checkout's untracked files, remain preserved. FI3, the welcome-status slice and
the PDF compatibility closure were developed in their own worktrees from `origin/main` `6f0859b` and combined
on `codex/integrate-fi3-welcome-pdf`; those source branches and worktrees are preserved too.

## What is explicitly not claimed

- FI4/FI5 (applying approved financial facts to the knowledge base) are not started. FI3 only
  dry-runs; no verified financial data was added and no seed or golden changed.
- Spec 18 is not complete: Case A has a backend route only (no traveler UI, no approved offer
  data, no valued points bonus) and Case B (new-card suggestions) is untouched.
- PDF results are not exploit-resistance or sandbox results, and do not cover encrypted,
  scanned, CJK/RTL or real issuer PDFs, or platforms other than macOS arm64.
- CP4, FI1 and crawler work are not included in G3.4, G3.5, G4 or FI0. No credential, live
  provider/MCP/LLM call, booking, payment or transfer execution was activated during development.
- A report saying “complete” for an older milestone does not mean its later live activation or
  integration follow-up is complete.
- The untracked plans and image directory are not canonical until deliberately committed.
