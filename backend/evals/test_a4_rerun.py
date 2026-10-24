"""A4 Task 6 — re-running a saved trip into a new revision.

A re-run recompiles the attached session's latest confirmed brief with the caller's
*current* wallet, runs the unchanged confirmed-planning job against current reference
data, and — only if that job completes with a report — appends it as the next
revision, server-side, once. Nothing here changes revision 1.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import accounts.store as store_module
import api.main as api_main
from accounts.models import UserProfile
from accounts.store import AccountStore
from api import saved_trips
from api.main import app
from core.db import SEEDS_DIR, load_kb, seed_database
from core.models import UserWallet
from evals.a4_support import (
    PlanningKit,
    csrf,
    finished_plan,
    second_client,
    signed_in_client,
)

ZERO_WALLET = UserWallet(card_ids=[])


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    saved_trips._RERUNS.clear()
    saved_trips._ACTIVE_BY_TRIP.clear()
    saved_trips._START_EVENTS.clear()
    yield
    app.dependency_overrides.clear()


def _user_id(client: TestClient) -> str:
    return str(client.get("/auth/me").json()["id"])


def _add_card(client: TestClient, card_id: str = "hdfc-infinia", **extra: Any) -> None:
    response = client.post(
        "/account/wallet",
        headers=csrf(client),
        json={"card_id": card_id, "nickname": "Main", **extra},
    )
    assert response.status_code == 201, response.text


def _projection(client: TestClient) -> UserWallet:
    return UserWallet(**client.get("/account/wallet/projection").json())


def _save(client: TestClient, session_id: str, event: str = "save-1") -> dict[str, Any]:
    response = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session_id, "client_event_id": event},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _saved_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, with_card: bool = False
) -> tuple[TestClient, AccountStore, PlanningKit, str]:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    if with_card:
        _add_card(client)
    session, _job = finished_plan(client, kit, wallet=_projection(client))
    return client, store, kit, _save(client, session["id"])["trip"]["id"]


def _rerun(client: TestClient, trip_id: str, event: str = "rr-1") -> Any:
    return client.post(
        f"/account/trips/{trip_id}/reruns",
        headers=csrf(client),
        json={"client_event_id": event},
    )


def _wait(
    client: TestClient, trip_id: str, job_id: str, *, timeout_s: float = 60.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = client.get(f"/account/trips/{trip_id}/reruns/{job_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        if body["status"] not in {"queued", "running"}:
            return body
        time.sleep(0.05)
    raise AssertionError("rerun did not finish in time")


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


# --- authentication, CSRF, ownership --------------------------------------------------- #


def test_rerun_routes_require_authentication_and_csrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, trip_id = _saved_trip(tmp_path, monkeypatch)

    assert (
        client.post(f"/account/trips/{trip_id}/reruns", json={"client_event_id": "e"}).status_code
        == 403
    )
    with TestClient(app) as anonymous:
        assert (
            anonymous.post(
                f"/account/trips/{trip_id}/reruns", json={"client_event_id": "e"}
            ).status_code
            == 401
        )
        assert anonymous.get(f"/account/trips/{trip_id}/reruns/x").status_code == 401


def test_another_users_trip_cannot_be_rerun_or_polled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    kit.queue_run()
    job_id = _rerun(client, trip_id).json()["job_id"]
    intruder = second_client("intruder@example.com")

    foreign = _rerun(intruder, trip_id, "x")
    missing = _rerun(intruder, "no-such-trip", "x")
    polled = intruder.get(f"/account/trips/{trip_id}/reruns/{job_id}")

    assert foreign.status_code == missing.status_code == polled.status_code == 404
    assert foreign.json() == missing.json() == polled.json()
    _wait(client, trip_id, job_id)


def test_a_job_id_of_another_trip_is_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    kit.queue_run()
    job_id = _rerun(client, trip_id).json()["job_id"]
    _wait(client, trip_id, job_id)

    wrong_trip = client.get(f"/account/trips/other-trip/reruns/{job_id}")
    unknown_job = client.get(f"/account/trips/{trip_id}/reruns/no-such-job")

    assert wrong_trip.status_code == unknown_job.status_code == 404


# --- the happy path ---------------------------------------------------------------------- #


def test_a_rerun_appends_revision_two_with_the_callers_current_wallet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    user_id = _user_id(client)
    (before,) = store.revisions(user_id, trip_id)
    assert before.report_json and '"card_ids":[]' in before.report_json  # saved with no cards

    _add_card(client, points_balances={"hdfc-reward-points": 50000})
    current = _projection(client)
    kit.queue_run(wallet=current, summary="Second run summary.")
    started = _rerun(client, trip_id)

    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]
    done = _wait(client, trip_id, job_id)
    assert done["status"] == "complete" and done["revision"] == 2 and done["error"] is None

    first, second = store.revisions(user_id, trip_id)
    assert first == before  # revision 1 is byte-for-byte what it was
    assert second.revision == 2
    assert '"hdfc-infinia"' in second.report_json
    detail = client.get(f"/account/trips/{trip_id}/revisions/2").json()
    assert detail["report"]["trip_spec"]["wallet"]["card_ids"] == ["hdfc-infinia"]
    assert detail["report"]["summary"] == "Second run summary."
    events = [e for e in store.trip_mutation_events(user_id) if e.operation == "rerun_complete"]
    assert [e.client_event_id for e in events] == [f"rerun:{job_id}"]


def test_revision_one_is_unchanged_when_reference_data_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 17 §5: a saved plan keeps what was true when it was computed."""
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch, with_card=True)
    user_id = _user_id(client)
    (before,) = store.revisions(user_id, trip_id)
    fingerprint = hashlib.sha256(before.report_json.encode()).hexdigest()

    seeds = tmp_path / "altered-seeds"
    shutil.copytree(SEEDS_DIR, seeds)
    valuations = seeds / "point_valuations.yaml"
    valuations.write_text(
        valuations.read_text().replace(
            "value_micro_major_per_point: 1000000", "value_micro_major_per_point: 3000000", 1
        )
    )
    altered_db = tmp_path / "altered.sqlite"
    seed_database(seeds, altered_db)
    monkeypatch.setattr(api_main, "get_kb", lambda: load_kb(altered_db))

    kit.queue_run(wallet=_projection(client), summary="After the data changed.")
    job_id = _rerun(client, trip_id).json()["job_id"]
    assert _wait(client, trip_id, job_id)["status"] == "complete"

    first, second = store.revisions(user_id, trip_id)
    assert hashlib.sha256(first.report_json.encode()).hexdigest() == fingerprint
    assert first.report_json == before.report_json
    old, new = json.loads(first.report_json), json.loads(second.report_json)
    changed = sorted(key for key in old if old[key] != new[key])
    # The edited valuation reaches the money fields of the new revision only.
    assert {"optimizer_result", "budget_totals"} <= set(changed), changed
    assert second.created_at >= first.created_at


