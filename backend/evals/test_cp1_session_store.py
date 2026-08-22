"""Resumable planning-session persistence (CP1 task 4).

``PlanningSession`` is the in-memory domain shape for a conversational
interview; ``PlanningSessionRepository`` persists it through ``AccountStore``
as an opaque JSON snapshot with real optimistic-concurrency (compare-and-swap
on ``version``), per-user ownership scoping, and 30-day abandoned-session
expiry (a session attached to a saved trip is retained forever).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from accounts.models import PlanningSessionSnapshot
from accounts.store import (
    AccountStore,
    PlanningSessionExistsError,
    StalePlanningSessionError,
)
from core.models import UserWallet
from planning.answers import InterviewAnswer, QuestionId, TripEssentialsPayload
from planning.contracts import (
    PlanningSession,
    PlanningSessionStatus,
    TravelerHomeContext,
)
from planning.policy import record_answer, start_interview
from planning.repository import PlanningSessionRepository

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
LATER = NOW + timedelta(hours=1)
OLD = datetime(2020, 1, 1, tzinfo=UTC)


def _user_store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="a@example.com", now=NOW, user_id="u1")
    return store


def _session(
    *,
    session_id: str = "ps1",
    user_id: str = "u1",
    version: int = 0,
    updated_at: datetime = NOW,
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
    status: PlanningSessionStatus = PlanningSessionStatus.INTERVIEWING,
    saved_trip_id: str | None = None,
) -> PlanningSession:
    created = created_at if created_at is not None else updated_at
    expires = expires_at if expires_at is not None else updated_at + timedelta(days=30)
    return PlanningSession(
        id=session_id,
        user_id=user_id,
        status=status,
        version=version,
        created_at=created,
        updated_at=updated_at,
        expires_at=expires,
        home=TravelerHomeContext(
            home_country="IN", home_currency="INR", default_origin="DEL"
        ),
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        saved_trip_id=saved_trip_id,
    )


def _repository_with_session(tmp_path: Path) -> PlanningSessionRepository:
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    repository.create(_session())
    return repository


# --------------------------------------------------------------------------- #
# Contract shape                                                                #
# --------------------------------------------------------------------------- #


def test_new_session_is_server_owned_and_version_zero() -> None:
    session = PlanningSession(
        id="ps1",
        user_id="u1",
        status="interviewing",
        version=0,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(days=30),
        home=TravelerHomeContext(
            home_country="IN", home_currency="INR", default_origin="DEL"
        ),
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
    )
    assert session.answers == {}
    assert session.processed_event_ids == []
    assert session.assistance_status == "not_run"


def test_traveler_home_context_normalizes_currency_and_origin() -> None:
    home = TravelerHomeContext(
        home_country="IN", home_currency=" inr ", default_origin=" del "
    )
    assert home.home_currency == "INR"
    assert home.default_origin == "DEL"


def test_traveler_home_context_rejects_a_malformed_currency() -> None:
    with pytest.raises(ValidationError):
        TravelerHomeContext(home_country="IN", home_currency="rupees")


def test_planning_session_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        PlanningSession(
            id="ps1",
            user_id="u1",
            status=PlanningSessionStatus.INTERVIEWING,
            version=0,
            created_at=datetime(2026, 8, 21, 12, 0),  # naive
            updated_at=NOW,
            expires_at=NOW + timedelta(days=30),
            home=TravelerHomeContext(home_country="IN", home_currency="INR"),
            wallet=UserWallet(card_ids=[]),
        )


def test_planning_session_rejects_expires_at_not_after_updated_at() -> None:
    with pytest.raises(ValidationError):
        PlanningSession(
            id="ps1",
            user_id="u1",
            status=PlanningSessionStatus.INTERVIEWING,
            version=0,
            created_at=NOW,
            updated_at=NOW,
            expires_at=NOW,  # not strictly after updated_at
            home=TravelerHomeContext(home_country="IN", home_currency="INR"),
            wallet=UserWallet(card_ids=[]),
        )


def test_planning_session_rejects_duplicate_processed_event_ids() -> None:
    with pytest.raises(ValidationError):
        PlanningSession(
            id="ps1",
            user_id="u1",
            status=PlanningSessionStatus.INTERVIEWING,
            version=0,
            created_at=NOW,
            updated_at=NOW,
            expires_at=NOW + timedelta(days=30),
            home=TravelerHomeContext(home_country="IN", home_currency="INR"),
            wallet=UserWallet(card_ids=[]),
            processed_event_ids=["e1", "e1"],
        )


# --------------------------------------------------------------------------- #
# Repository round trip and optimistic concurrency                             #
# --------------------------------------------------------------------------- #


def test_repository_round_trips_a_session(tmp_path: Path) -> None:
    accounts = _user_store(tmp_path)
    repository = PlanningSessionRepository(accounts)
    session = _session()
    repository.create(session)
    assert repository.get(user_id="u1", session_id="ps1") == session


def test_repository_rejects_a_stale_compare_and_swap(tmp_path: Path) -> None:
    repository = _repository_with_session(tmp_path)
    current = repository.get(user_id="u1", session_id="ps1")
    assert current is not None
    v1 = current.model_copy(update={"version": 1, "updated_at": LATER})
    repository.save(v1, expected_version=0)
    stale = current.model_copy(update={"version": 1, "updated_at": LATER})
    with pytest.raises(StalePlanningSessionError):
        repository.save(stale, expected_version=0)


def test_create_rejects_a_duplicate_session_id(tmp_path: Path) -> None:
    repository = _repository_with_session(tmp_path)

    with pytest.raises(PlanningSessionExistsError):
        repository.create(_session())


def test_get_returns_none_for_a_different_user(tmp_path: Path) -> None:
    repository = _repository_with_session(tmp_path)

    assert repository.get(user_id="someone-else", session_id="ps1") is None


def test_save_rejects_a_cross_user_update(tmp_path: Path) -> None:
    repository = _repository_with_session(tmp_path)
    current = repository.get(user_id="u1", session_id="ps1")
    assert current is not None
    hijack = current.model_copy(
        update={"user_id": "u2", "version": 1, "updated_at": LATER}
    )

    with pytest.raises(StalePlanningSessionError):
        repository.save(hijack, expected_version=0)

    # The original owner's row is untouched.
    unchanged = repository.get(user_id="u1", session_id="ps1")
    assert unchanged is not None
    assert unchanged.version == 0


def test_planning_session_snapshot_rejects_non_object_payload_json() -> None:
    with pytest.raises(ValidationError):
        PlanningSessionSnapshot(
            id="ps1",
            user_id="u1",
            status="interviewing",
            version=0,
            updated_at=NOW,
            expires_at=NOW + timedelta(days=30),
            payload_json="[1, 2, 3]",
        )


def test_store_persists_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "accounts.sqlite"
    accounts = AccountStore.open(db_path)
    accounts.create_user(email="a@example.com", now=NOW, user_id="u1")
    PlanningSessionRepository(accounts).create(_session())

    reopened = AccountStore.open(db_path)
    reopened_repository = PlanningSessionRepository(reopened)

    fetched = reopened_repository.get(user_id="u1", session_id="ps1")
    assert fetched is not None
    assert fetched.id == "ps1"


def test_list_for_user_orders_by_updated_at_then_id(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    repository.create(_session(session_id="ps-b", updated_at=NOW))
    repository.create(_session(session_id="ps-a", updated_at=NOW))
    repository.create(_session(session_id="ps-c", updated_at=NOW - timedelta(hours=1)))

    ordered = repository.list_for_user("u1")

    assert [s.id for s in ordered] == ["ps-c", "ps-a", "ps-b"]


# --------------------------------------------------------------------------- #
# Expiry sweeping                                                               #
# --------------------------------------------------------------------------- #


def test_delete_expired_removes_an_abandoned_session_past_its_expiry(
    tmp_path: Path,
) -> None:
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    repository.create(_session(session_id="ps-old", updated_at=OLD))

    removed = repository.delete_expired(now=NOW)

    assert removed == 1
    assert repository.get(user_id="u1", session_id="ps-old") is None


def test_delete_expired_retains_a_session_attached_to_a_saved_trip(
    tmp_path: Path,
) -> None:
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    repository.create(
        _session(session_id="ps-old", updated_at=OLD, saved_trip_id="trip-1")
    )

    removed = repository.delete_expired(now=NOW)

    assert removed == 0
    assert repository.get(user_id="u1", session_id="ps-old") is not None


# --------------------------------------------------------------------------- #
# Privacy export and account deletion cascade                                  #
# --------------------------------------------------------------------------- #


def test_export_user_includes_planning_sessions(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    repository.create(_session())

    export = store.export_user("u1", now=NOW)

    assert [s.id for s in export.planning_sessions] == ["ps1"]


def test_delete_user_removes_planning_sessions(tmp_path: Path) -> None:
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    repository.create(_session())

    store.delete_user("u1")

    assert repository.get(user_id="u1", session_id="ps1") is None


# --------------------------------------------------------------------------- #
# Idempotent-replay / compare-and-swap composition (final-review finding 2)     #
# --------------------------------------------------------------------------- #


def _trip_essentials_answer(*, event_id: str) -> InterviewAnswer:
    return InterviewAnswer(
        question_id=QuestionId.TRIP_ESSENTIALS,
        payload=TripEssentialsPayload(
            origin="DEL",
            destination="SIN",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 5),
            travelers=2,
        ),
        client_event_id=event_id,
        answered_at=NOW,
    )


def test_save_after_replaying_an_idempotent_record_answer_does_not_raise(
    tmp_path: Path,
) -> None:
    """The natural caller sequence -- record an answer, save it, then
    legitimately resubmit the same ``client_event_id`` and save again --
    must not raise.

    ``policy.record_answer`` is deliberately idempotent on
    ``client_event_id``: a replayed event returns the identical, unchanged
    session (same version) *before* its own version check even runs. The
    store's compare-and-swap (``AccountStore.put_planning_session_snapshot``,
    reached through ``PlanningSessionRepository.save``) hard-requires
    ``snapshot.version == expected_version + 1`` for every write. Composing
    the two naively -- calling ``repository.save`` with the *same*
    ``expected_version`` that was just (correctly) passed to the replayed
    ``record_answer`` call, i.e. the session's own current version, since
    nothing changed -- broke before the fix: the store's pre-check saw
    ``session.version == expected_version`` (not ``expected_version + 1``)
    and raised a bare, untyped ``ValueError`` before ever reaching the
    database. The fix makes the repository recognize the no-change case and
    skip the write entirely, returning the already-current session.
    """
    store = _user_store(tmp_path)
    repository = PlanningSessionRepository(store)
    session0 = start_interview(
        user_id="u1",
        session_id="ps1",
        home=TravelerHomeContext(
            home_country="IN", home_currency="INR", default_origin="DEL"
        ),
        wallet=UserWallet(card_ids=["hdfc-infinia"]),
        profile_defaults=None,
        now=NOW,
        expires_at=NOW + timedelta(days=30),
    )
    repository.create(session0)

    answer = _trip_essentials_answer(event_id="evt-1")

    session1 = record_answer(session0, answer, expected_version=0, now=NOW)
    assert session1.version == 1
    saved = repository.save(session1, expected_version=0)
    assert saved.version == 1

    # A legitimate resubmission of the exact same answer/event, made at the
    # session's real current version (1). Because `client_event_id` is
    # already in `processed_event_ids`, `record_answer` takes the
    # idempotency short-circuit and returns `saved` unchanged rather than
    # raising `StaleSessionVersionError`.
    replayed = record_answer(saved, answer, expected_version=1, now=NOW)
    assert replayed == saved
    assert replayed.version == 1

    # The caller's natural next step: save at the version the (unchanged)
    # session now reports. This must succeed as a no-op, not raise.
    result = repository.save(replayed, expected_version=1)

    assert result.version == 1
    persisted = repository.get(user_id="u1", session_id="ps1")
    assert persisted is not None
    assert persisted.version == 1
    assert persisted == saved


# --------------------------------------------------------------------------- #
# Status enum / Literal parity lock (final-review finding 3)                    #
# --------------------------------------------------------------------------- #


def test_planning_session_status_enum_and_snapshot_literal_stay_in_sync() -> None:
    """``accounts/`` cannot import ``planning/`` (package-boundary rule), so
    ``PlanningSessionSnapshot.status``'s ``Literal[...]`` is a hand-duplicated
    copy of ``planning.contracts.PlanningSessionStatus``. This cross-package
    test is the only possible lock between the two: if a future change adds,
    removes, or renames a status on one side without updating the other,
    persistence would otherwise break at runtime (a `pydantic.ValidationError`
    out of `PlanningSessionSnapshot` when `planning/repository.py` passes
    `session.status.value` through) with nothing catching it beforehand.
    """
    enum_values = {member.value for member in PlanningSessionStatus}

    status_field = PlanningSessionSnapshot.model_fields["status"]
    literal_values = set(get_args(status_field.annotation))

    assert enum_values == literal_values
