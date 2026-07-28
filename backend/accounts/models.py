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

import json
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
