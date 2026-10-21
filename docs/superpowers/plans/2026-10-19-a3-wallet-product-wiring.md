# A3 — Persistent Wallet Product Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing `WalletEntry` persistence and `UserWallet` projection into a complete authenticated product flow — a real `/wallet` surface where a signed-in traveler views, adds, edits, and removes card products and points balances, and sees the wallet that will be used when they start conversational planning.

**Architecture:** The storage layer and the projection already exist and are correct. A3 adds the three things missing between them and the user: (1) user-scoped, versioned, idempotent mutation methods on `AccountStore`, because the two existing mutators are keyed by entry id alone and have no concurrency control; (2) an authenticated `/account/wallet` route family that never trusts a request-body `user_id`; (3) a real frontend route with every failure state. `UserWallet` stays derived — it is never stored.

**Tech Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2 (SQLite), pytest + Hypothesis, mypy `--strict`, Ruff; Next.js 16 App Router + TypeScript strict, Vitest, Playwright, MSW, semantic `--th-*` tokens.

---

## Global Constraints

From `AGENTS.md`/`CLAUDE.md` and spec 06. Every task's requirements implicitly include these.

- **LLMs never do money math; neither does the frontend.** Render server fields. No reward/points arithmetic in React. Wallet balances are user-entered integers stored verbatim.
- **Never store a PAN, expiry, CVV/CVC, PIN, banking credential, loyalty password, or any payment-authorizing value.** `card_id` is a knowledge-base slug; `last4` is a human disambiguator only. Reject these fields explicitly rather than ignoring them.
- **Agents propose, humans approve.** No autonomous writes of financial facts. Every wallet mutation in A3 is a direct, authenticated human action.
- **Every fact carries provenance** and propagates to the UI as trust badges. Never style them away.
- **Never use `localStorage` or `sessionStorage`.** Never commit secrets.
- **`backend/core/` imports nothing from `accounts/`, `gateway/`, `ingestion/`, or `api/`.** AST-checked; do not weaken.
- **One-PR rule (spec 12 §8):** Pydantic models, routes, `contract/openapi.json`, generated client, frontend facade, MSW fixtures/handlers, components, and tests ship together. Split PRs are the drift vector.
- **Tier-F untouchable:** optimizer/transfer arithmetic, golden expected values, the projection rules below, provenance columns. `docs/specs/` is read-only.
- **Tier C decisions get a `DEVIATIONS.md` row** (`date, doc§, question, decision, rationale, affected_files`). Task 12 collects them.
- **Ambiguity protocol:** do not stop and ask. Choose the most conservative option that changes no Tier-F behavior and no golden number, log it, continue. Ask a human only for a confirmed Tier-F spec bug, credentials/paid services, legal wording, replacing seed placeholders with real data, or public deployment.
- **Out of scope — do not start:** saved-trip product wiring, CP4, FI1/crawlers, spec 18 card acquisition/welcome offers, live provider activation (Gondola/Tripadvisor/Open-Meteo/any MCP), bank linking, transaction import, statement parsing, booking, payment, transfer execution. Do not refactor unrelated code. Do not touch another worktree.

---

## Context: what already exists, verified

Read this before Task 1. It prevents rebuilding correct code and names the two real defects.

**Already correct — do not reimplement:**

`backend/accounts/projection.py::build_user_wallet(entries) -> UserWallet` already folds rows exactly as spec 17 requires: `card_ids` deduplicated through a `set` and returned **sorted**; duplicate points currencies collapse by **max, not sum** (its docstring gives the reason — pooled issuer balances would be overstated by summing, producing unfundable transfer plans); output deterministic so optimizer output stays byte-reproducible. `UserWallet` is derived at request time and is **not** a stored entity. A3 preserves this function's behavior unchanged.

`backend/accounts/models.py::WalletEntry` already validates: `last4` is exactly four digits or `None` (`check_last4`, explicitly "never a full PAN"); `statement_day` is `Field(ge=1, le=31)`; every points balance is `>= 0` (`check_balances`). **Reuse these validators — do not duplicate the rules in API models.**

`backend/api/conversation.py:536-554::_profile_for_user` already does `entries = store.wallet_entries(user.id)` then `wallet = build_user_wallet(entries)`. The server-owned planning session wallet is **already** projected from account rows. A3's job on the planning side is to *surface* this, never to introduce a second client-side wallet source.

