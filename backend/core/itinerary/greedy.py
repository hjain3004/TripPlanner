from typing import Optional
from core.trip_models import TripSpec, RetrievalContext
from core.itinerary.contracts import RouteMatrix, ItineraryConstraints
from core.itinerary.compose import ComposerResult, compose_itinerary

class GreedyComposer:
    name: str = "greedy"

    def compose(
        self, spec: TripSpec, retrieval: RetrievalContext,
        matrix: Optional[RouteMatrix] = None,
        constraints: Optional[ItineraryConstraints] = None,
    ) -> ComposerResult:
        return compose_itinerary(spec, retrieval)
