from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from gateway.travel.contracts import (
    AwardQuote,
    AwardSearchRequest,
    EvidenceMeta,
    FlexibleFlightSearchRequest,
    FlexibleStaySearchRequest,
    FlightPriceObservation,
    FlightQuote,
    FlightSearchRequest,
    FlightSegment,
    HotelQuote,
    HotelSearchRequest,
    TravelerMix,
)


def _evidence(**overrides: object) -> EvidenceMeta:
    base: dict[str, object] = dict(
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
    return EvidenceMeta(**base)  # type: ignore[arg-type]


def _segment(**overrides: object) -> FlightSegment:
    base: dict[str, object] = dict(
        origin="DEL",
        destination="SIN",
        departure_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
        arrival_at=datetime(2026, 8, 1, 15, 0, tzinfo=UTC),
        marketing_airline="IndiGo",
        operating_airline=None,
        flight_number="SAMPLE-DEL-SIN-6E-ECO",
        cabin="economy",
        duration_min=360,
    )
    base.update(overrides)
    return FlightSegment(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# EvidenceMeta
# --------------------------------------------------------------------------- #


def test_evidence_meta_requires_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        EvidenceMeta(
            provider_id="p",
            provider_quote_id=None,
            source_url=None,
            deep_link_url=None,
            retrieved_at=datetime(2026, 8, 1),  # naive — must be rejected
            expires_at=None,
            status="estimated",
            cache_age_seconds=None,
            terms_version="v1",
            attribution=None,
            completeness="complete",
            needs_verification=True,
            notes=[],
        )


def test_evidence_meta_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        _evidence(status="fresh")


def test_evidence_meta_live_cannot_be_past_expiry() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            status="live",
            provider_id="real_provider",
            expires_at=datetime(2020, 1, 1, tzinfo=UTC),
        )


def test_evidence_meta_sample_provider_cannot_be_live() -> None:
    with pytest.raises(ValidationError):
        _evidence(
            status="live",
            provider_id="sample_travel_adapter",
            expires_at=datetime(2099, 1, 1, tzinfo=UTC),
        )


# --------------------------------------------------------------------------- #
# Search requests
# --------------------------------------------------------------------------- #


def test_flight_search_request_normalizes_iata_and_currency() -> None:
    req = FlightSearchRequest(
        origin="del",
        destination="sin",
        depart_date=date(2026, 8, 1),
        return_date=date(2026, 8, 5),
        travelers=TravelerMix(adults=2),
        cabin="economy",
        currency="inr",
    )
    assert req.origin == "DEL"
    assert req.destination == "SIN"
    assert req.currency == "INR"


def test_flight_search_request_rejects_return_before_depart() -> None:
    with pytest.raises(ValidationError):
        FlightSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_date=date(2026, 8, 5),
            return_date=date(2026, 8, 1),
            travelers=TravelerMix(adults=1),
            cabin="economy",
            currency="INR",
        )


def test_flight_search_request_rejects_invalid_iata() -> None:
    with pytest.raises(ValidationError):
        FlightSearchRequest(
            origin="DELHI",
            destination="SIN",
            depart_date=date(2026, 8, 1),
            return_date=None,
            travelers=TravelerMix(adults=1),
            cabin="economy",
            currency="INR",
        )


def test_traveler_mix_requires_at_least_one_traveler() -> None:
    with pytest.raises(ValidationError):
        TravelerMix(adults=0, children=0, infants=0)


def test_traveler_mix_accepts_children_and_infants_without_adults_error() -> None:
    mix = TravelerMix(adults=0, children=1, infants=0)
    assert mix.children == 1


def test_hotel_search_request_rejects_checkout_not_after_checkin() -> None:
    with pytest.raises(ValidationError):
        HotelSearchRequest(
            city="SIN",
            check_in=date(2026, 8, 5),
            check_out=date(2026, 8, 5),
            travelers=TravelerMix(adults=2),
            rooms=1,
            area_ids=["marina_bay"],
            style="balanced",
            currency="INR",
        )


def test_hotel_search_request_rejects_nonpositive_rooms() -> None:
    with pytest.raises(ValidationError):
        HotelSearchRequest(
            city="SIN",
            check_in=date(2026, 8, 1),
            check_out=date(2026, 8, 5),
            travelers=TravelerMix(adults=2),
            rooms=0,
            area_ids=[],
            style="balanced",
            currency="INR",
        )


def test_hotel_search_request_defaults_property_kind_to_hotel() -> None:
    req = HotelSearchRequest(
        city="SIN",
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5),
        travelers=TravelerMix(adults=2),
        rooms=1,
        area_ids=[],
        style="balanced",
        currency="INR",
    )
    assert req.property_kinds == {"hotel"}


