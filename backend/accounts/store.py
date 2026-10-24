"""``AccountStore`` — the only write boundary for user-owned data (spec 17, pending).

``backend/core/`` is a read facade and must never import this module. Everything
that mutates user state passes through the typed methods here, which keeps the
optimizer deterministic and keeps user writes out of the kernel's path.

Determinism: no method reads the clock or a random seed implicitly. Timestamps
arrive as an explicit ``now`` argument and identifiers may be supplied by the
caller — the same injection style the pipeline uses for ``booking_date``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sqlalchemy import Engine, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from accounts import passwords
from accounts.db import (
    ACCOUNTS_DB_PATH,
    PlanningSessionRow,
    SavedTripRow,
    SessionRow,
    TravelPreferenceRow,
    TripMutationEventRow,
    TripRevisionRow,
    UserCredentialRow,
    UserProfileRow,
    UserRow,
    WalletEntryRow,
    WalletMutationEventRow,
    create_accounts_engine,
)
from accounts.models import (
    MAX_REPORT_BYTES,
    MAX_REVISIONS_PER_TRIP,
    MAX_SAVED_TRIPS,
    PlanningSessionSnapshot,
    SavedTrip,
    TravelPreferenceProfile,
    TripMutationEvent,
    TripRevision,
    User,
    UserCredential,
    UserExport,
    UserProfile,
    WalletEntry,
    WalletMutationEvent,
)
from accounts.models import (
    Session as SessionRecord,
)


class DuplicateEmailError(ValueError):
    """Raised when an email is already registered to another user."""


class UnknownUserError(ValueError):
    """Raised when an operation names a user id that does not exist."""


class UnknownTripError(ValueError):
    """Raised when no saved trip with that id is owned by this user.

    Deliberately indistinguishable from "the trip exists but belongs to someone
    else", and the message carries no owner information, so the API can never be
    used to probe for another user's trip ids.
    """


class TripRevisionConflictError(ValueError):
    """Raised when a revision number could not be allocated after one retry."""


class TripIdempotencyConflictError(ValueError):
    """Raised when a client event id is reused for a materially different trip request."""


class TripLimitReachedError(ValueError):
    """Raised when a user already holds the maximum number of saved trips."""


class RevisionLimitReachedError(ValueError):
    """Raised when a trip already holds the maximum number of revisions."""


class ReportTooLargeError(ValueError):
    """Raised when a report to be stored exceeds the per-revision size bound."""


TripOperation = Literal["save", "append_revision", "delete", "rerun_complete"]


def trip_event_fingerprint(
    operation: str,
    *,
    trip_id: str | None = None,
    fields: dict[str, object] | None = None,
) -> str:
    """Canonical identity of a saved-trip mutation request.

    Callers that know the *intent* of the request (the API, which sees a session id
    and a title rather than the report it will compute) pass their own fingerprint,
    because a retry of the same intent legitimately arrives with a different report.
    The clock and server-generated ids are never part of it.
    """
    canonical = json.dumps(
        {"operation": operation, "trip_id": trip_id, "fields": fields or {}},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SavedTripResult:
    """A newly saved trip together with its first revision."""

    trip: SavedTrip
    revision: TripRevision


class PlanningSessionExistsError(ValueError):
    """Raised when a caller tries to create an existing planning-session ID."""


class StalePlanningSessionError(ValueError):
    """Raised when a compare-and-swap session version no longer matches."""


class WalletEntryNotFoundError(ValueError):
    """Raised when no wallet entry with that id is owned by this user.

    Deliberately indistinguishable from "the entry exists but belongs to
    someone else": the API must never disclose another user's entry ids.
    """


class StaleWalletEntryError(ValueError):
    """Raised when a compare-and-swap wallet version no longer matches."""


class WalletIdempotencyConflictError(ValueError):
    """Raised when a client event id is reused for a materially different request.

    A genuine retry resends the same intent and replays. Reusing the same id for
    a different operation, target, precondition or payload is a client bug, and
    silently applying it would be a second unintended mutation.
    """


def wallet_event_fingerprint(
    operation: str,
    *,
    entry_id: str | None = None,
    expected_version: int | None = None,
    fields: dict[str, object] | None = None,
) -> str:
    """Canonical identity of a wallet mutation request.

    Deliberately excludes the caller's clock and any server-generated entry id:
    a retry of the same intent arrives with a later ``now`` and would generate a
    different uuid, and folding either in would make every honest retry look
    like a conflict. For a create, ``entry_id`` is excluded for that reason; for
    an update or delete it is part of the target and is included.
    """
    canonical = json.dumps(
        {
            "operation": operation,
            "entry_id": entry_id,
            "expected_version": expected_version,
            "fields": fields or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _Unset:
    """Sentinel distinguishing "field omitted" from "field set to null".

    ``update_wallet_entry`` is a patch: an omitted ``last4`` must be left as it
    is, while an explicit ``None`` clears it. ``None`` alone cannot express both.
    """

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"


UNSET = _Unset()


MAX_FAILED_ATTEMPTS = 10
LOCKOUT_DURATION = timedelta(minutes=15)
SESSION_TTL = timedelta(days=14)


def hash_token(token: str) -> str:
    """SHA-256 hex of a session token. The raw token is never persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


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

    # -- travel preferences (consent-based, CP1) ----------------------------- #

    def put_travel_preferences(
        self, preferences: TravelPreferenceProfile
    ) -> TravelPreferenceProfile:
        """Insert or replace the single travel-preferences row for a user.

        Callers submit a fully validated replacement profile — this store
        never merges partial updates itself.
        """
        with Session(self._engine) as session:
            self._require_user(session, preferences.user_id)
            row = session.get(TravelPreferenceRow, preferences.user_id)
            if row is None:
                session.add(
                    TravelPreferenceRow(
                        user_id=preferences.user_id,
                        payload=preferences.model_dump_json(),
                    )
                )
            else:
                row.payload = preferences.model_dump_json()
            session.commit()
        return preferences

    def get_travel_preferences(self, user_id: str) -> TravelPreferenceProfile | None:
        with Session(self._engine) as session:
            row = session.get(TravelPreferenceRow, user_id)
            return (
                None
                if row is None
                else TravelPreferenceProfile.model_validate_json(row.payload)
            )

    # -- planning sessions (opaque snapshots, CP1) --------------------------- #

    def create_planning_session_snapshot(
        self, snapshot: PlanningSessionSnapshot
    ) -> PlanningSessionSnapshot:
        """Insert a brand-new planning-session snapshot. Never overwrites."""
        with Session(self._engine) as session:
            self._require_user(session, snapshot.user_id)
            if session.get(PlanningSessionRow, snapshot.id) is not None:
                raise PlanningSessionExistsError(
                    f"planning session already exists: {snapshot.id}"
                )
            session.add(
                PlanningSessionRow(
                    id=snapshot.id,
                    user_id=snapshot.user_id,
                    status=snapshot.status,
                    version=snapshot.version,
                    updated_at=snapshot.updated_at.isoformat(),
                    expires_at=snapshot.expires_at.isoformat(),
                    saved_trip_id=snapshot.saved_trip_id,
                    payload=snapshot.model_dump_json(),
                )
            )
            session.commit()
        return snapshot

    def get_planning_session_snapshot(
        self, *, user_id: str, session_id: str
    ) -> PlanningSessionSnapshot | None:
        """The snapshot for one session, scoped to its owner. ``None`` otherwise.

        A session id that exists but belongs to a different user is
        indistinguishable from a session that does not exist — ownership
        scoping never leaks existence.
        """
        with Session(self._engine) as session:
            row = session.get(PlanningSessionRow, session_id)
            if row is None or row.user_id != user_id:
                return None
            return PlanningSessionSnapshot.model_validate_json(row.payload)

    def put_planning_session_snapshot(
        self, snapshot: PlanningSessionSnapshot, *, expected_version: int
    ) -> PlanningSessionSnapshot:
        """Atomic compare-and-swap update. Raises rather than overwriting stale data.

        Issues exactly one SQLAlchemy ``update`` whose ``WHERE`` matches the
        session id, the caller-asserted owner, and the expected current
        version. A mismatch on any of the three (wrong id, wrong owner, or a
        version someone else already advanced) yields ``rowcount == 0`` and
        this never retries or falls back to an overwrite — the caller must
        re-read and resubmit.
        """
        if snapshot.version != expected_version + 1:
            raise ValueError(
                f"snapshot.version ({snapshot.version}) must equal "
                f"expected_version + 1 ({expected_version + 1})"
            )
        with Session(self._engine) as session:
            result = session.execute(
                update(PlanningSessionRow)
                .where(
                    PlanningSessionRow.id == snapshot.id,
                    PlanningSessionRow.user_id == snapshot.user_id,
                    PlanningSessionRow.version == expected_version,
                )
                .values(
                    status=snapshot.status,
                    version=snapshot.version,
                    updated_at=snapshot.updated_at.isoformat(),
                    expires_at=snapshot.expires_at.isoformat(),
                    saved_trip_id=snapshot.saved_trip_id,
                    payload=snapshot.model_dump_json(),
                )
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                session.rollback()
                raise StalePlanningSessionError(
                    f"planning session {snapshot.id} was not at version "
                    f"{expected_version} for user {snapshot.user_id}"
                )
            session.commit()
        return snapshot

    def planning_session_snapshots(self, user_id: str) -> list[PlanningSessionSnapshot]:
        """Every planning-session snapshot for a user, ordered by ``(updated_at, id)``."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(PlanningSessionRow).where(PlanningSessionRow.user_id == user_id)
            ).all()
            snapshots = [
                PlanningSessionSnapshot.model_validate_json(r.payload) for r in rows
            ]
        return sorted(snapshots, key=lambda s: (s.updated_at, s.id))

    def delete_expired_planning_sessions(self, *, now: datetime) -> int:
        """Hard-delete abandoned sessions past expiry. Returns how many were removed.

        A session attached to a saved trip (``saved_trip_id`` set) is
        retained with that trip rather than swept as abandoned, regardless
        of its own ``expires_at``.
        """
        with Session(self._engine) as session:
            result = session.execute(
                delete(PlanningSessionRow).where(
                    PlanningSessionRow.expires_at < now.isoformat(),
                    PlanningSessionRow.saved_trip_id.is_(None),
                )
            )
            session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    # -- wallet ------------------------------------------------------------- #

    # -- wallet mutation idempotency ---------------------------------------- #

    def _replay_wallet_event(
        self,
        session: Session,
        *,
        user_id: str,
        client_event_id: str,
        fingerprint: str,
    ) -> str | None:
        """Return the original result payload for a replayed event, else ``None``.

        Raises on a reused id whose request fingerprint differs, because
        applying it would be a second, unintended mutation.
        """
        row = session.get(WalletMutationEventRow, (user_id, client_event_id))
        if row is None:
            return None
        if row.fingerprint != fingerprint:
            raise WalletIdempotencyConflictError(
                f"client event {client_event_id} was already used for a "
                f"materially different wallet request"
            )
        return row.result_payload

    def _record_wallet_event(
        self,
        session: Session,
        *,
        user_id: str,
        client_event_id: str,
        fingerprint: str,
        operation: str,
        entry_id: str | None,
        result_payload: str,
        now: datetime | None,
    ) -> None:
        """Stage the event alongside the mutation so both commit together.

        Staging rather than committing separately is what keeps the promise that
        a failed or stale operation is never recorded as a success: if the
        mutation raises, this row never reaches the database.
        """
        session.add(
            WalletMutationEventRow(
                user_id=user_id,
                client_event_id=client_event_id,
                fingerprint=fingerprint,
                operation=operation,
                entry_id=entry_id,
                result_payload=result_payload,
                created_at=now.isoformat() if now is not None else None,
            )
        )

    def _replay_after_race(
        self, *, user_id: str, client_event_id: str, fingerprint: str
    ) -> str:
        """Resolve a composite-key collision from two concurrent identical requests.

        The primary key, not the earlier read, is the real guard. When it fires
        the other request already committed, so re-read and replay its result
        rather than letting an IntegrityError reach the caller.
        """
        with Session(self._engine) as session:
            payload = self._replay_wallet_event(
                session,
                user_id=user_id,
                client_event_id=client_event_id,
                fingerprint=fingerprint,
            )
        if payload is None:  # pragma: no cover - key fired but row absent
            raise WalletIdempotencyConflictError(
                f"client event {client_event_id} collided but could not be replayed"
            )
        return payload

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
        client_event_id: str | None = None,
    ) -> WalletEntry:
        fingerprint = wallet_event_fingerprint(
            "create",
            fields={
                "card_id": card_id,
                "nickname": nickname,
                "last4": last4,
                "statement_day": statement_day,
                "opened_on": opened_on,
                "points_balances": dict(points_balances or {}),
            },
        )
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
            if client_event_id is not None:
                replayed = self._replay_wallet_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                )
                if replayed is not None:
                    return WalletEntry.model_validate_json(replayed)
            session.add(
                WalletEntryRow(
                    id=entry.id,
                    user_id=entry.user_id,
                    card_id=entry.card_id,
                    payload=entry.model_dump_json(),
                    version=entry.version,
                )
            )
            if client_event_id is not None:
                self._record_wallet_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                    operation="create",
                    entry_id=entry.id,
                    result_payload=entry.model_dump_json(),
                    now=now,
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if client_event_id is None:
                    raise
                return WalletEntry.model_validate_json(
                    self._replay_after_race(
                        user_id=user_id,
                        client_event_id=client_event_id,
                        fingerprint=fingerprint,
                    )
                )
        return entry

    def set_points_balances(
        self, *, user_id: str, entry_id: str, balances: dict[str, int]
    ) -> WalletEntry:
        """Replace (not merge) the stored balance map for one wallet entry.

        Owner-scoped convenience wrapper over ``update_wallet_entry``. It reads
        the current version and immediately writes, so it does **not** give the
        caller compare-and-swap protection against a concurrent edit; the API
        deliberately uses ``update_wallet_entry`` with an explicit
        ``expected_version`` instead. Kept for internal callers and tests.
        """
        with Session(self._engine) as session:
            row = session.scalar(
                select(WalletEntryRow).where(
                    WalletEntryRow.id == entry_id,
                    WalletEntryRow.user_id == user_id,
                )
            )
            if row is None:
                raise WalletEntryNotFoundError(
                    f"no wallet entry {entry_id} for this user"
                )
            current_version = WalletEntry.model_validate_json(row.payload).version
        return self.update_wallet_entry(
            user_id=user_id,
            entry_id=entry_id,
            expected_version=current_version,
            points_balances=balances,
        )

    def update_wallet_entry(
        self,
        *,
        user_id: str,
        entry_id: str,
        expected_version: int,
        nickname: str | _Unset = UNSET,
        last4: str | None | _Unset = UNSET,
        statement_day: int | None | _Unset = UNSET,
        opened_on: date | None | _Unset = UNSET,
        points_balances: dict[str, int] | None | _Unset = UNSET,
        client_event_id: str | None = None,
        now: datetime | None = None,
    ) -> WalletEntry:
        """Owner-scoped compare-and-swap patch of the safe metadata fields.

        Mirrors ``put_planning_session_snapshot``: the ``WHERE`` carries the
        entry id, the asserted owner, **and** the expected version, so a wrong
        owner and a stale version both yield ``rowcount == 0`` instead of an
        overwrite. Never retries and never falls back to a blind write — the
        caller must re-read and resubmit.

        ``id``, ``user_id``, ``card_id`` and ``added_at`` are immutable here.
        Omitted fields are left alone; an explicit ``None`` clears a nullable one.
        """
        if expected_version < 1:
            raise ValueError("expected_version must be >= 1")

        changes: dict[str, object] = {}
        if not isinstance(nickname, _Unset):
            changes["nickname"] = nickname
        if not isinstance(last4, _Unset):
            changes["last4"] = last4
        if not isinstance(statement_day, _Unset):
            changes["statement_day"] = statement_day
        if not isinstance(opened_on, _Unset):
            changes["opened_on"] = opened_on
        if not isinstance(points_balances, _Unset):
            changes["points_balances"] = (
                dict(points_balances) if points_balances is not None else {}
            )

        fingerprint = wallet_event_fingerprint(
            "update",
            entry_id=entry_id,
            expected_version=expected_version,
            fields=dict(changes),
        )

        with Session(self._engine) as session:
            # The replay check precedes the existence and version checks on
            # purpose. A retry of an update that already succeeded arrives with
            # the *original* expected_version, which is now stale, and may even
            # target a row since deleted. Checking staleness first would reject
            # exactly the retry idempotency exists to absorb.
            if client_event_id is not None:
                replayed = self._replay_wallet_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                )
                if replayed is not None:
                    return WalletEntry.model_validate_json(replayed)

            current_row = session.scalar(
                select(WalletEntryRow).where(
                    WalletEntryRow.id == entry_id,
                    WalletEntryRow.user_id == user_id,
                )
            )
            if current_row is None:
                raise WalletEntryNotFoundError(
                    f"no wallet entry {entry_id} for this user"
                )

            current = WalletEntry.model_validate_json(current_row.payload)
            if current.version != expected_version:
                raise StaleWalletEntryError(
                    f"wallet entry {entry_id} is at version {current.version}, "
                    f"not {expected_version}"
                )

            candidate = current.model_copy(
                update={**changes, "version": current.version + 1}
            )
            # model_copy skips validators, so round-trip the JSON to re-validate.
            # This raises *before* any write, so a rejected patch cannot advance
            # the version.
            updated = WalletEntry.model_validate_json(candidate.model_dump_json())

            result = session.execute(
                update(WalletEntryRow)
                .where(
                    WalletEntryRow.id == entry_id,
                    WalletEntryRow.user_id == user_id,
                    WalletEntryRow.version == expected_version,
                )
                .values(payload=updated.model_dump_json(), version=updated.version)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                session.rollback()
                raise StaleWalletEntryError(
                    f"wallet entry {entry_id} was not at version {expected_version} "
                    f"for this user"
                )
            if client_event_id is not None:
                self._record_wallet_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                    operation="update",
                    entry_id=entry_id,
                    result_payload=updated.model_dump_json(),
                    now=now,
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if client_event_id is None:
                    raise
                return WalletEntry.model_validate_json(
                    self._replay_after_race(
                        user_id=user_id,
                        client_event_id=client_event_id,
                        fingerprint=fingerprint,
                    )
                )
        return updated

    def remove_wallet_entry(
        self,
        *,
        user_id: str,
        entry_id: str,
        client_event_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Owner-scoped delete. Returns whether a row was actually removed.

        Returns ``False`` both when the entry does not exist and when it belongs
        to a different user — the two are deliberately indistinguishable so the
        API cannot be used to probe for another user's entry ids.

        With a ``client_event_id``, a replay returns the *original* outcome: a
        retried successful delete reports ``True`` again rather than the
        ``False`` a genuine second delete would produce.
        """
        fingerprint = wallet_event_fingerprint("delete", entry_id=entry_id)

        with Session(self._engine) as session:
            if client_event_id is not None:
                replayed = self._replay_wallet_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                )
                if replayed is not None:
                    return bool(json.loads(replayed)["removed"])

            result = session.execute(
                delete(WalletEntryRow).where(
                    WalletEntryRow.id == entry_id,
                    WalletEntryRow.user_id == user_id,
                )
            )
            removed = bool(result.rowcount == 1)  # type: ignore[attr-defined]
            if client_event_id is not None:
                self._record_wallet_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                    operation="delete",
                    entry_id=entry_id,
                    result_payload=json.dumps({"removed": removed}),
                    now=now,
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if client_event_id is None:
                    raise
                return bool(
                    json.loads(
                        self._replay_after_race(
                            user_id=user_id,
                            client_event_id=client_event_id,
                            fingerprint=fingerprint,
                        )
                    )["removed"]
                )
        return removed

    def wallet_mutation_events(self, user_id: str) -> list[WalletMutationEvent]:
        """This user's recorded wallet mutations, ordered by ``client_event_id``.

        Ordered by the event id rather than ``created_at`` because that column is
        nullable advisory metadata (this package takes no ambient clock), so it
        cannot provide a total order.
        """
        with Session(self._engine) as session:
            rows = session.scalars(
                select(WalletMutationEventRow).where(
                    WalletMutationEventRow.user_id == user_id
                )
            ).all()
            events = [
                WalletMutationEvent(
                    user_id=r.user_id,
                    client_event_id=r.client_event_id,
                    operation=r.operation,
                    entry_id=r.entry_id,
                    fingerprint=r.fingerprint,
                    result_payload=r.result_payload,
                    created_at=(
                        datetime.fromisoformat(r.created_at)
                        if r.created_at is not None
                        else None
                    ),
                )
                for r in rows
            ]
        return sorted(events, key=lambda e: e.client_event_id)

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

    # -- saved-trip idempotency ---------------------------------------------- #

    @staticmethod
    def _begin_write(session: Session) -> None:
        """Take SQLite's write lock up front so check-then-write is atomic.

        Replay, limit and numbering decisions all read before they write; under
        deferred locking two writers could both pass the same check. Acquiring the
        lock first makes the second writer wait, then see the first one's rows.
        """
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")

    @staticmethod
    def _replay_trip_event(
        session: Session, *, user_id: str, client_event_id: str, fingerprint: str
    ) -> str | None:
        row = session.get(TripMutationEventRow, (user_id, client_event_id))
        if row is None:
            return None
        if row.fingerprint != fingerprint:
            raise TripIdempotencyConflictError(
                f"client event {client_event_id} was already used for a "
                f"materially different saved-trip request"
            )
        return row.result_payload

    @staticmethod
    def _record_trip_event(
        session: Session,
        *,
        user_id: str,
        client_event_id: str,
        fingerprint: str,
        operation: TripOperation,
        trip_id: str | None,
        result_payload: str,
        now: datetime | None,
    ) -> None:
        session.add(
            TripMutationEventRow(
                user_id=user_id,
                client_event_id=client_event_id,
                fingerprint=fingerprint,
                operation=operation,
                trip_id=trip_id,
                result_payload=result_payload,
                created_at=now.isoformat() if now is not None else None,
            )
        )

    def trip_event_result(
        self, *, user_id: str, client_event_id: str, request_fingerprint: str
    ) -> str | None:
        """The stored outcome of a previously applied event, else ``None``.

        Lets the API recognise an honest retry *before* it applies state checks that
        the original success has since changed (for example "this session is already
        saved"). Raises on a reused id whose fingerprint differs.
        """
        with Session(self._engine) as session:
            return self._replay_trip_event(
                session,
                user_id=user_id,
                client_event_id=client_event_id,
                fingerprint=request_fingerprint,
            )

    def trip_mutation_events(self, user_id: str) -> list[TripMutationEvent]:
        """This user's recorded saved-trip mutations, ordered by ``client_event_id``."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(TripMutationEventRow).where(TripMutationEventRow.user_id == user_id)
            ).all()
            events = [
                TripMutationEvent(
                    user_id=r.user_id,
                    client_event_id=r.client_event_id,
                    operation=r.operation,
                    trip_id=r.trip_id,
                    fingerprint=r.fingerprint,
                    result_payload=r.result_payload,
                    created_at=(
                        datetime.fromisoformat(r.created_at)
                        if r.created_at is not None
                        else None
                    ),
                )
                for r in rows
            ]
        return sorted(events, key=lambda e: e.client_event_id)

    @staticmethod
    def _check_report_size(report_json: str) -> None:
        if len(report_json.encode("utf-8")) > MAX_REPORT_BYTES:
            raise ReportTooLargeError(
                f"report exceeds the {MAX_REPORT_BYTES}-byte storage limit"
            )

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

    def save_trip_with_revision(
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
        trace_id: str,
        report_json: str,
        now: datetime,
        trip_id: str | None = None,
        attach_session: PlanningSessionSnapshot | None = None,
        expected_session_version: int | None = None,
        client_event_id: str | None = None,
        request_fingerprint: str | None = None,
    ) -> SavedTripResult:
        """Create a trip and its first revision, atomically and idempotently.

        One transaction covers the replay check, the size and count limits, the
        trip, revision 1, the optional compare-and-swap attach of the originating
        planning session, and the idempotency record. If the session was advanced by
        someone else the whole save rolls back, so a lost race never leaves a trip
        the session does not point at.
        """
        fingerprint = request_fingerprint or trip_event_fingerprint(
            "save",
            fields={
                "title": title,
                "origin_city": origin_city,
                "destination_city": destination_city,
                "start_date": start_date,
                "end_date": end_date,
                "raw_request": raw_request,
                "trip_spec_json": trip_spec_json,
                "report_sha256": hashlib.sha256(report_json.encode("utf-8")).hexdigest(),
            },
        )
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
        revision = TripRevision(
            id=uuid4().hex,
            trip_id=trip.id,
            revision=1,
            trace_id=trace_id,
            report_json=report_json,
            created_at=now,
        )
        if attach_session is not None:
            if (
                expected_session_version is None
                or attach_session.user_id != user_id
                or attach_session.saved_trip_id != trip.id
                or attach_session.version != expected_session_version + 1
            ):
                raise ValueError("attach_session must point at the new trip and advance by one")
        result_payload = json.dumps(
            {
                "trip": json.loads(trip.model_dump_json()),
                "revision": json.loads(revision.model_dump_json()),
            }
        )

        def replayed(payload: str) -> SavedTripResult:
            data = json.loads(payload)
            return SavedTripResult(
                trip=SavedTrip.model_validate(data["trip"]),
                revision=TripRevision.model_validate(data["revision"]),
            )

        with Session(self._engine) as session:
            self._begin_write(session)
            if client_event_id is not None:
                prior = self._replay_trip_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                )
                if prior is not None:
                    return replayed(prior)
            self._check_report_size(report_json)
            self._require_user(session, user_id)
            held = session.scalar(
                select(func.count())
                .select_from(SavedTripRow)
                .where(SavedTripRow.user_id == user_id)
            )
            if int(held or 0) >= MAX_SAVED_TRIPS:
                raise TripLimitReachedError(
                    f"at most {MAX_SAVED_TRIPS} saved trips are kept per user"
                )
            if attach_session is not None:
                outcome = session.execute(
                    update(PlanningSessionRow)
                    .where(
                        PlanningSessionRow.id == attach_session.id,
                        PlanningSessionRow.user_id == user_id,
                        PlanningSessionRow.version == expected_session_version,
                    )
                    .values(
                        status=attach_session.status,
                        version=attach_session.version,
                        updated_at=attach_session.updated_at.isoformat(),
                        expires_at=attach_session.expires_at.isoformat(),
                        saved_trip_id=attach_session.saved_trip_id,
                        payload=attach_session.model_dump_json(),
                    )
                )
                if outcome.rowcount != 1:  # type: ignore[attr-defined]
                    raise StalePlanningSessionError(
                        f"planning session {attach_session.id} was not at version "
                        f"{expected_session_version} for this user"
                    )
            session.add(
                SavedTripRow(
                    id=trip.id,
                    user_id=trip.user_id,
                    created_at=trip.created_at.isoformat(),
                    payload=trip.model_dump_json(),
                )
            )
            session.add(
                TripRevisionRow(
                    id=revision.id,
                    trip_id=revision.trip_id,
                    revision=revision.revision,
                    payload=revision.model_dump_json(),
                )
            )
            if client_event_id is not None:
                self._record_trip_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                    operation="save",
                    trip_id=trip.id,
                    result_payload=result_payload,
                    now=now,
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if client_event_id is None:
                    raise
                with Session(self._engine) as again:
                    prior = self._replay_trip_event(
                        again,
                        user_id=user_id,
                        client_event_id=client_event_id,
                        fingerprint=fingerprint,
                    )
                if prior is None:
                    raise
                return replayed(prior)
        return SavedTripResult(trip=trip, revision=revision)

    def get_trip(self, user_id: str, trip_id: str) -> SavedTrip:
        """One trip, scoped to its owner. Wrong owner reads as missing."""
        with Session(self._engine) as session:
            row = self._owned_trip_row(session, user_id, trip_id)
            return SavedTrip.model_validate_json(row.payload)

    @staticmethod
    def _owned_trip_row(session: Session, user_id: str, trip_id: str) -> SavedTripRow:
        row = session.scalar(
            select(SavedTripRow).where(
                SavedTripRow.id == trip_id, SavedTripRow.user_id == user_id
            )
        )
        if row is None:
            raise UnknownTripError(f"no saved trip {trip_id} for this user")
        return row

    @staticmethod
    def _highest_revision(session: Session, trip_id: str) -> int:
        highest = session.scalar(
            select(func.max(TripRevisionRow.revision)).where(
                TripRevisionRow.trip_id == trip_id
            )
        )
        return int(highest or 0)

    def add_revision(
        self,
        *,
        user_id: str,
        trip_id: str,
        trace_id: str,
        report_json: str,
        now: datetime,
        revision_id: str | None = None,
        client_event_id: str | None = None,
        request_fingerprint: str | None = None,
        operation: Literal["append_revision", "rerun_complete"] = "append_revision",
    ) -> TripRevision:
        """Append a computed result to a trip this user owns. Never mutates one.

        Saved trips are immutable: re-running a trip produces revision N+1 so the
        provenance and ``last_verified`` values of every earlier run survive intact.

        Everything happens in one ``BEGIN IMMEDIATE`` transaction, in this order:
        replay, size, ownership, revision limit, numbering, insert. Replay comes
        first so a retried append that already succeeded is never rejected by the
        limit it consumed. A second writer waits for the lock instead of computing
        the same ``max + 1``; the unique ``(trip_id, revision)`` index is the
        backstop, retried once and then surfaced as a typed error — a raw driver
        exception never leaves the store.
        """
        fingerprint = request_fingerprint or trip_event_fingerprint(
            operation,
            trip_id=trip_id,
            fields={
                "trace_id": trace_id,
                "report_sha256": hashlib.sha256(report_json.encode("utf-8")).hexdigest(),
            },
        )
        for _attempt in range(2):
            with Session(self._engine) as session:
                self._begin_write(session)
                if client_event_id is not None:
                    prior = self._replay_trip_event(
                        session,
                        user_id=user_id,
                        client_event_id=client_event_id,
                        fingerprint=fingerprint,
                    )
                    if prior is not None:
                        return TripRevision.model_validate_json(prior)
                self._check_report_size(report_json)
                self._owned_trip_row(session, user_id, trip_id)
                held = session.scalar(
                    select(func.count())
                    .select_from(TripRevisionRow)
                    .where(TripRevisionRow.trip_id == trip_id)
                )
                if int(held or 0) >= MAX_REVISIONS_PER_TRIP:
                    raise RevisionLimitReachedError(
                        f"at most {MAX_REVISIONS_PER_TRIP} revisions are kept per trip"
                    )
                revision = TripRevision(
                    id=revision_id or uuid4().hex,
                    trip_id=trip_id,
                    revision=self._highest_revision(session, trip_id) + 1,
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
                if client_event_id is not None:
                    self._record_trip_event(
                        session,
                        user_id=user_id,
                        client_event_id=client_event_id,
                        fingerprint=fingerprint,
                        operation=operation,
                        trip_id=trip_id,
                        result_payload=revision.model_dump_json(),
                        now=now,
                    )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    if client_event_id is not None:
                        with Session(self._engine) as again:
                            prior = self._replay_trip_event(
                                again,
                                user_id=user_id,
                                client_event_id=client_event_id,
                                fingerprint=fingerprint,
                            )
                        if prior is not None:
                            return TripRevision.model_validate_json(prior)
                    continue
            return revision
        raise TripRevisionConflictError(
            f"could not allocate a revision number for trip {trip_id}"
        )

    def trips(self, user_id: str) -> list[SavedTrip]:
        """Every saved trip for a user, ordered by ``(created_at, id)``."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(SavedTripRow).where(SavedTripRow.user_id == user_id)
            ).all()
            trips = [SavedTrip.model_validate_json(r.payload) for r in rows]
        return sorted(trips, key=lambda t: (t.created_at, t.id))

    def revisions(self, user_id: str, trip_id: str) -> list[TripRevision]:
        """Every revision of a trip this user owns, oldest first."""
        with Session(self._engine) as session:
            self._owned_trip_row(session, user_id, trip_id)
        return self._revisions_of_trip(trip_id)

    def _revisions_of_trip(self, trip_id: str) -> list[TripRevision]:
        """Unscoped read. Internal: callers must already have proved ownership."""
        with Session(self._engine) as session:
            rows = session.scalars(
                select(TripRevisionRow).where(TripRevisionRow.trip_id == trip_id)
            ).all()
            revisions = [TripRevision.model_validate_json(r.payload) for r in rows]
        return sorted(revisions, key=lambda r: r.revision)

    def latest_revision(self, user_id: str, trip_id: str) -> TripRevision | None:
        stored = self.revisions(user_id, trip_id)
        return stored[-1] if stored else None

    def delete_trip(
        self,
        user_id: str,
        trip_id: str,
        *,
        client_event_id: str | None = None,
        request_fingerprint: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        """Hard-delete one trip and its revisions. ``False`` if not this user's.

        With a ``client_event_id`` a replay returns the *original* outcome, so a
        retried successful delete reports ``True`` again rather than the ``False`` a
        genuine second delete would produce.
        """
        fingerprint = request_fingerprint or trip_event_fingerprint("delete", trip_id=trip_id)
        with Session(self._engine) as session:
            self._begin_write(session)
            if client_event_id is not None:
                prior = self._replay_trip_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                )
                if prior is not None:
                    return bool(json.loads(prior)["removed"])
            owned = session.scalar(
                select(SavedTripRow.id).where(
                    SavedTripRow.id == trip_id, SavedTripRow.user_id == user_id
                )
            )
            removed = owned is not None
            if removed:
                session.execute(
                    delete(TripRevisionRow).where(TripRevisionRow.trip_id == trip_id)
                )
                # The trip's own save/append/rerun outcomes carry its report, so
                # they go with it. Delete events are kept (trip_id is already NULL)
                # so a retried DELETE can still replay as "removed".
                session.execute(
                    delete(TripMutationEventRow).where(
                        TripMutationEventRow.user_id == user_id,
                        TripMutationEventRow.trip_id == trip_id,
                    )
                )
                # A planning session attached to the trip is retained only *with*
                # the trip (its expiry exemption); it dies with it.
                session.execute(
                    delete(PlanningSessionRow).where(
                        PlanningSessionRow.user_id == user_id,
                        PlanningSessionRow.saved_trip_id == trip_id,
                    )
                )
                session.execute(
                    delete(SavedTripRow).where(
                        SavedTripRow.id == trip_id, SavedTripRow.user_id == user_id
                    )
                )
            if client_event_id is not None:
                self._record_trip_event(
                    session,
                    user_id=user_id,
                    client_event_id=client_event_id,
                    fingerprint=fingerprint,
                    operation="delete",
                    trip_id=None,
                    result_payload=json.dumps({"removed": removed}),
                    now=now,
                )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if client_event_id is None:
                    raise
                with Session(self._engine) as again:
                    prior = self._replay_trip_event(
                        again,
                        user_id=user_id,
                        client_event_id=client_event_id,
                        fingerprint=fingerprint,
                    )
                if prior is None:
                    raise
                return bool(json.loads(prior)["removed"])
        return removed

    # -- privacy ------------------------------------------------------------ #

    def export_user(self, user_id: str, *, now: datetime) -> UserExport:
        """Every row held about a user, in the layer's deterministic order."""
        user = self.get_user(user_id)
        if user is None:
            raise UnknownUserError(f"no such user: {user_id}")
        trips = self.trips(user_id)
        revisions: list[TripRevision] = []
        for trip in trips:
            revisions.extend(self._revisions_of_trip(trip.id))
        return UserExport(
            user=user,
            profile=self.get_profile(user_id),
            wallet_entries=self.wallet_entries(user_id),
            wallet_mutation_events=self.wallet_mutation_events(user_id),
            trips=trips,
            revisions=revisions,
            trip_mutation_events=self.trip_mutation_events(user_id),
            travel_preferences=self.get_travel_preferences(user_id),
            planning_sessions=self.planning_session_snapshots(user_id),
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
                delete(TripMutationEventRow).where(TripMutationEventRow.user_id == user_id)
            )
            session.execute(
                delete(WalletEntryRow).where(WalletEntryRow.user_id == user_id)
            )
            session.execute(
                delete(WalletMutationEventRow).where(
                    WalletMutationEventRow.user_id == user_id
                )
            )
            session.execute(
                delete(UserProfileRow).where(UserProfileRow.user_id == user_id)
            )
            session.execute(
                delete(TravelPreferenceRow).where(
                    TravelPreferenceRow.user_id == user_id
                )
            )
            session.execute(
                delete(PlanningSessionRow).where(
                    PlanningSessionRow.user_id == user_id
                )
            )
            session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))
            session.execute(
                delete(UserCredentialRow).where(UserCredentialRow.user_id == user_id)
            )
            session.execute(delete(UserRow).where(UserRow.id == user_id))
            session.commit()

    # -- credentials -------------------------------------------------------- #

    def set_password(self, user_id: str, plaintext: str, *, now: datetime) -> None:
        """Set or replace a password and revoke every existing session."""
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

            session_rows = session.scalars(
                select(SessionRow).where(SessionRow.user_id == user_id)
            ).all()
            for session_row in session_rows:
                record = SessionRecord.model_validate_json(session_row.payload)
                if record.revoked_at is None:
                    session_row.payload = record.model_copy(
                        update={"revoked_at": now}
                    ).model_dump_json()
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
        return int(result.rowcount or 0)  # type: ignore[attr-defined]
