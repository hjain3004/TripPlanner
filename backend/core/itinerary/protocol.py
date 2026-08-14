from typing import Protocol, Optional
from core.trip_models import TripSpec, RetrievalContext
from core.itinerary.contracts import RouteMatrix, ItineraryConstraints
from core.itinerary.compose import ComposerResult

class Composer(Protocol):
    name: str
    def compose(
        self, spec: TripSpec, retrieval: RetrievalContext,
        matrix: Optional[RouteMatrix] = None,
        constraints: Optional[ItineraryConstraints] = None,
    ) -> ComposerResult: ...
