# Trip-First Travel Rewards Optimizer — Kernel MVP Implementation Pack

**Audience:** an implementing AI assistant (or developer) building this from scratch.
**Product:** "A travel planner that knows your credit cards." Given a trip (origin, destination, dates, travelers, budget, style, interests) and the user's credit cards / points balances, produce (a) a day-by-day itinerary, (b) a costed trip estimate, and (c) an optimal, explainable card/offer/payment strategy per spend category — with provenance and confidence on every claim.

**Kernel MVP corridor:** Indian user → Singapore, 3–7 days, manually curated/sample inventory, no required paid APIs, no booking, no account linking.

**Operating profile:** non-commercial student/portfolio project. Default provider spend is zero; commercial scale, SLAs, and production inventory contracts are not current goals.

**Relationship to the target prototype:** This pack builds the deterministic kernel and complete test-data experience. `08_product_vision.md` defines the unified live prototype it serves; `09_target_platform_architecture.md` and `16_data_gateway_and_adapters.md` define the post-F4 discovery layer. Those documents expand product scope without changing this pack's milestone gates or numeric contracts.

---

## Documents in this pack

| Doc | Contents | Implement in |
|---|---|---|
| `01_data_model.md` | Full SQLite schema: cards, reward rules, offers, point valuations, forex fees, POIs, sample flights/hotels, provenance. Pydantic models. Seed-data format. | Milestone 1 |
| `02_rewards_optimizer.md` | The deterministic optimizer: spend normalization, rule matching, cap-aware allocation, offer stacking, effective-cost math. Worked numeric example with expected outputs. | Milestone 1 |
| `03_orchestration_and_agents.md` | Agent graph (Coordinator over Sequential pipeline + Critic loop), TripSpec schema, all four LLM call-site contracts (prompts, input/output JSON schemas), provider-agnostic LLM interface, failure/fallback policy. | Milestone 2 |
| `04_evals_and_golden_dataset.md` | Golden-trip YAML format, pytest harness for the optimizer, LM-judge rubric for itinerary quality, regression gate policy. | Milestone 1 (optimizer tests) + Milestone 3 (judge) |
| `05_ingestion_pipeline_phase2.md` | Phase-2 only: Crawl4AI change-detection + draft-extraction + human review queue. **Do not build in MVP.** | Phase 2 |
| `06_implementation_protocol.md` | **Read first.** Decision-authority tiers (frozen vs. your call), ambiguity/deviation protocol, per-milestone self-review gates, anti-drift rules. Replaces external architect review. | Always |
| `07_transfer_pathfinder.md` | Transfer Graph & Pathfinder: schema for transfer edges/bonuses/award charts, deterministic graph search with worked example, verify-before-transfer guardrails, pipeline node 4b. | Milestone 1b |
| `08_product_vision.md` | Canonical target product, user journey, evidence states, product phases, success measures, and permanent non-goals. | Design now; implementation spans later phases |
| `09_target_platform_architecture.md` | Bounded orchestrator, domain workflows, kernel/gateway boundaries, reliability, security, and post-F4 milestones. | Design now; G1+ after F4 |
| `16_data_gateway_and_adapters.md` | Normalized live quote contracts, provider registry/activation, freshness, caching, errors, budgets, and adapter tests. | G1+ after F4 |
| `17_accounts_and_persistence.md` | **NOT YET WRITTEN.** User accounts, profiles, stored wallet entries, saved trips and revisions, auth/session approach, privacy and retention. `docs/superpowers/plans/2026-07-28-accounts-persistence.md` builds the persistence half ahead of it — a deliberate, logged process inversion (DEVIATIONS §A1). | After Kernel MVP gates |
| `18_card_acquisition_and_welcome_offers.md` | Welcome-bonus windows on held cards (Case A) and new-card offer information (Case B): acquisition offer schema, deterministic first-year math, the timing gate, and the hard non-goals around eligibility and referral economics. Depends on 17. | After 17 |

**Frontend pack:** docs `10`–`15` specify the frontend (build plan & MCP tooling, design system & theming, integration contract, pages & motion, component contracts, wit pack). Start at `10_frontend_build_plan.md`. Doc `12` amends Doc 03 §8 with the async job + polling API.

## Non-negotiable architectural principles

1. **The LLM never does money math.** All reward/fee/discount arithmetic happens in the deterministic optimizer (`02`). LLMs structure input, plan itineraries, critique, and explain. If an LLM output contains a number about rewards/costs, that number must be copied from optimizer output, never generated.
2. **The Kernel MVP runtime never crawls or calls inventory providers.** All Kernel MVP recommendations are computed from local sample/curated data; only the configured LLM may be external. The target prototype later calls profile-eligible providers only through the allowlisted gateway (`09`, `16`). The application does not directly crawl live booking/search pages; financial-rule crawling remains an offline ingestion concern with human review (`05`).
3. **Every fact has provenance.** Every row that can influence a recommendation carries `source_url`, `last_verified`, `verified_by`, `confidence`. The final report renders these. A fact with `needs_verification=true` may be used but must be flagged in output.
4. **Autonomy is deliberately low in the kernel and bounded in the target platform.** The Kernel MVP is a Level 1–2 governed workflow with exactly the graph in `03`. Future product-facing domain "agents" are typed workflows from `09`, mostly deterministic code. Do not add dynamic tool/provider creation, free-form delegation, or runtime self-modification.
5. **Seed data ships with `needs_verification: true` on every real-world card/offer fact.** Real card names in seed data are placeholders for structure; a human must verify values before any real use. Worked examples in specs use fictional cards so the math is self-contained.

