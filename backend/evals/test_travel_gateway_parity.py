from __future__ import annotations

from datetime import date

from agents.estimator import estimate_costed_trip
from agents.gateway_estimator import estimate_costed_trip_via_gateway
from agents.kernel import run_kernel
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from core.trip_models import TripSpec


def _kb(tmp_path):  # type: ignore[no-untyped-def]
    db_path = tmp_path / "tripwise.sqlite"
    seed_database(SEEDS_DIR, db_path)
    return load_kb(db_path)


def _spec() -> TripSpec:
    return TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        travelers=2,
        budget_minor=25000000,
        budget_currency="INR",
        style="balanced",
        interests=["nature", "food"],
        wallet=UserWallet(
            card_ids=["hdfc-infinia", "axis-atlas"],
            points_balances={"voyager-prime": 140000},
        ),
    )


def _itinerary() -> DraftItinerary:
    return DraftItinerary(
        hotel_area_id="marina_bay",
        days=[
            ItineraryDay(
                date=date(2026, 8, 1),
                items=[
                    ItineraryItem(poi_id="sg-gardens-by-the-bay"),
                    ItineraryItem(poi_id="sg-hawker-maxwell"),
                ],
            ),
            ItineraryDay(date=date(2026, 8, 2), items=[]),
            ItineraryDay(date=date(2026, 8, 3), items=[]),
            ItineraryDay(date=date(2026, 8, 4), items=[]),
        ],
    )


