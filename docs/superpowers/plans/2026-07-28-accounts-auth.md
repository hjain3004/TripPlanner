# Accounts Authentication Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement spec 17 §4 — Argon2id credentials, server-side sessions in an `httpOnly` cookie, CSRF protection, and the four auth endpoints — on top of the `backend/accounts/` write boundary.

**Architecture:** Credentials live in their own `UserCredential` table, never on `User`, so no read path loads a secret. A login mints a high-entropy token, returns it in an `httpOnly`/`Secure`/`SameSite=Lax` cookie, and stores only its SHA-256 in `sessions` — a database leak yields no usable session. Mutating endpoints require a double-submit CSRF token. `backend/core/` is untouched.

**Tech Stack:** Python 3.11, Pydantic v2, SQLAlchemy 2.0, SQLite, `argon2-cffi`, FastAPI, pytest, mypy `--strict`.

## Hard dependency

**`docs/superpowers/plans/2026-07-28-accounts-persistence.md` must be complete and its Gate A1 passing before Task 1 here.** This plan extends `accounts/models.py`, `accounts/db.py`, and `AccountStore`, all of which that plan creates. If `backend/accounts/` does not exist, stop and run that plan first.

Read `docs/specs/17_accounts_and_persistence.md` §4 before starting. It is authoritative; this plan implements it.

## Global Constraints

- **Never store a raw session token or a plaintext password.** The DB holds an Argon2id hash and a SHA-256 token hash. Nothing else.
- **Never use `localStorage` or `sessionStorage`** (standing repo rule, spec 17 §4). The session cookie must be `httpOnly` — that is the whole point.
- **Login must not be a user-enumeration oracle.** "No such user" and "wrong password" return identical status, identical body, and comparable timing. A dummy hash verification runs even when the user does not exist.
- **`backend/core/` must never import `backend/accounts/`.** The A1 boundary test already enforces this; do not weaken it.
- **Time and identifiers are injected, never ambient.** Every method taking a timestamp takes explicit `now: datetime`; every method minting an id or token accepts an optional caller-supplied value. This is what makes these tests deterministic.
- **Style match:** `from __future__ import annotations`, module docstring, `field_validator` for normalization, `# ---- #` section dividers.
- **Commands:** `cd backend && .venv/bin/python -m …`, matching `reports/milestone_3.md`.
- Tests go in `backend/evals/test_a2_*.py` (`testpaths = ["evals"]`). "A2" is this milestone's tag.

## File Structure

| File | Responsibility |
|---|---|
| `backend/accounts/passwords.py` | Argon2id hash/verify + the dummy-verify used for timing uniformity. No I/O, no DB. |
| `backend/accounts/models.py` (modify) | Append `UserCredential`, `Session`. |
| `backend/accounts/db.py` (modify) | Append `UserCredentialRow`, `SessionRow`. |
| `backend/accounts/store.py` (modify) | Append credential and session methods; extend `delete_user`. |
| `backend/api/auth.py` | Cookie/CSRF helpers and the `current_user` dependency. |
| `backend/api/main.py` (modify) | The four auth endpoints. |
| `backend/pyproject.toml` (modify) | Add `argon2-cffi`. |
| `backend/evals/test_a2_passwords.py` | Hashing and timing-uniformity. |
| `backend/evals/test_a2_store.py` | Credential and session store methods. |
| `backend/evals/test_a2_api.py` | Endpoints, cookie flags, CSRF. |

## Out of scope

Password reset / email delivery, third-party OAuth or social login (spec 17 §7 — requires human approval), MFA, rate limiting beyond per-account lockout, and any frontend work. `POST /plan` stays anonymous in this plan; wiring saved trips to a session is a later change.

---

### Task 1: Argon2id password hashing

**Files:**
- Create: `backend/accounts/passwords.py`
- Modify: `backend/pyproject.toml` (add `"argon2-cffi>=23.1"` to `[project] dependencies`)
- Test: `backend/evals/test_a2_passwords.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `hash_password(plaintext: str) -> str`, `verify_password(plaintext: str, stored_hash: str) -> bool`, `dummy_verify(plaintext: str) -> None`, `ALGORITHM: str`.

**Why `dummy_verify` exists:** if login skips hashing when the user is absent, the response comes back measurably faster and the endpoint leaks which emails are registered. `dummy_verify` burns the same work against a fixed hash so both paths cost the same.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a2_passwords.py`:

