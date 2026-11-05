# Weather planning integration

**Status: OFFLINE DEVELOPMENT COMPLETE — LIVE ACTIVATION PENDING**.

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

- `make seed PY=.venv/bin/python`: passed; 42 seeded rows.
- Complete backend suite: **3,082 passed, 53 skipped, 3 warnings**.
- Focused weather/boundary/CP4/API regressions: **77 passed**; the dedicated
  weather integration module has **8 passed** tests.
- Strict mypy: **201 + 34 + 4 source files**, all clean. Ruff zero-tolerance
  scopes passed; legacy core/api scope measured **8 findings** under the ceiling
  of 12.
- OpenAPI export twice and generated-client regeneration twice: byte-stable;
  contract drift check passed. The public contract, generated client, and MSW
  fixtures shipped together.
- Frontend: TypeScript passed; Vitest **229 passed**; ESLint **0 errors, 14
  existing warnings**; token lint passed; production build passed; dead-class
  check passed; frontend contract tests **27 passed**.
- Browser mock suite: **107 passed, 13 skipped** across the normal projects;
  no live provider tests were enabled.
- Exact final-tree `make gate`: **PASSED** with the backend counts above,
  frozen goldens, contract one-PR check, identical briefs, and `TREE_CLEAN`.

## Independent review

An independent whole-branch review found no Critical or Important defects. It
identified one Minor coverage gap: CP4 weather preservation/invalidation was
implemented but not directly exercised. Two dedicated regressions were added
and passed, proving same-trip edits preserve evidence and destination changes
invalidate it without a weather dispatch.

## Limitations

Live Open-Meteo activation remains disabled and the real historical/climate
response shapes are covered by the existing offline adapter fixtures rather
than new live evidence. A destination without an admitted region coordinate is
unavailable. Weather does not yet provide a traveler-facing dedicated UI; the
public planning report contract is the supported surface. This milestone does
not alter FI, card-bank activation, provider inventory, or frozen Kernel
arithmetic.
