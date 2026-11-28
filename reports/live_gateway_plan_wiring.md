# Opt-In Live Gateway Wiring in `run_pipeline()` (`POST /plan`)

**Status:** COMPLETE on branch `codex/live-gateway-plan-wiring` — opt-in gated (`TRIPWISE_GATEWAY_LIVE_ENABLED=1`), default path byte-identical, per-domain fallback to `SampleAdapter` verified offline with recorded `DEL → SIN` captures.

## 1. Working Now (End-to-End Capability)

When `TRIPWISE_GATEWAY_LIVE_ENABLED=1` (and `TRIPWISE_GATEWAY_KILL_SWITCH` is unset/falsy), `run_pipeline()` (called by `POST /plan`) fans out concurrently across enabled `student_noncommercial` travel MCP providers (`kiwi`, `trivago`, `seats_aero`, plus caller-injected `openbnb`) via `backend/gateway/travel/live_orchestrator.py` and `backend/agents/gateway_estimator.py`:

1. **Default parity (flags off):** When `TRIPWISE_GATEWAY_LIVE_ENABLED` is unset or falsy (or `TRIPWISE_GATEWAY_KILL_SWITCH` is set), `backend/agents/pipeline.py` stays on the pre-existing `estimate_costed_trip` / `run_kernel` path with zero changes to outputs, `travel_inventory`, `core/`, OpenAPI contracts, or golden tests.
2. **Concurrent per-domain execution & fallback:**
   - **Flight (`kiwi` → `sample_travel_adapter`):** Selected via `get_default_travel_registry()`, normalized into home currency (`INR`) `SpendLineItem` via deterministic `price_in_home` FX arithmetic.
   - **Hotel (`trivago` / injected `openbnb` → `sample_travel_adapter`):** Ranks complete quotes strictly ahead of `taxes_uncertain`/`fees_uncertain` listings so unverified tax-excluded quotes cannot win solely on lower headline price; excludes `partial` quotes from cost selection. Keeps `openbnb` absent from default registry and avoids importing the `openbnb` package from production modules (preserving `evals/test_g3b_boundaries.py`).
   - **Award (`seats_aero` → local seed award chart):** Queries anonymous one-way awards within `0..60` days of `booking_date`, compares one-way awards against 50% of the round-trip cash flight cost, builds an in-memory ephemeral `KnowledgeBase` clone preserving existing `_award_chart_entries` (without touching SQLite or `agents/kernel.py`), skips zero-mile quotes safely, and preserves `"VERIFY (blocking):"` as checklist step 1 and `needs_verification=True` provenance flags.
   - **Async/sync bridge:** `run_coro_sync()` runs safely both from synchronous callers and inside active asyncio event loops (e.g., FastAPI handlers) via a single-worker `ThreadPoolExecutor` fallback.
   - **Failure isolation & replan stability:** Factory errors, `TravelGatewayError` (429 `rate_limited`, `timeout`, `budget_exhausted`, `invalid_response`, `unsupported_domain`, missing FX rate), or empty responses trigger per-domain `SampleAdapter` fallback without failing `run_pipeline()`, recording `gateway:<domain>:<provider>:ok|disabled|fallback:<reason>` entries in `EstimatorResult.assumptions` / `FinalReport.assumptions` and structured telemetry in `FinalReport.travel_inventory`. Critic replan loops reuse the initial `LiveGatewayEstimate` via `reprice_live_estimate_for_itinerary()` without re-calling live providers.

## 2. Demonstrated Execution & Evidence

- **Offline recorded replay (`socket.socket.connect` blocked):** `backend/evals/test_gateway_pipeline_wiring.py` exercises `run_pipeline()` end-to-end with `FixtureMcpTransport` backed by captured `DEL → SIN` fixtures (`kiwi` business INR 93,741 extended with a test `2026-12-30` return leg for round-trip `TripSpec` validation; `trivago` INR 19,934 stay; `seats_aero` 75,000 Aeroplan miles with test `aeroplan` KB transfer edge, `0.40 INR/pt` baseline, and `CAD->INR` FX row), producing a complete `FinalReport` with live `CostedTrip` lines, `travel_inventory`, and `"VERIFY (blocking): ... https://seats.aero/i/..."` transfer checklist. Also verifies that against the 50% one-way cash equivalent (`INR 46,870.50`) at `1.00 INR/pt`, live one-way 75k Aeroplan returns `PAY_CASH` (and never overrides a better seed round-trip `REDEEM` plan).
- **One-way vs round-trip mismatch, critic replanning, active event loop fallback & kill-switch replay:** Proved offline that:
  - an unmodified one-way Stage-1 `kiwi` capture against a round-trip `TripSpec` fails closed with `gateway:flight:kiwi:fallback:invalid_response` and falls back to `SampleAdapter`;
  - a blocking critic replan loop (`CriticVerdict(passed=False)` -> `CriticVerdict(passed=True)`) invokes live provider factories only once (no duplicate MCP calls);
  - inside a running `asyncio.run(...)` event loop, `kiwi` (`rate_limited`), `seats_aero` (`timeout`), and injected `openbnb` (`unsupported_domain` on hotel/neighbourhood search) fall back cleanly while `trivago` supplies the hotel `SpendLineItem`;
  - `TRIPWISE_KIWI_KILL_SWITCH=1` overrides `TRIPWISE_KIWI_LIVE_ENABLED=1` and >60-day `seats_aero` dates skip transport dispatch (`outside_60d_anonymous_horizon`);
  - zero-mile `AwardQuote` entries are skipped without crashing, and `"first"` cabin awards preserve `"first"` cabin matching and existing `_award_chart_entries`.

## 3. Remaining Boundaries & Limitations

- Live network calls remain disabled by default until an operator explicitly sets `TRIPWISE_GATEWAY_LIVE_ENABLED=1` and per-provider `TRIPWISE_<PROVIDER>_LIVE_ENABLED=1`.
- `OpenBnBAdapter` remains isolated per G3b (`openbnb` is never imported by production modules and stays absent from `get_default_travel_registry()`), so it only participates when explicitly injected via `GatewayProviderFactories.openbnb` with `TRIPWISE_OPENBNB_ENABLED=1`.
- `report.travel_inventory.reference_only_awards` reflects whether live award quotes were fetched (`len(bundle.awards) == 0`); if live awards are fetched but unmatchable due to missing KB transfer edges or FX rates (e.g., seed data lacks `CAD->INR`), `evaluate_live_awards` falls back to `base_advice` (`reference_only_awards` stays `False` to record that live quotes were inspected alongside merged infeasible reasons).
