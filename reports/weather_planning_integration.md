# Weather planning integration

**Status: ACCEPTANCE PENDING** — implementation is offline-complete pending the
independent review, full verification, and exact-tree gate.

## Delivered path

The existing `/plan` job and confirmed-brief job now attach an optional,
application-owned `weather_context` to `FinalReport`. The context is obtained
after the deterministic Kernel report is built, so weather never changes the
itinerary, cost lines, reward arithmetic, transfer advice, or LLM call graph.
The same typed report is persisted and can be parsed after a restart; older
reports without the field remain readable with an explicit unavailable value.

The service resolves coordinates only from the admitted destination region and
uses the existing G4 Open-Meteo adapter, tool policy, stdio boundary, evidence
normalization, failure mapping, and shared SQLite call ledger. It supports
distinct current/forecast, historical, and climate evidence. Unsupported date
windows and provider failures return the fixed public message `Weather context
unavailable`, with typed status, request kind, requested dates, attribution,
retrieval/validity metadata, origin, and limitations. Climate evidence retains
the explicit “not a forecast” caveat.

## Runtime mode and safety

The default runtime remains disabled and fail-soft. Explicit activation requires
the existing audited, pinned upstream installation variables and still uses the
G4 adapter; no direct HTTP client or competing weather implementation was added.
Fixture-backed tests use synthetic provenance honestly. No live provider call,
credential, spending, or model activation was performed for this milestone.
The shared file-backed budget is keyed by the planning trace id. Weather is
context only: it does not rewrite an itinerary or enter financial arithmetic.

## Verification evidence

- Focused weather, boundary, CP4, and API tests: measured during completion.
- `make seed` completed against a task-local `TRIPWISE_DATA_DIR`.
- OpenAPI export is byte-stable across repeated exports and the generated client
  is synchronized with the committed contract.
- Full backend, typing, frontend, browser applicability, review, and exact-tree
  gate results will be recorded here before changing this status.

## Limitations

Live Open-Meteo activation remains disabled and the real historical/climate
response shapes are covered by the existing offline adapter fixtures rather
than new live evidence. A destination without an admitted region coordinate is
unavailable. Weather does not yet provide a traveler-facing dedicated UI; the
public planning report contract is the supported surface. This milestone does
not alter FI, card-bank activation, provider inventory, or frozen Kernel
arithmetic.
