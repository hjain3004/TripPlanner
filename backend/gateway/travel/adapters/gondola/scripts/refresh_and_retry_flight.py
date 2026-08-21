"""G3.2.1: one-time, human-supervised script that (a) exercises a real
OAuth token refresh using the persisted client_info + tokens from
bootstrap_oauth.py, and (b) retries search_flights DEL->SIN with a
corrected argument shape, capturing the sanitized error text if it fails
again. NOT part of pytest/make gate. Never invoked automatically.

Requires the same two gates as smoke_gondola.py. Uses a fresh
GondolaCallBudget plan id ("g3.2.1-authenticated") for this milestone's
authenticated calls, independent of G3.2's exhausted "g3.2-authenticated"
budget. Never falls back to an interactive browser re-authorization if
refresh fails -- that would silently turn a "refresh exercise" into an
unplanned fresh authorization; instead it stops and reports the failure.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gateway.travel.adapters.gondola.budget import GondolaCallBudget
from gateway.travel.adapters.gondola.mcp_client import ALLOWED_HOST
from gateway.travel.adapters.gondola.oauth import (
    REQUIRED_SCOPE,
    KeychainClientInfoStore,
    KeychainTokenStore,
)

MCP_ENDPOINT = f"https://{ALLOWED_HOST}/mcp"
LIVE_SMOKE_ENV_VAR = "TRIPWISE_GONDOLA_LIVE_SMOKE"
BUDGET_DB_PATH = (
    Path(__file__).parent.parent.parent.parent.parent.parent
    / "scripts"
    / ".gondola_smoke_budget.sqlite"
)


def _sanitize(value: object) -> object:
    """Local copy of smoke_gondola.sanitize_structural_fixture -- avoids a
    fragile cross-directory sys.path import for this small, stable
    function. Recursively replaces every leaf value with a synthetic
    synthetic value, preserving key names, structure, and list length."""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int):
        return 12345
    if isinstance(value, float):
        return 1.5
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return "https://example.invalid/sanitized-link"
        return "SANITIZED_STRING"
    return "SANITIZED_UNKNOWN_TYPE"


def require_gates(acknowledged: bool) -> None:
    if not acknowledged:
        print("Refusing to run: pass --acknowledge.", file=sys.stderr)
        sys.exit(2)
    if os.environ.get(LIVE_SMOKE_ENV_VAR, "").strip().lower() not in {"1", "true", "yes"}:
        print(f"Refusing to run: set {LIVE_SMOKE_ENV_VAR}=1.", file=sys.stderr)
        sys.exit(2)


async def _refresh_and_call() -> None:
    import httpx2
    from mcp import ClientSession
    from mcp.client.auth import OAuthClientProvider
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

    client_info_json = KeychainClientInfoStore().load()
    stored_tokens = KeychainTokenStore().load()
    if client_info_json is None or stored_tokens is None:
        print(
            "Refusing to run: no persisted client_info/tokens found. Run "
            "bootstrap_oauth.py first (this script only refreshes, never "
            "re-registers or re-authorizes interactively).",
            file=sys.stderr,
        )
        sys.exit(1)

    if stored_tokens.scope != REQUIRED_SCOPE:
        print(
            f"SAFETY VIOLATION: stored token scope {stored_tokens.scope!r} is not "
            f"exactly {REQUIRED_SCOPE!r}",
            file=sys.stderr,
        )
        sys.exit(1)

    client_info = OAuthClientInformationFull.model_validate_json(client_info_json)
    original_access_token = stored_tokens.access_token
    seeded_oauth_token = OAuthToken(
        access_token=stored_tokens.access_token,
        refresh_token=stored_tokens.refresh_token,
        # Force the SDK to see this as needing a refresh check by reporting
        # no explicit expires_in -- combined with our own expiry check below,
        # this exercises the SDK's real refresh path whenever the token we
        # already know is expired, without fabricating a false expiry.
        expires_in=None,
        scope=stored_tokens.scope,
    )

    class _SeededStorage:
        def __init__(self) -> None:
            self.tokens: OAuthToken | None = seeded_oauth_token
            self.client_info: OAuthClientInformationFull | None = client_info

        async def get_tokens(self) -> OAuthToken | None:
            return self.tokens

        async def set_tokens(self, tokens: OAuthToken) -> None:
            self.tokens = tokens

        async def get_client_info(self) -> OAuthClientInformationFull | None:
            return self.client_info

        async def set_client_info(self, info: OAuthClientInformationFull) -> None:
            self.client_info = info

    async def _refuse_interactive_reauth(_url: str) -> None:
        raise RuntimeError(
            "Refresh failed and the SDK is attempting a fresh interactive "
            "authorization -- refusing (this script only exercises refresh; "
            "re-run bootstrap_oauth.py for a full re-authorization)."
        )

    metadata_fields = set(OAuthClientMetadata.model_fields.keys())
    client_metadata = OAuthClientMetadata.model_validate(
        client_info.model_dump(include=metadata_fields)
    )

    storage = _SeededStorage()
    provider = OAuthClientProvider(
        server_url=MCP_ENDPOINT,
        client_metadata=client_metadata,
        storage=storage,
        redirect_handler=_refuse_interactive_reauth,
    )

    # Corrected argument shape: the original attempt included "currency",
    # the one field with no clear analogue in the empty/permissive
    # inputSchema discovery returned -- removed as the primary correction,
    # keeping the shape that discovery + normalize_flight.py already agree
    # on (origin/destination/depart_date/adults/cabin).
    depart_date = (datetime.now(UTC).date() + timedelta(days=90)).isoformat()
    arguments = {
        "origin": "DEL",
        "destination": "SIN",
        "depart_date": depart_date,
        "adults": 1,
        "cabin": "economy",
    }
    print("=== Refresh + retry: authenticated search_flights (DEL -> SIN) ===")
    print(
        "corrected_request_shape=origin,destination,depart_date,adults,cabin "
        f"depart_date={depart_date}"
    )

    async with httpx2.AsyncClient(auth=provider, timeout=30.0) as client:
        async with streamable_http_client(MCP_ENDPOINT, http_client=client) as (
            read_stream,
            write_stream,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool("search_flights", arguments)

    refreshed = storage.tokens is not None and storage.tokens.access_token != original_access_token
    print(f"token_refresh_occurred={refreshed}")

    if storage.tokens is not None:
        from gateway.travel.adapters.gondola.oauth import OAuthTokens

        retrieved_at = datetime.now(UTC)
        expires_in = storage.tokens.expires_in
        expires_at = retrieved_at + timedelta(seconds=expires_in) if expires_in else retrieved_at
        granted_scope = storage.tokens.scope or REQUIRED_SCOPE
        if granted_scope != REQUIRED_SCOPE:
            print(
                f"SAFETY VIOLATION: refreshed token scope {granted_scope!r} is not exactly "
                f"{REQUIRED_SCOPE!r}; NOT persisting.",
                file=sys.stderr,
            )
        else:
            KeychainTokenStore().save(
                OAuthTokens(
                    access_token=storage.tokens.access_token,
                    refresh_token=storage.tokens.refresh_token,
                    expires_at=expires_at,
                    scope=granted_scope,
                )
            )

    if bool(getattr(result, "is_error", False)):
        text = None
        for block in getattr(result, "content", None) or []:
            candidate = getattr(block, "text", None)
            if isinstance(candidate, str):
                text = candidate[:300]
                break
        print(f"status=error error_message={text or '(no text content)'}")
        print("del_sin_coverage=unknown (call failed; not evidence of no coverage)")
        return

    structured = getattr(result, "structured_content", None)
    print(f"status=success structured_content_present={structured is not None}")
    if isinstance(structured, dict):
        print(f"top_level_keys={sorted(structured.keys())}")
        for key, value in structured.items():
            if isinstance(value, list):
                print(f"result_list_key={key!r} result_count={len(value)}")
                break

        import json

        sanitized = _sanitize(structured)
        envelope: dict[str, object] = {
            "_fixture_provenance": (
                f"schema observed from live Gondola MCP on "
                f"{datetime.now(UTC).date().isoformat()}; content sanitized and synthetic"
            ),
            "_fixture_meta": {"status": "estimated", "source_method": "provider_mcp"},
        }
        envelope.update(sanitized if isinstance(sanitized, dict) else {"value": sanitized})
        fixture_path = (
            Path(__file__).parent.parent / "fixtures" / "search_flights_live_g321.json"
        )
        fixture_path.write_text(json.dumps(envelope, indent=2) + "\n")
        print(f"sanitized_fixture_written={fixture_path.name}")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--acknowledge", action="store_true", default=False)
    args = parser.parse_args()
    require_gates(args.acknowledge)

    budget = GondolaCallBudget(BUDGET_DB_PATH)
    if not budget.reserve_call("g3.2.1-authenticated"):
        print("SAFETY VIOLATION: g3.2.1-authenticated budget exhausted", file=sys.stderr)
        return 1

    asyncio.run(_refresh_and_call())
    return 0


if __name__ == "__main__":
    sys.exit(main())