# --- one in flight, failures append nothing ------------------------------------------------ #


def test_a_second_rerun_while_one_is_running_is_refused_then_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    entered, release = _hold_intake(kit)
    kit.queue_run()
    first = _rerun(client, trip_id, "rr-1").json()["job_id"]
    assert entered.wait(timeout=30)

    busy = _rerun(client, trip_id, "rr-2")
    release.set()
    _wait(client, trip_id, first)

    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "RERUN_IN_PROGRESS"
    kit.queue_run()
    assert _rerun(client, trip_id, "rr-3").status_code == 202


def test_a_failed_run_appends_nothing_and_frees_the_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    # No scripted responses queued: the LLM call fails, the pipeline reports an error.
    job_id = _rerun(client, trip_id).json()["job_id"]

    done = _wait(client, trip_id, job_id)

    assert done["status"] == "failed" and done["revision"] is None
    assert done["error"]["code"]
    assert len(store.revisions(_user_id(client), trip_id)) == 1
    kit.queue_run()
    assert _rerun(client, trip_id, "rr-again").status_code == 202


def test_a_run_that_needs_clarification_appends_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    kit.queue_run()
    kit.llm._scripts["intake"][-1] = kit.llm._scripts["intake"][-1].model_copy(
        update={"unresolved": ["Need exact dates."]}
    )

    job_id = _rerun(client, trip_id).json()["job_id"]
    done = _wait(client, trip_id, job_id)

    assert done["status"] == "needs_clarification" and done["revision"] is None
    assert len(store.revisions(_user_id(client), trip_id)) == 1


def test_a_completion_that_fires_twice_appends_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    kit.queue_run()
    job_id = _rerun(client, trip_id).json()["job_id"]
    _wait(client, trip_id, job_id)
    record = saved_trips._RERUNS[job_id]

    saved_trips._append_rerun_result(record, store)  # a duplicate callback
    saved_trips._append_rerun_result(record, store)

    assert [r.revision for r in store.revisions(_user_id(client), trip_id)] == [1, 2]


