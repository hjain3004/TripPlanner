"""CP4 Task 3 — the durable post-plan workspace, reservations and result commits.

The properties that matter, each proven against a real SQLite file: identical replay is
answered before any stale check; conflicting reuse is a typed conflict; client and system
ids live in separate namespaces; two genuine connections racing one expected version have
exactly one winner; a proposal gets exactly one terminal decision; budgets are consumed at
reservation; accepted results are immutable; and nothing leaks across owners.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier

import pytest
from sqlalchemy import create_engine

import accounts.store as store_module
from accounts.db import AccountsBase
from accounts.models import PostPlanOperation
from accounts.store import (
    AccountStore,
    PostPlanOperationConflictError,
    PostPlanOperationInProgressError,
    PostPlanProposalStateError,
    PostPlanQuotaError,
    PostPlanWorkspaceNotFoundError,
    StalePlanningSessionError,
    StalePostPlanBaseError,
    StalePostPlanWorkspaceError,
    UnknownPlanningSessionError,
)
from evals.cp4_support import (
    NOW,
    make_operation,
    open_store,
    planning_snapshot,
    run_operation,
    seed_workspace,
)


def reserve(
    store: AccountStore,
    operation: PostPlanOperation,
    *,
    workspace_version: int | None = None,
    session_version: int | None = None,
) -> PostPlanOperation:
    workspace = store.get_post_plan_workspace(user_id=operation.user_id, session_id="s1")
    session = store.get_planning_session_snapshot(user_id=operation.user_id, session_id="s1")
    assert workspace is not None and session is not None
    return store.reserve_post_plan_operation(
        user_id=operation.user_id,
        session_id=operation.session_id,
        operation=operation,
        expected_workspace_version=workspace_version or workspace.version,
        expected_session_version=session_version or session.version,
    )


# --------------------------------------------------------------------------- #
# Migration: the account database upgrades without touching existing rows        #
# --------------------------------------------------------------------------- #


def test_a_pre_cp4_database_upgrades_without_rewriting_a_single_row(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    store.add_wallet_entry(
        user_id="alice",
        card_id="hdfc-infinia",
        nickname="Main",
        now=NOW,
        points_balances={"hdfc-reward-points": 7},
    )
    trip = store.save_trip_with_revision(
        user_id="alice",
        title="DEL to SIN",
        origin_city="DEL",
        destination_city="SIN",
        start_date=NOW.date(),
        end_date=NOW.date() + timedelta(days=4),
        raw_request="r",
        trip_spec_json="{}",
        trace_id="t",
        report_json='{"summary":"as saved"}',
        now=NOW,
        client_event_id="save-1",
        request_fingerprint="fp",
    )
    store._engine.dispose()
    # Make the database exactly what the previous release left: the new tables did not exist.
    raw = sqlite3.connect(path)
    for table in ("post_plan_operations", "post_plan_results", "post_plan_workspaces"):
        raw.execute(f"DROP TABLE {table}")
    raw.commit()
    before = {
        table: raw.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
        for table in (
            "users",
            "wallet_entries",
            "wallet_mutation_events",
            "saved_trips",
            "trip_revisions",
            "trip_mutation_events",
        )
    }
    raw.close()

    reopened = AccountStore.open(path)
    AccountStore.open(path)  # and again: idempotent

    raw = sqlite3.connect(path)
    after = {
        table: raw.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall() for table in before
    }
    tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    raw.close()
    assert after == before
    assert {"post_plan_workspaces", "post_plan_results", "post_plan_operations"} <= tables
    (kept,) = reopened.revisions("alice", trip.trip.id)
    assert kept.report_json == '{"summary":"as saved"}'


def test_reseeding_does_not_touch_the_new_tables() -> None:
    assert {"post_plan_workspaces", "post_plan_results", "post_plan_operations"} <= set(
        AccountsBase.metadata.tables
    )


# --------------------------------------------------------------------------- #
# Creating the workspace                                                         #
# --------------------------------------------------------------------------- #


def test_a_workspace_is_created_once_with_its_first_result(tmp_path: Path) -> None:
    store = open_store(tmp_path)

    created = seed_workspace(store)
    again, was_created = store.create_post_plan_workspace(
        workspace=created,
        result=store.get_post_plan_result(user_id="alice", session_id="s1", result_id="r1"),  # type: ignore[arg-type]
        operation=make_operation(
            "propose", "init:s1", event_source="system", workspace_version=0
        ).model_copy(update={"kind": "initialize", "status": "complete", "fingerprint": "init"}),
    )

    assert again == created and was_created is False
    result = store.get_post_plan_result(user_id="alice", session_id="s1", result_id="r1")
    assert result is not None and result.report_json == '{"n":1}'


def test_a_workspace_needs_an_owned_session(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.create_planning_session_snapshot(planning_snapshot("s-bob", "bob"))
    ours = seed_workspace(store)

    for owner, session_id in (("alice", "s-bob"), ("alice", "no-such-session")):
        with pytest.raises(UnknownPlanningSessionError):
            store.create_post_plan_workspace(
                workspace=ours.model_copy(update={"session_id": session_id, "user_id": owner}),
                result=store.get_post_plan_result(  # type: ignore[arg-type]
                    user_id="alice", session_id="s1", result_id="r1"
                ).model_copy(update={"session_id": session_id}),
                operation=make_operation("propose", "x", session_id=session_id).model_copy(
                    update={"kind": "initialize", "status": "complete"}
                ),
            )
    assert store.get_post_plan_workspace(user_id="alice", session_id="s-bob") is None


def test_another_user_can_neither_read_nor_reserve_against_a_workspace(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)

    assert store.get_post_plan_workspace(user_id="bob", session_id="s1") is None
    assert store.get_post_plan_result(user_id="bob", session_id="s1", result_id="r1") is None
    with pytest.raises(PostPlanWorkspaceNotFoundError):
        store.reserve_post_plan_operation(
            user_id="bob",
            session_id="s1",
            operation=make_operation("propose", "e1", user_id="bob"),
            expected_workspace_version=1,
            expected_session_version=1,
        )


def test_accepted_results_have_no_update_or_delete_method() -> None:
    forbidden = {"update_post_plan_result", "delete_post_plan_result", "edit_post_plan_result"}

    assert forbidden.isdisjoint(dir(AccountStore))


# --------------------------------------------------------------------------- #
# Reservation: replay first, conflict, namespaces, concurrency                    #
# --------------------------------------------------------------------------- #


def test_reserving_advances_the_workspace_version_and_returns_it(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)

    reserved = reserve(store, make_operation("propose", "e1"))

    assert reserved.status == "reserved" and reserved.reserved_workspace_version == 2
    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    assert workspace is not None and workspace.version == 2
    assert reserved.base_result_id == "r1"


def test_an_identical_replay_is_answered_before_any_stale_check(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    operation = make_operation("propose", "e1")
    first = reserve(store, operation)

    # The workspace has since moved on; the retried request must still get its answer.
    replay = store.reserve_post_plan_operation(
        user_id="alice",
        session_id="s1",
        operation=operation,
        expected_workspace_version=1,  # stale
        expected_session_version=99,  # stale
    )

    assert replay == first
    assert len(store.post_plan_operations(user_id="alice", session_id="s1")) == 2  # init + e1


def test_reusing_an_event_id_for_a_different_request_is_a_typed_conflict(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserve(store, make_operation("propose", "e1", fingerprint="the-original-request"))

    with pytest.raises(PostPlanOperationConflictError):
        store.reserve_post_plan_operation(
            user_id="alice",
            session_id="s1",
            operation=make_operation("propose", "e1", fingerprint="a-different-request"),
            expected_workspace_version=2,
            expected_session_version=1,
        )


def test_client_and_system_ids_are_separate_namespaces(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    client = make_operation("propose", "same-id", event_source="client")
    run_operation(store, client)

    system = run_operation(
        store, make_operation("save", "same-id", event_source="system", operation_id="op-sys")
    )

    assert system.event_source == "system" and system.status == "complete"
    sources = {
        (o.event_source, o.event_id)
        for o in store.post_plan_operations(user_id="alice", session_id="s1")
    }
    assert ("client", "same-id") in sources and ("system", "same-id") in sources


def test_stale_workspace_and_session_versions_are_typed(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)

    with pytest.raises(StalePostPlanWorkspaceError) as workspace_stale:
        store.reserve_post_plan_operation(
            user_id="alice",
            session_id="s1",
            operation=make_operation("propose", "a"),
            expected_workspace_version=7,
            expected_session_version=1,
        )
    with pytest.raises(StalePlanningSessionError):
        store.reserve_post_plan_operation(
            user_id="alice",
            session_id="s1",
            operation=make_operation("propose", "b"),
            expected_workspace_version=1,
            expected_session_version=7,
        )

    assert workspace_stale.value.current_version == 1
    assert (
        len(store.post_plan_operations(user_id="alice", session_id="s1")) == 1
    )  # nothing recorded


def test_only_one_operation_may_be_in_flight(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    reserve(store, make_operation("propose", "first"))

    with pytest.raises(PostPlanOperationInProgressError):
        reserve(store, make_operation("propose", "second"))


def test_two_connections_competing_at_one_version_have_exactly_one_winner(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    seed_workspace(store)
    gate = Barrier(2)

    def attempt(label: str) -> str:
        own = AccountStore.open(path)  # a separate connection
        gate.wait()
        try:
            own.reserve_post_plan_operation(
                user_id="alice",
                session_id="s1",
                operation=make_operation("propose", label),
                expected_workspace_version=1,
                expected_session_version=1,
            )
            return "won"
        except StalePostPlanWorkspaceError:
            return "stale"
        except PostPlanOperationInProgressError:
            return "in_progress"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, ["tab-a", "tab-b"]))

    assert outcomes.count("won") == 1 and len(outcomes) == 2, outcomes
    operations = AccountStore.open(path).post_plan_operations(user_id="alice", session_id="s1")
    assert [o.status for o in operations if o.kind == "propose"] == ["reserved"]


def test_two_connections_submitting_the_same_event_apply_once(tmp_path: Path) -> None:
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    seed_workspace(store)
    gate = Barrier(2)

    def attempt(_: int) -> str:
        own = AccountStore.open(path)
        gate.wait()
        return own.reserve_post_plan_operation(
            user_id="alice",
            session_id="s1",
            operation=make_operation("propose", "same"),
            expected_workspace_version=1,
            expected_session_version=1,
        ).operation_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(attempt, range(2)))

    assert ids[0] == ids[1]
    workspace = AccountStore.open(path).get_post_plan_workspace(user_id="alice", session_id="s1")
    assert workspace is not None and workspace.version == 2  # advanced once, not twice


# --------------------------------------------------------------------------- #
# Budgets are consumed at reservation and never returned                           #
# --------------------------------------------------------------------------- #


def test_the_interpreter_budget_is_consumed_at_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_INTERPRETER_CALLS_PER_SESSION", 2)
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "a", interpreter_calls=1))
    # A reservation that fails still holds its slot: the model may already have been called.
    second = reserve(store, make_operation("propose", "b", interpreter_calls=1))
    store.fail_post_plan_operation(
        user_id="alice",
        session_id="s1",
        event_id="b",
        fingerprint="fp-b",
        expected_workspace_version=second.reserved_workspace_version or 0,
        error_code="MODEL_TIMEOUT",
        updated_at=NOW,
    )

    with pytest.raises(PostPlanQuotaError) as exceeded:
        reserve(store, make_operation("propose", "c", interpreter_calls=1))

    assert exceeded.value.quota == "interpreter_calls"
    run_operation(store, make_operation("propose", "d"))  # deterministic work is unaffected


def test_scoped_replan_and_record_caps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store_module, "MAX_SCOPED_REPLANS_PER_SESSION", 1)
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "p1"))
    run_operation(store, make_operation("propose", "p2"))
    run_operation(
        store,
        make_operation(
            "approve", "ap1", proposal_id="op-p1", action_kind="scoped_itinerary_replan"
        ),
    )

    with pytest.raises(PostPlanQuotaError) as replans:
        reserve(
            store,
            make_operation(
                "approve", "ap2", proposal_id="op-p2", action_kind="scoped_itinerary_replan"
            ),
        )
    assert replans.value.quota == "scoped_replans"

    monkeypatch.setattr(store_module, "MAX_POST_PLAN_RECORDS_PER_SESSION", 4)
    with pytest.raises(PostPlanQuotaError) as records:
        reserve(store, make_operation("propose", "p3"))
    assert records.value.quota == "records"


# --------------------------------------------------------------------------- #
# Proposals have exactly one terminal decision                                      #
# --------------------------------------------------------------------------- #


def test_a_proposal_is_decided_once(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    proposed = run_operation(store, make_operation("propose", "p1"))
    assert proposed.decision == "pending"

    run_operation(store, make_operation("approve", "ap1", proposal_id="op-p1"))

    for kind, event in (("approve", "ap2"), ("reject", "rj1")):
        with pytest.raises(PostPlanProposalStateError):
            reserve(store, make_operation(kind, event, proposal_id="op-p1"))  # type: ignore[arg-type]
    decided = store.get_post_plan_operation_by_id(
        user_id="alice", session_id="s1", operation_id="op-p1"
    )
    assert decided is not None and decided.decision == "approved"


def test_rejecting_decides_the_proposal_without_touching_the_result(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "p1"))

    rejected = run_operation(store, make_operation("reject", "rj1", proposal_id="op-p1"))

    assert rejected.result_id == "r1"
    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    assert workspace is not None and workspace.current_result_id == "r1"
    with pytest.raises(PostPlanProposalStateError):
        reserve(store, make_operation("approve", "ap1", proposal_id="op-p1"))


def test_an_unknown_or_foreign_proposal_cannot_be_approved(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)

    with pytest.raises(PostPlanProposalStateError):
        reserve(store, make_operation("approve", "ap1", proposal_id="nope"))


def test_a_proposal_made_against_an_older_result_cannot_be_approved(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "pa"))
    run_operation(store, make_operation("propose", "pb"))
    run_operation(
        store,
        make_operation("approve", "apa", proposal_id="op-pa"),
        report_json='{"n":2}',
        new_result_id="r2",
    )

    with pytest.raises(StalePostPlanBaseError):
        reserve(store, make_operation("approve", "apb", proposal_id="op-pb"))
    pending = store.get_post_plan_operation_by_id(
        user_id="alice", session_id="s1", operation_id="op-pb"
    )
    assert (
        pending is not None and pending.decision == "pending"
    )  # still decidable by a new proposal


# --------------------------------------------------------------------------- #
# Commits                                                                          #
# --------------------------------------------------------------------------- #


def test_committing_a_report_adds_an_immutable_result_and_moves_the_pointer(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    run_operation(store, make_operation("propose", "p1"))

    done = run_operation(
        store,
        make_operation("approve", "ap1", proposal_id="op-p1"),
        report_json='{"n":2}',
        new_result_id="r2",
    )

    assert done.status == "complete" and done.result_id == "r2"
    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    assert workspace is not None and workspace.current_result_id == "r2"
    old = store.get_post_plan_result(user_id="alice", session_id="s1", result_id="r1")
    new = store.get_post_plan_result(user_id="alice", session_id="s1", result_id="r2")
    assert old is not None and old.report_json == '{"n":1}'  # the earlier result is untouched
    assert new is not None and new.report_json == '{"n":2}'
    session = store.get_planning_session_snapshot(user_id="alice", session_id="s1")
    assert session is not None and session.version == 3  # one bump per committed operation


def test_a_duplicate_completion_is_harmless_and_a_late_one_cannot_apply(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    operation = make_operation("propose", "p1")
    first = run_operation(store, operation)

    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    session = store.get_planning_session_snapshot(user_id="alice", session_id="s1")
    assert workspace is not None and session is not None
    again = store.commit_post_plan_operation(
        user_id="alice",
        session_id="s1",
        event_id="p1",
        fingerprint=operation.fingerprint,
        expected_workspace_version=first.reserved_workspace_version or 0,
        workspace=workspace,
        session=session.model_copy(update={"version": 99}),
        report_json=None,
    )

    assert again == first
    assert store.get_planning_session_snapshot(user_id="alice", session_id="s1") == session


def test_a_commit_cannot_smuggle_a_result_change_without_a_report(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    seed_workspace(store)
    operation = make_operation("propose", "p1")
    reserved = reserve(store, operation)
    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    session = store.get_planning_session_snapshot(user_id="alice", session_id="s1")
    assert workspace is not None and session is not None

    with pytest.raises(ValueError, match="current result"):
        store.commit_post_plan_operation(
            user_id="alice",
            session_id="s1",
            event_id="p1",
            fingerprint=operation.fingerprint,
            expected_workspace_version=reserved.reserved_workspace_version or 0,
            workspace=workspace.model_copy(update={"current_result_id": "r-forged"}),
            session=session.model_copy(update={"version": 2}),
            report_json=None,
        )
    with pytest.raises(ValueError, match="new result id"):
        store.commit_post_plan_operation(
            user_id="alice",
            session_id="s1",
            event_id="p1",
            fingerprint=operation.fingerprint,
            expected_workspace_version=reserved.reserved_workspace_version or 0,
            workspace=workspace,
            session=session.model_copy(update={"version": 2}),
            report_json='{"n":9}',
        )
    assert (
        store.get_post_plan_result(user_id="alice", session_id="s1", result_id="r-forged") is None
    )


def test_an_oversized_report_is_refused_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store_module, "MAX_REPORT_BYTES", 8)
    store = open_store(tmp_path)
    seed_workspace(store, report_json='{"n":1}')
    run_operation(store, make_operation("propose", "p1"))

    with pytest.raises(store_module.ReportTooLargeError):
        run_operation(
            store,
            make_operation("approve", "ap1", proposal_id="op-p1"),
            report_json='{"blob":"' + "x" * 50 + '"}',
            new_result_id="r2",
        )

    workspace = store.get_post_plan_workspace(user_id="alice", session_id="s1")
    assert workspace is not None and workspace.current_result_id == "r1"
    assert store.get_post_plan_result(user_id="alice", session_id="s1", result_id="r2") is None


def test_the_engine_can_be_a_plain_second_connection(tmp_path: Path) -> None:
    """A store built from a bare engine (as tests and workers do) behaves identically."""
    path = tmp_path / "accounts.sqlite"
    store = open_store(tmp_path)
    seed_workspace(store)
    other = AccountStore(create_engine(f"sqlite:///{path}"))

    assert other.get_post_plan_workspace(user_id="alice", session_id="s1") == (
        store.get_post_plan_workspace(user_id="alice", session_id="s1")
    )
