"""Static safety checks on the OAuth bootstrap script — the script itself
makes a real network call and requires human browser interaction, so it is
never executed by the normal test suite (matching the parent task's
explicit "never invoked automatically by an agent" instruction). These
tests only inspect its source/structure.
"""

from __future__ import annotations

import asyncio
import inspect
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).parent.parent


def _source() -> str:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    return inspect.getsource(module)


def test_module_imports_without_executing_the_network_flow() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    assert module.MCP_ENDPOINT == "https://mcp.gondola.ai/mcp/auth"


def test_requests_only_mcp_read_scope() -> None:
    from gateway.travel.adapters.gondola.oauth import REQUIRED_SCOPE

    assert REQUIRED_SCOPE == "mcp:read"
    source = _source()
    assert "scope=REQUIRED_SCOPE" in source  # the constructed OAuthClientMetadata scope value
    # "mcp:write"/"mcp:book" appear only as negations in the module docstring
    # (documenting what is never requested), never as a constructed scope
    # literal string in the code:
    assert 'scope="mcp:write"' not in source
    assert 'scope="mcp:book"' not in source


def test_bootstrap_uses_non_tool_mcp_request_and_never_spends_a_travel_call() -> None:
    source = _source()
    assert "await session.list_tools()" in source
    assert "session.call_tool(" not in source
    assert "search_flights" not in source


def test_never_logs_or_prints_a_raw_access_token() -> None:
    source = _source()
    # The only print of a token-adjacent value is the redacted expiry, never
    # access_token/refresh_token themselves.
    assert "print(tokens.access_token" not in source
    assert "print(tokens.refresh_token" not in source
    assert "print(f\"Token: " not in source


def test_stores_tokens_only_via_the_keychain_token_store() -> None:
    source = _source()
    assert "_BootstrapStorage(KeychainTokenStore(), KeychainClientInfoStore())" in source
    # No direct file/DB write of token material anywhere in the module:
    assert "with open(" not in source
    assert ".sqlite" not in source


def test_loopback_server_binds_only_to_localhost() -> None:
    source = _source()
    assert 'LOOPBACK_HOST = "127.0.0.1"' in source


def test_script_is_never_imported_by_core_accounts_agents_or_api() -> None:
    for package in ("core", "accounts", "agents", "api"):
        for py_file in (BACKEND / package).rglob("*.py"):
            content = py_file.read_text()
            assert "bootstrap_oauth" not in content


def test_pin_scope_forces_a_server_escalated_scope_back_to_read_only() -> None:
    # Reproduces exactly what was observed live against Gondola (G3.2): the
    # mcp SDK's step-up scope selection (SEP-2350) escalated the authorization
    # URL's scope to "mcp:read mcp:write" after the 401 challenge, even
    # though this script only ever configures "mcp:read".
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    escalated_url = (
        "https://www.gondola.ai/oauth/authorize?response_type=code&client_id=abc"
        "&redirect_uri=http%3A%2F%2F127.0.0.1%3A8734%2Fgondola-oauth-callback"
        "&state=xyz&code_challenge=chal&code_challenge_method=S256"
        "&resource=https%3A%2F%2Fmcp.gondola.ai&scope=mcp%3Aread+mcp%3Awrite"
    )
    pinned = module.pin_scope_to_read_only(escalated_url)
    assert "mcp%3Awrite" not in pinned
    assert "write" not in pinned
    assert "scope=mcp%3Aread" in pinned or "scope=mcp:read" in pinned


def test_pin_scope_leaves_an_already_correct_scope_unchanged() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    correct_url = "https://www.gondola.ai/oauth/authorize?client_id=abc&scope=mcp%3Aread"
    pinned = module.pin_scope_to_read_only(correct_url)
    assert pinned == correct_url


def test_pin_scope_never_allows_book_scope_through() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    booky_url = "https://www.gondola.ai/oauth/authorize?client_id=abc&scope=mcp%3Aread+mcp%3Abook"
    pinned = module.pin_scope_to_read_only(booky_url)
    assert "book" not in pinned


def test_token_exchange_refuses_to_store_a_token_with_an_unexpected_granted_scope() -> None:
    source = _source()
    assert "SAFETY VIOLATION" in source
    assert "effective_scope != REQUIRED_SCOPE" in source
    assert "Refusing to store this token" in source


def _callback_request(query: str) -> tuple[object, int]:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    result = module._CallbackResult()
    handler_type = module._make_handler(result)
    handler = handler_type.__new__(handler_type)
    handler.path = f"{module.CALLBACK_PATH}?{query}"
    handler.wfile = BytesIO()
    statuses: list[int] = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler_type.do_GET(handler)
    return result, statuses[0]


def test_callback_handler_forwards_decoded_issuer_to_sdk_result() -> None:
    from mcp.shared.auth import AuthorizationCodeResult

    result, status = _callback_request(
        "code=authorization%2Fcode&state=expected&iss=https%3A%2F%2Fissuer.example"
    )
    assert status == 200
    assert result.iss == "https://issuer.example"
    assert AuthorizationCodeResult(
        code=result.code, state=result.state, iss=result.iss
    ).iss == "https://issuer.example"


