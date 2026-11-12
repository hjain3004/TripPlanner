# Runtime LLM design: Claude API behind the four Kernel call sites

Date: 2026-11-11 · Author: Opus (design only, no application code) · Base: `origin/main` `a9efea0`

Status: **design for implementation; several items are proposals awaiting owner confirmation** (§2). Nothing in this document authorizes a paid call, a credential, a deployment or a Tier-F change. Implementers build the parts marked *decided* and stop at each *owner decision*.

Missing inputs: `docs/superpowers/plans/2026-11-11-agent-work-packages.md` and `2026-11-11-travel-change-feed.md` were untracked files on the owner's Mac and are not on any remote branch. This design does not depend on them. Their publication and corrections are still open (§13).

## 1. What the code does today (read, not assumed)

| Fact | Where |
|---|---|
| One `LLMClient` protocol: `complete_json(node, system, user, schema, temperature, max_tokens, timeout_s, tools) -> schema \| SearchIntent`. | `backend/agents/llm.py:24` |
| Production client is `HostedFreeTier` (OpenAI-compatible `urllib`). It makes up to 3 attempts per model, honors `Retry-After` on 429 (capped at 60 s), falls back to the next model only on 404, and enforces a per-instance `max_calls` (default 25). It adds no spend accounting. | `llm.py:117-335` |
| `get_llm()` builds a fresh `HostedFreeTier()` per request dependency. It has no plan id, no user and no budget. | `backend/api/main.py:200` |
| Pipeline: intake → retrieval → planner → estimator → kernel → critic loop (≤ 2 critic calls, ≤ 1 re-plan) → explainer. | `backend/agents/pipeline.py:71-237` |
| Planner calls go through the discovery loop (`max_calls=6`, `max_rounds=3`). A validation failure triggers a second full discovery run. | `agents/planner.py:56-140`, `agents/discovery/contracts.py:26-28` |
| Theoretical dispatch worst case per plan: intake 2 + planner 12 + critic 4 + re-plan 12 + explainer 2 = **32**. The existing ceiling of 25 truncates it, and later nodes then take their fail-soft path. | derived from the above |
| The critic catches **every** exception and returns `passed=True` plus the caveat "Critic unavailable; itinerary was not LLM-reviewed." | `agents/critic.py:61-67` |
| The confirmed-brief path serializes the brief to JSON and still calls the intake LLM. `validate_confirmed_intake` then compares 11 identity fields and returns `NEEDS_CLARIFICATION` on mismatch. `interests`, `pace` and `dietary` are **not** compared, so the model's reading of them wins over the confirmed brief. | `agents/confirmed_trip.py`, `pipeline.py:105-114` |
| `TripIntakeRequest.wallet` is accepted by `POST /plan`, but `_run_job` passes only `raw_request`, so a supplied wallet is silently dropped. | `agents/models.py:218`, `api/main.py:376` |
| Interview and post-plan roles exist (`get_interview_llm`, `get_post_plan_llm`). They are disabled unless an operator sets `*_ZERO_SPEND_CONFIRMED=1`, and production startup rejects that flag. | `agents/interview_assistant.py:46`, `agents/post_plan_interpreter.py:77`, `api/runtime_config.py` |
| `JobError.code` is a free `string` in the contract, so new error codes need no OpenAPI change. | `contract/openapi.json` |
| `anthropic` is not a dependency. `httpx2==2.15.1` (which `anthropic` 1.x uses) is already in the hashed lock through `mcp`. | `backend/requirements.lock:259` |

## 2. Explicit owner instructions vs. proposals

**Explicit (owner, 2026-11-11):**
- No paid API calls during development. Claude API credit is reserved for the deployed site.
- Development uses scripted or recorded clients.
- Existing free-tier access may be used only within its established authorization and zero-out-of-pocket conditions.

**Proposals in this document that are not approved until the owner confirms them:**

