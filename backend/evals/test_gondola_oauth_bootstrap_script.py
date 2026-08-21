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