```python
from __future__ import annotations

import pytest

from accounts.passwords import (
    ALGORITHM,
    dummy_verify,
    hash_password,
    verify_password,
)


def test_hash_is_argon2id_and_not_the_plaintext() -> None:
    stored = hash_password("correct horse battery staple")

    assert ALGORITHM == "argon2id"
    assert stored.startswith("$argon2id$")
    assert "correct horse battery staple" not in stored


def test_same_password_hashes_differently_each_time() -> None:
    assert hash_password("hunter2hunter2") != hash_password("hunter2hunter2")


def test_verify_accepts_the_right_password() -> None:
    assert verify_password("hunter2hunter2", hash_password("hunter2hunter2")) is True


def test_verify_rejects_the_wrong_password() -> None:
    assert verify_password("hunter3hunter3", hash_password("hunter2hunter2")) is False


def test_verify_rejects_a_malformed_hash_without_raising() -> None:
    assert verify_password("hunter2hunter2", "not-a-hash") is False


def test_dummy_verify_returns_none_and_does_not_raise() -> None:
    assert dummy_verify("anything") is None


def test_empty_password_is_rejected() -> None:
    with pytest.raises(ValueError):
        hash_password("")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_passwords.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'accounts.passwords'`

- [ ] **Step 3: Install the dependency**

Add `"argon2-cffi>=23.1",` to the `dependencies` list in `backend/pyproject.toml`, then:

Run: `cd backend && .venv/bin/python -m pip install "argon2-cffi>=23.1"`

- [ ] **Step 4: Write minimal implementation**

Create `backend/accounts/passwords.py`:

```python
"""Argon2id password hashing (spec 17 §4).

Never MD5, SHA-1, plain SHA-256, or bcrypt without tuned cost. The returned
string encodes salt and parameters, so no separate salt column is needed.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

ALGORITHM = "argon2id"

_hasher = PasswordHasher()

# A hash of a value no user can have. Verifying against it costs the same as a
# real verification, which is what keeps login timing uniform when the account
# does not exist — see dummy_verify.
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing-uniformity")


def hash_password(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("password must not be empty")
    return _hasher.hash(plaintext)


def verify_password(plaintext: str, stored_hash: str) -> bool:
    """False on mismatch AND on a malformed stored hash. Never raises."""
    try:
        return _hasher.verify(stored_hash, plaintext)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def dummy_verify(plaintext: str) -> None:
    """Burn a verification against a fixed hash. Call when the user is absent."""
    try:
        _hasher.verify(_DUMMY_HASH, plaintext)
    except (VerifyMismatchError, VerificationError, ValueError):
        pass
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_passwords.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Type check and commit**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`
Expected: `Success`

```bash
git add backend/accounts/passwords.py backend/evals/test_a2_passwords.py backend/pyproject.toml
git commit -m "feat(auth): Argon2id password hashing with timing-uniform dummy verify"
```

---

### Task 2: UserCredential and Session models

**Files:**
- Modify: `backend/accounts/models.py` (append a section)
- Test: `backend/evals/test_a2_store.py` (create; model tests first)

**Interfaces:**
- Consumes: `AccountModel`, `FORBIDDEN_FIELD_NAMES` (persistence plan Task 1).
- Produces: `UserCredential(user_id, password_hash, algorithm, updated_at, failed_attempts, locked_until)` and `Session(id, user_id, token_hash, created_at, last_seen_at, expires_at, revoked_at)`, plus `Session.is_valid_at(now) -> bool`.

**Note on `FORBIDDEN_FIELD_NAMES`:** it contains `password` but deliberately not `password_hash`. `UserCredential.password_hash` is correct and must pass the A1 invariant test unchanged. Do not add `password_hash` to the forbidden set.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a2_store.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from accounts.models import FORBIDDEN_FIELD_NAMES, Session, UserCredential

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)


def _session(**overrides: object) -> Session:
    kwargs: dict[str, object] = {
        "id": "s1",
        "user_id": "u1",
        "token_hash": "a" * 64,
        "created_at": NOW,
        "last_seen_at": NOW,
        "expires_at": NOW + timedelta(days=14),
    }
    kwargs.update(overrides)
    return Session(**kwargs)  # type: ignore[arg-type]


def test_credential_stores_a_hash_not_a_password() -> None:
    cred = UserCredential(
        user_id="u1",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$abc$def",
        updated_at=NOW,
    )

    assert cred.algorithm == "argon2id"
    assert cred.failed_attempts == 0
    assert cred.locked_until is None


def test_credential_rejects_a_plaintext_password_field() -> None:
    with pytest.raises(ValidationError):
        UserCredential(
            user_id="u1",
            password_hash="$argon2id$x",
            updated_at=NOW,
            password="hunter2",
        )


def test_password_hash_is_not_a_forbidden_field_name() -> None:
    """password is forbidden forever; password_hash is the correct thing to store."""
    assert "password" in FORBIDDEN_FIELD_NAMES
    assert "password_hash" not in FORBIDDEN_FIELD_NAMES
    for field_name in UserCredential.model_fields:
        assert field_name.lower() not in FORBIDDEN_FIELD_NAMES


def test_session_rejects_a_token_hash_that_is_not_sha256_hex() -> None:
    with pytest.raises(ValidationError):
        _session(token_hash="tooshort")


def test_session_is_valid_before_expiry() -> None:
    assert _session().is_valid_at(NOW + timedelta(days=1)) is True


def test_session_is_invalid_at_and_after_expiry() -> None:
    session = _session()

    assert session.is_valid_at(session.expires_at) is False
    assert session.is_valid_at(session.expires_at + timedelta(seconds=1)) is False