| ID | Proposal | Why it needs the owner |
|---|---|---|
| P1 | Use the Anthropic Messages API as the runtime provider for the four pipeline call sites on the deployed site. | Paid service, credential, and the USD 0 out-of-pocket rule (§6.1). |
| P2 | **Mode B:** when input is structured or confirmed, a deterministic projection *replaces* the intake LLM call. | It changes the frozen Kernel pipeline graph (Tier F: "the four call sites"). |
| P3 | Paid dispatch only for authenticated, owner-bound jobs; anonymous `/plan` and `/plan/refresh-prose` never dispatch paid calls. | Product scope for the public demo. |
| P4 | Model choice (§6.2), caps (§7) and the server-side refusal fallback (§8.3). | Spend. |
| P5 | Sending trip, wallet and points data to Anthropic, plus the privacy wording shown to users. | Legal and compliance wording. |
| P6 | Any paid model for the interview or post-plan roles. | A runtime model role beyond the four call sites. This design keeps both **off**. |

Everything else here is Tier C or V and is decided.

## 3. Structured-input validation (decided, Mode A; Tier C)

Mode A keeps the four call sites. The intake LLM still runs, and server-owned facts override it after it returns.

```python
# backend/agents/structured_input.py  (owner: Argon)
class StructuredTripInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home_country: Literal["IN", "AE", "US"]
    origin_city: str               # IATA, normalized by the TripSpec validator
    destination_city: str
    start_date: date
    end_date: date
    travelers: int = Field(gt=0)
    budget_minor: int | None = Field(default=None, ge=0)
    budget_currency: str
    style: Literal["budget", "balanced", "luxury"]
    interests: list[str] = Field(default_factory=list)
    pace: Literal["relaxed", "moderate", "packed"] = "moderate"
    dietary: list[str] = Field(default_factory=list)
    wallet: UserWallet
    objective: Literal["min_cash_outlay", "max_savings", "simplicity"] = "max_savings"

def project_structured_trip_spec(inp: StructuredTripInput, kb: KnowledgeBase) -> TripSpec: ...
    # Pure. Builds TripSpec (unresolved=[]); then runs the existing intake._validate_intake
    # rules (IATA aliases, ORIGIN_CITIES, regions.yaml destinations, kb.has_card) and raises
    # StructuredInputRejected(unresolved: list[str]) instead of returning a partial spec.

def apply_authoritative_fields(spec: TripSpec, authority: TripSpec) -> tuple[TripSpec, list[str]]: ...
    # Pure. Returns (spec with identity fields compared and preference fields overwritten,
    # mismatched identity field names). Identity fields = the 11 in ConfirmedTripInput.expected_fields.
    # Preference fields overwritten from authority = interests, pace, dietary.
```

Rules:
1. **Confirmed brief.** `compile_confirmed_input` gains `authority: TripSpec`, built from the brief: `interests` from `experiences_and_food.interests`, `pace` from `daily_rhythm.pace` (`no_preference` becomes `moderate`), `dietary` from `hard_constraints.dietary`. After intake, the pipeline calls `apply_authoritative_fields(intake_spec, authority)`.
   - An identity mismatch behaves as today: `NEEDS_CLARIFICATION`.
   - Preference fields are overwritten silently. The confirmed brief is the authority, and the overwrite is recorded in the trace.
2. **Anonymous `/plan` with `wallet`.** When `TripIntakeRequest.wallet` is present, it replaces `spec.wallet` after intake, and every card id must pass `kb.has_card` or the request gets `NEEDS_CLARIFICATION`. This fixes the silently dropped wallet. Log it as a DEVIATIONS row.
3. **Structured wizard submission** (Luna, later): `TripIntakeRequest` gains `trip: StructuredTripInput | None`. When it is present, the server renders `raw_request` from it deterministically (sorted JSON, the same style as `compile_confirmed_input`), calls intake as today, and then applies rule 1 with `authority = project_structured_trip_spec(trip, kb)`. A request carrying both `trip` and free text uses `trip` as the authority.

**Mode B (P2, owner decision).** With Mode B on, the intake call is skipped when `authority` exists: `spec = authority`, and the trace records `intake: projected`. That saves one dispatch per plan and removes the model's ability to contradict confirmed facts. Until the owner approves it, Mode B stays unimplemented. It is **not** built behind a flag on `main`, because a flag would be a production stub.

