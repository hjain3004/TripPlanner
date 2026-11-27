# Free Keyless Remote MCP Travel Adapters (`Seats.aero`, `Trivago`, `Kiwi.com`)

**Status:** Stage 1 bounded live discovery **PASSED (`GO` for all 3)**; Stage 2 Spec-16 read-only adapters & Stage 3 recorded-replay kernel flow **COMPLETE** on branch `codex/free-mcp-travel-adapters`.

## 1. Working Now (Capability & Execution Modes)

An operator or downstream orchestrator running under the `student_noncommercial` USD 0 profile can now enable any combination of three keyless, anonymous, read-only remote MCP adapters (`seats_aero`, `trivago`, `kiwi`) via `get_default_travel_registry()` or invoke the offline replay harness (`python -m gateway.travel.scripts.smoke_free_mcps --fixture`):

- **Seats.aero (`seats_aero`, domain `award`):** Queries anonymous cached award flights (`get_flights`, up to 60 days ahead, 0 OAuth, USD 0) and normalizes per-passenger miles and taxes scaled to `travelers` into `AwardQuote` (`status="cached"`, `cache_age_seconds=minutes_old*60`, `needs_verification=True`, deep link to `seats.aero/i/<flight_ref>`), feeding directly into `core.transfer.pathfinder.find_transfer_plans` / OPT-2 `solve_pooled_transfer` with `"VERIFY (blocking):"` as checklist step 1.
- **Trivago (`trivago`, domain `hotel`):** Queries live hotel metasearch deals (`trivago-accommodation-search` / `trivago-accommodation-radius-search`) and normalizes multi-advertiser rates, cancellation attributes, pay timing, deep links, and `0..10_000` scaled ratings (`review_scale_source="trivago_0_10_rating_index"`) into `HotelQuote` (`placement="unknown"`, `completeness="taxes_uncertain"`).
- **Kiwi.com (`kiwi`, domain `flight`):** Queries live cash flights (`search-flight`) and normalizes chronological segments, baggage summary, booking links, and virtual-interline/multi-carrier warnings into `FlightQuote` (`completeness="taxes_uncertain"`).

### Execution modes exercised

| Evidence | Scope | What it establishes |
|---|---|---|
| **Bounded live discovery (Stage 1, 2026-11-27)** | Anonymous `tools/list` + 7 read-only `tools/call` probes (`seats_aero`: 3, `trivago`: 2, `kiwi`: 2; total <= 9 ceiling) on `DEL->SIN` (~30d ahead: `2026-12-27`..`30`) | Real endpoint accessibility, HTTP/MCP compatibility (`mcp` Streamable HTTP with `terminate_on_close=False`), non-commercial Terms fit, and real wire schemas |
| **Recorded real-payload replay (Stage 3 offline)** | Sanitized Stage-1 captures saved under `backend/gateway/travel/adapters/*/fixtures/*_live.json`, executed with `socket.socket.connect` blocked | Real live responses normalize cleanly to `AwardQuote`, `HotelQuote`, `FlightQuote` and flow deterministically through `core.optimizer.optimize`, OPT-4 `build_audit_certificate`, and OPT-2 `find_transfer_plans(..., allow_pooling=True)` |
| **Synthetic negative / boundary regressions** | Malformed payloads, prompt-injection text, `bool`/binary `float` rejection, HTTP 429 zero-retry circuit breaking, 1-retry timeout handling, SQLite call-budget exhaustion, AST core-isolation check | Deterministic fail-closed safety behavior offline without network calls |

## 2. Stage 1 Live Discovery & GO / NO-GO Matrix

