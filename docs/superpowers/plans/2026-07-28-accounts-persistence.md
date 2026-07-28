# Accounts Persistence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `backend/accounts/` — the persistence layer for user identity, card-product holdings, and saved trips — as a write boundary that `backend/core/` never imports.

**Architecture:** A new top-level package `backend/accounts/` holding (a) Pydantic models for `User`, `UserProfile`, `WalletEntry`, `SavedTrip`, `TripRevision`, (b) a SQLAlchemy schema in its **own** database file with its **own** `DeclarativeBase`, and (c) an `AccountStore` class that is the only code in the repo permitted to write user data. `backend/core/` keeps its read-only posture and gains no new imports. The request-time `UserWallet` the kernel already consumes is produced by a pure projection function over stored `WalletEntry` rows — it is not duplicated as a stored model.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2.0 (declarative, `Mapped`/`mapped_column`), SQLite, pytest, mypy `--strict`, ruff.

## Global Constraints

Every task's requirements implicitly include this section.

- **Never store PAN, expiry, CVV, bank credentials, or loyalty-account passwords.** This is a schema invariant enforced in code and by test, not a convention.
- **Money is never a float.** Minor units and points balances are `int`. Basis points are `int`. Micro-major per-point values are `int`. (spec 01, Tier F)
- **`backend/core/` must never import `backend/accounts/`.** The dependency runs one way only: `accounts` may read `core.models`; `core` may not name `accounts`. Enforced by a test.
- **`backend/core/` stays read-only.** No new write paths are added to `core/db.py`. `core.db.seed_database()` calls `Base.metadata.drop_all(engine)`; accounts data must be physically unreachable from that call.
- **Never use localStorage/sessionStorage** anywhere (CLAUDE.md). Nothing in this plan touches the frontend, but the constraint binds the later auth plan.
- **Deterministic ordering.** Every collection accessor returns rows in a stable, documented order, matching `core/db.py`'s `KnowledgeBase` contract.
- **Time and identifiers are injected, never ambient.** Every store method that records a timestamp takes an explicit `now: datetime`; every method that mints an id accepts an optional caller-supplied id. This is how the existing pipeline injects `booking_date` (`backend/api/main.py:39`) and is what makes these tests deterministic.
- **Style match:** `from __future__ import annotations` at the top of every module; a module docstring explaining what it serves; `field_validator` for normalization; section-divider comments in the `# ---- #` style used by `backend/core/models.py`.
- **Python invocation:** all commands below use `cd backend && .venv/bin/python -m …`, matching `reports/milestone_3.md`. If the venv is not at that path, substitute your interpreter consistently.

## Context an implementer needs

**This plan builds ahead of its spec.** `docs/specs/17_accounts_and_persistence.md` does not exist yet. Every backend milestone so far (M1, M1b, M2, M3) was specced first. That inversion is a deliberate, human-approved trade for momentum and **must be logged in `DEVIATIONS.md`** (Task 10). If spec 17 later contradicts something here, spec 17 wins and this code is revised.

**Existing shapes you will interact with** (read these files before starting):

- `backend/core/models.py:278` — `UserWallet(card_ids: list[str], points_balances: dict[str, int])`. This is the kernel's request-time input. **Do not duplicate it.** You will build it from stored rows.
- `backend/core/db.py:161` — `KnowledgeBase`, the read facade. Note its storage pattern: *one table per model, spec index columns broken out as real columns, plus a `payload` TEXT column holding canonical `model_dump_json()`.* `AccountStore` follows the same pattern.
- `backend/core/db.py:418` — `seed_database()` opens with `Base.metadata.drop_all(engine)`. This is why accounts get a separate `DeclarativeBase` and a separate file.
- `backend/agents/models.py:29` — `TripSpec` (the planner's typed trip input) and `backend/agents/models.py:149` — `FinalReport` (the pipeline's output). Accounts stores **JSON snapshots** of these, not the typed objects — see Task 3's rationale.
- `backend/evals/test_m2_api.py` — the test conventions to match: plain module-level `def test_x() -> None:` functions, no test classes, `tmp_path` fixtures for databases, private `_helper()` builders at the top of the file.

**Where tests live:** all backend tests live in `backend/evals/`, because `pyproject.toml` sets `testpaths = ["evals"]`. That directory name is about pytest collection, not semantics. New tests go in `backend/evals/test_a1_*.py`. "A1" is the milestone tag for this work.

## File Structure

| File | Responsibility |
|---|---|
| `backend/accounts/__init__.py` | Package marker. Empty. |
| `backend/accounts/models.py` | Pydantic models for all five entities + the forbidden-field invariant. No I/O. |
| `backend/accounts/db.py` | SQLAlchemy `AccountsBase`, the five row classes, engine/DB-path helpers. No business logic. |
| `backend/accounts/store.py` | `AccountStore` — the write boundary. The only place user data is written. |
| `backend/accounts/projection.py` | Pure functions turning stored rows into kernel inputs (`build_user_wallet`). |
| `backend/evals/test_a1_models.py` | Model validation + the forbidden-field invariant. |
| `backend/evals/test_a1_store.py` | Users, profiles, wallet CRUD, saved trips, revisions, export/delete. |
| `backend/evals/test_a1_projection.py` | `UserWallet` projection behaviour. |
| `backend/evals/test_a1_boundary.py` | `core/` never imports `accounts/`; accounts DB survives re-seeding. |
| `backend/pyproject.toml` | Add `accounts` to `[tool.setuptools] packages`. |
| `DEVIATIONS.md` | New `## A1` section with the judgment calls this plan makes. |
| `reports/milestone_a1.md` | Gate A1 record. |

## Out of scope (explicitly deferred to the next plan)

