from datetime import UTC, datetime, timedelta

import pytest

from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest, TravelerMix
from gateway.travel.product import TravelInventorySnapshot
from gateway.travel.reuse import InventoryReuseRequired, PinnedInventoryService


def _requests() -> tuple[FlightSearchRequest, HotelSearchRequest]:
    travelers = TravelerMix(adults=2, children=0, infants=0)
    return (
        FlightSearchRequest(
            origin="DEL",
            destination="SIN",
            depart_date=datetime(2026, 11, 1, tzinfo=UTC).date(),
            return_date=datetime(2026, 11, 5, tzinfo=UTC).date(),
            travelers=travelers,
            cabin="economy",
            currency="INR",
        ),
        HotelSearchRequest(
            city="SIN",
            check_in=datetime(2026, 11, 1, tzinfo=UTC).date(),
            check_out=datetime(2026, 11, 5, tzinfo=UTC).date(),
            travelers=travelers,
            rooms=1,
            currency="INR",
            style="balanced",
            area_ids=["marina_bay"],
        ),
    )


def test_pinned_reuse_preserves_snapshot_bytes_and_never_refreshes_time() -> None:
    flight, hotel = _requests()
    retrieved = datetime(2026, 10, 25, tzinfo=UTC)
    snapshot = TravelInventorySnapshot(
        flight_request=flight,
        hotel_request=hotel,
        retrieved_at=retrieved,
        expires_at=retrieved + timedelta(days=1),
    )
    service = PinnedInventoryService(snapshot, now=lambda: datetime(2026, 10, 25, 12, tzinfo=UTC))
    reused = service.reuse(flight=flight, hotel=hotel)
    assert reused.model_dump_json() == snapshot.model_dump_json()


def test_pinned_reuse_rejects_expired_or_mismatched_search_without_transport() -> None:
    flight, hotel = _requests()
    retrieved = datetime(2026, 10, 25, tzinfo=UTC)
    service = PinnedInventoryService(
        TravelInventorySnapshot(
            flight_request=flight,
            hotel_request=hotel,
            retrieved_at=retrieved,
            expires_at=retrieved + timedelta(hours=1),
        ),
        now=lambda: datetime(2026, 10, 26, tzinfo=UTC),
    )
    with pytest.raises(InventoryReuseRequired):
        service.reuse(flight=flight, hotel=hotel)
