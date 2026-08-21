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
from urllib.parse import parse_qs, urlparse

from gateway.travel.adapters.gondola.mcp_client import ALLOWED_HOST
from gateway.travel.adapters.gondola.oauth import REQUIRED_SCOPE, KeychainTokenStore, OAuthTokens

MCP_ENDPOINT = f"https://{ALLOWED_HOST}/mcp"
LOOPBACK_HOST = "127.0.0.1"
LOOPBACK_PORT = 8734
CALLBACK_PATH = "/gondola-oauth-callback"
CALLBACK_TIMEOUT_S = 300.0


class _CallbackResult:
    def __init__(self) -> None:
        self.code: str | None = None
        self.state: str | None = None
        self.error: str | None = None
        self.event = threading.Event()


def _make_handler(result: _CallbackResult) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib method name
            parsed = urlparse(self.path)
            if parsed.path != CALLBACK_PATH:
                self.send_response(404)
                self.end_headers()
                return
            params = parse_qs(parsed.query)
            result.code = params.get("code", [None])[0]
            result.state = params.get("state", [None])[0]
            result.error = params.get("error", [None])[0]
            result.event.set()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Gondola authorization received. You can close this tab.")

        def log_message(self, fmt: str, *args: object) -> None:
            return  # never log request paths/query strings (may carry the code)

    return Handler


async def _exchange_via_real_mcp_sdk() -> OAuthTokens:
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

    class _CaptureStorage:
        def __init__(self) -> None:
            self.tokens: object | None = None
            self.client_info: object | None = None

        async def get_tokens(self) -> object | None:
            return self.tokens

        async def set_tokens(self, tokens: object) -> None:
            self.tokens = tokens

        async def get_client_info(self) -> object | None:
            return self.client_info

        async def set_client_info(self, client_info: object) -> None:
            self.client_info = client_info

    async def _redirect_handler(authorization_url: str) -> None:
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
        return AuthorizationCodeResult(code=result.code, state=result.state)

    storage = _CaptureStorage()
    redirect_uri = f"http://{LOOPBACK_HOST}:{LOOPBACK_PORT}{CALLBACK_PATH}"

    provider = OAuthClientProvider(
        server_url=MCP_ENDPOINT,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            scope=REQUIRED_SCOPE,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="none",
        ),
        storage=storage,  # type: ignore[arg-type]
        redirect_handler=_redirect_handler,
        callback_handler=_callback_handler,
    )

    try:
        async with httpx2.AsyncClient(auth=provider, timeout=30.0) as client:
            # A lightweight request triggers the SDK's internal
            # 401 -> discovery -> DCR -> PKCE(redirect_handler/callback_handler)
            # -> token-exchange flow.
            await client.get(MCP_ENDPOINT)
    finally:
        server.shutdown()

    if storage.tokens is None:
        raise RuntimeError("Gondola OAuth exchange did not produce tokens")

    retrieved_at = datetime.now(UTC)
    expires_in = getattr(storage.tokens, "expires_in", None)
    expires_at = retrieved_at + timedelta(seconds=expires_in) if expires_in else retrieved_at
    return OAuthTokens(
        access_token=storage.tokens.access_token,  # type: ignore[attr-defined]
        refresh_token=getattr(storage.tokens, "refresh_token", None),
        expires_at=expires_at,
        scope=getattr(storage.tokens, "scope", REQUIRED_SCOPE) or REQUIRED_SCOPE,
    )


def main() -> None:
    print(f"Gondola OAuth bootstrap: requesting scope={REQUIRED_SCOPE!r} only.")
    tokens = asyncio.run(_exchange_via_real_mcp_sdk())
    KeychainTokenStore().save(tokens)
    print("Gondola OAuth bootstrap complete. Tokens stored in the OS keychain.")
    print(f"Token expires at: {tokens.expires_at.isoformat()}")


if __name__ == "__main__":
    main()
