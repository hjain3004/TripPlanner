# Implementation Plan: F5.1 Itinerary Interaction Hardening

Hardening the F5 editable itinerary into a reliable, touch-accessible, evidence-backed planning workspace without altering the deterministic core architecture or invoking LLMs for financial or schedule math.

---

## The Architectural Invariants

1. **Deterministic Execution:** No LLM is touched during search, editing, recomputation, or payment guidance.
2. **Single-Flight Concurrency:** Recompute requests are sequenced with monotonic request IDs and active-flight locking. Double clicks or out-of-order responses cannot corrupt state.
3. **Pure Provenance & Real Coordinates:** All coordinates and evidence badges originate from catalog/KB records. No hardcoded city pairs or visual offset fake points.
4. **Contract Synchronization:** Schema modifications (`ItineraryItem` coordinates, `AddItem`, `ReplaceItem`, `PlaceSearchResult`, `PlaceSearchRequest`) are committed atomically with `contract/openapi.json`, generated SDK/types, MSW handlers, and UI consumers.
5. **Accessibility & Responsive Parity:** Every drag interaction is fully mirrored by keyboard actions with >= 44x44px touch targets and strict aXe compliance.

---

## Detailed Task Breakdown

### Task 1: Backend Data Model Extensions (Coordinates & Add/Replace Edit Operations)
- Add `lat: float | None` and `lon: float | None` to `ItineraryItem` in `backend/core/trip_models.py`.
- Add `AddItem` and `ReplaceItem` to `backend/core/trip_models.py` discriminated union `ItineraryEdit`.
- Update `backend/core/itinerary/edits.py`:
  - `apply_edit(itinerary, edit, candidate_pool)` to handle `add_item` and `replace_item` with catalog validation, bounds checking, and duplicate prevention.
- Update `backend/agents/retrieval.py` and `backend/agents/recompute.py` to populate coordinates on `ItineraryItem`.
- Add unit tests in `backend/evals/test_itinerary_edits.py`.
- **Commit:** `feat(core): itinerary item coordinates and add/replace edit operations`

---

### Task 2: Backend Places Search Endpoint
- Create `backend/api/places.py` or endpoint in `backend/api/main.py`:
  - `POST /places/search` or `GET /places/search` accepting `destination: str`, `query: str = ""`, `category: str | None = None`, `limit: int = 10`.
  - Uses `gateway.catalog.regions.get_region` and `gateway.places.adapters.snapshot.SnapshotPlaceAdapter` or KB POIs.
  - Returns `PlaceSearchResult` objects with ID, name, category, area, lat, lon, price_minor, currency, and `POIEvidence`.
  - Zero external network calls, zero LLM calls.
- Add unit tests in `backend/evals/test_places_search.py`.
- **Commit:** `feat(api): bounded deterministic place catalog search endpoint`

---

### Task 3: Contract, OpenAPI, Generated Types, and MSW Fixtures Synchronization
- Export OpenAPI schema with updated `ItineraryItem`, `AddItem`, `ReplaceItem`, and `/places/search` endpoint.
- Regenerate frontend SDK with `npm run gen:api` in `frontend/`.
- Restore hand-written `client-config.ts` and update `schemas.ts` and `index.ts`.
- Update `frontend/src/mocks/handlers.ts` to mock `/places/search`, handle `add_item` and `replace_item` in `/plan/recompute`, and supply coordinate fields in fixture items.
- Verify `backend/evals/test_contract_one_pr.py` passes.
- **Commit:** `feat(contract): place search and add/replace itinerary edit schema`

---

### Task 4: Frontend Concurrency & Single-Flight Editing State
- In `frontend/src/app/plan/page.tsx`:
  - Add single-flight guard `isRecomputing` and sequence tracking `requestSeqRef`.
  - Disable editing controls and prose refresh while recompute is active.
  - Set `aria-busy={isRecomputing}` on the itinerary region.
  - Handle recompute failure gracefully: restore previous state, display retryable error banner.
  - Handle prose refresh failure visibly with dismissible alert.
  - Do not use optimistic financial figures; only render when backend responds.
