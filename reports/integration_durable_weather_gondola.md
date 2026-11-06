# Durable jobs, weather context, and Gondola integration

Status: accepted for offline integration; live provider activation remains disabled.

## Integrated history

This branch lands the already reviewed feature branches in order: durable planning
jobs from source `3d8f741123368661e4ef9c4e31f499353341c2e`, PR #28 merge
`4f77b1548801dabcd31ff33a034b84946cc6eb16`; weather planning from source
`8ae921225fe9e08ec6219a670d013806a46dab49`, reconciled source merge
`a91d1ae92e5daa4ed4e157cd055a607fc757911e`, PR #27 merge
`d3d7279dfffb51fd1b01b66ca4878ba5829994bb`; and Gondola planning from source
`5fdeeb784544df4e15c1c15ab4d9d9f29af0e757`, reconciled source merge
`e8deab5863ef51a03ae8962b49d80556f6bee78d`.

The Gondola reconciliation preserved both sides of the main-branch changes in
`DEVIATIONS.md` and `.env.example`, retained the current config-loader typing,
and regenerated the frontend client after resolving its generated-file merge.

## Demonstrated workflow

The combined offline demonstration is:

```text
cd backend
PYTHONPATH=. .venv/bin/python -m evals.demo_gondola_hotel_plan \
  /private/tmp/tripwise-gondola-finish/normalized-hotel-quote.json \
  --flight-observations /private/tmp/tripwise-gondola-finish/flight-observations.json
```

It uses the real FastAPI authenticated endpoints, a real task-local SQLite
database, a scripted model, and recorded Gondola artifacts. It exercises typed
interview input, explicit confirmation, planning, save, SQLite reopen, and a
CP4 scoped amendment. The replay completed with `provider_calls: 0`, preserved
timestamps and evidence, retained the flight observations and weather context
through the amendment, and approved the amendment without redispatch.

The hotel artifact is the retained Gondola observation for Four Seasons Hotel
Singapore, SGD 1,970.94 (`197094` minor units). It is verify-required and not
cost-eligible because tax/fee and purchase-channel coverage is incomplete, so
the budget remains sample-backed. The flight artifact contains six typed USD
round-trip price observations. Return itineraries are unselected, times are
source-local without timezone, and the rows are non-bookable and verify-required;
they remain excluded from costing and reward allocation.

The demonstration’s weather rows are an authored, synthetic replay fixture. The
shipped climate fixture did not cover the exact retained 2027-02-10..13 window,
so the demo shifts and truncates that authored fixture in task-local storage.
It is explicitly not presented as a live forecast or provider capture.

## Safety and limitations

No live provider/model call, OAuth flow, credential access, booking, transfer,
spending, or ongoing live traffic was used. Gondola live activation and weather
live transport remain disabled by their existing flags and kill switches. The
retained artifacts are replay evidence only; no FlightQuote was fabricated and
no provider prose was promoted into costable inventory. Existing kernel
arithmetic, seeds, goldens, provenance rules, and fallback behavior remain
unchanged. The source branches, primary checkout, and other worktrees remain
preserved.

## Verification

On the exact committed integration tree, `make seed` completed successfully.
The full `make gate` passed with 3,148 backend tests passed, 53 skipped and 3
warnings; strict mypy passed for 207 core source files, 34 ingestion files and
4 welcome files; all required Ruff scopes passed; frozen artifacts, OpenAPI
contract drift, briefs and clean-tree checks passed. The first gate run had a
single non-reproducible warm-catalog timing miss; the isolated test passed and
the complete gate was rerun successfully.

PR #29's final head `86c64960fcfb3faede420604b1db2c1dfa0be22a` passed backend,
frontend, OpenAPI/client drift, and container/full-stack smoke checks before
normal merge. The merge commit is `871c08d387e18a8761364f503cfd00cc398f7180`.
