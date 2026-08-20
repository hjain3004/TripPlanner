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
