"""Durable planning jobs: what survives a restart, what is interrupted, what never repeats.

Real SQLite, real API (``TestClient``), scripted offline LLM. "Restart" here is the in-process
shortcut (``simulate_restart``); the real process-kill demonstration is
``evals/test_durable_jobs_process_restart.py``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from accounts.db import AccountsBase
from accounts.models import PLANNING_JOB_RETENTION_DAYS
from accounts.store import AccountStore
from api import conversation
from api.job_manager import job_manager
from api.main import app
from evals.a4_support import (
    PlanningKit,
    confirm,
    csrf,
    finished_plan,
    run_interview,
    second_client,
    signed_in_client,
    simulate_restart,
    wait_for_job,
)

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _user_id(client: TestClient) -> str:
    return str(client.get("/auth/me").json()["id"])


def _hold_intake(kit: PlanningKit) -> tuple[threading.Event, threading.Event]:
    """Block the next intake call until released; returns (entered, release)."""
    entered, release = threading.Event(), threading.Event()
    original = kit.llm.complete_json

    def held(*, node: str, **kwargs: Any) -> Any:
        if node == "intake":
            entered.set()
            assert release.wait(timeout=30), "test never released the held intake call"
        return original(node=node, **kwargs)

    kit.llm.complete_json = held  # type: ignore[method-assign]
    return entered, release


def _job(client: TestClient, session_id: str) -> Any:
    return client.get(f"/planning/sessions/{session_id}/job")


def _wait_for_calls(kit: PlanningKit, node: str, count: int = 1) -> None:
    deadline = time.monotonic() + 30
    while kit.llm.invocations.get(node, 0) < count and time.monotonic() < deadline:
        time.sleep(0.05)
    assert kit.llm.invocations.get(node, 0) >= count


def _started_job(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    """A confirmed session whose job row exists (queued) but whose worker never starts."""
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    return str(confirm(client, run_interview(client))["job_id"])


# --- 1. a finished job survives a restart ---------------------------------------------------- #


def test_a_completed_plan_and_its_report_survive_a_restart_byte_for_byte(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, before = finished_plan(client, kit)
    calls = dict(kit.llm.invocations)

    simulate_restart(monkeypatch)
    after = _job(client, session["id"])
    legacy = client.get(f"/plan/{session['job_id']}")

    assert after.status_code == 200 and after.json() == before
    assert legacy.status_code == 200 and legacy.json() == before
    assert dict(kit.llm.invocations) == calls  # reading is not planning
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "complete" and stored.report_json is not None


def test_a_traveler_edit_is_part_of_the_durable_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, job = finished_plan(client, kit)
    revision = job["report"]["travel_inventory"]["inventory_revision"]
    body = {
        "expected_inventory_revision": revision,
        "edit": {"op": "remove_item", "poi_id": "sg-hawker-maxwell", "day_index": 0},
    }
    edited = client.post(
        f"/planning/sessions/{session['id']}/recompute", headers=csrf(client), json=body
    )
    assert edited.status_code == 200, edited.text

    simulate_restart(monkeypatch)

    assert _job(client, session["id"]).json()["report"] == edited.json()
    # The edit is an optimistic-concurrency write: the same revision cannot be edited twice.
    stale = client.post(
        f"/planning/sessions/{session['id']}/recompute", headers=csrf(client), json=body
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "INVENTORY_REVIEW_REQUIRED"


# --- 2. ownership: a stranger cannot tell a job from a missing one --------------------------- #


def test_another_owner_gets_exactly_the_response_for_a_missing_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job_body = finished_plan(client, kit)
    stranger = second_client("stranger@example.com")
    simulate_restart(monkeypatch)

    real = stranger.get(f"/plan/{session['job_id']}")
    missing = stranger.get("/plan/" + "0" * 32)
    anonymous = TestClient(app, base_url="https://testserver").get(f"/plan/{session['job_id']}")

    assert real.status_code == missing.status_code == 404
    assert real.json() == missing.json() == {"detail": "Job not found"}
    assert anonymous.status_code == 404 and anonymous.json() == missing.json()
    # the session route is owner-scoped too: the stranger cannot see the session at all
    assert _job(stranger, session["id"]).status_code in {403, 404}


# --- 3. interruption is represented truthfully, and nothing re-dispatches ---------------------- #


def test_work_interrupted_by_a_restart_reads_failed_interrupted_and_is_never_redispatched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    entered, release = _hold_intake(kit)
    kit.queue_run()
    session = confirm(client, run_interview(client))
    assert entered.wait(timeout=30)  # the pipeline is mid-flight, inside a model call
    assert _job(client, session["id"]).json()["status"] == "running"
    calls = dict(kit.llm.invocations)

    simulate_restart(monkeypatch)
    replay = client.post(  # re-sending the same confirmation must not start a second job
        f"/planning/sessions/{session['id']}/confirm",
        headers=csrf(client),
        json={
            "expected_version": session["version"],
            "brief": client.get(f"/planning/sessions/{session['id']}").json()["brief"],
            "client_event_id": "confirm-1",
        },
    )
    first = _job(client, session["id"])
    again = client.get(f"/plan/{session['job_id']}")  # polling again must not change anything

    body = first.json()
    assert first.status_code == 200 and body["status"] == "failed"
    assert body["error"]["code"] == "JOB_INTERRUPTED"
    assert "may already have been made" in body["error"]["message"]
    assert "Nothing was repeated automatically" in body["error"]["message"]
    assert body["report"] is None and again.json()["error"] == body["error"]
    assert replay.status_code == 202 and replay.json()["job_id"] == session["job_id"]
    assert dict(kit.llm.invocations) == calls  # no model call was dispatched by any of it
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "interrupted" and stored.calls_may_have_started is True
    assert stored.stage == "intake" and stored.report_json is None
    release.set()  # the "old process" thread wakes late and runs to its end
    _wait_for_calls(kit, "explainer")
    time.sleep(0.3)
    (after,) = store.planning_jobs(_user_id(client))
    assert after.status == "interrupted" and after.report_json is None  # it published nothing


def test_a_job_that_never_started_says_no_call_was_made(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    session = confirm(client, run_interview(client))
    assert _job(client, session["id"]).json()["status"] == "queued"

    simulate_restart(monkeypatch)
    body = _job(client, session["id"]).json()

    assert body["status"] == "failed" and body["error"]["code"] == "JOB_INTERRUPTED"
    assert "before any planning stage had begun" in body["error"]["message"]
    assert "no model or provider call was started" in body["error"]["message"]
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.calls_may_have_started is False


def test_the_traveler_retries_an_interrupted_plan_through_the_normal_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    entered, release = _hold_intake(kit)
    kit.queue_run()
    session = confirm(client, run_interview(client))
    assert entered.wait(timeout=30)
    simulate_restart(monkeypatch)
    assert _job(client, session["id"]).json()["error"]["code"] == "JOB_INTERRUPTED"
    release.set()
    _wait_for_calls(kit, "explainer")
    # polling moved the session to FAILED, which is the state the existing retry expects
    current = client.get(f"/planning/sessions/{session['id']}").json()
    assert current["status"] == "failed" and current["planning_error"]

    kit.queue_run(summary="Second attempt.")
    retry = client.post(
        f"/planning/sessions/{session['id']}/confirm",
        headers=csrf(client),
        json={
            "expected_version": current["version"],
            "brief": current["brief"],
            "client_event_id": "confirm-retry",
        },
    )

    assert retry.status_code == 202, retry.text
    assert retry.json()["job_id"] != session["job_id"]
    done = wait_for_job(client, session["id"])
    assert done["status"] == "complete" and done["report"]["summary"] == "Second attempt."
    states = {j.job_id: j.status for j in store.planning_jobs(_user_id(client))}
    assert states[session["job_id"]] == "interrupted"
    assert states[retry.json()["job_id"]] == "complete"


def test_a_session_whose_job_record_never_existed_reads_interrupted_not_queued_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    session = confirm(client, run_interview(client))
    with store._engine.begin() as connection:  # as a build from before this feature left it
        connection.execute(text("DELETE FROM planning_jobs"))
    assert _job(client, session["id"]).json()["status"] == "queued"  # inside the start window

    monkeypatch.setattr(conversation, "_JOB_RECORD_GRACE", timedelta(seconds=0))
    body = _job(client, session["id"]).json()

    assert body["status"] == "failed" and body["error"]["code"] == "JOB_INTERRUPTED"
    assert "cannot be established" in body["error"]["message"]


def test_a_job_whose_worker_stopped_without_publishing_does_not_read_running_forever(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)
    assert client.get(f"/plan/{job_id}").json()["status"] == "queued"  # a worker handle exists

    job_manager._forget(job_id)  # the worker is gone (died, or its final write was lost)
    body = client.get(f"/plan/{job_id}").json()

    assert body["status"] == "failed" and body["error"]["code"] == "JOB_INTERRUPTED"


def test_a_final_write_that_keeps_failing_is_reported_not_left_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import OperationalError

    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    kit.queue_run()

    def locked(*_: Any, **__: Any) -> bool:
        raise OperationalError("UPDATE planning_jobs", {}, Exception("database is locked"))

    monkeypatch.setattr(store, "finish_planning_job", locked)
    monkeypatch.setattr("api.job_manager.time.sleep", lambda _s: None)
    session = confirm(client, run_interview(client))

    done = wait_for_job(client, session["id"])

    assert done["status"] == "failed" and done["error"]["code"] == "JOB_INTERRUPTED"
    assert done["report"] is None


def test_a_dispatch_failure_closes_the_job_instead_of_leaving_it_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)

    def boom(session: Any, job_id: str) -> None:
        raise RuntimeError("thread could not start")

    monkeypatch.setattr(conversation, "_start_legacy_job", boom)
    review = run_interview(client)
    failed = client.post(
        f"/planning/sessions/{review['id']}/confirm",
        headers=csrf(client),
        json={
            "expected_version": review["version"],
            "brief": review["brief"],
            "client_event_id": "confirm-boom",
        },
    )

    assert failed.status_code == 503
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "failed" and stored.error_code == "PLANNING_START_FAILED"
    assert stored.job_id not in job_manager._stores  # no leaked worker handle


def test_a_stuck_job_of_this_process_does_not_block_the_next_rerun_of_the_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    user_id = _user_id(client)
    session_id = str(confirm(client, run_interview(client))["id"])

    def start(job: str, event: str) -> tuple[str, bool]:
        return job_manager.start_job(
            job,
            owner_id=user_id,
            session_id=session_id,
            store=store,
            kind="rerun",
            trip_id="trip-x",
            start_event_id=event,
            start_fingerprint="fp",
            one_live_per_trip=True,
        )

    start("rerun-1", "e1")
    from api.saved_trips import RerunInProgressError

    with pytest.raises(RerunInProgressError):  # a genuinely live one still blocks
        start("rerun-2", "e2")
    job_manager._forget("rerun-1")  # its worker is gone (final write lost); nobody polled it

    assert start("rerun-3", "e3") == ("rerun-3", True)


def test_a_complete_that_raises_still_releases_the_worker_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)
    assert job_id in job_manager._stores

    def explode(*_: Any, **__: Any) -> bool:
        raise ValueError("unexpected")

    monkeypatch.setattr(store, "finish_planning_job", explode)
    job_manager.complete(job_id, "failed", error={"code": "X", "message": "m", "trace_id": ""})

    assert job_id not in job_manager._stores
    assert client.get(f"/plan/{job_id}").json()["error"]["code"] == "JOB_INTERRUPTED"


def test_a_saved_trips_session_whose_job_expired_says_expired_and_is_not_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _ = finished_plan(client, kit)
    saved = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "save-1"},
    )
    assert saved.status_code == 201, saved.text
    with store._engine.begin() as connection:  # the 30-day sweep removed the working copy
        connection.execute(text("DELETE FROM planning_jobs"))
    monkeypatch.setattr(conversation, "_JOB_RECORD_GRACE", timedelta(seconds=0))

    body = _job(client, session["id"]).json()

    assert body["status"] == "failed" and body["error"]["code"] == "JOB_EXPIRED"
    assert "restarted" not in body["error"]["message"]
    assert client.get(f"/planning/sessions/{session['id']}").json()["status"] != "failed"


# --- 4. stale, late and repeated executions cannot overwrite newer state --------------------- #


def test_a_stale_completion_from_a_replaced_process_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)
    old_process = job_manager.process_id
    assert store.advance_planning_job(
        job_id, process_id=old_process, stage="intake", stage_index=0, now=NOW
    )
    simulate_restart(monkeypatch)
    store.get_planning_job(job_id, process_id=job_manager.process_id, now=NOW)  # marks interrupted

    published = store.finish_planning_job(
        job_id, process_id=old_process, status="complete", now=NOW, report_json="{}"
    )
    advanced = store.advance_planning_job(
        job_id, process_id=old_process, stage="costing", stage_index=2, now=NOW
    )

    assert published is False and advanced is False
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "interrupted" and stored.report_json is None
    assert stored.stage == "intake"


def test_a_job_is_published_once_and_a_second_outcome_cannot_replace_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)
    me = job_manager.process_id

    first = store.finish_planning_job(
        job_id, process_id=me, status="failed", now=NOW, error={"code": "X", "message": "first"}
    )
    second = store.finish_planning_job(job_id, process_id=me, status="complete", now=NOW)

    assert (first, second) == (True, False)
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "failed" and stored.error_message == "first"


def test_another_process_cannot_publish_to_a_live_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)

    assert not store.finish_planning_job(
        job_id, process_id="some-other-process", status="complete", now=NOW
    )
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "queued"


def test_an_oversized_report_is_published_as_a_typed_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)

    store.finish_planning_job(
        job_id,
        process_id=job_manager.process_id,
        status="complete",
        now=NOW,
        report_json="x" * (2 * 1024 * 1024 + 1),
    )

    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "failed" and stored.error_code == "REPORT_TOO_LARGE"
    assert stored.report_json is None


# --- 5. deletion wins over a late completion --------------------------------------------------- #


def test_deleting_the_account_while_work_is_pending_cannot_be_undone_by_its_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    entered, release = _hold_intake(kit)
    kit.queue_run()
    session = confirm(client, run_interview(client))
    assert entered.wait(timeout=30)
    user_id = _user_id(client)
    assert len(store.planning_jobs(user_id)) == 1

    store.delete_user(user_id)
    release.set()  # the worker finishes its whole pipeline and tries to publish
    _wait_for_calls(kit, "explainer")
    deadline = time.monotonic() + 10
    while session["job_id"] in job_manager._stores and time.monotonic() < deadline:
        time.sleep(0.05)

    assert session["job_id"] not in job_manager._stores
    assert store.planning_jobs(user_id) == []
    with store._engine.begin() as connection:
        for table in ("planning_jobs", "planning_sessions", "users"):
            assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 0, table


def test_a_job_cannot_be_started_for_a_deleted_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    user_id = _user_id(client)
    store.delete_user(user_id)

    with pytest.raises(Exception, match="no such user"):
        job_manager.start_job("late-job", owner_id=user_id, session_id="s", store=store)
    assert store.planning_jobs(user_id) == []


# --- 6. privacy, retention, migration --------------------------------------------------------- #


def test_jobs_are_in_the_privacy_export_and_removed_with_the_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _ = finished_plan(client, kit)
    user_id = _user_id(client)

    export = store.export_user(user_id, now=NOW)
    assert [j.job_id for j in export.planning_jobs] == [session["job_id"]]
    assert export.planning_jobs[0].report_json is not None

    store.delete_user(user_id)
    assert store.planning_jobs(user_id) == []


def test_finished_jobs_expire_but_live_jobs_are_never_swept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    finished, _ = finished_plan(client, kit)
    live_id = _started_job(client, monkeypatch)
    later = datetime.now(UTC) + timedelta(days=PLANNING_JOB_RETENTION_DAYS + 1)

    assert store.delete_expired_planning_jobs(now=later) == 1

    remaining = {j.job_id: j.status for j in store.planning_jobs(_user_id(client))}
    assert remaining == {live_id: "queued"} and finished["job_id"] not in remaining


def test_a_database_from_before_this_feature_opens_without_losing_anything(
    tmp_path: Path,
) -> None:
    path = tmp_path / "accounts.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    AccountsBase.metadata.create_all(engine)
    store = AccountStore(engine)
    user = store.create_user(email="old@example.com", now=NOW)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE planning_jobs"))
    engine.dispose()
    assert "planning_jobs" not in inspect(create_engine(f"sqlite:///{path}")).get_table_names()

    reopened = AccountStore.open(path)

    assert reopened.get_user(user.id) is not None
    assert reopened.planning_jobs(user.id) == []
    assert "planning_jobs" in inspect(create_engine(f"sqlite:///{path}")).get_table_names()


# --- 7. anonymous jobs keep their old, in-memory semantics ------------------------------------ #


def test_an_anonymous_plan_is_not_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    kit.queue_run()
    anonymous = TestClient(app, base_url="https://testserver")

    started = anonymous.post(
        "/plan", json={"raw_request": "Singapore for 3 days", "wallet": {"card_ids": []}}
    )
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    body: dict[str, Any] = {}
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = anonymous.get(f"/plan/{job_id}").json()
        if body["status"] not in {"queued", "running"}:
            break
        time.sleep(0.05)

    assert body["status"] in {"complete", "needs_clarification", "failed"}
    with store._engine.begin() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM planning_jobs")).scalar() == 0


def test_startup_reconciliation_interrupts_every_orphaned_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    job_id = _started_job(client, monkeypatch)
    simulate_restart(monkeypatch)

    assert job_manager.reconcile(store) == [job_id]
    assert job_manager.reconcile(store) == []  # idempotent
    (stored,) = store.planning_jobs(_user_id(client))
    assert stored.status == "interrupted"


def test_two_simultaneous_identical_starts_make_one_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store = signed_in_client(tmp_path)
    user_id = _user_id(client)
    monkeypatch.setattr(conversation, "_start_legacy_job", lambda session, job_id: None)
    session = confirm(client, run_interview(client))
    outcomes: list[tuple[str, bool]] = []

    def start(n: int) -> None:
        outcomes.append(
            job_manager.start_job(
                f"job-{n}",
                owner_id=user_id,
                session_id=session["id"],
                store=store,
                kind="rerun",
                trip_id="trip-x",
                start_event_id="same-event",
                start_fingerprint="fp",
            )
        )

    threads = [threading.Thread(target=start, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sum(1 for _id, created in outcomes if created) == 1
    assert len({job_id for job_id, _created in outcomes}) == 1
