# G1 — Travel Inventory Gateway Foundation Implementation Plan

> **For agentic workers:** This plan is executed inline in the same session per an explicit
> human directive ("execute it test-first ... do not wait for another conversation"). It is
> saved to the repo for recovery if context is lost mid-milestone (CLAUDE.md session-start
> protocol) — do not re-derive it from scratch; resume from whichever task's tests are still
> red.

**Goal:** Build the provider-neutral travel inventory gateway (spec 09 §13 "G1", spec 16) —
normalized flight/hotel/award contracts, a validated provider registry, the required
`SampleAdapter`, a recorded-fixture harness, deterministic flexible-date generation — and prove
the existing DEL→SIN sample journey produces byte-identical optimizer/pathfinder numbers whether
costed through the legacy direct-sample path or through the new gateway.

**Architecture:** A new `backend/gateway/travel/` package holds provider-neutral Pydantic
contracts (`contracts.py`), the adapter `Protocol` (`protocol.py`), typed errors (`errors.py`),
a static validated registry (`registry.py`, deterministic selection), code-computed freshness
(`freshness.py`), deterministic identity hashing (`identity.py`), bounded flexible-date
generation (`flexible.py`), and a fixture replay harness (`fixtures/`). `adapters/sample.py`
implements `TravelProviderAdapter` by reading the *existing* `KnowledgeBase.sample_flights`/
`sample_hotels` rows (no new fixture files for the sample corridor — the fixtures ARE the
existing seed DB) and mapping them into `FlightQuote`/`HotelQuote` with `status="estimated"`.
A new orchestration seam, `agents/gateway_estimator.py`, builds typed search requests from
`TripSpec`, selects the adapter through the registry, applies the *same* winner-selection
rule the legacy estimator uses (cheapest by price/stops/id for flights; exact-area-then-
centrality-fallback for hotels), and maps the winning quote back into a `SpendLineItem` using
the same currency-conversion order as `agents/estimator.py`. The legacy path
(`agents/estimator.py::estimate_costed_trip`) is left completely unmodified and remains the
one wired into `agents/pipeline.py`; a new parity test proves the gateway path is numerically
identical by feeding both into the unmodified `core/optimizer` and `core/transfer/pathfinder`.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, mypy --strict, ruff. No new third-party
dependencies. No real network I/O. The adapter protocol declares `async def` methods per
spec 16 §6 to match the target-platform contract shape; `SampleAdapter`'s implementation does
no I/O and tests call it via `asyncio.run`.

## Global Constraints

- Money: integer minor units only, everywhere. No float in any money path (`grep -rn "float"` audited).
- `backend/core/` must never import `backend/gateway/` (AST-checked test, spec 09 §4).
- Zero network calls in the normal test suite (guarded test asserts `socket.socket.connect` is patched to raise and the code path still works).
- No live provider, MCP, credential, paid service, booking, crawling, or transfer execution.
- `SampleAdapter` is enabled by default; unknown-cost providers are disabled by default; `SampleAdapter` is never circuit-broken.
- Every quote's `EvidenceMeta.status` for sample data is `"estimated"`, `needs_verification=True`.
- All timestamps in `EvidenceMeta`/quotes are timezone-aware (`AwareDatetime`); tests use an injected/frozen clock, never wall-clock.
- Existing golden tests (`backend/evals/golden/`) and the two existing scenario tests in `evals/test_m2_estimator.py` must not change: `git diff --exit-code -- backend/evals/golden/` stays clean.
- `AGENTS.md` and `CLAUDE.md` stay byte-identical to each other; their checkpoint prose is updated only after the G1 gate passes, in the docs commit.
- No change to `contract/openapi.json` or generated frontend files — the public API is not touched in this plan.

---

## File inventory

New:
- `backend/gateway/travel/__init__.py`
- `backend/gateway/travel/contracts.py` — `EvidenceMeta`, `TravelerMix`, 5 search-request models, `FlightSegment`, `FlightQuote`, `FlightPriceObservation`, `HotelQuote`, `AwardQuote`.
- `backend/gateway/travel/errors.py` — `TravelGatewayError` (11 typed codes), reuses `redact_secret` from `gateway.places.registry`.
- `backend/gateway/travel/protocol.py` — `AdapterCapabilities`, `TravelProviderAdapter` Protocol.
- `backend/gateway/travel/freshness.py` — `compute_status(...)`, `is_expired(...)` — pure, clock-injected.
- `backend/gateway/travel/identity.py` — `flight_quote_id(...)`, `flight_observation_id(...)`, `hotel_quote_id(...)`, `award_quote_id(...)`.
- `backend/gateway/travel/flexible.py` — `generate_flight_date_pairs(...)`, `generate_stay_windows(...)`, `stay_windows_comparable(...)`.
- `backend/gateway/travel/registry.py` — `TravelProviderRegistryEntry`, `TravelProviderRegistry`, `get_default_travel_registry(...)`.
- `backend/gateway/travel/fixtures/__init__.py`
- `backend/gateway/travel/fixtures/transport.py` — `FixtureTravelTransport`, generic recorded/replay seam for future live adapters (G3+).
- `backend/gateway/travel/fixtures/data/*.json` — 8 sanitized fixture files (success/empty/malformed/partial_price/stale/rate_limited/auth_failed/timeout).
- `backend/gateway/travel/adapters/__init__.py`
- `backend/gateway/travel/adapters/sample.py` — `SampleAdapter` implementing `TravelProviderAdapter` against `core.db.KnowledgeBase`.
- `backend/agents/gateway_estimator.py` — orchestration boundary: `estimate_costed_trip_via_gateway(...)`.
- `backend/evals/test_travel_contracts.py`
- `backend/evals/test_travel_errors.py`
- `backend/evals/test_travel_protocol.py`
- `backend/evals/test_travel_sample_adapter.py`
- `backend/evals/test_travel_registry.py`
- `backend/evals/test_travel_flexible.py`
- `backend/evals/test_travel_freshness.py`
- `backend/evals/test_travel_identity.py`
- `backend/evals/test_travel_fixtures_harness.py`
- `backend/evals/test_travel_gateway_parity.py` — the required non-vacuous DEL→SIN parity test.
- `backend/evals/test_travel_boundary.py` — `backend/core/` AST-import-boundary test + zero-network guard.

Modified: `backend/agents/estimator.py` (rename 7 module-private helpers to public, zero
behavior change — separate refactor commit). No Kernel/pipeline behavior change. `DEVIATIONS.md`
gets new entries. `reports/g1_travel_inventory_gateway.md` is created. `CLAUDE.md`/`AGENTS.md`
checkpoint prose updated together, byte-identical, in the final docs commit.

---

## Task 1 — Canonical evidence metadata + search request contracts

**Files:**
- Create: `backend/gateway/travel/contracts.py`
- Test: `backend/evals/test_travel_contracts.py`

**Interfaces:**
- Produces: `EvidenceMeta`, `TravelerMix`, `FlightSearchRequest`, `FlexibleFlightSearchRequest`, `HotelSearchRequest`, `FlexibleStaySearchRequest`, `AwardSearchRequest` — all Pydantic v2 `BaseModel`, importable as `from gateway.travel.contracts import ...`.

**Ambiguity note (log to DEVIATIONS.md, Tier C):** Spec 16 §4/§6 request models don't state a
numeric upper bound for `max_date_pairs`/`max_start_dates`. Conservative choice: add
`Field(gt=0, le=31)` (one calendar month — generous but finite; changes no golden value).
IATA/currency fields get uppercase-normalizing validators matching the existing `TripSpec`
pattern (`core/trip_models.py:32-38`).

- [ ] **Step 1: Write the failing contract tests**

```python
# backend/evals/test_travel_contracts.py
from __future__ import annotations

from datetime import date, datetime, UTC

import pytest
from pydantic import ValidationError

from gateway.travel.contracts import (
    AwardSearchRequest,
    EvidenceMeta,
    FlexibleFlightSearchRequest,
    FlexibleStaySearchRequest,
    FlightSearchRequest,
    HotelSearchRequest,
    TravelerMix,
)


def _evidence(**overrides: object) -> EvidenceMeta:
    base = dict(
        provider_id="sample_travel_adapter",
        provider_quote_id="q1",
        source_url=None,
        deep_link_url=None,
        retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
        expires_at=None,
        status="estimated",
        cache_age_seconds=None,
        terms_version="sample-fixture-v1",
        attribution="TripPlanner sample fixture data",
        completeness="taxes_uncertain",
        needs_verification=True,
        notes=[],
    )
    base.update(overrides)
    return EvidenceMeta(**base)


def test_evidence_meta_requires_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        EvidenceMeta(
            provider_id="p", provider_quote_id=None, source_url=None, deep_link_url=None,
            retrieved_at=datetime(2026, 8, 1),  # naive — must be rejected
            expires_at=None, status="estimated", cache_age_seconds=None,
            terms_version="v1", attribution=None, completeness="complete",
            needs_verification=True, notes=[],
        )


def test_evidence_meta_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        _evidence(status="fresh")


def test_flight_search_request_normalizes_iata_and_currency() -> None:
    req = FlightSearchRequest(
        origin="del", destination="sin", depart_date=date(2026, 8, 1),
        return_date=date(2026, 8, 5), travelers=TravelerMix(adults=2),
        cabin="economy", currency="inr",
    )
    assert req.origin == "DEL"
    assert req.destination == "SIN"
    assert req.currency == "INR"


def test_flight_search_request_rejects_return_before_depart() -> None:
    with pytest.raises(ValidationError):
        FlightSearchRequest(
            origin="DEL", destination="SIN", depart_date=date(2026, 8, 5),
            return_date=date(2026, 8, 1), travelers=TravelerMix(adults=1),
            cabin="economy", currency="INR",
        )


def test_traveler_mix_requires_at_least_one_traveler() -> None:
    with pytest.raises(ValidationError):
        TravelerMix(adults=0, children=0, infants=0)


def test_hotel_search_request_rejects_checkout_not_after_checkin() -> None:
    with pytest.raises(ValidationError):
        HotelSearchRequest(
            city="SIN", check_in=date(2026, 8, 5), check_out=date(2026, 8, 5),
            travelers=TravelerMix(adults=2), rooms=1, area_ids=["marina_bay"],
            style="balanced", currency="INR",
        )


def test_hotel_search_request_rejects_nonpositive_rooms() -> None:
    with pytest.raises(ValidationError):
        HotelSearchRequest(
            city="SIN", check_in=date(2026, 8, 1), check_out=date(2026, 8, 5),
            travelers=TravelerMix(adults=2), rooms=0, area_ids=[], style="balanced",
            currency="INR",
        )


def test_flexible_flight_request_bounds_max_date_pairs() -> None:
    with pytest.raises(ValidationError):
        FlexibleFlightSearchRequest(
            origin="DEL", destination="SIN", depart_window_start=date(2026, 8, 1),
            depart_window_end=date(2026, 8, 10), return_window_start=None,
            return_window_end=None, trip_length_nights=4, travelers=TravelerMix(adults=1),
            cabin="economy", currency="INR", max_date_pairs=0,
        )


def test_flexible_stay_request_rejects_window_end_before_start() -> None:
    with pytest.raises(ValidationError):
        FlexibleStaySearchRequest(
            city="SIN", window_start=date(2026, 8, 10), window_end=date(2026, 8, 1),
            nights=3, travelers=TravelerMix(adults=2), rooms=1, area_ids=[],
            style="balanced", currency="INR", property_kinds={"hotel"}, max_start_dates=5,
        )


def test_award_search_request_normalizes_iata() -> None:
    req = AwardSearchRequest(
        origin="del", destination="sin", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=1), cabin="business", program_ids=["lionmiles"],
    )
    assert req.origin == "DEL"


def test_deterministic_serialization_is_stable() -> None:
    req1 = FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=2), cabin="economy", currency="INR",
    )
    req2 = FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=2), cabin="economy", currency="INR",
    )
    assert req1.model_dump_json() == req2.model_dump_json()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/pytest evals/test_travel_contracts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway.travel'`

- [ ] **Step 3: Implement `contracts.py`**

