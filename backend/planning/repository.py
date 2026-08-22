"""Typed repository adapter persisting ``PlanningSession`` through ``AccountStore``.

``AccountStore`` is the only public database write boundary in this codebase
(see ``accounts/store.py``'s module docstring). This module never touches
SQLAlchemy or a database engine/session directly — it only translates
between the domain ``PlanningSession`` (``planning/contracts.py``) and the
account-side opaque ``PlanningSessionSnapshot`` (``accounts/models.py``), and
delegates every actual read/write to the injected ``AccountStore``.
"""

from __future__ import annotations

from datetime import datetime

from accounts.models import PlanningSessionSnapshot
from accounts.store import AccountStore
from planning.contracts import PlanningSession


def _to_snapshot(session: PlanningSession) -> PlanningSessionSnapshot:
    return PlanningSessionSnapshot(
        id=session.id,
        user_id=session.user_id,
        status=session.status.value,
        version=session.version,
        updated_at=session.updated_at,
        expires_at=session.expires_at,
        saved_trip_id=session.saved_trip_id,
        payload_json=session.model_dump_json(),
    )


class PlanningSessionRepository:
    """Ownership-scoped, optimistic-concurrency-safe planning-session storage."""

    def __init__(self, store: AccountStore) -> None:
        self._store = store

    def create(self, session: PlanningSession) -> PlanningSession:
        self._store.create_planning_session_snapshot(_to_snapshot(session))
        return session

    def get(self, *, user_id: str, session_id: str) -> PlanningSession | None:
        snapshot = self._store.get_planning_session_snapshot(
            user_id=user_id, session_id=session_id
        )
        if snapshot is None:
            return None
        return PlanningSession.model_validate_json(snapshot.payload_json)

    def save(
        self, session: PlanningSession, *, expected_version: int
    ) -> PlanningSession:
        """Persist ``session`` via compare-and-swap, tolerating idempotent replay.

        ``planning.policy.record_answer`` is idempotent on
        ``client_event_id``: replaying an already-processed event returns the
        identical, unchanged session (same version) rather than bumping it.
        ``AccountStore.put_planning_session_snapshot`` hard-requires
        ``snapshot.version == expected_version + 1`` for every write, so a
        caller that naively saves that unchanged session at its own current
        version (``session.version == expected_version``, since nothing
        changed) would hit that precondition and fail before ever reaching
        the database. There is nothing to persist in that case -- the
        session is already exactly what the store has -- so this is a no-op
        that returns ``session`` as-is. Only an actual state change
        (``session.version == expected_version + 1``) reaches the store's
        real compare-and-swap update.
        """
        if session.version == expected_version:
            return session
        self._store.put_planning_session_snapshot(
            _to_snapshot(session), expected_version=expected_version
        )
        return session

    def list_for_user(self, user_id: str) -> list[PlanningSession]:
        snapshots = self._store.planning_session_snapshots(user_id)
        return [
            PlanningSession.model_validate_json(snapshot.payload_json)
            for snapshot in snapshots
        ]

    def delete_expired(self, *, now: datetime) -> int:
        return self._store.delete_expired_planning_sessions(now=now)
