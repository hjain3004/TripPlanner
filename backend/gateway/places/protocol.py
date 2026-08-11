from __future__ import annotations

from typing import Protocol

from gateway.places.contracts import PartialPlaceResult, PlaceCandidate, PlaceSearchRequest


class PlaceProviderAdapter(Protocol):
    def search_places(
        self, request: PlaceSearchRequest
    ) -> tuple[list[PlaceCandidate], PartialPlaceResult | None]:
        ...
