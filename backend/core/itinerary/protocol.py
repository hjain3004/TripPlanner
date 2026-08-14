# ruff: noqa: E501, E402
from typing import Protocol

from core.itinerary.compose import ComposerResult
from core.itinerary.contracts import ItineraryConstraints, RouteMatrix
from core.trip_models import RetrievalContext, TripSpec


class Composer(Protocol):
    name: str
    def compose(
        self, spec: TripSpec, retrieval: RetrievalContext,
        matrix: RouteMatrix | None = None,
        constraints: ItineraryConstraints | None = None,
    ) -> ComposerResult: ...
