# 01 — Data Model & Knowledge Base Schema

This is the foundation of the whole system. The schema must be expressive enough to represent real credit-card reward programs, which involve: category/MCC-conditioned earn rates, per-cycle caps, portal-only accelerations, exclusion lists, milestone bonuses, redemption-path-dependent point values, forex markup **plus tax on the markup** (India: 18% GST on the markup), and offers with stacking constraints and expiry. If the schema can't represent a rule, the optimizer can't reason about it — extend the schema rather than special-casing in code.

Storage: SQLite via SQLAlchemy. All interfaces are Pydantic v2 models; DB rows serialize to/from them. Money is stored as **integer minor units** (paise/fils/cents) with a `currency` code — never floats. Percentages are stored in **basis points** (int; 2.36% = 236 bp). Dates are ISO-8601 strings (SQLite) mapped to `date`/`datetime`.

---

## 1. Provenance (applies to every fact table)

Every table that can influence a recommendation embeds these columns:

```python
class Provenance(BaseModel):
    source_url: str | None          # where the fact came from (bank page, T&C PDF, manual)
    source_type: Literal["official_page", "tnc_pdf", "manual_curation", "crawl_draft"]
    last_verified: date             # when a human last confirmed this fact
    verified_by: str                # curator id, or "UNVERIFIED"
    needs_verification: bool        # True on all shipped seed data
    confidence: float               # 0.0–1.0 curator-assigned
    notes: str | None
```

Rule: the optimizer may use `needs_verification=True` facts, but must propagate the flag so the report renders a warning on any recommendation derived from them. Facts older than `STALENESS_DAYS` (default 90) for offers, 365 for card rules, get an automatic staleness warning.

## 2. Enumerations

```python
class SpendCategory(str, Enum):
    FLIGHTS = "flights"; HOTELS = "hotels"; DINING = "dining"
    GROCERY = "grocery"; TRANSIT = "transit"; ATTRACTIONS = "attractions"
    SHOPPING = "shopping"; FOREX_GENERAL = "forex_general"  # generic intl POS spend
    OTA = "ota"; INSURANCE = "insurance"; OTHER = "other"

class Channel(str, Enum):
    DIRECT_AIRLINE = "direct_airline"; DIRECT_HOTEL = "direct_hotel"
    OTA_GENERIC = "ota_generic"          # e.g. MMT, Cleartrip, Agoda
    BANK_PORTAL = "bank_portal"          # e.g. issuer travel portal (SmartBuy-class)
    POS_ABROAD = "pos_abroad"            # physical/online spend in destination currency
    POS_DOMESTIC = "pos_domestic"

class RedemptionPath(str, Enum):
    CASHBACK = "cashback"; PORTAL_FLIGHTS = "portal_flights"
    PORTAL_HOTELS = "portal_hotels"; TRANSFER_AIRLINE = "transfer_airline"
    TRANSFER_HOTEL = "transfer_hotel"; VOUCHER = "voucher"

class OfferKind(str, Enum):
    INSTANT_DISCOUNT = "instant_discount"   # reduces amount paid now
    CASHBACK_LATER = "cashback_later"       # statement credit after N days
    BONUS_POINTS = "bonus_points"
    NO_COST_EMI = "no_cost_emi"             # out of MVP scope for optimization; store only
```

`SpendCategory` is the MVP abstraction over MCCs. Keep an optional `mcc_codes: list[int]` on rules for future precision, but matching in MVP is category-based (see 02 §4).

## 3. `cards`

```python
class Card(BaseModel):
    id: str                      # slug, e.g. "hdfc-infinia"
    issuer: str                  # "HDFC Bank"
    network: Literal["visa", "mastercard", "amex", "rupay", "diners"]
    network_tier: Literal["infinite", "signature", "world_elite",
                          "world", "platinum", "centurion", "reserve"] | None = None
                                 # scheme tier, e.g. Visa Infinite vs Signature.
                                 # Optional: every existing seed row and golden
                                 # expectation stays valid with this unset.
    country: Literal["IN", "AE", "US"]
    name: str
    annual_fee_minor: int
    fee_currency: str            # "INR"
    forex_markup_bp: int         # e.g. 200 = 2.00%
    forex_markup_tax_bp: int     # tax ON THE MARKUP, e.g. India GST 1800 = 18%
                                 # effective forex cost = markup * (1 + tax) → 2% * 1.18 = 2.36%
    base_earn: EarnRate          # default earn when no rule matches
    lounge_intl_visits_per_year: int | None   # stored for report color; not optimized in MVP
    provenance: Provenance
```

