# Milestone Report: `CAR_RENTAL` Support & Deterministic `backend/core/perks/`

**Branch:** `codex/car-rental-and-card-perks`  
**Base:** `origin/main` (`0014a79`)  
**Date:** 2026-11-27  

---

## 1. Working Now

1. **First-class Car Rental Spend & Channel Enums:**
   - Added `SpendCategory.CAR_RENTAL = "car_rental"` and `Channel.DIRECT_CAR_RENTAL = "direct_car_rental"` in [`backend/core/models.py`](../backend/core/models.py) and synchronized `contract/openapi.json` and generated frontend TypeScript enums.
2. **Deterministic Non-Points Card Perks Valuation ([`backend/core/perks/`](../backend/core/perks/)):**
   - [`contracts.py`](../backend/core/perks/contracts.py): Typed Pydantic v2 contracts for `RentalCarProtection`, `CardGrantedStatus`, `StatementCreditPerk`, `AirlineBagPerk`, `CardPerkProfile`, `ReferenceRentalProgram`, `RentalCarCardComparison`, and `TripPerksValuation`.
   - [`evaluator.py`](../backend/core/perks/evaluator.py): Pure integer minor-unit evaluators `evaluate_rental_car_cards(...)` and `evaluate_trip_perks(...)` covering primary vs. secondary CDW (disqualifying secondary coverage, excluded countries, excess rental days, or unpaid rentals), card-granted hotel/rental/airline status benefits, checked-bag savings, and cross-item capped statement credits (zero float money arithmetic).
   - [`reference_perks.py`](../backend/core/perks/reference_perks.py): Read-only unverified (`verified_by="UNVERIFIED"`, `needs_verification=True`) reference catalog for `national-emerald`, `hertz-gold`, `avis-preferred`, `sixt-status`, and representative reference card perk profiles outside `backend/core/seeds/`.

---

## 2. Demonstrated Behavior & Execution Mode

- **Execution mode:** Pure offline Python unit tests and AST static checks (`evals/test_car_rental_and_perks.py`), verifying enum round-trips, primary-vs-secondary CDW card ranking flip, excluded-country/duration/payment disqualifications, multi-item statement-credit cap enforcement, provenance `needs_verification` warning propagation, and AST zero-float / `gateway`-isolation invariants.
- **OpenAPI & frontend sync:** Regenerated `contract/openapi.json` and `frontend/src/lib/api/generated/` so `SpendCategory` and `Channel` include `"car_rental"` and `"direct_car_rental"`.

---

## 3. Unavailable / Deferred

- Seed YAML files (`backend/core/seeds/*.yaml`), `core/loyalty/`, `core/optimizer/`, `core/transfer/`, and `gateway/` remain untouched.
- Verifying issuer terms in `reference_perks.py` requires manual human review before promoting into approved KB facts.

---

## 4. Verification Summary

- `make seed && make gate` (clean tree): **PASSED** (`GATE PASSED`, `GOLDENS_OK`, `CONTRACT_OK`, `BRIEFS_IDENTICAL`, `TREE_CLEAN`).
- `scripts/check-contract-drift.sh`: **PASSED** (`CONTRACT_DRIFT_OK`).
- Frontend `npx tsc --noEmit` & `npx vitest run`: **PASSED**.
