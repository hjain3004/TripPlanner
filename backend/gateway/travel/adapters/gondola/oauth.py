"""OAuth bootstrap and token storage boundary for Gondola's MCP.

Only ``mcp:read`` is ever requested — never ``mcp:write`` or ``mcp:book``.
The actual discovery/DCR/PKCE/refresh HTTP exchange is performed by an
injected ``AuthTransport`` (a ``Protocol``): tests inject
``FakeAuthTransport``; the live path (never constructed by default) injects
a thin wrapper around the official ``mcp`` SDK's OAuth client. This class
never opens a socket itself. Token refresh is serialized behind a lock with
double-checked reload, so concurrent callers never trigger more than one
refresh HTTP call. ``OAuthTokens.__repr__`` never exposes raw token values —
only redacted markers — because tokens must never appear in a log, trace,
or error message.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from gateway.travel.errors import TravelGatewayError

REQUIRED_SCOPE = "mcp:read"


class OAuthTokens(BaseModel):
    access_token: str
    refresh_token: str | None
    expires_at: datetime
    scope: str

    def __repr__(self) -> str:
        return (
            f"OAuthTokens(access_token=<redacted len={len(self.access_token)}>, "
            f"refresh_token=<redacted>, expires_at={self.expires_at!r}, scope={self.scope!r})"
        )

    __str__ = __repr__


class TokenStore(Protocol):
    def load(self) -> OAuthTokens | None: ...

    def save(self, tokens: OAuthTokens) -> None: ...

    def clear(self) -> None: ...


class InMemoryTokenStore:
    """Test-only token store — never used outside evals/."""

    def __init__(self) -> None:
        self._tokens: OAuthTokens | None = None

    def load(self) -> OAuthTokens | None:
        return self._tokens

    def save(self, tokens: OAuthTokens) -> None:
        self._tokens = tokens

    def clear(self) -> None:
        self._tokens = None


class KeychainTokenStore:
    """OS-backed secure token store (macOS/Linux keychain via ``keyring``).

    Never persists tokens to a repository file — the OS keychain is the only
    backing store. Import is module-level (``keyring`` is a pinned
    dependency, not optional), but every keychain call goes through the
    ``keyring`` module attribute so tests can monkeypatch it without a real
    OS keychain present.
    """

    SERVICE_NAME = "tripwise-gondola-mcp"

    def __init__(self, username: str = "gondola-oauth-local-demo") -> None:
        self._username = username

    def load(self) -> OAuthTokens | None:
        import keyring

        raw = keyring.get_password(self.SERVICE_NAME, self._username)
        if raw is None:
            return None
        return OAuthTokens.model_validate_json(raw)

    def save(self, tokens: OAuthTokens) -> None:
        import keyring

        keyring.set_password(self.SERVICE_NAME, self._username, tokens.model_dump_json())

    def clear(self) -> None:
        import keyring

        keyring.delete_password(self.SERVICE_NAME, self._username)


class KeychainClientInfoStore:
    """OS-backed secure storage for OAuth Dynamic Client Registration
    info (client_id, token endpoint, etc.) — a distinct keychain entry
    from :class:`KeychainTokenStore`, so tokens and client registration
    can be cleared/rotated independently. Stores an opaque JSON string;
    callers (which already depend on the ``mcp`` SDK's
    ``OAuthClientInformationFull``) own serialization, keeping this module
    decoupled from that SDK type. Without this, every bootstrap re-runs
    DCR and registers a new client — this store is what makes a later
    token refresh possible without a fresh full re-authorization."""

    SERVICE_NAME = "tripwise-gondola-mcp-client-info"

    def __init__(self, username: str = "gondola-oauth-local-demo") -> None:
        self._username = username

    def load(self) -> str | None:
        import keyring

        result: str | None = keyring.get_password(self.SERVICE_NAME, self._username)
        return result

    def save(self, client_info_json: str) -> None:
        import keyring

        keyring.set_password(self.SERVICE_NAME, self._username, client_info_json)

    def clear(self) -> None:
        import keyring

        keyring.delete_password(self.SERVICE_NAME, self._username)


class AuthTransport(Protocol):
    def build_authorization_url(self, *, scope: str) -> str: ...

    def exchange_code(self, code: str) -> OAuthTokens: ...

    def refresh(self, refresh_token: str) -> OAuthTokens: ...


class OAuthClientBoundary:
    def __init__(
        self,
        token_store: TokenStore,
        *,
        auth_transport: AuthTransport,
        now: Callable[[], datetime],
    ) -> None:
        self._token_store = token_store
        self._auth_transport = auth_transport
        self._now = now
        self._refresh_lock = threading.Lock()

    def authorization_url(self) -> str:
        return self._auth_transport.build_authorization_url(scope=REQUIRED_SCOPE)

    def bootstrap(self, *, authorization_code: str) -> OAuthTokens:
        # authorization_url() must be called (or the transport's own scope
        # default asserted elsewhere) before exchanging a code in a real flow;
        # here the transport itself records the requested scope for callers
        # that skip straight to exchange in a test.
        self._auth_transport.build_authorization_url(scope=REQUIRED_SCOPE)
        tokens = self._auth_transport.exchange_code(authorization_code)
        self._token_store.save(tokens)
        return tokens

    def get_valid_tokens(self) -> OAuthTokens:
        tokens = self._token_store.load()
        if tokens is None:
            raise TravelGatewayError(
                "authentication_failed",
                "no Gondola OAuth tokens found; run the one-time bootstrap flow",
            )
        if tokens.expires_at > self._now():
            return tokens
        return self._refresh(tokens)

    def _refresh(self, stale_tokens: OAuthTokens) -> OAuthTokens:
        with self._refresh_lock:
            current = self._token_store.load()
            if current is not None and current.expires_at > self._now():
                return current
            refresh_token = stale_tokens.refresh_token if current is None else current.refresh_token
            if refresh_token is None:
                raise TravelGatewayError(
                    "authentication_failed", "no refresh_token available; re-run bootstrap"
                )
            try:
                refreshed = self._auth_transport.refresh(refresh_token)
            except Exception as exc:  # noqa: BLE001 - normalize every transport failure
                raise TravelGatewayError(
                    "authentication_failed", f"Gondola token refresh failed: {exc}"
                ) from exc
            self._token_store.save(refreshed)
            return refreshed
