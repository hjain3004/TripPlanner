"""CP4 Task 3 — atomic commits, restart recovery, deletion races, privacy, initialisation.

Late completions must neither overwrite newer state nor recreate deleted data, and an
interrupted reservation must never be dispatched again. Every scenario runs against a
real SQLite file that is reopened before it is inspected.
"""

from __future__ import annotations

import json
import socket
import sqlite3
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import accounts.store as store_module
from accounts.db import AccountsBase
from accounts.models import TripRevision
from accounts.store import (
    AccountStore,
    PostPlanOperationConflictError,
    PostPlanOperationNotReservedError,
    PostPlanQuotaError,
    PostPlanWorkspaceNotFoundError,
    UnknownTripError,
)
from agents.post_plan_models import report_schema_fingerprint
from api import post_plan_service as service
from api.job_manager import job_manager
from api.main import app
from evals.a4_support import PlanningKit, csrf, finished_plan, signed_in_client
from evals.cp4_support import (
    EXPIRES,
    NOW,
    make_operation,
    open_store,
    planning_snapshot,
    run_operation,
    seed_workspace,
)
from planning.repository import PlanningSessionRepository

POST_PLAN_TABLES = ("post_plan_workspaces", "post_plan_results", "post_plan_operations")


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def rows(path: Path, table: str) -> int:
    connection = sqlite3.connect(path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def reserved_state(
    store: AccountStore,
) -> tuple[Any, Any, Any]:
    """Reserve a propose operation; return (reserved op, workspace, session) to commit."""
    operation = make_operation("propose", "p1", interpreter_calls=1)
    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    session = store.get_planning_session_snapshot(user_id="alice", session_id="s1")
    assert workspace is not None and session is not None
    reserved = store.reserve_post_plan_operation(
        user_id="alice",
        session_id="s1",
        operation=operation,
        expected_workspace_version=workspace.version,
        expected_session_version=session.version,
    )
    return reserved, workspace, session


def commit(store: AccountStore, reserved: Any, workspace: Any, session: Any, **extra: Any) -> Any:
    return store.commit_post_plan_operation(
        user_id="alice",
        session_id="s1",
        event_id=reserved.event_id,
        fingerprint=reserved.fingerprint,
        expected_workspace_version=reserved.reserved_workspace_version,
        workspace=workspace.model_copy(
            update={"current_result_id": extra.pop("result_id", workspace.current_result_id)}
        ),
        session=session.model_copy(update={"version": session.version + 1}),
        report_json=extra.pop("report_json", None),
        **extra,
    )


# --------------------------------------------------------------------------- #
# Atomicity: a failure at any statement leaves no partial state                    #
# --------------------------------------------------------------------------- #


def count_commit_statements(tmp_path: Path) -> int:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, workspace, session = reserved_state(store)
    statements: list[str] = []

    def count(*_: Any) -> None:
        statements.append("x")

    event.listen(store._engine, "before_cursor_execute", count)
    commit(store, reserved, workspace, session, result_id="r2", report_json='{"n":2}')
    event.remove(store._engine, "before_cursor_execute", count)
    return len(statements)


def test_a_failure_at_every_commit_statement_leaves_no_partial_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dry = tmp_path / "dry"
    dry.mkdir()
    total = count_commit_statements(dry)
    assert total >= 6  # lookup, session CAS, result insert, workspace, operation, commit

    for fail_at in range(1, total + 1):
        directory = tmp_path / f"fail-{fail_at}"
        directory.mkdir()
        store = open_store(directory)
        seed_workspace(store)
        reserved, workspace, session = reserved_state(store)
        seen = {"count": 0}

        def explode(
            conn: Any,
            cursor: Any,
            statement: str,
            params: Any,
            context: Any,
            many: Any,
            _fail_at: int = fail_at,
            _seen: dict[str, int] = seen,
        ) -> None:
            _seen["count"] += 1
            if _seen["count"] == _fail_at:
                raise RuntimeError(f"injected failure at statement {_fail_at}")

        event.listen(store._engine, "before_cursor_execute", explode)
        with pytest.raises(Exception, match="injected"):
            commit(store, reserved, workspace, session, result_id="r2", report_json='{"n":2}')
        event.remove(store._engine, "before_cursor_execute", explode)

        reopened = AccountStore.open(directory / "accounts.sqlite")
        after = reopened.get_post_plan_workspace(user_id="alice", session_id="s1")
        assert after is not None, fail_at
        assert after.version == reserved.reserved_workspace_version, fail_at
        assert after.current_result_id == "r1", fail_at
        assert (
            reopened.get_post_plan_result(user_id="alice", session_id="s1", result_id="r2") is None
        ), fail_at
        stored = reopened.get_post_plan_operation(user_id="alice", event_id="p1")
        assert stored is not None and stored.status == "reserved", fail_at
        still = reopened.get_planning_session_snapshot(user_id="alice", session_id="s1")
        assert still is not None and still.version == session.version, fail_at


def test_a_failed_database_commit_leaves_the_reservation_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, workspace, session = reserved_state(store)
    real_commit = Session.commit

    def failing(self: Session) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(Session, "commit", failing)
    with pytest.raises(RuntimeError, match="disk full"):
        commit(store, reserved, workspace, session, result_id="r2", report_json='{"n":2}')
    monkeypatch.setattr(Session, "commit", real_commit)

    again = commit(store, reserved, workspace, session, result_id="r2", report_json='{"n":2}')
    assert again.status == "complete"  # the retry of the same completion now succeeds


# --------------------------------------------------------------------------- #
# Deletion racing a late completion                                                  #
# --------------------------------------------------------------------------- #


def attach_trip(store: AccountStore) -> None:
    store.save_trip_with_revision(
        user_id="alice",
        title="t",
        origin_city="DEL",
        destination_city="SIN",
        start_date=NOW.date(),
        end_date=NOW.date() + timedelta(days=4),
        raw_request="r",
        trip_spec_json="{}",
        trace_id="t",
        report_json="{}",
        now=NOW,
        trip_id="t1",
        attach_session=planning_snapshot("s1", "alice", version=2, saved_trip_id="t1"),
        expected_session_version=1,
    )


@pytest.mark.parametrize("deleter", ["user", "trip", "expiry"])
def test_deleted_data_is_never_recreated_by_a_late_completion(tmp_path: Path, deleter: str) -> None:
    store = open_store(tmp_path)
    path = tmp_path / "accounts.sqlite"
    if deleter == "expiry":
        seed_workspace(store, expires_at=NOW + timedelta(days=1))
    else:
        seed_workspace(store)
    if deleter == "trip":
        attach_trip(store)
    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    session = store.get_planning_session_snapshot(user_id="alice", session_id="s1")
    assert workspace is not None and session is not None
    reserved = store.reserve_post_plan_operation(
        user_id="alice",
        session_id="s1",
        operation=make_operation("propose", "late", session_version=session.version),
        expected_workspace_version=workspace.version,
        expected_session_version=session.version,
    )

    if deleter == "user":
        store.delete_user("alice")
    elif deleter == "trip":
        assert store.delete_trip("alice", "t1") is True
    else:
        assert store.delete_expired_planning_sessions(now=NOW + timedelta(days=5)) == 1

    with pytest.raises((PostPlanOperationNotReservedError, PostPlanWorkspaceNotFoundError)):
        store.commit_post_plan_operation(
            user_id="alice",
            session_id="s1",
            event_id="late",
            fingerprint=reserved.fingerprint,
            expected_workspace_version=reserved.reserved_workspace_version or 0,
            workspace=workspace.model_copy(update={"current_result_id": "r-late"}),
            session=session.model_copy(update={"version": session.version + 1}),
            report_json='{"late":true}',
        )

    reopened = AccountStore.open(path)
    for table in POST_PLAN_TABLES:
        assert rows(path, table) == 0, table
    assert (
        reopened.get_post_plan_result(user_id="alice", session_id="s1", result_id="r-late") is None
    )


# --------------------------------------------------------------------------- #
# Interrupted work is never dispatched again                                          #
# --------------------------------------------------------------------------- #


def test_an_unfinished_reservation_becomes_interrupted_and_keeps_its_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_INTERPRETER_CALLS_PER_SESSION", 1)
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, workspace, session = reserved_state(store)  # consumes the only interpreter slot

    interrupted = store.interrupt_stale_post_plan_operations(
        user_id="alice", session_id="s1", active_operation_ids=frozenset(), updated_at=NOW
    )

    assert [o.operation_id for o in interrupted] == [reserved.operation_id]
    assert interrupted[0].status == "interrupted" and interrupted[0].error_code
    advanced = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    assert advanced is not None and advanced.version == reserved.reserved_workspace_version + 1
    # The worker that survives its reservation cannot overwrite the newer state.
    with pytest.raises(PostPlanOperationNotReservedError):
        commit(store, reserved, workspace, session)
    # A retry is a NEW explicit action, and the interpreter budget is still spent.
    with pytest.raises(PostPlanQuotaError):
        store.reserve_post_plan_operation(
            user_id="alice",
            session_id="s1",
            operation=make_operation("propose", "retry", interpreter_calls=1),
            expected_workspace_version=advanced.version,
            expected_session_version=1,
        )
    # An identical replay of the interrupted request is answered, not re-dispatched.
    replay = store.reserve_post_plan_operation(
        user_id="alice",
        session_id="s1",
        operation=make_operation("propose", "p1", interpreter_calls=1),
        expected_workspace_version=1,
        expected_session_version=1,
    )
    assert replay.status == "interrupted"


def test_an_operation_this_process_is_running_is_left_alone(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, _, _ = reserved_state(store)

    interrupted = store.interrupt_stale_post_plan_operations(
        user_id="alice",
        session_id="s1",
        active_operation_ids=frozenset({reserved.operation_id}),
        updated_at=NOW,
    )

    assert interrupted == []
    current = store.get_post_plan_operation(user_id="alice", event_id="p1")
    assert current is not None and current.status == "reserved"


def test_a_failed_operation_is_terminal_keeps_its_budget_and_frees_the_workspace(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, workspace, session = reserved_state(store)

    failed = store.fail_post_plan_operation(
        user_id="alice",
        session_id="s1",
        event_id="p1",
        fingerprint=reserved.fingerprint,
        expected_workspace_version=reserved.reserved_workspace_version or 0,
        error_code="MODEL_TIMEOUT",
        updated_at=NOW,
    )

    assert failed.status == "failed" and failed.error_code == "MODEL_TIMEOUT"
    assert failed.interpreter_calls == 1
    with pytest.raises(PostPlanOperationNotReservedError):
        commit(store, reserved, workspace, session)
    moved = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    assert moved is not None
    run_operation(store, make_operation("propose", "next"))  # the workspace is usable again


def test_failing_with_a_wrong_fingerprint_is_a_conflict(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, _, _ = reserved_state(store)

    with pytest.raises(PostPlanOperationConflictError):
        store.fail_post_plan_operation(
            user_id="alice",
            session_id="s1",
            event_id="p1",
            fingerprint="not-the-request",
            expected_workspace_version=reserved.reserved_workspace_version or 0,
            error_code="X",
            updated_at=NOW,
        )


# --------------------------------------------------------------------------- #
# Privacy, trip deletion and expiry                                                    #
# --------------------------------------------------------------------------- #


def test_privacy_export_covers_every_post_plan_row_for_one_user(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "p1"))
    store.create_planning_session_snapshot(planning_snapshot("s-bob", "bob"))

    export = store.export_user("alice", now=NOW)

    assert [w.session_id for w in export.post_plan_workspaces] == ["s1"]
    assert [r.result_id for r in export.post_plan_results] == ["r1"]
    assert {o.event_id for o in export.post_plan_operations} == {"init:s1", "p1"}
    assert export == store.export_user("alice", now=NOW)  # deterministic
    assert "bob" not in export.model_dump_json().replace("alice@", "")


def test_account_deletion_leaves_no_post_plan_row_in_the_reopened_file(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "p1"))
    seed_workspace(store, user_id="bob", session_id="s-bob", result_id="rb")

    store.delete_user("alice")

    reopened = AccountStore.open(path)
    connection = sqlite3.connect(path)
    try:
        for table in AccountsBase.metadata.sorted_tables:
            if "user_id" in {c.name for c in table.columns}:
                (count,) = connection.execute(
                    f"SELECT COUNT(*) FROM {table.name} WHERE user_id = 'alice'"
                ).fetchone()
                assert count == 0, table.name
    finally:
        connection.close()
    assert reopened.get_post_plan_workspace(user_id="bob", session_id="s-bob") is not None


def test_deleting_a_trip_deletes_its_sessions_workspace_and_only_that(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    seed_workspace(store)
    seed_workspace(store, session_id="s2", result_id="r2")
    attach_trip(store)
    run_operation(store, make_operation("propose", "p1", session_version=2))

    assert store.delete_trip("alice", "t1") is True

    reopened = AccountStore.open(path)
    assert reopened.get_post_plan_workspace(user_id="alice", session_id="s1") is None
    assert reopened.get_post_plan_workspace(user_id="alice", session_id="s2") is not None
    assert rows(path, "post_plan_workspaces") == 1
    assert rows(path, "post_plan_results") == 1
    assert rows(path, "post_plan_operations") == 1  # only s2's initialise record remains


def test_expiry_sweeps_an_abandoned_workspace_but_keeps_one_attached_to_a_trip(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    soon = NOW + timedelta(days=1)
    seed_workspace(store, session_id="abandoned", result_id="ra", expires_at=soon)
    seed_workspace(store, session_id="s1", result_id="r1", expires_at=soon)
    attach_trip(store)

    swept = store.delete_expired_planning_sessions(now=EXPIRES + timedelta(days=60))

    assert swept == 1
    reopened = AccountStore.open(path)
    assert reopened.get_post_plan_workspace(user_id="alice", session_id="abandoned") is None
    assert reopened.get_post_plan_workspace(user_id="alice", session_id="s1") is not None


# --------------------------------------------------------------------------- #
# Initialising from a real finished plan                                               #
# --------------------------------------------------------------------------- #


def real_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, AccountStore, PlanningKit, dict[str, Any], str]:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit)
    return client, store, kit, session, str(client.get("/auth/me").json()["id"])


def planning_session(store: AccountStore, user_id: str, session_id: str) -> Any:
    found = PlanningSessionRepository(store).get(user_id=user_id, session_id=session_id)
    assert found is not None
    return found


def test_initialising_from_a_finished_job_calls_nothing_external(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, session, user_id = real_plan(tmp_path, monkeypatch)
    calls_before = dict(kit.llm.invocations)

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("initialisation must not open a connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    snapshot, created = service.initialize_from_job(
        store, user_id=user_id, session=planning_session(store, user_id, session["id"]), now=NOW
    )

    assert created is True and dict(kit.llm.invocations) == calls_before
    loaded = service.load_workspace(store, user_id=user_id, session_id=session["id"])
    assert loaded is not None
    state = job_manager.get_job(session["job_id"])
    assert state is not None and state.report is not None
    assert loaded.result.report_json == state.report.model_dump_json()  # exact bytes
    assert loaded.workspace.report_schema_fingerprint == report_schema_fingerprint()
    assert loaded.workspace.inventory is not None
    assert loaded.workspace.inventory.retained_hotel_area_id == state.report.itinerary.hotel_area_id
    assert loaded.snapshot.version == 1 and snapshot.expires_at == loaded.snapshot.expires_at


def test_initialising_twice_returns_the_existing_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, store, _kit, session, user_id = real_plan(tmp_path, monkeypatch)
    parsed = planning_session(store, user_id, session["id"])

    first, created_first = service.initialize_from_job(
        store, user_id=user_id, session=parsed, now=NOW
    )
    second, created_second = service.initialize_from_job(
        store, user_id=user_id, session=parsed, now=NOW + timedelta(hours=1)
    )

    assert (created_first, created_second) == (True, False)
    assert first == second


def test_initialisation_refuses_an_unfinished_lost_or_foreign_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, store, _kit, session, user_id = real_plan(tmp_path, monkeypatch)
    parsed = planning_session(store, user_id, session["id"])
    state = job_manager.get_job(session["job_id"])
    assert state is not None

    with pytest.raises(service.PlanUnavailableError):  # someone else's identity
        service.initialize_from_job(store, user_id="someone-else", session=parsed, now=NOW)
    held = state.report
    with state._lock:
        state.report = None
    with pytest.raises(service.PlanUnavailableError):  # not finished
        service.initialize_from_job(store, user_id=user_id, session=parsed, now=NOW)
    with state._lock:
        state.report = held
    with job_manager._lock:
        job_manager._jobs.pop(session["job_id"])
    with pytest.raises(service.PlanUnavailableError):  # lost to a restart: never rebuilt
        service.initialize_from_job(store, user_id=user_id, session=parsed, now=NOW)
    assert store.get_post_plan_workspace(user_id=user_id, session_id=session["id"]) is None


def test_an_unconfirmed_session_cannot_start_a_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from evals.a4_support import run_interview

    client, store = signed_in_client(tmp_path)
    PlanningKit(monkeypatch, tmp_path)
    review = run_interview(client)
    user_id = str(client.get("/auth/me").json()["id"])

    with pytest.raises(service.SessionNotConfirmedError):
        service.initialize_from_job(
            store, user_id=user_id, session=planning_session(store, user_id, review["id"]), now=NOW
        )


def save_trip_via_api(client: Any, session_id: str) -> str:
    response = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session_id, "client_event_id": "save-1"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["trip"]["id"])


def test_a_saved_revision_initialises_after_a_restart_with_its_exact_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, user_id = real_plan(tmp_path, monkeypatch)
    trip_id = save_trip_via_api(client, session["id"])
    with job_manager._lock:
        job_manager._jobs.pop(session["job_id"])  # the process-local job is gone
    stored = store.get_revision(user_id, trip_id, 1)

    snapshot, created = service.initialize_from_saved_revision(
        store,
        user_id=user_id,
        session=planning_session(store, user_id, session["id"]),
        trip_id=trip_id,
        revision=1,
        now=NOW,
    )

    assert created is True
    loaded = service.load_workspace(store, user_id=user_id, session_id=session["id"])
    assert loaded is not None and loaded.result.report_json == stored.report_json
    assert loaded.workspace.source.kind == "saved_revision"
    assert snapshot.saved_trip_id == trip_id


def write_revision(store: AccountStore, trip_id: str, number: int, report: dict[str, Any]) -> None:
    from accounts.db import TripRevisionRow

    revision = TripRevision(
        id=f"rev-{number}",
        trip_id=trip_id,
        revision=number,
        trace_id="t",
        report_json=json.dumps(report),
        created_at=NOW,
    )
    with Session(store._engine) as db:
        db.add(
            TripRevisionRow(
                id=revision.id, trip_id=trip_id, revision=number, payload=revision.model_dump_json()
            )
        )
        db.commit()


def test_history_that_todays_model_would_reshape_needs_a_rebuild_not_an_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, user_id = real_plan(tmp_path, monkeypatch)
    trip_id = save_trip_via_api(client, session["id"])
    first = json.loads(store.get_revision(user_id, trip_id, 1).report_json)
    older = {k: v for k, v in first.items() if k != "footer"}  # a field the older shape lacked
    write_revision(store, trip_id, 2, older)
    write_revision(store, trip_id, 3, {"legacy": "an older, unrelated shape"})
    parsed = planning_session(store, user_id, session["id"])

    for revision in (2, 3):
        with pytest.raises(service.WorkspaceRebuildRequiredError):
            service.initialize_from_saved_revision(
                store, user_id=user_id, session=parsed, trip_id=trip_id, revision=revision, now=NOW
            )

    assert store.get_post_plan_workspace(user_id=user_id, session_id=session["id"]) is None
    # The history itself stays readable verbatim through the saved-trip route.
    assert client.get(f"/account/trips/{trip_id}/revisions/3").json()["report"]["legacy"]


def test_a_revision_planned_for_a_different_trip_is_not_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, user_id = real_plan(tmp_path, monkeypatch)
    trip_id = save_trip_via_api(client, session["id"])
    report = json.loads(store.get_revision(user_id, trip_id, 1).report_json)
    report["trip_spec"]["destination_city"] = "BOM"
    write_revision(store, trip_id, 2, report)

    with pytest.raises(service.WorkspaceRebuildRequiredError, match="different trip"):
        service.initialize_from_saved_revision(
            store,
            user_id=user_id,
            session=planning_session(store, user_id, session["id"]),
            trip_id=trip_id,
            revision=2,
            now=NOW,
        )


def test_saved_revision_initialisation_checks_attachment_and_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, session, user_id = real_plan(tmp_path, monkeypatch)
    trip_id = save_trip_via_api(client, session["id"])
    other, _ = finished_plan(client, kit)
    other_session = planning_session(store, user_id, other["id"])

    with pytest.raises(service.SessionNotAttachedError):
        service.initialize_from_saved_revision(
            store, user_id=user_id, session=other_session, trip_id=trip_id, revision=1, now=NOW
        )
    with pytest.raises(UnknownTripError):
        service.initialize_from_saved_revision(
            store,
            user_id="someone-else",
            session=planning_session(store, user_id, session["id"]).model_copy(),
            trip_id=trip_id,
            revision=1,
            now=NOW,
        )
    with pytest.raises(store_module.UnknownRevisionError):
        service.initialize_from_saved_revision(
            store,
            user_id=user_id,
            session=planning_session(store, user_id, session["id"]),
            trip_id=trip_id,
            revision=9,
            now=NOW,
        )


def test_a_workspace_from_a_different_report_shape_is_not_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, store, _kit, session, user_id = real_plan(tmp_path, monkeypatch)
    service.initialize_from_job(
        store, user_id=user_id, session=planning_session(store, user_id, session["id"]), now=NOW
    )
    monkeypatch.setattr(service, "report_schema_fingerprint", lambda: "a-later-report-shape")

    with pytest.raises(service.WorkspaceRebuildRequiredError):
        service.load_workspace(store, user_id=user_id, session_id=session["id"])


def test_recovery_marks_only_reservations_this_process_does_not_run(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserved, _, _ = reserved_state(store)

    service.mark_active(reserved.operation_id)
    assert service.recover_interrupted(store, user_id="alice", session_id="s1", now=NOW) == []
    service.mark_finished(reserved.operation_id)
    recovered = service.recover_interrupted(store, user_id="alice", session_id="s1", now=NOW)

    assert [o.status for o in recovered] == ["interrupted"]
    assert service.active_operation_ids() == frozenset()
