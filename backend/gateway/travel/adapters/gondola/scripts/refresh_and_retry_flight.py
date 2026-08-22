"""G3.2.1: one-time, human-supervised script that (a) exercises a real
OAuth token refresh using the persisted client_info + tokens from
bootstrap_oauth.py, and (b) retries search_flights DEL->SIN with a
corrected argument shape, capturing the sanitized error text if it fails
again. NOT part of pytest/make gate. Never invoked automatically.

Requires the same two gates as smoke_gondola.py. Uses a fresh
GondolaCallBudget plan id ("g3.2.2-authenticated") for this milestone's
network-reaching authenticated calls, independent of every exhausted prior
plan id ("g3.2-authenticated", "g3.2.1-authenticated",
"g3.2.1-authenticated-v2" are all at the 2-call ceiling). Never falls back
to an interactive browser re-authorization if refresh fails -- that would
silently turn a "refresh exercise" into an unplanned fresh authorization;
instead it stops and reports the failure.
"""

from __future__ import annotations

import asyncio
import logging
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
from gateway.travel.adapters.gondola.tool_policy import assert_tool_allowed

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
    value, preserving key names, structure, and list length."""
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


class _RefreshDiagnosticHandler(logging.Handler):
    """Captures the mcp SDK's own token-refresh-failure log line, which is
    just an HTTP status code (e.g. "Token refresh failed: 400") -- never a
    token, header, or response body -- so a real refresh failure can be
    diagnosed instead of failing silently into an unexplained fall-through
    to a full re-authorization attempt."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage()[:200])


def _find_oauth_flow_error(exc: BaseException, *, _depth: int = 0) -> Exception | None:
    """Unwrap anyio's BaseExceptionGroup (same pattern as
    smoke_gondola.py's extract_travel_gateway_error) to find the mcp SDK's
    own OAuthFlowError, raised when a full re-authorization is attempted
    but no callback handler is configured -- the exact, safe outcome this
    script's refusal-of-interactive-reauth is designed to produce. Bounded
    to a shallow depth (anyio task groups nest 1-2 levels in practice) so a
    pathologically deep or self-referential exception group can't recurse
    unboundedly."""
    from mcp.client.auth.exceptions import OAuthFlowError

    if _depth > 10:
        return None
    if isinstance(exc, OAuthFlowError):
        return exc
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            found = _find_oauth_flow_error(sub, _depth=_depth + 1)
            if found is not None:
                return found
    return None


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
        # NOTE (G3.2.2 root cause): passing expires_in=None here does NOT
        # make the mcp SDK attempt a refresh, despite earlier intent. The
        # SDK's OAuthClientProvider.is_token_valid() treats an unset local
        # token_expiry_time as valid regardless of the real token state --
        # _initialize() loads tokens from storage but never calls
        # update_token_expiry() on them. So a seeded token is always
        # treated as locally valid, is sent as-is, and only a real 401 from
        # the server (not a local expiry check) triggers any recovery path
        # -- and that path is full re-authorization, not refresh_token. See
        # DEVIATIONS.md's G3.2.2 section for the full diagnosis.
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

    # Corrected argument shape, confirmed live in G3.2.1 via the provider's
    # own error text (captured through mcp_client.py's _summarize_error):
    # the field is "departure_date", not "depart_date", and there is no
    # "currency" field.
    departure_date = (datetime.now(UTC).date() + timedelta(days=90)).isoformat()
    arguments = {
        "origin": "DEL",
        "destination": "SIN",
        "departure_date": departure_date,
        "adults": 1,
        "cabin": "economy",
    }
    print("=== Refresh + retry: authenticated search_flights (DEL -> SIN) ===")
    print(
        "corrected_request_shape=origin,destination,departure_date,adults,cabin "
        f"departure_date={departure_date}"
    )

    # This script builds its own ClientSession (rather than reusing
    # LiveGondolaTransport) because it must pass an OAuthClientProvider as
    # httpx2's `auth=` handler to exercise real token refresh --
    # LiveGondolaTransport only ever sends a static bearer header. Calling
    # the same static allowlist gate every other Gondola call path uses
    # keeps that divergence from ever bypassing tool-policy enforcement.
    assert_tool_allowed("search_flights")

    diagnostic_handler = _RefreshDiagnosticHandler()
    oauth_logger = logging.getLogger("mcp.client.auth.oauth2")
    oauth_logger.addHandler(diagnostic_handler)
    try:
        async with httpx2.AsyncClient(auth=provider, timeout=30.0) as client:
            async with streamable_http_client(MCP_ENDPOINT, http_client=client) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("search_flights", arguments)
    except BaseException as exc:  # noqa: BLE001 - task-group-wrapped errors need broad catch
        flow_error = _find_oauth_flow_error(exc)
        if flow_error is None:
            raise
        print("status=error")
        print(f"oauth_flow_error={str(flow_error)[:300]}")
        for message in diagnostic_handler.messages:
            print(f"oauth_refresh_diagnostic={message}")
        print(
            "del_sin_coverage=unknown (OAuth refresh/re-auth failed before the tool "
            "call was reached; not evidence of no coverage)"
        )
        return
    finally:
        oauth_logger.removeHandler(diagnostic_handler)

    for message in diagnostic_handler.messages:
        print(f"oauth_refresh_diagnostic={message}")

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
            Path(__file__).parent.parent / "fixtures" / "search_flights_live_g322.json"
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
    if not budget.reserve_call("g3.2.2-authenticated"):
        print("SAFETY VIOLATION: g3.2.2-authenticated budget exhausted", file=sys.stderr)
        return 1

    asyncio.run(_refresh_and_call())
    return 0


if __name__ == "__main__":
    sys.exit(main())