Field shapes copied verbatim from spec 16 §3/§4/§5. Key excerpt (the full file also defines
`FlightSegment`, `FlightQuote`, `FlightPriceObservation`, `HotelQuote`, `AwardQuote` — those
get their dedicated invariant tests in Task 2, but must exist in this same file/step since
Task 2's tests need real classes to import):

```python
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from core.models import Channel

Cabin = Literal["economy", "premium", "business", "first"]
Status = Literal["live", "cached", "estimated", "stale", "verify_required"]
Completeness = Literal["complete", "taxes_uncertain", "fees_uncertain", "partial"]
PropertyKind = Literal["hotel", "serviced_apartment", "vacation_rental", "hostel"]


class EvidenceMeta(BaseModel):
    provider_id: str = Field(min_length=1)
    provider_quote_id: str | None = None
    source_url: str | None = None
    deep_link_url: str | None = None
    retrieved_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    status: Status
    cache_age_seconds: int | None = Field(default=None, ge=0)
    terms_version: str = Field(min_length=1)
    attribution: str | None = None
    completeness: Completeness
    needs_verification: bool
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _live_requires_unexpired_and_non_sample(self) -> "EvidenceMeta":
        if self.status == "live":
            if self.expires_at is not None and self.retrieved_at >= self.expires_at:
                raise ValueError("live evidence cannot already be past its own expiry")
            if self.provider_id.startswith("sample_"):
                raise ValueError("sample/sandbox evidence can never be status=live")
        return self
```

(Continue analogously for `TravelerMix`, `FlightSearchRequest`,
`FlexibleFlightSearchRequest`, `HotelSearchRequest`, `FlexibleStaySearchRequest`,
`AwardSearchRequest`, then the five quote models — every field name matches spec 16 exactly;
money fields are `int`, never `float`.)

- [ ] **Step 4: Run to verify pass**, **Step 5: mypy/ruff, commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_contracts.py -v
.venv/bin/mypy --strict gateway/travel/contracts.py
.venv/bin/ruff check gateway/travel/contracts.py evals/test_travel_contracts.py
git add gateway/travel/__init__.py gateway/travel/contracts.py evals/test_travel_contracts.py
git commit -m "feat(gateway): add normalized travel inventory contracts"
```

---

## Task 2 — Flight/hotel/award quote contracts + anti-promotion invariants

**Files:**
- Modify: `backend/gateway/travel/contracts.py` (the five quote models, written in Task 1's
  implementation step; this task adds their dedicated invariant tests)
- Test: `backend/evals/test_travel_contracts.py` (extended)

**Interfaces:**
- Consumes: `EvidenceMeta`, `TravelerMix`, `Cabin`, `PropertyKind` from Task 1.
- Produces: `FlightSegment`, `FlightQuote`, `FlightPriceObservation`, `HotelQuote`, `AwardQuote`.

- [ ] **Step 1: Write failing invariant tests (append to `test_travel_contracts.py`)**

```python
from gateway.travel.contracts import (
    AwardQuote, FlightPriceObservation, FlightQuote, FlightSegment, HotelQuote,
)


def _segment(**overrides: object) -> FlightSegment:
    base = dict(
        origin="DEL", destination="SIN",
        departure_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        arrival_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        marketing_airline="IndiGo", operating_airline=None,
        flight_number="SAMPLE-DEL-SIN-6E-ECO", cabin="economy", duration_min=360,
    )
    base.update(overrides)
    return FlightSegment(**base)


def test_flight_quote_rejects_empty_segments() -> None:
    with pytest.raises(ValidationError):
        FlightQuote(
            id="q1", segments=[], trip_type="one_way", travelers=TravelerMix(adults=1),
            fare_brand=None, baggage_summary=None, refundable=None, changeable=None,
            base_minor=None, taxes_minor=None, fees_minor=None, total_minor=10000,
            currency="INR", purchasable_channels=[], evidence=_evidence(),
        )


def test_flight_segment_rejects_arrival_before_departure() -> None:
    with pytest.raises(ValidationError):
        _segment(arrival_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC))


def test_flight_quote_rejects_negative_money() -> None:
    with pytest.raises(ValidationError):
        FlightQuote(
            id="q1", segments=[_segment()], trip_type="one_way",
            travelers=TravelerMix(adults=1), fare_brand=None, baggage_summary=None,
            refundable=None, changeable=None, base_minor=None, taxes_minor=None,
            fees_minor=None, total_minor=-1, currency="INR", purchasable_channels=[],
            evidence=_evidence(),
        )


def test_flight_price_observation_is_bookable_is_always_false() -> None:
    obs = FlightPriceObservation(
        id="obs1", origin="DEL", destination="SIN", depart_date=date(2026, 8, 1),
        return_date=None, cabin="economy", stops=1, observed_total_minor=400000,
        currency="INR", observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        itinerary_detail="route_only", evidence=_evidence(status="estimated"),
    )
    assert obs.is_bookable is False


def test_flight_price_observation_rejects_is_bookable_true() -> None:
    with pytest.raises(ValidationError):
        FlightPriceObservation(
            id="obs1", origin="DEL", destination="SIN", depart_date=date(2026, 8, 1),
            return_date=None, cabin="economy", stops=1, observed_total_minor=400000,
            currency="INR", observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            itinerary_detail="route_only", is_bookable=True, evidence=_evidence(),
        )


def test_flight_price_observation_cannot_validate_as_flight_quote() -> None:
    obs = FlightPriceObservation(
        id="obs1", origin="DEL", destination="SIN", depart_date=date(2026, 8, 1),
        return_date=None, cabin="economy", stops=1, observed_total_minor=400000,
        currency="INR", observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        itinerary_detail="route_only", evidence=_evidence(),
    )
    with pytest.raises(ValidationError):
        FlightQuote.model_validate(obs.model_dump())


def test_flight_price_observation_evidence_cannot_be_live() -> None:
    with pytest.raises(ValidationError):
        FlightPriceObservation(
            id="obs1", origin="DEL", destination="SIN", depart_date=date(2026, 8, 1),
            return_date=None, cabin="economy", stops=1, observed_total_minor=400000,
            currency="INR", observed_at=datetime(2026, 8, 1, tzinfo=UTC),
            itinerary_detail="route_only",
            evidence=_evidence(
                status="live", provider_id="real_provider",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            ),
        )


def test_hotel_quote_rejects_checkout_not_after_checkin() -> None:
    with pytest.raises(ValidationError):
        HotelQuote(
            id="h1", property_id="p1", name="Marina Bay Harbourview",
            property_kind="hotel", city="SIN", area_id="marina_bay", lat=None, lon=None,
            check_in=date(2026, 8, 1), check_out=date(2026, 8, 1),
            travelers=TravelerMix(adults=2), rooms=1, room_name=None, rate_plan=None,
            cancellation_summary=None, refundable=None, review_score_scaled=None,
            review_scale_source=None, review_count=None, placement="organic",
            base_minor=None, taxes_minor=None, fees_minor=None, total_minor=6400000,
            currency="INR", pay_timing="unknown", purchasable_channels=[],
            evidence=_evidence(),
        )


def test_hotel_quote_review_score_requires_scale_source() -> None:
    with pytest.raises(ValidationError):
        HotelQuote(
            id="h1", property_id="p1", name="X", property_kind="hotel", city="SIN",
            area_id=None, lat=None, lon=None, check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5), travelers=TravelerMix(adults=2), rooms=1,
            room_name=None, rate_plan=None, cancellation_summary=None, refundable=None,
            review_score_scaled=8000, review_scale_source=None, review_count=None,
            placement="organic", base_minor=None, taxes_minor=None, fees_minor=None,
            total_minor=1, currency="INR", pay_timing="unknown", purchasable_channels=[],
            evidence=_evidence(),
        )


def test_hotel_quote_review_score_bounds() -> None:
    with pytest.raises(ValidationError):
        HotelQuote(
            id="h1", property_id="p1", name="X", property_kind="hotel", city="SIN",
            area_id=None, lat=None, lon=None, check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5), travelers=TravelerMix(adults=2), rooms=1,
            room_name=None, rate_plan=None, cancellation_summary=None, refundable=None,
            review_score_scaled=10001, review_scale_source="TripAdvisor 0-5 * 2000",
            review_count=None, placement="organic", base_minor=None, taxes_minor=None,
            fees_minor=None, total_minor=1, currency="INR", pay_timing="unknown",
            purchasable_channels=[], evidence=_evidence(),
        )


def test_hotel_quote_missing_coordinates_stay_none() -> None:
    hq = HotelQuote(
        id="h1", property_id="p1", name="X", property_kind="hotel", city="SIN",
        area_id="marina_bay", lat=None, lon=None, check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5), travelers=TravelerMix(adults=2), rooms=1,
        room_name=None, rate_plan=None, cancellation_summary=None, refundable=None,
        review_score_scaled=None, review_scale_source=None, review_count=None,
        placement="organic", base_minor=None, taxes_minor=None, fees_minor=None,
        total_minor=6400000, currency="INR", pay_timing="unknown",
        purchasable_channels=[], evidence=_evidence(),
    )
    assert hq.lat is None and hq.lon is None


def test_award_quote_money_and_miles_are_ints() -> None:
    aq = AwardQuote(
        id="a1", program_id="lionmiles", origin="DEL", destination="SIN",
        depart_date=date(2026, 8, 1), return_date=date(2026, 8, 5), cabin="business",
        travelers=TravelerMix(adults=2), seats_available=None, miles_total=124000,
        fees_minor=1800000, fees_currency="INR", operating_airline=None,
        mixed_cabin=None, evidence=_evidence(status="verify_required"),
    )
    assert isinstance(aq.miles_total, int) and isinstance(aq.fees_minor, int)


def test_award_quote_sample_evidence_cannot_be_live() -> None:
    with pytest.raises(ValidationError):
        AwardQuote(
            id="a1", program_id="lionmiles", origin="DEL", destination="SIN",
            depart_date=date(2026, 8, 1), return_date=None, cabin="business",
            travelers=TravelerMix(adults=1), seats_available=None, miles_total=1,
            fees_minor=0, fees_currency="INR", operating_airline=None, mixed_cabin=None,
            evidence=_evidence(
                status="live", provider_id="sample_travel_adapter",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            ),
        )
```

- [ ] **Step 2: run, verify failures**
- [ ] **Step 3: implement the five quote models** with validators: non-empty `segments`;
  chronological `arrival_at > departure_at`; non-negative `int` money fields; `is_bookable:
  Literal[False] = False` on `FlightPriceObservation`; `review_score_scaled: int | None =
  Field(default=None, ge=0, le=10_000)` with a `model_validator` requiring
  `review_scale_source` whenever the score is set; `check_out > check_in` on `HotelQuote`.
- [ ] **Step 4: run, verify pass**
- [ ] **Step 5: commit (amend Task 1's commit — same file, same feature, not yet shared)**

```bash
cd backend
.venv/bin/pytest evals/test_travel_contracts.py -v
.venv/bin/mypy --strict gateway/travel/contracts.py
git add gateway/travel/contracts.py evals/test_travel_contracts.py
git commit --amend --no-edit
```

---

## Task 3 — Typed gateway errors

**Files:**
- Create: `backend/gateway/travel/errors.py`
- Test: `backend/evals/test_travel_errors.py`

**Interfaces:**
- Consumes: `redact_secret` from `gateway.places.registry` (existing, generic string
  utility — reused, not duplicated).
- Produces: `TravelGatewayError` with `.code` (`Literal` of the 11 spec 16 §13 codes) and
  `.message` (redacted).

- [ ] **Step 1: Write failing test**

```python
# backend/evals/test_travel_errors.py
from __future__ import annotations

import pytest

from gateway.travel.errors import TravelGatewayError


def test_error_carries_typed_code() -> None:
    err = TravelGatewayError("no_results", "no flights found")
    assert err.code == "no_results"
    assert "no flights found" in str(err)


def test_error_redacts_secrets() -> None:
    err = TravelGatewayError("authentication_failed", "Authorization: Bearer sk_live_abcdef123456")
    assert "sk_live_abcdef123456" not in str(err)
    assert "REDACTED" in str(err)


