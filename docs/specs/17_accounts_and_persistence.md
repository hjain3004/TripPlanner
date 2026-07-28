# 17 — Accounts & Persistence

**Do not build during the Kernel MVP.** Users are ephemeral there by design (01 §8): a `TripSpec` carries the wallet, nothing is stored, and `backend/core/` is a read facade over seeded reference data. This spec introduces the first user-owned mutable state in the system, and the whole design problem is doing that without compromising the kernel's determinism or its read-only posture.

**Note on order.** `docs/superpowers/plans/2026-07-28-accounts-persistence.md` was written before this spec, covering the persistence half (entities + write boundary). That inversion is deliberate, human-approved, and logged as SCOPE+ in `DEVIATIONS.md`. **Where this spec and that plan disagree, this spec wins** and the plan is revised. One known refinement is marked ⚠ below.

## 1. The boundary

```
backend/core/       read-only facade over seeded reference data. Imports nothing from accounts/.
backend/accounts/   the ONLY module permitted to write user data.
backend/agents/     reads a projection; never writes.
backend/api/        maps HTTP to accounts/ calls.
```

`backend/core/` must never import `backend/accounts/`. This mirrors the existing `gateway/` rule and is what keeps the optimizer deterministic and testable: the kernel's inputs are values passed in, never state it reaches out for. **Enforce with a test that walks `core/`'s AST for `accounts` imports**, not with convention.

`core.db.seed_database()` opens with `Base.metadata.drop_all(engine)`. Accounts therefore get their own `DeclarativeBase` **and their own database file**, so re-seeding reference data cannot destroy user data. This is not a preference; sharing either would make routine maintenance destructive.

## 2. What is stored

| Entity | Holds | Notes |
|---|---|---|
| `User` | id, email, created_at, status | No credentials. See §4. |
| `UserProfile` | display name, home country, home currency, origin city | One row per user. |
| `WalletEntry` | card_id, nickname, last4?, statement_day?, opened_on?, points_balances | Product reference. See §3. |
| `SavedTrip` | trip input + canonical `TripSpec` JSON | Immutable. See §5. |
| `TripRevision` | one computed `FinalReport` JSON snapshot | Append-only. See §5. |

**`UserWallet` is not stored.** It already exists (`core.models`, 01 §8) as the kernel's request-time input and is **built by projection from `WalletEntry` rows** at request time. Do not create a second stored model that duplicates it — a duplicated wallet is a wallet that can disagree with itself.

Projection rule: duplicate points currencies across entries collapse by **max, not sum**. Cards from one issuer typically share a pooled balance, so summing user-entered pool figures overstates available points and can produce a transfer plan the user cannot fund (07). Max never overstates.

## 3. What is never stored — schema invariant

**Never: PAN, expiry date, CVV/CVC, card PIN, bank or net-banking credentials, loyalty-account passwords.**

The optimizer resolves earn rules by product slug (`Card.id`), so a real card number buys the system nothing while pulling a non-commercial student project into PCI-DSS scope. This is reinforced by the standing non-negotiable that the system never executes transfers or bookings — it has no use for an instrument because it never transacts.

State it as a schema invariant, not a convention. Two mechanisms, both required:

1. Every stored account model sets `extra="forbid"`, so `WalletEntry(..., pan="…")` raises rather than silently ignoring the field.
2. A `FORBIDDEN_FIELD_NAMES` set and a test asserting no account model declares any of them, so a future developer *adding* such a field fails the suite.

`last4` is a human disambiguator ("which Infinia is this?") and is optional. Four digits carry no payment capability. `opened_on` exists solely so spec 18 can reason about welcome-bonus windows; nothing in this layer interprets it.

## 4. Authentication and sessions

⚠ **Refines the persistence plan**, which put a `password_hash` column on `User`. Credentials live in a **separate table**, so loading a user never loads a secret and a `User` can be returned from any read path without redaction.

```python
class UserCredential(BaseModel):
    user_id: str
    password_hash: str            # Argon2id; encodes salt and parameters
    algorithm: Literal["argon2id"]
    updated_at: datetime
    failed_attempts: int
    locked_until: datetime | None
```

**Approach: email + password, hashed with Argon2id.** Chosen because it needs no external service and no credentials — third-party OAuth or a hosted auth provider would require human approval under the ambiguity protocol and adds a secret-management burden this project does not need. Never MD5, SHA-1, plain SHA-256, or bcrypt without tuned cost.

```python
class Session(BaseModel):
    id: str
    user_id: str
    token_hash: str               # SHA-256 of the cookie token; the token itself is NEVER stored
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
```

**Server-side sessions, transported in a cookie that is `httpOnly`, `Secure`, `SameSite=Lax`, with a hard `expires_at`.** The DB stores only a hash of the token, so a database leak does not hand an attacker live sessions — the same reasoning as password hashing.

**Never use `localStorage` or `sessionStorage`** (standing repo rule). A token in `localStorage` is readable by any script on the page; `httpOnly` is precisely the property that rules out that class of theft. This is why bearer-token-in-JS is rejected here despite being the more common SPA pattern.

Cookie sessions require **CSRF protection** on every state-changing request — double-submit token, or `SameSite=Strict` on mutations. Do not skip this; it is the tax for choosing cookies, and choosing cookies is correct.

Required behaviours: logout revokes server-side (`revoked_at`), not just client-side; a password change revokes all other sessions; failed-attempt lockout via `failed_attempts`/`locked_until`; login responses are uniform in timing and message between "no such user" and "wrong password", so the endpoint is not a user-enumeration oracle.

## 5. Saved trips are immutable

A stored plan keeps the provenance and `last_verified` values it was computed with. **Re-running a saved trip appends a `TripRevision`; it never mutates one.** The store exposes no update or delete method for a revision.

Payloads are stored as **canonical JSON strings** (`model_dump_json()`) plus a schema version, not as typed `TripSpec`/`FinalReport` fields. Re-reading an old row through a *later* version of those models would silently coerce, default, or drop fields — the snapshot would quietly change meaning, which defeats the entire point of keeping one. Storing bytes also keeps `accounts/` independent of `agents/`.

A revision's provenance is a record of what was true when it was computed. The UI must render a saved plan's age and never imply its numbers are current — a six-month-old plan showing a since-expired offer is a correctness failure, not a stale cache.

## 6. Privacy and retention

Under the active `student_noncommercial` profile (16): **no PII is sold, shared, sent to third-party processors, or used for analytics.** The only external request at plan time remains the LLM API, and trip prompts must not carry email, display name, or `last4`.

PII held: email, display name, home country/currency, origin city, card product references with optional `last4`/statement day/open date, self-reported points balances, and saved trips (destinations, dates, budgets) — which are, in aggregate, a travel history. Treat them as such.

Required operations, both belonging to the storage layer rather than to an endpoint:

- **Export** — return everything held about one user as one structured document.
- **Delete** — hard cascade (revisions → trips → wallet entries → profile → credentials → sessions → user), idempotent. No soft-delete tombstone retaining PII.

Retention: sessions expire per `expires_at` and expired rows are swept; saved trips persist until the user deletes them or the account; credentials die with the account. If the project is ever monetized, this section is re-reviewed under spec 16's commercial profile — the student profile is not a permanent exemption.

## 7. Non-goals

No bank-account linking, no transaction import, no open-banking or aggregator connection, no statement parsing. No storing anything that could authorize a payment. No third-party OAuth, social login, or hosted auth provider without explicit human approval. No password recovery via security questions. No account data in the LLM prompt path. No autonomous writes of financial facts — the human-approval boundary (05) is unaffected by users having accounts.
