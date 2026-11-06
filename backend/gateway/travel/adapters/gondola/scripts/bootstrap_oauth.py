"""One-time, human-supervised OAuth bootstrap for the developer's own
Gondola account. NOT part of ``pytest``/``make gate`` — this script makes a
real network call and requires the human to sign into Gondola in their own
browser. Never invoked automatically by an agent.

Requests only ``mcp:read``. Never ``mcp:write`` or ``mcp:book``. Persists
tokens to the OS keychain via ``KeychainTokenStore`` — never to a repository
file. Never prints or logs a raw token value.

Usage (run manually, from ``backend/``):

    .venv/bin/python -m gateway.travel.adapters.gondola.scripts.bootstrap_oauth

This opens a browser tab at Gondola's authorization page and runs a local
loopback HTTP server on 127.0.0.1 to receive the redirect. Sign in when
prompted; the script exits once tokens are stored.
"""

from __future__ import annotations

import asyncio
import threading
import webbrowser
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from gateway.travel.adapters.gondola.mcp_client import ALLOWED_HOST
from gateway.travel.adapters.gondola.oauth import (
    REQUIRED_SCOPE,
    KeychainClientInfoStore,
    KeychainTokenStore,
    OAuthTokens,
)

MCP_ENDPOINT = f"https://{ALLOWED_HOST}/mcp/auth"
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8734
CALLBACK_PATH = "/gondola-oauth-callback"
CALLBACK_TIMEOUT_S = 300.0


class _TokenSink(Protocol):
    def save(self, tokens: OAuthTokens) -> None: ...


class _ClientInfoSink(Protocol):
    def save(self, client_info_json: str) -> None: ...


class _BootstrapStorage:
    """SDK storage that persists validated credentials at each SDK callback."""

    def __init__(self, token_sink: _TokenSink, client_info_sink: _ClientInfoSink) -> None:
        self.token_sink = token_sink
        self.client_info_sink = client_info_sink
        self.tokens: object | None = None
        self.client_info: object | None = None
        self.persisted_tokens: OAuthTokens | None = None
        self.persisted_client_info: str | None = None

    async def get_tokens(self) -> object | None:
        return self.tokens

    async def set_tokens(self, tokens: object) -> None:
        granted_scope = getattr(tokens, "scope", None)
        effective_scope = granted_scope if granted_scope else REQUIRED_SCOPE
        if effective_scope != REQUIRED_SCOPE:
            raise RuntimeError(
                f"SAFETY VIOLATION: Gondola granted scope {effective_scope!r}, not exactly "
                f"{REQUIRED_SCOPE!r}. Refusing to store this token. No token was persisted."
            )
        self.tokens = tokens
        expires_in = getattr(tokens, "expires_in", None)
        retrieved_at = datetime.now(UTC)
        expires_at = retrieved_at + timedelta(seconds=expires_in) if expires_in else retrieved_at
        persisted = OAuthTokens(
            access_token=tokens.access_token,  # type: ignore[attr-defined]
            refresh_token=getattr(tokens, "refresh_token", None),
            expires_at=expires_at,
            scope=effective_scope,
        )
        self.token_sink.save(persisted)
        self.persisted_tokens = persisted

    async def get_client_info(self) -> object | None:
        return self.client_info

    async def set_client_info(self, client_info: object) -> None:
        serialized = client_info.model_dump_json()  # type: ignore[attr-defined]
        self.client_info_sink.save(serialized)
        self.client_info = client_info
        self.persisted_client_info = serialized


class _CallbackResult:
    def __init__(self) -> None:
        self.code: str | None = None
        self.state: str | None = None
        self.iss: str | None = None
        self.error: str | None = None
        self.event = threading.Event()


_SECURITY_PARAMETERS = frozenset(("code", "state", "error", "iss"))


def _single_callback_parameters(query: str) -> dict[str, str | None]:
    """Decode callback parameters without silently accepting duplicates."""
    values: dict[str, list[str]] = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key in _SECURITY_PARAMETERS:
            values.setdefault(key, []).append(value)
    duplicates = [key for key, entries in values.items() if len(entries) > 1]
    if duplicates:
        raise ValueError("ambiguous OAuth callback security parameter")
    return {key: entries[0] for key, entries in values.items()}


def _make_handler(result: _CallbackResult) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            try:
                params = _single_callback_parameters(parsed.query)
            except ValueError:
                result.code = None
                result.state = None
                result.iss = None
                result.error = "ambiguous OAuth callback security parameter"
                result.event.set()
                self.send_response(400)
                self.end_headers()
                return
            result.code = params.get("code")
            result.state = params.get("state")
            result.iss = params.get("iss")
            result.error = params.get("error")
            result.event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Gondola authorization received. You can close this tab.")

        def log_message(self, fmt: str, *args: object) -> None:
            return  # never log request paths/query strings (may carry the code)

    return Handler