@pytest.mark.parametrize(
    "code",
    [
        "provider_unavailable", "authentication_failed", "permission_denied",
        "rate_limited", "budget_exhausted", "timeout", "invalid_response",
        "no_results", "unsupported_domain", "region_restricted", "terms_disabled",
    ],
)
def test_all_spec16_codes_are_constructible(code: str) -> None:
    err = TravelGatewayError(code, "x")  # type: ignore[arg-type]
    assert err.code == code
```

- [ ] **Step 2: run, verify fail** — **Step 3: implement**

```python
from __future__ import annotations

from typing import Literal

from gateway.places.registry import redact_secret

ErrorCode = Literal[
    "provider_unavailable", "authentication_failed", "permission_denied",
    "rate_limited", "budget_exhausted", "timeout", "invalid_response",
    "no_results", "unsupported_domain", "region_restricted", "terms_disabled",
]


class TravelGatewayError(Exception):
    def __init__(self, code: ErrorCode, message: str) -> None:
        sanitized = redact_secret(message)
        super().__init__(sanitized)
        self.code = code
        self.message = sanitized

    def __str__(self) -> str:
        return self.message

    def __repr__(self) -> str:
        return f"TravelGatewayError(code={self.code!r}, message={self.message!r})"
```

- [ ] **Step 4: run, verify pass** — **Step 5: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_errors.py -v
.venv/bin/mypy --strict gateway/travel/errors.py
git add gateway/travel/errors.py evals/test_travel_errors.py
git commit -m "feat(gateway): add typed travel gateway errors"
```

---

## Task 4 — Adapter protocol + capabilities

**Files:**
- Create: `backend/gateway/travel/protocol.py`
- Test: `backend/evals/test_travel_protocol.py`

**Interfaces:**
- Consumes: contracts from Task 1/2.
- Produces: `AdapterCapabilities`, `TravelProviderAdapter` (Protocol with 4 async methods).

- [ ] **Step 1: failing test**

```python
# backend/evals/test_travel_protocol.py
from __future__ import annotations

import pytest

from gateway.travel.protocol import AdapterCapabilities


def test_capabilities_rejects_unknown_domain() -> None:
    with pytest.raises(Exception):
        AdapterCapabilities(
            provider_id="x", domains={"flight", "bookings"}, countries="configured",
            live_data=False, supports_cache=False, supports_commercial_use=False,
            allowed_profiles={"student_noncommercial"}, source_method="sample",
            stability="stable", requires_user_initiated_search=False, max_concurrency=1,
        )


def test_capabilities_rejects_unknown_source_method() -> None:
    with pytest.raises(Exception):
        AdapterCapabilities(
            provider_id="x", domains={"flight"}, countries="configured",
            live_data=False, supports_cache=False, supports_commercial_use=False,
            allowed_profiles={"student_noncommercial"}, source_method="webhook",
            stability="stable", requires_user_initiated_search=False, max_concurrency=1,
        )


def test_capabilities_accepts_valid_shape() -> None:
    caps = AdapterCapabilities(
        provider_id="sample_travel_adapter", domains={"flight", "hotel", "award"},
        countries="configured", live_data=False, supports_cache=False,
        supports_commercial_use=False, allowed_profiles={"student_noncommercial"},
        source_method="sample", stability="stable",
        requires_user_initiated_search=False, max_concurrency=1,
    )
    assert caps.provider_id == "sample_travel_adapter"
```

- [ ] **Step 2: run, verify fail** — **Step 3: implement**

```python
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from gateway.travel.contracts import (
    AwardQuote, AwardSearchRequest, FlexibleFlightSearchRequest, FlightPriceObservation,
    FlightQuote, FlightSearchRequest, HotelQuote, HotelSearchRequest,
)

Domain = Literal["flight", "flight_trend", "hotel", "award", "fx", "poi"]
SourceMethod = Literal[
    "sample", "official_api", "provider_mcp", "community_mcp",
    "scraper_wrapper", "open_data",
]


class AdapterCapabilities(BaseModel):
    provider_id: str = Field(min_length=1)
    domains: set[Domain]
    countries: set[str] | Literal["configured"]
    live_data: bool
    supports_cache: bool
    supports_commercial_use: bool
    allowed_profiles: set[Literal["student_noncommercial", "commercial_production"]]
    source_method: SourceMethod
    stability: Literal["stable", "experimental"]
    requires_user_initiated_search: bool
    max_concurrency: int = Field(ge=1)


class TravelProviderAdapter(Protocol):
    capabilities: AdapterCapabilities

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]: ...

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]: ...

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]: ...

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]: ...
```

- [ ] **Step 4: run, verify pass** — **Step 5: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_protocol.py -v
.venv/bin/mypy --strict gateway/travel/protocol.py
git add gateway/travel/protocol.py evals/test_travel_protocol.py
git commit -m "feat(gateway): add travel adapter protocol and capabilities"
```

---

## Task 5 — Deterministic identity + freshness

**Files:**
- Create: `backend/gateway/travel/identity.py`, `backend/gateway/travel/freshness.py`
- Test: `backend/evals/test_travel_identity.py`, `backend/evals/test_travel_freshness.py`

**Interfaces:**
- Produces: `identity.flight_quote_id(segments, travelers, *, fare_brand) -> str`,
  `identity.flight_observation_id(*, provider_id, origin, destination, depart_date,
  return_date, cabin, stops, observed_time_bucket) -> str`,
  `identity.hotel_quote_id(property_id, check_in, check_out, room_name, rate_plan) -> str`,
  `identity.award_quote_id(program_id, origin, destination, depart_date, cabin,
  operating_airline) -> str`.
- Produces: `freshness.compute_status(*, source_status, retrieved_at, expires_at, now) ->
  Status`, `freshness.is_expired(expires_at, now) -> bool`.

- [ ] **Step 1: failing tests**

```python
# backend/evals/test_travel_identity.py
from __future__ import annotations

from datetime import UTC, date, datetime

from gateway.travel.contracts import FlightSegment, TravelerMix
from gateway.travel.identity import flight_quote_id, hotel_quote_id


def _seg(**kw: object) -> FlightSegment:
    base = dict(
        origin="DEL", destination="SIN",
        departure_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        arrival_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        marketing_airline="IndiGo", operating_airline=None,
        flight_number="6E-ECO", cabin="economy", duration_min=360,
    )
    base.update(kw)
    return FlightSegment(**base)


def test_flight_quote_id_is_deterministic() -> None:
    a = flight_quote_id([_seg()], TravelerMix(adults=2), fare_brand=None)
    b = flight_quote_id([_seg()], TravelerMix(adults=2), fare_brand=None)
    assert a == b


def test_flight_quote_id_is_sensitive_to_segment_order() -> None:
    seg1 = _seg(origin="DEL", destination="BOM")
    seg2 = _seg(origin="BOM", destination="SIN", flight_number="6E-2")
    forward = flight_quote_id([seg1, seg2], TravelerMix(adults=1), fare_brand=None)
    backward = flight_quote_id([seg2, seg1], TravelerMix(adults=1), fare_brand=None)
    assert forward != backward


def test_flight_quote_id_changes_with_fare_condition() -> None:
    a = flight_quote_id([_seg()], TravelerMix(adults=1), fare_brand="basic")
    b = flight_quote_id([_seg()], TravelerMix(adults=1), fare_brand="flex")
    assert a != b


def test_hotel_quote_id_keeps_room_rate_variants_separate() -> None:
    a = hotel_quote_id("sg-hotel-marina-balanced", date(2026, 8, 1), date(2026, 8, 5), "Deluxe", "Non-refundable")
    b = hotel_quote_id("sg-hotel-marina-balanced", date(2026, 8, 1), date(2026, 8, 5), "Deluxe", "Refundable")
    assert a != b
```

```python
# backend/evals/test_travel_freshness.py
from __future__ import annotations

from datetime import UTC, datetime

from gateway.travel.freshness import compute_status, is_expired


def test_live_inside_ttl_stays_live() -> None:
    now = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    expires = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    assert compute_status(source_status="live", retrieved_at=now, expires_at=expires, now=now) == "live"


def test_expired_live_becomes_stale() -> None:
    retrieved = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)
    expires = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    assert compute_status(source_status="live", retrieved_at=retrieved, expires_at=expires, now=now) == "stale"


def test_exact_instant_equality_counts_as_expired() -> None:
    t = datetime(2026, 8, 1, 11, 0, tzinfo=UTC)
    assert is_expired(t, t) is True


def test_estimated_never_becomes_live_regardless_of_clock() -> None:
    retrieved = datetime(2026, 8, 1, tzinfo=UTC)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    assert compute_status(source_status="estimated", retrieved_at=retrieved, expires_at=None, now=now) == "estimated"


def test_cached_without_expiry_stays_cached() -> None:
    retrieved = datetime(2026, 8, 1, tzinfo=UTC)
    now = datetime(2026, 8, 2, tzinfo=UTC)
    assert compute_status(source_status="cached", retrieved_at=retrieved, expires_at=None, now=now) == "cached"
```

- [ ] **Step 2: run, verify fail** — **Step 3: implement**

```python
# backend/gateway/travel/identity.py
from __future__ import annotations

import hashlib
import json
from datetime import date

from gateway.travel.contracts import FlightSegment, TravelerMix


def _hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def flight_quote_id(
    segments: list[FlightSegment], travelers: TravelerMix, *, fare_brand: str | None
) -> str:
    payload = {
        "segments": [
            {
                "origin": s.origin, "destination": s.destination,
                "departure_at": s.departure_at.isoformat(), "arrival_at": s.arrival_at.isoformat(),
                "operating_airline": s.operating_airline or s.marketing_airline,
                "flight_number": s.flight_number,
            }
            for s in segments
        ],
        "fare_brand": fare_brand,
    }
    return f"fq_{_hash(payload)}"


def flight_observation_id(
    *, provider_id: str, origin: str, destination: str, depart_date: date,
    return_date: date | None, cabin: str | None, stops: int | None, observed_time_bucket: str,
) -> str:
    payload = {
        "provider_id": provider_id, "origin": origin, "destination": destination,
        "depart_date": depart_date.isoformat(),
        "return_date": return_date.isoformat() if return_date else None,
        "cabin": cabin, "stops": stops, "observed_time_bucket": observed_time_bucket,
    }
    return f"fo_{_hash(payload)}"


def hotel_quote_id(
    property_id: str, check_in: date, check_out: date, room_name: str | None, rate_plan: str | None
) -> str:
    payload = {
        "property_id": property_id, "check_in": check_in.isoformat(),
        "check_out": check_out.isoformat(), "room_name": room_name, "rate_plan": rate_plan,
    }
    return f"hq_{_hash(payload)}"


def award_quote_id(
    program_id: str, origin: str, destination: str, depart_date: date,
    cabin: str, operating_airline: str | None,
) -> str:
    payload = {
        "program_id": program_id, "origin": origin, "destination": destination,
        "depart_date": depart_date.isoformat(), "cabin": cabin,
        "operating_airline": operating_airline,
    }
    return f"aq_{_hash(payload)}"
```

```python
# backend/gateway/travel/freshness.py
from __future__ import annotations

from datetime import datetime
from typing import Literal

Status = Literal["live", "cached", "estimated", "stale", "verify_required"]


def is_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    return now >= expires_at


def compute_status(
    *, source_status: Status, retrieved_at: datetime, expires_at: datetime | None, now: datetime,
) -> Status:
    """Code-computed status transition (spec 16 §8). A provider/LLM declares
    `source_status`; only this function may promote it to `stale`."""
    if source_status in ("live", "cached") and is_expired(expires_at, now):
        return "stale"
    return source_status
```

- [ ] **Step 4: run, verify pass** — **Step 5: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_identity.py evals/test_travel_freshness.py -v
.venv/bin/mypy --strict gateway/travel/identity.py gateway/travel/freshness.py
git add gateway/travel/identity.py gateway/travel/freshness.py evals/test_travel_identity.py evals/test_travel_freshness.py
git commit -m "feat(gateway): add deterministic travel identity and freshness"
```

---

## Task 6 — Bounded flexible-date generation

