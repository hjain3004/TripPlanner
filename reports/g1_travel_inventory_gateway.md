# G1 — Travel Inventory Gateway Foundation

**Milestone status:** complete
**Branch:** `feat/g1-travel-inventory-gateway`
**Base:** `main` @ `7a490bc` (post accounts-persistence merge, PR #5; PR #8 i8a already merged)
**Authoritative specs:** 09 §13 ("G1 — Contracts and sample gateway"), 16 (full)

## 1. Scope and non-goals

G1 is the first target-platform milestone after the Kernel MVP + frontend passed F4. Per
spec 09 §2 ("The app must build and run end-to-end with only `SampleAdapter`") and spec 16
§18's explicit G1 gate, this milestone builds the provider-neutral travel inventory
contracts, a validated registry, the required `SampleAdapter`, a recorded-fixture harness,
and deterministic bounded flexible-date generation — and proves the existing DEL→SIN sample
journey produces byte-identical optimizer/transfer-pathfinder numbers whether costed through
the new gateway or the pre-existing direct-sample path.

**Explicitly out of scope (none implemented or activated):** Gondola, Travelpayouts, Duffel,
OpenBnB, seats.aero, Tripadvisor live transport, any other MCP or live travel provider,
Google Flights scraping, runtime crawling, browser automation, bookings/holds/payments/
points-transfer execution, accounts/authentication, saved trips, card acquisition, public
deployment, frontend redesign, new LLM call sites, dynamic provider discovery, LLM-selected
providers, real financial data replacing seed placeholders, paid credentials, or positive
provider spend. `search_flight_price_trends` returns a typed `unsupported_domain` error —
no trend fixture or adapter exists in this repo. `agents/pipeline.py`'s production wiring was
**not** switched to the gateway path (see §9).

## 2. Architecture implemented

A new `backend/gateway/travel/` package:

```
gateway/travel/
    __init__.py
    contracts.py    # EvidenceMeta, 5 search requests, 5 quote/observation models
    errors.py        # TravelGatewayError, 11 spec-16 typed codes
    protocol.py       # AdapterCapabilities, TravelProviderAdapter Protocol
    freshness.py       # compute_status/is_expired — code-computed, clock-injected
    identity.py         # deterministic quote/observation id hashing
    flexible.py           # bounded flexible-flight/stay date generation
    registry.py             # TravelProviderRegistry, deterministic selection
    fixtures/
        transport.py          # FixtureTravelTransport replay seam (for future G3+ adapters)
        data/*.json              # 8 sanitized fixtures (success/empty/malformed/partial/
                                  # stale/rate_limited/auth_failed/timeout)
    adapters/
        sample.py                 # required, enabled-by-default SampleAdapter
```

Plus one new orchestration-layer module, `backend/agents/gateway_estimator.py`, and a pure
rename in `backend/agents/estimator.py` (7 previously-private helpers made public so the new
module can reuse them — zero behavior change, verified against the pre-refactor green
baseline before any new code was added).

**Boundary discipline:** `backend/core/` never imports `backend/gateway/` — machine-checked
by an AST-walking test (`evals/test_travel_boundary.py::test_core_never_imports_gateway`).
Gateway/provider objects (`FlightQuote`, `HotelQuote`, ...) never reach
`core.optimizer`/`core.transfer.pathfinder`: `agents/gateway_estimator.py` converts every
winning quote into the same `SpendLineItem`/`SampleFlight`/`SampleHotel` types the legacy
path already produces before anything downstream sees it.

## 3. Contract summary (spec 16 §3–§5)

- `EvidenceMeta`: all 12 spec fields, `AwareDatetime` timestamps (naive datetimes rejected),
  the 5 required `status` values, the 4 required `completeness` values. Two code-enforced
  invariants beyond the letter of the spec: `status="live"` is rejected if
  `retrieved_at >= expires_at`, and rejected outright whenever `provider_id` starts with
  `"sample_"` — the "a sample/sandbox quote can never be labeled live" rule is enforced in
  one place, not left to adapter discipline.
- `TravelerMix`, `FlightSearchRequest`, `FlexibleFlightSearchRequest`, `HotelSearchRequest`,
  `FlexibleStaySearchRequest`, `AwardSearchRequest`: uppercase IATA/currency normalization,
  return/checkout-not-before-depart/checkin validators, `rooms > 0`, `max_date_pairs`/
  `max_start_dates` bounded `(0, 31]` (spec 16 requires "bounded" without a number — 31 is
  the conservative finite choice, logged in `DEVIATIONS.md`).
- `FlightSegment`/`FlightQuote`: non-empty ordered segments, chronological
  arrival-after-departure, non-negative integer money fields.
- `FlightPriceObservation`: `is_bookable: Literal[False] = False` (constructing it with
  `True` raises `ValidationError`); a dedicated test round-trips an observation's
  `model_dump()` through `FlightQuote.model_validate(...)` and asserts it fails —
  the anti-promotion boundary is proven structurally, not just typed.
- `HotelQuote`: `check_out > check_in`; `review_score_scaled` (`0..10_000`) requires
  `review_scale_source`; missing `lat`/`lon` stay `None`.
- `AwardQuote`: integer `miles_total`/`fees_minor`; sample evidence cannot be `live`.

## 4. SampleAdapter behavior

`SampleAdapter` maps the **existing** `core.db.KnowledgeBase.sample_flights`/
`sample_hotels` seed rows — not invented data — into `FlightQuote`/`HotelQuote`:

- Every result: `status="estimated"`, `needs_verification=True`, deterministic
  constructor-injected `retrieved_at` (no wall clock), deterministic quote IDs
  (`gateway.travel.identity`), original seed amount preserved unmodified
  (`total_minor == flight.price_minor` / `== hotel.price_per_night_minor * nights`).
- `SampleFlight` has no real segment times or flight number; `SampleAdapter` synthesizes one
  segment per quote (never fake intermediate airports for `stops > 0`), a fixed synthetic
  `09:00 UTC` departure, `duration_min = 240 + 120*stops`, and `flight_number =
  "SAMPLE-{id}"` — all documented in `evidence.notes`, never used in any money computation.
- `completeness="taxes_uncertain"` on every quote (tax/fee breakdown genuinely unavailable
  in the fixture); `base_minor`/`taxes_minor`/`fees_minor` stay `None` rather than being
  invented.
- `search_awards` returns `[]`: no genuine sample award-availability fixture exists in this
  repo, so it honestly returns empty instead of fabricating availability.
- `search_flight_price_trends` raises `TravelGatewayError("unsupported_domain", ...)`.
- No network, no credentials, no wall clock (`test_travel_sample_adapter.py::test_no_network_calls`
  monkeypatches `socket.socket.connect` to raise and re-runs a live call through the adapter).

## 5. Fixture strategy

`gateway/travel/fixtures/transport.py::FixtureTravelTransport` is a reusable local-fixture
replay seam for **future** (G3+) live adapters — `SampleAdapter` itself does not use it,
since its "fixture" is the already-committed seed database, not JSON files. It reads only
committed sanitized JSON under `gateway/travel/fixtures/data/`, enforces a 512 KB payload
bound, and covers all 8 required scenarios (success, empty, malformed, partial-price, stale,
rate-limited, auth-failed, timeout). A fixture that (accidentally or maliciously) claims
`"status": "live"` is rejected with `invalid_response` — proven by
`test_fixture_cannot_claim_live_status`, which mutates a copy of the success fixture to claim
`live` and asserts the transport still refuses it.

## 6. Flexible-date behavior

`gateway/travel/flexible.py`: pure, deterministic, no LLM/provider/I/O involvement.
`generate_flight_date_pairs` never produces a date outside the declared window, respects
`trip_length_nights` when supplied, falls back to enumerating the return window otherwise (or
one-way `None` when neither is given), stops at `max_date_pairs`, and is
chronologically-ordered/byte-identical across repeated calls. `generate_stay_windows` is the
same shape for hotel stays, bounded by `max_start_dates`, and returns `[]` (not an error)
when the window can't fit even one full stay of the requested length. `stay_windows_comparable`
implements spec 16 §11's comparability rule (same property/dates/rooms/travelers/room/rate/
currency); `placement` never gates comparability (proven by a dedicated test), matching the
"sponsored placement is never a ranking signal" rule.

