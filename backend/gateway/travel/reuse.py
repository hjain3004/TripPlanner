"""Transport-free reuse of evidence admitted by a confirmed plan."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from gateway.travel.contracts import FlightSearchRequest, HotelSearchRequest
from gateway.travel.product import TravelInventorySnapshot


class InventoryReuseRequired(ValueError):
    """The captured evidence cannot answer the requested confirmed search."""


class PinnedInventoryService:
    """Return deep copies of one admitted snapshot without contacting a provider."""

    def __init__(self, snapshot: TravelInventorySnapshot, *, now: Callable[[], datetime]) -> None:
        self._snapshot = snapshot.model_copy(deep=True)
        self._now = now

    def reuse(
        self,
        *,
        flight: FlightSearchRequest,
        hotel: HotelSearchRequest,
        domains: set[str] | None = None,
    ) -> TravelInventorySnapshot:
        requested = {"flight", "hotel"} if domains is None else set(domains)
        if not requested <= {"flight", "hotel"}:
            raise InventoryReuseRequired("unsupported inventory domain")
        if "flight" in requested and flight != self._snapshot.flight_request:
            raise InventoryReuseRequired("retained flight evidence does not match the request")
        if "hotel" in requested and hotel != self._snapshot.hotel_request:
            raise InventoryReuseRequired("retained hotel evidence does not match the request")
        if not self._snapshot.is_current(self._now()):
            raise InventoryReuseRequired("retained inventory evidence has expired")
        return self._snapshot.model_copy(deep=True)