**Files:**
- Create: `backend/gateway/travel/flexible.py`
- Test: `backend/evals/test_travel_flexible.py`

**Interfaces:**
- Produces: `generate_flight_date_pairs(request: FlexibleFlightSearchRequest) ->
  list[tuple[date, date | None]]`, `generate_stay_windows(request:
  FlexibleStaySearchRequest) -> list[tuple[date, date]]`, `stay_windows_comparable(a:
  HotelQuote, b: HotelQuote) -> bool`.

- [ ] **Step 1: failing tests**

```python
# backend/evals/test_travel_flexible.py
from __future__ import annotations

from datetime import date

from gateway.travel.contracts import FlexibleFlightSearchRequest, FlexibleStaySearchRequest, TravelerMix
from gateway.travel.flexible import generate_flight_date_pairs, generate_stay_windows


def _flex_flight(**kw: object) -> FlexibleFlightSearchRequest:
    base = dict(
        origin="DEL", destination="SIN",
        depart_window_start=date(2026, 8, 1), depart_window_end=date(2026, 8, 3),
        return_window_start=None, return_window_end=None, trip_length_nights=4,
        travelers=TravelerMix(adults=1), cabin="economy", currency="INR", max_date_pairs=10,
    )
    base.update(kw)
    return FlexibleFlightSearchRequest(**base)


def test_flight_date_pairs_apply_trip_length_and_stay_in_window() -> None:
    pairs = generate_flight_date_pairs(_flex_flight())
    assert pairs
    for depart, ret in pairs:
        assert date(2026, 8, 1) <= depart <= date(2026, 8, 3)
        assert ret is not None and (ret - depart).days == 4


def test_flight_date_pairs_never_exceed_window() -> None:
    pairs = generate_flight_date_pairs(_flex_flight(
        depart_window_start=date(2026, 8, 30), depart_window_end=date(2026, 8, 31),
        trip_length_nights=None,
    ))
    for depart, _ in pairs:
        assert date(2026, 8, 30) <= depart <= date(2026, 8, 31)


def test_flight_date_pairs_respects_max_date_pairs() -> None:
    req = _flex_flight(
        depart_window_start=date(2026, 8, 1), depart_window_end=date(2026, 8, 10),
        trip_length_nights=None, max_date_pairs=3,
    )
    pairs = generate_flight_date_pairs(req)
    assert len(pairs) == 3


def test_flight_date_pairs_are_chronologically_ordered_and_deterministic() -> None:
    req = _flex_flight(depart_window_start=date(2026, 8, 1), depart_window_end=date(2026, 8, 5), trip_length_nights=None)
    first = generate_flight_date_pairs(req)
    second = generate_flight_date_pairs(req)
    assert first == second
    assert [p[0] for p in first] == sorted(p[0] for p in first)


def test_flight_date_pairs_one_way_when_no_return_window_and_no_trip_length() -> None:
    req = _flex_flight(trip_length_nights=None)
    pairs = generate_flight_date_pairs(req)
    assert all(ret is None for _, ret in pairs)


def _flex_stay(**kw: object) -> FlexibleStaySearchRequest:
    base = dict(
        city="SIN", window_start=date(2026, 8, 1), window_end=date(2026, 8, 5), nights=3,
        travelers=TravelerMix(adults=2), rooms=1, area_ids=["marina_bay"], style="balanced",
        currency="INR", property_kinds={"hotel"}, max_start_dates=10,
    )
    base.update(kw)
    return FlexibleStaySearchRequest(**base)


def test_stay_windows_never_exceed_window_end_for_checkout() -> None:
    windows = generate_stay_windows(_flex_stay())
    assert windows
    for start, end in windows:
        assert start >= date(2026, 8, 1)
        assert end <= date(2026, 8, 5)
        assert (end - start).days == 3


def test_stay_windows_respect_max_start_dates() -> None:
    windows = generate_stay_windows(_flex_stay(window_start=date(2026, 8, 1), window_end=date(2026, 8, 20), nights=1, max_start_dates=4))
    assert len(windows) == 4


def test_stay_windows_deterministic_chronological_order() -> None:
    req = _flex_stay()
    first = generate_stay_windows(req)
    second = generate_stay_windows(req)
    assert first == second == sorted(first)


def test_stay_windows_empty_when_no_start_date_leaves_room_for_nights() -> None:
    req = _flex_stay(window_start=date(2026, 8, 1), window_end=date(2026, 8, 2), nights=5)
    assert generate_stay_windows(req) == []
```

- [ ] **Step 2: run, verify fail** — **Step 3: implement**

```python
from __future__ import annotations

from datetime import date, timedelta

from gateway.travel.contracts import FlexibleFlightSearchRequest, FlexibleStaySearchRequest, HotelQuote


def _date_range(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def generate_flight_date_pairs(
    request: FlexibleFlightSearchRequest,
) -> list[tuple[date, date | None]]:
    depart_candidates = _date_range(request.depart_window_start, request.depart_window_end)
    pairs: list[tuple[date, date | None]] = []
    for depart in depart_candidates:
        if request.trip_length_nights is not None:
            pairs.append((depart, depart + timedelta(days=request.trip_length_nights)))
        elif request.return_window_start is not None and request.return_window_end is not None:
            for ret in _date_range(request.return_window_start, request.return_window_end):
                if ret >= depart:
                    pairs.append((depart, ret))
        else:
            pairs.append((depart, None))
    pairs.sort(key=lambda p: (p[0], p[1] or date.min))
    return pairs[: request.max_date_pairs]


def generate_stay_windows(request: FlexibleStaySearchRequest) -> list[tuple[date, date]]:
    latest_start = request.window_end - timedelta(days=request.nights)
    if latest_start < request.window_start:
        return []
    starts = _date_range(request.window_start, latest_start)
    windows = sorted((start, start + timedelta(days=request.nights)) for start in starts)
    return windows[: request.max_start_dates]


def stay_windows_comparable(a: HotelQuote, b: HotelQuote) -> bool:
    """Spec 16 §11: compare same-property rates only after entity, occupancy,
    room/rate, dates, and mandatory-fee scope match. Sponsored `placement`
    must never gate comparability (it must never gate ranking either — that
    rule lives in the orchestration ranking layer, not here)."""
    return (
        a.property_id == b.property_id
        and a.check_in == b.check_in
        and a.check_out == b.check_out
        and a.rooms == b.rooms
        and a.travelers == b.travelers
        and a.room_name == b.room_name
        and a.rate_plan == b.rate_plan
        and a.currency == b.currency
    )
```

- [ ] **Step 4: add + run the `stay_windows_comparable` tests, verify pass**

```python
def test_stay_windows_comparable_ignores_placement_but_not_room_name(tmp_path=None) -> None:
    from datetime import date as _date
    from gateway.travel.contracts import EvidenceMeta, HotelQuote, TravelerMix
    from gateway.travel.flexible import stay_windows_comparable
    from datetime import UTC, datetime

    def _hq(**overrides: object) -> HotelQuote:
        base = dict(
            id="h", property_id="p1", name="X", property_kind="hotel", city="SIN",
            area_id=None, lat=None, lon=None, check_in=_date(2026, 8, 1),
            check_out=_date(2026, 8, 5), travelers=TravelerMix(adults=2), rooms=1,
            room_name="Deluxe", rate_plan="Refundable", cancellation_summary=None,
            refundable=True, review_score_scaled=None, review_scale_source=None,
            review_count=None, placement="organic", base_minor=None, taxes_minor=None,
            fees_minor=None, total_minor=100, currency="INR", pay_timing="unknown",
            purchasable_channels=[],
            evidence=EvidenceMeta(
                provider_id="sample_travel_adapter", provider_quote_id="q",
                source_url=None, deep_link_url=None,
                retrieved_at=datetime(2026, 8, 1, tzinfo=UTC), expires_at=None,
                status="estimated", cache_age_seconds=None, terms_version="v1",
                attribution=None, completeness="taxes_uncertain", needs_verification=True,
                notes=[],
            ),
        )
        base.update(overrides)
        return HotelQuote(**base)

    organic = _hq(placement="organic")
    sponsored = _hq(placement="sponsored")
    assert stay_windows_comparable(organic, sponsored) is True

    different_room = _hq(room_name="Suite")
    assert stay_windows_comparable(organic, different_room) is False
```

- [ ] **Step 5: run full file, verify pass** — **Step 6: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_flexible.py -v
.venv/bin/mypy --strict gateway/travel/flexible.py
git add gateway/travel/flexible.py evals/test_travel_flexible.py
git commit -m "feat(gateway): add bounded deterministic flexible travel search"
```

---

## Task 7 — Provider registry

**Files:**
- Create: `backend/gateway/travel/registry.py`
- Test: `backend/evals/test_travel_registry.py`

**Interfaces:**
- Produces: `TravelProviderRegistryEntry`, `TravelProviderRegistry.select_providers(...)`,
  `get_default_travel_registry() -> TravelProviderRegistry`.

**Ambiguity note (Tier C, DEVIATIONS):** spec 16 §7's YAML registry-entry shape is an
illustrative human-review *config* format; encoding it as literal YAML files is Tier V
(free) detail. Conservative choice: build the default registry as typed Pydantic objects in
Python (`get_default_travel_registry()`), mirroring the existing `gateway/places/registry.py`
precedent, which also builds its default registry in Python despite spec 16's illustrative
YAML — avoids introducing a second registry-loading mechanism in the same codebase.

- [ ] **Step 1: failing tests**

```python
# backend/evals/test_travel_registry.py
from __future__ import annotations

import pytest

from gateway.travel.registry import (
    TravelProviderRegistry,
    TravelProviderRegistryEntry,
    get_default_travel_registry,
)


def test_sample_adapter_is_enabled_by_default() -> None:
    registry = get_default_travel_registry()
    entry = registry.get_entry("sample_travel_adapter")
    assert entry.enabled is True
    assert entry.source_method == "sample"
    assert entry.live_data is False
    assert entry.monthly_cost_minor == 0


def test_disabled_provider_is_never_selected() -> None:
    registry = TravelProviderRegistry(entries=[
        TravelProviderRegistryEntry(
            provider_id="future_live", enabled=False,
            allowed_profiles={"student_noncommercial"}, domains={"flight"},
            countries={"SG"}, source_method="official_api", monthly_cost_minor=0,
            priority=10,
        ),
    ])
    selected = registry.select_providers(active_profile="student_noncommercial", domain="flight", country="SG")
    assert selected == []


def test_capability_mismatch_excludes_provider() -> None:
    registry = TravelProviderRegistry(entries=[
        TravelProviderRegistryEntry(
            provider_id="hotel_only", enabled=True,
            allowed_profiles={"student_noncommercial"}, domains={"hotel"},
            countries={"SG"}, source_method="sample", monthly_cost_minor=0, priority=10,
        ),
    ])
    assert registry.select_providers(active_profile="student_noncommercial", domain="flight", country="SG") == []


def test_profile_mismatch_excludes_provider() -> None:
    registry = TravelProviderRegistry(entries=[
        TravelProviderRegistryEntry(
            provider_id="commercial_only", enabled=True,
            allowed_profiles={"commercial_production"}, domains={"flight"},
            countries={"SG"}, source_method="official_api", monthly_cost_minor=0, priority=10,
        ),
    ])
    assert registry.select_providers(active_profile="student_noncommercial", domain="flight", country="SG") == []


def test_unsupported_country_excludes_provider() -> None:
    registry = get_default_travel_registry()
    registry.entries.append(
        TravelProviderRegistryEntry(
            provider_id="sg_only", enabled=True,
            allowed_profiles={"student_noncommercial"}, domains={"flight"},
            countries={"SG"}, source_method="official_api", monthly_cost_minor=0, priority=1,
        )
    )
    selected = registry.select_providers(active_profile="student_noncommercial", domain="flight", country="IN")
    assert all(e.provider_id != "sg_only" for e in selected)


def test_unknown_cost_means_disabled() -> None:
    with pytest.raises(Exception):
        TravelProviderRegistryEntry(
            provider_id="mystery", enabled=True,
            allowed_profiles={"student_noncommercial"}, domains={"flight"},
            countries={"SG"}, source_method="official_api", monthly_cost_minor=None,  # type: ignore[arg-type]
            priority=10,
        )


