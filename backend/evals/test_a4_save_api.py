"""A4 Task 4 — saving a finished plan as an immutable trip revision.

Negative paths first: no save without a session cookie and CSRF, none from another
user's session, none from an unconfirmed, unfinished or lost plan, and never two
trips for one session. Every plan here is produced by the real confirmed-planning
job (scripted LLM, sample inventory), not hand-built.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from accounts.store import AccountStore
from api.job_manager import job_manager
from api.main import app
from evals.a4_support import (
    PlanningKit,
    csrf,
    finished_plan,
    run_interview,
    second_client,
    signed_in_client,
)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _save(client: TestClient, session_id: str, event: str = "save-1", **extra: Any) -> Any:
    return client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session_id, "client_event_id": event, **extra},
    )


def _user_id(client: TestClient) -> str:
    return str(client.get("/auth/me").json()["id"])


def _plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, AccountStore, PlanningKit, dict[str, Any], dict[str, Any]]:
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, job = finished_plan(client, kit)
    return client, store, kit, session, job


# --- authentication, CSRF, body hygiene -------------------------------------- #


def test_saving_requires_authentication_and_csrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    body = {"session_id": session["id"], "client_event_id": "e1"}

    assert client.post("/account/trips", json=body).status_code == 403  # no CSRF header
    with TestClient(app) as anonymous:
        assert anonymous.post("/account/trips", json=body).status_code == 401


def test_the_body_cannot_name_a_user_or_extra_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    response = _save(client, session["id"], user_id="someone-else")

    assert response.status_code == 422


@pytest.mark.parametrize("title", ["", "   ", "x" * 81])
def test_a_caller_title_must_be_one_to_eighty_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, title: str
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    assert _save(client, session["id"], title=title).status_code == 422


# --- which sessions may be saved ------------------------------------------------ #


def test_another_users_session_is_indistinguishable_from_a_missing_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    intruder = second_client("intruder@example.com")

    foreign = _save(intruder, session["id"])
    missing = _save(intruder, "no-such-session")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert _store.trips(_user_id(client)) == []


def test_an_unconfirmed_session_cannot_be_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store = signed_in_client(tmp_path)
    PlanningKit(monkeypatch, tmp_path)
    review = run_interview(client)  # answered, reviewed, never confirmed

    response = _save(client, review["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_NOT_CONFIRMED"


def test_an_unfinished_plan_cannot_be_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    state = job_manager.get_job(session["job_id"])
    assert state is not None
    with state._lock:
        state.report = None  # as if the job were still running

    response = _save(client, session["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PLAN_RESULT_UNAVAILABLE"


def test_a_plan_lost_to_a_restart_is_never_reconstructed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    with job_manager._lock:
        job_manager._jobs.pop(session["job_id"])  # process restart

    response = _save(client, session["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PLAN_RESULT_UNAVAILABLE"
    assert store.trips(_user_id(client)) == []


# --- what is stored ----------------------------------------------------------------- #


def test_saving_stores_the_report_exactly_as_the_user_saw_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, job = _plan(tmp_path, monkeypatch)

    response = _save(client, session["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["revision"]["revision"] == 1
    assert body["revision"]["report"] == job["report"]
    assert body["trip"]["revision_count"] == 1
    user_id = _user_id(client)
    (trip,) = store.trips(user_id)
    (stored,) = store.revisions(user_id, trip.id)
    assert json.loads(stored.report_json) == job["report"]
    assert stored.trace_id == job["report"]["trace_id"]


def test_the_default_title_is_built_server_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    body = _save(client, session["id"]).json()

    assert body["trip"]["title"] == "DEL → SIN · 2026-11-01"
    assert body["trip"]["origin_city"] == "DEL"
    assert body["trip"]["destination_city"] == "SIN"
    assert body["trip"]["start_date"] == "2026-11-01"
    assert body["trip"]["end_date"] == "2026-11-05"


def test_a_caller_title_overrides_the_default_and_is_trimmed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    body = _save(client, session["id"], title="  Singapore with family  ").json()

    assert body["trip"]["title"] == "Singapore with family"


def _remove_item(client: TestClient, session_id: str, job: dict[str, Any]) -> Any:
    return client.post(
        f"/planning/sessions/{session_id}/recompute",
        headers=csrf(client),
        json={
            "expected_inventory_revision": job["report"]["travel_inventory"]["inventory_revision"],
            "edit": {"op": "remove_item", "poi_id": "sg-hawker-maxwell", "day_index": 0},
        },
    )


def test_a_typed_edit_is_what_gets_saved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _store, _kit, session, job = _plan(tmp_path, monkeypatch)
    edited = _remove_item(client, session["id"], job)
    assert edited.status_code == 200, edited.text

    saved = _save(client, session["id"]).json()["revision"]["report"]

    assert saved == edited.json()
    assert saved != job["report"]
    original_revision = job["report"]["travel_inventory"]["inventory_revision"]
    assert saved["travel_inventory"]["inventory_revision"] == original_revision + 1


def test_saving_attaches_the_session_to_the_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    trip_id = _save(client, session["id"]).json()["trip"]["id"]

    snapshot = store.get_planning_session_snapshot(
        user_id=_user_id(client), session_id=session["id"]
    )
    assert snapshot is not None and snapshot.saved_trip_id == trip_id


# --- idempotency and one trip per session ------------------------------------------- #


def test_a_retry_with_the_same_event_returns_the_original_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    first = _save(client, session["id"], "save-1")
    retry = _save(client, session["id"], "save-1")

    assert retry.status_code == 201
    assert retry.json() == first.json()
    assert len(store.trips(_user_id(client))) == 1


def test_reusing_an_event_id_for_a_different_request_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    _save(client, session["id"], "save-1", title="One")

    response = _save(client, session["id"], "save-1", title="Two")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_a_second_save_of_one_session_is_refused_and_names_the_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    trip_id = _save(client, session["id"], "save-1").json()["trip"]["id"]

    again = _save(client, session["id"], "save-2")

    assert again.status_code == 409
    detail = again.json()["detail"]
    assert detail["code"] == "SESSION_ALREADY_SAVED" and detail["trip_id"] == trip_id
    assert len(store.trips(_user_id(client))) == 1


def test_two_concurrent_saves_of_one_session_make_exactly_one_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)

    def attempt(event: str) -> tuple[int, str]:
        response = _save(client, session["id"], event)
        detail = response.json().get("detail")
        return response.status_code, detail["code"] if isinstance(detail, dict) else "ok"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, ["race-a", "race-b"]))

    assert outcomes == [(201, "ok"), (409, "SESSION_ALREADY_SAVED")], outcomes
    assert len(store.trips(_user_id(client))) == 1


# --- appending another revision from the same session --------------------------------- #


def _append(client: TestClient, trip_id: str, session_id: str, event: str = "app-1") -> Any:
    return client.post(
        f"/account/trips/{trip_id}/revisions",
        headers=csrf(client),
        json={"session_id": session_id, "client_event_id": event},
    )


def test_an_edited_plan_is_appended_as_revision_two_and_revision_one_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, job = _plan(tmp_path, monkeypatch)
    first = _save(client, session["id"]).json()
    edited = _remove_item(client, session["id"], job).json()

    appended = _append(client, first["trip"]["id"], session["id"])

    assert appended.status_code == 201, appended.text
    assert appended.json()["revision"] == 2
    assert appended.json()["report"] == edited
    stored = store.revisions(_user_id(client), first["trip"]["id"])
    assert json.loads(stored[0].report_json) == first["revision"]["report"] == job["report"]


def test_appending_from_a_session_not_attached_to_that_trip_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, kit, session, _job = _plan(tmp_path, monkeypatch)
    trip_id = _save(client, session["id"]).json()["trip"]["id"]
    other, _ = finished_plan(client, kit)

    response = _append(client, trip_id, other["id"])

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "SESSION_NOT_ATTACHED"


def test_appending_to_another_users_trip_is_a_plain_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    trip_id = _save(client, session["id"]).json()["trip"]["id"]
    intruder = second_client("intruder@example.com")

    foreign = _append(intruder, trip_id, session["id"])
    missing = _append(intruder, "no-such-trip", session["id"])

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["detail"]["code"] == missing.json()["detail"]["code"] == "TRIP_NOT_FOUND"


def test_a_retried_append_adds_one_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    trip_id = _save(client, session["id"]).json()["trip"]["id"]

    first = _append(client, trip_id, session["id"], "app-1")
    retry = _append(client, trip_id, session["id"], "app-1")

    assert retry.status_code == 201 and retry.json() == first.json()
    assert len(store.revisions(_user_id(client), trip_id)) == 2


def test_an_expired_unattached_session_cannot_be_saved_and_revived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attaching a trip exempts a session from expiry for good, so an expired,
    unattached session must be refused exactly as the conversation API refuses it."""
    from datetime import UTC, datetime

    from api import saved_trips

    client, store, _kit, session, _job = _plan(tmp_path, monkeypatch)
    monkeypatch.setattr(saved_trips, "now_utc", lambda: datetime(2030, 1, 1, tzinfo=UTC))

    response = _save(client, session["id"])

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "SESSION_EXPIRED"
    assert store.trips(_user_id(client)) == []


def test_two_concurrent_saves_of_different_sessions_respect_the_trip_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without the write lock both pass the count check and the cap is exceeded."""
    import accounts.store as store_module

    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    first, _ = finished_plan(client, kit)
    second, _ = finished_plan(client, kit)
    monkeypatch.setattr(store_module, "MAX_SAVED_TRIPS", 1)

    def attempt(session_id: str) -> int:
        return int(_save(client, session_id, f"save-{session_id}").status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, [first["id"], second["id"]]))

    assert outcomes == [201, 409], outcomes
    assert len(store.trips(_user_id(client))) == 1
