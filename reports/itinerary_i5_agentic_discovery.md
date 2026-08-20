# Gate I5: Bounded Agentic Discovery

Gate I5 is formally complete. The deterministic kernel MVP pipeline now implements a bounded, agentic discovery loop inside the planner tier, preserving the strict 4-call-site architecture while enabling the model to search live (or mocked) data.

## Metrics
- 396 tests passing
- 0 out-of-bounds tool calls allowed
- 4 strict pipeline call sites maintained
- 1 tool (`search_places`) integrated safely

## Implementation Details
1. **Loop Controller**: Enforces strict budgets (`max_rounds=3`, `max_calls=6`, `max_per_day=12`).
2. **Referential Integrity**: Implemented `assert_ids_returned_by_gateway` which ensures no hallucinated `place_id`s enter the `DraftItinerary`. Only candidate IDs explicitly returned by the gateway (or existing in the `SEED_POIS`) are permitted.
3. **No Fifth Call Site**: To avoid adding a new call site, the loop invokes an injected callback `execute_planner_call`, preserving the 4 fixed nodes: `intake`, `planner`, `critic`, and `explainer`.
4. **Tool Projection**: Only the required schema fields are projected to the LLM to prevent hostile injection from poisoning verification states.