def test_selection_is_deterministic_ordering() -> None:
    registry = TravelProviderRegistry(entries=[
        TravelProviderRegistryEntry(
            provider_id="b", enabled=True, allowed_profiles={"student_noncommercial"},
            domains={"flight"}, countries={"SG"}, source_method="sample",
            monthly_cost_minor=0, priority=10,
        ),
        TravelProviderRegistryEntry(
            provider_id="a", enabled=True, allowed_profiles={"student_noncommercial"},
            domains={"flight"}, countries={"SG"}, source_method="sample",
            monthly_cost_minor=0, priority=10,
        ),
    ])
    selected = registry.select_providers(active_profile="student_noncommercial", domain="flight", country="SG")
    assert [e.provider_id for e in selected] == ["a", "b"]


def test_sample_adapter_always_available_even_with_zero_other_providers() -> None:
    registry = get_default_travel_registry()
    selected = registry.select_providers(active_profile="student_noncommercial", domain="flight", country="IN")
    assert any(e.provider_id == "sample_travel_adapter" for e in selected)


def test_llm_is_never_involved_in_selection() -> None:
    import inspect
    from gateway.travel import registry as registry_module
    source = inspect.getsource(registry_module)
    assert "llm" not in source.casefold()
```

- [ ] **Step 2: run, verify fail** — **Step 3: implement**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Domain = Literal["flight", "flight_trend", "hotel", "award", "fx", "poi"]
SourceMethod = Literal[
    "sample", "official_api", "provider_mcp", "community_mcp",
    "scraper_wrapper", "open_data",
]


class TravelProviderRegistryEntry(BaseModel):
    provider_id: str = Field(min_length=1)
    enabled: bool = False
    allowed_profiles: set[Literal["student_noncommercial", "commercial_production"]]
    domains: set[Domain]
    countries: set[str] | Literal["configured"] = "configured"
    source_method: SourceMethod
    live_data: bool = False
    # Unknown cost means disabled: no default here — a caller that cannot
    # state a monthly ceiling cannot construct an enabled entry.
    monthly_cost_minor: int = Field(ge=0)
    priority: int = 100


class TravelProviderRegistry(BaseModel):
    entries: list[TravelProviderRegistryEntry] = Field(default_factory=list)

    def select_providers(
        self, *, active_profile: str, domain: Domain, country: str
    ) -> list[TravelProviderRegistryEntry]:
        eligible = []
        for entry in self.entries:
            if not entry.enabled:
                continue
            if active_profile not in entry.allowed_profiles:
                continue
            if domain not in entry.domains:
                continue
            if entry.countries != "configured" and country not in entry.countries:
                continue
            eligible.append(entry)
        eligible.sort(key=lambda e: (e.priority, e.provider_id))
        return eligible

    def get_entry(self, provider_id: str) -> TravelProviderRegistryEntry:
        for entry in self.entries:
            if entry.provider_id == provider_id:
                return entry
        from gateway.travel.errors import TravelGatewayError

        raise TravelGatewayError("provider_unavailable", f"Unknown provider_id: {provider_id}")


def get_default_travel_registry() -> TravelProviderRegistry:
    sample = TravelProviderRegistryEntry(
        provider_id="sample_travel_adapter",
        enabled=True,
        allowed_profiles={"student_noncommercial", "commercial_production"},
        domains={"flight", "hotel", "award"},
        countries="configured",
        source_method="sample",
        live_data=False,
        monthly_cost_minor=0,
        priority=999,
    )
    return TravelProviderRegistry(entries=[sample])
```

- [ ] **Step 4: run, verify pass** — **Step 5: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_registry.py -v
.venv/bin/mypy --strict gateway/travel/registry.py
git add gateway/travel/registry.py evals/test_travel_registry.py
git commit -m "feat(gateway): add travel provider registry"
```

---

## Task 8 — Recorded/local fixture replay harness

**Files:**
- Create: `backend/gateway/travel/fixtures/__init__.py`,
  `backend/gateway/travel/fixtures/transport.py`, 8 JSON files under
  `backend/gateway/travel/fixtures/data/`
- Test: `backend/evals/test_travel_fixtures_harness.py`

**Interfaces:**
- Produces: `FixtureTravelTransport(fixture_dir: Path, *, now: Callable[[], datetime])
  .load(name: str) -> dict` — raises `TravelGatewayError` for the error scenarios. This is a
  seam for future G3 adapters; `SampleAdapter` does not use it (its "fixture" is the existing
  seeded `KnowledgeBase`, not JSON files).

- [ ] **Step 1: failing tests**

```python
# backend/evals/test_travel_fixtures_harness.py
from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gateway.travel.errors import TravelGatewayError
from gateway.travel.fixtures.transport import FixtureTravelTransport

FIXTURES = Path(__file__).parent.parent / "gateway" / "travel" / "fixtures" / "data"


def _transport() -> FixtureTravelTransport:
    return FixtureTravelTransport(FIXTURES, now=lambda: datetime(2026, 8, 1, tzinfo=UTC))


def test_success_fixture_loads_and_carries_source_method() -> None:
    envelope = _transport().load("flight_success")
    assert envelope["_fixture_meta"]["source_method"] == "sample"
    assert envelope["_fixture_meta"]["status"] != "live"
    assert envelope["results"]


def test_empty_fixture_is_a_successful_empty_result() -> None:
    envelope = _transport().load("flight_empty")
    assert envelope["results"] == []


def test_malformed_fixture_raises_invalid_response() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_malformed")
    assert exc_info.value.code == "invalid_response"


def test_partial_price_fixture_marks_completeness() -> None:
    envelope = _transport().load("flight_partial_price")
    assert envelope["results"]
    assert envelope["results"][0]["completeness"] in {"taxes_uncertain", "fees_uncertain", "partial"}


def test_stale_fixture_status_is_stale() -> None:
    envelope = _transport().load("flight_stale")
    assert envelope["_fixture_meta"]["status"] == "stale"


def test_rate_limited_fixture_raises_rate_limited() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_rate_limited")
    assert exc_info.value.code == "rate_limited"


def test_auth_failed_fixture_raises_authentication_failed() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_auth_failed")
    assert exc_info.value.code == "authentication_failed"


def test_timeout_fixture_raises_timeout() -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        _transport().load("flight_timeout")
    assert exc_info.value.code == "timeout"


def test_fixture_cannot_claim_live_status(tmp_path: Path) -> None:
    data = json.loads((FIXTURES / "flight_success.json").read_text())
    data["_fixture_meta"]["status"] = "live"
    bad_dir = tmp_path
    (bad_dir / "claims_live.json").write_text(json.dumps(data))
    transport = FixtureTravelTransport(bad_dir, now=lambda: datetime(2026, 8, 1, tzinfo=UTC))
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.load("claims_live")
    assert exc_info.value.code == "invalid_response"