def test_flexible_flight_request_bounds_max_date_pairs() -> None:
    with pytest.raises(ValidationError):
        FlexibleFlightSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_window_start=date(2026, 8, 1),
            depart_window_end=date(2026, 8, 10),
            return_window_start=None,
            return_window_end=None,
            trip_length_nights=4,
            travelers=TravelerMix(adults=1),
            cabin="economy",
            currency="INR",
            max_date_pairs=0,
        )


def test_flexible_flight_request_rejects_depart_window_reversed() -> None:
    with pytest.raises(ValidationError):
        FlexibleFlightSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_window_start=date(2026, 8, 10),
            depart_window_end=date(2026, 8, 1),
            return_window_start=None,
            return_window_end=None,
            trip_length_nights=4,
            travelers=TravelerMix(adults=1),
            cabin="economy",
            currency="INR",
            max_date_pairs=5,
        )


def test_flexible_stay_request_rejects_window_end_before_start() -> None:
    with pytest.raises(ValidationError):
        FlexibleStaySearchRequest(
            city="SIN",
            window_start=date(2026, 8, 10),
            window_end=date(2026, 8, 1),
            nights=3,
            travelers=TravelerMix(adults=2),
            rooms=1,
            area_ids=[],
            style="balanced",
            currency="INR",
            property_kinds={"hotel"},
            max_start_dates=5,
        )


def test_flexible_stay_request_bounds_max_start_dates() -> None:
    with pytest.raises(ValidationError):
        FlexibleStaySearchRequest(
            city="SIN",
            window_start=date(2026, 8, 1),
            window_end=date(2026, 8, 10),
            nights=3,
            travelers=TravelerMix(adults=2),
            rooms=1,
            area_ids=[],
            style="balanced",
            currency="INR",
            property_kinds={"hotel"},
            max_start_dates=0,
        )


def test_award_search_request_normalizes_iata() -> None:
    req = AwardSearchRequest(
        origin="del",
        destination="sin",
        depart_date=date(2026, 8, 1),
        return_date=None,
        travelers=TravelerMix(adults=1),
        cabin="business",
        program_ids=["lionmiles"],
    )
    assert req.origin == "DEL"


def test_deterministic_serialization_is_stable() -> None:
    req1 = FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=None,
        travelers=TravelerMix(adults=2),
        cabin="economy",
        currency="INR",
    )
    req2 = FlightSearchRequest(
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=None,
        travelers=TravelerMix(adults=2),
        cabin="economy",
        currency="INR",
    )
    assert req1.model_dump_json() == req2.model_dump_json()


# --------------------------------------------------------------------------- #
# FlightQuote / FlightSegment invariants
# --------------------------------------------------------------------------- #


def test_flight_quote_rejects_empty_segments() -> None:
    with pytest.raises(ValidationError):
        FlightQuote(
            id="q1",
            segments=[],
            trip_type="one_way",
            travelers=TravelerMix(adults=1),
            fare_brand=None,
            baggage_summary=None,
            refundable=None,
            changeable=None,
            base_minor=None,
            taxes_minor=None,
            fees_minor=None,
            total_minor=10000,
            currency="INR",
            purchasable_channels=[],
            evidence=_evidence(),
        )


def test_flight_segment_rejects_arrival_before_departure() -> None:
    with pytest.raises(ValidationError):
        _segment(arrival_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC))


def test_flight_segment_rejects_nonpositive_duration() -> None:
    with pytest.raises(ValidationError):
        _segment(duration_min=0)


def test_flight_quote_rejects_negative_money() -> None:
    with pytest.raises(ValidationError):
        FlightQuote(
            id="q1",
            segments=[_segment()],
            trip_type="one_way",
            travelers=TravelerMix(adults=1),
            fare_brand=None,
            baggage_summary=None,
            refundable=None,
            changeable=None,
            base_minor=None,
            taxes_minor=None,
            fees_minor=None,
            total_minor=-1,
            currency="INR",
            purchasable_channels=[],
            evidence=_evidence(),
        )


def test_flight_quote_accepts_valid_shape() -> None:
    quote = FlightQuote(
        id="q1",
        segments=[_segment()],
        trip_type="one_way",
        travelers=TravelerMix(adults=1),
        fare_brand=None,
        baggage_summary=None,
        refundable=None,
        changeable=None,
        base_minor=None,
        taxes_minor=None,
        fees_minor=None,
        total_minor=4_100_000,
        currency="INR",
        purchasable_channels=[],
        evidence=_evidence(),
    )
    assert quote.total_minor == 4_100_000


# --------------------------------------------------------------------------- #
# FlightPriceObservation anti-promotion
# --------------------------------------------------------------------------- #


def _observation(**overrides: object) -> FlightPriceObservation:
    base: dict[str, object] = dict(
        id="obs1",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=None,
        cabin="economy",
        stops=1,
        observed_total_minor=400000,
        currency="INR",
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        itinerary_detail="route_only",
        evidence=_evidence(status="estimated"),
    )
    base.update(overrides)
    return FlightPriceObservation(**base)  # type: ignore[arg-type]


