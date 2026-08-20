from datetime import timedelta

from core.itinerary.compose import (
    ComposerResult,
    ScheduleWarning,
    check_poi_hours,
)
from core.itinerary.contracts import ItineraryConstraints, RouteMatrix
from core.itinerary.greedy import GreedyComposer
from core.models import POI
from core.trip_models import DraftItinerary, ItineraryDay, ItineraryItem, RetrievalContext, TripSpec


class ORToolsComposer:
    name: str = "ortools"

    def compose(
        self,
        spec: TripSpec,
        retrieval: RetrievalContext,
        matrix: RouteMatrix | None = None,
        constraints: ItineraryConstraints | None = None,
    ) -> ComposerResult:
        # Fallback to greedy if no matrix or constraints, as ORTools needs them.
        if not matrix or not constraints or len(retrieval.pois) == 0:
            return GreedyComposer().compose(spec, retrieval, matrix, constraints)

        try:
            from ortools.constraint_solver import (  # type: ignore[import-untyped]
                pywrapcp,
                routing_enums_pb2,
            )
        except ImportError:
            return GreedyComposer().compose(spec, retrieval, matrix, constraints)

        # Simplified VRP setup: 1 depot (dummy), nodes = pois
        # Vehicles = nights.
        num_vehicles = spec.nights
        nodes: list[POI | None] = [None] + list(retrieval.pois)  # 0 is dummy depot

        # We need a travel time matrix
        time_matrix = []
        for i in range(len(nodes)):
            row = []
            for j in range(len(nodes)):
                node_i = nodes[i]
                node_j = nodes[j]
                if node_i is None or node_j is None:
                    row.append(0)
                elif i == j:
                    row.append(0)
                else:
                    dur = matrix.duration_min(node_i.id, node_j.id, "transit")
                    row.append(dur if dur is not None else 30)  # default 30 min
            time_matrix.append(row)

        manager = pywrapcp.RoutingIndexManager(len(nodes), num_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        def time_callback(from_index: int, to_index: int) -> int:
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            return int(time_matrix[from_node][to_node])

        transit_callback_index = routing.RegisterTransitCallback(time_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

        # Add Time constraint
        routing.AddDimension(
            transit_callback_index,
            0,  # no slack
            constraints.max_daily_travel_min,  # vehicle max time
            True,  # start cumul to zero
            "Time",
        )
        routing.GetDimensionOrDie("Time")

        # Add penalties for dropping visits (so it's optional to visit all)
        penalty = 1000
        for node in range(1, len(nodes)):
            routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
        )

        solution = routing.SolveWithParameters(search_parameters)

        if not solution:
            return GreedyComposer().compose(spec, retrieval, matrix, constraints)

        days: list[ItineraryDay] = []
        warnings: list[ScheduleWarning] = []
        excluded: list[str] = []

        hotel_area_id = retrieval.areas[0].id if retrieval.areas else "unknown"

        for vehicle_id in range(num_vehicles):
            visit_date = spec.start_date + timedelta(days=vehicle_id)
            items = []
            index = routing.Start(vehicle_id)

            # Extract route
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                poi = nodes[node_index]
                if poi is not None:
                    status = check_poi_hours(poi, visit_date)
                    if status == "closed":
                        excluded.append(poi.id)
                    else:
                        items.append(ItineraryItem(poi_id=poi.id))
                index = solution.Value(routing.NextVar(index))

            days.append(ItineraryDay(date=visit_date, items=items))

        itinerary = DraftItinerary(
            hotel_area_id=hotel_area_id,
            days=days,
            notes=["OR-Tools TSP optimized route"],
            itinerary_quality="fallback",
        )

        return ComposerResult(
            itinerary=itinerary,
            warnings=warnings,
            excluded_items=excluded,
        )