`backend/api/auth.py` provides `current_user` (httpOnly `tp_session` cookie), `require_csrf(request)` (compares `tp_csrf` cookie against `X-CSRF-Token` via `secrets.compare_digest`, 403 on mismatch), and `get_store`. `conversation.py` is the pattern to copy: `user: Annotated[User, Depends(current_user)]` plus an explicit `require_csrf(request)` call as the first statement of every mutating handler.

`AccountStore.put_planning_session_snapshot` is the **CAS pattern to mirror**: one `update()` whose `WHERE` matches id **and** `user_id` **and** `version == expected_version`; `rowcount != 1` → `session.rollback()` and raise a typed error; never retry, never fall back to overwrite.

**Defect 1 — the two existing wallet mutators are not user-scoped.** `set_points_balances(entry_id, balances)` and `remove_wallet_entry(entry_id)` both resolve by primary key alone:

```python
row = session.get(WalletEntryRow, entry_id)   # no user_id predicate
```

Exposed naively, any authenticated user could mutate or delete another user's entry. A3 must add owner predicates. Note `remove_wallet_entry` currently silently no-ops on a missing row — keep that non-disclosing shape deliberately, and extend it so a wrong-owner delete is indistinguishable from a missing entry.

**Defect 2 — no version column.** `WalletEntryRow` is `(id, user_id, card_id, payload)`. CAS needs a version. Task 1 adds it migration-safely: existing rows must survive and default to version `1`, never be deleted or rewritten.

**There is no wallet route yet.** `grep` for `/wallet` across `backend/api/` returns nothing. `backend/api/main.py` currently only shows `app.include_router(conversation_router)` — confirm where the auth router is registered before adding a third.

---

## File Structure

| File | Task | Responsibility |
|---|---|---|
| `backend/accounts/db.py` | 1 | `WalletEntryRow.version` column + migration-safe backfill |
| `backend/accounts/models.py` | 1 | `WalletEntry.version`; `WalletMutation` audit record if chosen |
| `backend/accounts/errors.py` *(or existing module)* | 2 | `StaleWalletEntryError`, `WalletEntryNotFoundError`, `WalletIdempotencyConflictError` |
| `backend/accounts/store.py` | 1,2,3 | User-scoped versioned CAS mutators + idempotent client events |
| `backend/accounts/cards.py` *(new)* | 4 | Eligible card-product listing from the seeded KB |
| `backend/api/wallet.py` *(new)* | 5 | `/account/wallet` route family, auth + CSRF |
| `backend/api/main.py` | 5 | Register `wallet_router` |
| `contract/openapi.json` | 7 | Regenerated snapshot (byte-stable) |
| `frontend/src/lib/api/generated/**` | 7 | Regenerated client |
| `frontend/src/lib/api/index.ts` | 7 | Facade re-exports |
| `frontend/src/mocks/{handlers.ts,fixtures}` | 7 | MSW wallet routes |
| `frontend/src/app/wallet/page.tsx` *(new)* | 8 | The authenticated wallet route |
| `frontend/src/components/product/wallet/*` *(new)* | 8 | List, add form, edit form, destructive confirm |
| `frontend/src/app/layout.tsx` (header) | 8 | Replace dead "Your wallet" text with a real link |
| `frontend/src/app/plan/**` or conversational surface | 9 | Projected-wallet summary before confirmation |
| `backend/evals/test_a3_*.py` *(new)* | 1–10 | Backend coverage |
| `frontend/tests/wallet*.test.ts*` *(new)* | 8,9 | Vitest coverage |
| `frontend/e2e/a3-wallet.spec.ts` *(new)* | 11 | Browser journey |
| `reports/a3_wallet_product_wiring.md` *(new)* | 12 | Milestone report |
| `DEVIATIONS.md`, `AGENTS.md`/`CLAUDE.md` | 12 | Judgment calls + checkpoint |

---

## Setup