def test_no_network_socket_is_never_touched(monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("FixtureTravelTransport must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    _transport().load("flight_success")


def test_payload_size_is_bounded(tmp_path: Path) -> None:
    huge = tmp_path / "huge.json"
    huge.write_text(json.dumps({"_fixture_meta": {"status": "estimated", "source_method": "sample"}, "results": ["x" * 600_000]}))
    transport = FixtureTravelTransport(tmp_path, now=lambda: datetime(2026, 8, 1, tzinfo=UTC))
    with pytest.raises(TravelGatewayError) as exc_info:
        transport.load("huge")
    assert exc_info.value.code == "invalid_response"
```

- [ ] **Step 2: run, verify fail (module + fixture files missing)**

- [ ] **Step 3: write the 8 fixture JSON files** under
  `backend/gateway/travel/fixtures/data/`. Envelope shape:
  `{"_fixture_meta": {"source_method": "sample", "status": "...", "captured_at":
  "2026-08-01T00:00:00Z", "known_limitations": [...]}, "results": [...]}` for success/empty/
  partial/stale, or `{"_fixture_meta": {...}, "error": {"code": "...", "message": "..."}}`
  for the 3 error cases; `flight_malformed.json` is deliberately truncated invalid JSON text
  (`{"results": [`) so `json.loads` raises.

  `flight_success.json`:
  ```json
  {
    "_fixture_meta": {"source_method": "sample", "status": "estimated", "captured_at": "2026-08-01T00:00:00Z", "known_limitations": ["synthetic fixture; not a live provider capture"]},
    "results": [{"id": "fx-1", "origin": "DEL", "destination": "SIN", "total_minor": 4100000, "currency": "INR", "completeness": "taxes_uncertain"}]
  }
  ```
  `flight_empty.json`: same envelope, `"results": []`.
  `flight_partial_price.json`: one result with `"completeness": "partial"`.
  `flight_stale.json`: `_fixture_meta.status = "stale"`, one result.
  `flight_rate_limited.json` / `flight_auth_failed.json` / `flight_timeout.json`:
  `{"_fixture_meta": {"source_method": "sample", "status": "estimated", "captured_at": "2026-08-01T00:00:00Z", "known_limitations": []}, "error": {"code": "rate_limited"|"authentication_failed"|"timeout", "message": "simulated <code> fixture"}}`.

- [ ] **Step 4: implement `transport.py`**

```python
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from gateway.travel.errors import ErrorCode, TravelGatewayError

_ERROR_FIXTURE_DEFAULT_CODE: dict[str, ErrorCode] = {
    "flight_rate_limited": "rate_limited",
    "flight_auth_failed": "authentication_failed",
    "flight_timeout": "timeout",
}


class FixtureTravelTransport:
    """Reads committed, sanitized local fixtures. Never opens a socket, never
    reads credentials, never uses the wall clock for loading (the injected
    `now` exists so callers can thread a frozen clock into identity/freshness
    code deterministically alongside the fixture read)."""

    MAX_PAYLOAD_BYTES = 512_000

    def __init__(self, fixture_dir: Path, *, now: Callable[[], datetime]) -> None:
        self.fixture_dir = fixture_dir
        self.now = now

    def load(self, name: str) -> dict[str, Any]:
        path = self.fixture_dir / f"{name}.json"
        raw = path.read_bytes()
        if len(raw) > self.MAX_PAYLOAD_BYTES:
            raise TravelGatewayError("invalid_response", f"fixture {name} exceeds payload bound")
        try:
            envelope: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TravelGatewayError("invalid_response", f"malformed fixture {name}: {exc}") from exc

        meta = envelope.get("_fixture_meta", {})
        if meta.get("status") == "live":
            raise TravelGatewayError("invalid_response", f"fixture {name} illegally claims status=live")

        if "error" in envelope:
            code = envelope["error"].get("code", _ERROR_FIXTURE_DEFAULT_CODE.get(name, "invalid_response"))
            message = envelope["error"].get("message", f"fixture {name} simulates {code}")
            raise TravelGatewayError(code, message)

        return envelope
```

- [ ] **Step 5: run, verify pass** — **Step 6: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_fixtures_harness.py -v
.venv/bin/mypy --strict gateway/travel/fixtures/transport.py
.venv/bin/ruff check gateway/travel/fixtures/
git add gateway/travel/fixtures/ evals/test_travel_fixtures_harness.py
git commit -m "feat(gateway): add recorded travel fixture replay harness"
```

---

## Task 9 — SampleAdapter

**Files:**
- Create: `backend/gateway/travel/adapters/__init__.py`, `backend/gateway/travel/adapters/sample.py`
- Test: `backend/evals/test_travel_sample_adapter.py`

**Interfaces:**
- Consumes: `core.db.KnowledgeBase.sample_flights(origin, destination, cabin)`,
  `.sample_hotels(city, style, area)` (existing), contracts from Tasks 1–2,
  `identity.flight_quote_id`/`hotel_quote_id`, `TravelGatewayError`.
- Produces: `SampleAdapter(kb: KnowledgeBase, *, now: Callable[[], datetime])` implementing
  `TravelProviderAdapter`: `search_flights`, `search_hotels` map real seed rows;
  `search_awards` returns `[]`; `search_flight_price_trends` raises `unsupported_domain`.

**Ambiguity notes (Tier C, DEVIATIONS):**
1. *Synthetic segment timing.* `SampleFlight` has no departure/arrival times or flight
   number — spec 01 §7 explicitly anticipates this ("`SampleAdapter` maps them into
   `FlightQuote`/`HotelQuote` with ... declared synthetic dates ... incomplete-detail
   notes"). Conservative choice: one segment per `FlightQuote` — never fabricate fake
   intermediate airports for `stops > 0`; `departure_at` = `depart_date` at fixed synthetic
   `09:00 UTC`; `duration_min = 240 + 120 * stops` (labeled-synthetic estimate, never used
   in any money computation); `flight_number = f"SAMPLE-{flight.id.upper()}"`. Declared in
   `evidence.notes`.
2. *Unknown tax/fee breakdown.* Conservative choice: `completeness="taxes_uncertain"` on
   every sample quote; `base_minor`/`taxes_minor`/`fees_minor` left `None`; `total_minor` =
   the seed's price unmodified.
3. *No FX conversion inside the adapter.* The adapter returns quotes in the *original* seed
   currency; conversion happens downstream in `agents/gateway_estimator.py` (Task 10),
   matching spec 16 §9 ("never overwrites the provider amount").
4. *Deterministic `retrieved_at`.* No wall clock; `now` is constructor-injected.

- [ ] **Step 1: failing tests**

```python
# backend/evals/test_travel_sample_adapter.py
from __future__ import annotations

import asyncio
import socket
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from core.db import SEEDS_DIR, load_kb, seed_database
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import (
    AwardSearchRequest,
    FlexibleFlightSearchRequest,
    FlightSearchRequest,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.errors import TravelGatewayError


def _kb(tmp_path: Path):
    db_path = tmp_path / "t.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _adapter(tmp_path: Path) -> SampleAdapter:
    return SampleAdapter(_kb(tmp_path), now=lambda: datetime(2026, 7, 25, tzinfo=UTC))


def test_search_flights_maps_seed_row_and_preserves_amount(tmp_path: Path) -> None:
    quotes = asyncio.run(_adapter(tmp_path).search_flights(FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=date(2026, 8, 5),
        travelers=TravelerMix(adults=2), cabin="economy", currency="INR",
    )))
    assert quotes
    winner = next(q for q in quotes if q.evidence.provider_quote_id == "del-sin-6e-eco")
    assert winner.total_minor == 4_100_000
    assert winner.currency == "INR"
    assert winner.segments[0].marketing_airline == "IndiGo"
    assert winner.travelers.adults == 2
    assert all(q.evidence.status == "estimated" for q in quotes)
    assert all(q.evidence.needs_verification for q in quotes)


def test_search_flights_deterministic_ids_and_timestamps(tmp_path: Path) -> None:
    req = FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=1), cabin="economy", currency="INR",
    )
    first = asyncio.run(_adapter(tmp_path).search_flights(req))
    second = asyncio.run(_adapter(tmp_path).search_flights(req))
    assert [q.id for q in first] == [q.id for q in second]
    assert [q.evidence.retrieved_at for q in first] == [q.evidence.retrieved_at for q in second]


def test_search_flights_empty_route_returns_empty_list_not_error(tmp_path: Path) -> None:
    quotes = asyncio.run(_adapter(tmp_path).search_flights(FlightSearchRequest(
        origin="NYC", destination="LON", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=1), cabin="economy", currency="USD",
    )))
    assert quotes == []


def test_search_hotels_maps_seed_row(tmp_path: Path) -> None:
    quotes = asyncio.run(_adapter(tmp_path).search_hotels(HotelSearchRequest(
        city="Singapore", check_in=date(2026, 8, 1), check_out=date(2026, 8, 5),
        travelers=TravelerMix(adults=2), rooms=1, area_ids=["marina_bay"], style="balanced",
        currency="INR",
    )))
    winner = next(q for q in quotes if q.property_id == "sg-hotel-marina-balanced")
    assert winner.total_minor == 1_600_000 * 4
    assert winner.currency == "INR"
    assert winner.evidence.status == "estimated"
    assert winner.evidence.needs_verification is True


def test_search_awards_returns_empty_no_fabricated_availability(tmp_path: Path) -> None:
    quotes = asyncio.run(_adapter(tmp_path).search_awards(AwardSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=date(2026, 8, 5),
        travelers=TravelerMix(adults=2), cabin="business", program_ids=["lionmiles"],
    )))
    assert quotes == []


def test_search_flight_price_trends_is_unsupported_domain(tmp_path: Path) -> None:
    with pytest.raises(TravelGatewayError) as exc_info:
        asyncio.run(_adapter(tmp_path).search_flight_price_trends(FlexibleFlightSearchRequest(
            origin="DEL", destination="SIN", depart_window_start=date(2026, 8, 1),
            depart_window_end=date(2026, 8, 3), return_window_start=None,
            return_window_end=None, trip_length_nights=4, travelers=TravelerMix(adults=1),
            cabin="economy", currency="INR", max_date_pairs=5,
        )))
    assert exc_info.value.code == "unsupported_domain"


def test_no_network_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("SampleAdapter must never open a socket")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    quotes = asyncio.run(_adapter(tmp_path).search_flights(FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=1), cabin="economy", currency="INR",
    )))
    assert quotes


def test_notes_document_synthetic_timing_and_incomplete_price(tmp_path: Path) -> None:
    quotes = asyncio.run(_adapter(tmp_path).search_flights(FlightSearchRequest(
        origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
        travelers=TravelerMix(adults=1), cabin="economy", currency="INR",
    )))
    notes_text = " ".join(quotes[0].evidence.notes).casefold()
    assert "synthetic" in notes_text
    assert quotes[0].evidence.completeness == "taxes_uncertain"


def test_seed_amount_is_never_modified(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    seed_row = kb.sample_flights("DEL", "SIN", "economy")[0]
    quotes = asyncio.run(SampleAdapter(kb, now=lambda: datetime(2026, 7, 25, tzinfo=UTC)).search_flights(
        FlightSearchRequest(
            origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
            travelers=TravelerMix(adults=1), cabin="economy", currency="INR",
        )
    ))
    match = next(q for q in quotes if q.evidence.provider_quote_id == seed_row.id)
    assert match.total_minor == seed_row.price_minor
```

- [ ] **Step 2: run, verify fail** — **Step 3: implement `adapters/sample.py`**

```python
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta

from core.db import KnowledgeBase
from core.models import SampleFlight, SampleHotel
from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    EvidenceMeta,
    FlexibleFlightSearchRequest,
    FlightPriceObservation,
    FlightQuote,
    FlightSearchRequest,
    FlightSegment,
    HotelQuote,
    HotelSearchRequest,
    TravelerMix,
)
from gateway.travel.errors import TravelGatewayError
from gateway.travel.identity import flight_quote_id, hotel_quote_id
from gateway.travel.protocol import AdapterCapabilities

PROVIDER_ID = "sample_travel_adapter"
TERMS_VERSION = "sample-fixture-v1"
ATTRIBUTION = "TripPlanner sample fixture data (not real inventory)"


class SampleAdapter:
    capabilities = AdapterCapabilities(
        provider_id=PROVIDER_ID,
        domains={"flight", "hotel", "award"},
        countries="configured",
        live_data=False,
        supports_cache=False,
        supports_commercial_use=False,
        allowed_profiles={"student_noncommercial", "commercial_production"},
        source_method="sample",
        stability="stable",
        requires_user_initiated_search=False,
        max_concurrency=1,
    )

    def __init__(self, kb: KnowledgeBase, *, now: Callable[[], datetime]) -> None:
        self.kb = kb
        self.now = now

    def _evidence(self, provider_quote_id: str, notes: list[str]) -> EvidenceMeta:
        return EvidenceMeta(
            provider_id=PROVIDER_ID, provider_quote_id=provider_quote_id, source_url=None,
            deep_link_url=None, retrieved_at=self.now(), expires_at=None, status="estimated",
            cache_age_seconds=None, terms_version=TERMS_VERSION, attribution=ATTRIBUTION,
            completeness="taxes_uncertain", needs_verification=True, notes=notes,
        )

    def _map_flight(self, flight: SampleFlight, depart_date: date, cabin: str, travelers: TravelerMix) -> FlightQuote:
        departure_at = datetime.combine(depart_date, time(9, 0), tzinfo=UTC)
        duration_min = 240 + 120 * flight.stops
        segment = FlightSegment(
            origin=flight.origin, destination=flight.destination, departure_at=departure_at,
            arrival_at=departure_at + timedelta(minutes=duration_min),
            marketing_airline=flight.airline, operating_airline=None,
            flight_number=f"SAMPLE-{flight.id.upper()}", cabin=cabin, duration_min=duration_min,
        )
        segments = [segment]
        notes = [
            f"Sample fixture models {flight.stops} stop(s) as a single normalized segment; "
            "intermediate routing not available.",
            "Departure/arrival times and flight number are synthetic (not a real schedule).",
            "Tax/fee breakdown not available in sample fixture; total price only.",
        ]
        if flight.notes:
            notes.append(f"Seed note: {flight.notes}")
        return FlightQuote(
            id=flight_quote_id(segments, travelers, fare_brand=None), segments=segments,
            trip_type="one_way", travelers=travelers, fare_brand=None, baggage_summary=None,
            refundable=None, changeable=None, base_minor=None, taxes_minor=None,
            fees_minor=None, total_minor=flight.price_minor, currency=flight.currency,
            purchasable_channels=list(flight.purchasable_channels),
            evidence=self._evidence(flight.id, notes),
        )

    async def search_flights(self, request: FlightSearchRequest) -> list[FlightQuote]:
        rows = self.kb.sample_flights(request.origin, request.destination, request.cabin)
        return [self._map_flight(row, request.depart_date, request.cabin, request.travelers) for row in rows]

    async def search_flight_price_trends(
        self, request: FlexibleFlightSearchRequest
    ) -> list[FlightPriceObservation]:
        raise TravelGatewayError("unsupported_domain", f"{PROVIDER_ID} does not support flight_trend")

    def _map_hotel(self, hotel: SampleHotel, request: HotelSearchRequest) -> HotelQuote:
        nights = (request.check_out - request.check_in).days
        notes = [
            "Sample fixture provides one all-in nightly rate; tax/fee breakdown not available.",
            f"total_minor is the unconverted seed nightly rate x {nights} nights (synthetic packaging, not a live quote).",
        ]
        return HotelQuote(
            id=hotel_quote_id(hotel.id, request.check_in, request.check_out, None, None),
            property_id=hotel.id, name=hotel.name, property_kind="hotel", city=hotel.city,
            area_id=hotel.area, lat=None, lon=None, check_in=request.check_in,
            check_out=request.check_out, travelers=request.travelers, rooms=request.rooms,
            room_name=None, rate_plan=None, cancellation_summary=None, refundable=None,
            review_score_scaled=None, review_scale_source=None, review_count=None,
            placement="organic", base_minor=None, taxes_minor=None, fees_minor=None,
            total_minor=hotel.price_per_night_minor * nights, currency=hotel.currency,
            pay_timing="unknown", purchasable_channels=list(hotel.purchasable_channels),
            evidence=self._evidence(hotel.id, notes),
        )

    async def search_hotels(self, request: HotelSearchRequest) -> list[HotelQuote]:
        rows = self.kb.sample_hotels(request.city, request.style)
        return [self._map_hotel(row, request) for row in rows]

    async def search_awards(self, request: AwardSearchRequest) -> list[AwardQuote]:
        # No genuine sample award-availability fixture exists in this repo: honestly
        # return empty rather than fabricate availability (spec 16 §4/G1 scope).
        return []
```

- [ ] **Step 4: run, verify pass**
- [ ] **Step 5: mypy/ruff, then commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_sample_adapter.py -v
.venv/bin/mypy --strict gateway/travel/
.venv/bin/ruff check gateway/travel/
git add gateway/travel/adapters/ evals/test_travel_sample_adapter.py
git commit -m "feat(gateway): add sample travel adapter mapping seed fixtures"
```

---

## Task 10a — Expose estimator helpers (pure refactor, separate commit)

**Files:**
- Modify: `backend/agents/estimator.py` — rename `_area_by_id`, `_destination_city`,
  `_home_currency`, `_per_diem_lines`, `_poi_lines`, `_preferred_cabin`, `_price_in_home` to
  drop their leading underscore (public names, same signatures, same bodies); update their
  in-file call sites (`estimate_costed_trip`, `_pick_flight`, `_pick_hotel`, `_poi_category`
  as applicable).

**Interfaces:** unchanged signatures, only names change:
`area_by_id`, `destination_city`, `home_currency`, `per_diem_lines`, `poi_lines`,
`preferred_cabin`, `price_in_home`.

- [ ] **Step 1: run the existing estimator tests first to record the green baseline**

```bash
cd backend && .venv/bin/pytest evals/test_m2_estimator.py evals/test_estimator_catalog.py -v
```

- [ ] **Step 2: rename in `agents/estimator.py`** (mechanical — `sed`-equivalent rename of
  the 7 identifiers and their call sites within the same file; `_pick_flight`/`_pick_hotel`
  stay private since nothing outside the file needs them).

- [ ] **Step 3: re-run the same tests, confirm byte-identical pass (zero behavior change)**

```bash
cd backend && .venv/bin/pytest evals/test_m2_estimator.py evals/test_estimator_catalog.py -v
.venv/bin/mypy --strict agents/estimator.py
.venv/bin/ruff check agents/estimator.py
```

- [ ] **Step 4: commit**

```bash
cd backend
git add agents/estimator.py
git commit -m "refactor(agents): expose estimator helpers for gateway reuse"
```

---

## Task 10 — Orchestration boundary + non-vacuous parity proof

**Files:**
- Create: `backend/agents/gateway_estimator.py`
- Test: `backend/evals/test_travel_gateway_parity.py`

**Interfaces:**
- Consumes: `agents.models.DraftItinerary`, `core.trip_models.TripSpec` (existing),
  the now-public helpers from Task 10a, `core.db.KnowledgeBase`,
  `gateway.travel.registry.get_default_travel_registry`,
  `gateway.travel.adapters.sample.SampleAdapter`, `gateway.travel.contracts.*`.
- Produces: `estimate_costed_trip_via_gateway(spec, itinerary, kb, *, booking_date) ->
  EstimatorResult` — same return type as `agents.estimator.estimate_costed_trip`.

Flight winner selection: `min(quotes, key=lambda q: (q.total_minor, len(q.segments) - 1,
q.evidence.provider_quote_id or ""))` — matches legacy's `(price_minor, stops, id)` because
`SampleAdapter` always emits exactly one segment per quote, so `len(segments) - 1 == 0 ==
flight.stops` is NOT generally true — **note the discrepancy and resolution**: since G1's
`SampleAdapter` deliberately collapses every sample flight into a single segment
(Task 9 ambiguity note 1), `len(segments) - 1` is always `0` regardless of the seed's real
`stops` value, so it cannot be used as the tie-break proxy for `stops`. Fix: thread the
original `stops` count through instead, via a small local lookup keyed by
`evidence.provider_quote_id` back to the seed row (`kb.sample_flights(...)` results, already
fetched), OR — simpler and avoiding a second KB round trip — read `stops` out of
`FlightSegment.duration_min` is fragile; instead read it directly from a private
`_gateway_stops` note-free channel is over-engineering. **Resolved choice:** since
`duration_min = 240 + 120 * stops` is a deterministic, reversible encoding set by the
adapter itself in Task 9, recover `stops = (segment.duration_min - 240) // 120` for the
tie-break only (never for money). This keeps the orchestration layer from needing adapter-
internal knowledge beyond the public contract's `duration_min` field, and is documented
inline with a comment pointing at Task 9's encoding.

Hotel winner selection: exact `area_id == itinerary.hotel_area_id` match first (cheapest by
`total_minor` among ties), else centrality-fallback among same-style quotes — identical
structure to legacy `_pick_hotel`.

- [ ] **Step 1: failing parity test**

```python
# backend/evals/test_travel_gateway_parity.py
from __future__ import annotations

from datetime import date

from agents.estimator import estimate_costed_trip
from agents.gateway_estimator import estimate_costed_trip_via_gateway
from agents.kernel import run_kernel
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from core.trip_models import TripSpec


def _kb(tmp_path):
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _spec() -> TripSpec:
    return TripSpec(
        home_country="IN", origin_city="DEL", destination_city="SIN",
        start_date=date(2026, 8, 1), end_date=date(2026, 8, 5), travelers=2,
        budget_minor=25000000, budget_currency="INR", style="balanced",
        interests=["nature", "food"],
        wallet=UserWallet(card_ids=["hdfc-infinia", "axis-atlas"], points_balances={"voyager-prime": 140000}),
    )


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(date=date(2026, 8, 1), items=[
                ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                ItineraryItem(poi_id="sg-hawker-maxwell"),
            ]),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
            ItineraryDay(date=date(2026, 8, 4), items=[]),
        ],
    )


def test_gateway_and_legacy_paths_produce_identical_costed_trip(tmp_path) -> None:
    kb = _kb(tmp_path)
    booking_date = date(2026, 7, 25)

    legacy = estimate_costed_trip(_spec(), _itinerary(), kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(_spec(), _itinerary(), kb, booking_date=booking_date)

    assert legacy.costed_trip.lines
    assert gateway.costed_trip.lines

    legacy_lines = {line.id: line.amount_minor for line in legacy.costed_trip.lines}
    gateway_lines = {line.id: line.amount_minor for line in gateway.costed_trip.lines}
    assert legacy_lines == gateway_lines
    assert legacy_lines["flight:del-sin-6e-eco"] == 8_200_000
    assert legacy_lines["hotel:sg-hotel-marina-balanced"] == 6_400_000
    assert gateway_lines["flight:del-sin-6e-eco"] == 8_200_000
    assert gateway_lines["hotel:sg-hotel-marina-balanced"] == 6_400_000
    assert legacy.costed_trip.model_dump() == gateway.costed_trip.model_dump()


def test_gateway_path_used_a_real_flight_quote_not_a_stub(tmp_path) -> None:
    kb = _kb(tmp_path)
    gateway = estimate_costed_trip_via_gateway(_spec(), _itinerary(), kb, booking_date=date(2026, 7, 25))
    assert gateway.flight is not None and gateway.flight.id == "del-sin-6e-eco"
    assert gateway.hotel is not None and gateway.hotel.id == "sg-hotel-marina-balanced"


def test_gateway_and_legacy_optimizer_and_pathfinder_numbers_are_identical(tmp_path) -> None:
    kb = _kb(tmp_path)
    spec = _spec()
    booking_date = date(2026, 7, 25)

    legacy_estimate = estimate_costed_trip(spec, _itinerary(), kb, booking_date=booking_date)
    gateway_estimate = estimate_costed_trip_via_gateway(spec, _itinerary(), kb, booking_date=booking_date)

    legacy_kernel = run_kernel(spec, legacy_estimate, kb, booking_date=booking_date)
    gateway_kernel = run_kernel(spec, gateway_estimate, kb, booking_date=booking_date)

    assert legacy_kernel.optimizer_result.gross_minor > 0
    assert legacy_kernel.optimizer_result.model_dump() == gateway_kernel.optimizer_result.model_dump()
    assert legacy_kernel.transfer_advice is not None and gateway_kernel.transfer_advice is not None
    assert legacy_kernel.transfer_advice.plans
    assert legacy_kernel.transfer_advice.model_dump() == gateway_kernel.transfer_advice.model_dump()


def test_gateway_hotel_area_fallback_matches_legacy(tmp_path) -> None:
    kb = _kb(tmp_path)
    itinerary = _itinerary().model_copy(update={"hotel_area_id": "sentosa"})
    booking_date = date(2026, 7, 25)

    legacy = estimate_costed_trip(_spec(), itinerary, kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(_spec(), itinerary, kb, booking_date=booking_date)

    assert legacy.hotel is not None and gateway.hotel is not None
    assert legacy.hotel.id == gateway.hotel.id == "sg-hotel-marina-balanced"
```

- [ ] **Step 2: run, verify fail** — `ModuleNotFoundError: agents.gateway_estimator`

- [ ] **Step 3: implement `agents/gateway_estimator.py`**

```python
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

from agents.estimator import (
    area_by_id,
    destination_city,
    home_currency,
    per_diem_lines,
    poi_lines,
    preferred_cabin,
    price_in_home,
)
from agents.models import DraftItinerary, EstimatorResult
from core.db import KnowledgeBase
from core.models import CostedTrip, SpendCategory, SpendLineItem
from core.trip_models import TripSpec
from gateway.travel.adapters.sample import SampleAdapter
from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from gateway.travel.registry import get_default_travel_registry


def _traveler_mix(spec: TripSpec) -> TravelerMix:
    return TravelerMix(adults=spec.travelers)


def _flight_stops(quote) -> int:  # type: ignore[no-untyped-def]
    # Recovers the seed's original stop count from SampleAdapter's deterministic
    # duration_min encoding (Task 9: duration_min = 240 + 120 * stops). Only used
    # for winner tie-breaking, never for money.
    return max(0, (quote.segments[0].duration_min - 240) // 120)


def _select_flight_winner(quotes: list, spec: TripSpec):  # type: ignore[no-untyped-def, type-arg]
    if not quotes:
        return None, [f"No sample flight exists for {spec.origin_city}-{spec.destination_city}."]
    winner = min(quotes, key=lambda q: (q.total_minor, _flight_stops(q), q.evidence.provider_quote_id or ""))
    return winner, []


def _select_hotel_winner(quotes: list, itinerary: DraftItinerary, kb: KnowledgeBase, city: str):  # type: ignore[no-untyped-def, type-arg]
    if not quotes:
        return None, [f"No sample hotel exists for {city}."]
    exact = [q for q in quotes if q.area_id == itinerary.hotel_area_id]
    if exact:
        return min(exact, key=lambda q: (q.total_minor, q.property_id)), []

    selected_area = area_by_id(kb, city, itinerary.hotel_area_id)
    centrality = selected_area.centrality_score if selected_area is not None else 1.0
    area_scores = {area.id: area.centrality_score for area in kb.areas(city)}
    winner = min(
        quotes,
        key=lambda q: (abs(area_scores.get(q.area_id or "", 1.0) - centrality), q.total_minor, q.property_id),
    )
    return winner, [
        f"No sample {itinerary.hotel_area_id} hotel match; used closest available area by centrality fallback."
    ]


def estimate_costed_trip_via_gateway(
    spec: TripSpec, itinerary: DraftItinerary, kb: KnowledgeBase, *, booking_date: date,
) -> EstimatorResult:
    home_ccy = home_currency(spec)
    now = datetime.combine(booking_date, datetime.min.time(), tzinfo=UTC)
    adapter = SampleAdapter(kb, now=lambda: now)
    registry = get_default_travel_registry()
    eligible = registry.select_providers(active_profile="student_noncommercial", domain="flight", country="IN")
    assert any(e.provider_id == "sample_travel_adapter" for e in eligible)

    cabin = preferred_cabin(spec.style)
    flight_quotes = asyncio.run(adapter.search_flights(FlightSearchRequest(
        origin=spec.origin_city, destination=spec.destination_city, depart_date=spec.start_date,
        return_date=spec.end_date, travelers=_traveler_mix(spec), cabin=cabin, currency=home_ccy,
    )))
    flight_winner, flight_assumptions = _select_flight_winner(flight_quotes, spec)
    if flight_winner is None and cabin != "economy":
        fallback = asyncio.run(adapter.search_flights(FlightSearchRequest(
            origin=spec.origin_city, destination=spec.destination_city, depart_date=spec.start_date,
            return_date=spec.end_date, travelers=_traveler_mix(spec), cabin="economy", currency=home_ccy,
        )))
        alt, _ = _select_flight_winner(fallback, spec)
        if alt is not None:
            flight_winner = alt
            flight_assumptions = [
                f"No sample {cabin} cash flight exists for {spec.origin_city}-{spec.destination_city}; "
                "using the cheapest economy fixture."
            ]

    city = destination_city(spec)
    hotel_quotes = asyncio.run(adapter.search_hotels(HotelSearchRequest(
        city=city, check_in=spec.start_date, check_out=spec.end_date, travelers=_traveler_mix(spec),
        rooms=1, area_ids=[itinerary.hotel_area_id], style=spec.style, currency=home_ccy,
    )))
    hotel_winner, hotel_assumptions = _select_hotel_winner(hotel_quotes, itinerary, kb, city)

    lines: list[SpendLineItem] = []
    legacy_flight = None
    if flight_winner is not None:
        candidates = kb.sample_flights(spec.origin_city, spec.destination_city, flight_winner.segments[0].cabin)
        legacy_flight = next((f for f in candidates if f.id == flight_winner.evidence.provider_quote_id), None)
        lines.append(SpendLineItem(
            id=f"flight:{flight_winner.evidence.provider_quote_id}",
            label=f"{flight_winner.segments[0].marketing_airline} round-trip flight",
            category=SpendCategory.FLIGHTS,
            amount_minor=price_in_home(flight_winner.total_minor, flight_winner.currency, home_ccy, kb) * spec.travelers,
            currency=home_ccy, available_channels=flight_winner.purchasable_channels,
            merchant_hint=flight_winner.segments[0].marketing_airline,
        ))

    legacy_hotel = None
    if hotel_winner is not None:
        nights = spec.nights
        per_night_original = hotel_winner.total_minor // nights
        legacy_hotel = next((h for h in kb.sample_hotels(city, spec.style) if h.id == hotel_winner.property_id), None)
        lines.append(SpendLineItem(
            id=f"hotel:{hotel_winner.property_id}",
            label=f"{hotel_winner.name} ({nights} nights)",
            category=SpendCategory.HOTELS,
            amount_minor=price_in_home(per_night_original, hotel_winner.currency, home_ccy, kb) * nights,
            currency=home_ccy, available_channels=hotel_winner.purchasable_channels,
            merchant_hint=hotel_winner.name,
        ))

    poi_line_items, poi_assumptions = poi_lines(spec, itinerary, kb)
    lines.extend(poi_line_items)
    per_diem_line_items, per_diem_assumptions = per_diem_lines(spec, kb)
    lines.extend(per_diem_line_items)

    return EstimatorResult(
        costed_trip=CostedTrip(
            id=f"{spec.origin_city}-{spec.destination_city}-{spec.start_date.isoformat()}",
            origin=spec.origin_city, destination=spec.destination_city, home_currency=home_ccy,
            booking_date=booking_date, trip_start_date=spec.start_date, lines=lines,
        ),
        flight=legacy_flight, hotel=legacy_hotel,
        assumptions=[*flight_assumptions, *hotel_assumptions, *poi_assumptions, *per_diem_assumptions],
    )
```

`EstimatorResult.flight`/`.hotel` reconstruct the original `SampleFlight`/`SampleHotel` seed
row by id — a deliberate compatibility shim so `EstimatorResult`'s existing typed contract
(`flight: SampleFlight | None`) is unchanged, documented here, not a design endorsement for
future gateway-native result types.

- [ ] **Step 4: run parity + legacy tests, verify both pass**

```bash
cd backend
.venv/bin/pytest evals/test_travel_gateway_parity.py evals/test_m2_estimator.py -v
```

- [ ] **Step 5: mypy/ruff, then commit**

```bash
cd backend
.venv/bin/mypy --strict agents/gateway_estimator.py
.venv/bin/ruff check agents/gateway_estimator.py evals/test_travel_gateway_parity.py
git add agents/gateway_estimator.py evals/test_travel_gateway_parity.py
git commit -m "feat(orchestration): route sample inventory through gateway with proven parity"
```

**Wiring decision (log to DEVIATIONS.md, Tier C, SCOPE-bounded):** `agents/pipeline.py`
keeps calling `agents.estimator.estimate_costed_trip` (the legacy path), NOT
`estimate_costed_trip_via_gateway`. G1's gate (spec 16 §18) requires proving parity, not
switching the live pipeline. Swapping production wiring would touch every existing
integration/E2E test and the F-series frontend contract for zero product benefit while the
gateway currently has exactly one adapter that already produces byte-identical numbers to
production — the conservative choice is to leave production wiring untouched and let this
milestone's value be the proven, tested, swappable seam. Revisit at G3 when a live adapter
gives users an actual behavior difference worth exposing.

---

## Task 11 — Boundary and zero-network guards

**Files:**
- Create: `backend/evals/test_travel_boundary.py`

- [ ] **Step 1: failing/enforcing tests**

```python
# backend/evals/test_travel_boundary.py
from __future__ import annotations

import ast
import socket
import tempfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).parent.parent / "core"


def _imports_in(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_core_never_imports_gateway() -> None:
    offenders = [
        str(path) for path in CORE_DIR.rglob("*.py")
        if any(name == "gateway" or name.startswith("gateway.") for name in _imports_in(path))
    ]
    assert offenders == []


def test_travel_gateway_search_flights_makes_no_socket_call(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from core.db import SEEDS_DIR, load_kb, seed_database
    from gateway.travel.adapters.sample import SampleAdapter
    from gateway.travel.contracts import FlightSearchRequest, TravelerMix

    def _forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("no socket calls allowed in gateway travel tests")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)

    with tempfile.TemporaryDirectory() as d:
        db_path = Path(d) / "t.sqlite"
        seed_database(SEEDS_DIR, db_path)
        kb = load_kb(db_path)
        adapter = SampleAdapter(kb, now=lambda: datetime(2026, 7, 25, tzinfo=UTC))
        quotes = asyncio.run(adapter.search_flights(FlightSearchRequest(
            origin="DEL", destination="SIN", depart_date=date(2026, 8, 1), return_date=None,
            travelers=TravelerMix(adults=1), cabin="economy", currency="INR",
        )))
        assert quotes


def test_no_secret_markers_in_travel_gateway_source() -> None:
    travel_dir = Path(__file__).parent.parent / "gateway" / "travel"
    forbidden_markers = ["sk_live", "api_key=", "Authorization: Bearer "]
    offenders = [
        str(path) for path in travel_dir.rglob("*.py")
        if any(marker in path.read_text() for marker in forbidden_markers)
    ]
    assert offenders == []
```

- [ ] **Step 2/3/4: run.** These should pass immediately if Tasks 1–10 respected the
  boundary; if `test_core_never_imports_gateway` fails, an earlier task accidentally
  regressed the boundary — fix the offending import, do not weaken the test.
- [ ] **Step 5: commit**

```bash
cd backend
.venv/bin/pytest evals/test_travel_boundary.py -v
git add evals/test_travel_boundary.py
git commit -m "test(gateway): enforce core/gateway import boundary and zero-network guard"
```

---

## Task 12 — Full-suite verification, review, and milestone report

- [ ] **Step 1: run the full backend gate**

```bash
cd backend
.venv/bin/pytest -q
.venv/bin/mypy --strict core/ agents/ api/ gateway/
.venv/bin/ruff check agents/ core/ gateway/ evals/
git diff --exit-code -- evals/golden/
cd ..
diff CLAUDE.md AGENTS.md
make gate
```

- [ ] **Step 2: invoke `superpowers:requesting-code-review`** against the full G1 diff
  (`git diff main...feat/g1-travel-inventory-gateway`), scoped to specs 09 and 16 and this
  plan's Global Constraints. Reproduce every Critical/Important finding before changing code;
  fix test-first; re-run Step 1.

- [ ] **Step 3: write `reports/g1_travel_inventory_gateway.md`** — scope/non-goals;
  architecture; files changed; contract summary; SampleAdapter behavior; fixture strategy;
  flexible-date behavior; direct-vs-gateway parity evidence; exact optimizer/pathfinder
  equality results; test count added; zero-network evidence; secrets audit; deviations;
  full gate output; remaining limitations (no G2/G3 adapters; production pipeline
  intentionally not switched); explicit no-live-provider/MCP/credential/paid-service/
  booking/crawling/transfer-execution statement.

- [ ] **Step 4: update `CLAUDE.md` checkpoint prose, copy byte-identical into `AGENTS.md`**,
  verify with `diff CLAUDE.md AGENTS.md`.

- [ ] **Step 5: final commit**

```bash
git add DEVIATIONS.md reports/g1_travel_inventory_gateway.md CLAUDE.md AGENTS.md
git commit -m "docs: record G1 travel inventory gateway milestone"
git log --oneline main..HEAD
git status
```

---

## Self-review against specs 09 and 16 (performed before execution)

- **09 §4 boundary rules** → Task 11 machine-checks `core/` never imports `gateway`; Task 10
  keeps quote objects inside `agents/gateway_estimator.py` and converts to
  `SpendLineItem`/`SampleFlight`/`SampleHotel` (existing kernel input types) before anything
  reaches `core.optimizer`/`core.transfer.pathfinder` — gateway/provider objects never reach
  the kernel.
- **09 §12 testing strategy** → every adapter test group in spec 16 §16 has a task (contract
  tests Task 1–2, SampleAdapter Task 9, registry Task 7, freshness Task 5, flexible Task 6,
  fixture harness Task 8, boundary/no-network Task 11, parity Task 10).
- **16 §18 G1 gate** → each bullet maps 1:1 to a task (see the Gate section below).
- **16 §5 SampleFlight/SampleHotel → SampleAdapter mapping** → Task 9 implements exactly
  this, with the ambiguity notes documenting the synthetic-timing decision.
- **16 §9 "never overwrites the provider amount"** → Task 9's adapter returns quotes in
  original currency; Task 10's orchestration does the (parity-tested) currency conversion.
- **Gap found and fixed during self-review:** an early draft of Task 10's flight tie-break
  used `len(segments) - 1` as a stand-in for `stops`, but `SampleAdapter` always emits one
  segment, making that always `0`. Fixed by recovering `stops` from the adapter's own
  deterministic `duration_min = 240 + 120*stops` encoding, documented inline.
  Fixed by deriving `per_night_original = total_minor // nights` before converting
  (matches legacy's per-night-then-multiply floor-rounding order) instead of converting the
  pre-multiplied total, which would have risked a different floor result under a future
  non-integer-rate corridor — documented in Task 10.
- **Gap found and fixed:** `EstimatorResult.flight`/`.hotel` typing (`SampleFlight | None`)
  wasn't addressed by early drafts of the gateway path. Fixed: Task 10 reconstructs the
  original seed row by id, documented as a deliberate compatibility shim.

## Out of scope (explicit)

Everything in the assignment's "Explicit non-goals" list: Gondola, Travelpayouts, Duffel,
OpenBnB, seats.aero, Tripadvisor live transport, any other MCP/live provider, Google Flights
scraping, runtime crawling, browser automation, bookings/holds/payments/points-transfer
execution, accounts/auth, saved trips, card acquisition, public deployment, frontend
redesign, new LLM call sites, dynamic provider discovery, LLM-selected providers, real
financial data replacing seed placeholders, paid credentials/spend. Also out of scope for
this plan specifically: switching `agents/pipeline.py`'s production wiring to the gateway
path (Task 10's logged wiring decision); any OpenAPI/frontend contract change (no public API
is touched); `search_flight_price_trends` producing real trend data (returns
`unsupported_domain` — no trend fixture exists in this repo).

## G1 gate (restated from spec 16 §18, to run in Task 12)

- [ ] normalized models and registry validation exist — Tasks 1, 2, 7
- [ ] `SampleAdapter` maps existing fixtures with `estimated` state — Task 9
- [ ] `FlightPriceObservation` is structurally non-bookable and cannot validate as `FlightQuote` — Task 2
- [ ] flexible-flight date generation is deterministic and budget-bounded — Task 6
- [ ] flexible-stay window generation/comparison are deterministic and budget-bounded — Task 6
- [ ] the complete demo plan produces the same optimizer/pathfinder numbers through the gateway — Task 10
- [ ] all gateway tests use recorded/local fixtures and pass without network — Tasks 8, 9, 11
- [ ] `backend/core/` has no gateway/provider imports — Task 11
- [ ] secrets audit is clean — Task 11
- [ ] OpenAPI/frontend artifacts synchronized if contract extended — N/A, contract not touched
