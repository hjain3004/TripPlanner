import logging
from typing import Optional
from core.trip_models import TripSpec, RetrievalContext
from core.itinerary.contracts import RouteMatrix, ItineraryConstraints
from core.itinerary.compose import ComposerResult
from core.itinerary.ortools import ORToolsComposer
from core.itinerary.greedy import GreedyComposer
from core.itinerary.validate import validate_draft

logger = logging.getLogger(__name__)

class ComposeStrategy:
    name: str = "strategy_fallback"

    def compose(
        self, spec: TripSpec, retrieval: RetrievalContext,
        matrix: Optional[RouteMatrix] = None,
        constraints: Optional[ItineraryConstraints] = None,
    ) -> ComposerResult:
        if not matrix or not constraints:
            logger.info("Missing matrix or constraints. Falling back to greedy composer.")
            return GreedyComposer().compose(spec, retrieval, matrix, constraints)

        # Attempt OR-Tools
        try:
            ortools_composer = ORToolsComposer()
            result = ortools_composer.compose(spec, retrieval, matrix, constraints)
            
            # Validate output
            validation = validate_draft(result.itinerary, matrix, constraints, retrieval)
            if validation.valid:
                return result
            else:
                logger.warning(f"ORTools produced invalid itinerary. Rejections: {validation.rejections}. Falling back to greedy.")
        except Exception as e:
            logger.warning(f"ORTools composition failed with exception: {e}. Falling back to greedy.")
            
        # Fallback to greedy
        greedy_composer = GreedyComposer()
        return greedy_composer.compose(spec, retrieval, matrix, constraints)