- [ ] **Step 0.1: Confirm the workspace** *(already done — verify, don't redo)*

```bash
cd /Users/himanshu_jain/.codex/worktrees/a3-wallet-product-wiring/TripPlanner
git rev-parse --abbrev-ref HEAD   # expect codex/a3-wallet-product-wiring
git log --oneline -1              # expect a378d0b docs: close G3.4 acceptance in the integrated tree
```

Already verified: branch created from exactly `a378d0b0b5e5728912fbbfd7ebceaff8ebb02c66`; `origin/main` is `eccb1988…` and is a full ancestor of it (33 ahead, 0 behind); source worktree tracked-clean and untouched.

- [ ] **Step 0.2: Environment and seed**

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]' 2>&1 | tail -3
cd .. && make seed
```

- [ ] **Step 0.3: Provision the ignored regional catalogs if tests require them, then prove they stayed untracked**

```bash
git status --porcelain | grep -iE "catalog|overture" || echo "no catalog artifact is tracked — correct"
```

Never commit a catalog artifact. If a catalog-dependent test fails, provision locally via the existing CLI; do **not** claim an environment exemption for a reproducible setup issue.

- [ ] **Step 0.4: Capture the real baseline — do not copy a number from any report**

```bash
cd backend
.venv/bin/pytest -q 2>&1 | tail -3
.venv/bin/pytest -q evals/test_a1_store.py evals/test_a2_auth.py 2>&1 | tail -3
.venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/ ingestion/ 2>&1 | tail -2
cd ../frontend && npx tsc --noEmit; echo "tsc: $?"; npx vitest run 2>&1 | tail -3
```

Write these numbers down. Every later comparison is against *this*, not a checkpoint figure.

---

### Task 1: Version the wallet row, migration-safely

**Files:** Modify `backend/accounts/db.py`, `backend/accounts/models.py`. Test: `backend/evals/test_a3_wallet_versioning.py` (create).

**Interfaces:**
- Consumes: nothing.
- Produces: `WalletEntryRow.version: Mapped[int]` (indexed, server default `1`) and `WalletEntry.version: int = 1`. Tasks 2 and 3 CAS on it.

- [ ] **Step 1.1: Write the failing migration-safety test**

Create `backend/evals/test_a3_wallet_versioning.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from accounts.store import AccountStore


def test_existing_rows_survive_version_addition(tmp_path) -> None:
    """A row written before versioning must still read back, at version 1."""
    db = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db)
    now = datetime(2026, 10, 19, tzinfo=UTC)
    user = store.create_user(email="a@example.com", now=now)
    entry = store.add_wallet_entry(
        user_id=user.id, card_id="hdfc-infinia", nickname="Primary", now=now
    )
    assert entry.version == 1

    # Reopen: the column must persist, not be recreated per-process.
    reopened = AccountStore.open(db)
    (loaded,) = reopened.wallet_entries(user.id)
    assert loaded.version == 1
    assert loaded.id == entry.id
```

- [ ] **Step 1.2: Run it and confirm it fails**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_versioning.py
```

Expected: FAIL — `WalletEntry` has no attribute `version`.

- [ ] **Step 1.3: Add the column and the field**

In `backend/accounts/db.py`, inside `class WalletEntryRow`:

```python
version: Mapped[int] = mapped_column(index=True, server_default="1", default=1)
```

In `backend/accounts/models.py`, inside `class WalletEntry`, beside `added_at`:

```python
version: int = Field(default=1, ge=1)
```

`server_default="1"` is what makes this migration-safe: rows created before the column existed read back as `1` rather than `NULL`, and no existing account data is deleted or rewritten. Confirm the repo's actual schema-evolution convention before relying on `create_all` alone — if `accounts/db.py` has an explicit migration hook, use it.

- [ ] **Step 1.4: Persist version in `add_wallet_entry`**

In `store.py::add_wallet_entry`, pass `version=entry.version` into the `WalletEntryRow(...)` constructor so the column and the payload agree.

- [ ] **Step 1.5: Run the test**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_versioning.py
```

Expected: PASS.

- [ ] **Step 1.6: Prove no regression**

```bash
cd backend && .venv/bin/pytest -q evals/test_a1_store.py && .venv/bin/mypy --strict accounts/
```

- [ ] **Step 1.7: Commit**

```bash
git add backend/accounts/db.py backend/accounts/models.py backend/accounts/store.py backend/evals/test_a3_wallet_versioning.py
git commit -m "feat(accounts): version wallet entries migration-safely"
```

---

### Task 2: User-scoped CAS update and non-disclosing delete

Closes Defect 1 and Defect 2 at the store layer. No API yet.

**Files:** Modify `backend/accounts/store.py`; create/extend the accounts error module. Test: `backend/evals/test_a3_wallet_scoping.py` (create).

**Interfaces:**
- Consumes: `WalletEntry.version` (Task 1).
- Produces, with these exact names:
  - `StaleWalletEntryError(Exception)`, `WalletEntryNotFoundError(Exception)`
  - `AccountStore.update_wallet_entry(*, user_id: str, entry_id: str, expected_version: int, nickname: str | None = None, last4: str | None = None, statement_day: int | None = None, opened_on: date | None = None, points_balances: dict[str, int] | None = None, now: datetime) -> WalletEntry`
  - `AccountStore.remove_wallet_entry(*, user_id: str, entry_id: str) -> bool`

  Task 5's routes call exactly these.

- [ ] **Step 2.1: Write the failing cross-user and CAS tests**

Create `backend/evals/test_a3_wallet_scoping.py`:

```python
from __future__ import annotations

