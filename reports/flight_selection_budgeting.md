# Flight selection and budgeting

Status: **ACCEPTED on the exact-commit gate recorded in the pull request acceptance record.** The two problems reported earlier (a catalog-fixture FX failure and strict-typing findings) were investigated and are explained below; neither was a defect in the flight change, and one real test defect and the branch's own lint findings were fixed.

## Delivered workflow

An authenticated traveler can read the server-retained flight request, complete quote summaries and separate `FlightPriceObservation` discovery evidence at `GET /planning/sessions/{session_id}/flight-selection`. Observations are explicitly non-bookable and never appear in the quote resolver.

`POST /flight-selection/preview` creates a durable CP4 proposal without changing the plan. An approval recomputes only the admitted `flights` spend line through the existing deterministic kernel, updates the owner-scoped workspace with CAS/idempotency, and the existing explicit save/append APIs persist a new immutable revision. The focused API test demonstrates initial save, preview, replay, approval, append, SQLite reopen, and owner isolation.

Two input classes are separate:

- A retained provider quote is admitted only when it is current, has a verified eligible price scope and matching party, currency, request and ordered itinerary. It must provide a payment channel. There is no inference of segments, taxes, baggage, time zones, flight numbers or fare terms.
- A traveler-provided scenario total needs a currency, coverage statement, payment channel, and explicit `party_total` or `per_traveler` scope. The existing FX conversion is applied once; a per-traveler value is multiplied once by the retained party size. It remains a labelled planning estimate, never provider evidence or booking availability.

Non-flight recomputations retain an accepted flight estimate. A provider-invalidating flight refresh clears it; hotel and weather fields remain intact.

## Demonstrated offline evidence

`PYTHONDONTWRITEBYTECODE=1 backend/.venv/bin/pytest -q -p no:cacheprovider backend/evals/test_flight_selection_budgeting.py backend/evals/test_hotel_selection_budgeting.py backend/evals/test_cp4_intents.py backend/evals/test_cp4_api.py`

Result: **65 passed** (including the adversarial continuous-itinerary regression).

`make seed` completed in the isolated worktree, creating only its local sample SQLite file. `make contract-check` passed: OpenAPI export is deterministic and the generated client is byte-stable.

Frontend lint and TypeScript completed with no errors; lint retains the repository's 14 existing warnings. An earlier ad hoc `mypy` run reported 32 findings in 13 files; that count reproduces **only when mypy is run from the repository root**, where the project configuration under `backend/` (including the pydantic plugin) is not applied. With the repository's own scopes (run from `backend/`: `core accounts planning agents api gateway`, `ingestion`, `welcome`) strict mypy is clean on this branch.

Earlier the complete suite showed one failure, `evals/test_estimator_catalog.py::test_estimator_can_cost_a_catalog_poi_without_keyerror` (`Missing FX rate for SGD->INR`). Cause, reproduced on the branch: the test seeded its knowledge base from the **relative** path `Path("core/seeds")`, which exists only when pytest runs with `backend/` as the working directory; from the repository root it silently seeded nothing, so there was no FX rate. It is a working-directory-dependent test defect that predates this change, not a missing FX fact and not a catalog fixture problem. The test now uses the `SEEDS_DIR` constant (no assertion changed, no FX fact added). CI had also failed this branch on the zero-tolerance ruff scope (long lines and an import-order finding in the new flight code, plus an unstrict pairwise `zip`); those were fixed without changing behavior, and the legacy `core/`+`api/` ruff count is back to its baseline.

## Limits

- Current retained Gondola observations remain discovery-only and non-bookable; they cannot be selected or costed.
- The existing sample adapter supplies a synthetic one-way segment for the normal round-trip brief. It is inspectable retained evidence, but is correctly refused as a round-trip selection (`FLIGHT_IDENTITY_MISMATCH`). The demonstrated usable budget workflow is therefore the separately labelled traveler estimate.
- No live provider/model call, credential, booking, transfer, activation, seed-fact update, or financial formula change occurred.
- This branch is stacked on open PR #31 at `ce9acafd68a3f3cca53197831db2844e0fa71922`; it must target `codex/hotel-selection-budgeting`, not `main`, until that dependency lands.

## Independent review

One independent whole-branch review found no Critical findings and two Important findings, both reproduced and fixed before final acceptance:

1. A chronological but discontinuous `DEL → DXB`, `HKG → DEL` sequence could previously pass the first/last-segment test for a `DEL → SIN` round trip. Admission now requires contiguous segments that reach the requested destination and return to the requested origin on the retained dates; an adversarial regression covers the rejected itinerary.
2. A hotel-only provider refresh could rebuild the default flight line while retaining a prior accepted flight-selection record. The refresh now restores the accepted flight line through the existing frozen kernel when flight evidence was not refreshed; a flight refresh clears the selection record.
