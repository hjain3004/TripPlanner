# 03 — Orchestration & Agent Contracts

**Scope:** This is the Kernel MVP pipeline over local sample/curated data. It remains the executable graph through M2/M3 and F4. Spec 09 later wraps this kernel with a bounded target orchestrator and domain workflows; it does not silently mutate this graph.

Design stance (per the agentic taxonomy): this is a **Level 1–2 governed workflow** — a Coordinator over a mostly Sequential pipeline with one Iterative-Refinement (critic) loop. Kernel LLM autonomy is confined to four call sites; everything else is deterministic code. Agents never choose tools dynamically in the Kernel MVP; the graph is fixed. Do not add framework machinery a 6-node pipeline doesn't need — plain Python with typed node interfaces; LangGraph optional later for streaming/checkpoints.

## 1. Pipeline graph

```
user input ─▶ [1 Intake LLM] ─▶ TripSpec
TripSpec ───▶ [2 Itinerary Planner LLM ⇄ KB retrieval] ─▶ DraftItinerary
DraftItinerary ─▶ [3 Cost Estimator (code)] ─▶ CostedTrip
CostedTrip + wallet ─▶ [4 Optimizer (code, doc 02)] ─▶ OptimizerResult
DraftItinerary + OptimizerResult ─▶ [5 Critic LLM] ─▶ pass | revision notes ─▶ (back to 2, max 2 loops)
all artifacts ─▶ [6 Explainer LLM] ─▶ FinalReport JSON ─▶ API response
```

Coordinator = `agents/pipeline.py`: runs nodes in order, validates every artifact against its Pydantic schema, retries an LLM node once on schema violation (feeding the validation error back), and fails soft (see §8). Every node execution appends a `TraceEvent{node, started, ended, model?, tokens?, artifact_hash}` to a per-request trace (JSON file) — this is the observability the whitepapers demand; no OpenTelemetry dependency needed in MVP, but keep the event shape OTel-compatible (`name, start, end, attributes`).

## 2. TripSpec (output of Intake; the contract for everything downstream)

```python
class TripSpec(BaseModel):
    home_country: Literal["IN","AE","US"]
    origin_city: str                     # IATA-resolvable
    destination_city: str
    start_date: date; end_date: date     # 3–7 nights enforced in MVP
    travelers: int
    budget_minor: int | None; budget_currency: str
    style: Literal["budget","balanced","luxury"]
    interests: list[str]                 # subset of POI tag vocabulary
    pace: Literal["relaxed","moderate","packed"] = "moderate"
    dietary: list[str] = []              # ["vegetarian","halal",...] — planner hint only
    wallet: UserWallet                   # card_ids owned + optional points_balances
    optimization: OptimizationPrefs      # objective + free-text nuance
    unresolved: list[str]                # questions intake couldn't resolve (rendered as assumptions)
```

## 3. Call site 1 — Intake

- **Input:** raw user text/form + the card catalog (id, issuer, name) for fuzzy card matching.
- **Output:** `TripSpec` JSON only. Temperature 0. If the user's card mention doesn't match the catalog (e.g. "my SBI card" when no SBI card seeded), put it in `unresolved` — never invent a card id.
- **System prompt skeleton:** "You convert a travel request into a strict JSON TripSpec. Output only JSON matching this schema: {schema}. Card catalog: {catalog}. Rules: never guess dates — if absent, ask via `unresolved`; map interests onto this tag vocabulary: {tags}; map card mentions to catalog ids only on unambiguous match…" Include 2 few-shot examples (one clean, one with ambiguity → `unresolved`).
- MVP UI may be a structured form, making this node near-trivial — keep it anyway so free-text works.

## 4. Call site 2 — Itinerary Planner (+ deterministic retrieval and estimator)

