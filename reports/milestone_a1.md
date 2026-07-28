# Milestone A1 — Accounts Persistence Layer

Date: 2026-07-28  
Branch: `feat/accounts-persistence`  
Scope: spec 17 (Persistence plan Phase A). No frontend or authentication logic was added.

## Result

A1 is complete.

Implemented the isolated `backend/accounts/` write boundary, SQLite `accounts.sqlite` schema, immutable `SavedTrip` / `TripRevision` rows, `WalletEntry` persistence with no-PAN invariant, `UserProfile` management, `UserWallet` projection logic, and privacy export/delete cascading operations.

## Gate A1

- A1 tests: 28 tests in `test_a1_store.py`, 6 tests in `test_a1_projection.py`, 5 tests in `test_a1_boundary.py`, 19 tests in `test_a1_models.py` = 58 passed.
- Full regression verification: `pytest` run collected 155 tests, with 97 pre-existing + 58 new = 155 passed.
- Strict typing: `mypy --strict core/ accounts/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py` verified 40 source files clean (35 old + 5 new).
- Linting: `ruff check` on accounts code and A1 tests passed.
- Gate A1 status: PASS.

## Implemented files

- `backend/accounts/models.py`: `User`, `UserProfile`, `WalletEntry`, `SavedTrip`, `TripRevision`, `UserExport` models, plus `FORBIDDEN_FIELD_NAMES` validator.
- `backend/accounts/db.py`: `AccountsBase`, `create_accounts_engine`, and table rows (`UserRow`, `UserProfileRow`, `WalletEntryRow`, `SavedTripRow`, `TripRevisionRow`).
- `backend/accounts/store.py`: `AccountStore` CRUD methods, bounded by exception types.
- `backend/accounts/projection.py`: `build_user_wallet` projection combining entries by maximum balance.
- `backend/evals/test_a1_*.py`: Model, store, projection, and boundary test cases.

## Boundary Invariants Proven

- No forbidden field (e.g. pan, cvv, expiry) on any model; extra=forbid rejects a smuggled PAN.
- `core/` does not import `accounts/`.
- `accounts/` does not import `agents/` or `api/`.
- Re-seeding the `tripwise.sqlite` KB leaves the accounts tables intact.
- Revisions are append-only and never mutated.
- Wallet projection is order-independent and does not double-count pooled balances.

## Not Delivered in A1

- Authentication, session credentials, headers, tokens.
- HTTP endpoints for accounts.
- Use of the `opened_on` field for suggestions (e.g., spec 18 welcome offers).

## Outstanding Debt

- Spec 17 is still owed. Building A1 before spec 17 was a documented process deviation (`SCOPE+`).