import pytest
from datetime import UTC, datetime

from accounts.errors import StaleWalletEntryError, WalletEntryNotFoundError
from accounts.store import AccountStore


def _two_users(tmp_path):
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    now = datetime(2026, 10, 19, tzinfo=UTC)
    alice = store.create_user(email="alice@example.com", now=now)
    bob = store.create_user(email="bob@example.com", now=now)
    entry = store.add_wallet_entry(
        user_id=alice.id, card_id="hdfc-infinia", nickname="Alice card", now=now
    )
    return store, alice, bob, entry, now


def test_other_user_cannot_update(tmp_path) -> None:
    store, _alice, bob, entry, now = _two_users(tmp_path)
    with pytest.raises(WalletEntryNotFoundError):
        store.update_wallet_entry(
            user_id=bob.id, entry_id=entry.id, expected_version=1,
            nickname="stolen", now=now,
        )


def test_other_user_delete_is_indistinguishable_from_missing(tmp_path) -> None:
    store, alice, bob, entry, _now = _two_users(tmp_path)
    assert store.remove_wallet_entry(user_id=bob.id, entry_id=entry.id) is False
    assert store.remove_wallet_entry(user_id=bob.id, entry_id="no-such-id") is False
    # Alice's row is untouched.
    assert [e.id for e in store.wallet_entries(alice.id)] == [entry.id]


def test_stale_version_loses(tmp_path) -> None:
    store, alice, _bob, entry, now = _two_users(tmp_path)
    first = store.update_wallet_entry(
        user_id=alice.id, entry_id=entry.id, expected_version=1,
        nickname="v2", now=now,
    )
    assert first.version == 2
    with pytest.raises(StaleWalletEntryError):
        store.update_wallet_entry(
            user_id=alice.id, entry_id=entry.id, expected_version=1,
            nickname="also v2", now=now,
        )
```

- [ ] **Step 2.2: Run and confirm failure**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_scoping.py
```

Expected: FAIL on the missing `accounts.errors` import.

- [ ] **Step 2.3: Add the typed errors**

Create `backend/accounts/errors.py` (or extend the module that already holds `StalePlanningSessionError` — check first and co-locate rather than splitting):

```python
class WalletEntryNotFoundError(Exception):
    """No wallet entry with that id is owned by this user.

    Deliberately indistinguishable from "exists but owned by someone else" —
    the API must not disclose another user's entry ids.
    """


class StaleWalletEntryError(Exception):
    """The entry moved past the caller's expected version. Re-read and resubmit."""
```

- [ ] **Step 2.4: Implement the scoped CAS update**

Mirror `put_planning_session_snapshot` exactly: read the row under an owner predicate, apply only the permitted fields, re-validate by JSON round-trip (`model_copy` skips validators — the existing `set_points_balances` comment documents this), then issue one `update()` whose `WHERE` carries id, `user_id`, **and** `version == expected_version`. On `rowcount != 1`, `rollback()` and raise. Distinguish the two failures by re-reading under the owner predicate: absent → `WalletEntryNotFoundError`; present at another version → `StaleWalletEntryError`. Bump `version` by exactly 1 and set it in both the column and the payload.

Only these fields are writable: `nickname`, `last4`, `statement_day`, `opened_on`, `points_balances`. `id`, `user_id`, `card_id`, `added_at` are immutable — a caller asking to change them is a bug, not a merge.

- [ ] **Step 2.5: Make `remove_wallet_entry` owner-scoped and non-disclosing**

Change the signature to keyword-only `user_id` + `entry_id`, delete with both predicates, and return `rowcount == 1`. Returning `False` for both "missing" and "not yours" is the non-disclosure property the test pins.

**This is a breaking signature change.** Grep every caller and update it in the same commit:

```bash
grep -rn "remove_wallet_entry\|set_points_balances" backend/ --include "*.py"
```

Keep `set_points_balances` working (other code and tests may call it) by delegating to `update_wallet_entry`, or update its callers — decide, and log the choice for Task 12.