| Provider | Endpoint | Init / Call Latency | Advertised Tools & Policy | Observed Structured Response Quirks | Decision |
|---|---|---|---|---|---|
| **Seats.aero** | `https://seats.aero/mcp` | `tools/list`: 0.379s; `get_capabilities`: 0.466s; `get_flights`: 0.306s; `get_flight_details`: 0.415s | 7 read-only inventory/reference tools allowlisted; mutations (`create_alert`, `expire_alert`, `book_flight`, `live_search`) & `search_help_docs` excluded/denylisted | `structuredContent=None`; returns optional text warning prefix + **NDJSON** lines (`flight_ref`, `miles_price`, `taxes="$22.46 USD"`, `minutes_old`, `remaining_seats`) + `Operating Carriers:` JSON + `View on seats.aero:` link (10 of 52 DEL→SIN results returned per page). Confirmed anonymous limit: `60` advance days, `1,000` daily req/IP, `live_search=false` | **GO** |
| **Trivago** | `https://mcp.trivago.com/mcp` | `tools/list`: 0.295s; `trivago-accommodation-radius-search`: 9.867s; `trivago-accommodation-search`: 9.564s | All 3 read-only search/trend tools allowlisted; mutation tools denied | `structuredContent=None`; text block contains prose header + JSON `{ "system_message": "...", "output": "<JSON array string>" }` + trailing `image` blocks. Normalized 25 real Singapore properties (`73` advertiser deals in `INR`, e.g., `₹19,934`–`₹48,413`). Adapter strips `system_message`, drops `image` blocks, parses prices via `Decimal`, and excludes binary images from fixtures | **GO** |
| **Kiwi.com** | `https://mcp.kiwi.com` | `tools/list`: 1.096s; `search-flight` (Eco): 5.523s; `search-flight` (Biz): 12.698s | `search-flight` allowlisted; **`feedback-to-devs` explicitly DENYLISTED** (mutating external feedback channel) | `structuredContent=None`; text block returns pure JSON dict (`currency="INR"`, `15` itineraries, e.g. direct `6E1207` `20578 INR`, virtual-interline itineraries carrying `\|` multi-booking IDs and separate low-cost carriers like `OD206\|AK705`). Airport-local segment timestamps lack timezone offsets and are explicitly annotated in `EvidenceMeta.notes` | **GO** |

## 3. End-to-End Deterministic Kernel Flow Demonstrated

Verified offline with recorded real payloads via `python -m gateway.travel.scripts.smoke_free_mcps --fixture` (with `socket.socket.connect` disabled in `evals/test_free_mcp_adapters.py`):

- Normalized `15` Kiwi economy flights (`selected_flight_total_minor = 2_057_800` INR paise), `73` Trivago Singapore hotel deals (`selected_hotel_total_minor = 1_993_400` INR paise), and `2` Seats.aero `2026-12-28` business awards (`75_000` miles + `7_410` CAD cents taxes) -> built `CostedTrip` (`INR`) -> `core.optimizer.optimize` computed `effective_cost_minor = 3_916_700` -> `core.explain.audit.build_audit_certificate` emitted deterministic `trip_snapshot_hash` / `result_hash` -> `core.transfer.pathfinder.find_transfer_plans(..., allow_pooling=True)` produced `"VERIFY (blocking): Confirm business award space..."` as checklist step 1 (and recommends `REDEEM` when evaluated against Kiwi business cash fares).

## 4. Remaining Limitations & Boundaries

- **Disabled by default (`/plan` untouched):** `seats_aero`, `trivago`, and `kiwi` default to `enabled=False` in `get_default_travel_registry()`, gated behind read-once `TRIPWISE_<PROVIDER>_LIVE_ENABLED` and overridden unconditionally by `TRIPWISE_<PROVIDER>_KILL_SWITCH`. `agents/pipeline.py`, `backend/core/`, `backend/core/seeds/`, `contract/openapi.json`, and `frontend/` were not modified.
- **Provider constraints:** Seats.aero anonymous access covers `<= 60` days from today (requests outside `0..60` days return `[]` cleanly with a diagnostic without calling live endpoints) and cached availability only; hotel/flight prices from Trivago and Kiwi do not break out base vs. taxes/ancillaries (`completeness="taxes_uncertain"`, `needs_verification=True`); non-commercial `student_noncommercial` profile only (`supports_commercial_use=False`, `monthly_cost_minor=0`).
- **Kiwi local timestamps:** Kiwi `search-flight` omits timezone offsets on segment timestamps; the normalizer preserves airport-local wall clocks deterministically while tagging `timestamps_airport_local_without_tz_offset` in `EvidenceMeta.notes` and guarding westbound local-clock transitions.
