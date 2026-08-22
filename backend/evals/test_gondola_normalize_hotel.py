from __future__ import annotations

import inspect
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from gateway.travel.adapters.gondola import normalize_hotel as normalize_hotel_module
from gateway.travel.adapters.gondola.contracts import GondolaHotelResult, parse_hotel_results
from gateway.travel.adapters.gondola.normalize_hotel import normalize_gondola_hotel
from gateway.travel.contracts import HotelSearchRequest, TravelerMix
from gateway.travel.errors import TravelGatewayError

FIXTURES = Path(__file__).parent.parent / "gateway" / "travel" / "adapters" / "gondola" / "fixtures"


def _load_first_result(name: str) -> GondolaHotelResult:
    envelope = json.loads((FIXTURES / f"{name}.json").read_text())
    return parse_hotel_results(envelope["results"])[0]


def _request() -> HotelSearchRequest:
    return HotelSearchRequest(
        city="Singapore",
        check_in=date(2026, 11, 10),
        check_out=date(2026, 11, 13),
        travelers=TravelerMix(adults=2),
        rooms=1,
        style="balanced",
        currency="SGD",
    )


def _now() -> datetime:
    return datetime(2026, 8, 21, tzinfo=UTC)


def test_success_fixture_normalizes_to_verify_required_never_live() -> None:
    raw = _load_first_result("search_hotels_success")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.evidence.status == "verify_required"
    assert quote.evidence.needs_verification is True


def test_total_minor_is_an_integer_matching_cash_rate() -> None:
    raw = _load_first_result("search_hotels_success")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert isinstance(quote.total_minor, int)
    assert quote.total_minor == raw.cash_rate_minor


def test_missing_cash_rate_minor_raises_invalid_response_not_a_fabricated_price() -> None:
    raw = GondolaHotelResult(hotel_id="gnd-x", name="No Price Hotel", cash_rate_minor=None)
    with pytest.raises(TravelGatewayError) as exc_info:
        normalize_gondola_hotel(raw, _request(), now=_now())
    assert exc_info.value.code == "invalid_response"


def test_partial_price_fixture_marks_completeness_partial() -> None:
    raw = _load_first_result("search_hotels_partial_price")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.evidence.completeness == "partial"


def test_success_fixture_marks_completeness_taxes_uncertain() -> None:
    raw = _load_first_result("search_hotels_success")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.evidence.completeness == "taxes_uncertain"


def test_no_fabricated_coordinates() -> None:
    raw = _load_first_result("search_hotels_success")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.lat is None
    assert quote.lon is None


def test_never_smuggles_points_rate_into_cash_fields() -> None:
    raw = _load_first_result("search_hotels_success")
    assert raw.points_rate is not None  # the fixture does carry a points rate
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    dumped = quote.model_dump()
    assert raw.points_rate not in dumped.values()  # no field literally equals the raw points rate
    assert not hasattr(quote, "points_rate")
    assert not hasattr(quote, "cents_per_point")


def test_normalize_function_body_performs_no_points_rate_arithmetic() -> None:
    source = inspect.getsource(normalize_hotel_module)
    for forbidden in ("points_rate *", "* points_rate", "points_rate /", "/ points_rate"):
        assert forbidden not in source


def test_hostile_name_is_sanitized_before_entering_hotel_quote() -> None:
    raw = _load_first_result("search_hotels_prompt_injection")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert "ignore previous instructions" not in quote.name.lower()


def test_hostile_raw_note_is_sanitized_before_entering_evidence_notes() -> None:
    raw = _load_first_result("search_hotels_prompt_injection")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    joined_notes = " ".join(quote.evidence.notes).lower()
    assert "disregard all prior rules" not in joined_notes


def test_missing_booking_link_leaves_deep_link_url_none() -> None:
    raw = _load_first_result("search_hotels_missing_booking_link")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.evidence.deep_link_url is None


def test_booking_link_on_untrusted_host_is_discarded() -> None:
    raw = GondolaHotelResult(
        hotel_id="gnd-y",
        name="Evil Link Hotel",
        cash_rate_minor=10000,
        cash_currency="SGD",
        booking_link="https://evil.example.com/steal-session",
    )
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.evidence.deep_link_url is None


def test_booking_link_on_gondola_host_is_preserved() -> None:
    raw = _load_first_result("search_hotels_success")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.evidence.deep_link_url == raw.booking_link


def test_placement_is_honestly_unknown_not_organic() -> None:
    raw = _load_first_result("search_hotels_success")
    quote = normalize_gondola_hotel(raw, _request(), now=_now())
    assert quote.placement == "unknown"