## 7. Direct-vs-gateway parity evidence

`agents/gateway_estimator.py::estimate_costed_trip_via_gateway` builds spec 16 search
requests from `TripSpec`, selects `SampleAdapter` through
`gateway.travel.registry.get_default_travel_registry()`, applies the **same**
winner-selection rule the legacy `agents/estimator.py` uses (cheapest by
`(total_minor, stops, id)` for flights — `stops` recovered from `SampleAdapter`'s own
deterministic `duration_min` encoding; exact case-insensitive area match then
centrality-fallback for hotels), and maps the winner back to a `SpendLineItem` using the same
currency-conversion order as the legacy path (per-night amount converted, then multiplied by
nights — required for byte-identical FX-rounding parity in any future non-home-currency
corridor, even though the DEL→SIN demo's flight/hotel are already priced in INR = home
currency).

`evals/test_travel_gateway_parity.py` (9 tests) proves, for the DEL→SIN demo scenario
(`origin=DEL, destination=SIN, travelers=2, style=balanced, wallet={hdfc-infinia,
axis-atlas, voyager-prime: 140000}, booking_date=2026-07-25`):

- `CostedTrip.lines` — **identical** for both paths, including exact amounts:
  `flight:del-sin-6e-eco = 8,200,000` minor, `hotel:sg-hotel-marina-balanced = 6,400,000`
  minor. `legacy.costed_trip.model_dump() == gateway.costed_trip.model_dump()` (full
  structural equality, not just line totals).
