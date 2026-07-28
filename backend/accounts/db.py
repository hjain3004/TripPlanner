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
