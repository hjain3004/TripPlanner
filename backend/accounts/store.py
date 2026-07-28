"""``AccountStore`` — the only write boundary for user-owned data (spec 17, pending).

``backend/core/`` is a read facade and must never import this module. Everything
that mutates user state passes through the typed methods here, which keeps the
optimizer deterministic and keeps user writes out of the kernel's path.

Determinism: no method reads the clock or a random seed implicitly. Timestamps
arrive as an explicit ``now`` argument and identifiers may be supplied by the
caller — the same injection style the pipeline uses for ``booking_date``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from accounts.db import (
    ACCOUNTS_DB_PATH,
    SavedTripRow,
    TripRevisionRow,
    UserCredentialRow,
    UserProfileRow,
    UserRow,
    WalletEntryRow,
    create_accounts_engine,
)
from accounts.models import (
    SavedTrip,
    TripRevision,
    User,
    UserCredential,
    UserExport,
    UserProfile,
    WalletEntry,
)
from accounts import passwords


class DuplicateEmailError(ValueError):
    """Raised when an email is already registered to another user."""


class UnknownUserError(ValueError):
    """Raised when an operation names a user id that does not exist."""


class UnknownTripError(ValueError):
    """Raised when an operation names a saved trip id that does not exist."""


MAX_FAILED_ATTEMPTS = 10
LOCKOUT_DURATION = timedelta(minutes=15)


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