- `OptimizerResult` — **identical** `gross_minor`, `effective_cost_minor`, and full
  `model_dump()` equality between the two paths after both are run through the unmodified
  `core.optimizer.optimize()`.
- `TransferAdvice` — **identical** `plans` (non-empty, asserted non-vacuous) and full
  `model_dump()` equality after both are run through the unmodified
  `core.transfer.pathfinder.find_transfer_plans()`.
- Hotel area-fallback (centrality) selects the same winner on both paths when the requested
  area has no exact hotel.
- Hotel area matching is case-insensitive on both paths (regression test added after code
  review — see §10).
- A synthetic non-home-currency scenario (isolated temp seed set, not the committed
  `core/seeds/`) proves the per-night-then-multiply FX conversion order is load-bearing: with
  a hotel priced at 333 minor/night × 3 nights = 999 total and a deliberately chosen FX rate,
  `floor(999 × rate) ≠ floor(333 × rate) × 3` — the gateway and legacy paths agree
  (`amount_minor == 0` on both), which a total-first conversion order would not.

## 8. Tests added

**130 new tests**, all green, across 11 new files:

| File | Tests | Covers |
|---|---|---|
| `test_travel_contracts.py` | 36 | search-request validation, quote/observation invariants, anti-promotion |
| `test_travel_errors.py` | 14 | typed error codes, secret redaction |
| `test_travel_protocol.py` | 5 | `AdapterCapabilities` validation |
| `test_travel_identity.py` | 9 | deterministic quote/observation/hotel/award IDs |
| `test_travel_freshness.py` | 8 | live/cached/estimated/stale transitions, injected clock |
| `test_travel_flexible.py` | 16 | bounded flexible-date generation, stay comparability |
| `test_travel_registry.py` | 12 | capability/profile/country/cost filtering, deterministic ordering |
| `test_travel_fixtures_harness.py` | 12 | all 8 fixture scenarios, live-claim rejection, payload bound |
| `test_travel_sample_adapter.py` | 11 | seed mapping, determinism, no-network, unsupported-domain |
| `test_travel_gateway_parity.py` | 9 | the non-vacuous DEL→SIN direct-vs-gateway parity proof |
| `test_travel_boundary.py` | 4 | AST import boundary, zero-network guard, secret-marker scan |

