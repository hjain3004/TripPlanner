# Loyalty Ecosystem Foundation (`backend/core/loyalty/`)

**Status:** COMPLETE on branch `codex/loyalty-ecosystem`.

## 1. Capability Summary

`backend/core/loyalty/` adds a pure, deterministic domain bridge connecting TripWise's transfer pathfinder/OPT-2 pooling engine (`core/transfer/`) with real-world airline and hotel loyalty rules:

1. **Hotel brand matcher (`hotel_brands.py`):** Word-boundary, NFKD/casefold Unicode-folded, longest-phrase matcher mapping property names across Marriott Bonvoy, World of Hyatt, Hilton Honors, IHG One Rewards, Accor ALL, Shangri-La Circle, GHA DISCOVERY, Taj InnerCircle/NeuPass, Club ITC, Wyndham Rewards, Choice Privileges, and Radisson Rewards to canonical `program_id`s, while rejecting ambiguous generic titles (`"Grand Hotel Independent"`, `"Park View Inn"`, `"WXYZ Hostel"`, `"Taj Mahal View Guest House"`, `"Raffles Place Boutique Hostel"`).
2. **Deterministic hotel award & direct-vs-OTA arithmetic (`award_rules.py`):**
   - `compute_hotel_award_stay_points()` computes 5th-night-free (cheapest night per consecutive 5-night block for Marriott/Hilton) and 4th-night-free (4th night per consecutive 4-night block for IHG cardholders) using integer point arithmetic only.
   - `compare_direct_vs_ota_hotel()` converts eligible spend into USD minor units via single-division exact integer `FX_RATE_MICRO` (supporting 0-, 2-, and 3-decimal ISO 4217 currencies and runtime `bool`/`int` bounds guards), scales base earn by `1 + elite_bonus_bp / 10_000`, prices forfeited loyalty points + elite perks against OTA/portal price and card-points deltas, and recommends `"BOOK_DIRECT"`, `"BOOK_OTA"`, or `"TIE"`.
   - `find_partner_booking_programs()` resolves Star Alliance, oneworld, SkyTeam, and bilateral ticketing programs for an operating IATA carrier.
3. **Unverified reference catalog & non-mutating KB overlay (`reference_catalog.yaml`, `catalog_loader.py`):**
   - Supplies global + India/UAE airline, hotel, and card-currency `LoyaltyProgram` rows, starter `TransferEdge`s, hotel brand rules, Nth-night-free rules, and alliance/bilateral partner edges—every row strictly marked `verified_by="UNVERIFIED"` and `needs_verification=True`.
   - `load_loyalty_overlay_kb(base_kb)` returns a fresh in-memory `KnowledgeBase` merged cleanly (`base_kb` > `extra_edges` > `catalog`) for OPT-2 `solve_pooled_transfer` / `find_transfer_plans` without modifying `base_kb`, SQLite, or `core/seeds/*.yaml`.

## 2. Demonstrated Execution & Evidence

- Exercised offline in `backend/evals/test_loyalty_ecosystem.py` (with real `core.db.seed_database`, `KnowledgeBase.from_models`, OPT-2 CP-SAT `solve_pooled_transfer`, and `find_transfer_plans(..., allow_pooling=True)` pooling `chase-ur` + `amex-mr-us` -> `aeroplan` while preserving `"VERIFY (blocking):"` checklist step 1).
- AST check confirms `backend/core/loyalty/` imports zero `gateway/`, `api/`, `agents/`, or network/process packages and contains zero `float` arithmetic or literals in `award_rules.py` and `catalog_loader.py`.

## 3. Remaining Boundaries & Deferred Work

- All `reference_catalog.yaml` ratios, earn rates, and partner edges remain `UNVERIFIED` reference data (`needs_verification=True`) pending human verification.
- `run_pipeline()` / API routes do not automatically load `load_loyalty_overlay_kb()` yet; callers opt in explicitly in memory, leaving existing seed data, goldens, and OpenAPI unchanged.
