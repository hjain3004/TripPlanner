from __future__ import annotations

from datetime import date

from agents.estimator import estimate_costed_trip
from agents.models import DraftItinerary, ItineraryDay, ItineraryItem, TripSpec
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import Channel, SpendCategory, UserWallet


def _kb(tmp_path):
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


def test_estimator_builds_optimizer_lines_from_seeded_facts(tmp_path) -> None:
    result = estimate_costed_trip(_spec(), _itinerary(), _kb(tmp_path), booking_date=date(2026, 7, 25))

    assert result.flight is not None
    assert result.flight.id == "del-sin-6e-eco"
    assert result.hotel is not None
    assert result.hotel.id == "sg-hotel-marina-balanced"
    assert result.costed_trip.booking_date == date(2026, 7, 25)
    assert result.costed_trip.trip_start_date == date(2026, 8, 1)

    lines = {line.id: line for line in result.costed_trip.lines}
    assert lines["flight:del-sin-6e-eco"].amount_minor == 8200000
    assert lines["hotel:sg-hotel-marina-balanced"].amount_minor == 6400000
    assert lines["poi:sg-gardens-by-the-bay"].category == SpendCategory.ATTRACTIONS
    assert lines["poi:sg-gardens-by-the-bay"].amount_minor == 669920
    assert lines["poi:sg-hawker-maxwell"].amount_minor == 189600
    assert lines["per_diem:dining"].available_channels == [Channel.POS_ABROAD]
    assert lines["per_diem:dining"].amount_minor == 3539200
    assert lines["per_diem:misc"].amount_minor == 1264000
    assert "Sample per-diem estimate" in " ".join(result.assumptions)


def test_estimator_uses_centrality_fallback_when_style_missing_in_area(tmp_path) -> None:
    itinerary = _itinerary().model_copy(update={"hotel_area_id": "sentosa"})
    result = estimate_costed_trip(_spec(), itinerary, _kb(tmp_path), booking_date=date(2026, 7, 25))

    assert result.hotel is not None
    assert result.hotel.id == "sg-hotel-marina-balanced"
    assert any("fallback" in assumption.casefold() for assumption in result.assumptions)


def test_kernel_runs_optimizer_and_transfer_pathfinder(tmp_path) -> None:
    from agents.kernel import run_kernel

    estimate = estimate_costed_trip(
        _spec(), _itinerary(), _kb(tmp_path), booking_date=date(2026, 7, 25)
    )
    result = run_kernel(_spec(), estimate, _kb(tmp_path), booking_date=date(2026, 7, 25))

    assert result.optimizer_result.gross_minor > 0
    assert result.optimizer_result.effective_cost_minor > 0
    assert result.transfer_advice is not None
    assert result.transfer_advice.plans
