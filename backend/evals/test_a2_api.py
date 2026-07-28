from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from accounts.store import AccountStore
from api.auth import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, get_store
from api.main import app

NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
PASSWORD = "correct horse battery"


def _client(tmp_path: Path) -> TestClient:
    store = AccountStore.open(tmp_path / "accounts.sqlite")
    app.dependency_overrides[get_store] = lambda: store
    return TestClient(app, base_url="https://testserver")


def _register(client: TestClient) -> None:
    resp = client.post(
        "/auth/register", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 201, resp.text


def _login(client: TestClient) -> None:
    resp = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


def test_login_sets_an_httponly_session_cookie(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)

    resp = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )

    assert resp.status_code == 200
    raw = resp.headers["set-cookie"]
    assert SESSION_COOKIE in raw
    assert "HttpOnly" in raw
    assert "SameSite=Lax" in raw
    app.dependency_overrides.clear()


def test_csrf_cookie_is_readable_by_js(tmp_path: Path) -> None:
    """The CSRF cookie must NOT be httpOnly — the app's JS has to echo it."""
    client = _client(tmp_path)
    _register(client)
    _login(client)

    assert client.cookies.get(CSRF_COOKIE) is not None
    app.dependency_overrides.clear()


def test_session_token_is_never_returned_in_the_body(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)

    resp = client.post(
        "/auth/login", json={"email": "a@example.com", "password": PASSWORD}
    )

    assert "token" not in resp.text.lower()
    app.dependency_overrides.clear()


def test_me_requires_a_session(tmp_path: Path) -> None:
    client = _client(tmp_path)

    assert client.get("/auth/me").status_code == 401
    app.dependency_overrides.clear()


def test_me_returns_the_user_when_authenticated(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    _login(client)

    resp = client.get("/auth/me")

    assert resp.status_code == 200
    assert resp.json()["email"] == "a@example.com"
    assert "password_hash" not in resp.text
    app.dependency_overrides.clear()


def test_logout_without_csrf_header_is_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    _login(client)

    assert client.post("/auth/logout").status_code == 403
    app.dependency_overrides.clear()


def test_logout_with_csrf_header_revokes_the_session(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _register(client)
    _login(client)
    csrf = client.cookies.get(CSRF_COOKIE)
    assert csrf is not None

    resp = client.post("/auth/logout", headers={CSRF_HEADER: csrf})

    assert resp.status_code == 204
    assert client.get("/auth/me").status_code == 401
    app.dependency_overrides.clear()


def test_wrong_password_and_unknown_email_are_indistinguishable(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    _register(client)

    wrong = client.post(
        "/auth/login", json={"email": "a@example.com", "password": "nope nope nope"}
    )
    absent = client.post(
        "/auth/login", json={"email": "ghost@example.com", "password": "nope nope nope"}
    )

    assert wrong.status_code == absent.status_code == 401
    assert wrong.json() == absent.json()
    app.dependency_overrides.clear()