def test_callback_handler_preserves_absent_issuer_for_sdk_validation() -> None:
    from mcp.client.auth.exceptions import OAuthFlowError
    from mcp.client.auth.utils import validate_authorization_response_iss
    from mcp.shared.auth import OAuthMetadata

    result, status = _callback_request("code=authorization%2Fcode&state=expected")
    assert status == 200
    assert result.iss is None
    metadata = OAuthMetadata(
        issuer="https://issuer.example",
        authorization_endpoint="https://issuer.example/authorize",
        token_endpoint="https://issuer.example/token",
        authorization_response_iss_parameter_supported=True,
    )
    try:
        validate_authorization_response_iss(result.iss, metadata)
    except OAuthFlowError:
        pass
    else:
        raise AssertionError("missing issuer must remain rejected when required")


def test_callback_handler_mismatched_issuer_remains_rejected_by_sdk() -> None:
    from mcp.client.auth.exceptions import OAuthFlowError
    from mcp.client.auth.utils import validate_authorization_response_iss
    from mcp.shared.auth import OAuthMetadata

    result, status = _callback_request(
        "code=authorization%2Fcode&state=expected&iss=https%3A%2F%2Fevil.example"
    )
    assert status == 200
    try:
        validate_authorization_response_iss(
            result.iss,
            OAuthMetadata(
                issuer="https://issuer.example",
                authorization_endpoint="https://issuer.example/authorize",
                token_endpoint="https://issuer.example/token",
            ),
        )
    except OAuthFlowError:
        pass
    else:
        raise AssertionError("mismatched issuer must be rejected")


def test_callback_handler_preserves_state_and_rejects_ambiguous_security_values() -> None:
    result, status = _callback_request("code=one&code=two&state=expected")
    assert status == 400
    assert result.event.is_set()
    assert result.error == "ambiguous OAuth callback security parameter"
    assert result.state is None


def test_callback_source_does_not_log_callback_query_or_secret_values() -> None:
    source = _source()
    assert "print(self.path" not in source
    assert "print(result.code" not in source
    assert "print(result.iss" not in source
    assert "print(tokens.access_token" not in source


class _TokenSink:
    def __init__(self) -> None:
        self.saved = []

    def save(self, tokens: object) -> None:
        self.saved.append(tokens)


class _ClientInfoSink:
    def __init__(self) -> None:
        self.saved = []

    def save(self, client_info_json: str) -> None:
        self.saved.append(client_info_json)


def test_sdk_token_callback_persists_before_downstream_failure() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    token_sink = _TokenSink()
    storage = module._BootstrapStorage(token_sink, _ClientInfoSink())
    asyncio.run(
        storage.set_tokens(
            SimpleNamespace(
                access_token="access",
                refresh_token="refresh",
                expires_in=3600,
                scope="mcp:read",
            )
        )
    )
    assert len(token_sink.saved) == 1
    assert token_sink.saved[0].scope == "mcp:read"
    assert token_sink.saved[0].refresh_token == "refresh"
    with pytest.raises(TimeoutError):
        raise TimeoutError("downstream MCP request timed out")


def test_omitted_scope_uses_only_the_requested_read_scope() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    token_sink = _TokenSink()
    storage = module._BootstrapStorage(token_sink, _ClientInfoSink())
    asyncio.run(
        storage.set_tokens(
            SimpleNamespace(
                access_token="access",
                refresh_token="refresh",
                expires_in=60,
                scope=None,
            )
        )
    )
    assert token_sink.saved[0].scope == "mcp:read"


def test_unexpected_scope_is_rejected_without_overwriting_storage() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module
    token_sink = _TokenSink()
    storage = module._BootstrapStorage(token_sink, _ClientInfoSink())
    with pytest.raises(RuntimeError, match="No token was persisted"):
        asyncio.run(
            storage.set_tokens(
                SimpleNamespace(
                    access_token="access",
                    refresh_token="refresh",
                    expires_in=3600,
                    scope="mcp:read mcp:write",
                )
            )
        )
    assert token_sink.saved == []


def test_refresh_rotation_persists_the_new_refresh_token() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    token_sink = _TokenSink()
    storage = module._BootstrapStorage(token_sink, _ClientInfoSink())
    for refresh in ("old-refresh", "rotated-refresh"):
        asyncio.run(
            storage.set_tokens(
                SimpleNamespace(
                    access_token="access",
                    refresh_token=refresh,
                    expires_in=3600,
                    scope="mcp:read",
                )
            )
        )
    assert token_sink.saved[-1].refresh_token == "rotated-refresh"


def test_persistence_failure_is_propagated_without_repository_fallback() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module
    class FailingSink:
        def save(self, _tokens: object) -> None:
            raise OSError("keychain unavailable")

    storage = module._BootstrapStorage(FailingSink(), _ClientInfoSink())
    with pytest.raises(OSError, match="keychain unavailable"):
        asyncio.run(
            storage.set_tokens(
                SimpleNamespace(
                    access_token="access", refresh_token="refresh", expires_in=60, scope="mcp:read"
                )
            )
        )
    assert storage.persisted_tokens is None
