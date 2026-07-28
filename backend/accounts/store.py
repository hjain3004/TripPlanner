"""``AccountStore`` — the only write boundary for user-owned data (spec 17, pending).

``backend/core/`` is a read facade and must never import this module. Everything
that mutates user state passes through the typed methods here, which keeps the
optimizer deterministic and keeps user writes out of the kernel's path.

Determinism: no method reads the clock or a random seed implicitly. Timestamps
arrive as an explicit ``now`` argument and identifiers may be supplied by the
caller — the same injection style the pipeline uses for ``booking_date``.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from accounts.db import (
    ACCOUNTS_DB_PATH,
    UserProfileRow,
    UserRow,
    WalletEntryRow,
    create_accounts_engine,
)
from accounts.models import User, UserProfile, WalletEntry


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