def test_flight_price_observation_is_bookable_is_always_false() -> None:
    obs = _observation()
    assert obs.is_bookable is False


def test_flight_price_observation_rejects_is_bookable_true() -> None:
    with pytest.raises(ValidationError):
        _observation(is_bookable=True)


def test_flight_price_observation_cannot_validate_as_flight_quote() -> None:
    obs = _observation()
    with pytest.raises(ValidationError):
        FlightQuote.model_validate(obs.model_dump())


def test_flight_price_observation_evidence_cannot_be_live() -> None:
    with pytest.raises(ValidationError):
        _observation(
            evidence=_evidence(
                status="live",
                provider_id="real_provider",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            )
        )


# --------------------------------------------------------------------------- #
# HotelQuote invariants
# --------------------------------------------------------------------------- #


def _hotel(**overrides: object) -> HotelQuote:
    base: dict[str, object] = dict(
        id="h1",
        property_id="p1",
        name="Marina Bay Harbourview",
        property_kind="hotel",
        city="SIN",
        area_id="marina_bay",
        lat=None,
        lon=None,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5),
        travelers=TravelerMix(adults=2),
        rooms=1,
        room_name=None,
        rate_plan=None,
        cancellation_summary=None,
        refundable=None,
        review_score_scaled=None,
        review_scale_source=None,
        review_count=None,
        placement="organic",
        base_minor=None,
        taxes_minor=None,
        fees_minor=None,
        total_minor=6_400_000,
        currency="INR",
        pay_timing="unknown",
        purchasable_channels=[],
        evidence=_evidence(),
    )
    base.update(overrides)
    return HotelQuote(**base)  # type: ignore[arg-type]


def test_hotel_quote_rejects_checkout_not_after_checkin() -> None:
    with pytest.raises(ValidationError):
        _hotel(check_in=date(2026, 8, 5), check_out=date(2026, 8, 5))


def test_hotel_quote_review_score_requires_scale_source() -> None:
    with pytest.raises(ValidationError):
        _hotel(review_score_scaled=8000, review_scale_source=None)


def test_hotel_quote_review_score_bounds() -> None:
    with pytest.raises(ValidationError):
        _hotel(review_score_scaled=10_001, review_scale_source="TripAdvisor 0-5 * 2000")


def test_hotel_quote_review_score_accepts_valid_pair() -> None:
    hq = _hotel(review_score_scaled=8500, review_scale_source="TripAdvisor 0-5 * 2000")
    assert hq.review_score_scaled == 8500


def test_hotel_quote_missing_coordinates_stay_none() -> None:
    hq = _hotel(lat=None, lon=None)
    assert hq.lat is None and hq.lon is None


def test_hotel_quote_rejects_negative_money() -> None:
    with pytest.raises(ValidationError):
        _hotel(total_minor=-1)


# --------------------------------------------------------------------------- #
# AwardQuote invariants
# --------------------------------------------------------------------------- #


def test_award_quote_money_and_miles_are_ints() -> None:
    aq = AwardQuote(
        id="a1",
        program_id="lionmiles",
        origin="DEL",
        destination="SIN",
        depart_date=date(2026, 8, 1),
        return_date=date(2026, 8, 5),
        cabin="business",
        travelers=TravelerMix(adults=2),
        seats_available=None,
        miles_total=124_000,
        fees_minor=1_800_000,
        fees_currency="INR",
        operating_airline=None,
        mixed_cabin=None,
        evidence=_evidence(status="verify_required"),
    )
    assert isinstance(aq.miles_total, int)
    assert isinstance(aq.fees_minor, int)


def test_award_quote_sample_evidence_cannot_be_live() -> None:
    with pytest.raises(ValidationError):
        AwardQuote(
            id="a1",
            program_id="lionmiles",
            origin="DEL",
            destination="SIN",
            depart_date=date(2026, 8, 1),
            return_date=None,
            cabin="business",
            travelers=TravelerMix(adults=1),
            seats_available=None,
            miles_total=1,
            fees_minor=0,
            fees_currency="INR",
            operating_airline=None,
            mixed_cabin=None,
            evidence=_evidence(
                status="live",
                provider_id="sample_travel_adapter",
                expires_at=datetime(2099, 1, 1, tzinfo=UTC),
            ),
        )


def test_award_quote_rejects_negative_miles() -> None:
    with pytest.raises(ValidationError):
        AwardQuote(
            id="a1",
            program_id="lionmiles",
            origin="DEL",
            destination="SIN",
            depart_date=date(2026, 8, 1),
            return_date=None,
            cabin="business",
            travelers=TravelerMix(adults=1),
            seats_available=None,
            miles_total=-1,
            fees_minor=0,
            fees_currency="INR",
            operating_airline=None,
            mixed_cabin=None,
            evidence=_evidence(status="verify_required"),
        )