Authentication, password/credential storage, sessions, cookies, JWT, and every HTTP endpoint. `User` deliberately has **no** `password_hash` field; the auth plan adds it as an additive column. Do not add auth in this plan even if it feels natural. Also deferred: the new-card / welcome-offer recommendation feature (see Task 10's SCOPE+ row) — this plan persists `opened_on` so that feature is buildable later, and does nothing else about it.

---

### Task 1: Accounts package scaffold, forbidden-field invariant, and identity models

**Files:**
- Create: `backend/accounts/__init__.py`
- Create: `backend/accounts/models.py`
- Test: `backend/evals/test_a1_models.py`
- Modify: `backend/pyproject.toml` (the `[tool.setuptools] packages` list, currently `packages = ["core", "core.optimizer", "core.transfer", "agents", "api", "evals"]`)

**Interfaces:**
- Consumes: nothing.
- Produces: `ACCOUNTS_SCHEMA_VERSION: str`, `FORBIDDEN_FIELD_NAMES: frozenset[str]`, `AccountModel(BaseModel)`, `User`, `UserProfile`.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a1_models.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from accounts.models import (
    FORBIDDEN_FIELD_NAMES,
    User,
    UserProfile,
)

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def test_user_normalizes_email_to_lowercase() -> None:
    user = User(id="u1", email="  Himanshu.Jain@SJSU.edu ", created_at=NOW)

    assert user.email == "himanshu.jain@sjsu.edu"
    assert user.status == "active"


def test_user_rejects_an_email_without_a_domain() -> None:
    with pytest.raises(ValidationError):
        User(id="u1", email="himanshu", created_at=NOW)


def test_user_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        User(id="u1", email="a@b.com", created_at=NOW, password="hunter2")


def test_no_account_model_declares_a_forbidden_field() -> None:
    for model in (User, UserProfile):
        for field_name in model.model_fields:
            assert field_name.lower() not in FORBIDDEN_FIELD_NAMES, (
                f"{model.__name__}.{field_name} is a payment-instrument secret "
                "and must never be stored"
            )


def test_profile_normalizes_currency_and_origin_city() -> None:
    profile = UserProfile(
        user_id="u1",
        display_name="Himanshu",
        home_country="IN",
        home_currency="inr",
        origin_city="del",
        updated_at=NOW,
    )

    assert profile.home_currency == "INR"
    assert profile.origin_city == "DEL"


def test_profile_rejects_a_non_iata_origin_city() -> None:
    with pytest.raises(ValidationError):
        UserProfile(
            user_id="u1",
            display_name="Himanshu",
            home_country="IN",
            home_currency="INR",
            origin_city="Delhi",
            updated_at=NOW,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/accounts/__init__.py` as an empty file.

Create `backend/accounts/models.py`:

```python
"""Account persistence models — user identity, wallet holdings, and saved trips.

Builds ahead of ``docs/specs/17_accounts_and_persistence.md`` (see DEVIATIONS §A1).

Two invariants are load-bearing here:

1. **No payment-instrument secrets.** These models store a *card product reference*
   (a knowledge-base slug), never an instrument. ``FORBIDDEN_FIELD_NAMES`` plus
   ``extra="forbid"`` make that a schema rule rather than a convention: an unknown
   field is a hard validation error, and a declared forbidden field fails the test
   suite.
2. **Money is never a float.** Points balances are ``int`` counts; any minor-unit
   amount follows the spec-01 integer convention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

# Bumped when a stored JSON payload's shape changes incompatibly. Written onto
# every ``SavedTrip`` / ``TripRevision`` so a future reader knows how to parse a
# snapshot it did not write.
ACCOUNTS_SCHEMA_VERSION = "1"

# Field names that may never appear on a stored account model. ``password_hash``
# is deliberately absent — the (separate, later) auth plan owns credential storage
# and will add it to ``User``. ``password`` in the clear is forbidden forever.
FORBIDDEN_FIELD_NAMES: frozenset[str] = frozenset(
    {
        "pan",
        "card_number",
        "cardnumber",
        "primary_account_number",
        "expiry",
        "expiry_date",
        "exp_month",
        "exp_year",
        "cvv",
        "cvc",
        "csc",
        "security_code",
        "pin",
        "password",
        "bank_password",
        "loyalty_password",
        "net_banking_password",
    }
)


class AccountModel(BaseModel):
    """Base for every stored account model: unknown fields are a hard error.

    ``extra="forbid"`` is the first line of the no-secrets invariant — a caller
    that tries to smuggle ``pan=...`` through gets a ``ValidationError`` instead
    of a silently ignored kwarg.
    """

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- #
# 1. Identity                                                                   #
# --------------------------------------------------------------------------- #


class User(AccountModel):
    """A person with an account. Credentials are NOT stored here (see module doc)."""

    id: str
    email: str
    created_at: datetime
    status: Literal["active", "disabled"] = "active"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, _, domain = normalized.partition("@")
        if not local or not domain or "." not in domain:
            raise ValueError("email must be of the form local@domain.tld")
        return normalized


class UserProfile(AccountModel):
    """Personal details attached to a user. One row per user."""

    user_id: str
    display_name: str
    home_country: Literal["IN", "AE", "US"]
    home_currency: str
    origin_city: str | None = None  # IATA, e.g. "DEL"
    updated_at: datetime

    @field_validator("home_currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a 3-letter ISO 4217 code")
        return normalized

    @field_validator("origin_city")
    @classmethod
    def normalize_iata(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("origin_city must be a 3-letter IATA code")
        return normalized
```

- [ ] **Step 4: Add the package to setuptools**

In `backend/pyproject.toml`, change:

```toml
packages = ["core", "core.optimizer", "core.transfer", "agents", "api", "evals"]
```

to:

```toml
packages = ["core", "core.optimizer", "core.transfer", "accounts", "agents", "api", "evals"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 2 source files`

- [ ] **Step 7: Commit**

```bash
git add backend/accounts/__init__.py backend/accounts/models.py backend/evals/test_a1_models.py backend/pyproject.toml
git commit -m "feat(accounts): identity models and no-secrets schema invariant"
```

---

### Task 2: WalletEntry model

**Files:**
- Modify: `backend/accounts/models.py` (append a new section)
- Test: `backend/evals/test_a1_models.py` (append)

**Interfaces:**
- Consumes: `AccountModel`, `FORBIDDEN_FIELD_NAMES` from Task 1.
- Produces: `WalletEntry` with fields `id: str`, `user_id: str`, `card_id: str`, `nickname: str`, `last4: str | None`, `statement_day: int | None`, `opened_on: date | None`, `points_balances: dict[str, int]`, `added_at: datetime`.

**Why `opened_on` exists:** the highest-value card offers are usually welcome/joining bonuses that must be earned inside a window (commonly 90 days) after the card is opened. Persisting the open date is the *only* thing this plan does for that feature; the recommendation logic itself is unspecced and out of scope (see Task 10's SCOPE+ row).

**Why there is no `last4` uniqueness or Luhn check:** `last4` is a human disambiguator ("which Infinia is this?"), not an instrument. Four digits carry no payment capability and no Luhn signal.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a1_models.py`. Also extend the `accounts.models` import to include `WalletEntry`, and add `date` to the datetime import so the line reads `from datetime import date, datetime, timezone`:

```python
def _entry(**overrides: object) -> WalletEntry:
    kwargs: dict[str, object] = {
        "id": "w1",
        "user_id": "u1",
        "card_id": "hdfc-infinia",
        "nickname": "Main Infinia",
        "added_at": NOW,
    }
    kwargs.update(overrides)
    return WalletEntry(**kwargs)  # type: ignore[arg-type]


def test_wallet_entry_stores_a_product_reference_with_optional_details() -> None:
    entry = _entry(
        last4="4321",
        statement_day=18,
        opened_on=date(2026, 5, 2),
        points_balances={"hdfc-reward-points": 140000},
    )

    assert entry.card_id == "hdfc-infinia"
    assert entry.last4 == "4321"
    assert entry.statement_day == 18
    assert entry.opened_on == date(2026, 5, 2)
    assert entry.points_balances == {"hdfc-reward-points": 140000}


def test_wallet_entry_defaults_omit_every_optional_detail() -> None:
    entry = _entry()

    assert entry.last4 is None
    assert entry.statement_day is None
    assert entry.opened_on is None
    assert entry.points_balances == {}


def test_wallet_entry_rejects_a_full_card_number_as_last4() -> None:
    with pytest.raises(ValidationError):
        _entry(last4="4111111111111111")


def test_wallet_entry_rejects_non_numeric_last4() -> None:
    with pytest.raises(ValidationError):
        _entry(last4="12a4")


def test_wallet_entry_rejects_an_out_of_range_statement_day() -> None:
    with pytest.raises(ValidationError):
        _entry(statement_day=0)
    with pytest.raises(ValidationError):
        _entry(statement_day=32)


def test_wallet_entry_rejects_a_negative_points_balance() -> None:
    with pytest.raises(ValidationError):
        _entry(points_balances={"hdfc-reward-points": -1})


def test_wallet_entry_rejects_a_smuggled_pan() -> None:
    with pytest.raises(ValidationError):
        _entry(pan="4111111111111111")


def test_wallet_entry_declares_no_forbidden_field() -> None:
    for field_name in WalletEntry.model_fields:
        assert field_name.lower() not in FORBIDDEN_FIELD_NAMES
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'WalletEntry' from 'accounts.models'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/accounts/models.py`. Also change its datetime import to `from datetime import date, datetime` and its pydantic import to `from pydantic import BaseModel, ConfigDict, Field, field_validator`:

```python
# --------------------------------------------------------------------------- #
# 2. Wallet holdings                                                            #
# --------------------------------------------------------------------------- #


class WalletEntry(AccountModel):
    """One card product the user holds.

    ``card_id`` is a knowledge-base slug (``core.models.Card.id``, e.g.
    ``"hdfc-infinia"``) — the optimizer resolves earn rules by product, so a real
    card number would buy nothing and would pull this project into PCI-DSS scope.
    ``last4`` is a human disambiguator only.

    ``opened_on`` exists so a later feature can reason about welcome-bonus windows;
    nothing in this layer interprets it.
    """

    id: str
    user_id: str
    card_id: str
    nickname: str
    last4: str | None = None
    statement_day: int | None = Field(default=None, ge=1, le=31)
    opened_on: date | None = None
    points_balances: dict[str, int] = Field(default_factory=dict)
    added_at: datetime

    @field_validator("last4")
    @classmethod
    def check_last4(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if len(normalized) != 4 or not normalized.isdigit():
            raise ValueError("last4 must be exactly four digits (never a full PAN)")
        return normalized

    @field_validator("points_balances")
    @classmethod
    def check_balances(cls, value: dict[str, int]) -> dict[str, int]:
        for currency_id, balance in value.items():
            if balance < 0:
                raise ValueError(f"points balance for {currency_id} must be >= 0")
        return value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: PASS (14 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 2 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/models.py backend/evals/test_a1_models.py
git commit -m "feat(accounts): WalletEntry model with no-instrument invariant"
```

---

### Task 3: SavedTrip and TripRevision models

**Files:**
- Modify: `backend/accounts/models.py` (append a new section)
- Test: `backend/evals/test_a1_models.py` (append)

**Interfaces:**
- Consumes: `AccountModel`, `ACCOUNTS_SCHEMA_VERSION` from Task 1.
- Produces: `SavedTrip` (`id`, `user_id`, `title`, `origin_city`, `destination_city`, `start_date`, `end_date`, `raw_request`, `trip_spec_json`, `schema_version`, `created_at`) and `TripRevision` (`id`, `trip_id`, `revision`, `trace_id`, `report_json`, `schema_version`, `created_at`).

**Why the payloads are JSON strings, not typed `TripSpec` / `FinalReport`:** a saved trip is an *immutable snapshot* that must keep the provenance and `last_verified` data it was computed with. If `TripRevision` held a typed `FinalReport`, re-reading an old row through a *later* version of that model would silently coerce, default, or drop fields — the snapshot would quietly change meaning. Storing the exact canonical bytes plus a `schema_version` makes the snapshot survive schema evolution. It also keeps `accounts/` free of any dependency on `agents/`. Callers pass `spec.model_dump_json()` / `report.model_dump_json()`; the API layer (later plan) parses them back, since it already imports `agents`.

**Immutability rule:** re-running a saved trip appends a `TripRevision`. Nothing ever mutates an existing revision. Task 8 enforces this at the store level; here the model just carries a monotonic `revision` counter starting at 1.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a1_models.py`. Also extend the `accounts.models` import with `ACCOUNTS_SCHEMA_VERSION`, `SavedTrip`, `TripRevision`:

```python
def test_saved_trip_stores_the_canonical_input_snapshot() -> None:
    trip = SavedTrip(
        id="t1",
        user_id="u1",
        title="Singapore, August",
        origin_city="del",
        destination_city="sin",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        raw_request="Delhi to Singapore Aug 1-5",
        trip_spec_json='{"origin_city":"DEL"}',
        created_at=NOW,
    )

    assert trip.origin_city == "DEL"
    assert trip.destination_city == "SIN"
    assert trip.schema_version == ACCOUNTS_SCHEMA_VERSION


def test_saved_trip_rejects_an_end_date_before_the_start_date() -> None:
    with pytest.raises(ValidationError):
        SavedTrip(
            id="t1",
            user_id="u1",
            title="Backwards",
            origin_city="DEL",
            destination_city="SIN",
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 1),
            raw_request="x",
            trip_spec_json="{}",
            created_at=NOW,
        )


def test_saved_trip_rejects_a_payload_that_is_not_a_json_object() -> None:
    with pytest.raises(ValidationError):
        SavedTrip(
            id="t1",
            user_id="u1",
            title="Bad payload",
            origin_city="DEL",
            destination_city="SIN",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            raw_request="x",
            trip_spec_json="not json",
            created_at=NOW,
        )


def test_trip_revision_numbers_start_at_one() -> None:
    revision = TripRevision(
        id="r1",
        trip_id="t1",
        revision=1,
        trace_id="abc123",
        report_json='{"summary":"Grounded summary."}',
        created_at=NOW,
    )

    assert revision.revision == 1
    assert revision.schema_version == ACCOUNTS_SCHEMA_VERSION


def test_trip_revision_rejects_a_zero_revision_number() -> None:
    with pytest.raises(ValidationError):
        TripRevision(
            id="r1",
            trip_id="t1",
            revision=0,
            trace_id="abc123",
            report_json="{}",
            created_at=NOW,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: FAIL — `ImportError: cannot import name 'SavedTrip' from 'accounts.models'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/accounts/models.py`. Also add `import json` under the `from __future__` line, and extend the pydantic import to `from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator`:

```python
# --------------------------------------------------------------------------- #
# 3. Saved trips (immutable snapshots)                                          #
# --------------------------------------------------------------------------- #


def _require_json_object(value: str, field_name: str) -> str:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field_name} must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field_name} must be a JSON object")
    return value


class SavedTrip(AccountModel):
    """A trip the user asked for. The stored input half of a saved plan.

    ``trip_spec_json`` is the canonical ``TripSpec.model_dump_json()`` exactly as
    submitted. It is stored as bytes rather than a typed model so the snapshot
    cannot drift when ``TripSpec`` changes — see the plan's Task 3 rationale.
    """

    id: str
    user_id: str
    title: str
    origin_city: str
    destination_city: str
    start_date: date
    end_date: date
    raw_request: str
    trip_spec_json: str
    schema_version: str = ACCOUNTS_SCHEMA_VERSION
    created_at: datetime

    @field_validator("origin_city", "destination_city")
    @classmethod
    def normalize_iata(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("city must be a 3-letter IATA code")
        return normalized

    @field_validator("trip_spec_json")
    @classmethod
    def check_trip_spec_json(cls, value: str) -> str:
        return _require_json_object(value, "trip_spec_json")

    @model_validator(mode="after")
    def check_date_order(self) -> SavedTrip:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


class TripRevision(AccountModel):
    """One computed result for a saved trip. Append-only; never mutated.

    ``report_json`` is the canonical ``FinalReport.model_dump_json()`` produced by
    the pipeline, kept verbatim so the provenance and ``last_verified`` values the
    plan was computed with are preserved exactly.
    """

    id: str
    trip_id: str
    revision: int = Field(ge=1)
    trace_id: str
    report_json: str
    schema_version: str = ACCOUNTS_SCHEMA_VERSION
    created_at: datetime

    @field_validator("report_json")
    @classmethod
    def check_report_json(cls, value: str) -> str:
        return _require_json_object(value, "report_json")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: PASS (19 tests)

- [ ] **Step 5: Extend the forbidden-field sweep to every model**

In `test_no_account_model_declares_a_forbidden_field`, change the tuple to cover all five models:

```python
    for model in (User, UserProfile, WalletEntry, SavedTrip, TripRevision):
```

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: PASS (19 tests)

- [ ] **Step 6: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 2 source files`

- [ ] **Step 7: Commit**

```bash
git add backend/accounts/models.py backend/evals/test_a1_models.py
git commit -m "feat(accounts): SavedTrip and TripRevision immutable snapshot models"
```

---

### Task 4: SQLAlchemy schema in an isolated database

**Files:**
- Create: `backend/accounts/db.py`
- Test: `backend/evals/test_a1_boundary.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (schema only).
- Produces: `ACCOUNTS_DB_PATH: Path`, `AccountsBase`, row classes `UserRow`, `UserProfileRow`, `WalletEntryRow`, `SavedTripRow`, `TripRevisionRow`, and `create_accounts_engine(db_path: Path = ACCOUNTS_DB_PATH) -> Engine` (which creates tables if absent and **never** drops).

**The critical point:** `core/db.py:420` runs `Base.metadata.drop_all(engine)` every time `seed_database()` is called. If accounts tables shared that `DeclarativeBase` or that database file, re-seeding reference data would silently destroy every user account. Hence a separate `AccountsBase`, a separate file (`backend/accounts/accounts.sqlite`), and no `drop_all` anywhere in this module.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a1_boundary.py`:

```python
from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from accounts.db import AccountsBase, create_accounts_engine
from core.db import Base as CoreBase
from core.db import SEEDS_DIR, seed_database

ACCOUNTS_TABLES = {
    "users",
    "user_profiles",
    "wallet_entries",
    "saved_trips",
    "trip_revisions",
}


def test_accounts_tables_are_not_registered_on_the_core_metadata() -> None:
    assert set(AccountsBase.metadata.tables) == ACCOUNTS_TABLES
    assert set(CoreBase.metadata.tables).isdisjoint(ACCOUNTS_TABLES)


def test_create_accounts_engine_creates_every_table(tmp_path: Path) -> None:
    engine = create_accounts_engine(tmp_path / "accounts.sqlite")

    assert set(inspect(engine).get_table_names()) == ACCOUNTS_TABLES


def test_reseeding_the_knowledge_base_does_not_touch_accounts_tables(
    tmp_path: Path,
) -> None:
    engine = create_accounts_engine(tmp_path / "accounts.sqlite")
    kb_db = tmp_path / "tripwise.sqlite"

    seed_database(SEEDS_DIR, kb_db)
    seed_database(SEEDS_DIR, kb_db)  # drop_all + create_all, twice

    names = set(inspect(engine).get_table_names())
    assert "users" in names
    assert "cards" not in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_boundary.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.db'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/accounts/db.py`:

```python
"""SQLAlchemy schema for user-owned data (builds ahead of spec 17).

Storage pattern mirrors ``core/db.py``: one table per model, the columns worth
indexing broken out as real columns, plus a ``payload`` TEXT column holding the
canonical ``model_dump_json()`` for lossless round-trip.

**Isolation is deliberate.** ``core.db.seed_database`` opens with
``Base.metadata.drop_all(engine)``. Accounts therefore get their own
``DeclarativeBase`` and their own database file, so re-seeding reference data can
never destroy user data. Nothing in this module ever drops a table.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ACCOUNTS_DB_PATH = Path(__file__).parent / "accounts.sqlite"


class AccountsBase(DeclarativeBase):
    pass


class UserRow(AccountsBase):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    payload: Mapped[str] = mapped_column(Text)


class UserProfileRow(AccountsBase):
    __tablename__ = "user_profiles"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class WalletEntryRow(AccountsBase):
    __tablename__ = "wallet_entries"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    card_id: Mapped[str] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


class SavedTripRow(AccountsBase):
    __tablename__ = "saved_trips"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    created_at: Mapped[str] = mapped_column(index=True)  # ISO datetime string
    payload: Mapped[str] = mapped_column(Text)


class TripRevisionRow(AccountsBase):
    __tablename__ = "trip_revisions"
    id: Mapped[str] = mapped_column(primary_key=True)
    trip_id: Mapped[str] = mapped_column(index=True)
    revision: Mapped[int] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


def create_accounts_engine(db_path: Path = ACCOUNTS_DB_PATH) -> Engine:
    """Open (creating if needed) the accounts database. Never drops."""
    engine = create_engine(f"sqlite:///{db_path}")
    AccountsBase.metadata.create_all(engine)
    return engine
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_boundary.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 3 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/db.py backend/evals/test_a1_boundary.py
git commit -m "feat(accounts): isolated SQLAlchemy schema for user-owned data"
```

---

### Task 5: AccountStore — users and profiles

**Files:**
- Create: `backend/accounts/store.py`
- Test: `backend/evals/test_a1_store.py`

**Interfaces:**
- Consumes: `User`, `UserProfile` (Task 1); `ACCOUNTS_DB_PATH`, `create_accounts_engine`, `UserRow`, `UserProfileRow` (Task 4).
- Produces: `AccountStore` with `__init__(self, engine: Engine)`, `open(cls, db_path: Path = ACCOUNTS_DB_PATH) -> AccountStore`, `create_user(self, *, email: str, now: datetime, user_id: str | None = None) -> User`, `get_user(self, user_id: str) -> User | None`, `get_user_by_email(self, email: str) -> User | None`, `put_profile(self, profile: UserProfile) -> UserProfile`, `get_profile(self, user_id: str) -> UserProfile | None`. Also the module-level exceptions `DuplicateEmailError(ValueError)` and `UnknownUserError(ValueError)`.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a1_store.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from accounts.models import UserProfile
from accounts.store import AccountStore, DuplicateEmailError

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> AccountStore:
    return AccountStore.open(tmp_path / "accounts.sqlite")


def test_create_user_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)

    created = store.create_user(email="Himanshu@Example.com", now=NOW, user_id="u1")
    fetched = store.get_user("u1")

    assert created.id == "u1"
    assert created.email == "himanshu@example.com"
    assert fetched == created


def test_create_user_mints_an_id_when_none_is_given(tmp_path: Path) -> None:
    store = _store(tmp_path)

    created = store.create_user(email="a@example.com", now=NOW)

    assert len(created.id) > 0
    assert store.get_user(created.id) == created


def test_get_user_by_email_is_case_insensitive(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")

    found = store.get_user_by_email("  A@EXAMPLE.COM ")

    assert found is not None
    assert found.id == "u1"


def test_create_user_rejects_a_duplicate_email(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")

    with pytest.raises(DuplicateEmailError):
        store.create_user(email="A@example.com", now=NOW, user_id="u2")


def test_get_user_returns_none_when_absent(tmp_path: Path) -> None:
    assert _store(tmp_path).get_user("nobody") is None


def test_put_profile_upserts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")

    store.put_profile(
        UserProfile(
            user_id="u1",
            display_name="Himanshu",
            home_country="IN",
            home_currency="INR",
            updated_at=NOW,
        )
    )
    store.put_profile(
        UserProfile(
            user_id="u1",
            display_name="H. Jain",
            home_country="IN",
            home_currency="INR",
            origin_city="DEL",
            updated_at=NOW,
        )
    )

    profile = store.get_profile("u1")
    assert profile is not None
    assert profile.display_name == "H. Jain"
    assert profile.origin_city == "DEL"


def test_store_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "accounts.sqlite"
    AccountStore.open(db_path).create_user(email="a@example.com", now=NOW, user_id="u1")

    reopened = AccountStore.open(db_path)

    assert reopened.get_user("u1") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.store'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/accounts/store.py`:

```python
"""``AccountStore`` — the only write boundary for user-owned data (spec 17, pending).

``backend/core/`` is a read facade and must never import this module. Everything
that mutates user state passes through the typed methods here, which keeps the
optimizer deterministic and keeps user writes out of the kernel's path.

Determinism: no method reads the clock or a random seed implicitly. Timestamps
arrive as an explicit ``now`` argument and identifiers may be supplied by the
caller — the same injection style the pipeline uses for ``booking_date``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from accounts.db import (
    ACCOUNTS_DB_PATH,
    UserProfileRow,
    UserRow,
    create_accounts_engine,
)
from accounts.models import User, UserProfile


class DuplicateEmailError(ValueError):
    """Raised when an email is already registered to another user."""


class UnknownUserError(ValueError):
    """Raised when an operation names a user id that does not exist."""


class AccountStore:
    """Typed read/write access to user-owned data."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def open(cls, db_path: Path = ACCOUNTS_DB_PATH) -> AccountStore:
        return cls(create_accounts_engine(db_path))

    # -- users -------------------------------------------------------------- #

    def create_user(
        self, *, email: str, now: datetime, user_id: str | None = None
    ) -> User:
        user = User(id=user_id or uuid4().hex, email=email, created_at=now)
        with Session(self._engine) as session:
            existing = session.scalar(
                select(UserRow).where(UserRow.email == user.email)
            )
            if existing is not None:
                raise DuplicateEmailError(f"email already registered: {user.email}")
            session.add(
                UserRow(id=user.id, email=user.email, payload=user.model_dump_json())
            )
            session.commit()
        return user

    def get_user(self, user_id: str) -> User | None:
        with Session(self._engine) as session:
            row = session.get(UserRow, user_id)
            return None if row is None else User.model_validate_json(row.payload)

    def get_user_by_email(self, email: str) -> User | None:
        needle = email.strip().lower()
        with Session(self._engine) as session:
            row = session.scalar(select(UserRow).where(UserRow.email == needle))
            return None if row is None else User.model_validate_json(row.payload)

    def _require_user(self, session: Session, user_id: str) -> UserRow:
        row = session.get(UserRow, user_id)
        if row is None:
            raise UnknownUserError(f"no such user: {user_id}")
        return row

    # -- profiles ----------------------------------------------------------- #

    def put_profile(self, profile: UserProfile) -> UserProfile:
        """Insert or replace the single profile row for a user."""
        with Session(self._engine) as session:
            self._require_user(session, profile.user_id)
            row = session.get(UserProfileRow, profile.user_id)
            if row is None:
                session.add(
                    UserProfileRow(
                        user_id=profile.user_id, payload=profile.model_dump_json()
                    )
                )
            else:
                row.payload = profile.model_dump_json()
            session.commit()
        return profile

    def get_profile(self, user_id: str) -> UserProfile | None:
        with Session(self._engine) as session:
            row = session.get(UserProfileRow, user_id)
            return (
                None if row is None else UserProfile.model_validate_json(row.payload)
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 4 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/store.py backend/evals/test_a1_store.py
git commit -m "feat(accounts): AccountStore write boundary for users and profiles"
```

---

### Task 6: AccountStore — wallet entries

**Files:**
- Modify: `backend/accounts/store.py` (append a wallet section)
- Test: `backend/evals/test_a1_store.py` (append)

**Interfaces:**
- Consumes: `AccountStore`, `UnknownUserError` (Task 5); `WalletEntry` (Task 2); `WalletEntryRow` (Task 4).
- Produces: `AccountStore.add_wallet_entry(self, *, user_id: str, card_id: str, nickname: str, now: datetime, last4: str | None = None, statement_day: int | None = None, opened_on: date | None = None, points_balances: dict[str, int] | None = None, entry_id: str | None = None) -> WalletEntry`; `AccountStore.set_points_balances(self, entry_id: str, balances: dict[str, int]) -> WalletEntry`; `AccountStore.remove_wallet_entry(self, entry_id: str) -> None`; `AccountStore.wallet_entries(self, user_id: str) -> list[WalletEntry]` returning rows sorted by `(card_id, id)`.

**Ordering contract:** `wallet_entries` sorts by `(card_id, id)`. Stable ordering is what lets the projection in Task 7 produce a byte-reproducible `UserWallet`, which is what keeps the optimizer's output reproducible.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a1_store.py`. Also add `date` to the datetime import (`from datetime import date, datetime, timezone`) and extend the `accounts.store` import with `UnknownUserError`:

```python
def _user_store(tmp_path: Path) -> AccountStore:
    store = _store(tmp_path)
    store.create_user(email="a@example.com", now=NOW, user_id="u1")
    return store


def test_add_wallet_entry_round_trips(tmp_path: Path) -> None:
    store = _user_store(tmp_path)

    entry = store.add_wallet_entry(
        user_id="u1",
        card_id="hdfc-infinia",
        nickname="Main Infinia",
        now=NOW,
        last4="4321",
        statement_day=18,
        opened_on=date(2026, 5, 2),
        points_balances={"hdfc-reward-points": 140000},
        entry_id="w1",
    )

    assert store.wallet_entries("u1") == [entry]


def test_wallet_entries_are_ordered_by_card_id_then_id(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    for entry_id, card_id in [
        ("w3", "hdfc-infinia"),
        ("w1", "amex-platinum"),
        ("w2", "hdfc-infinia"),
    ]:
        store.add_wallet_entry(
            user_id="u1",
            card_id=card_id,
            nickname=entry_id,
            now=NOW,
            entry_id=entry_id,
        )

    assert [e.id for e in store.wallet_entries("u1")] == ["w1", "w2", "w3"]


def test_wallet_entries_are_scoped_to_one_user(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.create_user(email="b@example.com", now=NOW, user_id="u2")
    store.add_wallet_entry(
        user_id="u1", card_id="hdfc-infinia", nickname="A", now=NOW, entry_id="w1"
    )
    store.add_wallet_entry(
        user_id="u2", card_id="amex-platinum", nickname="B", now=NOW, entry_id="w2"
    )

    assert [e.id for e in store.wallet_entries("u1")] == ["w1"]
    assert [e.id for e in store.wallet_entries("u2")] == ["w2"]


def test_add_wallet_entry_rejects_an_unknown_user(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(UnknownUserError):
        store.add_wallet_entry(
            user_id="ghost", card_id="hdfc-infinia", nickname="A", now=NOW
        )


def test_set_points_balances_replaces_the_stored_map(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.add_wallet_entry(
        user_id="u1",
        card_id="hdfc-infinia",
        nickname="A",
        now=NOW,
        points_balances={"hdfc-reward-points": 100},
        entry_id="w1",
    )

    updated = store.set_points_balances("w1", {"hdfc-reward-points": 250})

    assert updated.points_balances == {"hdfc-reward-points": 250}
    assert store.wallet_entries("u1")[0].points_balances == {"hdfc-reward-points": 250}


def test_set_points_balances_rejects_a_negative_balance(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.add_wallet_entry(
        user_id="u1", card_id="hdfc-infinia", nickname="A", now=NOW, entry_id="w1"
    )

    with pytest.raises(ValueError):
        store.set_points_balances("w1", {"hdfc-reward-points": -5})


def test_remove_wallet_entry(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    store.add_wallet_entry(
        user_id="u1", card_id="hdfc-infinia", nickname="A", now=NOW, entry_id="w1"
    )

    store.remove_wallet_entry("w1")

    assert store.wallet_entries("u1") == []


def test_add_wallet_entry_rejects_a_full_card_number(tmp_path: Path) -> None:
    store = _user_store(tmp_path)

    with pytest.raises(ValueError):
        store.add_wallet_entry(
            user_id="u1",
            card_id="hdfc-infinia",
            nickname="A",
            now=NOW,
            last4="4111111111111111",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: FAIL — `AttributeError: 'AccountStore' object has no attribute 'add_wallet_entry'`

- [ ] **Step 3: Write minimal implementation**

In `backend/accounts/store.py`: change the datetime import to `from datetime import date, datetime`, add `WalletEntryRow` to the `accounts.db` import, add `WalletEntry` to the `accounts.models` import. Then append inside the `AccountStore` class:

```python
    # -- wallet ------------------------------------------------------------- #

    def add_wallet_entry(
        self,
        *,
        user_id: str,
        card_id: str,
        nickname: str,
        now: datetime,
        last4: str | None = None,
        statement_day: int | None = None,
        opened_on: date | None = None,
        points_balances: dict[str, int] | None = None,
        entry_id: str | None = None,
    ) -> WalletEntry:
        entry = WalletEntry(
            id=entry_id or uuid4().hex,
            user_id=user_id,
            card_id=card_id,
            nickname=nickname,
            last4=last4,
            statement_day=statement_day,
            opened_on=opened_on,
            points_balances=dict(points_balances or {}),
            added_at=now,
        )
        with Session(self._engine) as session:
            self._require_user(session, user_id)
            session.add(
                WalletEntryRow(
                    id=entry.id,
                    user_id=entry.user_id,
                    card_id=entry.card_id,
                    payload=entry.model_dump_json(),
                )
            )
            session.commit()
        return entry

    def set_points_balances(
        self, entry_id: str, balances: dict[str, int]
    ) -> WalletEntry:
        """Replace (not merge) the stored balance map for one wallet entry."""
        with Session(self._engine) as session:
            row = session.get(WalletEntryRow, entry_id)
            if row is None:
                raise ValueError(f"no such wallet entry: {entry_id}")
            entry = WalletEntry.model_validate_json(row.payload)
            candidate = entry.model_copy(update={"points_balances": dict(balances)})
            # model_copy skips validators, so round-trip the JSON to re-validate.
            updated = WalletEntry.model_validate_json(candidate.model_dump_json())
            row.payload = updated.model_dump_json()
            session.commit()
        return updated

    def remove_wallet_entry(self, entry_id: str) -> None:
        with Session(self._engine) as session:
            row = session.get(WalletEntryRow, entry_id)
            if row is not None:
                session.delete(row)
                session.commit()

    def wallet_entries(self, user_id: str) -> list[WalletEntry]:
        """Every card the user holds, ordered by ``(card_id, id)``.

        The order is part of the contract: the ``UserWallet`` projection folds
        these rows, and the optimizer's output must be byte-reproducible.
        """
        with Session(self._engine) as session:
            rows = session.scalars(
                select(WalletEntryRow).where(WalletEntryRow.user_id == user_id)
            ).all()
            entries = [WalletEntry.model_validate_json(r.payload) for r in rows]
        return sorted(entries, key=lambda e: (e.card_id, e.id))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 4 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/store.py backend/evals/test_a1_store.py
git commit -m "feat(accounts): wallet entry persistence with deterministic ordering"
```

---

### Task 7: UserWallet projection

**Files:**
- Create: `backend/accounts/projection.py`
- Test: `backend/evals/test_a1_projection.py`

**Interfaces:**
- Consumes: `WalletEntry` (Task 2); `core.models.UserWallet`.
- Produces: `build_user_wallet(entries: Sequence[WalletEntry]) -> UserWallet`.

**The one non-obvious rule — duplicate points currencies collapse by `max`, not `sum`.** Two cards from the same issuer usually share one pooled points balance. If a user records that pool balance on both wallet entries, summing would double-count it and could make the transfer pathfinder propose a transfer the user cannot actually fund. Taking the maximum is the conservative direction: it never overstates available points. This is a judgment call under the ambiguity protocol and gets a `DEVIATIONS.md` row in Task 10.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a1_projection.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from accounts.models import WalletEntry
from accounts.projection import build_user_wallet
from core.models import UserWallet

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _entry(
    entry_id: str, card_id: str, balances: dict[str, int] | None = None
) -> WalletEntry:
    return WalletEntry(
        id=entry_id,
        user_id="u1",
        card_id=card_id,
        nickname=entry_id,
        points_balances=balances or {},
        added_at=NOW,
    )


def test_empty_wallet_projects_to_an_empty_user_wallet() -> None:
    wallet = build_user_wallet([])

    assert wallet == UserWallet(card_ids=[], points_balances={})


def test_projection_collects_card_ids_and_balances() -> None:
    wallet = build_user_wallet(
        [
            _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 140000}),
            _entry("w2", "amex-platinum", {"membership-rewards": 50000}),
        ]
    )

    assert wallet.card_ids == ["amex-platinum", "hdfc-infinia"]
    assert wallet.points_balances == {
        "hdfc-reward-points": 140000,
        "membership-rewards": 50000,
    }


def test_projection_is_order_independent() -> None:
    a = _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 100})
    b = _entry("w2", "amex-platinum", {"membership-rewards": 200})

    assert build_user_wallet([a, b]) == build_user_wallet([b, a])


def test_duplicate_card_ids_appear_once() -> None:
    wallet = build_user_wallet(
        [_entry("w1", "hdfc-infinia"), _entry("w2", "hdfc-infinia")]
    )

    assert wallet.card_ids == ["hdfc-infinia"]


def test_a_shared_points_pool_is_not_double_counted() -> None:
    """Two cards on one pooled currency collapse by max, never by sum."""
    wallet = build_user_wallet(
        [
            _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 140000}),
            _entry("w2", "hdfc-diners-black", {"hdfc-reward-points": 140000}),
        ]
    )

    assert wallet.points_balances == {"hdfc-reward-points": 140000}


def test_the_larger_recorded_balance_wins() -> None:
    wallet = build_user_wallet(
        [
            _entry("w1", "hdfc-infinia", {"hdfc-reward-points": 90000}),
            _entry("w2", "hdfc-diners-black", {"hdfc-reward-points": 140000}),
        ]
    )

    assert wallet.points_balances == {"hdfc-reward-points": 140000}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_projection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.projection'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/accounts/projection.py`:

```python
"""Pure projections from stored account rows into kernel request inputs.

``UserWallet`` (``core.models``) is the shape the optimizer already consumes. It
is **not** duplicated as a stored model — it is derived here from ``WalletEntry``
rows at request time.
"""

from __future__ import annotations

from collections.abc import Sequence

from accounts.models import WalletEntry
from core.models import UserWallet


def build_user_wallet(entries: Sequence[WalletEntry]) -> UserWallet:
    """Fold stored wallet rows into the kernel's request-time ``UserWallet``.

    Deterministic: ``card_ids`` and ``points_balances`` come out sorted regardless
    of input order, so the optimizer's output stays byte-reproducible.

    Duplicate points currencies collapse by **max, not sum**. Cards from one issuer
    typically share a single pooled balance, so summing user-entered pool figures
    would overstate available points and could produce an unfundable transfer plan.
    Max never overstates.
    """
    card_ids: set[str] = set()
    balances: dict[str, int] = {}
    for entry in entries:
        card_ids.add(entry.card_id)
        for currency_id, balance in entry.points_balances.items():
            current = balances.get(currency_id)
            if current is None or balance > current:
                balances[currency_id] = balance
    return UserWallet(
        card_ids=sorted(card_ids),
        points_balances={key: balances[key] for key in sorted(balances)},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_projection.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 5 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/projection.py backend/evals/test_a1_projection.py
git commit -m "feat(accounts): UserWallet projection from stored wallet entries"
```

---

### Task 8: AccountStore — saved trips and append-only revisions

**Files:**
- Modify: `backend/accounts/store.py` (append a saved-trips section)
- Test: `backend/evals/test_a1_store.py` (append)

**Interfaces:**
- Consumes: `AccountStore` (Task 5); `SavedTrip`, `TripRevision` (Task 3); `SavedTripRow`, `TripRevisionRow` (Task 4).
- Produces: `AccountStore.save_trip(self, *, user_id: str, title: str, origin_city: str, destination_city: str, start_date: date, end_date: date, raw_request: str, trip_spec_json: str, now: datetime, trip_id: str | None = None) -> SavedTrip`; `AccountStore.add_revision(self, *, trip_id: str, trace_id: str, report_json: str, now: datetime, revision_id: str | None = None) -> TripRevision`; `AccountStore.trips(self, user_id: str) -> list[SavedTrip]`; `AccountStore.revisions(self, trip_id: str) -> list[TripRevision]`; `AccountStore.latest_revision(self, trip_id: str) -> TripRevision | None`. Also `UnknownTripError(ValueError)`.

**Immutability:** there is deliberately **no** method that updates or deletes a revision. `add_revision` reads the current maximum revision number for the trip and appends `max + 1`. A re-run produces revision 2; revision 1's stored bytes are untouched.

**Ordering:** `trips` sorts by `(created_at, id)`; `revisions` sorts by `revision` ascending.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a1_store.py`. Also extend the `accounts.store` import with `UnknownTripError`:

```python
def _saved_trip(store: AccountStore, trip_id: str = "t1") -> str:
    trip = store.save_trip(
        user_id="u1",
        title="Singapore, August",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        raw_request="Delhi to Singapore Aug 1-5",
        trip_spec_json='{"origin_city":"DEL","destination_city":"SIN"}',
        now=NOW,
        trip_id=trip_id,
    )
    return trip.id


def test_save_trip_round_trips(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)

    trips = store.trips("u1")

    assert [t.id for t in trips] == [trip_id]
    assert trips[0].trip_spec_json == '{"origin_city":"DEL","destination_city":"SIN"}'


def test_save_trip_rejects_an_unknown_user(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(UnknownUserError):
        store.save_trip(
            user_id="ghost",
            title="x",
            origin_city="DEL",
            destination_city="SIN",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            raw_request="x",
            trip_spec_json="{}",
            now=NOW,
        )


def test_revisions_are_numbered_from_one_and_append(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)

    first = store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )
    second = store.add_revision(
        trip_id=trip_id, trace_id="trace2", report_json='{"summary":"v2"}', now=NOW
    )

    assert first.revision == 1
    assert second.revision == 2
    assert [r.revision for r in store.revisions(trip_id)] == [1, 2]


def test_a_new_revision_never_mutates_an_earlier_one(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)
    store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )

    store.add_revision(
        trip_id=trip_id, trace_id="trace2", report_json='{"summary":"v2"}', now=NOW
    )

    stored = store.revisions(trip_id)
    assert stored[0].report_json == '{"summary":"v1"}'
    assert stored[0].trace_id == "trace1"


def test_the_store_exposes_no_way_to_edit_a_revision() -> None:
    """Immutability is structural: no update/delete method exists for revisions."""
    forbidden = {
        "update_revision",
        "edit_revision",
        "delete_revision",
        "set_revision",
        "replace_revision",
    }

    assert forbidden.isdisjoint(dir(AccountStore))


def test_latest_revision_returns_the_highest_numbered(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)
    store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )
    store.add_revision(
        trip_id=trip_id, trace_id="trace2", report_json='{"summary":"v2"}', now=NOW
    )

    latest = store.latest_revision(trip_id)

    assert latest is not None
    assert latest.revision == 2
    assert latest.trace_id == "trace2"


