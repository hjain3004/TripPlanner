# Milestone Report: F5.1 Itinerary Interaction Hardening

**Date:** 2026-08-17
**Branch:** `feat/f5-1-itinerary-interaction-hardening`
**Baseline:** Backend regression suite: 515 passed, strict mypy clean (84 source files), Playwright F5.1 suite: 20/20 passed across all browser/viewport profiles.

---

## 1. Overview & Architectural Objectives

The **F5.1 Itinerary Interaction Hardening** milestone converts the F5 editable itinerary into a mobile-friendly, evidence-backed, and concurrency-hardened planning workspace.

### Core Non-Negotiables Maintained
1. **LLMs never do money math**: All financial, reward, forex, and optimization arithmetic remains deterministic Python.
2. **Zero LLMs on the edit path**: Editing and recomputation make zero LLM requests and re-run only the deterministic optimizer and estimator.
3. **No runtime web scraping**: Place search queries exclusively the locally activated region catalogs and seeded knowledge base via `SnapshotPlaceAdapter`.
4. **Provenance and trust badges preserved**: Every activity and card recommendation carries explicit verification metadata (`TrustChip`).
5. **Contract synchronization (One-PR rule)**: Backend data models, `contract/openapi.json`, `@hey-api` generated frontend types, Zod validation schemas, MSW fixtures, and React UI consumers shipped simultaneously.

---

## 2. Key Deliverables & Changes

### A. Data Model & Pure Itinerary Operations (`backend/core/trip_models.py`, `backend/core/itinerary/edits.py`)
- Added optional `lat: float | None` and `lon: float | None` fields to `ItineraryItem` to transport genuine geographical coordinates to the UI.
- Extended `ItineraryEdit` with two new pure operations:
  - `AddItem(op="add_item", poi_id=..., day_index=..., position=...)`
  - `ReplaceItem(op="replace_item", old_poi_id=..., new_poi_id=..., day_index=...)`
- Updated `apply_edit()` to reject duplicates and out-of-bounds indices, and populate POI metadata (`name`, `category`, `lat`, `lon`, `evidence`) from retrieved candidate POIs without mutating the input draft.

### B. Local Place Search Endpoint (`backend/agents/search.py`, `backend/api/main.py`)
- Created `POST /places/search` accepting `{ destination, query, category, limit }`.
- Searches local `SnapshotPlaceAdapter` catalog and curated KB entries deterministically:
  - Exact/prefix name matches prioritized over substring matches.
  - Deterministic tie-breaking by name and `poi_id`.
  - Zero external network requests or LLM invocations.

### C. Concurrency Guard & Single-Flight Recomputation (`frontend/src/app/plan/page.tsx`)
- Monotonic sequence tracking (`requestSeqRef`, `proseSeqRef`) prevents out-of-order race conditions.
- Single-flight locking: `isRecomputing` blocks overlapping requests.
- Fail-safe state management: Recompute failure preserves the previously confirmed plan and presents an explicit retry button.
- Section marked with `aria-busy={isRecomputing}` for screen-reader and a11y compliance.

### D. Accessible Timeline & Attached Card Guidance (`frontend/src/components/product/itinerary-timeline.tsx`)
- `@dnd-kit` integration with `PointerSensor`, `TouchSensor` (delay + tolerance), and `KeyboardSensor` (`sortableKeyboardCoordinates`).
- Explicit 44×44px touch targets for Move Up, Move Down, Prev Day, Next Day, Replace, and Remove actions.
- Attached card payment guidance:
  - Displays canonical card label (e.g. `Use HDFC Infinia here`).
  - Only displayed for payable items (`amount_minor > 0`).
  - Expandable `Why this card?` disclosure with bulleted reward/forex points and verification badges.
  - Zero financial math executed in React.

### E. Activity Picker Dialog (`frontend/src/components/product/activity-picker-dialog.tsx`)
- Modal search dialog powered by Radix UI with category filter chips (`all`, `attractions`, `nature`, `landmark`, `food`, `culture`, `other`).
- Displays venue name, category tag, area, trust badge, and 44px Select button.
- Supports both "Add activity" and "Replace activity" workflows.

### F. Dynamic Trip Map with Real Coordinates (`frontend/src/components/product/trip-map.tsx`)
- Eliminated fake marker coordinate offsets (`lng + i * 0.01`).
- Plots real coordinates directly from `item.lat` and `item.lon`.
- Markers labeled with day and activity indices (e.g. `D1:1`, `D1:2`).
- Renders honest fallback `"Map unavailable for these activities"` if no items carry coordinates.
- Container isolated from screen reader / tab focus via `inert` attribute.

---

## 3. Verification & Test Evidence

1. **Backend Unit & Regression Suite**:
   - `pytest` full suite: **515 passed** (including `test_itinerary_edits.py`, `test_places_search.py`, `test_contract_one_pr.py`).
   - `mypy --strict`: Clean across 84 source files.
   - `ruff check`: Clean across `agents/`, `gateway/`, `evals/`.
2. **Frontend Quality Suite**:
   - `npx tsc --noEmit`: 0 errors.
   - `eslint`: 0 errors.
   - `token-lint.mjs`: 0 violations across 12 rules.
   - `vitest`: 119 unit and contract tests passed.
   - Playwright E2E (`f5-itinerary-hardening.spec.ts`): **20/20 passed** across Chromium, Mobile (390px), Tablet, and Reduced Motion.
3. **Accessibility & Responsive Checks**:
   - Zero horizontal overflow on 390px mobile viewport (`scrollWidth <= clientWidth`).
   - Touch targets meet WCAG 2.5.5 minimum 44×44px dimensions.
   - Expandable disclosures carry `aria-expanded` and clear accessible names.
