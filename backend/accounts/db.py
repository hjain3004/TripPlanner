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

import logging
from pathlib import Path
from typing import cast

from sqlalchemy import Engine, Index, Table, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.runtime_paths import state_path

logger = logging.getLogger(__name__)

ACCOUNTS_DB_PATH = state_path("accounts.sqlite", Path(__file__).parent / "accounts.sqlite")


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


class TripMutationEventRow(AccountsBase):
    """Durable idempotency record for one saved-trip mutation (A4).

    Same shape and reasoning as ``WalletMutationEventRow``: the composite primary
    key makes event identity ``(user_id, client_event_id)``, so two users may reuse
    a textual id and a genuine concurrent double-submit hits the key instead of
    applying twice. ``result_payload`` is the original outcome, so a replay answers
    identically. ``trip_id`` is nullable because a delete event outlives its trip.
    """

    __tablename__ = "trip_mutation_events"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    client_event_id: Mapped[str] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(index=True)
    operation: Mapped[str] = mapped_column()
    trip_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    result_payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str | None] = mapped_column(index=True, nullable=True)


class PostPlanWorkspaceRow(AccountsBase):
    """Current working state of a planning session (one row per session, CAS-updated)."""

    __tablename__ = "post_plan_workspaces"
    session_id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    version: Mapped[int] = mapped_column()
    current_result_id: Mapped[str] = mapped_column()
    expires_at: Mapped[str] = mapped_column(index=True)  # ISO datetime, for sweeping
    saved_trip_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    payload: Mapped[str] = mapped_column(Text)


class PostPlanResultRow(AccountsBase):
    """An accepted report. Insert-only: the store exposes no update or delete for it."""

    __tablename__ = "post_plan_results"
    result_id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    session_id: Mapped[str] = mapped_column(index=True)
    report_sha256: Mapped[str] = mapped_column()
    payload: Mapped[str] = mapped_column(Text)


class PostPlanOperationRow(AccountsBase):
    """A reservation / terminal outcome. ``(user_id, event_key)`` is the idempotency key."""

    __tablename__ = "post_plan_operations"
    user_id: Mapped[str] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(primary_key=True)
    operation_id: Mapped[str] = mapped_column(unique=True, index=True)
    session_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str] = mapped_column(index=True)
    status: Mapped[str] = mapped_column(index=True)
    proposal_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    decision: Mapped[str | None] = mapped_column(nullable=True)
    action_kind: Mapped[str | None] = mapped_column(nullable=True)
    interpreter_calls: Mapped[int] = mapped_column(default=0)
    planner_calls: Mapped[int] = mapped_column(default=0)
    provider_calls: Mapped[int] = mapped_column(default=0)
    payload: Mapped[str] = mapped_column(Text)


class SavedTripRow(AccountsBase):
    __tablename__ = "saved_trips"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(index=True)
    created_at: Mapped[str] = mapped_column(index=True)  # ISO datetime string
    payload: Mapped[str] = mapped_column(Text)


class TripRevisionRow(AccountsBase):
    __tablename__ = "trip_revisions"
    # One revision number per trip, enforced by the database. The store also
    # serialises numbering with BEGIN IMMEDIATE; this index is the backstop that
    # makes a duplicate number impossible rather than merely unlikely.
    __table_args__ = (
        Index("uq_trip_revisions_trip_revision", "trip_id", "revision", unique=True),
    )
    id: Mapped[str] = mapped_column(primary_key=True)
    trip_id: Mapped[str] = mapped_column(index=True)
    revision: Mapped[int] = mapped_column(index=True)
    payload: Mapped[str] = mapped_column(Text)


def create_accounts_engine(db_path: Path = ACCOUNTS_DB_PATH) -> Engine:
    """Open (creating if needed) the accounts database. Never drops."""
    engine = create_engine(f"sqlite:///{db_path}")
    AccountsBase.metadata.create_all(engine)
    _migrate_existing_accounts_schema(engine)
    return engine


def _migrate_existing_accounts_schema(engine: Engine) -> None:
    """Apply additive account-schema changes that ``create_all`` cannot apply.

    SQLAlchemy's ``create_all`` creates missing tables but deliberately does not
    alter an existing table. A3 added ``wallet_entries.version`` after account
    databases could already exist, so add that column explicitly with a
    non-null default. The idempotency table is already created by ``create_all``
    when absent; this hook keeps its indexes in place for both old and new DBs.
    """
    columns = {column["name"] for column in inspect(engine).get_columns("wallet_entries")}
    if "version" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE wallet_entries "
                    "ADD COLUMN version INTEGER NOT NULL DEFAULT 1"
                )
            )
    wallet_table = cast(Table, WalletEntryRow.__table__)
    for index in wallet_table.indexes:
        index.create(bind=engine, checkfirst=True)
    _ensure_unique_revision_index(engine)


def _ensure_unique_revision_index(engine: Engine) -> None:
    """Add the A4 ``(trip_id, revision)`` unique index to a pre-A4 database.

    Additive and idempotent. Rows are never rewritten: if an old database already
    holds duplicate numbers (possible only through the pre-A4 race), the index is
    skipped with a warning rather than failing startup or renumbering a stored
    revision. Numbering stays serialised by the store either way.
    """
    # ``get_store`` opens the database on every request, so the common case (index
    # already present) must cost one catalogue lookup, not a scan of every revision.
    existing = {index["name"] for index in inspect(engine).get_indexes("trip_revisions")}
    if "uq_trip_revisions_trip_revision" in existing:
        return
    with engine.begin() as connection:
        duplicates = connection.execute(
            text(
                "SELECT 1 FROM trip_revisions GROUP BY trip_id, revision "
                "HAVING COUNT(*) > 1 LIMIT 1"
            )
        ).first()
        if duplicates is not None:
            logger.warning(
                "trip_revisions holds duplicate (trip_id, revision) rows; "
                "the unique revision index was not created"
            )
            return
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_trip_revisions_trip_revision "
                "ON trip_revisions (trip_id, revision)"
            )
        )


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
