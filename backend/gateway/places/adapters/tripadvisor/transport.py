from __future__ import annotations

from typing import Protocol

from gateway.places.adapters.tripadvisor.contracts import (
    TripadvisorLocation,
    TripadvisorSearchResponse,
)


class TripadvisorTransport(Protocol):
    @property
    def is_live(self) -> bool: ...

    def search_locations(
        self,
        query: str,
        destination: str | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> TripadvisorSearchResponse: ...

    def get_location_details(self, location_id: str | int) -> TripadvisorLocation: ...