def test_latest_revision_is_none_for_a_trip_with_no_runs(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    trip_id = _saved_trip(store)

    assert store.latest_revision(trip_id) is None


def test_add_revision_rejects_an_unknown_trip(tmp_path: Path) -> None:
    store = _user_store(tmp_path)

    with pytest.raises(UnknownTripError):
        store.add_revision(trip_id="nope", trace_id="t", report_json="{}", now=NOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: FAIL — `AttributeError: 'AccountStore' object has no attribute 'save_trip'`

- [ ] **Step 3: Write minimal implementation**

In `backend/accounts/store.py`: add `SavedTripRow, TripRevisionRow` to the `accounts.db` import, add `SavedTrip, TripRevision` to the `accounts.models` import, and change the sqlalchemy import to `from sqlalchemy import Engine, func, select`. Add the new exception next to the others:

```python
class UnknownTripError(ValueError):
    """Raised when an operation names a saved trip id that does not exist."""
```

Then append inside the `AccountStore` class:

```python
    # -- saved trips (append-only) ------------------------------------------ #

    def save_trip(
        self,
        *,
        user_id: str,
        title: str,
        origin_city: str,
        destination_city: str,
        start_date: date,
        end_date: date,
        raw_request: str,
        trip_spec_json: str,
        now: datetime,
        trip_id: str | None = None,
    ) -> SavedTrip:
        trip = SavedTrip(
            id=trip_id or uuid4().hex,
            user_id=user_id,
            title=title,
            origin_city=origin_city,
            destination_city=destination_city,
            start_date=start_date,
            end_date=end_date,
            raw_request=raw_request,
            trip_spec_json=trip_spec_json,
            created_at=now,
        )
        with Session(self._engine) as session:
            self._require_user(session, user_id)
            session.add(
                SavedTripRow(
                    id=trip.id,
                    user_id=trip.user_id,
                    created_at=trip.created_at.isoformat(),
                    payload=trip.model_dump_json(),
                )
            )
            session.commit()
        return trip

    def add_revision(
        self,
        *,
        trip_id: str,
        trace_id: str,
        report_json: str,
        now: datetime,
        revision_id: str | None = None,
    ) -> TripRevision:
        """Append a computed result. Never mutates an existing revision.

        Saved trips are immutable: re-running a trip produces revision N+1 so the
        provenance and ``last_verified`` values of every earlier run survive intact.
        """
        with Session(self._engine) as session:
            if session.get(SavedTripRow, trip_id) is None:
                raise UnknownTripError(f"no such saved trip: {trip_id}")
            highest = session.scalar(
                select(func.max(TripRevisionRow.revision)).where(
                    TripRevisionRow.trip_id == trip_id
                )
            )
            revision = TripRevision(
                id=revision_id or uuid4().hex,
                trip_id=trip_id,
                revision=(highest or 0) + 1,
                trace_id=trace_id,
                report_json=report_json,
                created_at=now,
            )
            session.add(
                TripRevisionRow(
                    id=revision.id,
                    trip_id=revision.trip_id,
                    revision=revision.revision,
                    payload=revision.model_dump_json(),
                )
            )
            session.commit()
        return revision

    def trips(self, user_id: str) -> list[SavedTrip]:
        """Every saved trip for a user, ordered by ``(created_at, id)``."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(SavedTripRow).where(SavedTripRow.user_id == user_id)
            ).all()
            trips = [SavedTrip.model_validate_json(r.payload) for r in rows]
        return sorted(trips, key=lambda t: (t.created_at, t.id))

    def revisions(self, trip_id: str) -> list[TripRevision]:
        """Every revision for a trip, oldest first."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(TripRevisionRow).where(TripRevisionRow.trip_id == trip_id)
            ).all()
            revisions = [TripRevision.model_validate_json(r.payload) for r in rows]
        return sorted(revisions, key=lambda r: r.revision)

    def latest_revision(self, trip_id: str) -> TripRevision | None:
        stored = self.revisions(trip_id)
        return stored[-1] if stored else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: PASS (23 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 5 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/store.py backend/evals/test_a1_store.py
git commit -m "feat(accounts): append-only saved trips and trip revisions"
```

---

### Task 9: Export and delete (privacy operations)

**Files:**
- Modify: `backend/accounts/models.py` (append `UserExport`)
- Modify: `backend/accounts/store.py` (append a privacy section)
- Test: `backend/evals/test_a1_store.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–8.
- Produces: `UserExport(AccountModel)` with `user: User`, `profile: UserProfile | None`, `wallet_entries: list[WalletEntry]`, `trips: list[SavedTrip]`, `revisions: list[TripRevision]`, `exported_at: datetime`. And `AccountStore.export_user(self, user_id: str, *, now: datetime) -> UserExport`; `AccountStore.delete_user(self, user_id: str) -> None`.

**Why this is in the persistence plan:** the ability to hand a user everything you hold about them, and to erase it, is a property of the storage layer, not of an endpoint. Building it now means the later API plan only has to expose it.

`delete_user` cascades in dependency order (revisions → trips → wallet entries → profile → user) and is idempotent: deleting an absent user is a no-op, not an error.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a1_store.py`. Also extend the `accounts.models` import with `UserExport`:

```python
def _populated(tmp_path: Path) -> AccountStore:
    store = _user_store(tmp_path)
    store.put_profile(
        UserProfile(
            user_id="u1",
            display_name="Himanshu",
            home_country="IN",
            home_currency="INR",
            updated_at=NOW,
        )
    )
    store.add_wallet_entry(
        user_id="u1",
        card_id="hdfc-infinia",
        nickname="Main",
        now=NOW,
        points_balances={"hdfc-reward-points": 140000},
        entry_id="w1",
    )
    trip_id = _saved_trip(store)
    store.add_revision(
        trip_id=trip_id, trace_id="trace1", report_json='{"summary":"v1"}', now=NOW
    )
    return store


def test_export_user_returns_everything_held(tmp_path: Path) -> None:
    store = _populated(tmp_path)

    export = store.export_user("u1", now=NOW)

    assert isinstance(export, UserExport)
    assert export.user.id == "u1"
    assert export.profile is not None
    assert [e.id for e in export.wallet_entries] == ["w1"]
    assert [t.id for t in export.trips] == ["t1"]
    assert [r.revision for r in export.revisions] == [1]
    assert export.exported_at == NOW


def test_export_rejects_an_unknown_user(tmp_path: Path) -> None:
    with pytest.raises(UnknownUserError):
        _store(tmp_path).export_user("ghost", now=NOW)


def test_delete_user_removes_every_owned_row(tmp_path: Path) -> None:
    store = _populated(tmp_path)

    store.delete_user("u1")

    assert store.get_user("u1") is None
    assert store.get_profile("u1") is None
    assert store.wallet_entries("u1") == []
    assert store.trips("u1") == []
    assert store.revisions("t1") == []


def test_delete_user_leaves_other_users_intact(tmp_path: Path) -> None:
    store = _populated(tmp_path)
    store.create_user(email="b@example.com", now=NOW, user_id="u2")
    store.add_wallet_entry(
        user_id="u2", card_id="amex-platinum", nickname="B", now=NOW, entry_id="w2"
    )

    store.delete_user("u1")

    assert store.get_user("u2") is not None
    assert [e.id for e in store.wallet_entries("u2")] == ["w2"]


def test_delete_user_is_idempotent(tmp_path: Path) -> None:
    store = _populated(tmp_path)

    store.delete_user("u1")
    store.delete_user("u1")  # must not raise

    assert store.get_user("u1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'UserExport' from 'accounts.models'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/accounts/models.py`:

```python
# --------------------------------------------------------------------------- #
# 4. Privacy — the full picture of what is held about one user                  #
# --------------------------------------------------------------------------- #


class UserExport(AccountModel):
    """Everything the system stores about one user, for subject-access export."""

    user: User
    profile: UserProfile | None = None
    wallet_entries: list[WalletEntry] = Field(default_factory=list)
    trips: list[SavedTrip] = Field(default_factory=list)
    revisions: list[TripRevision] = Field(default_factory=list)
    exported_at: datetime
```

In `backend/accounts/store.py`, add `UserExport` to the `accounts.models` import and change the sqlalchemy import to `from sqlalchemy import Engine, delete, func, select`, then append inside `AccountStore`:

```python
    # -- privacy ------------------------------------------------------------ #

    def export_user(self, user_id: str, *, now: datetime) -> UserExport:
        """Every row held about a user, in the layer's deterministic order."""
        user = self.get_user(user_id)
        if user is None:
            raise UnknownUserError(f"no such user: {user_id}")
        trips = self.trips(user_id)
        revisions: list[TripRevision] = []
        for trip in trips:
            revisions.extend(self.revisions(trip.id))
        return UserExport(
            user=user,
            profile=self.get_profile(user_id),
            wallet_entries=self.wallet_entries(user_id),
            trips=trips,
            revisions=revisions,
            exported_at=now,
        )

    def delete_user(self, user_id: str) -> None:
        """Erase a user and everything they own. Idempotent."""
        trip_ids = [trip.id for trip in self.trips(user_id)]
        with Session(self._engine) as session:
            if trip_ids:
                session.execute(
                    delete(TripRevisionRow).where(
                        TripRevisionRow.trip_id.in_(trip_ids)
                    )
                )
            session.execute(delete(SavedTripRow).where(SavedTripRow.user_id == user_id))
            session.execute(
                delete(WalletEntryRow).where(WalletEntryRow.user_id == user_id)
            )
            session.execute(
                delete(UserProfileRow).where(UserProfileRow.user_id == user_id)
            )
            session.execute(delete(UserRow).where(UserRow.id == user_id))
            session.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_store.py -v`
Expected: PASS (28 tests)

- [ ] **Step 5: Type check**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success: no issues found in 5 source files`

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/models.py backend/accounts/store.py backend/evals/test_a1_store.py
git commit -m "feat(accounts): user export and cascading delete"
```

---

### Task 10: Gate A1 — boundary enforcement, regression, and the paper trail

**Files:**
- Modify: `backend/evals/test_a1_boundary.py` (append the import-direction tests)
- Create: `reports/milestone_a1.md`
- Modify: `DEVIATIONS.md` (new `## A1` section)
- Modify: the `.gitignore` that already covers `tripwise.sqlite` (add `accounts.sqlite`)

**Interfaces:**
- Consumes: everything.
- Produces: a passing Gate A1.

- [ ] **Step 1: Write the failing boundary tests**

Append to `backend/evals/test_a1_boundary.py`. Also add `import ast` to the imports:

```python
def _first_party_imports(path: Path) -> set[str]:
    """Top-level package names this module imports."""
    names: set[str] = set()
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_core_never_imports_accounts() -> None:
    """The dependency runs one way: accounts may read core, never the reverse."""
    backend_dir = Path(__file__).resolve().parents[1]
    core_dir = backend_dir / "core"
    offenders = [
        str(path.relative_to(backend_dir))
        for path in sorted(core_dir.rglob("*.py"))
        if "accounts" in _first_party_imports(path)
    ]

    assert offenders == [], f"core/ must not import accounts/: {offenders}"


def test_accounts_never_imports_agents_or_api() -> None:
    """Accounts stores JSON snapshots, so it needs no pipeline types."""
    backend_dir = Path(__file__).resolve().parents[1]
    accounts_dir = backend_dir / "accounts"
    offenders = [
        str(path.relative_to(backend_dir))
        for path in sorted(accounts_dir.rglob("*.py"))
        if {"agents", "api"} & _first_party_imports(path)
    ]

    assert offenders == [], f"accounts/ must not import agents/ or api/: {offenders}"
```

- [ ] **Step 2: Run the boundary tests**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_boundary.py -v`
Expected: PASS (5 tests). If either new test fails, fix the offending import rather than the test — these encode the repo boundary rules from `CLAUDE.md`.

- [ ] **Step 3: Ignore the local accounts database**

Run: `git check-ignore -v backend/accounts/accounts.sqlite; grep -rn "sqlite" .gitignore backend/.gitignore 2>/dev/null`

If `git check-ignore` reports nothing, add `backend/accounts/accounts.sqlite` to whichever `.gitignore` already covers `tripwise.sqlite`, matching that entry's path style.

- [ ] **Step 4: Run the full A1 suite**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py evals/test_a1_store.py evals/test_a1_projection.py evals/test_a1_boundary.py -v`
Expected: PASS — 19 + 28 + 6 + 5 = 58 tests.

- [ ] **Step 5: Run the full backend regression**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: the 97 pre-existing tests still pass, plus the 58 new ones. **No pre-existing test may change or be edited.** If a golden value moved, this work overreached — stop and investigate rather than adjusting the expectation.

- [ ] **Step 6: Strict type check across the whole backend**

Run: `cd backend && .venv/bin/python -m mypy --strict core/ accounts/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py`
Expected: `Success` — the previous 35 source files plus the 5 new `accounts/` modules.

- [ ] **Step 7: Lint**

Run: `cd backend && .venv/bin/python -m ruff check accounts/ evals/test_a1_models.py evals/test_a1_store.py evals/test_a1_projection.py evals/test_a1_boundary.py`
Expected: `All checks passed!`

- [ ] **Step 8: Log the deviations**

Append a new section to `DEVIATIONS.md`, after the existing `## Frontend design handover and F1 Phase 0 (design freeze)` section, using the established six-column table format:

```markdown
## A1 — Accounts persistence layer (builds ahead of spec 17)

| date | doc§ | question | decision | rationale | affected_files |
|---|---|---|---|---|---|
| 2026-07-28 | **SCOPE+ · process** | Every backend milestone so far was spec-first. `docs/specs/17_accounts_and_persistence.md` does not exist. Should `backend/accounts/` be built before it? | **Yes, knowingly, this once.** The human approved building the persistence layer ahead of spec 17 to keep momentum. Spec 17 is still owed and, once written, wins over this code. | The inversion is real and is the thing to revisit if the schema starts drifting. Recording it here means the next session inherits the debt rather than discovering it. | `backend/accounts/`, `docs/superpowers/plans/2026-07-28-accounts-persistence.md` |
| 2026-07-28 | Tier-C · 01 §10 | `core.db.seed_database` opens with `Base.metadata.drop_all(engine)`. Where do account tables live? | Their own `DeclarativeBase` (`AccountsBase`) in their own file (`backend/accounts/accounts.sqlite`). Nothing in `accounts/db.py` ever drops a table. | Sharing core's metadata or DB file would mean a routine re-seed of reference data silently destroys every user account. Physical isolation makes that unrepresentable, and a test proves it. | `backend/accounts/db.py`, `backend/evals/test_a1_boundary.py` |
| 2026-07-28 | Tier-C · 01 §8 | Two wallet entries can name the same points currency. Sum the balances or not? | **Collapse by `max`, never `sum`.** | Cards from one issuer usually share a pooled balance; summing user-entered pool figures would overstate available points and could produce a transfer plan the user cannot fund. Max is the conservative direction and never overstates. | `backend/accounts/projection.py` |
| 2026-07-28 | Tier-C · 03 | Should `TripRevision` hold a typed `FinalReport` or its JSON bytes? | Store the canonical `model_dump_json()` string plus an `ACCOUNTS_SCHEMA_VERSION`. | A saved trip is an immutable snapshot that must keep the provenance and `last_verified` values it was computed with. Re-parsing an old row through a later `FinalReport` would silently coerce or drop fields. Storing bytes also keeps `accounts/` free of any dependency on `agents/`. | `backend/accounts/models.py`, `backend/accounts/store.py` |
| 2026-07-28 | Tier-C · 06 §5 | Milestone tag and test location for this work. | Tag `A1`; tests live in `backend/evals/test_a1_*.py`. | `pyproject.toml` sets `testpaths = ["evals"]`, so every backend test already lives there regardless of whether it is an eval. Following the convention beats renaming the directory. | `backend/evals/test_a1_*.py`, `reports/milestone_a1.md` |
| 2026-07-28 | **SCOPE+** | Should the system suggest opening a *new* card for a trip, since joining bonuses are usually the largest offers and must be earned within ~90 days of approval? | **Not built here.** This plan persists `WalletEntry.opened_on` only, which is the field such a feature would need. The recommendation logic itself needs its own spec: eligibility rules, issuer application cooling-off periods, minimum-spend thresholds, and a hard line against anything resembling financial advice. | Real product value, but it is a new recommendation surface with regulatory sensitivity, not a persistence concern. Default answer to unspecced features is no until specced. | `backend/accounts/models.py` |
```

- [ ] **Step 9: Write the gate report**

Create `reports/milestone_a1.md` following the structure of `reports/milestone_3.md`. It must record, with the actual numbers from Steps 4–7:

- What A1 delivers: `backend/accounts/` — models, isolated schema, `AccountStore` write boundary, `UserWallet` projection, export/delete.
- The exact commands run and their results: A1 test count, full-regression count, mypy source-file count, ruff result.
- The invariants proven by test: no forbidden field on any model; `extra="forbid"` rejects a smuggled PAN; `core/` does not import `accounts/`; `accounts/` does not import `agents/` or `api/`; re-seeding the KB leaves accounts tables intact; revisions are append-only and never mutated; the wallet projection is order-independent and does not double-count pooled balances.
- What A1 explicitly does not deliver: auth, credentials, sessions, HTTP endpoints, and any use of `opened_on`.
- The outstanding debt: spec 17 is still owed.

- [ ] **Step 10: Commit**

```bash
git add backend/evals/test_a1_boundary.py DEVIATIONS.md reports/milestone_a1.md .gitignore
git commit -m "chore(accounts): Gate A1 — boundary tests, deviations log, milestone report"
```

---

## Verification (whole-plan)

Run after Task 10. All four must hold:

1. **A1 suite green:**
   `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py evals/test_a1_store.py evals/test_a1_projection.py evals/test_a1_boundary.py -v` → 58 passing.
2. **No regression, no edited expectations:**
   `cd backend && .venv/bin/python -m pytest` → the 97 pre-existing tests still pass. Then `git diff main --stat -- backend/evals/golden/` must be **empty** — no golden value changed.
3. **Strict typing clean:**
   `cd backend && .venv/bin/python -m mypy --strict core/ accounts/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py` → `Success`.
4. **The no-secrets invariant is enforced, not asserted:**
   `cd backend && grep -rniE "\b(pan|cvv|cvc|expiry|card_number)\b" accounts/ --include="*.py"` → the only hits are inside `FORBIDDEN_FIELD_NAMES`, docstrings, and validator error messages. No field declaration.