```python
class EarnRate(BaseModel):
    points: int                  # points earned...
    per_amount_minor: int        # ...per this much spend, e.g. 5 points per ₹150 → points=5, per_amount_minor=15000
    currency: str                # currency of per_amount ("INR")
```

Modeling earn as `points per amount` (not a float multiplier) matches how issuers state rules and avoids rounding ambiguity. Rounding rule: points floor per **transaction** (`floor(txn_amount / per_amount) * points`). This is the industry norm; make it a constant so it can be flipped per-card later if needed.

### 3.1 `network_benefits` — scheme tier entitlements

`network` alone cannot express what a cardholder is actually entitled to. Visa Infinite and Visa Signature are the same scheme with materially different benefits; so are Mastercard World Elite and World. Tier entitlements (lounge programs, golf, Infinite's Luxury Hotel Collection, minimum travel insurance floors) are published by the scheme, apply across every issuer's card at that tier in a country, and therefore belong in their own table rather than duplicated onto each `Card`.

```python
class NetworkBenefit(BaseModel):
    id: str
    network: Literal["visa", "mastercard", "amex", "rupay", "diners"]
    network_tier: str                        # matches Card.network_tier
    country: Literal["IN", "AE", "US"]       # entitlements are country-scoped
    lounge_program: str | None               # "Priority Pass", "LoungeKey", ...
    lounge_visits_per_year: int | None       # None = unlimited or unspecified
    golf_access: str | None
    hotel_collection: str | None             # "Visa Luxury Hotel Collection"
    travel_insurance_summary: str | None     # prose floor, not a computed value
    concierge: bool = False
    notes: str | None
    provenance: Provenance                   # scheme-published, verified like any fact
```

Lookup key is `(network, network_tier, country)`. A card with `network_tier=None` matches no `NetworkBenefit` row and simply renders nothing — this is why the field is optional.

**Composition with offers — read this before implementing.** `NetworkBenefit` rows are **report-only**. They are never scored, never enter the optimizer's benefit function, and **never enter the offer stacking order** (02 §6). The precedent is already in this document: §3's `lounge_intl_visits_per_year` is "stored for report color; not optimized in MVP." Tier entitlements are the same kind of thing — durable perks of holding the card, not per-transaction discounts — so they get the same treatment.

This is what makes the addition provably additive. The frozen stacking rule (per line item, at most one offer per `stacking_class`; `coupon` applied before `bank_offer`) is untouched, no new value enters `benefit`, and no golden expected value moves. **There is no Tier-F conflict to resolve here, and an implementer must not create one** by trying to score entitlements into the allocation.

The distinction to hold onto:

| Thing | Model | Optimized? |
|---|---|---|
| Network-targeted promo ("10% off with any Visa") | `Offer` with `networks` set | Yes — stacks normally |
| Tier entitlement ("Infinite includes Priority Pass") | `NetworkBenefit` | No — report only |

If a scheme runs a *promotion* restricted to a tier, that is an `Offer`, not a `NetworkBenefit` — see §6.

## 4. `reward_rules` — the heart of the schema

A card has 0..n rules. A rule *overrides* the card's base earn when it matches.

```python
class RewardRule(BaseModel):
    id: str
    card_id: str
    description: str                       # human-readable, used verbatim in explanations
    earn: EarnRate                         # accelerated rate when matched
    categories: list[SpendCategory]        # match if line item category ∈ this list
    channels: list[Channel] | None         # None = any channel; e.g. BANK_PORTAL-only accelerations
    currencies: list[str] | None           # None = any; lets you restrict to INR-only earn etc.
    excluded_categories: list[SpendCategory]  # hard exclusions (e.g. no points on OTA wallet loads)
    mcc_codes: list[int] | None            # optional future precision
    cap: RewardCap | None
    valid_from: date | None
    valid_to: date | None                  # rule expiry (promos)
    provenance: Provenance

class RewardCap(BaseModel):
    max_points: int                        # max points earnable under this rule...
    period: Literal["statement_cycle", "calendar_month", "day", "offer_period"]
    # Post-cap behavior: spend beyond cap falls through to the NEXT best matching
    # rule, else base earn. The optimizer must model this fall-through (02 §5).
    shared_cap_group: str | None           # rules sharing a pool (e.g. portal cap across flights+hotels)
```

**Why `shared_cap_group`:** issuers commonly cap *combined* accelerated earn across a portal (flights + hotels share one monthly pool). Two rules with the same group draw from one pool during allocation.

## 5. `point_valuations` — redemption-path-dependent value

A point has no single value. Value depends on how it's redeemed, and this drives card choice.

```python
class PointValuation(BaseModel):
    id: str
    card_id: str                 # valuations attach to the card's currency (or program)
    path: RedemptionPath
    value_minor_per_point: int   # in millicents/millipaise for precision: store value*1000
                                 # e.g. ₹0.50/pt → 500 (milli-paise per point? see below)
    value_unit: Literal["milli_minor"]  # value_minor_per_point is in 1/1000 of minor unit
    currency: str
    min_points: int | None       # minimum redemption block
    conditions: str | None       # free text, rendered in report
    provenance: Provenance
```

Precision note: ₹0.50/point = 50 paise = `50_000` milli-paise… **Convention:** `value_milli_minor_per_point`, i.e. ₹0.50/pt → 500 milli-paise × 100? To remove all ambiguity: **store `value_micro_major_per_point` = value in millionths of a major currency unit.** ₹0.50/pt → `500_000`. ₹1.00/pt → `1_000_000`. This is the single canonical representation; helper `to_major()` divides by 1e6. (Implementer: use this micro-major convention everywhere a per-point value appears, and delete the two rejected alternatives above from your mental model — they are shown only to flag the ambiguity trap.)

The optimizer values earned points at the **best available path for which the user is plausible** — MVP simplification: use the max valuation per card, but report which path that assumes ("assumes redemption via portal flights").

## 6. `offers`

```python
class Offer(BaseModel):
    id: str
    title: str                              # "10% instant discount on Agoda with XYZ Visa"
    kind: OfferKind
    issuer: str | None                      # bank offers
    card_ids: list[str] | None              # specific cards; None + issuer set = any card of issuer
    networks: list[str] | None              # network-level offers (Visa/Mastercard promos)
    network_tiers: list[str] | None = None  # optional tier restriction within `networks`,
                                            # e.g. Infinite-only promo. None = any tier.
                                            # A card with network_tier=None matches only
                                            # offers whose network_tiers is None.
    merchant: str                           # "Agoda", "Singapore Airlines", "Klook"
    channels: list[Channel]
    categories: list[SpendCategory]
    discount_bp: int | None                 # percentage form (1000 = 10%)
    discount_flat_minor: int | None         # flat form; exactly one of bp/flat set
    max_discount_minor: int | None          # cap per transaction
    min_txn_minor: int | None
    currency: str
    valid_to: date
    promo_code: str | None
    stacking_class: Literal["bank_offer", "coupon", "card_linked"]
    # Stacking rule (02 §6): per transaction, at most ONE offer per stacking_class.
    uses_per_card: int | None               # e.g. once per card during offer period
    provenance: Provenance
```

## 7. Destination & pricing data (curated samples for MVP)

```python
class POI(BaseModel):
    id: str; city: str; name: str
    tags: list[str]                          # ["food","museum","nature","kids","nightlife","shopping","landmark"]
    typical_duration_min: int
    price_minor: int; currency: str          # 0 for free
    lat: float; lon: float
    area: str                                # neighborhood key, e.g. "marina_bay"
    open_hours: "TimezoneAwareHours"         # structured tz-aware intervals + closures
    booking_channel: Channel                 # how it's typically paid (POS_ABROAD vs OTA…)
    merchant_hint: str | None                # "Klook" → enables offer matching on attractions
    description: str                         # 1–2 sentences for the planner LLM
    provenance: Provenance

class TimezoneAwareHours(BaseModel):
    timezone: str                            # e.g. "Asia/Singapore"
    # Mapping of weekday (0=Monday, 6=Sunday) to list of "HH:MM-HH:MM" strings
    regular_hours: dict[int, list[str]]
    # Explicit dates (YYYY-MM-DD) when the POI is entirely closed
    closed_dates: list[str]

class SampleFlight(BaseModel):
    id: str; origin: str; destination: str   # IATA
    airline: str; stops: int
    price_minor: int; currency: str          # per person, round trip
    cabin: Literal["economy","premium","business"]
    purchasable_channels: list[Channel]      # DIRECT_AIRLINE, OTA_GENERIC, BANK_PORTAL
    notes: str | None
    provenance: Provenance

class SampleHotel(BaseModel):
    id: str; city: str; name: str; area: str
    stars: int; price_per_night_minor: int; currency: str
    style: Literal["budget","balanced","luxury"]
    purchasable_channels: list[Channel]
    provenance: Provenance

class FxRate(BaseModel):
    base: str; quote: str; rate_micro: int   # SGD→INR 63.20 → 63_200_000
    as_of: date; provenance: Provenance
```

`SampleFlight` and `SampleHotel` are deliberately small Kernel MVP fixture models, not canonical live-provider contracts. Do not add provider-specific fields to them or write live API/MCP responses directly into these tables. Spec 16 defines normalized `FlightQuote`, non-bookable `FlightPriceObservation`, accommodation-capable `HotelQuote`, and `AwardQuote` models; the post-F4 `SampleAdapter` maps these fixtures into quote contracts with `status="estimated"`. Cached trend observations never become `SampleFlight` or `FlightQuote`. Vacation-rental evidence uses `HotelQuote.property_kind="vacation_rental"` rather than expanding the fixture schema.

Areas: a small `areas` table per city (`id, city, name, good_for_tags, centrality_score 0–1`) so the hotel-area recommendation is data-driven, not LLM-invented.

## 8. User input tables

Users are ephemeral in MVP (no accounts). `TripSpec` (03 §2) carries owned `card_ids` and optional `points_balances: dict[card_id, int]`. Nothing persisted beyond the request unless a `--save` flag writes the plan JSON to disk.

## 9. Seed data format

Seeds live in `core/seeds/*.yaml`, one file per table, loaded by `python -m core.db seed`. Example (structure only — **every real-world value must ship with `needs_verification: true` and `verified_by: "UNVERIFIED"`; the implementer must not treat these numbers as true**):

```yaml
# seeds/cards.yaml
- id: hdfc-infinia            # REAL CARD NAME, PLACEHOLDER VALUES — verify before use
  issuer: HDFC Bank
  network: visa
  country: IN
  name: Infinia Metal
  annual_fee_minor: 1250000    # ₹12,500 — VERIFY
  fee_currency: INR
  forex_markup_bp: 200         # VERIFY
  forex_markup_tax_bp: 1800    # 18% GST on markup (IN standard) — VERIFY
  base_earn: { points: 5, per_amount_minor: 15000, currency: INR }
  provenance:
    source_type: manual_curation
    last_verified: 2026-07-07
    verified_by: UNVERIFIED
    needs_verification: true
    confidence: 0.5
```

MVP dataset sizes: 8–12 IN cards, 20–40 reward rules, 15–25 offers, ~60–100 Singapore POIs, 8 areas, 6–10 sample flights DEL/BOM→SIN, 10–15 hotels, FX for SGD/INR/USD, and 0–6 `network_benefits` rows (optional — the tier table may ship empty; nothing depends on it).

## 10. SQL notes

- One table per model; `provenance_*` columns inlined (no join table).
- JSON-encode list fields (`categories`, `channels`, `tags`) in TEXT columns — SQLite JSON1 functions are sufficient; Postgres migration maps to JSONB.
- Indices: `reward_rules(card_id)`, `offers(merchant)`, `offers(valid_to)`, `poi(city)`, `network_benefits(network, network_tier, country)`.
- All reads for one plan request happen through a single `KnowledgeBase` facade class (`core/db.py`) exposing typed query methods (`rules_for_cards(ids)`, `offers_matching(merchant, channel, category, date)`, `pois(city, tags)`), so the optimizer and agents never write SQL.
