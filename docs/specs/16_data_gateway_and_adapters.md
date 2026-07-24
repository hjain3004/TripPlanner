# 16 — Live Data Gateway & Provider Adapter Contract

**Status:** Target-prototype specification; do not implement during M1–M3 or F1–F4. The first implementation is G1 after the test-data application works. Active profile: `student_noncommercial`. Current provider facts live in `reports/free_apis.md` and `reports/beat_the_booking_sites_assessment.md`; reports inform review but do not activate an adapter.

## 1. Purpose

Define the only permitted boundary for request-time flight, hotel/rental-stay, award, and related external evidence. The gateway converts heterogeneous provider responses into stable typed quotes while enforcing freshness, price completeness, source classification, active-use profile, credentials, budgets, and failure behavior.

MCP is transport plus a tool contract, not automatic data entitlement. Under `student_noncommercial`, an official, maintainer-hosted, or community MCP may be allowlisted for low-volume read-only experimentation after the student checklist in §7. Production suitability and commercial rights are deliberately not required for this profile. The adapter must still disclose its source method, follow published access controls, avoid circumvention, minimize retention, and fail back to sample evidence.

Under the inactive `commercial_production` profile, the same MCP must pass the full commercial checklist and may need to be replaced with a licensed direct API.

## 2. Non-goals

- Directly crawling booking/search pages from this application at runtime.
- Circumventing CAPTCHAs, bot controls, logins, or geographic restrictions.
- Booking, holding inventory, charging cards, or transferring points.
- Treating sandbox prices as real.
- Storing provider content longer than its licence permits.
- Converting external evidence directly into approved financial KB facts.
- Allowing LLMs or clients to select arbitrary URLs/providers/tools.

## 3. Canonical evidence metadata

All normalized results contain:

```python
class EvidenceMeta(BaseModel):
    provider_id: str
    provider_quote_id: str | None
    source_url: str | None
    deep_link_url: str | None
    retrieved_at: datetime
    expires_at: datetime | None
    status: Literal["live", "cached", "estimated", "stale", "verify_required"]
    cache_age_seconds: int | None
    terms_version: str
    attribution: str | None
    completeness: Literal["complete", "taxes_uncertain", "fees_uncertain", "partial"]
    needs_verification: bool
    notes: list[str]
```

Rules:

- `live` requires the provider to represent the response as current and `now < expires_at` when an expiry exists.
- `cached` requires a known provider/source cache window.
- `estimated` covers sandbox, sample, historical range, and modeled data.
- `stale` is computed by code, never supplied by an LLM.
- `verify_required` applies when the final claim must be checked elsewhere or before an irreversible action.
- `terms_version` identifies the reviewed provider-registry entry, not a URL guessed at runtime.

## 4. Search requests

```python
class TravelerMix(BaseModel):
    adults: int
    children: int = 0
    infants: int = 0

class FlightSearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    travelers: TravelerMix
    cabin: Literal["economy", "premium", "business", "first"]
    nearby_airports: bool = False
    nonstop_only: bool = False
    currency: str

class FlexibleFlightSearchRequest(BaseModel):
    origin: str
    destination: str
    depart_window_start: date
    depart_window_end: date
    return_window_start: date | None
    return_window_end: date | None
    trip_length_nights: int | None
    travelers: TravelerMix
    cabin: Literal["economy", "premium", "business", "first"]
    nearby_airports: bool = False
    nonstop_only: bool = False
    currency: str
    max_date_pairs: int

class HotelSearchRequest(BaseModel):
    city: str
    check_in: date
    check_out: date
    travelers: TravelerMix
    rooms: int
    area_ids: list[str]
    style: Literal["budget", "balanced", "luxury"]
    currency: str
    property_kinds: set[Literal["hotel", "serviced_apartment", "vacation_rental", "hostel"]] = Field(
        default_factory=lambda: {"hotel"}
    )

class FlexibleStaySearchRequest(BaseModel):
    city: str
    window_start: date
    window_end: date
    nights: int
    travelers: TravelerMix
    rooms: int
    area_ids: list[str]
    style: Literal["budget", "balanced", "luxury"]
    currency: str
    property_kinds: set[Literal["hotel", "serviced_apartment", "vacation_rental", "hostel"]]
    max_start_dates: int

class AwardSearchRequest(BaseModel):
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    travelers: TravelerMix
    cabin: Literal["economy", "premium", "business", "first"]
    program_ids: list[str]
```