def pin_scope_to_read_only(authorization_url: str) -> str:
    """The mcp SDK implements spec-compliant "step-up" scope selection
    (SEP-2350): after a 401 challenge, it adopts whatever scope the resource
    server's WWW-Authenticate header or protected-resource metadata
    declares, overriding the scope this script originally configured.
    Confirmed live against Gondola (G3.2): the server's challenge caused the
    SDK to request "mcp:read mcp:write" even though only "mcp:read" was
    ever configured here. This function is the absolute, non-negotiable
    backstop — it runs on the URL right before a human ever sees or visits
    it, so it force-pins the scope query parameter back to exactly
    REQUIRED_SCOPE regardless of what the server's challenge asked for.
    mcp:write and mcp:book are never requested under any circumstance."""
    parsed = urlparse(authorization_url)
    query = dict(parse_qsl(parsed.query))
    if query.get("scope") != REQUIRED_SCOPE:
        query["scope"] = REQUIRED_SCOPE
        parsed = parsed._replace(query=urlencode(query))
        authorization_url = urlunparse(parsed)
    # Defense-in-depth, not the primary guarantee (the overwrite above is):
    # a plain `assert` is stripped under `python -O`, so this is an explicit
    # raise rather than a security-critical assertion.
    if "write" in query["scope"] or "book" in query["scope"]:
        raise RuntimeError(
            f"SAFETY VIOLATION: pinned scope {query['scope']!r} still contains write/book"
        )
    return authorization_url


async def _exchange_via_real_mcp_sdk() -> tuple[OAuthTokens, str | None]:
    """Runs the interactive PKCE/DCR/discovery flow via the official mcp
    SDK's OAuthClientProvider, with our own loopback server supplying the
    redirect_handler/callback_handler pair. Kept as a single, narrow,
    reviewable async function — the only piece of this script that touches
    the network."""
    import httpx2
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import AuthorizationCodeResult, OAuthClientMetadata

    result = _CallbackResult()
    server = HTTPServer((LOOPBACK_HOST, LOOPBACK_PORT), _make_handler(result))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    async def _redirect_handler(authorization_url: str) -> None:
        authorization_url = pin_scope_to_read_only(authorization_url)
        print("Opening your browser to Gondola's sign-in page...")
        print(f"If it doesn't open automatically, visit:\n  {authorization_url}")
        webbrowser.open(authorization_url)

    async def _callback_handler() -> AuthorizationCodeResult:
        completed = await asyncio.get_event_loop().run_in_executor(
            None, result.event.wait, CALLBACK_TIMEOUT_S
        )
        if not completed:
            raise TimeoutError("Timed out waiting for Gondola's OAuth redirect")
        if result.error:
            raise RuntimeError(f"Gondola OAuth authorization failed: {result.error}")
        if result.code is None:
            raise RuntimeError("Gondola OAuth redirect carried no authorization code")
        return AuthorizationCodeResult(
            code=result.code,
            state=result.state,
            iss=result.iss,
        )

    storage = _BootstrapStorage(KeychainTokenStore(), KeychainClientInfoStore())
    redirect_uri = f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}{CALLBACK_PATH}"

    provider = OAuthClientProvider(
        server_url=MCP_ENDPOINT,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            scope=REQUIRED_SCOPE,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
            client_name="TripPlanner (student project, read-only)",
        ),
        storage=storage,  # type: ignore[arg-type]
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        async with httpx2.AsyncClient(auth=provider, timeout=30.0) as client:
            # A bare GET and session.initialize() are anonymous on Gondola.
            # Use the standard non-tool ``tools/list`` MCP request on the
            # authenticated endpoint as the SDK's 401 challenge. The
            # OAuthClientProvider intercepts that response, runs PKCE/DCR via
            # the redirect/callback handlers, and retries the same request
            # with the new token. This avoids consuming a travel ``tools/call``
            # merely to bootstrap authentication.
            async with streamable_http_client(MCP_ENDPOINT, http_client=client) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    await session.list_tools()
    finally:
        server.shutdown()

    if storage.tokens is None or storage.persisted_tokens is None:
        raise RuntimeError("Gondola OAuth exchange did not produce tokens")

    # Absolute backstop: RFC 6749 §5.1 says a token response that omits
    # `scope` implies the granted scope equals what the client *requested*
    # -- and the SDK's internal client_metadata.scope was overridden to
    # "mcp:read mcp:write" by its step-up scope-selection logic (see
    # _pin_scope_to_read_only above), independent of what the human's
    # browser actually visited. Never silently narrow an unexpected grant:
    # if the recorded scope is anything other than exactly REQUIRED_SCOPE,
    # refuse to store the token at all and stop.
    granted_scope = getattr(storage.tokens, "scope", None)
    effective_scope = granted_scope if granted_scope else REQUIRED_SCOPE
    if effective_scope != REQUIRED_SCOPE:
        raise RuntimeError(
            f"SAFETY VIOLATION: Gondola granted scope {effective_scope!r}, not exactly "
            f"{REQUIRED_SCOPE!r}. Refusing to store this token. No token was persisted."
        )

    tokens = storage.persisted_tokens

    client_info_json = storage.persisted_client_info

    return tokens, client_info_json


def main() -> None:
    print(f"Gondola OAuth bootstrap: requesting scope={REQUIRED_SCOPE!r} only.")
    tokens, client_info_json = asyncio.run(_exchange_via_real_mcp_sdk())
    print("Gondola OAuth bootstrap complete. Tokens stored in the OS keychain.")
    print(f"Token expires at: {tokens.expires_at.isoformat()}")
    print(f"client_info_persisted={client_info_json is not None}")


if __name__ == "__main__":
    main()
