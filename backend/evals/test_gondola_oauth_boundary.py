from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta

import pytest

from gateway.travel.adapters.gondola.oauth import (
    InMemoryTokenStore,
    KeychainTokenStore,
    OAuthClientBoundary,
    OAuthTokens,
)
from gateway.travel.errors import TravelGatewayError


class FakeAuthTransport:
    """Zero-network stand-in for the real mcp-SDK-backed OAuth client."""

    def __init__(self) -> None:
        self.authorization_scopes: list[str] = []
        self.refresh_calls = 0
        self.exchange_calls = 0

    def build_authorization_url(self, *, scope: str) -> str:
        self.authorization_scopes.append(scope)
        return f"https://mcp.gondola.ai/authorize?scope={scope}"

    def exchange_code(self, code: str) -> OAuthTokens:
        self.exchange_calls += 1
        return OAuthTokens(
            access_token=f"access-{code}",
            refresh_token="refresh-token-1",
            expires_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC) + timedelta(hours=1),
            scope="mcp:read",
        )

    def refresh(self, refresh_token: str) -> OAuthTokens:
        time.sleep(0.02)  # widen the race window for the concurrency test
        self.refresh_calls += 1
        return OAuthTokens(
            access_token=f"access-refreshed-{self.refresh_calls}",
            refresh_token=refresh_token,
            expires_at=datetime(2026, 8, 21, 12, 0, tzinfo=UTC) + timedelta(hours=1),
            scope="mcp:read",
        )


def _now() -> datetime:
    return datetime(2026, 8, 21, 12, 0, tzinfo=UTC)


def test_bootstrap_requests_exactly_mcp_read_scope() -> None:
    transport = FakeAuthTransport()
    boundary = OAuthClientBoundary(InMemoryTokenStore(), auth_transport=transport, now=_now)

    boundary.bootstrap(authorization_code="test-code")

    assert transport.authorization_scopes == ["mcp:read"]


def test_bootstrap_never_requests_write_or_book_scope() -> None:
    transport = FakeAuthTransport()
    boundary = OAuthClientBoundary(InMemoryTokenStore(), auth_transport=transport, now=_now)

    boundary.bootstrap(authorization_code="test-code")

    for scope in transport.authorization_scopes:
        assert "write" not in scope
        assert "book" not in scope


def test_bootstrap_persists_tokens_to_the_store() -> None:
    transport = FakeAuthTransport()
    store = InMemoryTokenStore()
    boundary = OAuthClientBoundary(store, auth_transport=transport, now=_now)

    boundary.bootstrap(authorization_code="test-code")

    assert store.load() is not None
    assert store.load().access_token == "access-test-code"


def test_get_valid_tokens_raises_authentication_failed_when_never_bootstrapped() -> None:
    boundary = OAuthClientBoundary(
        InMemoryTokenStore(), auth_transport=FakeAuthTransport(), now=_now
    )

    with pytest.raises(TravelGatewayError) as exc_info:
        boundary.get_valid_tokens()
    assert exc_info.value.code == "authentication_failed"


def test_get_valid_tokens_returns_unexpired_tokens_without_refreshing() -> None:
    transport = FakeAuthTransport()
    boundary = OAuthClientBoundary(InMemoryTokenStore(), auth_transport=transport, now=_now)
    boundary.bootstrap(authorization_code="test-code")

    boundary.get_valid_tokens()

    assert transport.refresh_calls == 0


def test_get_valid_tokens_refreshes_expired_tokens() -> None:
    transport = FakeAuthTransport()
    store = InMemoryTokenStore()
    store.save(
        OAuthTokens(
            access_token="stale-access",
            refresh_token="refresh-token-1",
            expires_at=_now() - timedelta(minutes=1),
            scope="mcp:read",
        )
    )
    boundary = OAuthClientBoundary(store, auth_transport=transport, now=_now)

    tokens = boundary.get_valid_tokens()

    assert transport.refresh_calls == 1
    assert tokens.access_token != "stale-access"


def test_concurrent_refresh_is_serialized_to_exactly_one_call() -> None:
    transport = FakeAuthTransport()
    store = InMemoryTokenStore()
    store.save(
        OAuthTokens(
            access_token="stale-access",
            refresh_token="refresh-token-1",
            expires_at=_now() - timedelta(minutes=1),
            scope="mcp:read",
        )
    )
    boundary = OAuthClientBoundary(store, auth_transport=transport, now=_now)

    threads = [threading.Thread(target=boundary.get_valid_tokens) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert transport.refresh_calls == 1


def test_keychain_token_store_round_trips_via_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_backend: dict[tuple[str, str], str] = {}

    def _fake_set(service: str, username: str, password: str) -> None:
        fake_backend[(service, username)] = password

    def _fake_get(service: str, username: str) -> str | None:
        return fake_backend.get((service, username))

    def _fake_delete(service: str, username: str) -> None:
        fake_backend.pop((service, username), None)

    monkeypatch.setattr("keyring.set_password", _fake_set)
    monkeypatch.setattr("keyring.get_password", _fake_get)
    monkeypatch.setattr("keyring.delete_password", _fake_delete)

    store = KeychainTokenStore()
    assert store.load() is None

    tokens = OAuthTokens(
        access_token="kc-access", refresh_token="kc-refresh", expires_at=_now(), scope="mcp:read"
    )
    store.save(tokens)
    loaded = store.load()
    assert loaded is not None
    assert loaded.access_token == "kc-access"

    store.clear()
    assert store.load() is None


def test_keychain_token_store_never_stores_raw_value_in_python_source() -> None:
    import inspect

    from gateway.travel.adapters.gondola import oauth as oauth_module

    source = inspect.getsource(oauth_module)
    assert "os.environ" not in source
    assert "getenv" not in source


def test_oauth_tokens_repr_never_exposes_raw_access_token() -> None:
    tokens = OAuthTokens(
        access_token="super-secret-access-value",
        refresh_token="super-secret-refresh-value",
        expires_at=_now(),
        scope="mcp:read",
    )
    rendered = repr(tokens)
    assert "super-secret-access-value" not in rendered
    assert "super-secret-refresh-value" not in rendered
