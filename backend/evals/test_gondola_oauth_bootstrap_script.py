"""Static safety checks on the OAuth bootstrap script — the script itself
makes a real network call and requires human browser interaction, so it is
never executed by the normal test suite (matching the parent task's
explicit "never invoked automatically by an agent" instruction). These
tests only inspect its source/structure.
"""

from __future__ import annotations

import inspect
from pathlib import Path

BACKEND = Path(__file__).parent.parent


def _source() -> str:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    return inspect.getsource(module)


def test_module_imports_without_executing_the_network_flow() -> None:
    import gateway.travel.adapters.gondola.scripts.bootstrap_oauth as module

    assert module.MCP_ENDPOINT == "https://mcp.gondola.ai/mcp"


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


def test_never_logs_or_prints_a_raw_access_token() -> None:
    source = _source()
    # The only print of a token-adjacent value is the redacted expiry, never
    # access_token/refresh_token themselves.
    assert "print(tokens.access_token" not in source
    assert "print(tokens.refresh_token" not in source
    assert "print(f\"Token: " not in source


def test_stores_tokens_only_via_the_keychain_token_store() -> None:
    source = _source()
    assert "KeychainTokenStore().save(tokens)" in source
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