Requests are validated before adapter selection. The flight and stay workflows expand flexible requests into deterministic exact-date calls, bounded by `max_date_pairs`/`max_start_dates` and provider budgets. A cached trend adapter may reduce which date pairs receive current-quote searches, but it cannot silently broaden the user window. Adapters cannot broaden dates, airports, cabins, occupancy, property kinds, or programs beyond the explicit request unless a separately labeled alternative-search branch authorizes it.

## 5. Normalized quotes

### Flights

```python
class FlightSegment(BaseModel):
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    marketing_airline: str
    operating_airline: str | None
    flight_number: str
    cabin: str
    duration_min: int

class FlightQuote(BaseModel):
    id: str
    segments: list[FlightSegment]
    trip_type: Literal["one_way", "round_trip"]
    travelers: TravelerMix
    fare_brand: str | None
    baggage_summary: str | None
    refundable: bool | None
    changeable: bool | None
    base_minor: int | None
    taxes_minor: int | None
    fees_minor: int | None
    total_minor: int
    currency: str
    purchasable_channels: list[Channel]
    evidence: EvidenceMeta
```

`FlightQuote` represents a concrete itinerary/fare candidate. It requires ordered segment details and can participate in winner selection only when its price scope is sufficiently complete and it remains current or explicitly reverified.

### Flight price observations

```python
class FlightPriceObservation(BaseModel):
    id: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: Literal["economy", "premium", "business", "first"] | None
    stops: int | None
    observed_total_minor: int
    currency: str
    observed_at: datetime
    itinerary_detail: Literal["route_only", "partial"]
    is_bookable: Literal[False] = False
    evidence: EvidenceMeta
```

An observation is cached trend/historical evidence, not a `FlightQuote`. It may rank date bands for follow-up searches and may appear as a clearly labeled estimate. It cannot become the bookable winner, supply missing segments, or be labeled `live`.

### Hotels

```python
class HotelQuote(BaseModel):
    id: str
    property_id: str
    name: str
    property_kind: Literal["hotel", "serviced_apartment", "vacation_rental", "hostel", "other"]
    city: str
    area_id: str | None
    lat: float | None
    lon: float | None
    check_in: date
    check_out: date
    travelers: TravelerMix
    rooms: int
    room_name: str | None
    rate_plan: str | None
    cancellation_summary: str | None
    refundable: bool | None
    review_score_scaled: int | None  # normalized 0..10_000 by adapter/normalizer
    review_scale_source: str | None
    review_count: int | None
    placement: Literal["organic", "sponsored", "unknown"]
    base_minor: int | None
    taxes_minor: int | None
    fees_minor: int | None
    total_minor: int
    currency: str
    pay_timing: Literal["now", "property", "mixed", "unknown"]
    purchasable_channels: list[Channel]
    evidence: EvidenceMeta
```

`HotelQuote` is retained as the contract name but represents normalized accommodation evidence, including vacation rentals. `placement="sponsored"` may be displayed as such but cannot receive a ranking boost. A review score is admitted only with a documented provider scale and is normalized to integer `0..10_000` before ranking; otherwise it remains `None`.

### Awards

```python
class AwardQuote(BaseModel):
    id: str
    program_id: str
    origin: str
    destination: str
    depart_date: date
    return_date: date | None
    cabin: str
    travelers: TravelerMix
    seats_available: int | None
    miles_total: int
    fees_minor: int
    fees_currency: str
    operating_airline: str | None
    mixed_cabin: bool | None
    evidence: EvidenceMeta
```

All money and points are integers. Provider decimals are parsed to integer minor units at the adapter boundary using the currency exponent; no float crosses the boundary.

