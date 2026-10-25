"""A4 Task 1 — owner-scoped saved-trip access and safe revision numbering.

Mirrors A3's wallet scoping/concurrency tests. The pre-A4 store resolved a trip by
id alone, so any caller who knew (or guessed) a trip id could read, extend or
inspect another user's history; and nothing stopped two writers computing the
same ``max + 1`` revision number.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from accounts.db import TripRevisionRow
from accounts.store import (
    AccountStore,
    TripRevisionConflictError,
    UnknownTripError,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
SPEC = '{"origin_city":"DEL","destination_city":"SIN"}'


def _store(tmp_path: Path) -> AccountStore:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    store.create_user(email="alice@example.com", now=NOW, user_id="u-alice")
    store.create_user(email="bob@example.com", now=NOW, user_id="u-bob")
    return store


def _trip(store: AccountStore, user_id: str = "u-alice", trip_id: str = "t1") -> str:
    return store.save_trip(
        user_id=user_id,
        title="DEL to SIN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 6),
        raw_request="Delhi to Singapore",
        trip_spec_json=SPEC,
        now=NOW,
        trip_id=trip_id,
    ).id


# --------------------------------------------------------------------------- #
# Ownership scoping                                                             #
# --------------------------------------------------------------------------- #


def test_the_owner_can_read_their_trip_and_revisions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    trip_id = _trip(store)
    store.add_revision(
        user_id="u-alice", trip_id=trip_id, trace_id="tr1", report_json='{"a":1}', now=NOW
    )

    assert store.get_trip("u-alice", trip_id).id == trip_id
    assert [r.revision for r in store.revisions("u-alice", trip_id)] == [1]
    latest = store.latest_revision("u-alice", trip_id)
    assert latest is not None and latest.revision == 1


def test_another_user_cannot_read_a_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)

    with pytest.raises(UnknownTripError):
        store.get_trip("u-bob", "t1")


def test_another_user_cannot_read_revisions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)
    store.add_revision(
        user_id="u-alice", trip_id="t1", trace_id="tr1", report_json="{}", now=NOW
    )

    with pytest.raises(UnknownTripError):
        store.revisions("u-bob", "t1")
    with pytest.raises(UnknownTripError):
        store.latest_revision("u-bob", "t1")


def test_another_user_cannot_append_a_revision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)

    with pytest.raises(UnknownTripError):
        store.add_revision(
            user_id="u-bob", trip_id="t1", trace_id="tr", report_json="{}", now=NOW
        )

    assert store.revisions("u-alice", "t1") == []


def test_another_user_cannot_delete_a_trip(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)

    assert store.delete_trip("u-bob", "t1") is False

    assert [t.id for t in store.trips("u-alice")] == ["t1"]


def test_trips_never_returns_another_users_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)

    assert store.trips("u-bob") == []


def test_wrong_owner_is_indistinguishable_from_missing(tmp_path: Path) -> None:
    """Same exception type and a message that depends on neither owner nor existence."""
    store = _store(tmp_path)
    _trip(store)

    with pytest.raises(UnknownTripError) as wrong_owner:
        store.get_trip("u-bob", "t1")
    with pytest.raises(UnknownTripError) as missing:
        store.get_trip("u-bob", "nope")

    assert type(wrong_owner.value) is type(missing.value)
    assert str(wrong_owner.value).replace("t1", "X") == str(missing.value).replace("nope", "X")
    assert "u-alice" not in str(wrong_owner.value)


def test_delete_trip_removes_the_trip_and_its_revisions(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)
    store.add_revision(
        user_id="u-alice", trip_id="t1", trace_id="tr1", report_json="{}", now=NOW
    )

    assert store.delete_trip("u-alice", "t1") is True
    assert store.delete_trip("u-alice", "t1") is False  # idempotent second delete

    assert store.trips("u-alice") == []
    with pytest.raises(UnknownTripError):
        store.revisions("u-alice", "t1")


# --------------------------------------------------------------------------- #
# Revision numbering                                                            #
# --------------------------------------------------------------------------- #


def test_revision_numbers_are_unique_per_trip_at_the_schema_level(tmp_path: Path) -> None:
    store = _store(tmp_path)
    _trip(store)
    store.add_revision(
        user_id="u-alice", trip_id="t1", trace_id="tr1", report_json="{}", now=NOW
    )

    with Session(store._engine) as session:
        session.add(TripRevisionRow(id="dup", trip_id="t1", revision=1, payload="{}"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_concurrent_appends_get_distinct_consecutive_numbers(tmp_path: Path) -> None:
    """Separate connections, released together: never ``1`` and ``1``."""
    db_path = tmp_path / "accounts.sqlite"
    store = _store(tmp_path)
    _trip(store)
    workers = 6
    gate = Barrier(workers)

    def append(index: int) -> int | str:
        own = AccountStore.open(db_path)  # its own connection
        gate.wait()
        try:
            return own.add_revision(
                user_id="u-alice",
                trip_id="t1",
                trace_id=f"tr{index}",
                report_json="{}",
                now=NOW,
            ).revision
        except sqlite3.OperationalError:  # pragma: no cover - the bug this guards
            return "leaked-sqlite-error"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(append, range(workers)))

    assert sorted(o for o in outcomes if isinstance(o, int)) == list(
        range(1, workers + 1)
    ), outcomes
    stored = [r.revision for r in AccountStore.open(db_path).revisions("u-alice", "t1")]
    assert stored == list(range(1, workers + 1))


def test_a_persistent_collision_becomes_a_typed_error_not_a_driver_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)
    _trip(store)
    store.add_revision(
        user_id="u-alice", trip_id="t1", trace_id="tr1", report_json="{}", now=NOW
    )
    # Every attempt believes revision 1 is next: the unique index fires each time.
    monkeypatch.setattr(store, "_highest_revision", lambda session, trip_id: 0)

    with pytest.raises(TripRevisionConflictError):
        store.add_revision(
            user_id="u-alice", trip_id="t1", trace_id="tr2", report_json="{}", now=NOW
        )

    monkeypatch.undo()
    assert [r.revision for r in store.revisions("u-alice", "t1")] == [1]


# --------------------------------------------------------------------------- #
# Migration safety                                                              #
# --------------------------------------------------------------------------- #

_PRE_A4_DDL = (
    "CREATE TABLE saved_trips (id VARCHAR NOT NULL, user_id VARCHAR NOT NULL, "
    "created_at VARCHAR NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (id))",
    "CREATE INDEX ix_saved_trips_user_id ON saved_trips (user_id)",
    "CREATE INDEX ix_saved_trips_created_at ON saved_trips (created_at)",
    "CREATE TABLE trip_revisions (id VARCHAR NOT NULL, trip_id VARCHAR NOT NULL, "
    "revision INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY (id))",
    "CREATE INDEX ix_trip_revisions_trip_id ON trip_revisions (trip_id)",
    "CREATE INDEX ix_trip_revisions_revision ON trip_revisions (revision)",
)


def _pre_a4_database(path: Path, *, duplicate_revision: bool = False) -> str:
    """A database exactly as the pre-A4 schema left it, holding one trip + revision."""
    trip_payload = (
        '{"id":"t1","user_id":"u-alice","title":"DEL to SIN","origin_city":"DEL",'
        '"destination_city":"SIN","start_date":"2026-12-01","end_date":"2026-12-06",'
        '"raw_request":"r","trip_spec_json":"{}","schema_version":"1",'
        '"created_at":"2026-10-24T12:00:00Z"}'
    )
    revision_payload = (
        '{"id":"r1","trip_id":"t1","revision":1,"trace_id":"old",'
        '"report_json":"{\\"summary\\":\\"as computed in 2026\\"}",'
        '"schema_version":"1","created_at":"2026-10-24T12:00:00Z"}'
    )
    connection = sqlite3.connect(path)
    for statement in _PRE_A4_DDL:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO saved_trips VALUES ('t1','u-alice','2026-10-24T12:00:00+00:00',?)",
        (trip_payload,),
    )
    connection.execute("INSERT INTO trip_revisions VALUES ('r1','t1',1,?)", (revision_payload,))
    if duplicate_revision:
        connection.execute(
            "INSERT INTO trip_revisions VALUES ('r1-dup','t1',1,?)", (revision_payload,)
        )
    connection.commit()
    connection.close()
    return revision_payload


def _revision_rows(path: Path) -> list[tuple[str, str, int, str]]:
    connection = sqlite3.connect(path)
    try:
        return list(
            connection.execute(
                "SELECT id, trip_id, revision, payload FROM trip_revisions ORDER BY id"
            )
        )
    finally:
        connection.close()


def test_a_pre_a4_database_upgrades_without_rewriting_rows(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    original = _pre_a4_database(path)
    before = _revision_rows(path)

    store = AccountStore.open(path)  # runs the additive migration

    assert _revision_rows(path) == before
    assert before[0][3] == original
    (revision,) = store._revisions_of_trip("t1")
    assert revision.report_json == '{"summary":"as computed in 2026"}'
    connection = sqlite3.connect(path)
    try:
        index_names = {row[1] for row in connection.execute("PRAGMA index_list(trip_revisions)")}
    finally:
        connection.close()
    assert "uq_trip_revisions_trip_revision" in index_names


def test_opening_twice_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    _pre_a4_database(path)

    AccountStore.open(path)
    AccountStore.open(path)

    assert len(_revision_rows(path)) == 1


def test_a_database_with_legacy_duplicate_revisions_still_opens(tmp_path: Path) -> None:
    """Rows written by the old race must never make startup fail, nor be rewritten."""
    path = tmp_path / "accounts.sqlite"
    _pre_a4_database(path, duplicate_revision=True)
    before = _revision_rows(path)

    AccountStore.open(path)

    assert _revision_rows(path) == before


def test_reopening_does_not_rescan_revisions_once_the_index_exists(tmp_path: Path) -> None:
    """``get_store`` opens the database on every request; the duplicate scan must not
    run again once the unique index is already in place."""
    from sqlalchemy import event

    from accounts.db import _ensure_unique_revision_index

    store = _store(tmp_path)  # fresh database: the index already exists
    statements: list[str] = []

    @event.listens_for(store._engine, "before_cursor_execute")
    def capture(_conn: Any, _cur: Any, statement: str, *_args: Any) -> None:
        statements.append(statement)

    _ensure_unique_revision_index(store._engine)

    assert not any("GROUP BY" in s.upper() for s in statements), statements
