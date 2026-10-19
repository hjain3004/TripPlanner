"""A3 Task 10 — genuine concurrent wallet edits.

Not two sequential calls: two real SQLite connections racing the same
``expected_version`` from separate threads. Exactly one may win, the loser must
receive the typed ``StaleWalletEntryError`` (409 at the API), and a raw
``sqlite3.OperationalError`` must never reach a caller.
"""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from accounts.store import AccountStore, StaleWalletEntryError
from api.auth import CSRF_COOKIE, CSRF_HEADER, get_store
from api.main import app

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
PASSWORD = "long-password-123"


def _seeded(tmp_path: Path) -> tuple[Path, str]:
    db_path = tmp_path / "accounts.sqlite"
    store = AccountStore.open(db_path)
    store.create_user(email="traveler@example.com", now=NOW, user_id="u-alice")
    entry = store.add_wallet_entry(
        user_id="u-alice",
        card_id="hdfc-infinia",
        nickname="Primary",
        now=NOW,
        points_balances={"hdfc-reward-points": 100},
    )
    return db_path, entry.id


def test_exactly_one_writer_wins_a_genuine_race(tmp_path: Path) -> None:
    db_path, entry_id = _seeded(tmp_path)

    def attempt(nickname: str) -> str:
        # A separate AccountStore per thread means a separate SQLite connection,
        # which is what makes this a real race rather than two ordered calls.
        store = AccountStore.open(db_path)
        try:
            store.update_wallet_entry(
                user_id="u-alice",
                entry_id=entry_id,
                expected_version=1,
                nickname=nickname,
            )
            return "won"
        except StaleWalletEntryError:
            return "lost"
        except sqlite3.OperationalError:  # pragma: no cover - the bug this guards
            return "leaked-sqlite-error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = sorted(pool.map(attempt, ["writer-a", "writer-b"]))

    assert outcomes == ["lost", "won"], outcomes

    # The surviving row advanced exactly once.
    (final,) = AccountStore.open(db_path).wallet_entries("u-alice")
    assert final.version == 2
    assert final.nickname in {"writer-a", "writer-b"}


def test_a_concurrent_delete_and_update_leave_consistent_state(
    tmp_path: Path,
) -> None:
    db_path, entry_id = _seeded(tmp_path)

    def delete() -> str:
        store = AccountStore.open(db_path)
        try:
            removed = store.remove_wallet_entry(user_id="u-alice", entry_id=entry_id)
            return "deleted" if removed else "absent"
        except sqlite3.OperationalError:  # pragma: no cover
            return "leaked-sqlite-error"

    def update() -> str:
        store = AccountStore.open(db_path)
        try:
            store.update_wallet_entry(
                user_id="u-alice",
                entry_id=entry_id,
                expected_version=1,
                nickname="renamed",
            )
            return "updated"
        except sqlite3.OperationalError:  # pragma: no cover
            return "leaked-sqlite-error"
        except ValueError as exc:
            # Typed domain failures are acceptable outcomes of the race.
            return type(exc).__name__

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(delete), pool.submit(update)]
        outcomes = [f.result() for f in futures]

    assert "leaked-sqlite-error" not in outcomes
    # Whatever the interleaving, the store is left readable and coherent.
    remaining = AccountStore.open(db_path).wallet_entries("u-alice")
    assert len(remaining) in (0, 1)
    if remaining:
        assert remaining[0].version in (1, 2)


def test_concurrent_identical_replays_apply_once(tmp_path: Path) -> None:
    """Two threads, one client event id: the composite key serialises them."""
    db_path, _entry_id = _seeded(tmp_path)

    def create(_tag: int) -> str:
        store = AccountStore.open(db_path)
        try:
            entry = store.add_wallet_entry(
                user_id="u-alice",
                card_id="axis-atlas",
                nickname="Raced",
                now=NOW,
                client_event_id="evt-race",
            )
            return entry.id
        except sqlite3.OperationalError:  # pragma: no cover
            return "leaked-sqlite-error"

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(create, [1, 2]))

    assert "leaked-sqlite-error" not in ids
    assert len(set(ids)) == 1, f"the event applied twice: {ids}"
    # The seeded card plus exactly one raced card.
    assert len(AccountStore.open(db_path).wallet_entries("u-alice")) == 2


def test_the_api_reports_a_stale_version_as_409_not_a_driver_error(
    tmp_path: Path,
) -> None:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    client = TestClient(app, base_url="https://testserver")
    client.post(
        "/auth/register", json={"email": "traveler@example.com", "password": PASSWORD}
    )
    client.post(
        "/auth/login", json={"email": "traveler@example.com", "password": PASSWORD}
    )
    token = client.cookies.get(CSRF_COOKIE)
    assert token is not None
    headers = {CSRF_HEADER: token}

    created = client.post(
        "/account/wallet",
        json={"card_id": "hdfc-infinia", "nickname": "Primary"},
        headers=headers,
    )
    entry_id = created.json()["id"]

    first = client.patch(
        f"/account/wallet/{entry_id}",
        json={"expected_version": 1, "nickname": "v2"},
        headers=headers,
    )
    assert first.status_code == 200

    loser = client.patch(
        f"/account/wallet/{entry_id}",
        json={"expected_version": 1, "nickname": "also-v2"},
        headers=headers,
    )
    assert loser.status_code == 409
    assert loser.json()["detail"]["code"] == "wallet_version_conflict"
    body = loser.text.lower()
    for leak in ("sqlite", "operationalerror", "traceback", "sqlalchemy"):
        assert leak not in body, f"{leak!r} leaked into the response"

    app.dependency_overrides.clear()
