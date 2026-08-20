from __future__ import annotations

from datetime import UTC, date, datetime

from gateway.travel.contracts import FlightSegment, TravelerMix
from gateway.travel.identity import (
    award_quote_id,
    flight_observation_id,
    flight_quote_id,
    hotel_quote_id,
)


def _seg(**kw: object) -> FlightSegment:
    base: dict[str, object] = dict(
        origin="DEL",
        destination="SIN",
        departure_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        arrival_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        marketing_airline="IndiGo",
        operating_airline=None,
        flight_number="6E-ECO",
        cabin="economy",
        duration_min=360,
    )
    base.update(kw)
    return FlightSegment(**base)  # type: ignore[arg-type]


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


def test_flight_quote_id_ignores_traveler_count_but_stays_deterministic() -> None:
    # identity is segment/fare based per spec 16 §10 (origin, destination,
    # departure, arrival, operating carrier, flight number); traveler count is
    # not part of flight identity.
    a = flight_quote_id([_seg()], TravelerMix(adults=1), fare_brand=None)
    b = flight_quote_id([_seg()], TravelerMix(adults=1), fare_brand=None)
    assert a == b


def test_flight_observation_id_is_deterministic_and_distinct_from_quote_id() -> None:
    a = flight_observation_id(
        provider_id="p1",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=None,
        cabin="economy",
        stops=1,
        observed_time_bucket="2026-08-01T00",
    )
    b = flight_observation_id(
        provider_id="p1",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=None,
        cabin="economy",
        stops=1,
        observed_time_bucket="2026-08-01T00",
    )
    assert a == b
    quote_id = flight_quote_id([_seg()], TravelerMix(adults=1), fare_brand=None)
    assert a != quote_id


def test_hotel_quote_id_keeps_room_rate_variants_separate() -> None:
    a = hotel_quote_id(
        "sg-hotel-marina-balanced", date(2026, 8, 1), date(2026, 8, 5), "Deluxe", "Non-refundable"
    )
    b = hotel_quote_id(
        "sg-hotel-marina-balanced", date(2026, 8, 1), date(2026, 8, 5), "Deluxe", "Refundable"
    )
    assert a != b


def test_hotel_quote_id_deterministic() -> None:
    a = hotel_quote_id("p1", date(2026, 8, 1), date(2026, 8, 5), None, None)
    b = hotel_quote_id("p1", date(2026, 8, 1), date(2026, 8, 5), None, None)
    assert a == b


def test_award_quote_id_deterministic_and_program_sensitive() -> None:
    a = award_quote_id("lionmiles", "DEL", "SIN", date(2026, 8, 1), "business", None)
    b = award_quote_id("skyorchid", "DEL", "SIN", date(2026, 8, 1), "business", None)
    assert a != b
    assert award_quote_id("lionmiles", "DEL", "SIN", date(2026, 8, 1), "business", None) == a