`SampleFlight` and `SampleHotel` in spec 01 remain fixture models. `SampleAdapter` maps them into `FlightQuote`/`HotelQuote` with `status="estimated"`, declared synthetic dates, incomplete-detail notes, and `needs_verification=True`.

## 6. Adapter contract

```python
class AdapterCapabilities(BaseModel):
    provider_id: str
    domains: set[Literal["flight", "flight_trend", "hotel", "award", "fx", "poi"]]
    countries: set[str] | Literal["configured"]
    live_data: bool
    supports_cache: bool
    supports_commercial_use: bool
    allowed_profiles: set[Literal["student_noncommercial", "commercial_production"]]
    source_method: Literal[
        "sample", "official_api", "provider_mcp", "community_mcp",
        "scraper_wrapper", "open_data"
    ]
    stability: Literal["stable", "experimental"]
    requires_user_initiated_search: bool
    max_concurrency: int

class TravelProviderAdapter(Protocol):
    capabilities: AdapterCapabilities
    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]: ...
    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]: ...
    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]: ...
    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]: ...
```

An adapter may implement only declared domains; unsupported methods return a typed `unsupported_domain` error. Provider SDK objects never escape the adapter.

## 7. Provider registry and activation

Every enabled adapter has a reviewed registry entry:

```yaml
provider_id: example
enabled: false
active_profile: student_noncommercial
domains: [flight]
transport: direct_api
source_method: official_api
stability: experimental
base_urls: [https://api.example.invalid]
credential_ref: EXAMPLE_API_KEY
allowed_countries: [IN, SG]
allowed_use: noncommercial_demo
visibility: local_or_portfolio_demo
terms_version: "reviewed-YYYY-MM-DD"
cache_policy:
  allowed: false
  ttl_seconds: 0
retention:
  raw_response_seconds: 0
attribution: null
request_budget:
  calls_per_plan: 2
  monthly_cost_minor: 0
timeouts:
  connect_seconds: 3
  total_seconds: 12
```

### Student-profile activation (active)

Activation requires a short, recorded review of:

1. provider/server owner and fixed endpoint;
2. source method (`official_api`, `provider_mcp`, `community_mcp`, `scraper_wrapper`, or `open_data`);
3. non-commercial/personal/demo use fit and current terms snapshot;
4. anonymous versus credentialed access (credentials still require human approval);
5. live versus sandbox semantics and geographic coverage;
6. read-only tools/endpoints; booking/payment/transfer tools disabled;
7. robots/access-control behavior where relevant; no override or circumvention;
8. data sent, attribution, cache/retention uncertainty, and visible warning;
9. call/latency/zero-spend ceilings and shutdown switch;
10. failure fixture plus `SampleAdapter` fallback.

Experimental or unclear-source adapters are feature-flagged, low-volume, never a sole dependency, and normally carry `needs_verification=True`.

### Commercial-profile activation (inactive)

If commercialization is ever authorized, re-review from zero:

1. written commercial/account eligibility;
2. live versus sandbox semantics;
3. geographic and commercial permission;
4. AI/agent use rights;
5. caching, storage, forwarding, and retention;
6. attribution/display requirements;
7. rate limits and financial exposure;
8. permitted endpoints and read-only behavior;
9. privacy/data sent;
10. expiry/deactivation date and owner.

No adapter becomes enabled because a package or MCP server was installed.

### Current student-profile candidates (re-verify before implementation)

| Adapter | Intended use | Initial status |
|---|---|---|
| `SampleAdapter` | Complete deterministic fallback | Required, enabled by default |
| `GondolaAdapter` | Read-only hotel cash/points, flexible-night, direct-link, and cash-flight evidence | Preferred first live spike; anonymous search only |
| `TravelpayoutsTrendAdapter` | Cached flight date/route price observations | Optional free-token source; never emits live/bookable quotes |
| `DuffelSandboxAdapter` | Flight schema, expiry, fare-condition, and error fixtures | Test/development only; always estimated, prices/schedules not real |
| `OpenBnBAdapter` | Vacation-rental search and price evidence | Experimental; local/demo-only, low-volume, feature-flagged, always verify |