- [ ] **Step 2.6: Run the tests**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_scoping.py evals/test_a1_store.py
```

Expected: PASS.

- [ ] **Step 2.7: Commit**

```bash
git add backend/accounts/ backend/evals/test_a3_wallet_scoping.py
git commit -m "fix(accounts): scope wallet mutations to the owner with versioned CAS"
```

---

### Task 3: Idempotent wallet mutations

**Files:** Modify `backend/accounts/store.py` (+ `db.py` if a client-event table is needed). Test: `backend/evals/test_a3_wallet_idempotency.py` (create).

**Interfaces:**
- Consumes: Task 2's mutators.
- Produces: an optional `client_event_id: str | None` parameter on the create/update/delete store methods, plus `WalletIdempotencyConflictError`. Identical replay returns the original result; the same `client_event_id` reused with a *different* payload raises.

- [ ] **Step 3.1: Inspect the existing idempotency convention first**

```bash
grep -rn "client_event_id" backend/ --include "*.py" | head -20
```

CP1 already established idempotency on `client_event_id` for planning sessions. **Reuse that mechanism and its storage shape.** Only introduce a new table if the existing one cannot be reused, and log that decision.

- [ ] **Step 3.2: Write the failing test**

```python
def test_identical_replay_returns_original(tmp_path) -> None:
    store, alice, _bob, _entry, now = _two_users(tmp_path)
    first = store.add_wallet_entry(
        user_id=alice.id, card_id="hdfc-infinia", nickname="Dup", now=now,
        client_event_id="evt-1",
    )
    again = store.add_wallet_entry(
        user_id=alice.id, card_id="hdfc-infinia", nickname="Dup", now=now,
        client_event_id="evt-1",
    )
    assert again.id == first.id
    assert len(store.wallet_entries(alice.id)) == 2  # the pre-existing one + one new


def test_conflicting_reuse_is_typed(tmp_path) -> None:
    store, alice, _bob, _entry, now = _two_users(tmp_path)
    store.add_wallet_entry(
        user_id=alice.id, card_id="hdfc-infinia", nickname="One", now=now,
        client_event_id="evt-2",
    )
    with pytest.raises(WalletIdempotencyConflictError):
        store.add_wallet_entry(
            user_id=alice.id, card_id="axis-magnus", nickname="Two", now=now,
            client_event_id="evt-2",
        )
```

- [ ] **Step 3.3: Run it, confirm failure, implement, re-run**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_idempotency.py
```

Scope the event key by `(user_id, client_event_id)` so one user's event id can never collide with another's.

- [ ] **Step 3.4: Commit**

```bash
git add backend/accounts/ backend/evals/test_a3_wallet_idempotency.py
git commit -m "feat(accounts): make wallet mutations idempotent on client_event_id"
```

---

### Task 4: Eligible card products from the seeded knowledge base

**Files:** Create `backend/accounts/cards.py`, `backend/evals/test_a3_card_products.py`.

**Interfaces:**
- Consumes: the existing seeded `Card` knowledge base (`core.models.Card`; find the loader with `grep -rn "def cards" backend/core/`).
- Produces: `list_card_products() -> list[CardProductOut]` with fields `card_id`, `display_name`, `issuer`, `points_currency_id | None`, and `is_eligible: bool`; and `assert_known_card_id(card_id: str) -> None` raising `UnknownCardProductError`. Task 5 uses both.

- [ ] **Step 4.1: Write the failing test**

```python
def test_unknown_slug_is_rejected() -> None:
    with pytest.raises(UnknownCardProductError):
        assert_known_card_id("not-a-real-card")


def test_listing_is_deterministic_and_nonempty() -> None:
    products = list_card_products()
    assert products, "the seeded KB must expose at least one card product"
    assert [p.card_id for p in products] == sorted(p.card_id for p in products)
```

- [ ] **Step 4.2: Run, implement reading from the KB (never a hardcoded list), re-run**

The list must come from the same seeded knowledge base the optimizer resolves earn rules from. A hardcoded slug list would drift from the optimizer and silently accept cards it cannot cost.

- [ ] **Step 4.3: Commit**

```bash
git add backend/accounts/cards.py backend/evals/test_a3_card_products.py
git commit -m "feat(accounts): expose eligible card products from the seeded KB"
```

---

### Task 5: The authenticated `/account/wallet` API

**Route family decision (document in Task 12):** `/account/wallet` — `GET /account/wallet` (entries), `GET /account/wallet/projection` (derived `UserWallet`), `GET /account/card-products`, `POST /account/wallet`, `PATCH /account/wallet/{entry_id}`, `DELETE /account/wallet/{entry_id}`. Kept separate from the read-only deterministic kernel routes (`/plan*`, `/places/search`).

**Files:** Create `backend/api/wallet.py`, `backend/evals/test_a3_wallet_api.py`. Modify `backend/api/main.py`.