## Kernel MVP stack (local/free-compatible)

- Python 3.11+, FastAPI backend, SQLite (via SQLAlchemy; schema written to be Postgres-portable), Pydantic v2 for all interfaces.
- Frontend: Next.js (thin; consumes one `POST /plan` endpoint returning the full report JSON — can be built last or replaced with a CLI for the demo).
- Orchestration: plain Python pipeline first (a 6-node graph does not need a framework); optional LangGraph wrapper only if streaming/checkpointing is wanted.
- LLM: provider-agnostic interface (`03` §5). A configured hosted API or Ollama/local profile may be used; do not assume a third-party free tier will persist. Total ≤ 4 Kernel MVP LLM call sites per plan request.
- Retrieval: POI matching in MVP is SQL + tag filtering (dataset is ~100 rows; vector search is unnecessary). Add Chroma/FAISS only if the POI corpus grows past ~1k items.

## Build order & definition of done

**Milestone 1 — the kernel (no LLM, no web, no UI).**
Implement `01` + `02` + optimizer tests from `04`.
DoD: `pytest` green on all golden trips; `python -m optimizer demo` prints the worked example from `02` §8 with exactly the expected numbers.

**Milestone 2 — the pipeline.**
Implement `03`: TripSpec intake, itinerary planner over the POI dataset, cost estimator, optimizer integration, explainer. FastAPI `POST /plan`.
DoD: end-to-end plan for the demo trip returns a complete report JSON validating against `03` §7 schema.

**Milestone 3 — quality loop.**
Critic node, LM-judge evals, provenance rendering in report, minimal Next.js UI.
DoD: judge scores ≥ threshold on golden itineraries; report shows source/last-verified/confidence per claim.

**Post-F4 prototype phases:** G1 sample gateway (`09`, `16`) → open/reference importers → read-only Gondola hotel/cash-flight spike → optional Travelpayouts cached flight trends → experimental OpenBnB rental spike → one free/personal-use award adapter when available. Duffel test mode supplies flight contract fixtures, not real prices; Google Flights is verification/deep-link only. Paid/credentialed sources require explicit human approval. The offline ingestion pipeline (`05`) is independent and may begin only after Kernel MVP gates unless explicitly reprioritized.

## Repo layout (unified monorepo — backend + frontend + specs)

```
tripwise/
  README.md               # 3 lines + pointer to docs/ARCHITECTURE.md
  DEVIATIONS.md           # judgment-call log (Doc 06) — created empty on day one
  docs/
    ARCHITECTURE.md       # one-page orientation
    specs/                # 18 spec docs: kernel 00–07, platform 08/09/16, frontend 10–15,
                          #   accounts 17 (PENDING — not yet written), acquisition 18
  reports/                # milestone self-review reports (Doc 06 §5, Doc 10 §5)
  contract/
    openapi.json          # committed schema snapshot — single source of truth (Doc 12)
  backend/
    core/                 # Milestone 1 — pure, deterministic, zero I/O beyond SQLite
      models.py           # Pydantic models from 01
      db.py               # SQLAlchemy schema + KnowledgeBase facade
      seeds/              # YAML seed data (01 §9; corridor packs live here)
      optimizer/          # normalize.py, rules.py, allocate.py, offers.py, report.py (02)
      transfer/           # pathfinder (07) — Milestone 1b
    agents/               # Milestone 2 — llm.py, intake.py, planner.py, estimator.py,
                          #   critic.py, explainer.py, pipeline.py (03)
    api/                  # FastAPI app + job wrapper (03, amended by 12 §2)
    evals/                # golden/*.yaml, recorded/, test_*.py, judge.py (04)
    ingestion/            # Phase 2 ONLY (05): watchlist.yaml, snapshots/, review queue
    gateway/              # Post-F4 ONLY (09/16): provider registry, adapters, quote cache
  frontend/               # Milestones F1–F4 — full internal layout in Doc 10 §4
    src/  design/  e2e/
```

Rules: specs are read-only during implementation (changes go through Doc 06 §3); `backend/core/` never imports from `agents/` or `api/`; nothing imports across the `backend/`↔`frontend/` boundary except via the contract snapshot.

Start with Milestone 1. Read `06` (the working protocol), then `01` and `02` fully, before writing code. Maintain `DEVIATIONS.md` from the first commit; pass each milestone's self-review gate in `06 §5` before moving on — no external review round-trips are expected or required.