- **Retrieval (code, not LLM):** `kb.pois(city, tags=interests)` ranked by tag overlap; take top ~40; plus the `areas` table. Compact each POI to one line: `id | name | area | tags | price | duration | hours`. This is the context-engineering step: the LLM sees only curated candidates, so it cannot invent attractions.
- **LLM contract:** input = TripSpec + candidate list + area list. Output = `DraftItinerary` JSON: `hotel_area_id` (must be a listed area id), `days: [{date, items: [{poi_id, start_hint, meal_slots}]}]`, `notes`. **Every `poi_id` must come from the candidate list** — the coordinator validates referential integrity and rejects/retries otherwise. Planner reasons about geography (cluster same-area POIs per day), pacing (duration budget per day by `pace`), and hours (avoid closed-day conflicts; critic double-checks).
- **Cost Estimator (pure code):** flights = cheapest `SampleFlight` matching origin/dest/cabin-by-style × travelers; hotel = `SampleHotel` filtered by `style` + chosen area (fallback: nearest area by centrality) × nights; attractions = Σ POI prices × travelers grouped per `merchant_hint`; dining/misc = per-diem table by style (config constants, e.g. balanced Singapore: S$70 dining + S$25 misc per person-day — mark as assumption). Output `CostedTrip{spend_line_items, itinerary_ref, fx_used}` feeding doc 02 §3.

## 5. Provider-agnostic LLM interface

```python
class LLMClient(Protocol):
    def complete_json(self, system: str, user: str, schema: type[BaseModel],
                      temperature: float = 0.0, max_tokens: int = 2048) -> BaseModel: ...
```

Implementations: `HostedFreeTier` (default; env-configured base URL/model/key) and `OllamaLocal`. `complete_json` = call → strip fences → `model_validate_json` → on failure, one retry with the error appended. Config in `agents/config.yaml` per node (model, temperature, max loops). Never embed provider names in node code.

## 6. Call sites 3 & 4 — Critic and Explainer

**Critic** (temperature 0) receives DraftItinerary + CostedTrip + POI reference rows and returns `CriticVerdict{pass: bool, issues: [{severity, kind, message, poi_id?}]}` checking only: hours/closed-day conflicts, same-day geographic scatter (> 2 areas/day), pace overload (Σ durations vs daylight budget), budget overshoot > 15%, dietary conflicts, and **unsupported claims** (anything not derivable from provided rows). `blocking` issues route back to the planner with the issues as revision notes (max 2 loops, then proceed and surface remaining issues as report caveats).

**Explainer** (temperature ≤ 0.3) receives all artifacts and renders `FinalReport` (§7) prose fields. Hard rules in its system prompt: *every number must be copied verbatim from OptimizerResult/CostedTrip fields; never compute; never mention cards/offers absent from assignments; attach the provided provenance strings; write the "why not X?" section from `runner_up` deltas only.* The coordinator post-validates: regex-extract all currency amounts from prose and assert each appears in the structured artifacts (cheap groundedness gate).

## 7. FinalReport (API response of `POST /plan`)

`FinalReport{trip_spec, itinerary, hotel_area{id, name, reason}, flights_pick, hotel_pick, budget_table, payment_strategy: [per-line: card, channel, offers, action_sentence], totals{gross, discounts, rewards_value, forex_fees, effective_cost, cash_outlay_now, deferred_value, savings_pct}, points_advice, booking_checklist: [ordered steps: "Book flights via {portal} with {card} before {rule.valid_to}…"], assumptions: [...], provenance_warnings: [...], confidence, trace_id}`. The checklist is generated deterministically from assignments (template per channel type), then lightly polished by the explainer.

## 8. Failure policy (fail soft, never blank)

- Intake unparseable → return `unresolved` questions to the UI (HTTP 200 with `needs_clarification`).
- Planner fails schema twice → deterministic fallback: greedy day-packing of top-ranked POIs by area clustering (code), flagged `"itinerary_quality": "fallback"`.
- Critic fails → skip critique, add caveat.
- Explainer fails → return structured artifacts with template-rendered minimal prose.
- Optimizer is code: it must not fail; any exception is a bug (500 + trace id).
- Global timeout per request 60s; each LLM call 20s.

## 9. Explicitly out of MVP scope

Live pricing/inventory, provider adapters, award search, account linking, card application recommendations, multi-city routing, DCC modeling, EMI optimization, and user accounts/memory are outside the **Kernel MVP**. Student-profile live discovery is planned after F4 in specs 08/09/16; it is not a reason to alter M2. Booking and points-transfer execution remain permanently out of scope. The report footer must state: computed from data last verified on {min last_verified}; informational, not financial advice; verify prices and offer terms before paying.
