# ruff: noqa: E501, E402
import logging

from core.itinerary.compose import ComposerResult
from core.itinerary.contracts import ItineraryConstraints, RouteMatrix
from core.itinerary.greedy import GreedyComposer
from core.itinerary.ortools_composer import ORToolsComposer
from core.itinerary.validate import validate_draft
from core.trip_models import RetrievalContext, TripSpec

logger = logging.getLogger(__name__)

class ComposeStrategy:
    name: str = "strategy_fallback"

    def compose(
        self, spec: TripSpec, retrieval: RetrievalContext,
        matrix: RouteMatrix | None = None,
        constraints: ItineraryConstraints | None = None,
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
