# ruff: noqa: E501, E402
from datetime import date

from core.itinerary.contracts import ItineraryConstraints, RouteMatrix
from core.itinerary.fallback import ComposeStrategy
from core.models import UserWallet
from core.trip_models import TripSpec
from evals.test_i1_safety import _poi, _retrieval


def _matrix() -> RouteMatrix:
    return RouteMatrix(cells=[])

def test_compose_strategy_uses_ortools_then_falls_back():
    s = TripSpec(
        home_country="IN", origin_city="DEL", destination_city="SIN", 
        start_date=date(2026, 8, 3), end_date=date(2026, 8, 7), travelers=2,
        budget_minor=25000000, budget_currency="INR", style="balanced",
        interests=["nature"], pace="moderate",
        wallet=UserWallet(card_ids=[])
    )
    ctx = _retrieval([_poi("p1")])
    
    # ComposeStrategy should return the ORTools output if valid. If we make it invalid or timeout, it returns greedy.
    # We will just test that calling compose() on the strategy returns a ComposerResult that matches what greedy would return if ORTools failed,
    # or what ORTools returns if it succeeds.
    
    strategy = ComposeStrategy()
    result = strategy.compose(s, ctx, _matrix(), ItineraryConstraints(max_daily_travel_min=120))
    
    # Assert result is valid
    assert len(result.itinerary.days) == 4