**Interfaces:**
- Consumes: Tasks 2–4; `current_user`, `require_csrf`, `get_store`, `now_utc` from `api.auth`.
- Produces: `wallet_router`. Request models forbid extra fields; response models never include session/credential values.

- [ ] **Step 5.1: Write the failing negative-path tests first**

Cover, each as its own test: unauthenticated request → 401; mutation without `X-CSRF-Token` → 403; cross-user `PATCH`/`DELETE`/`GET` → 404 **with a body identical to a genuinely-missing entry**; `user_id` in the request body → rejected (and ownership unchanged); unknown `card_id` → 422/400; `pan`/`card_number`/`cvv`/`cvc`/`expiry`/`pin` fields → rejected by `extra="forbid"`; malformed `last4` (`"12"`, `"abcd"`, a 16-digit PAN) → 422; `statement_day` `0` and `32` → 422; malformed `opened_on` → 422; negative balance → 422; stale `expected_version` → **409** with a typed code; replayed `client_event_id` → original result; conflicting reuse → typed 409; and no raw `sqlite3.OperationalError` ever crossing the boundary.

- [ ] **Step 5.2: Run them and confirm they fail**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_api.py
```

- [ ] **Step 5.3: Implement the router**

Rules, non-negotiable:

```python
# Every mutating handler starts with these two lines, in this order.
require_csrf(request)
# ...then operate strictly on user.id — never a body-supplied user id.
```

All request models set `model_config = ConfigDict(extra="forbid")`. Derive nothing about ownership from the payload. Map errors centrally: `WalletEntryNotFoundError` → 404, `StaleWalletEntryError` → 409 (`code="wallet_version_conflict"`), `WalletIdempotencyConflictError` → 409 (`code="wallet_event_conflict"`), `UnknownCardProductError` → 422. Catch `sqlalchemy.exc.OperationalError` at the boundary and return a typed 503/409 rather than leaking a driver exception. `GET /account/wallet/projection` returns `build_user_wallet(store.wallet_entries(user.id))` — it must not store anything.

- [ ] **Step 5.4: Register the router**

In `backend/api/main.py`, beside the existing `include_router` calls:

```python
app.include_router(wallet_router)
```

- [ ] **Step 5.5: Run the suite, then typecheck and lint**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_api.py \
  && .venv/bin/mypy --strict api/ accounts/ \
  && .venv/bin/ruff check api/ accounts/
```

- [ ] **Step 5.6: Commit**

```bash
git add backend/api/ backend/evals/test_a3_wallet_api.py
git commit -m "feat(api): add authenticated user-scoped wallet routes"
```

---

### Task 6: Projection and planning-session guarantees

**Files:** Create `backend/evals/test_a3_wallet_projection.py`.

- [ ] **Step 6.1: Write the projection-rule tests**

Pin the spec-17 rules against the *API surface*, not just the pure function: duplicate points currencies across two entries project by **max, not sum**; two entries for the same `card_id` yield **one** `card_ids` member so the optimizer never treats one product as two; ordering is deterministic across a SQLite reopen; and an **empty persisted wallet reaches planning as an empty `UserWallet` and produces truthful cash-only behavior** — never a demo-wallet substitution for an authenticated user.

```python
def test_duplicate_currencies_project_by_max_not_sum(...) -> None: ...
def test_two_entries_one_product_do_not_duplicate_eligibility(...) -> None: ...
def test_authenticated_empty_wallet_stays_empty_and_is_cash_only(...) -> None: ...
```

The last one is the behavioral trap: the legacy `/plan` fixture/demo path may fall back to a demo wallet. For an authenticated user whose persisted wallet is intentionally empty, that fallback must **not** apply.

- [ ] **Step 6.2: Run, fix any gap found, re-run, commit**

```bash
cd backend && .venv/bin/pytest -q evals/test_a3_wallet_projection.py
git add backend/evals/test_a3_wallet_projection.py backend/
git commit -m "test(accounts): pin wallet projection and cash-only guarantees"
```

---

### Task 7: Contract synchronization — one PR

**Files:** `contract/openapi.json`, `frontend/src/lib/api/generated/**`, `frontend/src/lib/api/index.ts`, `frontend/src/mocks/handlers.ts` (+ fixtures).

- [ ] **Step 7.1: Find and use the repo's own regeneration commands — do not hand-edit generated files**

```bash
grep -nE "openapi|codegen|generate" Makefile frontend/package.json | head -20
```

- [ ] **Step 7.2: Regenerate, then prove byte stability by regenerating again**