Backend regression baseline moves from **717 → 847** tests (130 new, 0 removed, 0 modified
existing test).

## 9. Wiring decision (production pipeline)

`agents/pipeline.py` still calls `agents.estimator.estimate_costed_trip` (the legacy path),
**not** `estimate_costed_trip_via_gateway`. Spec 16 §18's G1 gate requires proving parity,
not switching the live pipeline; CLAUDE.md's build-order instruction directs the most
conservative choice once parity is established. Swapping production wiring in this milestone
would touch every existing integration/E2E test and the F-series frontend contract for zero
product benefit today, since the gateway has exactly one adapter that already produces
byte-identical numbers to production. `estimate_costed_trip_via_gateway` exists as a proven,
tested, swappable seam, ready to become the default once a live G3 adapter gives users an
actual behavior difference worth exposing. Logged in `DEVIATIONS.md`.

## 10. Required code review

Ran `superpowers:requesting-code-review` (a `general-purpose` subagent, given the full
`main...feat/g1-travel-inventory-gateway` diff plus specs 09/16) after Task 11's boundary
tests but before this report was written. Full review scope: it independently re-derived
both non-obvious arithmetic tricks (the `stops`-recovery from `duration_min`, and the
per-night-then-multiply FX rounding order) rather than taking the code comments' word for
it.

**Findings and resolutions:**

- **Important — hotel area matching case-sensitivity mismatch.** The gateway's exact-area
  match (`gateway_estimator.py::_select_hotel_winner`) used plain `==`, while the legacy
  `KnowledgeBase.sample_hotels(city, style, area)` casefolds. Latent divergence, not
  exercised by any existing test. **Fixed**: casefolded the comparison; added
  `test_gateway_hotel_area_match_is_case_insensitive_like_legacy`.
- **Important — FX-rounding-order fix was unexercised.** The per-night-then-multiply
  conversion order (the one genuinely novel arithmetic decision in this diff) was only ever
  run on a corridor where hotel currency already equals home currency, so the risky branch
  of `price_in_home` never actually executed in any test. **Fixed**: added an isolated
  synthetic-seed regression test (`test_gateway_hotel_currency_conversion_matches_legacy_when_currency_differs_from_home`)
  proving the specific rounding-order property the DEVIATIONS.md entry claims.
- **Important — milestone documentation gap.** This report and the CLAUDE.md/AGENTS.md
  checkpoint update had not yet been written when the review ran. **Fixed**: this report, and
  §14 below.
