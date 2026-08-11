# Phase I1 — Closed-World Itinerary Safety: Execution Report

**Date:** 2026-08-11  
**Branch:** `feat/i1-safety` (worktree at `TripPlanner_I1/`)  
**Status:** All tasks complete (A1–A3, T1–T5). Gate checks pass.

---

## Completed Tasks

### Phase A — Spec pass (docs only, no code)

| Task | Summary |
|------|---------|
| **A1** | Amended `docs/specs/01_data_model.md`: retyped `POI.open_hours` from free string to structured `TimezoneAwareHours` (timezone, weekly intervals keyed 0=Mon..6=Sun, explicit closure dates). |
| **A2** | Amended `docs/specs/03_orchestration_and_agents.md`: retrieval contract is provenance-aware (ranks and may filter on trust), `_poi_row` exposes trust status. |
| **A3** | Logged Tier-C exception for `POI.open_hours` and I1-before-I0 justification in `DEVIATIONS.md`. |

### Phase B — Implementation

| Task | Summary | Files |
|------|---------|-------|
| **T1** | Provenance-aware retrieval: ranks by `needs_verification`, `verified_by`, `confidence`, `last_verified` alongside interest overlap. Added `trust_status` to `_poi_row`. Fixes H1+H2. | `agents/retrieval.py` |
| **T2** | Moved `fallback_itinerary` from `agents/planner.py` to `core/itinerary/compose.py`. Pure move, zero behavior change. | `agents/planner.py`, `core/itinerary/compose.py`, `core/itinerary/__init__.py` |
| **T3** | Implemented `TimezoneAwareHours` in `core/models.py`. Migrated `core/seeds/pois.yaml` to structured hours. Fixed `evals/test_m3_judge.py` fixture. | `core/models.py`, `core/seeds/pois.yaml`, `evals/test_m3_judge.py` |
| **T4** | Hours feasibility in the composer: `is_poi_open(poi, date)` checks weekly schedule and closed-date list. `compose_itinerary()` skips closed POIs with warnings. Fixes H3. | `core/itinerary/compose.py` |
| **T5** | Travel-time budget: `haversine_km()` + conservative `estimate_travel_min()` (1.4× stretch, 15 min overhead, 20 km/h). Per-day travel budgets by pace. `compose_itinerary()` validates and warns. Fixes H4. | `core/itinerary/compose.py` |

---

## Test Count

| Suite | Before | After | Delta |
|-------|--------|-------|-------|
| Backend total | 133 | **151** | +18 |
| T4/T5 new (`test_i1_safety.py`) | 0 | **18** | +18 |
| Optimizer golden | 12 | 12 | 0 |
| Demo output | 2 | 2 | 0 |
| Transfer pathfinder | 18 | 18 | 0 |

---

## Gate Verification (I1 plan §7)

1. **pytest:** 151 passed, 0 failed ✅
2. **mypy --strict:** 38 source files, no issues ✅
3. **Golden tests unchanged:** All 12 optimizer goldens + canonical demo pass byte-identical ✅
4. **No frontend changes:** `git diff --stat -- frontend/` is empty ✅
5. **Determinism:** `test_compose_determinism` verifies byte-identical results ✅

---

## Design Decisions Logged in DEVIATIONS.md

| Decision | Choice |
|----------|--------|
| Missing weekday key in `regular_hours` | Treat as open (conservative; unknown ≠ closed) |
| Travel-time constants | 1.4× stretch, 15 min base overhead, 20 km/h transit, relaxed/moderate/packed = 90/120/180 min |
| `fallback_itinerary` backward compat | Delegates to `compose_itinerary()`, returns only `DraftItinerary` |

---

## Architecture Notes

- `compose_itinerary()` returns `ComposerResult(itinerary, warnings, excluded_items)`.
- `fallback_itinerary()` wraps it for backward compatibility (callers in `agents/planner.py` unchanged).
- `ScheduleWarning` has three kinds: `closed_day`, `closed_date`, `travel_budget_exceeded`.
- All new code is in `core/itinerary/compose.py` — deterministic, golden-testable, no agent/API imports beyond `agents.models` for `DraftItinerary`/`TripSpec` types.

---

## Next Accuracy Risk

The primary risk is **time-of-day feasibility within a day**. Currently T4 checks whether a POI is open *at all* on a given date (weekday check), but does not verify that the proposed visit window (start time + duration) falls within the open interval. For example, a POI open 09:00–13:00 could be scheduled at 14:00 without detection. This requires time-slot assignment in the composer (Phase I4 work) and is deliberately deferred since the current fallback composer does not assign start times.

The second risk is **haversine underestimating real travel time** for routes that require crossing water (e.g., mainland → Sentosa, which requires a bridge/cable-car detour). The 1.4× stretch factor partially accounts for this, but a real routing adapter (Phase I4/I8) would be more accurate.