```bash
<regen command>
shasum -a 256 contract/openapi.json > /tmp/a3_openapi.1
<regen command>
shasum -a 256 contract/openapi.json > /tmp/a3_openapi.2
diff /tmp/a3_openapi.1 /tmp/a3_openapi.2 && echo "OPENAPI BYTE-STABLE"
```

Non-stable output (timestamps, set-ordering) must be fixed, not tolerated — it is a drift vector.

- [ ] **Step 7.3: Re-export the new types through the facade**

`frontend/src/lib/api/index.ts` is the hand-maintained facade; generated code lives under `./generated/`. Add the wallet types/operations there so components import `@/lib/api`, never `@/lib/api/generated/...` directly.

- [ ] **Step 7.4: Add MSW handlers for all six routes, including failure fixtures**

Fixtures must cover success, empty, 401, 403 (CSRF), 404, 409 (both conflict codes), and 422 — Task 8's states are untestable without them.

- [ ] **Step 7.5: Commit — backend + contract + client + mocks together**

```bash
git add contract/openapi.json frontend/src/lib/api frontend/src/mocks
git commit -m "feat(contract): synchronize wallet API contract, client, and mocks"
```

---

### Task 8: The `/wallet` route

**Files:** Create `frontend/src/app/wallet/page.tsx` and `frontend/src/components/product/wallet/*`; modify the header in `frontend/src/app/layout.tsx`; create `frontend/tests/wallet.test.tsx`.

- [ ] **Step 8.1: Replace the dead "Your wallet" header text with a real accessible link**

```bash
grep -rn "Your wallet" frontend/src | head
```

- [ ] **Step 8.2: Build the route with every state**

Required: signed-out (clear sign-in action), loading, empty, populated, validation-error, conflict, server-error, retry. Plus: accessible card-product selection fed by `GET /account/card-products` (never a client-side hardcoded list), an add form, an edit form for the five safe fields, and a destructive-action confirmation before removal.

Copy requirement: state plainly that TripWise stores card **products** and optional last4 only, never full card details.

Discipline: semantic `--th-*` tokens only; keyboard reachable with visible focus; semantic labels and error association (`aria-describedby`); WCAG-AA contrast; responsive desktop/mobile; **no `localStorage`/`sessionStorage`**; **no financial arithmetic in React** — render server values verbatim.

- [ ] **Step 8.3: On a 409, re-read and tell the truth**

A version conflict must surface as "this wallet changed in another tab — reload to see the current version", never a silent overwrite and never a blind retry.

- [ ] **Step 8.4: Verify**

```bash
cd frontend && npx tsc --noEmit && npx vitest run tests/wallet.test.tsx && npx eslint . && node scripts/token-lint.mjs
```

- [ ] **Step 8.5: Commit**

```bash
git add frontend/src/app/wallet frontend/src/components/product/wallet frontend/src/app/layout.tsx frontend/tests/wallet.test.tsx
git commit -m "feat(frontend): add authenticated wallet route"
```

---

### Task 9: Show the planning wallet before confirmation

**Files:** Modify the conversational planning surface; create `frontend/tests/planning-wallet-summary.test.tsx`.

- [ ] **Step 9.1: Surface the server-owned projection — do not build a second source**

The backend already projects it (`conversation.py:536-554`). Render `GET /account/wallet/projection` or the session's own wallet field. **Do not** assemble a wallet client-side from the `/wallet` list.

- [ ] **Step 9.2: Make it visible before final confirmation, and truthful when empty**

An authenticated user with an empty persisted wallet sees an explicit empty/cash-only summary — never a demo wallet.

- [ ] **Step 9.3: Preserve the legacy `/plan` fixture path**

```bash
git diff --stat a378d0b..HEAD -- frontend/src/app/plan/
```

Change it only if strictly required, and say so in the report.