def test_a_trip_deleted_mid_run_gets_no_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    entered, release = _hold_intake(kit)
    kit.queue_run()
    job_id = _rerun(client, trip_id).json()["job_id"]
    assert entered.wait(timeout=30)

    deleted = store.delete_trip(_user_id(client), trip_id)
    release.set()
    deadline = time.monotonic() + 30
    while not saved_trips._RERUNS[job_id].finished and time.monotonic() < deadline:
        time.sleep(0.05)

    assert deleted is True
    assert saved_trips._RERUNS[job_id].finished
    assert saved_trips._RERUNS[job_id].revision is None
    assert store.trips(_user_id(client)) == []
    assert store._revisions_of_trip(trip_id) == []


# --- starting is idempotent and bounded ----------------------------------------------------- #


def test_retrying_the_start_returns_the_same_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    entered, release = _hold_intake(kit)
    kit.queue_run()

    first = _rerun(client, trip_id, "rr-1")
    assert entered.wait(timeout=30)
    retry = _rerun(client, trip_id, "rr-1")
    release.set()

    assert first.status_code == retry.status_code == 202
    assert retry.json() == first.json()
    _wait(client, trip_id, first.json()["job_id"])
    assert kit.llm.invocations["intake"] == 2  # the original plan + exactly one rerun


def test_an_event_id_reused_for_another_trip_is_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    other_session, _ = finished_plan(client, kit)
    other_trip = _save(client, other_session["id"], "save-other")["trip"]["id"]
    kit.queue_run()
    job_id = _rerun(client, trip_id, "shared").json()["job_id"]
    _wait(client, trip_id, job_id)

    reused = _rerun(client, other_trip, "shared")

    assert reused.status_code == 409
    assert reused.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_a_full_trip_is_refused_before_any_llm_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    monkeypatch.setattr(store_module, "MAX_REVISIONS_PER_TRIP", 1)
    calls_before = dict(kit.llm.invocations)

    response = _rerun(client, trip_id)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "REVISION_LIMIT_REACHED"
    assert dict(kit.llm.invocations) == calls_before


def test_a_rerun_unknown_after_a_restart_is_a_typed_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Jobs are process-local: after a restart the status route has nothing to report.

    Clearing the registry stands in for the restart (a real one also kills the worker,
    so the trip would be left unchanged — documented, not simulated here).
    """
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    entered, release = _hold_intake(kit)
    kit.queue_run()
    job_id = _rerun(client, trip_id).json()["job_id"]
    assert entered.wait(timeout=30)
    saved_trips._RERUNS.clear()

    lost = client.get(f"/account/trips/{trip_id}/reruns/{job_id}")

    assert lost.status_code == 404
    assert lost.json()["detail"]["code"] == "RERUN_NOT_FOUND"
    release.set()  # let the in-process worker finish so it cannot outlive the test
    deadline = time.monotonic() + 30
    while len(store.revisions(_user_id(client), trip_id)) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)


# --- privacy ---------------------------------------------------------------------------------- #


def test_no_account_identity_reaches_the_llm_during_a_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, kit, trip_id = _saved_trip(tmp_path, monkeypatch)
    user_id = _user_id(client)
    store.put_profile(
        UserProfile(
            user_id=user_id,
            display_name="Zaphod Beeblebrox",
            home_country="IN",
            home_currency="INR",
            origin_city="DEL",
            updated_at=store.get_user(user_id).created_at,  # type: ignore[union-attr]
        )
    )
    _add_card(client, nickname="Zaphod's travel card", last4="4242")
    prompts: list[str] = []
    original = kit.llm.complete_json

    def recording(*, node: str, system: str, user: str, **kwargs: Any) -> Any:
        prompts.append(f"{node}\n{system}\n{user}")
        return original(node=node, system=system, user=user, **kwargs)

    kit.llm.complete_json = recording  # type: ignore[method-assign]
    kit.queue_run(wallet=_projection(client))

    job_id = _rerun(client, trip_id).json()["job_id"]
    assert _wait(client, trip_id, job_id)["status"] == "complete"

    joined = "\n".join(prompts)
    assert prompts, "the rerun should have called the LLM"
    for secret in ("traveler@example.com", "Zaphod", "4242", "Beeblebrox"):
        assert secret not in joined, secret
