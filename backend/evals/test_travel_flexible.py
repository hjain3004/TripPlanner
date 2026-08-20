from __future__ import annotations

from datetime import UTC, date, datetime

from gateway.travel.contracts import (
    EvidenceMeta,
    FlexibleFlightSearchRequest,
    FlexibleStaySearchRequest,
    HotelQuote,
    TravelerMix,
)
from gateway.travel.flexible import (
    generate_flight_date_pairs,
    generate_stay_windows,
    stay_windows_comparable,
)


def _flex_flight(**kw: object) -> FlexibleFlightSearchRequest:
    base: dict[str, object] = dict(
        origin="DEL",
        destination="SIN",
        depart_window_start=date(2026, 8, 1),
        depart_window_end=date(2026, 8, 3),
        return_window_start=None,
        return_window_end=None,
        trip_length_nights=4,
        travelers=TravelerMix(adults=1),
        cabin="economy",
        currency="INR",
        max_date_pairs=10,
    )
    base.update(kw)
    return FlexibleFlightSearchRequest(**base)  # type: ignore[arg-type]


def test_flight_date_pairs_apply_trip_length_and_stay_in_window() -> None:
    pairs = generate_flight_date_pairs(_flex_flight())
    assert pairs
    for depart, ret in pairs:
        assert date(2026, 8, 1) <= depart <= date(2026, 8, 3)
        assert ret is not None
        assert (ret - depart).days == 4


def test_flight_date_pairs_never_exceed_window() -> None:
    pairs = generate_flight_date_pairs(
        _flex_flight(
            depart_window_start=date(2026, 8, 30),
            depart_window_end=date(2026, 8, 31),
            trip_length_nights=None,
        )
    )
    assert pairs
    for depart, _ in pairs:
        assert date(2026, 8, 30) <= depart <= date(2026, 8, 31)


def test_flight_date_pairs_respects_max_date_pairs() -> None:
    req = _flex_flight(
        depart_window_start=date(2026, 8, 1),
        depart_window_end=date(2026, 8, 10),
        trip_length_nights=None,
        max_date_pairs=3,
    )
    pairs = generate_flight_date_pairs(req)
    assert len(pairs) == 3


def test_flight_date_pairs_are_chronologically_ordered_and_deterministic() -> None:
    req = _flex_flight(
        depart_window_start=date(2026, 8, 1),
        depart_window_end=date(2026, 8, 5),
        trip_length_nights=None,
    )
    first = generate_flight_date_pairs(req)
    second = generate_flight_date_pairs(req)
    assert first == second
    assert [p[0] for p in first] == sorted(p[0] for p in first)


def test_flight_date_pairs_one_way_when_no_return_window_and_no_trip_length() -> None:
    req = _flex_flight(trip_length_nights=None)
    pairs = generate_flight_date_pairs(req)
    assert pairs
    assert all(ret is None for _, ret in pairs)


def test_flight_date_pairs_use_return_window_when_no_trip_length() -> None:
    req = _flex_flight(
        depart_window_start=date(2026, 8, 1),
        depart_window_end=date(2026, 8, 2),
        trip_length_nights=None,
        return_window_start=date(2026, 8, 5),
        return_window_end=date(2026, 8, 6),
        max_date_pairs=20,
    )
    pairs = generate_flight_date_pairs(req)
    assert pairs
    for depart, ret in pairs:
        assert ret is not None
        assert date(2026, 8, 5) <= ret <= date(2026, 8, 6)
        assert ret >= depart


def _flex_stay(**kw: object) -> FlexibleStaySearchRequest:
    base: dict[str, object] = dict(
        city="SIN",
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 5),
        nights=3,
        travelers=TravelerMix(adults=2),
        rooms=1,
        area_ids=["marina_bay"],
        style="balanced",
        currency="INR",
        property_kinds={"hotel"},
        max_start_dates=10,
    )
    base.update(kw)
    return FlexibleStaySearchRequest(**base)  # type: ignore[arg-type]


def test_stay_windows_never_exceed_window_end_for_checkout() -> None:
    windows = generate_stay_windows(_flex_stay())
    assert windows
    for start, end in windows:
        assert start >= date(2026, 8, 1)
        assert end <= date(2026, 8, 5)
        assert (end - start).days == 3


def test_stay_windows_respect_max_start_dates() -> None:
    windows = generate_stay_windows(
        _flex_stay(
            window_start=date(2026, 8, 1), window_end=date(2026, 8, 20), nights=1, max_start_dates=4
        )
    )
    assert len(windows) == 4


def test_stay_windows_deterministic_chronological_order() -> None:
    req = _flex_stay()
    first = generate_stay_windows(req)
    second = generate_stay_windows(req)
    assert first == second == sorted(first)


def test_stay_windows_empty_when_no_start_date_leaves_room_for_nights() -> None:
    req = _flex_stay(window_start=date(2026, 8, 1), window_end=date(2026, 8, 2), nights=5)
    assert generate_stay_windows(req) == []


def _hq(**overrides: object) -> HotelQuote:
    base: dict[str, object] = dict(
        id="h",
        property_id="p1",
        name="X",
        property_kind="hotel",
        city="SIN",
        area_id=None,
        lat=None,
        lon=None,
        check_in=date(2026, 8, 1),
        check_out=date(2026, 8, 5),
        travelers=TravelerMix(adults=2),
        rooms=1,
        room_name="Deluxe",
        rate_plan="Refundable",
        cancellation_summary=None,
        refundable=True,
        review_score_scaled=None,
        review_scale_source=None,
        review_count=None,
        placement="organic",
        base_minor=None,
        taxes_minor=None,
        fees_minor=None,
        total_minor=100,
        currency="INR",
        pay_timing="unknown",
        purchasable_channels=[],
        evidence=EvidenceMeta(
            provider_id="sample_travel_adapter",
            provider_quote_id="q",
            source_url=None,
            deep_link_url=None,
            retrieved_at=datetime(2026, 8, 1, tzinfo=UTC),
            expires_at=None,
            status="estimated",
            cache_age_seconds=None,
            terms_version="v1",
            attribution=None,
            completeness="taxes_uncertain",
            needs_verification=True,
            notes=[],
        ),
    )
    base.update(overrides)
    return HotelQuote(**base)  # type: ignore[arg-type]


def test_stay_windows_comparable_ignores_placement() -> None:
    organic = _hq(placement="organic")
    sponsored = _hq(placement="sponsored")
    assert stay_windows_comparable(organic, sponsored) is True


def test_stay_windows_comparable_rejects_different_room_name() -> None:
    organic = _hq(room_name="Deluxe")
    other_room = _hq(room_name="Suite")
    assert stay_windows_comparable(organic, other_room) is False


def test_stay_windows_comparable_rejects_different_dates() -> None:
    a = _hq(check_in=date(2026, 8, 1))
    b = _hq(check_in=date(2026, 8, 2))
    assert stay_windows_comparable(a, b) is False