## 4. Critic behavior (decided; consistent with spec 03 §6/§8)

Spec 03 §8 says "Critic fails → skip critique, add caveat." That policy stays. Two narrowings, both Tier C:
- Catch only `LLMCallError`, `ValidationError` and `json.JSONDecodeError`. Any other exception is a bug and propagates, which yields a 500 with a trace id.
- The caveat names the cause, with fixed strings:
  - `"Critic unavailable (budget); itinerary was not LLM-reviewed."`
  - `"Critic unavailable (provider); itinerary was not LLM-reviewed."`
  - `"Critic unavailable (invalid response); itinerary was not LLM-reviewed."`

  Luna renders these through the existing caveat or assumption surface. They must not be restyled away.

The critic never retries outside `complete_with_repair`'s single repair. Blocking issues keep the frozen loop (≤ 2 critic calls, ≤ 1 re-plan). A critic `passed=True` produced by the failure path is recorded in the trace as `critic_skipped=true`, never as a pass.

## 5. Provider client (decided design; activation needs P1)

```python
# backend/agents/llm_anthropic.py  (owner: Sonnet)
class AnthropicMessagesClient:          # satisfies agents.llm.LLMClient
    def __init__(
        self, *, model: str, plan: PlanBudget, ledger: LLMSpendLedger,
        node_settings: Mapping[str, AnthropicNodeSettings],
        client: anthropic.Anthropic | None = None,   # injected in tests via http_client=httpx2.Client(transport=MockTransport)
        gate: DispatchGate,                          # §7.3
        clock: Callable[[], float] = time.monotonic,
    ) -> None: ...
    def complete_json(self, *, node, system, user, schema, temperature=0.0,
                      max_tokens=2048, timeout_s=20, tools=None) -> BaseModel: ...

@dataclass(frozen=True)
class AnthropicNodeSettings:            # from config.yaml `anthropic:` block (Tier C, tunable)
    max_tokens: int
    effort: Literal["low", "medium", "high"]
    thinking: Literal["off", "adaptive"]   # "off" maps per model, see below
```

Request composition:
- Official SDK `anthropic>=1,<2`, `client.messages.parse(...)` with `output_format=<pydantic model>`. The SDK strips unsupported constraints (`gt`, `ge`, length limits), sends `output_config.format`, and validates client-side. Construct the client with `max_retries=0`: this client owns retries (§8), so every dispatch gets its own reservation. Set the timeout to the node's `timeout_s`.
- **Never send `temperature`.** Current models reject non-default sampling parameters, and API version `2026-10-21` rejects them on every model. Determinism of money is unaffected because it comes from the kernel. The `temperature` argument is accepted and ignored.
- **Tools path (planner only).** Send no Anthropic tools. Use a structured-output envelope instead:

  ```python
  class PlannerTurn(BaseModel):
      kind: Literal["itinerary", "search"]
      itinerary: DraftItinerary | None = None
      search_intent: SearchIntent | None = None
  ```

  The client returns the populated member. Wrong `kind` or member pairing raises `ValidationError`, which goes into the existing repair. Forced `tool_choice` returns 400 on current models, and the envelope keeps the existing "schema or SearchIntent" contract exact.
- **Thinking.** With `thinking="off"`, Sonnet 5.5 gets `thinking={"type": "between_tools"}` (thinking off, effort ≤ `high`) and Haiku 5.5 gets `{"type": "disabled"}` (effort ≤ `high`). Opus 5.5 cannot disable thinking, so for it `max_tokens` must include thinking headroom and the reservation grows (§6.2).
- **Refusal handling.** Check `stop_reason` before reading output:
  - `refusal` raises `LLMRefusal(LLMCallError)`.
  - `max_tokens` raises `LLMTruncated(LLMCallError)`. It is not a `ValidationError`, so there is no repair loop. A repeat at the same cap would truncate again.
  - The node then takes its spec 03 §8 fail-soft path.