def test_gateway_and_legacy_paths_produce_identical_costed_trip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    booking_date = date(2026, 7, 25)

    legacy = estimate_costed_trip(_spec(), _itinerary(), kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(_spec(), _itinerary(), kb, booking_date=booking_date)

    assert legacy.costed_trip.lines  # non-vacuous
    assert gateway.costed_trip.lines  # proves the gateway path actually ran

    legacy_lines = {line.id: line.amount_minor for line in legacy.costed_trip.lines}
    gateway_lines = {line.id: line.amount_minor for line in gateway.costed_trip.lines}
    assert legacy_lines == gateway_lines

    assert legacy_lines["flight:del-sin-6e-eco"] == 8_200_000
    assert legacy_lines["hotel:sg-hotel-marina-balanced"] == 6_400_000
    assert gateway_lines["flight:del-sin-6e-eco"] == 8_200_000
    assert gateway_lines["hotel:sg-hotel-marina-balanced"] == 6_400_000

    assert legacy.costed_trip.model_dump() == gateway.costed_trip.model_dump()


def test_gateway_path_used_a_real_flight_quote_not_a_stub(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    gateway = estimate_costed_trip_via_gateway(
        _spec(), _itinerary(), kb, booking_date=date(2026, 7, 25)
    )
    assert gateway.flight is not None
    assert gateway.flight.id == "del-sin-6e-eco"
    assert gateway.hotel is not None
    assert gateway.hotel.id == "sg-hotel-marina-balanced"


def test_gateway_and_legacy_optimizer_and_pathfinder_numbers_are_identical(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    spec = _spec()
    booking_date = date(2026, 7, 25)

    legacy_estimate = estimate_costed_trip(spec, _itinerary(), kb, booking_date=booking_date)
    gateway_estimate = estimate_costed_trip_via_gateway(
        spec, _itinerary(), kb, booking_date=booking_date
    )

    legacy_kernel = run_kernel(spec, legacy_estimate, kb, booking_date=booking_date)
    gateway_kernel = run_kernel(spec, gateway_estimate, kb, booking_date=booking_date)

    assert legacy_kernel.optimizer_result.gross_minor > 0  # non-vacuous
    assert legacy_kernel.optimizer_result.gross_minor == gateway_kernel.optimizer_result.gross_minor
    assert (
        legacy_kernel.optimizer_result.effective_cost_minor
        == gateway_kernel.optimizer_result.effective_cost_minor
    )
    assert (
        legacy_kernel.optimizer_result.model_dump() == gateway_kernel.optimizer_result.model_dump()
    )

    assert legacy_kernel.transfer_advice is not None
    assert gateway_kernel.transfer_advice is not None
    assert legacy_kernel.transfer_advice.plans  # non-vacuous
    assert legacy_kernel.transfer_advice.model_dump() == gateway_kernel.transfer_advice.model_dump()


def test_gateway_hotel_area_fallback_matches_legacy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    itinerary = _itinerary().model_copy(update={"hotel_area_id": "sentosa"})
    booking_date = date(2026, 7, 25)

    legacy = estimate_costed_trip(_spec(), itinerary, kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(_spec(), itinerary, kb, booking_date=booking_date)

    assert legacy.hotel is not None and gateway.hotel is not None
    assert legacy.hotel.id == gateway.hotel.id == "sg-hotel-marina-balanced"


def test_gateway_records_same_assumptions_shape_as_legacy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    booking_date = date(2026, 7, 25)
    legacy = estimate_costed_trip(_spec(), _itinerary(), kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(_spec(), _itinerary(), kb, booking_date=booking_date)
    assert legacy.assumptions  # non-vacuous (per-diem assumption always present)
    assert gateway.assumptions
    assert any("per-diem" in a.casefold() for a in legacy.assumptions)
    assert any("per-diem" in a.casefold() for a in gateway.assumptions)


def _synthetic_currency_mismatch_kb(tmp_path):  # type: ignore[no-untyped-def]
    """Isolated temp seed set (not the committed core/seeds/) with a hotel
    priced in a currency other than home currency, and an FX rate chosen so
    that converting the pre-multiplied stay total gives a DIFFERENT floor
    result than converting the per-night price and multiplying by nights:
    333 minor/night x 3 nights = 999 total; rate_micro=3000 (0.003) gives
    floor(999*3000/1e6)=2 but floor(333*3000/1e6)*3 = 0*3 = 0. This proves
    the gateway path's per-night-recovery-before-conversion order (see
    agents/gateway_estimator.py and the matching DEVIATIONS.md entry) is
    load-bearing, not merely plausible.
    """
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "sample_hotels.yaml").write_text(
        """
- id: test-hotel-usd
  city: Singapore
  name: Test Hotel
  area: test_area
  stars: 3
  price_per_night_minor: 333
  currency: USD
  style: balanced
  purchasable_channels: [ota_generic]
  provenance:
    source_type: manual_curation
    last_verified: "2026-07-07"
    verified_by: UNVERIFIED
    needs_verification: true
    confidence: 0.5
"""
    )
    (seeds_dir / "fx_rates.yaml").write_text(
        """
- base: USD
  quote: INR
  rate_micro: 3000
  as_of: "2026-07-07"
  provenance:
    source_type: manual_curation
    last_verified: "2026-07-07"
    verified_by: UNVERIFIED
    needs_verification: true
    confidence: 0.5
- base: SGD
  quote: INR
  rate_micro: 63200000
  as_of: "2026-07-07"
  provenance:
    source_type: manual_curation
    last_verified: "2026-07-07"
    verified_by: UNVERIFIED
    needs_verification: true
    confidence: 0.5
"""
    )
    db_path = tmp_path / "synthetic.sqlite"
    seed_database(seeds_dir, db_path)
    return load_kb(db_path)


def test_gateway_hotel_currency_conversion_matches_legacy_when_currency_differs_from_home(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    kb = _synthetic_currency_mismatch_kb(tmp_path)
    spec = TripSpec(
        home_country="IN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 4),
        travelers=1,
        style="balanced",
        wallet=UserWallet(card_ids=[]),
    )
    itinerary = DraftItinerary(
        hotel_area_id="test_area",
        days=[ItineraryDay(date=date(2026, 8, 1), items=[])],
    )
    booking_date = date(2026, 7, 25)

    legacy = estimate_costed_trip(spec, itinerary, kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(spec, itinerary, kb, booking_date=booking_date)

    legacy_hotel_line = next(
        line for line in legacy.costed_trip.lines if line.id == "hotel:test-hotel-usd"
    )
    gateway_hotel_line = next(
        line for line in gateway.costed_trip.lines if line.id == "hotel:test-hotel-usd"
    )

    # floor(333*3000/1e6)*3 = 0*3 = 0 -- the per-night-then-multiply order.
    # A buggy total-first order would instead yield floor(999*3000/1e6) = 2,
    # which this test would catch.
    assert legacy_hotel_line.amount_minor == 0
    assert gateway_hotel_line.amount_minor == legacy_hotel_line.amount_minor


def test_gateway_hotel_area_match_is_case_insensitive_like_legacy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    kb = _kb(tmp_path)
    itinerary = _itinerary().model_copy(update={"hotel_area_id": "MARINA_BAY"})
    booking_date = date(2026, 7, 25)

    legacy = estimate_costed_trip(_spec(), itinerary, kb, booking_date=booking_date)
    gateway = estimate_costed_trip_via_gateway(_spec(), itinerary, kb, booking_date=booking_date)

    assert legacy.hotel is not None and gateway.hotel is not None
    assert legacy.hotel.id == gateway.hotel.id == "sg-hotel-marina-balanced"
    # Case-insensitive exact match should NOT trigger the centrality-fallback
    # assumption on either path.
    assert not any("fallback" in a.casefold() for a in legacy.assumptions)
    assert not any("fallback" in a.casefold() for a in gateway.assumptions)