def test_revoked_session_is_invalid_even_before_expiry() -> None:
    session = _session(revoked_at=NOW)

    assert session.is_valid_at(NOW + timedelta(days=1)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'UserCredential' from 'accounts.models'`

- [ ] **Step 3: Write minimal implementation**

Append to `backend/accounts/models.py`:

```python
# --------------------------------------------------------------------------- #
# 5. Credentials and sessions (spec 17 §4)                                      #
# --------------------------------------------------------------------------- #


class UserCredential(AccountModel):
    """Secrets live here, never on ``User``, so a read path never loads one."""

    user_id: str
    password_hash: str                      # Argon2id; encodes salt and params
    algorithm: Literal["argon2id"] = "argon2id"
    updated_at: datetime
    failed_attempts: int = Field(default=0, ge=0)
    locked_until: datetime | None = None


class Session(AccountModel):
    """A server-side session. ``token_hash`` only — the raw token is NEVER stored."""

    id: str
    user_id: str
    token_hash: str                         # SHA-256 hex of the cookie token
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None

    @field_validator("token_hash")
    @classmethod
    def check_token_hash(cls, value: str) -> str:
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("token_hash must be 64 lowercase hex characters (SHA-256)")
        return value

    def is_valid_at(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_store.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Confirm the A1 invariant still holds**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_models.py -v`
Expected: PASS, unchanged. If `test_no_account_model_declares_a_forbidden_field` now fails, `password_hash` was wrongly added to the forbidden set — revert that, not the model.

- [ ] **Step 6: Commit**

```bash
git add backend/accounts/models.py backend/evals/test_a2_store.py
git commit -m "feat(auth): UserCredential and Session models"
```

---

### Task 3: Credential and session tables

**Files:**
- Modify: `backend/accounts/db.py` (append two row classes)
- Test: `backend/evals/test_a1_boundary.py` (extend the table-set assertions)

**Interfaces:**
- Consumes: `AccountsBase` (persistence plan Task 4).
- Produces: `UserCredentialRow` (`user_credentials`, PK `user_id`) and `SessionRow` (`sessions`, PK `id`, `token_hash` unique+indexed, `user_id` indexed, `expires_at` indexed).

**`token_hash` is `unique=True` and indexed** because every authenticated request looks a session up by it. That is the hottest path in the API.

- [ ] **Step 1: Update the test**

In `backend/evals/test_a1_boundary.py`, extend the `ACCOUNTS_TABLES` constant:

```python
ACCOUNTS_TABLES = {
    "users",
    "user_profiles",
    "wallet_entries",
    "saved_trips",
    "trip_revisions",
    "user_credentials",
    "sessions",
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_boundary.py -v`
Expected: FAIL — the metadata and created-table sets lack `user_credentials` and `sessions`.

- [ ] **Step 3: Write minimal implementation**

Append to `backend/accounts/db.py`:

```python
class UserCredentialRow(AccountsBase):
    __tablename__ = "user_credentials"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class SessionRow(AccountsBase):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)
    expires_at: Mapped[str] = mapped_column(index=True)  # ISO datetime, for sweeping
    payload: Mapped[str] = mapped_column(Text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a1_boundary.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Type check and commit**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`

```bash
git add backend/accounts/db.py backend/evals/test_a1_boundary.py
git commit -m "feat(auth): credential and session tables"
```

---

### Task 4: AccountStore credential methods

**Files:**
- Modify: `backend/accounts/store.py` (append a credentials section)
- Test: `backend/evals/test_a2_store.py` (append)

**Interfaces:**
- Consumes: `AccountStore`, `UnknownUserError` (persistence Task 5); `passwords` (Task 1); `UserCredential` (Task 2); `UserCredentialRow` (Task 3).
- Produces: `AccountStore.set_password(self, user_id: str, plaintext: str, *, now: datetime) -> None`; `AccountStore.authenticate(self, email: str, plaintext: str, *, now: datetime) -> User | None`; `AccountStore.get_credential(self, user_id: str) -> UserCredential | None`. Module-level `MAX_FAILED_ATTEMPTS = 10`, `LOCKOUT_DURATION = timedelta(minutes=15)`.

**`authenticate` returns `User | None` — never a reason.** A caller that *can* distinguish absent-user from wrong-password from locked-out will eventually leak that distinction into a response body. It cannot here.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a2_store.py` (add `from accounts.store import AccountStore` to the imports):

```python
def _store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="a@example.com", now=NOW, user_id="u1")
    store.set_password("u1", "correct horse battery", now=NOW)
    return store


def test_authenticate_accepts_the_right_password(tmp_path: Path) -> None:
    store = _store(tmp_path)

    user = store.authenticate("a@example.com", "correct horse battery", now=NOW)

    assert user is not None
    assert user.id == "u1"


def test_authenticate_rejects_the_wrong_password(tmp_path: Path) -> None:
    assert _store(tmp_path).authenticate("a@example.com", "wrong", now=NOW) is None


def test_authenticate_returns_none_for_an_unknown_email(tmp_path: Path) -> None:
    assert _store(tmp_path).authenticate("ghost@example.com", "x", now=NOW) is None


def test_authenticate_is_case_insensitive_on_email(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.authenticate("A@EXAMPLE.COM", "correct horse battery", now=NOW) is not None


def test_stored_hash_is_never_the_plaintext(tmp_path: Path) -> None:
    cred = _store(tmp_path).get_credential("u1")

    assert cred is not None
    assert "correct horse battery" not in cred.password_hash
    assert cred.password_hash.startswith("$argon2id$")


def test_failed_attempts_accumulate_then_lock(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for _ in range(10):
        store.authenticate("a@example.com", "wrong", now=NOW)

    cred = store.get_credential("u1")
    assert cred is not None
    assert cred.failed_attempts >= 10
    assert cred.locked_until is not None
    # The correct password is refused while locked.
    assert store.authenticate("a@example.com", "correct horse battery", now=NOW) is None


def test_lock_expires_and_the_right_password_works_again(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for _ in range(10):
        store.authenticate("a@example.com", "wrong", now=NOW)

    later = NOW + timedelta(minutes=16)
    assert store.authenticate("a@example.com", "correct horse battery", now=later) is not None


def test_success_resets_the_failure_counter(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.authenticate("a@example.com", "wrong", now=NOW)
    store.authenticate("a@example.com", "correct horse battery", now=NOW)

    cred = store.get_credential("u1")
    assert cred is not None
    assert cred.failed_attempts == 0


def test_set_password_rejects_an_unknown_user(tmp_path: Path) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")

    with pytest.raises(ValueError):
        store.set_password("ghost", "some passphrase", now=NOW)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_store.py -v`
Expected: FAIL — `AttributeError: 'AccountStore' object has no attribute 'set_password'`

- [ ] **Step 3: Write minimal implementation**

In `backend/accounts/store.py`: add `timedelta` to the datetime import, add `UserCredentialRow` to the `accounts.db` import, add `UserCredential` to the `accounts.models` import, and add `from accounts import passwords`. Add at module level next to the exceptions:

```python
MAX_FAILED_ATTEMPTS = 10
LOCKOUT_DURATION = timedelta(minutes=15)
```

Then append inside `AccountStore`:

```python
    # -- credentials -------------------------------------------------------- #

    def set_password(self, user_id: str, plaintext: str, *, now: datetime) -> None:
        """Set or replace a user's password. Resets lockout state."""
        credential = UserCredential(
            user_id=user_id,
            password_hash=passwords.hash_password(plaintext),
            updated_at=now,
            failed_attempts=0,
            locked_until=None,
        )
        with Session(self._engine) as session:
            self._require_user(session, user_id)
            row = session.get(UserCredentialRow, user_id)
            if row is None:
                session.add(
                    UserCredentialRow(
                        user_id=user_id, payload=credential.model_dump_json()
                    )
                )
            else:
                row.payload = credential.model_dump_json()
            session.commit()

    def get_credential(self, user_id: str) -> UserCredential | None:
        with Session(self._engine) as session:
            row = session.get(UserCredentialRow, user_id)
            return (
                None
                if row is None
                else UserCredential.model_validate_json(row.payload)
            )

    def authenticate(
        self, email: str, plaintext: str, *, now: datetime
    ) -> User | None:
        """Return the user on success, ``None`` otherwise — never a reason.

        Timing is uniform: when the user or credential is missing, or the account
        is locked, we still burn one Argon2 verification against a fixed dummy
        hash, so the caller cannot distinguish the cases by response time.
        """
        user = self.get_user_by_email(email)
        if user is None:
            passwords.dummy_verify(plaintext)
            return None

        with Session(self._engine) as session:
            row = session.get(UserCredentialRow, user.id)
            if row is None:
                passwords.dummy_verify(plaintext)
                return None

            credential = UserCredential.model_validate_json(row.payload)
            if credential.locked_until is not None and now < credential.locked_until:
                passwords.dummy_verify(plaintext)
                return None

            ok = passwords.verify_password(plaintext, credential.password_hash)
            if ok:
                updated = credential.model_copy(
                    update={"failed_attempts": 0, "locked_until": None}
                )
            else:
                attempts = credential.failed_attempts + 1
                locked = (
                    now + LOCKOUT_DURATION if attempts >= MAX_FAILED_ATTEMPTS else None
                )
                updated = credential.model_copy(
                    update={"failed_attempts": attempts, "locked_until": locked}
                )
            row.payload = updated.model_dump_json()
            session.commit()

        return user if ok else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_store.py -v`
Expected: PASS (16 tests)

- [ ] **Step 5: Type check and commit**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`

```bash
git add backend/accounts/store.py backend/evals/test_a2_store.py
git commit -m "feat(auth): credential storage, authentication, and lockout"
```

---

### Task 5: AccountStore session methods

**Files:**
- Modify: `backend/accounts/store.py` (append a sessions section; extend `delete_user`)
- Test: `backend/evals/test_a2_store.py` (append)

**Interfaces:**
- Consumes: `SessionRow` (Task 3), `Session` model (Task 2).
- Produces: `create_session(self, user_id, *, now, ttl=SESSION_TTL, session_id=None, token=None) -> tuple[Session, str]` (returns the record **and the raw token** — the only moment it exists); `session_for_token(self, token, *, now) -> Session | None`; `revoke_session(self, session_id, *, now) -> None`; `revoke_all_sessions(self, user_id, *, now, except_session_id=None) -> int`; `sweep_expired_sessions(self, *, now) -> int`. Module-level `SESSION_TTL = timedelta(days=14)` and `hash_token(token: str) -> str`.

⚠ **`delete_user` (persistence Task 9) must also delete `user_credentials` and `sessions`.** Extend its cascade here — an account deletion that leaves live sessions behind is a real defect.

- [ ] **Step 1: Write the failing test**

Append to `backend/evals/test_a2_store.py`:

```python
def test_create_session_returns_a_token_that_is_not_stored(tmp_path: Path) -> None:
    store = _store(tmp_path)

    record, token = store.create_session("u1", now=NOW, session_id="s1")

    assert len(token) >= 32
    assert token != record.token_hash
    assert token not in record.model_dump_json()


def test_session_for_token_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, token = store.create_session("u1", now=NOW, session_id="s1")

    found = store.session_for_token(token, now=NOW)

    assert found is not None
    assert found.user_id == "u1"


def test_session_for_token_rejects_a_wrong_token(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_session("u1", now=NOW, session_id="s1")

    assert store.session_for_token("not-the-token", now=NOW) is None


def test_expired_session_is_not_returned(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, token = store.create_session(
        "u1", now=NOW, ttl=timedelta(hours=1), session_id="s1"
    )

    assert store.session_for_token(token, now=NOW + timedelta(hours=2)) is None


def test_revoked_session_is_not_returned(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, token = store.create_session("u1", now=NOW, session_id="s1")

    store.revoke_session("s1", now=NOW)

    assert store.session_for_token(token, now=NOW) is None


def test_revoke_all_sessions_can_spare_the_current_one(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, keep = store.create_session("u1", now=NOW, session_id="s1")
    _, drop = store.create_session("u1", now=NOW, session_id="s2")

    revoked = store.revoke_all_sessions("u1", now=NOW, except_session_id="s1")

    assert revoked == 1
    assert store.session_for_token(keep, now=NOW) is not None
    assert store.session_for_token(drop, now=NOW) is None


def test_sweep_removes_only_expired_sessions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create_session("u1", now=NOW, ttl=timedelta(hours=1), session_id="old")
    _, live = store.create_session(
        "u1", now=NOW, ttl=timedelta(days=30), session_id="new"
    )

    removed = store.sweep_expired_sessions(now=NOW + timedelta(days=1))

    assert removed == 1
    assert store.session_for_token(live, now=NOW + timedelta(days=1)) is not None


def test_delete_user_also_removes_credentials_and_sessions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _, token = store.create_session("u1", now=NOW, session_id="s1")

    store.delete_user("u1")

    assert store.get_credential("u1") is None
    assert store.session_for_token(token, now=NOW) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_store.py -v`
Expected: FAIL — `AttributeError: 'AccountStore' object has no attribute 'create_session'`

- [ ] **Step 3: Write minimal implementation**

In `backend/accounts/store.py`: add `import hashlib` and `import secrets`, add `SessionRow` to the `accounts.db` import, and import the model aliased — `from accounts.models import Session as SessionRecord` — because `Session` is already SQLAlchemy's in this module. Add at module level:

```python
SESSION_TTL = timedelta(days=14)


def hash_token(token: str) -> str:
    """SHA-256 hex of a session token. The raw token is never persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
```

Then append inside `AccountStore`:

```python
    # -- sessions ----------------------------------------------------------- #

    def create_session(
        self,
        user_id: str,
        *,
        now: datetime,
        ttl: timedelta = SESSION_TTL,
        session_id: str | None = None,
        token: str | None = None,
    ) -> tuple[SessionRecord, str]:
        """Mint a session. Returns the record and the raw token.

        This is the only moment the raw token exists in the process; the caller
        puts it in an httpOnly cookie and drops it. Only its hash is stored.
        """
        raw = token or secrets.token_urlsafe(32)
        record = SessionRecord(
            id=session_id or uuid4().hex,
            user_id=user_id,
            token_hash=hash_token(raw),
            created_at=now,
            last_seen_at=now,
            expires_at=now + ttl,
        )
        with Session(self._engine) as session:
            self._require_user(session, user_id)
            session.add(
                SessionRow(
                    id=record.id,
                    user_id=record.user_id,
                    token_hash=record.token_hash,
                    expires_at=record.expires_at.isoformat(),
                    payload=record.model_dump_json(),
                )
            )
            session.commit()
        return record, raw

    def session_for_token(self, token: str, *, now: datetime) -> SessionRecord | None:
        """The live session for a token, or None if absent, expired, or revoked."""
        with Session(self._engine) as session:
            row = session.scalar(
                select(SessionRow).where(SessionRow.token_hash == hash_token(token))
            )
            if row is None:
                return None
            record = SessionRecord.model_validate_json(row.payload)
            if not record.is_valid_at(now):
                return None
            record = record.model_copy(update={"last_seen_at": now})
            row.payload = record.model_dump_json()
            session.commit()
        return record

    def revoke_session(self, session_id: str, *, now: datetime) -> None:
        with Session(self._engine) as session:
            row = session.get(SessionRow, session_id)
            if row is None:
                return
            record = SessionRecord.model_validate_json(row.payload)
            if record.revoked_at is None:
                row.payload = record.model_copy(
                    update={"revoked_at": now}
                ).model_dump_json()
                session.commit()

    def revoke_all_sessions(
        self, user_id: str, *, now: datetime, except_session_id: str | None = None
    ) -> int:
        """Revoke every live session for a user. Returns how many were revoked."""
        revoked = 0
        with Session(self._engine) as session:
            rows = session.scalars(
                select(SessionRow).where(SessionRow.user_id == user_id)
            ).all()
            for row in rows:
                if row.id == except_session_id:
                    continue
                record = SessionRecord.model_validate_json(row.payload)
                if record.revoked_at is None:
                    row.payload = record.model_copy(
                        update={"revoked_at": now}
                    ).model_dump_json()
                    revoked += 1
            session.commit()
        return revoked

    def sweep_expired_sessions(self, *, now: datetime) -> int:
        """Hard-delete sessions past expiry. Returns how many were removed."""
        with Session(self._engine) as session:
            result = session.execute(
                delete(SessionRow).where(SessionRow.expires_at <= now.isoformat())
            )
            session.commit()
        return int(result.rowcount or 0)
```

Finally, extend `delete_user`'s cascade — add these two statements before the `UserRow` delete:

```python
            session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))
            session.execute(
                delete(UserCredentialRow).where(UserCredentialRow.user_id == user_id)
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_store.py evals/test_a1_store.py -v`
Expected: PASS — A2 store 24 tests, A1 store 28 tests unchanged.

- [ ] **Step 5: Type check and commit**

Run: `cd backend && .venv/bin/python -m mypy --strict accounts/`

```bash
git add backend/accounts/store.py backend/evals/test_a2_store.py
git commit -m "feat(auth): server-side sessions with hashed tokens and revocation"
```

---

### Task 6: Cookie, CSRF, and the current-user dependency

**Files:**
- Create: `backend/api/auth.py`
- Test: `backend/evals/test_a2_api.py`

**Interfaces:**
- Consumes: `AccountStore` and its session methods (Task 5).
- Produces: `SESSION_COOKIE = "tp_session"`, `CSRF_COOKIE = "tp_csrf"`, `CSRF_HEADER = "X-CSRF-Token"`; `get_store()`, `now_utc()`, `new_csrf_token()`, `set_session_cookies(response, token, csrf_token, expires_at)`, `clear_session_cookies(response)`, `require_csrf(request)`, `current_user(request, store) -> User`.

**Why double-submit CSRF:** the session cookie is `httpOnly`, so JS cannot read it — but the browser still attaches it to cross-site requests. The CSRF cookie is deliberately **not** `httpOnly`, so the app's own JS can read it and echo it in a header. An attacker's page can cause the request but cannot read the cookie to set the header. `SameSite=Lax` is a second layer, not a substitute.

- [ ] **Step 1: Write the failing test**

Create `backend/evals/test_a2_api.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from accounts.store import AccountStore
from api.auth import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, get_store
from api.main import app

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery"


def _client(tmp_path: Path) -> TestClient:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app)


def _register(client: TestClient) -> None:
    resp = client.post(
        "/auth/register", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 201, resp.text


def _login(client: TestClient) -> None:
    resp = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


def test_login_sets_an_httponly_session_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)

    resp = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )

    assert resp.status_code == 200
    raw = resp.headers["set-cookie"]
    assert SESSION_COOKIE in raw
    assert "HttpOnly" in raw
    assert "SameSite=Lax" in raw
    app.dependency_overrides.clear()


def test_csrf_cookie_is_readable_by_js(tmp_path: Path) -> None:
    """The CSRF cookie must NOT be httpOnly — the app's JS has to echo it."""
    client = _client(tmp_path)
    _register(client)
    _login(client)

    assert client.cookies.get(CSRF_COOKIE) is not None
    app.dependency_overrides.clear()


def test_session_token_is_never_returned_in_the_body(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)

    resp = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )

    assert "token" not in resp.text.lower()
    app.dependency_overrides.clear()


def test_me_requires_a_session(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/auth/me").status_code == 401
    app.dependency_overrides.clear()


def test_me_returns_the_user_when_authenticated(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    _login(client)

    resp = client.get("/auth/me")

    assert resp.status_code == 200
    assert resp.json()["email"] == "a@example.com"
    assert "password_hash" not in resp.text
    app.dependency_overrides.clear()


def test_logout_without_csrf_header_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    _login(client)

    assert client.post("/auth/logout").status_code == 403
    app.dependency_overrides.clear()


def test_logout_with_csrf_header_revokes_the_session(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    _login(client)
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf is not None

    resp = client.post("/auth/logout", headers={CSRF_HEADER: csrf})

    assert resp.status_code == 204
    assert client.get("/auth/me").status_code == 401
    app.dependency_overrides.clear()


def test_wrong_password_and_unknown_email_are_indistinguishable(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _register(client)

    wrong = client.post(
        "/auth/login", json={"email": "a@example.com", "password": "nope nope nope"}
    )
    absent = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope nope nope"}
    )

    assert wrong.status_code == absent.status_code == 401
    assert wrong.json() == absent.json()
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api.auth'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/api/auth.py`:

```python
"""Cookie, CSRF, and current-user plumbing for the auth endpoints (spec 17 §4).

The session cookie is httpOnly so no script can read it. The CSRF cookie is
deliberately NOT httpOnly: the app's own JS must read it and echo it in a
header, which an attacker's page cannot do. SameSite=Lax is a second layer,
not a substitute for the token.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response

from accounts.models import User
from accounts.store import AccountStore

SESSION_COOKIE = "tp_session"
CSRF_COOKIE = "tp_csrf"
CSRF_HEADER = "X-CSRF-Token"


def get_store() -> AccountStore:
    return AccountStore.open()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def set_session_cookies(
    response: Response, token: str, csrf_token: str, expires_at: datetime
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
        expires=expires_at,
    )
    # Not httpOnly by design — the SPA reads this and echoes it in CSRF_HEADER.
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        httponly=False,
        secure=True,
        samesite="lax",
        path="/",
        expires=expires_at,
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def require_csrf(request: Request) -> None:
    """Double-submit check. Call on every state-changing request."""
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        raise HTTPException(status_code=403, detail="CSRF check failed")


def current_user(
    request: Request, store: AccountStore = Depends(get_store)
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = store.session_for_token(token, now=now_utc())
    if session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = store.get_user(session.user_id)
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
```

- [ ] **Step 4: Commit (the API tests still fail — endpoints come next)**

```bash
git add backend/api/auth.py backend/evals/test_a2_api.py
git commit -m "feat(auth): cookie, CSRF, and current-user dependency"
```

---

### Task 7: The auth endpoints

**Files:**
- Modify: `backend/api/main.py` (append four routes)
- Test: `backend/evals/test_a2_api.py` (written in Task 6)

**Interfaces:**
- Consumes: everything from Tasks 4–6.
- Produces: `POST /auth/register` (201), `POST /auth/login` (200), `POST /auth/logout` (204, CSRF-protected), `GET /auth/me` (200 or 401). All return `UserOut{id, email, status}`.

**No token is ever returned in a response body.** The session lives in the cookie. A token in JSON invites a client to stash it in `localStorage`, which spec 17 §4 forbids.

- [ ] **Step 1: Run the Task 6 tests to confirm they fail**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_api.py -v`
Expected: FAIL — 404 on `/auth/register`.

- [ ] **Step 2: Write minimal implementation**

Add to the imports at the top of `backend/api/main.py`:

```python
from fastapi import Request, Response
from pydantic import BaseModel, Field

from accounts.models import User
from accounts.store import AccountStore, DuplicateEmailError
from api.auth import (
    SESSION_COOKIE,
    clear_session_cookies,
    current_user,
    get_store,
    new_csrf_token,
    now_utc,
    require_csrf,
    set_session_cookies,
)
```

Then append:

```python
class CredentialsIn(BaseModel):
    email: str
    password: str = Field(min_length=12)


class UserOut(BaseModel):
    id: str
    email: str
    status: str


@app.post("/auth/register", status_code=201, response_model=UserOut)
def register(
    body: CredentialsIn, store: AccountStore = Depends(get_store)
) -> UserOut:
    now = now_utc()
    try:
        user = store.create_user(email=body.email, now=now)
    except DuplicateEmailError:
        # Deliberately uninformative: registration must not confirm which
        # emails already exist.
        raise HTTPException(status_code=409, detail="Registration failed")
    store.set_password(user.id, body.password, now=now)
    return UserOut(id=user.id, email=user.email, status=user.status)


@app.post("/auth/login", response_model=UserOut)
def login(
    body: CredentialsIn,
    response: Response,
    store: AccountStore = Depends(get_store),
) -> UserOut:
    now = now_utc()
    user = store.authenticate(body.email, body.password, now=now)
    if user is None:
        # One message for absent-user, wrong-password and locked-out alike.
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session, raw_token = store.create_session(user.id, now=now)
    set_session_cookies(response, raw_token, new_csrf_token(), session.expires_at)
    return UserOut(id=user.id, email=user.email, status=user.status)


@app.post("/auth/logout", status_code=204)
def logout(
    request: Request, store: AccountStore = Depends(get_store)
) -> Response:
    require_csrf(request)
    now = now_utc()
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        session = store.session_for_token(token, now=now)
        if session is not None:
            store.revoke_session(session.id, now=now)
    response = Response(status_code=204)
    clear_session_cookies(response)
    return response


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, status=user.status)
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_api.py -v`
Expected: PASS (8 tests)

- [ ] **Step 4: Confirm nothing pre-existing broke**

Run: `cd backend && .venv/bin/python -m pytest evals/test_m2_api.py -v`
Expected: PASS, unchanged. `/health` and `/plan` are unaffected — auth is purely additive here.

- [ ] **Step 5: Commit**

```bash
git add backend/api/main.py backend/evals/test_a2_api.py
git commit -m "feat(auth): register, login, logout, and me endpoints"
```

---

### Task 8: Gate A2

**Files:**
- Modify: `backend/evals/test_a2_api.py` (append the secret-leak sweep)
- Create: `reports/milestone_a2.md`
- Modify: `DEVIATIONS.md` (new `## A2` section)

- [ ] **Step 1: Add the secret-leak sweep**

Append to `backend/evals/test_a2_api.py`:

```python
def test_password_change_revokes_other_sessions(tmp_path: Path) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    user = store.create_user(email="a@example.com", now=NOW, user_id="u1")
    store.set_password(user.id, PASSWORD, now=NOW)
    _, old_token = store.create_session("u1", now=NOW, session_id="s1")

    store.set_password("u1", "a brand new passphrase", now=NOW)
    store.revoke_all_sessions("u1", now=NOW)

    assert store.session_for_token(old_token, now=NOW) is None


def test_no_endpoint_ever_returns_a_hash_or_token(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    login = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    me_resp = client.get("/auth/me")

    for resp in (login, me_resp):
        assert "$argon2id$" not in resp.text
        assert "password_hash" not in resp.text
        assert "token_hash" not in resp.text
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run the full A2 suite**

Run: `cd backend && .venv/bin/python -m pytest evals/test_a2_passwords.py evals/test_a2_store.py evals/test_a2_api.py -v`
Expected: PASS — 7 + 24 + 10 = 41 tests.

- [ ] **Step 3: Full regression**

Run: `cd backend && .venv/bin/python -m pytest`
Expected: the 100 pre-A1 tests, plus A1's 58, plus A2's 41. **No pre-existing test edited.**

- [ ] **Step 4: Strict typing**

Run: `cd backend && .venv/bin/python -m mypy --strict core/ accounts/ agents/ api/ evals/judge.py evals/itinerary_fixtures.py evals/itinerary_eval.py evals/report.py`
Expected: `Success`

- [ ] **Step 5: Grep for leaked secrets**

Run: `cd backend && grep -rn "localStorage\|sessionStorage" api/ accounts/ --include="*.py"`
Expected: no hits.

Run: `cd backend && grep -rniE "\bpassword\b" api/ --include="*.py" | grep -v "password_hash\|CredentialsIn\|body.password\|set_password\|#"`
Expected: no hit that logs, stores, or returns a plaintext password.

- [ ] **Step 6: Log deviations**

Add a `## A2 — Accounts authentication` section to `DEVIATIONS.md` recording at minimum: the double-submit CSRF choice and why `SameSite=Lax` alone was judged insufficient; `MAX_FAILED_ATTEMPTS=10` and `LOCKOUT_DURATION=15min` (Tier C, tunable); the decision that `authenticate` returns `User | None` with no reason; `409` on duplicate registration being deliberately uninformative; and the `min_length=12` password floor.

- [ ] **Step 7: Write the gate report**

Create `reports/milestone_a2.md` in the shape of `reports/milestone_3.md`, recording the commands run, the counts from Steps 2–4, and the invariants proven by test: no plaintext password stored or returned; no raw session token persisted; session cookie `httpOnly`+`Secure`+`SameSite=Lax`; CSRF cookie readable by JS by design; CSRF absent → 403; logout revokes server-side; login is not a user-enumeration oracle; `delete_user` removes credentials and sessions.

- [ ] **Step 8: Commit**

```bash
git add backend/evals/test_a2_api.py DEVIATIONS.md reports/milestone_a2.md
git commit -m "chore(auth): Gate A2 — secret-leak sweep, deviations log, milestone report"
```

---

## Verification (whole-plan)

1. `cd backend && .venv/bin/python -m pytest` — all green, no pre-existing test edited.
2. `cd backend && .venv/bin/python -m mypy --strict core/ accounts/ agents/ api/ …` — `Success`.
3. `cd backend && grep -rn "localStorage\|sessionStorage" api/ accounts/` — **no hits**, ever.
4. Inspect a stored session row: its payload carries a 64-character hex `token_hash` and no raw token.
5. `git diff main -- backend/evals/golden/` — empty. Auth touches no kernel behaviour.