Provider-calculated cents-per-point, rewards, card coverage, or portfolio recommendations are evidence only. The kernel recomputes every value used in our recommendation.

Google Flights is not an adapter candidate: its consumer fare search has no open student API. The product may generate an allowlisted user verification/deep link; it does not scrape Google Flights.

## 8. Freshness state machine

```text
provider response
  ├── sandbox/sample/range ───────────────▶ estimated
  ├── cached flight trend ────────────────▶ cached observation (never quote)
  ├── provider-declared cache ────────────▶ cached
  └── current quote inside TTL ───────────▶ live

live/cached + expiry passed ──────────────▶ stale
any state requiring first-party check ───▶ verify_required
```

`verify_required` may be an additional flag in implementation when the UI needs both origin (`live`/`cached`) and required action. Until then, choose the more conservative visible status and retain the original status in `notes`.

Before final assembly:

- re-check the winning quote's expiry;
- if expired, re-query that adapter at most once when budget permits;
- otherwise mark stale and keep a verification link or choose a fresh runner-up;
- never silently extend TTL.

## 9. Price completeness

Quotes are comparable only when traveler mix, dates, trip type, cabin/room, currency, and total-price scope align.

- `complete`: total includes mandatory known taxes/fees for the requested travelers.
- `taxes_uncertain` or `fees_uncertain`: may appear as an alternative but cannot win against a materially comparable complete quote solely on price.
- `partial`: excluded from effective-cost ranking unless no complete evidence exists; UI must say what is missing.

Currency conversion uses the deterministic FX path and retains both source amount and converted amount. It never overwrites the provider amount.

## 10. Normalization and deduplication

### Flight identity

Hash ordered segments using origin, destination, departure, arrival, operating carrier, and flight number. Fare variants with different baggage/refundability remain separate.

`FlightPriceObservation` identity uses provider + route + dates + cabin/stops + observed time bucket. Observations are never de-duplicated into `FlightQuote`.

### Hotel identity

Prefer reviewed provider crosswalks. Otherwise normalize name + geospatial proximity conservatively; uncertain matches stay separate. Room/rate-plan variants remain separate. Hotel and vacation-rental identities are never merged merely because their names or coordinates are similar.

### Award identity

Program + dates + origin/destination + cabin + operating carrier. Cached and live observations remain separate evidence records even when grouped in the UI.

Deduplication never discards:

- a materially different cancellation/fare condition;
- a price-completeness difference;
- a provider disagreement above the configured threshold;
- a fresher quote that supersedes an older one.

## 11. Ranking boundary

The gateway may rank provider evidence for relevance and completeness but cannot calculate card rewards, transfer value, or effective trip cost. The kernel performs financial comparison.

Pre-kernel deterministic filters may consider:

- exact request match;
- duration/stops;
- itinerary feasibility;
- hotel area/distance;
- cancellation/refundability;
- freshness and completeness;
- user hard constraints.

Provider commission or affiliate payout must never influence user-value ranking unless transparently separated and explicitly authorized.

For flexible-stay comparisons:

- generate start dates deterministically and stop at `max_start_dates`;
- calculate cheapest/most-expensive windows only from comparable completeness states;
- aggregate neighborhood price bands only above a configured minimum result count;
- compare same-property rates only after entity, occupancy, room/rate, dates, and mandatory-fee scope match;
- do not use `review_score / price` until review scales are normalized and confidence is sufficient;
- sponsored placement is never a positive ranking signal.

For flexible-flight comparisons:

- generate date/date-pair candidates deterministically and stop at `max_date_pairs`;
- optionally use cached observations to prioritize which pairs receive current searches;
- label cached minima as “observed price trend,” not “current cheapest fare”;
- require a concrete `FlightQuote` or user verification before selecting a bookable winner;
- do not infer missing segments, baggage, taxes, or fare conditions from a trend;
- keep cash-fare and award-seat rankings separate until the kernel compares complete artifacts.

