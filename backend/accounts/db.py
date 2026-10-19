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
    # Optimistic-concurrency version. ``server_default`` is what makes adding
    # this column migration-safe: a row written before A3 reads back as 1
    # rather than NULL, and no existing account data is rewritten.
    version: Mapped[int] = mapped_column(index=True, server_default="1", default=1)


class WalletMutationEventRow(AccountsBase):
    """Durable idempotency record for one wallet mutation.

    Owned by ``accounts`` rather than folded into a planning session: a create
    has no pre-existing row to hold a processed-event list, wallet events target
    different entries rather than one aggregate, and a replay must be able to
    return the *original outcome* and detect a conflicting reuse — neither of
    which a bare list of ids can express.

    The composite primary key is what makes event identity ``(user_id,
    client_event_id)``, so two users can reuse the same textual id without
    colliding, and a genuine concurrent double-submit hits the key instead of
    applying twice.
    """

    __tablename__ = "wallet_mutation_events"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    client_event_id: Mapped[str] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(index=True)
    operation: Mapped[str] = mapped_column()
    entry_id: Mapped[str | None] = mapped_column(nullable=True)
    result_payload: Mapped[str] = mapped_column(Text)
    # Advisory only, and nullable: this package never reads an ambient clock,
    # so it is set only when the caller supplies `now`. Event identity is
    # (user_id, client_event_id) plus the fingerprint, never the timestamp.
    created_at: Mapped[str | None] = mapped_column(index=True, nullable=True)


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


class TravelPreferenceRow(AccountsBase):
    __tablename__ = "travel_preferences"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class PlanningSessionRow(AccountsBase):
    __tablename__ = "planning_sessions"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column()
    version: Mapped[int] = mapped_column()
    updated_at: Mapped[str] = mapped_column(index=True)  # ISO datetime string
    expires_at: Mapped[str] = mapped_column(index=True)  # ISO datetime string
    saved_trip_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    payload: Mapped[str] = mapped_column(Text)
