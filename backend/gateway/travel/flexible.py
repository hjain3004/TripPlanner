"""Bounded deterministic flexible-date generation — spec 16 §4/§11.

Pure functions: no LLM, no provider call, and no I/O may generate or broaden
dates. Every candidate stays inside the caller's declared window and never
exceeds the declared bound (max_date_pairs / max_start_dates).
"""

from __future__ import annotations

from datetime import date, timedelta

from gateway.travel.contracts import (
    FlexibleFlightSearchRequest,
    FlexibleStaySearchRequest,
    HotelQuote,
)


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
    room/rate, dates, and mandatory-fee scope match. Sponsored ``placement``
    must never gate comparability (nor ranking — that rule lives in the
    orchestration ranking layer, not here)."""
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