- [ ] **Step 9.4: Verify and commit**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
git add frontend/src frontend/tests
git commit -m "feat(frontend): show the projected planning wallet before confirmation"
```

---

### Task 10: Privacy, concurrency, and boundary coverage

**Files:** Create `backend/evals/test_a3_wallet_privacy.py`, `backend/evals/test_a3_wallet_concurrency.py`.

- [ ] **Step 10.1: Privacy export/delete**

`export_user` includes the appropriate wallet state/history; `delete_user` removes wallet state **and** any audit/event history. If you added durable wallet audit events, both must cover them.

- [ ] **Step 10.2: A genuine two-connection concurrent update**

Not two sequential calls — two real SQLite connections racing the same `expected_version`. Exactly one wins; the loser receives `StaleWalletEntryError` (409 at the API), **never** `sqlite3.OperationalError`. Mirror the technique the G3.1 budget-ledger lock-contention test already uses:

```bash
grep -rln "OperationalError\|BEGIN IMMEDIATE\|two.connection" backend/evals/ | head
```

- [ ] **Step 10.3: Architecture boundaries**

```bash
cd backend && .venv/bin/pytest -q evals/ -k "boundary or import_boundary or architecture"
grep -rn "localStorage\|sessionStorage" ../frontend/src && echo "VIOLATION" || echo "clean"
```

`backend/core/` must still import nothing from `accounts/`, `gateway/`, `ingestion/`, or `api/`.

- [ ] **Step 10.4: Commit**

```bash
git add backend/evals/
git commit -m "test(accounts): cover wallet privacy, concurrency, and boundaries"
```

---

### Task 11: The browser journey

**Files:** Create `frontend/e2e/a3-wallet.spec.ts`.

- [ ] **Step 11.1: Write the nine-step journey as specified**

Sign in → open `/wallet` → add a known card product with a points balance → edit it → start/resume conversational planning → verify the wallet summary is present → confirm the server-owned session contains the projected wallet → remove the entry with confirmation → verify the authenticated empty-wallet state is **not** replaced by a demo wallet.

- [ ] **Step 11.2: Run across the configured projects**

```bash
cd frontend && npx playwright test a3-wallet.spec.ts --config=e2e/playwright.config.ts --reporter=list
```

Run the configured desktop, mobile, tablet, and reduced-motion projects. Check `e2e/playwright.config.ts` for their exact names rather than guessing.

- [ ] **Step 11.3: Commit**

```bash
git add frontend/e2e/a3-wallet.spec.ts
git commit -m "test(frontend): cover the end-to-end wallet journey"
```

---

### Task 12: Report, deviations, and the exact-tree gate

- [ ] **Step 12.1: Write `reports/a3_wallet_product_wiring.md` with status `ACCEPTANCE PENDING`**

Keep it pending until Step 12.4 actually passes. Do not write "complete" before then — this project has shipped that error twice (the Gondola milestone and CP1 task 8), both caught in review.

- [ ] **Step 12.2: Record the judgment calls in `DEVIATIONS.md`**

At minimum: the `/account/wallet` route-family choice; the `set_points_balances` compatibility decision from Step 2.5; whether durable audit events were added or versioned mutation history was judged sufficient (and why, including the retention argument); and the migration approach for existing rows.

- [ ] **Step 12.3: Keep `AGENTS.md` and `CLAUDE.md` byte-identical if either changes**

```bash
cp CLAUDE.md AGENTS.md && cmp CLAUDE.md AGENTS.md && echo IDENTICAL
```

- [ ] **Step 12.4: Run the full verification set on the exact committed clean tree**

```bash
git status --porcelain   # must be empty
make seed
cd backend && .venv/bin/pytest -q 2>&1 | tail -3
.venv/bin/mypy --strict core/ accounts/ planning/ agents/ api/ gateway/ ingestion/ 2>&1 | tail -2
.venv/bin/ruff check accounts/ planning/ agents/ gateway/ evals/ api/ ingestion/
cd ../frontend && npx tsc --noEmit && npx vitest run 2>&1 | tail -3 && npx eslint . && node scripts/token-lint.mjs && npm run build 2>&1 | tail -5
cd .. && make gate
```

- [ ] **Step 12.5: Obtain an independent whole-branch review**

Use `superpowers:requesting-code-review` against the full `a378d0b..HEAD` diff. Ask the reviewer specifically to check: that no endpoint trusts a body-supplied `user_id`; that cross-user 404s are genuinely indistinguishable from missing-entry 404s; that the max-not-sum projection rule is still intact; and that the report's numbers match the Step 12.4 output rather than restating an older figure.

- [ ] **Step 12.6: Fix every verified Critical or Important finding with regression coverage, then re-run Step 12.4**

- [ ] **Step 12.7: Only now mark the report complete**

Record: source/base SHA (`a378d0b0b5e5728912fbbfd7ebceaff8ebb02c66`), final branch SHA, full backend count, frontend Vitest count, browser results, mypy file count, Ruff result, OpenAPI byte-stability result, full `make gate` result, review findings and dispositions, and remaining limitations.

- [ ] **Step 12.8: Commit, and do not push or merge**

```bash
git add reports/a3_wallet_product_wiring.md DEVIATIONS.md CLAUDE.md AGENTS.md
git commit -m "docs: record A3 wallet product wiring milestone"
```

Nothing is pushed or merged unless explicitly requested. Do not start A4, CP4, FI1, spec 18, or any live-provider activation after A3.
