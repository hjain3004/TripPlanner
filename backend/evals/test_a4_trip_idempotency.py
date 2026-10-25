"""A4 Task 2 — durable idempotency and storage limits for saved-trip mutations.

Mirrors A3's wallet idempotency: ``(user_id, client_event_id)`` is the identity,
a replay returns the *original* outcome, reuse for a different request is a typed
conflict, and the replay check precedes every existence and limit check so an
honest retry of something that already succeeded is never rejected by the limit
it consumed.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest

import accounts.store as store_module
from accounts.models import PlanningSessionSnapshot
from accounts.store import (
    AccountStore,
    ReportTooLargeError,
    RevisionLimitReachedError,
    StalePlanningSessionError,
    TripIdempotencyConflictError,
    TripLimitReachedError,
    UnknownTripError,
    UnknownUserError,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
REPORT = '{"summary":"v1"}'


def _store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="u-bob")
    return store


def _save(store: AccountStore, **overrides: Any) -> Any:
    args: dict[str, Any] = {
        "user_id": "u-alice",
        "title": "DEL to SIN",
        "origin_city": "DEL",
        "destination_city": "SIN",
        "start_date": date(2026, 12, 1),
        "end_date": date(2026, 12, 6),
        "raw_request": "Delhi to Singapore",
        "trip_spec_json": "{}",
        "trace_id": "trace-1",
        "report_json": REPORT,
        "now": NOW,
    }
    args.update(overrides)
    return store.save_trip_with_revision(**args)


# --------------------------------------------------------------------------- #
# Replay, conflict, scoping of event ids                                        #
# --------------------------------------------------------------------------- #


def test_replaying_a_save_returns_the_original_and_writes_nothing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = _save(store, client_event_id="evt-1", request_fingerprint="fp-1")

    again = _save(
        store, client_event_id="evt-1", request_fingerprint="fp-1", trip_id="different-id"
    )

    assert again.trip.id == first.trip.id
    assert again.revision.id == first.revision.id
    assert [t.id for t in store.trips("u-alice")] == [first.trip.id]
    assert len(store.revisions("u-alice", first.trip.id)) == 1
    assert len(store.trip_mutation_events("u-alice")) == 1


def test_reusing_an_event_id_for_a_different_request_is_a_typed_conflict(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    _save(store, client_event_id="evt-1", request_fingerprint="fp-1")

    with pytest.raises(TripIdempotencyConflictError):
        _save(store, client_event_id="evt-1", request_fingerprint="fp-OTHER")

    assert len(store.trips("u-alice")) == 1


def test_two_users_may_reuse_the_same_textual_event_id(tmp_path: Path) -> None:
    store = _store(tmp_path)

    a = _save(store, user_id="u-alice", client_event_id="shared", request_fingerprint="fp")
    b = _save(store, user_id="u-bob", client_event_id="shared", request_fingerprint="fp")

    assert a.trip.id != b.trip.id
    assert len(store.trips("u-alice")) == 1
    assert len(store.trips("u-bob")) == 1


def test_concurrent_identical_saves_apply_once(tmp_path: Path) -> None:
    db_path = tmp_path / "accounts.sqlite"
    _store(tmp_path)
    workers = 4
    gate = Barrier(workers)

    def submit(_index: int) -> str:
        own = AccountStore.open(db_path)
        gate.wait()
        return str(
            _save(own, client_event_id="evt-race", request_fingerprint="fp").trip.id
        )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        ids = list(pool.map(submit, range(workers)))

    assert len(set(ids)) == 1, ids
    final = AccountStore.open(db_path)
    assert len(final.trips("u-alice")) == 1
    assert len(final.revisions("u-alice", ids[0])) == 1


def test_a_failed_mutation_is_never_recorded_as_a_success(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(UnknownUserError):
        _save(store, user_id="ghost", client_event_id="evt-x", request_fingerprint="fp")
    with pytest.raises(UnknownTripError):
        store.add_revision(
            user_id="u-bob",
            trip_id="nope",
            trace_id="t",
            report_json="{}",
            now=NOW,
            client_event_id="evt-y",
            request_fingerprint="fp",
        )

    assert store.trip_mutation_events("u-alice") == []
    assert store.trip_mutation_events("u-bob") == []
    assert store.trip_mutation_events("ghost") == []


# --------------------------------------------------------------------------- #
# Append, delete, rerun completion                                              #
# --------------------------------------------------------------------------- #


def test_replaying_an_append_adds_one_revision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    trip_id = _save(store).trip.id

    kwargs: dict[str, Any] = {
        "user_id": "u-alice",
        "trip_id": trip_id,
        "trace_id": "trace-2",
        "report_json": '{"summary":"v2"}',
        "now": NOW,
        "client_event_id": "evt-append",
        "request_fingerprint": "fp-append",
    }
    first = store.add_revision(**kwargs)
    second = store.add_revision(**kwargs)

    assert first.revision == second.revision == 2
    assert [r.revision for r in store.revisions("u-alice", trip_id)] == [1, 2]


def test_a_rerun_completion_that_fires_twice_appends_once(tmp_path: Path) -> None:
    store = _store(tmp_path)
    trip_id = _save(store).trip.id

    def complete() -> int:
        return store.add_revision(
            user_id="u-alice",
            trip_id=trip_id,
            trace_id="trace-rerun",
            report_json='{"summary":"rerun"}',
            now=NOW,
            system_event_id="rerun:job-1",
            request_fingerprint="rerun-fp",
            operation="rerun_complete",
        ).revision

    assert complete() == complete() == 2
    assert len(store.revisions("u-alice", trip_id)) == 2
    (event,) = [
        e for e in store.trip_mutation_events("u-alice") if e.client_event_id == "rerun:job-1"
    ]
    assert event.operation == "rerun_complete" and event.source == "system"


def test_a_replayed_delete_reports_the_original_outcome(tmp_path: Path) -> None:
    store = _store(tmp_path)
    trip_id = _save(store).trip.id

    first = store.delete_trip(
        "u-alice", trip_id, client_event_id="evt-del", request_fingerprint="fp-del"
    )
    replay = store.delete_trip(
        "u-alice", trip_id, client_event_id="evt-del", request_fingerprint="fp-del"
    )
    genuine_second = store.delete_trip("u-alice", trip_id)

    assert first is True and replay is True
    assert genuine_second is False


# --------------------------------------------------------------------------- #
# Limits (D11) and the replay-before-limit ordering trap                        #
# --------------------------------------------------------------------------- #


def test_the_trip_limit_is_enforced_with_a_typed_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_SAVED_TRIPS", 2)
    store = _store(tmp_path)
    _save(store)
    _save(store)

    with pytest.raises(TripLimitReachedError):
        _save(store)

    assert len(store.trips("u-alice")) == 2


def test_a_retried_save_is_not_rejected_by_the_limit_it_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_SAVED_TRIPS", 1)
    store = _store(tmp_path)
    first = _save(store, client_event_id="evt-1", request_fingerprint="fp-1")

    replay = _save(store, client_event_id="evt-1", request_fingerprint="fp-1")  # at the limit

    assert replay.trip.id == first.trip.id
    with pytest.raises(TripLimitReachedError):
        _save(store, client_event_id="evt-2", request_fingerprint="fp-2")


def test_the_revision_limit_is_enforced_and_replay_still_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_REVISIONS_PER_TRIP", 2)
    store = _store(tmp_path)
    trip_id = _save(store).trip.id
    kwargs: dict[str, Any] = {
        "user_id": "u-alice",
        "trip_id": trip_id,
        "trace_id": "t",
        "report_json": "{}",
        "now": NOW,
    }
    store.add_revision(**kwargs, client_event_id="evt-2", request_fingerprint="fp-2")

    store.add_revision(**kwargs, client_event_id="evt-2", request_fingerprint="fp-2")  # replay
    with pytest.raises(RevisionLimitReachedError):
        store.add_revision(**kwargs, client_event_id="evt-3", request_fingerprint="fp-3")

    assert len(store.revisions("u-alice", trip_id)) == 2


def test_an_oversized_report_is_rejected_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_REPORT_BYTES", 64)
    store = _store(tmp_path)

    with pytest.raises(ReportTooLargeError):
        _save(store, report_json='{"blob":"' + "a" * 100 + '"}')

    assert store.trips("u-alice") == []


# --------------------------------------------------------------------------- #
# Atomic attach of the originating planning session                             #
# --------------------------------------------------------------------------- #


def _session(store: AccountStore) -> PlanningSessionSnapshot:
    snapshot = PlanningSessionSnapshot(
        id="s1",
        user_id="u-alice",
        status="complete",
        version=3,
        updated_at=NOW,
        expires_at=datetime(2026, 11, 24, tzinfo=UTC),
        saved_trip_id=None,
        payload_json="{}",
    )
    store.create_planning_session_snapshot(snapshot)
    return snapshot


def test_saving_attaches_the_session_in_the_same_transaction(tmp_path: Path) -> None:
    store = _store(tmp_path)
    snapshot = _session(store)
    attached = snapshot.model_copy(update={"version": 4, "saved_trip_id": "trip-s1"})

    result = _save(
        store, trip_id="trip-s1", attach_session=attached, expected_session_version=3
    )

    stored = store.get_planning_session_snapshot(user_id="u-alice", session_id="s1")
    assert stored is not None
    assert stored.saved_trip_id == result.trip.id == "trip-s1"
    assert stored.version == 4


def test_a_lost_session_race_leaves_no_trip_revision_or_event_behind(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    snapshot = _session(store)
    stale = snapshot.model_copy(update={"version": 10, "saved_trip_id": "trip-s1"})

    with pytest.raises(StalePlanningSessionError):
        _save(
            store,
            trip_id="trip-s1",
            attach_session=stale,
            expected_session_version=9,  # the row is at 3
            client_event_id="evt-1",
            request_fingerprint="fp",
        )

    assert store.trips("u-alice") == []
    assert store.trip_mutation_events("u-alice") == []
    still = store.get_planning_session_snapshot(user_id="u-alice", session_id="s1")
    assert still is not None and still.saved_trip_id is None and still.version == 3


def test_a_client_event_id_can_never_shadow_an_internal_completion_event(
    tmp_path: Path,
) -> None:
    """Caller-supplied and internal event ids live in separate namespaces."""
    store = _store(tmp_path)
    trip_id = _save(store).trip.id
    common: dict[str, Any] = {
        "user_id": "u-alice",
        "trip_id": trip_id,
        "trace_id": "t",
        "now": NOW,
    }
    # A client happens to send the exact id the internal completion will use.
    store.add_revision(
        **common,
        report_json='{"by":"client"}',
        client_event_id="rerun:job-9",
        request_fingerprint="client-fp",
    )

    completed = store.add_revision(
        **common,
        report_json='{"by":"rerun"}',
        system_event_id="rerun:job-9",
        request_fingerprint="system-fp",
        operation="rerun_complete",
    )

    assert completed.revision == 3
    sources = {(e.source, e.client_event_id) for e in store.trip_mutation_events("u-alice")}
    assert ("client", "rerun:job-9") in sources and ("system", "rerun:job-9") in sources


def test_a_mutation_names_at_most_one_event_namespace(tmp_path: Path) -> None:
    store = _store(tmp_path)
    trip_id = _save(store).trip.id

    with pytest.raises(ValueError):
        store.add_revision(
            user_id="u-alice",
            trip_id=trip_id,
            trace_id="t",
            report_json="{}",
            now=NOW,
            client_event_id="a",
            system_event_id="b",
        )