- **Minor — `SampleAdapter.search_hotels` doesn't filter `area_ids`/`property_kinds`.**
  **Fixed**: added an inline comment explaining this is deliberate (filtering happens in the
  orchestration layer, matching the legacy path's own two-step structure).
- **Minor — function-local `TravelGatewayError` import in `registry.py`.** **Fixed**:
  hoisted to a top-level import (no circularity: `gateway.travel.errors` does not import
  `gateway.travel.registry`).

No Critical findings. Reviewer's final assessment before fixes: "Ready to merge: With
fixes" — all fixes applied test-first, full gate re-run green afterward (see §12).

## 11. Zero-network / security / secrets audit

- `grep -rEn "sk_live|api[_-]?key\s*=|Authorization:\s*Bearer|BEGIN (RSA|EC) PRIVATE KEY|password\s*="`
  over `gateway/travel/` and `agents/gateway_estimator.py`: **no matches**.
- `grep -rl "requests\.|httpx\.|urllib\.request|socket\.|aiohttp"` over the same scope:
  **no matches** — no HTTP/socket client code exists anywhere in the new package.
- Three independent `socket.socket.connect` monkeypatch guards (adapter-level, boundary-test
  level, and gateway-estimator-level) all pass with real, non-empty results returned — proof
  the guarded code paths actually executed rather than short-circuiting before reaching a
  network call.
- No `.env` changes; no new environment variables; no credentials of any kind referenced.
- `TravelGatewayError` reuses the existing `gateway.places.registry.redact_secret` utility
  (a generic string-scrubbing function, not a places-specific object) so error messages are
  scrubbed consistently across both gateway packages.

## 12. Full gate output (final run, post code-review fixes)

```
--- pytest (full suite) ---
847 passed, 4 warnings in 76.80s

--- mypy --strict (core/ accounts/ agents/ api/ gateway/) ---
Success: no issues found in 113 source files

--- ruff (accounts/ agents/ gateway/ evals/) ---
All checks passed!

--- ruff (core/ + api/: legacy debt, ratcheted, must not grow) ---
core/ + api/ ruff findings: 7 (ceiling 12)   # pre-existing, unrelated to G1

--- frozen artifacts ---
GOLDENS_OK
CONTRACT_OK (unchanged, or changed with codegen and fixtures)
BRIEFS_IDENTICAL

--- working tree ---
TREE_CLEAN

================ GATE PASSED ================
```

`git diff --exit-code -- backend/evals/golden/`: clean (no golden expected value touched).
`diff CLAUDE.md AGENTS.md`: identical (verified again after the checkpoint update in this
same commit — see §14).

## 13. Deviations recorded

10 new Tier-C entries under `## G1 — Travel Inventory Gateway Foundation` in
`DEVIATIONS.md`: the `max_date_pairs`/`max_start_dates` numeric bound, the
sample-provider-cannot-claim-live enforcement mechanism, the registry-as-Python-not-YAML
choice, the synthetic flight-segment-timing mapping, the taxes-uncertain completeness
default, the no-adapter-side-FX-conversion boundary, the `stops`-recovery-from-`duration_min`
tie-break trick, the per-night-then-multiply FX rounding-order fix, the
`EstimatorResult.flight`/`.hotel` compatibility shim, and the production-wiring decision.
Every entry states the question, the conservative decision made, and the rationale, per spec
06 §3's format.

## 14. Remaining limitations

- No live provider or adapter beyond `SampleAdapter` exists yet (by design — G2/G3 are
  separate future milestones per spec 09 §13).
- `search_flight_price_trends` has no real implementation or fixture in this repo; it
  correctly raises `unsupported_domain`, but no `FlightPriceObservation`-producing adapter
  exists to exercise that contract end-to-end against real trend data.
- The production `/plan` pipeline is intentionally not yet routed through the gateway (§9) —
  this is deliberate scope discipline, not an oversight, but it means the gateway's real-world
  request-time behavior (as opposed to its tested behavior) remains unverified until a future
  milestone flips the wiring.
- `AwardQuote`/`search_awards` has no genuine sample fixture; it is contract-complete and
  tested for the empty case, but no non-empty award-availability path exists yet.
- The `core/` + `api/` ruff legacy-debt ceiling (7/12 findings) is pre-existing and untouched
  by this milestone; it was not grown, but also not reduced.

## 15. Confirmation

No live provider, MCP, credential, paid service, booking, crawling, or transfer execution was
activated, added, or exercised at any point in this milestone. All 130 new tests run against
local, sanitized, committed fixtures and the existing seed database only; the zero-network
guards (§11) are non-vacuous and independently verified. `SampleAdapter` is the only enabled
provider, with `monthly_cost_minor=0` and `live_data=False`.