- **Schema too complex.** Structured outputs cap optional parameters at 24 and `anyOf` at 16. A 400 "Schema is too complex" raises `LLMSchemaRejected(LLMCallError)`. The deployment-day check (§10) must show zero such rejections for `TripSpec`, `PlannerTurn`, `CriticVerdict` and the explainer schema. If one is rejected, the fix is a flatter wire schema in the same PR. It is **not** a silent fallback to unconstrained JSON.
- Prompt text is unchanged. The four node prompts stay theirs, and the client adds nothing to `system`.

Factory (one place that picks a client):

```python
# backend/agents/llm_factory.py  (owner: Sonnet)
LLMProvider = Literal["scripted", "replay", "openai_compatible", "anthropic"]
LLMRole = Literal["pipeline", "interview", "post_plan"]

def build_llm_client(role: LLMRole, *, plan_id: str, user_id: str | None,
                     env: Mapping[str, str] = os.environ) -> LLMClient: ...
```

- `TRIPWISE_LLM_PROVIDER` selects the provider:
  - Unset means `openai_compatible` (today's `HostedFreeTier`, unchanged).
  - `anthropic` is honored **only** for `role="pipeline"`. For the other roles, `anthropic` returns `ScriptedLLMClient({})`, which reports the role unavailable (P6).
  - `anthropic` with `user_id is None` also returns `ScriptedLLMClient({})` unless `TRIPWISE_LLM_PAID_SCOPE=all` (P3). Intake then fails, and the job ends `failed` with code `LLM_SIGN_IN_REQUIRED`.
  - `TRIPWISE_LLM_KILL_SWITCH=1` returns `ScriptedLLMClient({})` for every role, whatever the provider. It is read on every call to `build_llm_client`, not cached.
- `api/main.py`: `get_llm` is removed as a request dependency. `_run_job` calls `build_llm_client("pipeline", plan_id=job_id, user_id=owner_id)`. `start_confirmed_job` passes `session.user_id`. `/plan/refresh-prose` passes `user_id=None`, which means template prose in Anthropic mode.
- `api/runtime_config.py`: with `TRIPWISE_LLM_PROVIDER=anthropic`, startup requires:
  - `ANTHROPIC_API_KEY` present (never echoed);
  - `TRIPWISE_ANTHROPIC_MODEL` present in `PRICE_TABLE`;
  - all four caps in §7 set as positive integers;
  - `TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED=1` (§6.1);
  - `TRIPWISE_DATA_DIR` writable.

  The production rejection of interview and post-plan zero-spend flags stays.

## 6. Provider selection

### 6.1 Spend profile against the USD 0 out-of-pocket rule

CLAUDE.md allows a credit-funded service only when overage is mechanically impossible. The code cannot see the Anthropic account. These layers are required, and the first two are owner actions:

1. **Owner:** a dedicated Console workspace for the deployed site with a **workspace spend limit** at or below the remaining credit. A request over a user-set limit returns HTTP 400 `invalid_request_error` ("You have reached your specified workspace API usage limits"). Auto-reload and any payment method that could top up are off. The owner attests to this with `TRIPWISE_ANTHROPIC_PREPAID_NO_OVERAGE_CONFIRMED=1`.
2. **Owner:** an API key scoped to that workspace only.
3. **Code:** the durable pre-dispatch reservation ledger (§7) with app-level caps below the workspace limit. This layer is the one that makes overage impossible from the application's side, independent of console settings.

### 6.2 Model (P4, owner decision)

`TRIPWISE_ANTHROPIC_MODEL` is required and has no default. Prices are integer micro-USD per million tokens, from the official model table (cached 2026-11-03, `needs_verification=true` until the §10 check re-reads the pricing page):

| Model | Input | Output | Thinking off? | Byte-bound reservation for the 25-call ceiling* |
|---|---|---|---|---|
| `claude-opus-5-5` | 4 000 000 | 20 000 000 | No (adaptive always) | 25 × (30 000 × 4 + 4 096 × 20) µ$ ≈ **$5.05** |
| `claude-sonnet-5-5` | 2 000 000 | 10 000 000 | Yes (`between_tools`) | 25 × (30 000 × 2 + 2 048 × 10) µ$ ≈ **$2.01** |
| `claude-haiku-5-5` | 100 000 (≤ 100K prompt; 500 000 above) | 500 000 (2 500 000 above) | Yes (`disabled`) | ≈ **$0.10** |

\* These figures are **upper bounds**. They assume 30 000 bytes of input per call, which is generous for the planner's POI rows, and a full `max_tokens` on every call. A real plan makes about 5–8 calls with far less output. The deploy-day check measures the actual figure. The bound is what the cap must allow for. It is not the expected bill.

Recommendation, which the owner decides: start with `claude-opus-5-5`, the current default model, at effort `low` with `max_tokens=4096`. If the per-plan cap the owner wants is below the Opus bound, choose `claude-sonnet-5-5`. A cheaper model is the owner's call, not the implementer's. Every price row carries `source_url`, `last_verified` and `verified_by` (non-negotiable 3), and an unknown model fails closed.

## 7. Pre-dispatch cost reservations and global limits (decided)

### 7.1 Arithmetic (Argon; integer only)

```python
# backend/agents/llm_budget.py  (owner: Argon)
@dataclass(frozen=True)
class ModelPrice:
    model: str
    input_micro_usd_per_mtok: int
    output_micro_usd_per_mtok: int
    cache_write_5m_micro_usd_per_mtok: int    # = input * 125 // 100
    cache_read_micro_usd_per_mtok: int
    long_prompt_threshold_tokens: int | None  # Haiku 5.5: 100_000
    long_input_micro_usd_per_mtok: int | None
    long_output_micro_usd_per_mtok: int | None
    source_url: str; last_verified: date; verified_by: str; needs_verification: bool

FRAMING_TOKENS = 2048   # message framing + structured-output system prompt; validated in §10

def input_token_upper_bound(*, system: str, user: str, wire_schema_json: str) -> int:
    """Tokens are formed from UTF-8 bytes, so each token covers at least one byte and
    token count <= byte count. FRAMING_TOKENS covers what the request adds that is not
    in these strings."""
    return (len(system.encode()) + len(user.encode()) + len(wire_schema_json.encode())
            + FRAMING_TOKENS)

def reservation_micro_usd(price: ModelPrice, *, input_upper: int, max_tokens: int) -> int:
    """ceil division; long-prompt prices whenever input_upper exceeds the threshold.
    max_tokens bounds all output, including thinking."""

def settled_micro_usd(price: ModelPrice, usage: UsageCounts) -> int:
    """ceil( input*in + cache_creation*cache_write_5m + cache_read*cache_read + output*out ) / 1e6"""
```

Golden-style unit tests pin hand-computed values. These figures are not kernel money and add nothing to the kernel's golden set.

### 7.2 Durable ledger (Argon)

The ledger lives in `TRIPWISE_DATA_DIR/llm_spend.sqlite3`, a separate database owned by `agents/` (never imported by `core/`). It carries a `schema_version` table, and Argon owns its migration.

```sql
reservations(id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, user_id TEXT, node TEXT NOT NULL,
  model TEXT NOT NULL, attempt INTEGER NOT NULL, reserved_micro_usd INTEGER NOT NULL CHECK(>0),
  settled_micro_usd INTEGER, state TEXT NOT NULL CHECK(state IN
  ('reserved','settled','released','uncertain')), created_at TEXT NOT NULL, settled_at TEXT,
  usage_json TEXT)            -- counts only; never prompt or response text
breakers(scope TEXT PRIMARY KEY, reason TEXT NOT NULL, opened_at TEXT NOT NULL)
```

```python
class LLMSpendLedger:
    def __init__(self, path: Path, caps: SpendCaps, *, now: Callable[[], datetime]) -> None: ...
    def reserve(self, *, plan_id: str, user_id: str | None, node: str, model: str,
                amount_micro_usd: int) -> str: ...     # returns reservation id
        # BEGIN IMMEDIATE; raises LLMBudgetExceeded(scope) if any breaker is open or if
        # committed(plan) / committed(UTC day) / committed(UTC month) + amount exceeds its cap,
        # or if this is a new plan_id and the user's distinct paid plans today >= cap.
        # committed = sum(settled for settled) + sum(reserved for reserved|uncertain).
    def settle(self, reservation_id: str, usage: UsageCounts, amount_micro_usd: int) -> None: ...
        # if amount > reserved: store the actual amount, then open breaker 'reservation_underestimated'
    def release(self, reservation_id: str) -> None: ...   # provider confirmed not billed
    def mark_uncertain(self, reservation_id: str) -> None: ...  # charged in full, never released
    def recover_stale(self, *, older_than: timedelta) -> int: ...  # startup: reserved -> uncertain
    def open_breaker(self, scope: str, reason: str) -> None: ...
    def reset_breaker(self, scope: str, *, operator: str) -> None: ...  # CLI only, never request-time

@dataclass(frozen=True)
class SpendCaps:            # all required in anthropic mode, from env, positive integers
    per_plan_micro_usd: int          # TRIPWISE_LLM_CAP_PER_PLAN_MICRO_USD
    per_day_micro_usd: int           # TRIPWISE_LLM_CAP_PER_DAY_MICRO_USD
    per_month_micro_usd: int         # TRIPWISE_LLM_CAP_PER_MONTH_MICRO_USD (<= workspace limit)
    paid_plans_per_user_per_day: int # TRIPWISE_LLM_PAID_PLANS_PER_USER_PER_DAY
```

Lifecycle of one dispatch:
1. Compute the reservation.
2. Call `ledger.reserve`.
3. Acquire the dispatch gate.
4. Send.
5. Close the reservation:
   - response received: `settle` (actual `usage`);
   - error that the API confirms was not processed (HTTP 400/401/403/404/413/429/529 with an error body): `release`;
   - timeout, connection drop after send, or process death: `mark_uncertain`. A restart runs `recover_stale(older_than=2×timeout)` before serving.

`agents.llm.LLMCallError` gains subclasses: `LLMBudgetExceeded`, `LLMProviderUnavailable`, `LLMRefusal`, `LLMTruncated`, `LLMSchemaRejected`. Each has `code: str`. `_run_job` maps them to `JobError.code`:
- `LLM_BUDGET_EXHAUSTED`
- `LLM_UNAVAILABLE`
- `LLM_SIGN_IN_REQUIRED`

These need no schema change. Luna adds the UI copy and MSW fixtures.

### 7.3 Global limits

| Limit | Value | Enforced by |
|---|---|---|
| Calls per plan | `TRIPWISE_LLM_MAX_CALLS` (existing, default 25) | client |
| Cost per plan, day, month; paid plans per user per day | §7.2 caps | ledger, before dispatch |
| Wall-clock per plan | 60 s for LLM dispatch (spec 03 §8). A call is not sent unless `deadline - now >= timeout_s`. Past the deadline, the node takes its fail-soft path. | `PlanBudget(deadline=...)` |
| Per call | `timeout_s` from config (20 s) | SDK timeout |
| Concurrent dispatches, process-wide | `TRIPWISE_LLM_MAX_CONCURRENT_DISPATCH` (default 2) | `DispatchGate` |
| Kill switch | `TRIPWISE_LLM_KILL_SWITCH=1` | factory |

```python
class DispatchGate(Protocol):
    def acquire(self, timeout_s: float) -> bool: ...   # False -> LLMProviderUnavailable('overloaded')
    def release(self) -> None: ...
```

This design owns the gate. `docs/superpowers/specs/2026-11-11-concurrency-design.md` (Sol, branch `codex/sol-feed-concurrency-design`) owns job admission and states that a job slot does not authorize a model call. The implementation is one process-wide `threading.BoundedSemaphore` in `agents/llm_factory.py` (Sonnet). Every client the factory builds acquires the gate before each dispatch, for **every role**: pipeline, refresh-prose, interview and post-plan, `HostedFreeTier` included. The gate has no queue beyond `acquire(min(remaining deadline, 5 s))`. On a failed acquire the client raises `LLMProviderUnavailable("overloaded")`, no reservation is made, and the node takes its fail-soft path. The gate holds no state that must survive a restart. Ledger recovery (§7.2) covers dispatches that were in flight.

## 8. Retry behavior (decided)

### 8.1 Anthropic client (SDK `max_retries=0`; one retry total per `complete_json`, each attempt separately reserved)

| Outcome | Action | Ledger |
|---|---|---|
| 200, `end_turn` | Return the parsed value. | settle |
| 200, `refusal` / `max_tokens` | Raise `LLMRefusal` / `LLMTruncated`. No retry. | settle |
| 429 with `retry-after`, `retry-after + timeout_s <= remaining deadline` | One retry. | release, then a new reserve |
| 429 with `error.details.error_code == "enforced_spend_limit_reached"` (no `retry-after`) | Raise `LLMBudgetExceeded`. Open breaker `provider_spend_cap`. | release |
| 400 "specified … API usage limits" | Same as the spend-cap row. Breaker `workspace_spend_limit`. | release |
| 402 `billing_error`, 401, 403 | Raise `LLMProviderUnavailable`. Open breaker `provider_auth_or_billing`. | release |
| 529 / 500 / 503, deadline allows | One retry after 2 s. | release, then a new reserve |
| 404 (model) | Raise `LLMProviderUnavailable`. No model fallback: the model is pinned and checked in §10. | release |
| 400 "Schema is too complex", other 400, 413 | Raise `LLMSchemaRejected` / `LLMCallError`. No retry. | release |
| Timeout / connection error | Raise `LLMTimeoutError` / `LLMProviderUnavailable`. **No retry**: the first request may have been processed. | uncertain |
| Pydantic `ValidationError` | Propagates. The existing `complete_with_repair` makes its one repair call. | settle |

Breakers persist until `ledger.reset_breaker` runs from the operator CLI. They are never closed automatically at request time.

### 8.2 HostedFreeTier

Out of scope here. Sonnet's narrow PR (429 fallback, schema-instruction preservation) stands on its own.

### 8.3 Server-side refusal fallback (P4, default off)

The `fallbacks` parameter re-runs a declined request on another model and bills it at that model's rates. Only the array form names a model the ledger can price. If the owner enables `TRIPWISE_ANTHROPIC_REFUSAL_FALLBACK_MODEL=<model in PRICE_TABLE>`, the request sends:
- beta `server-side-fallback-2026-07-01`
- `fallbacks=[{"model": ...}]`

The reservation becomes the sum of both models' bounds. The `"default"` form is not used, because the cost of an unknown model cannot be bounded.

## 9. Prompt caching: not implemented (decided)

- The node system prompts are a few hundred tokens. On current models, a prefix shorter than the 512-token minimum silently does not cache.
- Everything after the system prompt is per-plan: the request, the TripSpec, POI rows, the itinerary.
- Within one plan, the only repeated prefix is the critic or re-plan system prompt plus the TripSpec, and the itinerary changes between critic calls.
- Cache writes cost 1.25× input, demo traffic is sparse, and a miss-dominated cache raises the bill.
- Structured-output grammars are cached server-side for 24 h without any code.

Revisit trigger: ledger `usage_json` shows a node with ≥ 1 024 identical-prefix tokens recurring within 5 minutes at least twice per plan. The ledger already records `cache_*` fields, so measuring needs no new code.

## 10. Owner-run deployment-day API check

`backend/scripts/anthropic_preflight.py` (owner: Sonnet; built and tested offline with an injected transport; **run only by the owner**):

1. **Offline:** `validate_runtime_config()` passes in anthropic mode, the ledger opens, the price row exists, and the caps are below the attested workspace limit.
2. **Free:** `models.retrieve(model)` succeeds and its `max_tokens` is at least the largest node `max_tokens`.
3. **Free:** `messages.count_tokens` on each node's DEL→SIN fixture prompt. Assert `count ≤ input_token_upper_bound(...) - FRAMING_TOKENS + 64`. Token counting is free but rate-limited, and its count is an estimate.
4. **Free, negative:** with `per_plan_micro_usd = 1`, a pipeline run makes **zero** provider requests (transport counter) and ends `LLM_BUDGET_EXHAUSTED`.
5. **Paid, one plan:** one authenticated DEL→SIN confirmed plan under the owner-chosen per-plan cap.

   Pass criteria:
   - `status=OK` with a report;
   - every settled amount ≤ its reservation (no `reservation_underestimated` breaker);
   - plan total ≤ cap;
   - zero `LLMSchemaRejected`;
   - zero `max_tokens` stops;
   - the groundedness gate passes;
   - trace attributes `used_fallback` and `critic_skipped` recorded (either value is acceptable but must be reported).
6. **Output:** a sanitized JSON summary of counts, amounts, stop reasons and timings in `TRIPWISE_DATA_DIR`. Prompts, responses and keys are not written. The summary is not auto-committed. The owner decides whether a summary goes into `reports/`.

Pricing is re-read from the official page that day. The price rows flip to `needs_verification=false` with `verified_by=<owner>` only after that re-read.

## 11. Ownership and handoff (Argon → Sonnet → Luna, one feature branch)

All of this ships on **one** feature branch, `codex/runtime-llm`, with sequential phases. Each phase starts from the exact previous handoff SHA. There are no stubs or deliberate xfails on `main`, and one PR is opened when the whole feature works.

| Phase | Owner | Files (sole owner while active) | Done when |
|---|---|---|---|
| Core | **Argon** | new `agents/llm_budget.py`, new `agents/structured_input.py`, `agents/confirmed_trip.py` (authority projection), `agents/critic.py` (§4), the `LLMCallError` subclasses in `agents/llm.py` (append only; Sonnet's narrow `HostedFreeTier` PR touches `complete_json` — it merges to `main` first, or Argon brings it in with a normal merge, never a rebase), and focused tests | Arithmetic pinned; ledger concurrency test under real SQLite contention; projection and authority tests; existing goldens untouched; hands Sonnet a SHA |
| Build | **Sonnet** | new `agents/llm_anthropic.py`, new `agents/llm_factory.py`, `agents/pipeline.py` (apply authority, wallet rule), `api/main.py` (`_run_job`, factory wiring), `api/confirmed_planning.py`, `api/runtime_config.py`, `agents/config.yaml` (`anthropic:` block), `pyproject.toml` + both lockfiles (`make lock`), `scripts/anthropic_preflight.py`, OpenAPI snapshot for `TripIntakeRequest.trip` | Injected-transport tests show the exact request body for each node, envelope parsing, every §8.1 row, ledger states, and zero dispatch when over cap; scripted end-to-end `/plan` and confirmed plan pass; `make seed && make gate` passes in task-local storage; no network call made |
| Frontend | **Luna** | `frontend/src/lib/api/generated/` (regen), MSW fixtures, wizard structured submission, rendering of `LLM_BUDGET_EXHAUSTED` / `LLM_UNAVAILABLE` / `LLM_SIGN_IN_REQUIRED` and the critic caveats | Live-local API with scripted model: structured submit → plan → each error state renders; frontend gate passes |

After Luna: one independent review of the whole branch, then a PR, which the owner merges. Only after the merge does the owner do P1 setup (§6.1) and run §10. Deployment work depends on this feature, Sol's concurrency implementation and the feed commands all working. A deployment branch cannot be "done" before them.

## 12. Non-negotiables check

- **Money:** no LLM arithmetic. Spend accounting is integer micro-USD in Python and never enters the kernel.
- **Web:** the only request-time external call stays the LLM API, through one client.
- **Provenance:** the price rows carry provenance. Critic and refusal caveats render as trust warnings.
- **Approval:** no financial fact is written. Profile proposals are unchanged.
- **Bounded autonomy:** the call sites are unchanged under Mode A. There is no dynamic tool use: the envelope replaces the tool list.

## 13. Open items outside this design

- **Publication blocked:** the two 2026-11-11 plans and the load-test material are not on GitHub. Their corrections are still to be applied:
  - no production stubs or xfails on `main`;
  - core and build continue one feature branch;
  - published Firecrawl history is reconciled by merge, not rebase;
  - feed request code respects the ingestion boundary;
  - deployment depends on working runtime, concurrency and feed commands;
  - private captures are not auto-committed;
  - reviewer assignments reflect actual authorship and independence.

  They need the owner to push the plan files, or attach the Mac checkout to this session.
- Owner decisions **P1–P6** (§2).