## 12. Cache and retention

- Cache behavior is provider-specific and deny-by-default.
- Cache keys include all request fields that can affect price/availability.
- TTL is the minimum of provider permission, provider expiry, and configured product freshness.
- Raw payload retention is separate from normalized quote retention.
- Deletion jobs enforce expiry/contract requirements.
- The approved KB is not a cache for live quotes.
- Test fixtures require explicit sanitization and retention permission.

## 13. Reliability

Typed gateway errors:

```text
provider_unavailable
authentication_failed
permission_denied
rate_limited
budget_exhausted
timeout
invalid_response
no_results
unsupported_domain
region_restricted
terms_disabled
```

Retry matrix:

- transient network/5xx: at most one bounded retry with jitter;
- 429: honor `Retry-After` only within job deadline, otherwise fail soft;
- auth/permission/region/terms: no retry;
- invalid response: no retry; record sanitized validation path;
- empty valid response: success with zero results.

Circuit breakers are per adapter and do not disable `SampleAdapter`.

## 14. Credentials and request security

- Secrets are never committed, sent to the frontend, logged, or included in LLM context.
- Base URLs and endpoint paths are code/config allowlisted.
- Redirects are disabled or restricted to approved hosts.
- Request and response size limits are enforced.
- User-controlled free text never becomes a header, URL, or provider query without typed validation.
- Provider webhooks, OAuth, bookings, and payments are out of this contract.

## 15. Cost and rate limits

The gateway reserves budget before fan-out. If a provider has monetary exposure, the registry must define a hard monthly and per-plan ceiling. Unknown cost means disabled.

Selection order is deterministic:

1. enabled and eligible for the active use profile;
2. supports requested domain/country;
3. remaining quota/budget;
4. configured priority;
5. lexicographic provider id.

The orchestrator never asks an LLM which provider to call.

## 16. Testing

Every adapter must pass:

- capability/registry validation;
- success fixture;
- empty result;
- malformed provider payload;
- missing tax/fee fields;
- stale/expired quote;
- rate limit;
- authentication/permission failure;
- timeout;
- currency precision;
- deterministic quote IDs;
- secret/log redaction.

Flight-specific tests additionally assert:

- a `FlightPriceObservation` cannot validate as or be promoted to `FlightQuote`;
- Duffel test-mode evidence is always `estimated`;
- cached trend evidence is never `live` or bookable;
- expired cash quotes cannot win without one bounded refresh;
- an award recommendation without current availability remains `verify_required`.

Gateway-wide tests cover deduplication, disagreement, budget reservation, circuit breaking, clock-controlled expiry, and SampleAdapter parity.

Normal CI has no external network. A manual live smoke test requires an explicit zero/approved cost ceiling, read-only endpoint, and sanitized output. Credentials are required only when the selected provider requires them and always need human approval.

## 17. Frontend contract

The report exposes only normalized summaries and display-safe metadata:

- trust state and retrieved/expiry time;
- provider display name/attribution;
- complete source price and currency;
- deterministic converted/effective values;
- material limitations;
- safe deep/verification link.

The UI must render `live`, `cached`, `estimated`, `stale`, and `verify_required` distinctly but calmly. It must never label a sandbox quote live or hide missing taxes/fees.

## 18. G1 gate

G1 is complete when:

- normalized models and registry validation exist;
- `SampleAdapter` maps existing fixtures with `estimated` state;
- `FlightPriceObservation` is structurally non-bookable and cannot validate as `FlightQuote`;
- flexible-flight date generation is deterministic and budget-bounded;
- flexible-stay window generation and comparison are deterministic and budget-bounded;
- the complete demo plan produces the same optimizer/pathfinder numbers through the gateway;
- all gateway tests use recorded/local fixtures and pass without network;
- `backend/core/` has no gateway/provider imports;
- secrets audit is clean;
- OpenAPI snapshot, frontend generated types, MSW fixtures, and trust-state UI change together if the public contract is extended.