- Add Vitest tests in `frontend/tests/concurrency.test.ts`.
- **Commit:** `feat(ui): single-flight itinerary edit concurrency and visible error recovery`

---

### Task 5: Touch-Accessible @dnd-kit Timeline & 44px Controls
- Refactor `frontend/src/components/product/itinerary-timeline.tsx`:
  - Implement `@dnd-kit/core` and `@dnd-kit/sortable` with `PointerSensor` (distance: 5), `TouchSensor` (delay: 250, tolerance: 5), `KeyboardSensor`.
  - `DragOverlay` styled with semantic theme tokens.
  - Full keyboard action buttons for each item: Move Up, Move Down, Move to Prev Day, Move to Next Day, Replace, Remove.
  - Ensure all button targets are at least 44×44px with visible focus indicators.
  - Ensure mobile layout at 390px has zero horizontal overflow.
- **Commit:** `feat(ui): touch-accessible dnd-kit timeline with 44px action buttons`

---

### Task 6: Real Geography & Dynamic Trip Map
- Refactor `frontend/src/components/product/trip-map.tsx`:
  - Remove Delhi/Singapore hardcoding and synthetic offset math.
  - Plot markers using exact `item.lat` and `item.lon` from report data.
  - Derive map center and zoom from plotted items or destination region centroid.
  - Synchronize marker numbers and day groupings with the timeline items.
  - Show honest fallback `"Map unavailable for these activities"` if no items have valid coordinates.
  - Retain dynamic code-splitting and accessibility `inert` attribute.
- **Commit:** `feat(ui): report-derived geographic map with coordinate provenance`

---

### Task 7: Attached Traveler Payment Guidance & Expandable Explanation
- Refactor payment badge in `frontend/src/components/product/itinerary-timeline.tsx`:
  - Only show guidance on items with positive payable amount (`line.amount_minor > 0`).
  - Render canonical label (`"Use HDFC Infinia here"`).
  - Add expandable disclosure button ("Why this card?") with keyboard/touch support showing explanation points, forex/reward rate, and verification state.
  - Retain raw `card_id` as secondary metadata.
  - Zero financial math in React.
- **Commit:** `feat(ui): attached card payment guidance with accessible reason disclosure`

---

### Task 8: Add / Replace Activity Dialog
- Create `frontend/src/components/product/activity-picker-dialog.tsx`:
  - Searchable modal dialog using Radix Dialog / shadcn.
  - Search input with debounce querying `/places/search`.
  - Category filter pills based on returned categories.
  - Result list showing place name, category, area, price/currency, and `TrustChip` evidence.
  - Add to Day and Replace Item actions invoking `onEdit({ op: 'add_item', ... })` or `onEdit({ op: 'replace_item', ... })`.
  - Focus trap, keyboard escape, accessible labels.
- Wire into `itinerary-timeline.tsx` and `plan/page.tsx`.
- **Commit:** `feat(ui): accessible place search and add/replace activity dialog`

---

### Task 9: Playwright E2E Interaction Test Suite
- Create `frontend/e2e/f5-itinerary-hardening.spec.ts`:
  - Test move within day, move across days, remove, add, replace.
  - Test keyboard-only reordering and editing.
  - Test recompute loading state, disabled buttons, `aria-busy`.
  - Test double-edit prevention and out-of-order response discard.
  - Test recompute error and retry button.
  - Test stale prose marker and prose refresh.
  - Test payment guidance on payable vs free POIs.
  - Test map marker synchronization and missing coordinate fallback.
  - Test 44px touch targets and no 390px horizontal overflow.
  - Test aXe accessibility on edited state.
- **Commit:** `test(e2e): complete F5.1 browser interaction and accessibility coverage`

---

### Task 10: Verification, Milestone Report, and Code Review
- Run full gates: `make gate`, `make gate-f4`, `npx vitest run`, `npx playwright test`.
- Write `reports/f5_1_itinerary_interaction_hardening.md`.
- Update `DEVIATIONS.md`, `CLAUDE.md`, `AGENTS.md`.
- **Commit:** `docs(reports): F5.1 itinerary interaction hardening milestone report`
