"""A4 closure — a locked accounts database is a typed 503 on every saved-trip route.

These tests use genuine SQLite contention, not a stubbed exception: a second raw
connection holds ``BEGIN EXCLUSIVE`` while the store (configured with a short busy
timeout) tries to read or write. Authentication is overridden so the lock reaches the
route's own database access rather than failing the session lookup first.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from accounts.models import User
from accounts.store import AccountStore
from api import saved_trips
from api.auth import current_user, get_store
from api.main import app
from evals.a4_support import PlanningKit, csrf, finished_plan, signed_in_client

FORBIDDEN = ("sqlite", "sqlalchemy", "operationalerror", "traceback", "locked")


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    """Hold SQLite's exclusive lock from an independent connection."""
    holder = sqlite3.connect(path, isolation_level=None, timeout=0)
    holder.execute("BEGIN EXCLUSIVE")
    try:
        yield
    finally:
        holder.execute("ROLLBACK")
        holder.close()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    saved_trips._RERUNS.clear()
    saved_trips._ACTIVE_BY_TRIP.clear()
    saved_trips._START_EVENTS.clear()
    yield
    app.dependency_overrides.clear()


def _arrange(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TestClient, AccountStore, Path, dict[str, Any], str]:
    """A saved trip, then the same database reopened with a 0.2 s busy timeout."""
    client, store = signed_in_client(tmp_path)
    kit = PlanningKit(monkeypatch, tmp_path)
    session, _job = finished_plan(client, kit)
    created = client.post(
        "/account/trips",
        headers=csrf(client),
        json={"session_id": session["id"], "client_event_id": "save-1"},
    )
    assert created.status_code == 201, created.text
    path = tmp_path / "accounts.sqlite"
    user_id = client.get("/auth/me").json()["id"]
    user = store.get_user(user_id)
    assert isinstance(user, User)
    impatient = AccountStore(create_engine(f"sqlite:///{path}", connect_args={"timeout": 0.2}))
    app.dependency_overrides[get_store] = lambda: impatient
    app.dependency_overrides[current_user] = lambda: user
    return client, impatient, path, session, str(created.json()["trip"]["id"])


def _assert_typed_unavailable(response: Any) -> None:
    assert response.status_code == 503, (response.status_code, response.text)
    assert response.json()["detail"]["code"] == "SAVED_TRIPS_UNAVAILABLE"
    lowered = response.text.lower()
    for word in FORBIDDEN:
        assert word not in lowered, word


def test_every_saved_trip_route_answers_a_locked_database_with_a_typed_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _store, path, session, trip_id = _arrange(tmp_path, monkeypatch)
    headers = csrf(client)
    calls = {
        "list": lambda: client.get("/account/trips"),
        "detail": lambda: client.get(f"/account/trips/{trip_id}"),
        "revision": lambda: client.get(f"/account/trips/{trip_id}/revisions/1"),
        "save": lambda: client.post(
            "/account/trips",
            headers=headers,
            json={"session_id": session["id"], "client_event_id": "again"},
        ),
        "append": lambda: client.post(
            f"/account/trips/{trip_id}/revisions",
            headers=headers,
            json={"session_id": session["id"], "client_event_id": "app"},
        ),
        "delete": lambda: client.delete(
            f"/account/trips/{trip_id}?client_event_id=del", headers=headers
        ),
        "rerun_start": lambda: client.post(
            f"/account/trips/{trip_id}/reruns", headers=headers, json={"client_event_id": "rr"}
        ),
        "rerun_status": lambda: client.get(f"/account/trips/{trip_id}/reruns/some-job"),
    }

    with exclusive_lock(path):
        outcomes = {name: call() for name, call in calls.items()}

    for name, response in outcomes.items():
        try:
            _assert_typed_unavailable(response)
        except AssertionError as exc:  # name the route that leaked
            raise AssertionError(f"{name}: {exc}") from exc
    # Nothing was left half-done: the lock released, the trip is intact and usable.
    assert client.get(f"/account/trips/{trip_id}").status_code == 200
    assert saved_trips._ACTIVE_BY_TRIP == {}


def test_a_lock_hit_while_launching_a_rerun_is_a_503_and_frees_the_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_launch_rerun`` reads the attached session after the start has been reserved."""
    client, store, path, _session, trip_id = _arrange(tmp_path, monkeypatch)
    kit = PlanningKit(monkeypatch, tmp_path)
    original = store.planning_session_for_trip

    def locked_read(user_id: str, tid: str) -> Any:
        with exclusive_lock(path):  # the lock appears exactly at this read
            return original(user_id, tid)

    monkeypatch.setattr(store, "planning_session_for_trip", locked_read)
    headers = csrf(client)
    body = {"client_event_id": "rr-1"}

    contended = client.post(f"/account/trips/{trip_id}/reruns", headers=headers, json=body)

    _assert_typed_unavailable(contended)
    assert saved_trips._ACTIVE_BY_TRIP == {} and saved_trips._START_EVENTS == {}
    monkeypatch.setattr(store, "planning_session_for_trip", original)
    kit.queue_run()
    retry = client.post(f"/account/trips/{trip_id}/reruns", headers=headers, json=body)
    assert retry.status_code == 202, retry.text  # same event id: nothing was remembered
